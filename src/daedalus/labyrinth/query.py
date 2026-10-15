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
import logging
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
                            "receiver_types": dict(el.receiver_types), "bases": list(el.bases),
                            "extension_method": el.extension_method, "element_types": dict(el.element_types),
                            "decorators": list(el.decorators), "generic_bases": list(el.generic_bases),
                            "messages": [tuple(m) for m in el.messages], "dispatch_calls": dict(el.dispatch_calls),
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
    framework_labels: Dict[Tuple[str, str], str] = {}
    for node_id, node in raw.items():  # Foo() carries on into its constructor (Foo.__init__, Foo.constructor, ...)
        if node["type"] == "class":
            language = _language(node["file"])
            for ctor in (language.constructor_of(node["simple_name"]) if language else ("__init__",)):
                if f"{node_id}.{ctor}" in raw:
                    resolved[node_id].add(f"{node_id}.{ctor}")
            # Methods the framework calls on an instance: a test that only constructs the class still runs
            # them. Only where that's certain (C#): `override`s, and the message methods of a framework base
            # the class names (MonoBehaviour's Update, ComponentBase's OnInitializedAsync, IDisposable's
            # Dispose). Python classes already carry their methods' calls.
            if language is not None and language.name in ("C#", "Razor"):
                called = _framework_called(node_id, node, raw)
                resolved[node_id] |= called
                for target in called:
                    framework_labels[(node_id, target)] = "framework: " + (
                        "override" if re.search(r"\boverride\b", raw[target].get("signature", "")) else "lifecycle")

    labels = {**framework_labels, **_dispatch_edges(raw, resolved, resolver),
              **_config_dispatch(raw, resolved, project_root)}

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
    # Edges a framework makes rather than a direct call: (caller, callee) -> "MediatR Send", "Hangfire Enqueue",
    # "Celery delay", "framework: override" (issue #47). They count like any edge; output marks them.
    graph.edge_labels = {k: v for k, v in labels.items() if k[1] in graph.nodes.get(k[0], GraphNode.from_dict({})).calls}  # type: ignore[attr-defined]
    return QueryGraph(graph=graph, ambiguous_links=ambiguous, skipped=skipped)


JS_EXTS = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".mts", ".cts")
# Methods whose lambda gets the mocked type: Moq's Mock<T>.Setup(x => x.Find(1)) and friends
MOQ_LAMBDA_METHODS = {"Setup", "SetupGet", "SetupSet", "SetupSequence", "SetupProperty", "Verify", "VerifyGet",
                      "VerifySet", "Callback", "Raise"}
