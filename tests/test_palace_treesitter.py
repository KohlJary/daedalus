"""Tree-sitter frontend: palace queries on languages other than Python (daedalus[palace])."""

import logging
import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner

from daedalus.labyrinth import languages, treesitter
from daedalus.labyrinth.query import build_query_graph, convention_tests, resolve_symbol
from daedalus.labyrinth.query import tests_reaching as reaching

FILES = {
    "src/cart.ts": """import { tax } from "./tax";
export interface Priced { price(): number }
export class Cart {
  private items: Priced[] = [];
  constructor(private rate: number) { this.reset(); }
  reset(): void { this.items = []; }
  total(): number {
    return this.items.reduce((s, i) => s + i.price(), 0) * tax(this.rate);
  }
}
export const makeCart = (rate: number): Cart => new Cart(rate);
""",
    "src/tax.ts": "export function tax(rate: number): number { return 1 + rate; }\n",
    "src/cart.test.ts": """import { makeCart } from "./cart";
describe("cart", () => {
  it("totals", () => { expect(makeCart(0.1).total()).toBe(0); });
});
""",
    "pkg/calc.go": """package pkg

// Calc adds things.
type Calc struct{ n int }

func New() *Calc { return &Calc{} }

func (c *Calc) Add(x int) int { c.n += helper(x); return c.n }

func helper(x int) int { return x * 2 }
""",
    "pkg/calc_test.go": """package pkg

import "testing"

func TestAdd(t *testing.T) { if New().Add(1) != 2 { t.Fatal("bad") } }
func setup() {}
""",
    "rs/src/lib.rs": """pub struct Stack { v: Vec<i32> }
impl Stack {
    pub fn new() -> Self { Stack { v: Vec::new() } }
    pub fn push(&mut self, x: i32) { self.v.push(clamp(x)); }
}
fn clamp(x: i32) -> i32 { x.min(10) }
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn pushes() { let mut s = Stack::new(); s.push(3); }
}
""",
    "java/src/main/java/app/Greeter.java": """package app;
public class Greeter {
    public Greeter() { init(); }
    private void init() {}
    public String greet(String n) { return format(n); }
    static String format(String n) { return "hi " + n; }
}
""",
    "java/src/test/java/app/GreeterTest.java": """package app;
class GreeterTest {
    @Test void greets() { new Greeter().greet("a"); }
}
""",
    "rb/lib/bank.rb": """class Bank
  def initialize
    @b = 0
  end
  def deposit(x)
    log(x)
  end
  def log(x); end
end
""",
    "rb/spec/bank_spec.rb": """describe Bank do
  it "deposits" do
    Bank.new.deposit(3)
  end
end
""",
    "py/paths.py": """class Paths:
    def resolve(self, p):
        return p
""",
    "web/render.mjs": """import path from "node:path";
export function resolveFile(p) { return path.resolve(p); }
""",
}


def _needs(*wheels):
    for w in ("tree_sitter",) + wheels:
        pytest.importorskip(w)


@pytest.fixture(scope="module")
def repo(tmp_path_factory):
    root = tmp_path_factory.mktemp("polyglot")
    for rel, text in FILES.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text)
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    return root


@pytest.fixture(scope="module")
def graph(repo):
    languages._registry = None  # pick up whatever grammars are installed in this environment
    return build_query_graph(repo).graph


def _tests_for(graph, symbol):
    ids = resolve_symbol(graph, symbol)
    assert ids, f"{symbol} not found"
    return reaching(graph, ids)


def test_typescript_classes_methods_spans_and_calls(graph):
    _needs("tree_sitter_typescript", "tree_sitter_javascript")
    total = graph.nodes["src.cart.ts.Cart.total"]
    assert total.type == "method" and total.line == 7 and graph.end_lines["src.cart.ts.Cart.total"] == 9
    assert "src.tax.ts.tax" in total.calls  # a plain call resolves across files by name
    assert graph.nodes["src.cart.ts.Cart"].type == "class"
    assert "src.cart.ts.makeCart" in graph.nodes  # const arrow functions are definitions


