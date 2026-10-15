"""
Tree-sitter frontend: palace analysis for languages other than Python.

One LanguageSupport class serves every grammar. It runs the grammar's upstream tags query (the
queries editors and code search use for symbol indexing) and reads definitions and call
references from the matches, so adding a language is a table row, not a parser.

Grammars come from two places, tried in order:

1. Per-language wheels (tree-sitter-go, tree-sitter-rust, ...), dependencies of daedalus-cli.
   They ship with pip and never touch the network.
2. tree-sitter-language-pack, if installed (`daedalus-cli[palace-all]`). It covers hundreds of
   languages but downloads each grammar the first time it is used, so a language that only it
   provides fails offline; that failure is logged once and the language yields no elements.

Python stays on the stdlib ast analyzer, which reads signatures and docstrings more precisely.
"""

import importlib
import importlib.util
import logging
import posixpath
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from .languages import AnchorPattern, CodeElement, LanguageSupport

logger = logging.getLogger(__name__)

QUERY_DIR = Path(__file__).parent / "queries"

# Definition kinds that hold methods; everything else in a tags query is a function or method.
CONTAINER_KINDS = {"class", "interface", "module", "type", "struct", "enum", "trait", "object", "implementation"}
CALLABLE_KINDS = {"function", "method", "constructor", "macro"}


@dataclass
class Grammar:
    """One row of the language table."""
    name: str                  # display name and registry key
    extensions: List[str]
    wheel: Optional[str] = None            # importable module of the per-language wheel
    wheel_fn: str = "language"             # function in that module returning the language pointer
    pack: Optional[str] = None             # tree-sitter-language-pack name
    vendored_tags: Optional[str] = None    # queries/ file used when the grammar ships no tags query of its own
    supplement: Optional[str] = None       # queries/ file always appended (calls upstream doesn't capture)
    base_query_from: Optional[str] = None  # wheel whose TAGS_QUERY this grammar's query extends
    constructor_names: Tuple[str, ...] = ()
    constructor_is_class_name: bool = False
    test_file: Optional[str] = None        # regex on the repo-relative path (forward slashes)
    test_symbol: Optional[str] = None      # regex on the simple name; None means "any symbol in a test file"
    test_candidates: Tuple[str, ...] = ()  # templates: {dir} {stem} {ext}
    attribute_tests: bool = False          # Rust: #[test], #[tokio::test], #[rstest] functions
    test_marker: Optional[str] = None      # regex on a definition's text before its name (@Test, [Fact])
    package_markers: Tuple[str, ...] = ()  # files that stand for their directory (index.ts, mod.rs)
    doc_files: Tuple[str, ...] = ()        # files holding a directory's documentation (Go's doc.go)
    imports: Optional[str] = None          # import syntax we resolve: "js", "go", "java", "cs" (others: name-based)
    skip_kinds: Tuple[str, ...] = ()       # definition kinds that aren't code units (C# namespaces)
    top_level_node: bool = False           # give top-level statements a node (C#'s Program.cs)
    typed_receivers: bool = False          # read declared types of fields/parameters/locals (C#)
    implicit_self: bool = True             # False: a plain `name()` can't reach a method (needs obj./this./self.)


JS_TEST_FILE = r"(^|/)(__tests__|tests?)/|\.(test|spec)\.[cm]?[jt]sx?$"
JS_CANDIDATES = ("{dir}/{stem}.test{ext}", "{dir}/{stem}.spec{ext}", "{dir}/__tests__/{stem}.test{ext}",
                 "{dir}/__tests__/{stem}{ext}")