# Methods whose lambda gets a collection's element: orders.Where(o => o.IsPaid())
SEQUENCE_LAMBDA_METHODS = {"Where", "Select", "SelectMany", "Any", "All", "First", "FirstOrDefault", "Single",
                           "SingleOrDefault", "Last", "LastOrDefault", "Count", "LongCount", "OrderBy",
                           "OrderByDescending", "ThenBy", "ThenByDescending", "GroupBy", "ToDictionary", "ToLookup",
                           "Sum", "Min", "Max", "Average", "MinBy", "MaxBy", "DistinctBy", "TakeWhile", "SkipWhile",
                           "ForEach", "Find", "FindAll", "FindIndex", "FindLast", "Exists", "TrueForAll", "RemoveAll",
                           "Aggregate", "Zip", "Join", "GroupJoin", "Contains"}
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
        # C# class hierarchy by simple name (bases are written as simple names), and extension methods,
        # which make a call on an outside type land in the project
        self.cs_children: Dict[str, Set[str]] = {}
        self.cs_parents: Dict[str, Set[str]] = {}
        self.cs_by_name: Dict[str, List[str]] = {}
        self.cs_extensions: Set[str] = set()
        # Every name a C# file declares as a type, whatever the analyzer made of it (enums, delegates, ...)
        self.cs_declared_names: Set[str] = set()
        for f in imports:
            if f.endswith((".cs", ".razor", ".cshtml")):
                try:
                    text = (project_root / f).read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                self.cs_declared_names |= set(re.findall(
                    r"\b(?:class|interface|struct|record|enum|delegate\s+\S+)\s+([A-Z_]\w*)", text))
        for node_id, node in raw.items():
            if not node["file"].endswith(".cs"):
                continue
            if node["type"] == "class":
                self.cs_by_name.setdefault(node["simple_name"], []).append(node_id)
                for base in node.get("bases", ()):
                    self.cs_parents.setdefault(node["simple_name"], set()).add(base)
                    self.cs_children.setdefault(base, set()).add(node["simple_name"])
            elif node.get("extension_method"):
                self.cs_extensions.add(node["simple_name"])

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

    def _cs_walk(self, names: Set[str], edges: Dict[str, Set[str]]) -> List[str]:
        """Type names reachable along `edges` (parents or children), nearest first."""
        order, seen, frontier = [], set(names), list(names)
        while frontier:
            nxt = []
            for name in frontier:
                for other in sorted(edges.get(name, ())):
                    if other not in seen:
                        seen.add(other)
                        order.append(other)
                        nxt.append(other)
            frontier = nxt
        return order

    def _cs_method_targets(self, type_ids: List[str], call: str) -> Set[str]:
        """What `x.Call()` can run when x is declared as one of type_ids: the type's own Call and every
        override or implementation in its descendants; when the type doesn't define Call, the nearest
        ancestor's (an inherited method). An interface method isn't a target of a call through a class."""
        names = {self.raw[t]["simple_name"] for t in type_ids}
        own = {f"{t}.{call}" for t in type_ids if f"{t}.{call}" in self.raw}
        below = {f"{t}.{call}" for n in self._cs_walk(names, self.cs_children) for t in self.cs_by_name.get(n, ())
                 if f"{t}.{call}" in self.raw}
        # The nearest ancestor defining the name is a target too: either the method is inherited, or the
        # type's own Call is an overload of it (node ids carry no signature, so arguments can't tell them
        # apart). Interfaces above a concrete type are left out: a call through a class doesn't call them.
        for ancestor in self._cs_walk(names, self.cs_parents):
            inherited = {f"{t}.{call}" for t in self.cs_by_name.get(ancestor, ()) if f"{t}.{call}" in self.raw
                         and not (own and self._cs_is_interface(t))}
            if inherited:
                return own | inherited | below
        return own | below

    def _cs_is_interface(self, type_id: str) -> bool:
        return re.search(r"\binterface\b", self.raw[type_id].get("signature", "").split("{")[0]) is not None

    def _resolve_cs_receiver(self, node: dict, receiver: str, call: str) -> Optional[Set[str]]:
        """`inventory.Find()` where `inventory` is declared `IInventoryStore`: that interface's Find and the
        Find of every type in its hierarchy. A declared type outside the project links nothing, unless the
        project has an extension method of that name. Anything uncertain is left to the name-based rules."""
        return self._resolve_cs_type(node, node.get("receiver_types", {}).get(receiver), call)

    def _resolve_cs_element(self, node: dict, qualifier: str, call: str) -> Optional[Set[str]]:
        """Calls on what a mock or a collection hands to a lambda, or on mock.Object:
        `_inventory.Setup(s => s.Find(42))` with `Mock<IInventoryStore> _inventory` -> IInventoryStore.Find;
        `orders.Where(o => o.IsPaid())` with `List<Order> orders` -> Order.IsPaid."""
        kind, _, rest = qualifier.partition(":")
        if kind == "mockobj":
            receiver, method = rest, None
        else:
            receiver, _, method = rest.rpartition(":")
        element = node.get("element_types", {}).get(receiver, "")
        holder, _, type_name = element.partition(":")
        if not type_name:
            return None
        if holder == "mock" and (method is None or method in MOQ_LAMBDA_METHODS):
            return self._resolve_cs_type(node, type_name, call)
        if holder == "seq" and method in SEQUENCE_LAMBDA_METHODS:
            return self._resolve_cs_type(node, type_name, call)
        return None

    def _resolve_cs_type(self, node: dict, type_name: Optional[str], call: str) -> Optional[Set[str]]:
        if not type_name:
            return None
        if "." in type_name:  # written qualified: System.Threading.Tasks.Task, Shop.Billing.Money
            namespace, _, simple = type_name.rpartition(".")
            types = list(self.cs_types.get((namespace, simple), []))
            if not types and namespace.split(".")[-1] in self.cs_type_names:
                types = list(self.cs_by_name.get(simple, []))  # Outer.Node: a nested type, not a namespace
                if not types:
                    return None
            if not types:
                if any(ns == namespace or ns.startswith(namespace + ".") for ns, _ in self.cs_types):
                    return None  # a project namespace: the type is ours, we just didn't index it
                return None if call in self.cs_extensions else set()  # System.Threading.Tasks.Task: not ours
        else:
            simple = type_name
            types = self._cs_types(node["file"], type_name)
        if not types:
            if simple in self.cs_type_names or call in self.cs_extensions or simple in self.cs_declared_names:
                return None  # a project type this file doesn't see by its usings, or an extension method
            return set()  # ILogger.LogInformation, List.Add: not the project's code
        return self._cs_method_targets(types, call) or None

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
        if qualifier.startswith("self."):  # this._orders.Find(): the field, even if a local shares its name
            return self._resolve_cs_receiver(node, qualifier, call)
        if qualifier.startswith(("lambda:", "mockobj:")):
            return self._resolve_cs_element(node, qualifier, call)
        if qualifier.startswith("lambdatype:"):  # Enqueue<IInvoiceMailer>(m => m.SendOverdue())
            # A generic argument types the lambda only for certain when it's a project type: for ConvertAll<Uri>
            # or AddSingleton<IExternal> it says nothing about what the lambda's parameter is
            type_name = qualifier.split(":", 1)[1]
            if not self._cs_types(node["file"], type_name):
                return None
            return self._resolve_cs_type(node, type_name, call)
        if qualifier in node.get("receiver_types", {}):  # a parameter, local, field or property
            return self._resolve_cs_receiver(node, qualifier, call)
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


