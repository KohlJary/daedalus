"""
Fast, read-only call-graph queries for the main agent (`daedalus palace callers|callees|impact|path|tests-for`).

Builds the graph straight from source on every call (about 0.3 s on an 18k-line repo) and never touches
the project's .mind-palace storage. It differs from the palace builder's graph in ways that matter for
these queries:

- Private methods and dunders are nodes. The room builder's noise filter drops them, which cuts every
  call chain that passes through a private helper.
- A class links to its __init__, so construction (`Foo()`) carries on into the constructor's calls.
- The analyzer records calls made through an object (`orch.process_pending()`) by bare name, and lists
  those names separately so the graph can tell `obj.name()` from a plain `name()`. A plain call to a name
  defined in the same module links to that definition. A call through an object links to every node
  with that name when there are at most `max_candidates` (for callers outside tests, definitions inside
  test files don't count: test doubles are injected at runtime); past the cap, only same-module definitions
  are linked, and if there are none the name is skipped and reported. This favours recall: what a
  change affects, and which tests reach it.

Recall is good where the call target is unique or nearly so. For interfaces with many implementations
(e.g. an injected `reviewer.review`), every implementation is linked, so precision is low: test lists are
a superset. Calls made through dispatch (CLI runners, callbacks) stay invisible, which is why test
selection falls back to "run the full suite" when it finds nothing.

Languages: whatever the palace's language registry analyzes. Python uses the stdlib ast; tree-sitter
grammars (installed with daedalus-cli) cover JavaScript/TypeScript, Go, Rust, Java, C#, C/C++ and Ruby,
and Razor through C# (see treesitter.py, razor.py). Test conventions (which files and symbols are tests, where a
file's tests usually live) come from each language's support class.
"""

import json
import posixpath
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from .pathfinding import CallGraph, GraphNode

from .sources import (MAX_FILE_BYTES, OTHER_SKIP_DIRS, PYTHON_EXTS, SKIP_DIRS,  # noqa: F401  (re-exported)
                      git_ignored as _git_ignored, module_id, source_files)


_LANGUAGE_CACHE: Dict[Tuple[int, str], object] = {}
_TEST_FILE_CACHE: Dict[Tuple[int, str], bool] = {}


def _language(file: str):
    """The file's language support, by extension (cached per registry; called for every call candidate)."""
    from .languages import get_language_registry
    registry = get_language_registry()
    key = (id(registry), posixpath.splitext(file)[1].lower())
    if key not in _LANGUAGE_CACHE:
        _LANGUAGE_CACHE[key] = registry.get_by_extension(Path("x" + key[1]))
    return _LANGUAGE_CACHE[key]


FAMILIES = {"TypeScript": "JavaScript", "TSX": "JavaScript", "C++": "C", "Razor": "C#"}  # languages that call each other's code


def _family(file: str) -> str:
    language = _language(file)
    name = language.name if language else "Python"
    return FAMILIES.get(name, name)


def _python_test_file(file: str) -> bool:
    name = Path(file).name
    return (file.startswith("tests/") or "/tests/" in file or name.startswith("test_")
            or name.endswith("_test.py") or name == "conftest.py")


def in_test_file(file: str) -> bool:
    """Defined in test code, by the file's language's conventions (Python: tests/, test_*.py, *_test.py,
    conftest.py; files no analyzer covers use the Python rule)."""
    from .languages import get_language_registry
    key = (id(get_language_registry()), file)
    if key not in _TEST_FILE_CACHE:
        language = _language(file)
        _TEST_FILE_CACHE[key] = (_python_test_file(file) if language is None or language.name == "Python"
                                 else language.is_test_file(file))
    return _TEST_FILE_CACHE[key]


class GitError(RuntimeError):
    """git failed (not a repository, unknown base, ...)."""


@dataclass
class QueryGraph:
    graph: CallGraph
    ambiguous_links: int = 0
    skipped: Dict[str, int] = field(default_factory=dict)  # bare name -> number of definitions (over the cap)