GRAMMARS: List[Grammar] = [
    Grammar("JavaScript", [".js", ".jsx", ".mjs", ".cjs"], wheel="tree_sitter_javascript", pack="javascript",
            constructor_names=("constructor",), test_file=JS_TEST_FILE, test_candidates=JS_CANDIDATES, package_markers=("index.ts", "index.tsx", "index.js", "index.jsx", "index.mjs"), imports="js", implicit_self=False),
    Grammar("TypeScript", [".ts", ".mts", ".cts"], wheel="tree_sitter_typescript", wheel_fn="language_typescript",
            pack="typescript", vendored_tags="typescript-tags.scm", base_query_from="tree_sitter_javascript",
            constructor_names=("constructor",), test_file=JS_TEST_FILE, test_candidates=JS_CANDIDATES, package_markers=("index.ts", "index.tsx", "index.js", "index.jsx", "index.mjs"), imports="js", implicit_self=False),
    Grammar("TSX", [".tsx"], wheel="tree_sitter_typescript", wheel_fn="language_tsx", pack="tsx",
            vendored_tags="typescript-tags.scm", base_query_from="tree_sitter_javascript",
            constructor_names=("constructor",), test_file=JS_TEST_FILE, test_candidates=JS_CANDIDATES, package_markers=("index.ts", "index.tsx", "index.js", "index.jsx", "index.mjs"), imports="js", implicit_self=False),
    Grammar("Go", [".go"], wheel="tree_sitter_go", pack="go", test_file=r"_test\.go$",
            test_symbol=r"^(Test|Benchmark|Example|Fuzz)", test_candidates=("{dir}/{stem}_test.go",), doc_files=("doc.go",), imports="go", implicit_self=False),
    Grammar("Rust", [".rs"], wheel="tree_sitter_rust", pack="rust", constructor_names=("new",),
            supplement="rust-supplement.scm",
            test_file=r"(^|/)tests/", attribute_tests=True, test_candidates=("tests/{stem}.rs",), package_markers=("mod.rs", "lib.rs"), implicit_self=False),
    Grammar("Java", [".java"], wheel="tree_sitter_java", pack="java", constructor_is_class_name=True,
            imports="java", test_marker=r"@(Test|ParameterizedTest|RepeatedTest|TestFactory|TestTemplate)\b",
            test_file=r"(^|/)src/test/|Tests?\.java$|(^|/)Test[A-Z]\w*\.java$",
            test_candidates=("{testdir}/{stem}Test.java", "{testdir}/{stem}Tests.java", "{dir}/{stem}Test.java")),
    Grammar("C#", [".cs"], wheel="tree_sitter_c_sharp", pack="csharp", constructor_is_class_name=True,
            vendored_tags="c_sharp-tags.scm", supplement="c_sharp-supplement.scm", imports="cs",
            skip_kinds=("module",), top_level_node=True, typed_receivers=True,
            test_marker=r"\[\s*(Test|TestMethod|TestCase|TestCaseSource|Fact|Theory|UnityTest)\b",
            test_file=r"(^|/)[^/]*Tests?/|Tests?\.cs$"),
    Grammar("C", [".c", ".h"], wheel="tree_sitter_c", pack="c", test_file=r"(^|/)tests?/|_test\.c$|^test_"),
    Grammar("C++", [".cc", ".cpp", ".cxx", ".hpp", ".hh", ".hxx"], wheel="tree_sitter_cpp", pack="cpp",
            constructor_is_class_name=True, test_file=r"(^|/)tests?/|_test\.(cc|cpp|cxx)$"),
    Grammar("Ruby", [".rb"], wheel="tree_sitter_ruby", pack="ruby", constructor_names=("initialize",),
            test_file=r"(^|/)(spec|test)/|_(spec|test)\.rb$",
            test_candidates=("spec/{stem}_spec.rb", "test/{stem}_test.rb", "test/test_{stem}.rb")),
    # Language pack only: no maintained wheel, or none that ships a tags query. Left out after checking:
    # Swift (its tags query has no call references, so no call graph) and Elixir (reports def/defmodule
    # as calls).
    Grammar("Kotlin", [".kt", ".kts"], pack="kotlin", constructor_is_class_name=True,
            test_marker=r"@(Test|ParameterizedTest)\b",
            test_file=r"(^|/)src/test/|Tests?\.kt$"),
    Grammar("PHP", [".php"], pack="php", constructor_names=("__construct",), test_file=r"(^|/)tests?/|Test\.php$"),
    Grammar("Scala", [".scala"], pack="scala", test_file=r"(^|/)src/test/|(Spec|Test|Suite)\.scala$"),
    Grammar("Lua", [".lua"], pack="lua", test_file=r"(^|/)(spec|tests?)/|_spec\.lua$", implicit_self=False),
]


def _pack():
    try:
        import tree_sitter_language_pack  # noqa: F401
        return tree_sitter_language_pack
    except ImportError:
        return None


def tree_sitter_available() -> bool:
    return importlib.util.find_spec("tree_sitter") is not None


def grammar_source(g: Grammar) -> Optional[str]:
    """Where this grammar would load from ("wheel", "pack"), without loading or downloading it."""
    if not tree_sitter_available():
        return None
    if g.wheel and importlib.util.find_spec(g.wheel) is not None:
        return "wheel"
    if g.pack and _pack() is not None:
        return "pack"
    return None