# Message handlers: generic interface -> the methods the bus calls with a message of the type argument
HANDLER_INTERFACES = {
    "IRequestHandler": ("Handle",), "INotificationHandler": ("Handle",), "IStreamRequestHandler": ("Handle",),  # MediatR
    "IConsumer": ("Consume",),                                                                                  # MassTransit
    "IHandleMessages": ("Handle",), "IHandleTimeouts": ("Timeout",),                                            # NServiceBus
    "IEventHandler": ("Handle", "HandleAsync"), "ICommandHandler": ("Handle", "HandleAsync"),
    "IMessageHandler": ("Handle", "HandleAsync"), "IIntegrationEventHandler": ("Handle", "HandleAsync"),
}
BUS_NAMES = {"Send": "Send", "SendAsync": "Send", "Publish": "Publish", "PublishAsync": "Publish",
             "SendLocal": "SendLocal", "CreateStream": "CreateStream", "Request": "Request",
             "Schedule": "Schedule", "SchedulePublish": "Schedule", "ScheduleSend": "Schedule"}
CELERY_CALLS = {"delay", "apply_async", "s", "si", "signature", "apply"}


# Receivers whose Send/Publish is a message bus (anything declared as an outside type not in this list, such
# as SmtpClient or HttpClient, isn't one; an undeclared or project-typed receiver may be)
BUS_RECEIVERS = {"IMediator", "ISender", "IPublisher", "Mediator", "IBus", "IBusControl", "IPublishEndpoint",
                 "ISendEndpoint", "ISendEndpointProvider", "IRequestClient", "ConsumeContext", "IMessageSession",
                 "IMessageHandlerContext", "IEndpointInstance", "IPipelineContext", "IMessageBus", "ICapPublisher",
                 "IMessageBroker", "IEventBus", "ICommandBus", "IServiceBus"}