def test_jest_style_test_file_reaches_what_it_calls(graph):
    _needs("tree_sitter_typescript", "tree_sitter_javascript")
    # describe/it bodies are calls, not definitions: the file's top-level code is one test node
    assert _tests_for(graph, "tax") == ["src.cart.test.ts.<cart.test.ts>"]
    assert _tests_for(graph, "Cart.reset") == ["src.cart.test.ts.<cart.test.ts>"]


def test_go_receivers_and_test_functions(graph):
    _needs("tree_sitter_go")
    assert "pkg.calc.go.Calc.Add" in graph.nodes  # func (c *Calc) Add -> a method of Calc
    assert graph.nodes["pkg.calc.go.Calc.Add"].calls == ["pkg.calc.go.helper"]
    assert _tests_for(graph, "helper") == ["pkg.calc_test.go.TestAdd"]
    assert graph.nodes["pkg.calc_test.go.setup"].is_test is False  # in a _test.go file, but not Test*


def test_rust_impl_blocks_and_test_attributes(graph):
    _needs("tree_sitter_rust")
    assert "rs.src.lib.rs.Stack.push" in graph.nodes  # impl Stack { fn push } -> a method of Stack
    assert _tests_for(graph, "clamp") == ["rs.src.lib.rs.tests.pushes"]  # #[test] inside mod tests


def test_java_test_methods_by_location(graph):
    _needs("tree_sitter_java")
    assert _tests_for(graph, "Greeter.format") == ["java.src.test.java.app.GreeterTest.java.GreeterTest.greets"]


def test_ruby_spec_file(graph):
    _needs("tree_sitter_ruby")
    assert _tests_for(graph, "Bank.deposit") == ["rb.spec.bank_spec.rb.<bank_spec.rb>"]
    assert "rb.lib.bank.rb.Bank.log" in graph.nodes["rb.lib.bank.rb.Bank.deposit"].calls


def test_names_do_not_resolve_across_languages(graph):
    _needs("tree_sitter_javascript")
    # path.resolve() in JavaScript is not Python's Paths.resolve
    assert graph.nodes["py.paths.Paths.resolve"].called_by == []
    assert "py.paths.Paths.resolve" not in graph.nodes["web.render.mjs.resolveFile"].calls


def test_convention_tests_per_language(repo):
    _needs("tree_sitter_typescript", "tree_sitter_go", "tree_sitter_java")
    languages._registry = None
    found = convention_tests(repo, ["src/cart.ts", "pkg/calc.go", "java/src/main/java/app/Greeter.java"])
    assert found == ["java/src/test/java/app/GreeterTest.java", "pkg/calc_test.go", "src/cart.test.ts"]


def test_anchor_patterns_find_their_definitions(repo):
    _needs()
    languages._registry = None
    registry = languages.get_language_registry()
    checked = 0
    for rel in FILES:
        support = registry.get_by_extension(Path(rel))
        if not isinstance(support, treesitter.TreeSitterSupport) or support.source is None:
            continue
        source = (repo / rel).read_text()
        for el in support.analyze_file(repo / rel, repo):
            if el.element_type == "module":
                continue
            assert support.generate_anchor_pattern(el).find_line(source) == el.line, (rel, el.name)
            checked += 1
    assert checked > 0


def test_member_calls_are_told_apart(tmp_path):
    _needs("tree_sitter_typescript", "tree_sitter_javascript")
    (tmp_path / "a.ts").write_text("function helper() {}\nexport function run(o: any) { helper(); o.save(); }\n")
    support = treesitter.TreeSitterSupport(next(g for g in treesitter.GRAMMARS if g.name == "TypeScript"))
    run = next(e for e in support.analyze_file(tmp_path / "a.ts", tmp_path) if e.name == "run")
    assert sorted(run.calls) == ["helper", "save"] and run.member_calls == ["save"]