class TreeSitterSupport(LanguageSupport):
    """Palace analysis for one grammar, driven by its tags query. Loads the grammar on first use."""

    def __init__(self, grammar: Grammar):
        self.grammar = grammar
        self._loaded = False
        self._failed = False
        self._parser = None
        self._query = None
        self.fallback: Optional[LanguageSupport] = None  # e.g. the regex TypeScript analyzer
        self._last_parse: Optional[Tuple[object, bytes, object]] = None  # (key, source, tree)

    def _parse(self, file_path: Path) -> Tuple[bytes, object]:
        """Parse a file, reusing the last parse when the same unchanged file is asked for again (analysis
        and import extraction read the same file back to back)."""
        st = Path(file_path).stat()
        key = (str(file_path), st.st_mtime_ns, st.st_size)
        if self._last_parse is not None and self._last_parse[0] == key:
            return self._last_parse[1], self._last_parse[2]
        source = Path(file_path).read_bytes()
        tree = self._parser.parse(source)
        self._last_parse = (key, source, tree)
        return source, tree

    @property
    def name(self) -> str:
        return self.grammar.name

    @property
    def extensions(self) -> List[str]:
        return list(self.grammar.extensions)

    @property
    def source(self) -> Optional[str]:
        return grammar_source(self.grammar)

    # -- loading -------------------------------------------------------------------------------

    def _load(self) -> bool:
        if self._loaded or self._failed:
            return self._loaded
        try:
            import tree_sitter
            from tree_sitter import Language, Parser, Query
            if not hasattr(tree_sitter, "QueryCursor"):
                raise RuntimeError(f"tree-sitter {getattr(tree_sitter, '__version__', '?')} is too old; need >= 0.25")
            g = self.grammar
            wheel = g.wheel and importlib.util.find_spec(g.wheel) is not None
            if wheel:
                mod = importlib.import_module(g.wheel)
                language = Language(getattr(mod, g.wheel_fn)())
                own = getattr(mod, "TAGS_QUERY", None)
                base = getattr(importlib.import_module(g.base_query_from), "TAGS_QUERY", None) if g.base_query_from else None
            elif g.pack and _pack() is not None:
                pack = _pack()
                language = pack.get_language(g.pack)  # may download the grammar
                own = pack.get_tags_query(g.pack)
                base = pack.get_tags_query("javascript") if g.base_query_from else None
            else:
                raise RuntimeError("no grammar installed")
            if not own and g.vendored_tags:
                own = (QUERY_DIR / g.vendored_tags).read_text()
            tags = "\n".join(q for q in (base, own) if q)
            if not tags.strip():
                raise RuntimeError("grammar has no tags query")
            if g.supplement:
                tags += "\n" + (QUERY_DIR / g.supplement).read_text()
            self._parser = Parser(language)
            self._query = Query(language, tags)
            self._loaded = True
        except Exception as e:  # missing grammar, failed download, query that doesn't compile, old tree-sitter
            self._failed = True
            fallback = f"; using {self.fallback.name}'s basic analyzer" if self.fallback else "; its files are skipped"
            logger.warning(f"palace: {self.grammar.name} unavailable ({e}){fallback}")
        return self._loaded

    def available(self) -> bool:
        """Load the grammar now (a pack grammar may download) and report whether it works."""
        return self._load()

    # -- analysis ------------------------------------------------------------------------------

    def analyze_file(self, file_path: Path, project_root: Path) -> List[CodeElement]:
        if not self._load():
            return self.fallback.analyze_file(file_path, project_root) if self.fallback else []
        try:
            source, tree = self._parse(file_path)
        except OSError as e:
            logger.warning(f"Failed to read {file_path}: {e}")
            return []
        rel = Path(file_path).relative_to(project_root).as_posix()
        return extract_elements(self, source, rel, tree)

    def generate_anchor_pattern(self, element: CodeElement) -> AnchorPattern:
        # The definition's line from its start up to and including the name, whitespace-tolerant and
        # anchored at the line start, so `reset(): void` doesn't match a `this.reset()` call above it.
        head = element.signature.split("\n", 1)[0]
        idx = head.find(element.simple_name)
        head = head[: idx + len(element.simple_name)] if idx >= 0 else element.simple_name
        pattern = r"\s+".join(re.escape(part) for part in head.split())
        return AnchorPattern(pattern=r"^\s*" + pattern + r"\b", is_regex=True,
                             description=f"{element.element_type.title()}: {element.name}")

    # -- language conventions used by palace queries --------------------------------------------

    def is_test_file(self, rel_path: str) -> bool:
        return bool(self.grammar.test_file and re.search(self.grammar.test_file, rel_path))

    def test_file_candidates(self, rel_path: str) -> List[str]:
        p = Path(rel_path)
        d = p.parent.as_posix()
        testdir = d.replace("src/main/", "src/test/", 1) if "src/main/" in d else d
        out = []
        for t in self.grammar.test_candidates:
            c = t.format(dir=d, stem=p.stem, ext=p.suffix, testdir=testdir)
            out.append(c[2:] if c.startswith("./") else c)
        return out

    @property
    def implicit_self(self) -> bool:
        return self.grammar.implicit_self

    @property
    def package_markers(self) -> Tuple[str, ...]:  # type: ignore[override]
        return self.grammar.package_markers

    @property
    def doc_files(self) -> Tuple[str, ...]:
        return self.grammar.doc_files

    def module_doc(self, file_path: Path) -> Optional[str]:
        """The comment block at the top of the file (after a shebang or package line), markers stripped."""
        if not self._load():
            return None
        try:
            tree = self._parser.parse(Path(file_path).read_bytes())
        except OSError:
            return None
        block = []
        for child in tree.root_node.named_children:
            if "comment" in child.type:
                block.append(child.text.decode("utf-8", "replace"))
            elif block or child.type not in ("package_clause", "package_declaration", "hash_bang_line"):
                break
        text = "\n".join(block)
        lines = [re.sub(r"^\s*(//[/!]?|/\*\*?|\*/|\*|#)\s?", "", ln).rstrip() for ln in text.splitlines()]
        doc = "\n".join(ln for ln in lines if ln.strip() and ln.strip() != "*/").strip()
        return doc or None

    def file_imports(self, file_path: Path, project_root: Path) -> Dict[str, Tuple[str, Optional[str]]]:
        kind = self.grammar.imports
        if kind is None or not self._load():
            return {}
        try:
            _, tree = self._parse(file_path)
        except OSError:
            return {}
        rel = Path(file_path).relative_to(project_root).as_posix()
        return {"js": _js_imports, "go": _go_imports, "java": _java_imports,
                "cs": _cs_imports}[kind](tree.root_node, rel)

    def constructor_of(self, class_name: str) -> Tuple[str, ...]:
        names = self.grammar.constructor_names
        return names + ((class_name,) if self.grammar.constructor_is_class_name else ())


