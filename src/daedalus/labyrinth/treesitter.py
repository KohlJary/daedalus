"""
Tree-sitter frontend: palace analysis for languages other than Python.

One LanguageSupport class serves every grammar. It runs the grammar's upstream tags query (the
queries editors and code search use for symbol indexing) and reads definitions and call
references from the matches, so adding a language is a table row, not a parser.

Grammars come from two places, tried in order:

1. Per-language wheels (tree-sitter-go, tree-sitter-rust, ...), installed by `daedalus[palace]`.
   They ship with pip and never touch the network.
2. tree-sitter-language-pack, if installed (`daedalus[palace-all]`). It covers hundreds of
   languages but downloads each grammar the first time it is used, so a language that only it
   provides fails offline; that failure is logged once and the language yields no elements.

Python stays on the stdlib ast analyzer, which reads signatures and docstrings more precisely.
"""

import importlib
import importlib.util
import logging
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
    implicit_self: bool = True             # False: a plain `name()` can't reach a method (needs obj./this./self.)


JS_TEST_FILE = r"(^|/)(__tests__|tests?)/|\.(test|spec)\.[cm]?[jt]sx?$"
JS_CANDIDATES = ("{dir}/{stem}.test{ext}", "{dir}/{stem}.spec{ext}", "{dir}/__tests__/{stem}.test{ext}",
                 "{dir}/__tests__/{stem}{ext}")

GRAMMARS: List[Grammar] = [
    Grammar("JavaScript", [".js", ".jsx", ".mjs", ".cjs"], wheel="tree_sitter_javascript", pack="javascript",
            constructor_names=("constructor",), test_file=JS_TEST_FILE, test_candidates=JS_CANDIDATES, package_markers=("index.ts", "index.tsx", "index.js", "index.jsx", "index.mjs"), implicit_self=False),
    Grammar("TypeScript", [".ts", ".mts", ".cts"], wheel="tree_sitter_typescript", wheel_fn="language_typescript",
            pack="typescript", vendored_tags="typescript-tags.scm", base_query_from="tree_sitter_javascript",
            constructor_names=("constructor",), test_file=JS_TEST_FILE, test_candidates=JS_CANDIDATES, package_markers=("index.ts", "index.tsx", "index.js", "index.jsx", "index.mjs"), implicit_self=False),
    Grammar("TSX", [".tsx"], wheel="tree_sitter_typescript", wheel_fn="language_tsx", pack="tsx",
            vendored_tags="typescript-tags.scm", base_query_from="tree_sitter_javascript",
            constructor_names=("constructor",), test_file=JS_TEST_FILE, test_candidates=JS_CANDIDATES, package_markers=("index.ts", "index.tsx", "index.js", "index.jsx", "index.mjs"), implicit_self=False),
    Grammar("Go", [".go"], wheel="tree_sitter_go", pack="go", test_file=r"_test\.go$",
            test_symbol=r"^(Test|Benchmark|Example|Fuzz)", test_candidates=("{dir}/{stem}_test.go",), doc_files=("doc.go",), implicit_self=False),
    Grammar("Rust", [".rs"], wheel="tree_sitter_rust", pack="rust", constructor_names=("new",),
            supplement="rust-supplement.scm",
            test_file=r"(^|/)tests/", attribute_tests=True, test_candidates=("tests/{stem}.rs",), package_markers=("mod.rs", "lib.rs"), implicit_self=False),
    Grammar("Java", [".java"], wheel="tree_sitter_java", pack="java", constructor_is_class_name=True,
            test_marker=r"@(Test|ParameterizedTest|RepeatedTest|TestFactory|TestTemplate)\b",
            test_file=r"(^|/)src/test/|Tests?\.java$|(^|/)Test[A-Z]\w*\.java$",
            test_candidates=("{testdir}/{stem}Test.java", "{testdir}/{stem}Tests.java", "{dir}/{stem}Test.java")),
    Grammar("C#", [".cs"], wheel="tree_sitter_c_sharp", pack="csharp", constructor_is_class_name=True,
            vendored_tags="c_sharp-tags.scm", supplement="c_sharp-supplement.scm",
            test_marker=r"\[\s*(Test|TestMethod|TestCase|Fact|Theory)\b",
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
            source = Path(file_path).read_bytes()
        except OSError as e:
            logger.warning(f"Failed to read {file_path}: {e}")
            return []
        rel = Path(file_path).relative_to(project_root).as_posix()
        return extract_elements(self, source, rel)

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


def extract_elements(support: TreeSitterSupport, source: bytes, rel: str) -> List[CodeElement]:
    """Definitions and call references from one parsed file."""
    from tree_sitter import QueryCursor

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
        elements.append(el)
        spans.append((d.node.start_byte, d.node.end_byte, el))

    # Each call belongs to every element whose span contains it (a class collects its methods' calls,
    # as Python's ast.walk over a class body does).
    top_level: Set[str] = set()
    top_level_member: Set[str] = set()
    for ref, name_node, kind in calls:
        callee = name_node.text.decode("utf-8", "replace")
        through_object = kind in ("call", "send") and _through_object(ref, name_node)
        owners = [el for (a, b, el) in spans if a <= ref.start_byte < b]
        for el in owners:
            if callee not in el.calls:
                el.calls.append(callee)
            if through_object and callee not in el.member_calls:
                el.member_calls.append(callee)
        if not owners:
            top_level.add(callee)
            if through_object:
                top_level_member.add(callee)

    # Test files whose tests are calls, not definitions (describe/it, RSpec): one node for the file's
    # top-level code, so tests-for can reach what it calls.
    if is_test_file and top_level:
        stem = Path(rel).name
        el = CodeElement(name=f"<{stem}>", element_type="module", file=rel, line=1, signature=rel,
                         calls=sorted(top_level), simple_name=f"<{stem}>")
        el.end_line = None
        el.member_calls = sorted(top_level_member)
        el.is_test = True
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