def test_a_grammar_that_cannot_load_is_skipped_with_one_warning(tmp_path, caplog):
    _needs()
    (tmp_path / "x.zz").write_text("whatever")
    support = treesitter.TreeSitterSupport(treesitter.Grammar("Nope", [".zz"], wheel="tree_sitter_nope_missing"))
    with caplog.at_level(logging.WARNING):
        assert support.analyze_file(tmp_path / "x.zz", tmp_path) == []
        assert support.analyze_file(tmp_path / "x.zz", tmp_path) == []
    assert sum("Nope unavailable" in r.message for r in caplog.records) == 1


def test_without_tree_sitter_only_python_and_the_regex_analyzer_remain(monkeypatch):
    monkeypatch.setattr(treesitter, "grammar_source", lambda g: None)
    registry = languages.LanguageRegistry()
    assert registry.get_by_extension(Path("a.go")) is None
    assert registry.get_by_extension(Path("a.ts")).name == "TypeScript"
    assert isinstance(registry.get_by_extension(Path("a.ts")), languages.TypeScriptSupport)
    assert registry.get_by_extension(Path("a.py")).name == "Python"


def test_palace_languages_command():
    from daedalus.cli.main import main

    result = CliRunner().invoke(main, ["palace", "languages"])
    assert result.exit_code == 0, result.output
    assert "Python" in result.output


def test_go_builtin_calls_do_not_link_to_methods(tmp_path):
    _needs("tree_sitter_go")
    (tmp_path / "h.go").write_text("package h\ntype History struct{ l []int }\n"
                                   "func (h *History) append(x int) { h.l = append(h.l, x) }\n"
                                   "func add(xs []int) []int { return append(xs, 1) }\n"
                                   "func use(h *History) { h.append(2) }\n")
    languages._registry = None
    g = build_query_graph(tmp_path).graph
    # append(...) is Go's builtin: a plain call can't reach a method; h.append(...) can
    assert g.nodes["h.go.History.append"].called_by == ["h.go.use"]


def test_build_output_and_minified_files_are_skipped(tmp_path):
    _needs("tree_sitter_javascript")
    (tmp_path / "app.js").write_text("export function real() {}\n")
    (tmp_path / ".next" / "static").mkdir(parents=True)
    (tmp_path / ".next" / "static" / "chunk.js").write_text("function generated() {}\n")
    (tmp_path / "lib.min.js").write_text("function minified() {}\n")
    languages._registry = None
    g = build_query_graph(tmp_path).graph
    assert sorted(n.simple_name for n in g.nodes.values()) == ["real"]


def test_git_ignored_paths_are_skipped_but_tracked_files_are_not(tmp_path):
    (tmp_path / "keep.py").write_text("def kept():\n    pass\n")
    (tmp_path / "clone").mkdir()
    (tmp_path / "clone" / "lib.py").write_text("def third_party():\n    pass\n")
    (tmp_path / "gen.py").write_text("def tracked_anyway():\n    pass\n")
    (tmp_path / ".gitignore").write_text("clone/\ngen.py\n")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "-f", "gen.py"], cwd=tmp_path, check=True)  # tracked despite the ignore rule
    g = build_query_graph(tmp_path).graph
    assert sorted(n.simple_name for n in g.nodes.values()) == ["kept", "tracked_anyway"]


def _graph(tmp_path, files):
    for rel, text in files.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(text)
    languages._registry = None
    return build_query_graph(tmp_path).graph