@dataclass
class _Def:
    node: object
    name: str
    kind: str
    name_node: object = None
    doc: List[str] = field(default_factory=list)


def _kind(capture: str) -> str:
    return capture.split(".", 1)[1] if "." in capture else capture


def extract_elements(support: TreeSitterSupport, source: bytes, rel: str, tree=None) -> List[CodeElement]:
    """Definitions and call references from one parsed file."""
    from tree_sitter import QueryCursor

    if tree is None:
        tree = support._parser.parse(source)
    lines = source.split(b"\n")
    defs: Dict[Tuple[int, int], _Def] = {}
    calls: List[Tuple[object, object, str]] = []  # (reference node, name node, kind)
    for _, caps in QueryCursor(support._query).matches(tree.root_node):
        names = caps.get("name")
        if not names:
            continue
        for cap, nodes in caps.items():
            if cap.startswith("definition."):
                kind = _kind(cap)
                node = nodes[0]
                key = (node.start_byte, node.end_byte)
                existing = defs.get(key)
                # One node can match twice (rust: method and function); the more specific kind wins
                if existing is None or (existing.kind == "function" and kind == "method"):
                    doc = [d.text.decode("utf-8", "replace") for d in caps.get("doc", [])]
                    defs[key] = _Def(node, names[0].text.decode("utf-8", "replace"), kind, names[0], doc)
            elif cap in ("reference.call", "reference.send", "reference.class"):
                calls.append((nodes[0], names[0], _kind(cap)))

    def_nodes = {(d.node.start_byte, d.node.end_byte): d for d in defs.values()}

    def enclosing(node, kinds) -> Optional[_Def]:
        parent = node.parent
        while parent is not None:
            d = def_nodes.get((parent.start_byte, parent.end_byte))
            if d is not None and d.kind in kinds:
                return d
            parent = parent.parent
        return None

    is_test_file = support.is_test_file(rel)
    elements: List[CodeElement] = []
    spans: List[Tuple[int, int, CodeElement]] = []
    for d in sorted(defs.values(), key=lambda d: d.node.start_byte):
        callable_ = d.kind in CALLABLE_KINDS
        if callable_ and enclosing(d.node, CALLABLE_KINDS):
            continue  # nested functions belong to their parent, as in the Python analyzer
        container = enclosing(d.node, CONTAINER_KINDS) if callable_ else None
        # A function in a Rust mod or TS namespace is a function (plain calls reach it), named with its module
        in_module = container is not None and container.kind == "module" and (
            d.kind != "method" or not support.grammar.implicit_self)
        class_name = container.name if container else (_receiver(d.node) if callable_ else None)
        if callable_:
            element_type = "function" if in_module else ("method" if (class_name or d.kind == "method") else "function")
        else:
            element_type = "class"
        if not callable_ and enclosing(d.node, CALLABLE_KINDS):
            continue  # a type declared inside a function body
        if not callable_ and d.kind in support.grammar.skip_kinds:
            continue  # a C# namespace is a scope, not a code unit
        full = f"{class_name}.{d.name}" if (class_name and (element_type == "method" or in_module)) else d.name
        # The definition's first source line, from its start (so `type Calc struct`, not `Calc struct`)
        row = d.node.start_point[0]
        raw_line = lines[row] if row < len(lines) else b""
        # Cut at the first brace after the name: a one-line `interface P { price(): number }` keeps `price`
        name_end = d.name_node.end_point[1] if d.name_node.start_point[0] == row else 0
        cut = raw_line.find(b"{", name_end)
        signature = (raw_line[:cut] if cut >= 0 else raw_line).decode("utf-8", "replace").strip()[:200] or d.name
        el = CodeElement(name=full, element_type=element_type, file=rel, line=d.node.start_point[0] + 1,
                         signature=signature, docstring="\n".join(d.doc) or None,
                         class_name=class_name if element_type == "method" else None, simple_name=d.name)
        el.end_line = d.node.end_point[0] + 1
        el.is_test = _is_test(support, d, is_test_file) if callable_ else False
        if not callable_:
            el.bases = _bases(d.node)
        if support.grammar.typed_receivers:
            el.receiver_types = _cs_receiver_types(d.node, container.node if container else None, callable_)
            el.extension_method = callable_ and _is_extension(d.node)
        elements.append(el)
        spans.append((d.node.start_byte, d.node.end_byte, el))

    # Each call belongs to the innermost function or method containing it; a call outside any (a field
    # initializer, a static block) belongs to the innermost class. Enclosing classes don't collect their
    # methods' calls, so `callers` names the method that makes the call, not every class around it.
    top_level: Set[str] = set()
    top_level_member: Set[str] = set()
    top_level_sites: Set[Tuple[str, str]] = set()
    for ref, name_node, kind in calls:
        callee = name_node.text.decode("utf-8", "replace")
        through_object = kind in ("call", "send") and _through_object(ref, name_node)
        site = (_qualifier(ref, name_node) if through_object else "", callee)
        containing = [(b - a, el) for (a, b, el) in spans if a <= ref.start_byte < b]
        callables = [(size, el) for size, el in containing if el.element_type != "class"]
        pool = callables or containing
        owners = [min(pool, key=lambda t: t[0])[1]] if pool else []
        for el in owners:
            if callee not in el.calls:
                el.calls.append(callee)
            if through_object and callee not in el.member_calls:
                el.member_calls.append(callee)
            if site not in el.call_sites:
                el.call_sites.append(site)
        if not owners:
            top_level.add(callee)
            top_level_sites.add(site)
            if through_object:
                top_level_member.add(callee)

    # Test files whose tests are calls, not definitions (describe/it, RSpec): one node for the file's
    # top-level code, so tests-for can reach what it calls.
    if top_level and (is_test_file or support.grammar.top_level_node):
        stem = Path(rel).name
        el = CodeElement(name=f"<{stem}>", element_type="module", file=rel, line=1, signature=rel,
                         calls=sorted(top_level), simple_name=f"<{stem}>")
        el.end_line = None
        el.member_calls = sorted(top_level_member)
        el.call_sites = sorted(top_level_sites)
        el.is_test = is_test_file
        elements.append(el)
    return elements