def _collect_nodes(project_root: Path, imports: Optional[Dict[str, dict]] = None) -> Dict[str, dict]:
    """Every function, method and class, private ones and dunders included. When `imports` is given, each
    file's import bindings are collected into it (repo-relative path -> {local name: (spec, symbol)})."""
    from .cartographer import Cartographer
    from .storage import PalaceStorage

    # analyze_file reads only source; the palace argument is used by palace-building methods
    cart = Cartographer(None, PalaceStorage(project_root))  # type: ignore[arg-type]
    raw: Dict[str, dict] = {}
    for f in source_files(project_root, cart.language_registry.supported_extensions(), ignored=_git_ignored(project_root)):
        try:
            elements, _ = cart.analyze_file(f)
        except Exception:
            continue
        rel = f.relative_to(project_root)
        module = module_id(rel)
        family = _family(str(rel))
        language = _language(str(rel))
        implicit_self = language.implicit_self if language else True
        if imports is not None and language is not None:  # every analyzed file gets an entry
            try:
                imports[rel.as_posix()] = language.file_imports(f, project_root)
            except Exception:
                imports[rel.as_posix()] = {}
        for el in elements:
            node_id = f"{module}.{el.name}"
            raw[node_id] = {"family": family, "implicit_self": implicit_self, "id": node_id, "name": el.name, "simple_name": el.simple_name or el.name.split(".")[-1],
                            "type": el.element_type, "module": module, "file": rel.as_posix(), "line": el.line,
                            "end_line": el.end_line, "attr_calls": sorted(set(el.member_calls)),
                            "is_test": el.is_test, "signature": el.signature,
                            "call_sites": [tuple(site) for site in el.call_sites],
                            "docstring": (el.docstring or "")[:200], "calls": list(el.calls)}
    return raw


def build_query_graph(project_root: Path, max_candidates: int = 10) -> QueryGraph:
    """Build a call graph from source, without reading or writing palace storage."""
    project_root = Path(project_root).resolve()
    imports: Dict[str, dict] = {}
    raw = _collect_nodes(project_root, imports)
    resolver = ImportResolver(raw, imports, project_root)

    by_simple: Dict[str, List[str]] = {}
    for node_id, node in raw.items():
        by_simple.setdefault(node["simple_name"], []).append(node_id)

    resolved: Dict[str, Set[str]] = {}
    ambiguous, skipped = 0, {}
    for node_id, node in raw.items():
        targets: Set[str] = set()
        for call in node.get("calls", []):
            if call in raw:
                targets.add(call)
                continue
            # Imports decide what they can: `from x import f; f()`, `mod.f()`, `pkg.F()`. A call bound to
            # code outside the project (json.dumps, fmt.Println) links to nothing. Calls through variables,
            # self, or expressions fall through to the name-based rules below.
            decided, undecided = resolver.resolve_call(node, call)
            targets.update(decided)
            if not undecided:
                continue
            through_object = call.split(".")[-1] in node.get("attr_calls", ())
            local = f"{node['module']}.{call}"
            if local in raw and not through_object:  # a plain call: the module's own definition is the target
                targets.add(local)
                continue
            # A name only resolves within its own language family: JS `path.resolve()` is not Python's resolve
            candidates = [c for c in by_simple.get(call.split(".")[-1], []) if raw[c]["family"] == node["family"]]
            if not through_object and not node["implicit_self"]:
                # Go/JS/Rust: a plain call reaches functions only (`append(...)` is not History.append)
                candidates = [c for c in candidates if raw[c]["type"] != "method"]
            if not in_test_file(node["file"]):
                # Production code never calls into test files statically; test doubles are injected at runtime
                candidates = [c for c in candidates if not in_test_file(raw[c]["file"])]
            if 0 < len(candidates) <= max_candidates:
                targets.update(candidates)
                ambiguous += len(candidates) > 1
            elif candidates:
                same_module = [c for c in candidates if raw[c]["module"] == node["module"]]
                if same_module:
                    targets.update(same_module)
                else:
                    skipped[call.split(".")[-1]] = len(candidates)
        resolved[node_id] = targets
    for node_id, node in raw.items():  # Foo() carries on into its constructor (Foo.__init__, Foo.constructor, ...)
        if node["type"] == "class":
            language = _language(node["file"])
            for ctor in (language.constructor_of(node["simple_name"]) if language else ("__init__",)):
                if f"{node_id}.{ctor}" in raw:
                    resolved[node_id].add(f"{node_id}.{ctor}")

    graph = CallGraph()
    for node_id, node in raw.items():
        outgoing = sorted(t for t in resolved[node_id] if t != node_id)
        graph.nodes[node_id] = GraphNode.from_dict({**node, "calls": outgoing, "called_by": []})
    for node_id, node in graph.nodes.items():
        for t in node.calls:
            graph.nodes[t].called_by.append(node_id)
        graph.modules.setdefault(node.module, []).append(node_id)
    graph.project = project_root.name
    graph.end_lines = {nid: n.get("end_line") for nid, n in raw.items()}  # type: ignore[attr-defined]
    graph.raw_calls = {nid: list(n.get("calls", [])) for nid, n in raw.items()}  # type: ignore[attr-defined]
    return QueryGraph(graph=graph, ambiguous_links=ambiguous, skipped=skipped)