def _dispatch_edges(raw: Dict[str, dict], resolved: Dict[str, Set[str]], resolver: "ImportResolver") -> Dict[Tuple[str, str], str]:
    """Edges across framework dispatch (issue #47), added to `resolved`; returns their labels.

    - Message buses (MediatR, MassTransit, NServiceBus, ...): a method that sends or publishes a ShipOrder
      reaches the Handle/Consume of every class implementing a handler interface for that ShipOrder (the
      type each side sees through its namespace and usings), and the overrides in their subclasses.
    - Hangfire: calls made only inside an Enqueue/Schedule lambda are labelled as dispatch.
    - Celery: task.delay(...) / apply_async / .s() reaches the @task function, also as module.task.delay.
    An edge that is also a direct call keeps no label: it's a call either way.
    """
    direct = {node_id: set(targets) for node_id, targets in resolved.items()}
    labels: Dict[Tuple[str, str], str] = {}

    def link(src: str, dst: str, label: str) -> None:
        resolved[src].add(dst)
        if dst not in direct.get(src, ()):
            labels[(src, dst)] = label

    def message_types(file: str, name: str) -> Set[str]:
        """The project type a C# file means by `name` (by its namespace and usings), or by name elsewhere."""
        if file.endswith(".cs"):
            return set(resolver._cs_types(file, name))
        return set(resolver.cs_by_name.get(name, ()))

    handlers: Dict[str, List[Tuple[str, str]]] = {}  # message type node id -> [(handler method id, interface)]
    for node_id, node in raw.items():
        for entry in node.get("generic_bases", ()):
            interface, _, message = entry.partition(":")
            if interface not in HANDLER_INTERFACES:
                continue
            owners = [node_id] + [c for n in resolver._cs_walk({node["simple_name"]}, resolver.cs_children)
                                  for c in resolver.cs_by_name.get(n, ())]
            for message_id in message_types(node["file"], message):
                for owner in owners:  # the handler and the overrides in its subclasses
                    for method in HANDLER_INTERFACES[interface]:
                        for candidate in (f"{owner}.{method}", f"{owner}.{method}Async"):
                            if candidate in raw:
                                handlers.setdefault(message_id, []).append((candidate, interface))
    for node_id, node in raw.items():
        types = node.get("receiver_types", {})
        for message_entry in node.get("messages", ()):
            method, message, receiver = (tuple(message_entry) + ("",))[:3]
            declared = types.get(receiver, "").split(".")[-1]
            if declared and declared not in BUS_RECEIVERS and not resolver.cs_by_name.get(declared):
                continue  # smtp.Send(new MailMessage()): an outside type that isn't a bus
            for message_id in message_types(node["file"], message):
                for handler, interface in handlers.get(message_id, ()):
                    link(node_id, handler, f"{BUS_NAMES.get(method, method)} {message} -> {interface}")
        for name, label in node.get("dispatch_calls", {}).items():
            for target in resolved.get(node_id, ()):
                if raw[target]["simple_name"] == name:
                    labels[(node_id, target)] = label
        if node["file"].endswith(PYTHON_EXTS):
            for qualifier, call in node.get("call_sites", ()):
                if call in CELERY_CALLS and qualifier not in ("", "?", "self"):
                    for task in _celery_tasks(node, qualifier, raw, resolver):
                        link(node_id, task, f"Celery {call}")
    return labels


def dispatch_rules(project_root: Path) -> List[dict]:
    """In-house dispatch rules from the project's .daedalus/config.json, under palace.dispatch:

        {"publish": "JobQueue.Publish", "to": "enclosing:IJobHandler.CreateInstance"}
            a call to JobQueue.Publish reaches CreateInstance on the caller's own class (which implements
            IJobHandler); "to": "Type.Method" instead reaches Method on every class implementing Type.
        {"factory": "IJobHandler.CreateInstance", "entry": "JobInstance.Run"}
            a CreateInstance (on a class implementing IJobHandler) reaches Run on every class it constructs
            that derives from JobInstance.

    Rules shared with the team live in .daedalus/dispatch.json (committed: a list of rules, or
    {"dispatch": [...]}); .daedalus/config.json's palace.dispatch adds local ones. Each may carry a
    "label" for the output. Malformed rules are skipped with a warning."""
    return [r for r in all_dispatch_rules(project_root) if _rule_ok(r, warn=True)]