def test_rust_path_calls_link_and_integration_tests_reach_them(tmp_path):
    _needs("tree_sitter_rust")
    g = _graph(tmp_path, {
        "src/lib.rs": "pub struct S;\nimpl S { pub fn new() -> S { S } }\npub mod m { pub fn inner() {} }\n"
                      "pub fn user() { let _s = S::new(); m::inner(); }\n"
                      "#[cfg(not(test))]\nfn only_prod() {}\n"
                      "#[cfg(test)]\nmod tests {\n    fn fixture() {}\n    #[tokio::test]\n    async fn runs() { fixture(); super::user(); }\n}\n",
        "tests/it.rs": "#[test]\nfn integration() { mylib::user(); }\n",
    })
    assert set(g.nodes["src.lib.rs.user"].calls) == {"src.lib.rs.S.new", "src.lib.rs.m.inner"}
    assert g.nodes["src.lib.rs.only_prod"].is_test is False      # cfg(not(test)) is production code
    assert g.nodes["src.lib.rs.tests.fixture"].is_test is False  # a helper in mod tests, not a test
    assert _tests_for(g, "S.new") == ["src.lib.rs.tests.runs", "tests.it.rs.integration"]


def test_go_generic_receivers_name_the_type_not_the_parameter(tmp_path):
    _needs("tree_sitter_go")
    g = _graph(tmp_path, {"stack.go": "package s\ntype Stack[T any] struct{ v []T }\n"
                                      "func (s *Stack[T]) Push(x T) { s.v = append(s.v, x) }\n"
                                      "type Map[K comparable, V any] struct{}\nfunc (m Map[K, V]) Pop() {}\n"})
    assert "stack.go.Stack.Push" in g.nodes and "stack.go.Map.Pop" in g.nodes


def test_java_and_csharp_test_annotations_count_outside_test_dirs(tmp_path):
    _needs("tree_sitter_java", "tree_sitter_c_sharp")
    g = _graph(tmp_path, {
        "src/main/java/Calc.java": "class Calc { int add(int a) { return a; } }\n",
        "src/it/java/CalcIT.java": "class CalcIT {\n  @Test\n  void adds() { new Calc().add(1); }\n  void helper() {}\n}\n",
        "Calc.cs": "class Calc { public int Add(int x) { return Helper(x); } static int Helper(int x) { return x; } }\n"
                   "class CalcChecks { [Fact] public void Adds() { new Calc().Add(1); } }\n",
    })
    assert _tests_for(g, "Calc.add") == ["src.it.java.CalcIT.java.CalcIT.adds"]
    assert g.nodes["src.it.java.CalcIT.java.CalcIT.helper"].is_test is False
    assert g.nodes["Calc.cs.Calc.Add"].calls == ["Calc.cs.Calc.Helper"]  # plain calls, which upstream C# tags omit
    assert _tests_for(g, "Calc.Helper") == ["Calc.cs.CalcChecks.Adds"]


def test_same_stem_in_two_languages_keeps_both(tmp_path):
    _needs("tree_sitter_typescript", "tree_sitter_javascript")
    g = _graph(tmp_path, {"view.py": "def render():\n    pass\n", "view.ts": "export function render() {}\n",
                          "tests/test_view.py": "from view import render\ndef test_render():\n    render()\n"})
    assert "view.render" in g.nodes and "view.ts.render" in g.nodes
    assert _tests_for(g, "view.render") == ["tests.test_view.test_render"]


def test_python_files_ignore_the_other_ecosystem_skips(tmp_path):
    g = _graph(tmp_path, {"pkg/vendor/v.py": "def vendored():\n    pass\n", "target/t.py": "def targeted():\n    pass\n",
                          "big.py": "def big():\n    pass\n" + "# padding\n" * 120_000})
    assert {"vendored", "targeted", "big"} <= {n.simple_name for n in g.nodes.values()}


def test_too_old_tree_sitter_warns_and_falls_back(monkeypatch, caplog, tmp_path):
    _needs("tree_sitter_typescript", "tree_sitter_javascript")
    import tree_sitter
    monkeypatch.delattr(tree_sitter, "QueryCursor")
    with caplog.at_level(logging.WARNING):
        g = _graph(tmp_path, {"a.ts": "export function viaRegex() {}\n"})
    assert any("too old" in r.message for r in caplog.records)
    assert "a.ts.viaRegex" in g.nodes  # the regex TypeScript analyzer took over