def _through_object(ref, name_node) -> bool:
    """`obj.name()` rather than `name()`: the name sits under a member/selector node rather than
    directly under the call, or the call node itself names an object (java `object`, ruby `receiver`)."""
    parent = name_node.parent
    while parent is not None and parent.type == "parenthesized_expression":
        parent = parent.parent
    if parent is not None and parent != ref:
        return True
    return any(ref.child_by_field_name(f) is not None for f in ("object", "receiver"))


IDENTIFIER_TYPES = {"identifier", "package_identifier", "type_identifier", "constant", "name"}
SELF_WORDS = {"this", "self", "Self", "super", "base"}


def _qualifier(ref, name_node) -> str:
    """What a call goes through: an identifier (`pkg` in pkg.F(), `Foo` in Foo.bar()), "self" for
    this/self, or "?" for anything else (a field, a call result, ...)."""
    parent = name_node.parent
    while parent is not None and parent.type == "parenthesized_expression":
        parent = parent.parent
    holder = ref if parent == ref or parent is None else parent
    # this._orders.Find(): the call goes through the field `_orders`, recorded as "self._orders"
    for f in ("expression", "object"):
        inner = holder.child_by_field_name(f)
        if inner is not None and inner != name_node and inner.type in ("member_access_expression", "member_expression",
                                                                         "field_access"):
            target = inner.child_by_field_name("expression") or inner.child_by_field_name("object")
            field_name = inner.child_by_field_name("name") or inner.child_by_field_name("property") \
                or inner.child_by_field_name("field")
            if target is not None and field_name is not None and _text(target) in SELF_WORDS:
                return "self." + _text(field_name)
    obj = None
    for f in ("object", "operand", "path", "expression", "value", "receiver", "scope", "argument"):
        obj = holder.child_by_field_name(f)
        if obj is not None and obj != name_node:
            break
        obj = None
    if obj is None:
        return "?"
    text = obj.text.decode("utf-8", "replace")
    if text in SELF_WORDS or obj.type in ("this", "self", "super"):
        return "self"
    return text if obj.type in IDENTIFIER_TYPES else "?"


def _text(node) -> str:
    return node.text.decode("utf-8", "replace") if node is not None else ""


def _unquote(s: str) -> str:
    return s.strip().strip("'\"`")


def _top_level(root, wanted: str):
    """Nodes of type `wanted` among the file's top-level statements and inside its import declarations
    (imports never sit inside functions in the languages resolved here, so the bodies aren't walked)."""
    for child in root.named_children:
        if child.type == wanted:
            yield child
        elif "import" in child.type:
            yield from (n for n in _walk(child) if n.type == wanted)