JS_EXTS = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".mts", ".cts")
NODE_BUILTINS = {"assert", "buffer", "child_process", "cluster", "crypto", "dgram", "dns", "events", "fs", "http",
                 "http2", "https", "net", "os", "path", "perf_hooks", "process", "querystring", "readline",
                 "stream", "string_decoder", "timers", "tls", "tty", "url", "util", "v8", "vm", "worker_threads",
                 "zlib"}


class ImportResolver:
    """Maps import bindings (from each language's file_imports) to graph nodes.

    A lookup answers None when imports don't decide the call (no binding, an ambiguous module, a name the
    module doesn't define), an empty set when the binding points outside the project, and node ids otherwise.
    """

    def __init__(self, raw: Dict[str, dict], imports: Dict[str, dict], project_root: Path):
        self.raw = raw
        self.imports = imports
        # Every analyzed file is a module, definitions or not (an __init__.py that only re-exports still
        # makes its package part of the project, not an external import)
        self.module_file: Dict[str, str] = {module_id(Path(f)): f for f in imports}
        for node in raw.values():
            self.module_file.setdefault(node["module"], node["file"])
        self.file_module = {f: m for m, f in self.module_file.items()}
        self.py_suffix: Dict[str, List[str]] = {}
        self.py_dirs: Set[str] = set()  # dotted suffixes of every directory holding Python (namespace packages too)
        self.dir_modules: Dict[str, List[str]] = {}
        for m, f in self.module_file.items():
            if f.endswith(PYTHON_EXTS):
                parts = m.split(".")
                for i in range(len(parts)):
                    self.py_suffix.setdefault(".".join(parts[i:]), []).append(m)
                dirs = posixpath.dirname(f).split("/") if posixpath.dirname(f) else []
                for end in range(1, len(dirs) + 1):
                    for start in range(end):
                        self.py_dirs.add(".".join(dirs[start:end]))
            self.dir_modules.setdefault(posixpath.dirname(f), []).append(m)
        self.go_mods = self._go_modules(project_root)
        self.npm_packages = self._npm_packages(project_root)
        # C#: types by (namespace, name), partial classes across files included, and global usings
        self.cs_types: Dict[Tuple[str, str], List[str]] = {}
        self.cs_global: Set[str] = set()
        for f, bindings in imports.items():
            if f.endswith(".cs"):
                self.cs_global |= {k.split(":", 1)[1] for k in bindings if k.startswith("global:")}
        for node_id, node in raw.items():
            if node["file"].endswith(".cs") and node["type"] == "class":
                ns = self._cs_namespace(node["file"])
                self.cs_types.setdefault((ns, node["simple_name"]), []).append(node_id)
        self.cs_type_names = {name for _, name in self.cs_types}
        self.file_nodes: Dict[str, List[str]] = {}
        for node_id, node in raw.items():
            self.file_nodes.setdefault(node["file"], []).append(node_id)

    def _cs_namespace(self, file: str) -> str:
        return self.imports.get(file, {}).get("__namespace__", ("cs:", None))[0][3:]

    def _cs_visible(self, file: str) -> List[str]:
        """Namespaces a C# file sees: its own and every enclosing one, its usings, the project's global usings."""
        ns = self._cs_namespace(file)
        parts = ns.split(".") if ns else []
        chain = [".".join(parts[:i]) for i in range(len(parts), -1, -1)]
        usings = [k.split(":", 1)[1] for k in self.imports.get(file, {}) if k.startswith("using:")]
        return list(dict.fromkeys([*chain, *usings, *sorted(self.cs_global)]))

    def _cs_types(self, file: str, name: str) -> List[str]:
        binding = self.imports.get(file, {}).get(name)
        if binding is not None and binding[0].startswith("cs:") and binding[1]:  # using Alias = A.B.Type;
            return self.cs_types.get((binding[0][3:], binding[1]), [])
        return [t for ns in self._cs_visible(file) for t in self.cs_types.get((ns, name), [])]

    def _resolve_cs(self, node: dict, qualifier: str, call: str) -> Optional[Set[str]]:
        """A type name the file can see: `new Foo()` -> Foo, `Foo.Bar()` -> Foo.Bar (any partial). Anything
        else (a variable, an inherited method, a type it can't see) is left to the name-based rules."""
        if qualifier == "":
            # `Total()` may be the enclosing class's own method rather than `new Total()`: when the file defines
            # a method of that name, leave it to the name-based rules (which link both)
            if any(self.raw[n]["file"] == node["file"] and self.raw[n]["simple_name"] == call
                   and self.raw[n]["type"] == "method" for n in self.file_nodes.get(node["file"], ())):
                return None
            types = self._cs_types(node["file"], call) if call in self.cs_type_names else []
            return set(types) or None
        if qualifier in ("?", "self"):
            return None
        hits = {f"{t}.{call}" for t in self._cs_types(node["file"], qualifier) if f"{t}.{call}" in self.raw}
        return hits or None

    def _go_modules(self, project_root: Path) -> List[Tuple[str, str]]:
        """(directory, module path) for each go.mod above a Go file, nearest first."""
        found: Dict[str, str] = {}
        for d in {posixpath.dirname(f) for f in self.module_file.values() if f.endswith(".go")}:
            parts = d.split("/") if d else []
            for i in range(len(parts), -1, -1):
                rel = "/".join(parts[:i])
                if rel in found:
                    break
                gomod = project_root / rel / "go.mod"
                if gomod.is_file():
                    m = re.search(r"^module\s+(\S+)", gomod.read_text(errors="replace"), re.MULTILINE)
                    if m:
                        found[rel] = m.group(1)
                    break
        return sorted(found.items(), key=lambda kv: -len(kv[0]))

    def _npm_packages(self, project_root: Path) -> Set[str]:
        """Dependency names from the package.json files above the project's JS/TS files."""
        names: Set[str] = set()
        seen: Set[str] = set()
        for f in self.module_file.values():
            if not f.endswith(JS_EXTS):
                continue
            parts = posixpath.dirname(f).split("/") if posixpath.dirname(f) else []
            for i in range(len(parts), -1, -1):
                d = "/".join(parts[:i])
                if d in seen:
                    break
                seen.add(d)
                pkg = project_root / d / "package.json"
                if pkg.is_file():
                    try:
                        data = json.loads(pkg.read_text())
                    except (OSError, ValueError):
                        continue
                    for key in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
                        names |= set((data.get(key) or {}).keys())
        return names

    def _external_js(self, spec: str) -> bool:
        """A bare import is a package only when a package.json depends on it (or it's a Node builtin);
        anything else may be a tsconfig path alias or a workspace package, so imports don't decide it."""
        if spec.startswith("node:") or spec.split("/")[0] in NODE_BUILTINS:
            return True
        name = "/".join(spec.split("/")[:2]) if spec.startswith("@") else spec.split("/")[0]
        return name in self.npm_packages

    def modules_for(self, spec: str, importer: str) -> Optional[List[str]]:
        kind, _, value = spec.partition(":")
        if kind == "ext":
            if importer.endswith(JS_EXTS) and not self._external_js(value):
                return None
            return []
        if kind == "py":
            candidates = set(self.py_suffix.get(value, [])) | set(self.py_suffix.get(value + ".__init__", []))
            if not candidates:
                # A directory without __init__.py (a namespace package) is still the project's
                return None if value in self.py_dirs else []
            if len(candidates) == 1:
                return sorted(candidates)
            # Several files match (config.py at the root and in app/): an absolute import names the one whose
            # dotted path is exactly the spec; otherwise imports don't decide
            exact = [c for c in candidates if c in (value, value + ".__init__")]
            return exact if len(exact) == 1 else None
        if kind == "js":
            stem = value
            for ext in JS_EXTS:  # './x.js' in TypeScript ESM means x.ts
                if stem.endswith(ext):
                    stem = stem[: -len(ext)]
                    break
            for candidate in [stem + e for e in JS_EXTS] + [stem + "/index" + e for e in JS_EXTS]:
                if candidate in self.file_module:
                    return [self.file_module[candidate]]
            return None  # a relative import we can't see (generated, or an asset)
        if kind == "go":
            for directory, module_path in self.go_mods:
                if value == module_path or value.startswith(module_path + "/"):
                    rel = posixpath.normpath(posixpath.join(directory, value[len(module_path):].lstrip("/")))
                    rel = "" if rel == "." else rel
                    return sorted(m for m in self.dir_modules.get(rel, []) if self.module_file[m].endswith(".go")) or None
            return []  # standard library or a dependency
        if kind == "java":
            suffix = value + ".java"
            hits = [m for m, f in self.module_file.items() if f == suffix or f.endswith("/" + suffix)]
            if len(hits) > 1:
                return None
            if not hits:
                # com.x.Outer.Inner (a nested class) or anything under one of the project's packages: not
                # external, just not a file of its own
                parts = value.split("/")
                package = "/".join(parts[:-1])
                files = list(self.module_file.values())
                if any(posixpath.dirname(f) == package or posixpath.dirname(f).endswith("/" + package) for f in files):
                    return None  # a class of a project package we don't see a file for
                for i in range(len(parts) - 1, 1, -1):  # com.x.Outer.Inner lives in com/x/Outer.java
                    outer = "/".join(parts[:i]) + ".java"
                    if any(f == outer or f.endswith("/" + outer) for f in files):
                        return None
            return hits
        return None

    def symbol(self, spec: str, sym: str, local: str, importer: str, depth: int = 0) -> Optional[Set[str]]:
        """Nodes an imported symbol names: a definition, or one re-exported through the module's own imports."""
        if spec.startswith("py:"):  # from pkg import submodule: the submodule itself, not a name in pkg
            submodules = self.modules_for(f"{spec}.{sym}", importer)
            if submodules:
                return set(submodules)
        modules = self.modules_for(spec, importer)
        if modules is None:
            return None
        if not modules:
            return set()
        name = local if sym == "default" else sym
        hits = {f"{m}.{name}" for m in modules if f"{m}.{name}" in self.raw}
        if hits:
            return hits
        if depth < 3:  # from pkg import f, where pkg/__init__.py itself imports f
            for m in modules:
                binding = self.imports.get(self.module_file[m], {}).get(sym)
                if binding and binding[1] is not None:
                    found = self.symbol(binding[0], binding[1], sym, self.module_file[m], depth + 1)
                    if found:
                        return found
        return None

    def resolve_call(self, node: dict, call: str) -> Tuple[Set[str], bool]:
        """(targets the imports decide, whether any call site is left to the name-based rules)."""
        sites = {q for q, n in node.get("call_sites", ()) if n == call}
        if not sites:
            return set(), True
        imports = self.imports.get(node["file"], {})
        decided: Set[str] = set()
        undecided = False
        for qualifier in sites:
            result = None
            if node["file"].endswith(".cs"):
                result = self._resolve_cs(node, qualifier, call)
            elif qualifier == "":
                binding = imports.get(call)
                # A same-file definition of the name may shadow the import (or be shadowed): undecided
                if binding and binding[1] is not None and f"{node['module']}.{call}" not in self.raw:
                    result = self.symbol(binding[0], binding[1], call, node["file"])
                    if result and all(r in self.module_file for r in result):
                        result = None  # it names a module (from pkg import mod), and calling a module isn't a call
            elif qualifier not in ("?", "self") and qualifier in imports:
                spec, sym = imports[qualifier]
                if sym is None:  # a module or package: mod.f(), pkg.F()
                    modules = self.modules_for(spec, node["file"])
                    if modules is not None:
                        hits = {f"{m}.{call}" for m in modules if f"{m}.{call}" in self.raw}
                        result = hits if (hits or not modules) else None
                else:  # an imported class (Foo.bar()), or a submodule (from pkg import mod; mod.f())
                    owners = self.symbol(spec, sym, qualifier, node["file"])
                    if owners is not None:
                        hits = {f"{o}.{call}" for o in owners if f"{o}.{call}" in self.raw}
                        result = hits if (hits or not owners) else None
            if result is None:
                undecided = True
            else:
                decided |= result
        return decided, undecided