def all_dispatch_rules(project_root: Path) -> List:
    """Every configured rule as written, valid or not: the shared file's, then the local config's."""
    from ..config import load_project_overrides
    rules: List = []
    shared = Path(project_root) / ".daedalus" / "dispatch.json"
    if shared.is_file():
        try:
            data = json.loads(shared.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = None
        data = data.get("dispatch") if isinstance(data, dict) else data
        rules += data if isinstance(data, list) else [{"invalid_file": str(shared)}]
    local = (load_project_overrides(Path(project_root)).get("palace") or {}).get("dispatch") or []
    rules += local if isinstance(local, list) else [{"invalid": "palace.dispatch is not a list"}]
    return rules


def _rule_ok(rule, warn: bool = False) -> bool:
    ok = isinstance(rule, dict) and (
        (_dotted(rule.get("publish")) and isinstance(rule.get("to"), str) and _dotted(rule["to"].split(":", 1)[-1]))
        or (_dotted(rule.get("factory")) and _dotted(rule.get("entry"))))
    if not ok and warn:
        logging.getLogger(__name__).warning(f"palace.dispatch: skipping malformed rule {rule!r}")
    return bool(ok)


def _dotted(value) -> bool:
    return isinstance(value, str) and "." in value and all(value.split("."))


def _config_dispatch(raw: Dict[str, dict], resolved: Dict[str, Set[str]], project_root: Path) -> Dict[Tuple[str, str], str]:
    """Edges from the project's palace.dispatch rules (see dispatch_rules)."""
    rules = dispatch_rules(project_root)
    if not rules:
        return {}
    classes: Dict[str, List[str]] = {}
    parents: Dict[str, Set[str]] = {}
    for node_id, node in raw.items():
        if node["type"] == "class":
            classes.setdefault(node["simple_name"], []).append(node_id)
            parents.setdefault(node["simple_name"], set()).update(b.split(".")[-1] for b in node.get("bases", ()))

    def is_a(name: str, base: str) -> bool:
        seen, todo = set(), [name]
        while todo:
            current = todo.pop()
            if current == base:
                return True
            if current not in seen:
                seen.add(current)
                todo.extend(parents.get(current, ()))
        return False

    def owner(node_id: str) -> Optional[str]:
        """The class a method belongs to."""
        parent = node_id.rsplit(".", 1)[0]
        return parent if raw.get(parent, {}).get("type") == "class" else None

    labels: Dict[Tuple[str, str], str] = {}
    for rule in rules:
        if "publish" in rule:
            type_name, method = rule["publish"].rsplit(".", 1)
            spec = rule["to"]
            label = rule.get("label") or f"{rule['publish']} (palace.dispatch)"
            for node_id, node in raw.items():
                sites = [q for q, call in node.get("call_sites", ()) if call == method]
                types = node.get("receiver_types", {})
                if not any(q == type_name or is_a(types.get(q, "").split(".")[-1], type_name) for q in sites):
                    continue
                if spec.startswith("enclosing:"):
                    iface, target_method = spec.split(":", 1)[1].rsplit(".", 1)
                    cls = owner(node_id) if node["type"] != "class" else node_id
                    targets = [f"{cls}.{target_method}"] if cls and is_a(raw[cls]["simple_name"], iface) else []
                else:
                    target_type, target_method = spec.rsplit(".", 1)
                    targets = [f"{c}.{target_method}" for name in classes if is_a(name, target_type)
                               for c in classes[name]]
                for target in targets:
                    if target in raw:
                        resolved[node_id].add(target)
                        labels[(node_id, target)] = label
        else:
            iface, factory_method = rule["factory"].rsplit(".", 1)
            base, entry_method = rule["entry"].rsplit(".", 1)
            label = rule.get("label") or f"{rule['factory']} -> {rule['entry']} (palace.dispatch)"
            for name, ids in classes.items():
                if not is_a(name, iface):
                    continue
                for cls in ids:
                    factory = f"{cls}.{factory_method}"
                    if factory not in raw:
                        continue
                    built = [t for t in resolved.get(factory, ()) if raw[t]["type"] == "class"
                             and is_a(raw[t]["simple_name"], base)]
                    for made in built:
                        entry = f"{made}.{entry_method}"
                        if entry in raw:
                            resolved[factory].add(entry)
                            labels[(factory, entry)] = label
    return labels


def _celery_tasks(node: dict, qualifier: str, raw: Dict[str, dict], resolver: "ImportResolver") -> List[str]:
    """The task function `qualifier` names in `qualifier.delay(...)`: imported, or defined in the same module,
    and decorated as a task (@app.task, @shared_task, @celery.task(...))."""
    candidates: Set[str] = set()
    local = f"{node['module']}.{qualifier}"
    if local in raw:
        candidates.add(local)
    imports = resolver.imports.get(node["file"], {})
    head, _, rest = qualifier.partition(".")
    binding = imports.get(qualifier if not rest else head)
    if binding and not rest and binding[1] is not None:  # from tasks import send; send.delay()
        candidates |= resolver.symbol(binding[0], binding[1], qualifier, node["file"]) or set()
    elif binding and rest and "." not in rest:  # import tasks; tasks.send.delay() / from app import tasks
        if binding[1] is None:
            modules = resolver.modules_for(binding[0], node["file"]) or []
        else:
            modules = list(resolver.symbol(binding[0], binding[1], head, node["file"]) or ())
        candidates |= {f"{m}.{rest}" for m in modules}
    return sorted(c for c in candidates if c in raw and any(
        re.search(r"(^|\.)(shared_task|task)\b", d) for d in raw[c].get("decorators", ())))


# C# framework bases and the methods they call on a subclass, by name (Unity messages aren't overrides)
UNITY_MESSAGES = {"Awake", "Start", "Update", "FixedUpdate", "LateUpdate", "OnEnable", "OnDisable", "OnDestroy",
                  "OnValidate", "Reset", "OnGUI", "OnDrawGizmos", "OnDrawGizmosSelected", "OnApplicationQuit",
                  "OnApplicationPause", "OnApplicationFocus", "OnBecameVisible", "OnBecameInvisible",
                  "OnTriggerEnter", "OnTriggerExit", "OnTriggerStay", "OnTriggerEnter2D", "OnTriggerExit2D",
                  "OnTriggerStay2D", "OnCollisionEnter", "OnCollisionExit", "OnCollisionStay", "OnCollisionEnter2D",
                  "OnCollisionExit2D", "OnCollisionStay2D", "OnMouseDown", "OnMouseUp", "OnMouseEnter", "OnMouseExit",
                  "OnAnimatorMove", "OnAnimatorIK", "OnRenderObject", "OnPreRender", "OnPostRender"}
BLAZOR_LIFECYCLE = {"OnInitialized", "OnInitializedAsync", "OnParametersSet", "OnParametersSetAsync", "OnAfterRender",
                    "OnAfterRenderAsync", "SetParametersAsync", "ShouldRender", "BuildRenderTree", "Dispose",
                    "DisposeAsync"}
CS_FRAMEWORK_BASES = {
    **{b: UNITY_MESSAGES for b in ("MonoBehaviour", "NetworkBehaviour", "ScriptableObject", "StateMachineBehaviour",
                                    "Editor", "EditorWindow")},
    **{b: BLAZOR_LIFECYCLE for b in ("ComponentBase", "LayoutComponentBase", "OwningComponentBase")},
    "IDisposable": {"Dispose"}, "IAsyncDisposable": {"DisposeAsync"},
    "BackgroundService": {"ExecuteAsync", "StartAsync", "StopAsync", "Dispose"},
    "IHostedService": {"StartAsync", "StopAsync"},
}


def _framework_called(class_id: str, node: dict, raw: Dict[str, dict]) -> Set[str]:
    """A C# class's own methods its framework calls: overrides, and the messages of a framework base it
    names. A Razor component counts as a ComponentBase."""
    names: Set[str] = set()
    for base in node.get("bases", ()):
        names |= CS_FRAMEWORK_BASES.get(base.split(".")[-1], set())
    if node["file"].endswith((".razor", ".cshtml")):
        names |= BLAZOR_LIFECYCLE
    prefix = class_id + "."
    out = set()
    for other_id, other in raw.items():
        if other_id.startswith(prefix) and "." not in other_id[len(prefix):] and other["type"] == "method":
            if other["simple_name"] in names or re.search(r"\boverride\b", other.get("signature", "")):
                out.add(other_id)
    return out


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
    rel_path = Path(rel_path.replace("\\", "/")).as_posix()  # node files are forward-slash paths on every OS
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