def _js_imports(root, rel: str) -> Dict[str, Tuple[str, Optional[str]]]:
    """import X from './x'; import {a as b} from './x'; import * as m from './x' (relative specs only are
    the project's; bare specs are packages)."""
    out: Dict[str, Tuple[str, Optional[str]]] = {}
    for node in _top_level(root, "import_statement"):
        if node.type != "import_statement":
            continue
        source = _unquote(_text(node.child_by_field_name("source")))
        if not source:
            continue
        spec = ("js:" + posixpath.normpath(posixpath.join(posixpath.dirname(rel), source))
                if source.startswith(".") else "ext:" + source)
        for clause in (c for c in node.named_children if c.type == "import_clause"):
            for part in clause.named_children:
                if part.type == "identifier":  # default import
                    out[_text(part)] = (spec, "default")
                elif part.type == "namespace_import":
                    ident = next((c for c in part.named_children if c.type == "identifier"), None)
                    if ident is not None:
                        out[_text(ident)] = (spec, None)
                elif part.type == "named_imports":
                    for item in (c for c in part.named_children if c.type == "import_specifier"):
                        name = _text(item.child_by_field_name("name"))
                        alias = _text(item.child_by_field_name("alias")) or name
                        if name:
                            out[alias] = (spec, name)
    return out


def _go_imports(root, rel: str) -> Dict[str, Tuple[str, Optional[str]]]:
    """import "example.com/m/pkg" binds pkg (or its alias); query.py maps the path to a directory via go.mod."""
    out: Dict[str, Tuple[str, Optional[str]]] = {}
    for node in _top_level(root, "import_spec"):
        if node.type != "import_spec":
            continue
        path = _unquote(_text(node.child_by_field_name("path")))
        alias = _text(node.child_by_field_name("name"))
        if alias in ("_", "."):
            continue
        if not alias:
            segments = [p for p in path.split("/") if p]
            if not segments:
                continue
            alias = segments[-2] if re.fullmatch(r"v\d+", segments[-1]) and len(segments) > 1 else segments[-1]
            alias = alias.replace("-", "_").split(".")[0]
        out[alias] = ("go:" + path, None)
    return out


def _java_imports(root, rel: str) -> Dict[str, Tuple[str, Optional[str]]]:
    """import com.x.Foo binds Foo; import static com.x.Util.helper binds helper. Wildcards are skipped."""
    out: Dict[str, Tuple[str, Optional[str]]] = {}
    for node in _top_level(root, "import_declaration"):
        if node.type != "import_declaration":
            continue
        text = _text(node)
        if "*" in text:
            continue
        static = re.search(r"\bstatic\b", text) is not None
        target = next((c for c in node.named_children if c.type in ("scoped_identifier", "identifier")), None)
        if target is None:
            continue
        parts = _text(target).split(".")
        if static and len(parts) >= 2:
            out[parts[-1]] = ("java:" + "/".join(parts[:-1]), parts[-2] + "." + parts[-1])
        else:
            out[parts[-1]] = ("java:" + "/".join(parts), parts[-1])
    return out


def _cs_imports(root, rel: str) -> Dict[str, Tuple[str, Optional[str]]]:
    """C# imports namespaces, not files. Recorded as "using:<ns>" entries (global ones as "global:<ns>"),
    `using X = A.B.C;` aliases, and the file's own namespace under "__namespace__"; query.py resolves type
    names against the namespaces a file can see."""
    out: Dict[str, Tuple[str, Optional[str]]] = {}

    def visit(node, namespace: str):
        for child in node.named_children:
            if child.type == "using_directive":
                text = _text(child)
                if re.search(r"\busing\s+static\b", text):
                    continue
                alias = child.child_by_field_name("name")
                target = next((c for c in child.named_children if c.type in ("qualified_name", "identifier")
                               and c != alias), None)
                if target is None:
                    continue
                name = _text(target)
                if alias is not None:  # using Json = Newtonsoft.Json.JsonConvert;
                    head, _, last = name.rpartition(".")
                    out[_text(alias)] = ("cs:" + head, last)
                else:
                    out[("global:" if text.lstrip().startswith("global") else "using:") + name] = ("cs:" + name, None)
            elif child.type in ("namespace_declaration", "file_scoped_namespace_declaration"):
                name = _text(child.child_by_field_name("name"))
                full = f"{namespace}.{name}" if namespace else name
                out.setdefault("__namespace__", ("cs:" + full, None))
                body = child.child_by_field_name("body")
                visit(body if body is not None else child, full)
    visit(root, "")
    return out


BASE_CLAUSES = ("base_list", "superclass", "super_interfaces", "class_heritage", "extends_clause",
                "implements_clause", "extends_type_clause", "superclass_list", "superclasses")