def resolve_symbol(graph: CallGraph, symbol: str) -> List[str]:
    """Node ids matching a symbol: an exact id, a dotted suffix (Class.method), or a simple name."""
    if symbol in graph.nodes:
        return [symbol]
    suffix = [n for n in graph.nodes if n.endswith("." + symbol)]
    if suffix:
        return sorted(suffix)
    return sorted(n for n, node in graph.nodes.items() if node.simple_name == symbol)


def is_test_node(node: GraphNode) -> bool:
    if node.is_test is not None:  # the language's analyzer decided
        return node.is_test
    name = Path(node.file).name
    return (node.file.startswith("tests/") or "/tests/" in node.file or name.startswith("test_")) and \
        node.simple_name.startswith("test")


def reach(graph: CallGraph, node_ids: List[str], direction: str = "backward", max_depth: int = 6) -> Dict[str, int]:
    """Nodes reachable from any of node_ids (callers when backward), with their distance."""
    best: Dict[str, int] = {}
    for nid in node_ids:
        for other, depth in graph.bfs(nid, direction=direction, max_depth=max_depth).items():
            if other not in node_ids and (other not in best or depth < best[other]):
                best[other] = depth
    return best


def tests_reaching(graph: CallGraph, node_ids: List[str], max_depth: int = 6) -> List[str]:
    hits = [n for n in reach(graph, node_ids, "backward", max_depth) if is_test_node(graph.nodes[n])]
    hits += [n for n in node_ids if is_test_node(graph.nodes[n])]
    return sorted(set(hits))


def convention_tests(project_root: Path, files: List[str]) -> List[str]:
    """Conventional test files for the given source files (Python: tests/test_<stem>.py; Go: <stem>_test.go;
    TypeScript: <stem>.test.ts, ...), when they exist."""
    out = []
    for f in files:
        language = _language(f)
        candidates = language.test_file_candidates(f) if language else [str(Path("tests") / f"test_{Path(f).stem}.py")]
        out.extend(c for c in candidates if c != f and (Path(project_root) / c).exists())
    return sorted(set(out))


def nodes_in_file(graph: CallGraph, rel_path: str) -> List[str]:
    rel_path = str(Path(rel_path))
    return sorted(n for n, node in graph.nodes.items() if node.file == rel_path)


def _spans(graph: CallGraph) -> Dict[str, List[Tuple[int, int, str]]]:
    """Per file: (start, end, node_id). End lines are exact where the analyzer knows them (Python, tree-sitter);
    otherwise up to the next node's start."""
    end_lines = getattr(graph, "end_lines", {})
    per_file: Dict[str, List[GraphNode]] = {}
    for node in graph.nodes.values():
        per_file.setdefault(node.file, []).append(node)
    spans = {}
    for f, nodes in per_file.items():
        nodes.sort(key=lambda n: n.line)
        out = []
        for i, n in enumerate(nodes):
            end = end_lines.get(n.id) or ((nodes[i + 1].line - 1) if i + 1 < len(nodes) else 10 ** 9)
            out.append((n.line, end, n.id))
        spans[f] = out
    return spans