def _simple_type(node) -> Optional[str]:
    """`IStore`, `ILogger<T>`, `IStore?`, `A.B.IStore`, `IStore[]` -> the type's simple name; None for
    `var`, built-in types and anything else."""
    if node is None:
        return None
    t = node.type
    if t in ("identifier", "type_identifier"):
        return _text(node)
    if t == "generic_name":
        ident = next((c for c in node.named_children if c.type == "identifier"), None)
        return _text(ident) if ident is not None else None
    if t in ("nullable_type", "array_type", "pointer_type", "ref_type", "scoped_type"):
        inner = node.child_by_field_name("type") or (node.named_children[0] if node.named_children else None)
        return _simple_type(inner)
    if t in ("qualified_name", "alias_qualified_name"):
        last = node.child_by_field_name("name") or (node.named_children[-1] if node.named_children else None)
        return _simple_type(last)
    return None


def _bases(class_node) -> List[str]:
    """Simple names of the classes and interfaces a class declaration extends or implements."""
    out: List[str] = []
    for child in class_node.named_children:
        if child.type in BASE_CLAUSES:
            for item in child.named_children:
                name = _simple_type(item) or (_simple_type(item.named_children[0]) if item.named_children else None)
                if name and name not in out:
                    out.append(name)
    return out


def _declare(types: Dict[str, Optional[str]], name: str, type_name: Optional[str]) -> None:
    """Record name -> type. An untyped declaration (`var x = Make()`, a lambda parameter) or a name declared
    with two types is recorded as None: it shadows a typed field, and leaves the name to the name rule."""
    if not name:
        return
    types[name] = type_name if (type_name and types.get(name, type_name) == type_name) else None


def _type_text(node, type_params: Set[str]) -> Optional[str]:
    """A declared type for receiver resolution: `IStore`, or `System.Threading.Tasks.Task` when written
    qualified (so an outside type isn't mistaken for a project type of the same simple name); None for
    `var`, built-ins and the enclosing generic parameters (`T item` says nothing certain)."""
    if node is None:
        return None
    t = node.type
    if t in ("nullable_type", "array_type", "pointer_type", "ref_type", "scoped_type"):
        inner = node.child_by_field_name("type") or (node.named_children[0] if node.named_children else None)
        return _type_text(inner, type_params)
    if t in ("qualified_name", "alias_qualified_name"):
        text = re.sub(r"<.*$", "", _text(node)).replace("global::", "")
        return text if text.split(".")[-1] not in type_params else None
    name = _simple_type(node)
    return name if name and name not in type_params else None


def _type_parameters(*nodes) -> Set[str]:
    out: Set[str] = set()
    for node in nodes:
        if node is None:
            continue
        for child in node.named_children:
            if child.type == "type_parameter_list":
                out |= {_text(tp.child_by_field_name("name") or tp) for tp in child.named_children
                        if tp.type == "type_parameter"}
    return out


def _cs_declarations(node, types: Dict[str, Optional[str]], type_params: Set[str]) -> None:
    """Every name declared under `node`: parameters (lambda ones too), locals, `var x = new T()`, pattern
    variables (`is B f`), `out var`, catch and foreach variables, tuple declarations."""
    for n in _walk(node):
        t = n.type
        if t == "parameter":
            _declare(types, _text(n.child_by_field_name("name")), _type_text(n.child_by_field_name("type"), type_params))
        elif t == "implicit_parameter":
            _declare(types, _text(n), None)
        elif t == "variable_declaration":
            declared = _type_text(n.child_by_field_name("type"), type_params)
            for decl in (c for c in n.named_children if c.type == "variable_declarator"):
                pattern = next((c for c in decl.named_children if c.type == "tuple_pattern"), None)
                if pattern is not None:  # var (x, y) = ...
                    for ident in (x for x in _walk(pattern) if x.type == "identifier"):
                        _declare(types, _text(ident), None)
                    continue
                name = _text(decl.child_by_field_name("name") or next(
                    (c for c in decl.named_children if c.type == "identifier"), None))
                value = next((c for c in decl.named_children if c.type == "object_creation_expression"), None)
                created = _type_text(value.child_by_field_name("type"), type_params) if value is not None else None
                _declare(types, name, declared or created)
        elif t in ("declaration_pattern", "declaration_expression", "catch_declaration"):
            name = n.child_by_field_name("name")
            if name is not None and name.type == "identifier":
                _declare(types, _text(name), _type_text(n.child_by_field_name("type"), type_params))
            elif name is not None:  # var (x, y) = ...: every name in the designation, type unknown
                for ident in (x for x in _walk(name) if x.type == "identifier"):
                    _declare(types, _text(ident), None)
        elif t == "foreach_statement":
            left = n.child_by_field_name("left")
            if left is not None and left.type == "identifier":
                _declare(types, _text(left), _type_text(n.child_by_field_name("type"), type_params))
            elif left is not None:
                for ident in (x for x in _walk(left) if x.type == "identifier"):
                    _declare(types, _text(ident), None)
        elif t == "parenthesized_variable_designation":
            for ident in (x for x in n.named_children if x.type == "identifier"):
                _declare(types, _text(ident), None)


def _cs_member_types(class_node, type_params: Set[str]) -> Dict[str, Optional[str]]:
    """A C# type's fields, properties and primary-constructor parameters."""
    types: Dict[str, Optional[str]] = {}
    for child in class_node.named_children:
        if child.type == "parameter_list":  # primary constructor: class Restocker(IInventoryStore inventory)
            for param in (c for c in child.named_children if c.type == "parameter"):
                _declare(types, _text(param.child_by_field_name("name")),
                         _type_text(param.child_by_field_name("type"), type_params))
        if child.type == "declaration_list":
            for member in child.named_children:
                if member.type in ("field_declaration", "event_field_declaration"):
                    _cs_declarations(member, types, type_params)
                elif member.type == "property_declaration":
                    _declare(types, _text(member.child_by_field_name("name")),
                             _type_text(member.child_by_field_name("type"), type_params))
    return types


def _cs_receiver_types(def_node, container_node, callable_: bool) -> Dict[str, str]:
    """Declared types a C# definition can call through. Its own parameters and locals shadow its type's
    fields, properties and primary-constructor parameters; the members are also kept as "self.<name>" for
    `this.x.Call()`. Names whose type isn't certain are left out, so they fall back to the name rule."""
    owner = container_node if callable_ else def_node
    type_params = _type_parameters(owner, def_node)
    members = _cs_member_types(owner, type_params) if owner is not None else {}
    types: Dict[str, Optional[str]] = dict(members)
    types.update({f"self.{k}": v for k, v in members.items()})
    if callable_:
        local: Dict[str, Optional[str]] = {}
        _cs_declarations(def_node, local, type_params)
        types.update(local)  # a parameter or local, typed or not, shadows a field of the same name
    else:  # code on the type itself (field initializers, property bodies): their lambdas, locals, patterns
        local: Dict[str, Optional[str]] = {}
        for child in def_node.named_children:
            if child.type == "declaration_list":
                for member in child.named_children:
                    if member.type in ("property_declaration", "field_declaration"):
                        _cs_declarations(member, local, type_params)
        types.update(local)
    return {k: v for k, v in types.items() if v}


def _is_extension(def_node) -> bool:
    """`static void Audit(this ILogger l)`: the first parameter carries the `this` modifier."""
    params = def_node.child_by_field_name("parameters")
    first = next((c for c in params.named_children if c.type == "parameter"), None) if params is not None else None
    return first is not None and any(m.type == "modifier" and _text(m) == "this" for m in first.named_children)


def _receiver(node) -> Optional[str]:
    """The type a method belongs to when that isn't an enclosing node: Go receivers, Rust impl blocks."""
    recv = node.child_by_field_name("receiver")
    if recv is not None:  # go: func (s *S) Run()
        ids = [n for n in _walk(recv) if n.type == "type_identifier"]
        if ids:  # the first one: Stack in `(s *Stack[T])`, not the type parameter T
            return ids[0].text.decode("utf-8", "replace")
    parent = node.parent
    while parent is not None:
        if parent.type == "impl_item":  # rust: impl Trait for Type { fn ... }
            t = parent.child_by_field_name("type")
            if t is not None:
                ids = [n for n in _walk(t) if n.type == "type_identifier"] or [t]
                return ids[0].text.decode("utf-8", "replace")
        parent = parent.parent
    return None


def _is_test(support: TreeSitterSupport, d: _Def, in_test_file: bool) -> bool:
    g = support.grammar
    if g.attribute_tests and _rust_test(d.node):
        return True
    if g.test_marker and d.name_node is not None:
        head = d.node.text[: max(0, d.name_node.start_byte - d.node.start_byte)].decode("utf-8", "replace")
        prev = d.node.prev_named_sibling  # C# attributes and some annotations sit just before the node
        if prev is not None and prev.type in ("attribute_list", "annotation", "marker_annotation"):
            head = prev.text.decode("utf-8", "replace") + head
        if re.search(g.test_marker, head):
            return True
    if not in_test_file:
        return False
    return bool(re.search(g.test_symbol, d.name)) if g.test_symbol else True


RUST_TEST_ATTR = re.compile(r"^#\[\s*(?:[\w:]+::)?(?:test|rstest)\b")  # #[test], #[tokio::test], #[rstest]


def _rust_test(node) -> bool:
    """A #[test]-style attribute directly on the function (#[cfg(not(test))] is not one)."""
    prev = node.prev_named_sibling
    while prev is not None and prev.type in ("attribute_item", "line_comment", "block_comment"):
        if prev.type == "attribute_item" and RUST_TEST_ATTR.search(prev.text.decode("utf-8", "replace")):
            return True
        prev = prev.prev_named_sibling
    return False


def _walk(node):
    yield node
    for c in node.children:
        yield from _walk(c)


def tree_sitter_languages() -> List[TreeSitterSupport]:
    """A support object for every grammar that could load here (without loading it)."""
    return [TreeSitterSupport(g) for g in GRAMMARS if grammar_source(g)]