def _git(project_root: Path, *args: str) -> str:
    r = subprocess.run(["git", *args], cwd=project_root, capture_output=True, text=True)
    if r.returncode != 0:
        raise GitError(r.stderr.strip() or f"git {' '.join(args)} failed")
    return r.stdout


def changed_lines_from_diff(diff_text: str) -> Dict[str, Set[int]]:
    """New-side line numbers each file's hunks touch (`git diff -U0` or any unified diff). A pure deletion
    counts the line it happened at, so the definition it was cut from still registers."""
    changed: Dict[str, Set[int]] = {}
    current = None
    for line in diff_text.splitlines():
        if line.startswith("+++ "):
            current = line[6:] if line.startswith("+++ b/") else None
        elif line.startswith("@@") and current:
            m = re.match(r"@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@", line)
            if m:
                start, count = int(m.group(1)), int(m.group(2) if m.group(2) is not None else 1)
                changed.setdefault(current, set()).update(range(start, start + max(count, 1)))
    return changed


def nodes_for_lines(graph: CallGraph, changed: Dict[str, Set[int]]) -> Dict[str, List[str]]:
    """Each changed line maps to the innermost def/class containing it; lines outside any def touch nothing."""
    spans = _spans(graph)
    out: Dict[str, List[str]] = {}
    for f, lines in changed.items():
        hits = set()
        for ln in lines:
            containing = [(b - a, nid) for (a, b, nid) in spans.get(f, []) if a <= ln <= b]
            if containing:
                hits.add(min(containing)[1])
        if hits:
            out[f] = sorted(hits)
    return out


def changed_nodes(graph: CallGraph, project_root: Path, base: str = "HEAD") -> Dict[str, List[str]]:
    """Nodes touched by the working tree's changes against `base`: each changed line maps to the innermost
    def/class containing it (lines outside any def touch nothing); new untracked files count whole."""
    project_root = Path(project_root)
    diff = _git(project_root, "diff", "-U0", "--find-renames", base)
    untracked = _git(project_root, "ls-files", "--others", "--exclude-standard").split()
    out = nodes_for_lines(graph, changed_lines_from_diff(diff))
    for f in untracked:
        if nodes_in_file(graph, f):
            out[f] = nodes_in_file(graph, f)
    return out


def project_root_for(cwd: Path) -> Path:
    """The git work tree root when inside one (git reports repo-relative paths), else cwd."""
    try:
        return Path(_git(Path(cwd), "rev-parse", "--show-toplevel").strip())
    except (GitError, FileNotFoundError):
        return Path(cwd).resolve()
