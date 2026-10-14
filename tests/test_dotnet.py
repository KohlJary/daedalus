""".NET (C#, Razor/Blazor, Unity) in the palace and Ariadne's verifier."""

import shutil
import subprocess
import sys

import pytest

from daedalus.ariadne.diff_bus import Diff
from daedalus.ariadne.test_runners import plan_runs
from daedalus.ariadne.verification import CausalSliceVerifier
from daedalus.labyrinth import languages
from daedalus.labyrinth.orphan_detector import detect_orphans
from daedalus.labyrinth.query import build_query_graph, resolve_symbol
from daedalus.labyrinth.query import tests_reaching as reaching

pytest.importorskip("tree_sitter")
pytest.importorskip("tree_sitter_c_sharp")

NOOP = [sys.executable, "-c", "pass"]


def write(root, files):
    for rel, text in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text)


def graph(tmp_path, files):
    write(tmp_path, files)
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    languages._registry = None
    return build_query_graph(tmp_path).graph


def test_namespaces_are_scopes_and_program_cs_is_a_node(tmp_path):
    g = graph(tmp_path, {
        "Shop/Money.cs": "namespace Shop.Billing;\npublic class Money { public static string Format(int c) => c.ToString(); }\n",
        "Program.cs": "using Shop.Billing;\nvar text = Money.Format(5);\nSystem.Console.WriteLine(text);\n",
    })
    assert not any(n.endswith(".Billing") or n.endswith(".Shop") for n in g.nodes)  # no namespace nodes
    assert g.nodes["Program.cs.<Program.cs>"].calls == ["Shop.Money.cs.Money.Format"]


def test_using_directives_pick_the_visible_type(tmp_path):
    g = graph(tmp_path, {
        "A/Fmt.cs": "namespace Shop.A { public class Fmt { public static string Run() => \"\"; } }\n",
        "B/Fmt.cs": "namespace Shop.B { public class Fmt { public static string Run() => \"\"; } }\n",
        "Use.cs": "using Shop.B;\nnamespace App { public class Use { public void Go() { Fmt.Run(); new Fmt(); } } }\n",
        "Alias.cs": "using F = Shop.A.Fmt;\nnamespace App { public class Alias { public void Go() { F.Run(); } } }\n",
    })
    assert sorted(g.nodes["Use.cs.Use.Go"].calls) == ["B.Fmt.cs.Fmt", "B.Fmt.cs.Fmt.Run"]
    assert g.nodes["Alias.cs.Alias.Go"].calls == ["A.Fmt.cs.Fmt.Run"]


def test_partial_classes_and_xunit_tests(tmp_path):
    g = graph(tmp_path, {
        "Shop/Cart.cs": "namespace Shop;\npublic partial class Cart { public int Total() => Tax(1); }\n",
        "Shop/Cart.Tax.cs": "namespace Shop;\npublic partial class Cart { int Tax(int x) => x * 2; }\n",
        "Shop.Tests/CartTests.cs": "using Shop;\nusing Xunit;\nnamespace Shop.Tests;\n"
                                   "public class CartTests {\n  [Fact]\n  public void Totals() { Assert.Equal(2, new Cart().Total()); }\n"
                                   "  [Theory]\n  [InlineData(1)]\n  public void More(int x) { new Cart().Total(); }\n  void Helper() {}\n}\n",
    })
    tests = reaching(g, resolve_symbol(g, "Cart.Tax"))
    assert tests == ["Shop.Tests.CartTests.cs.CartTests.More", "Shop.Tests.CartTests.cs.CartTests.Totals"]
    assert g.nodes["Shop.Tests.CartTests.cs.CartTests.Helper"].is_test is True  # in a *.Tests project dir


BLAZOR = {
    "App/Pages/Counter.razor": "@page \"/counter\"\n<h1>Counter</h1>\n<p>Count: @currentCount</p>\n"
                               "<button @onclick=\"IncrementCount\">Click</button>\n<PriceTag Value=\"@Format(currentCount)\" />\n\n"
                               "@code {\n    private int currentCount = 0;\n\n    private void IncrementCount()\n    {\n"
                               "        currentCount = Clamp(currentCount + 1);\n    }\n\n"
                               "    private string Format(int x) => x.ToString();\n    private int Clamp(int x) => x;\n}\n",
    "App/Shared/PriceTag.razor": "<span>@Value</span>\n@code { [Parameter] public string Value { get; set; } = \"\"; }\n",
    "App.Tests/CounterTests.cs": "using Bunit;\nusing Xunit;\npublic class CounterTests : TestContext {\n"
                                 "  [Fact]\n  public void Clicks() { var cut = RenderComponent<Counter>(); cut.Find(\"button\").Click(); }\n}\n",
}


def test_blazor_components_methods_and_markup_references(tmp_path):
    g = graph(tmp_path, BLAZOR)
    counter = g.nodes["App.Pages.Counter.razor.Counter"]
    assert {"App.Pages.Counter.razor.Counter.IncrementCount", "App.Pages.Counter.razor.Counter.Format",
            "App.Shared.PriceTag.razor.PriceTag"} <= set(counter.calls)  # @onclick, @Format(...), <PriceTag />
    inc = g.nodes["App.Pages.Counter.razor.Counter.IncrementCount"]
    assert (inc.line, g.end_lines[inc.id]) == (10, 13)  # mapped back to the .razor file
    assert inc.calls == ["App.Pages.Counter.razor.Counter.Clamp"]
    # bUnit renders the component through a generic type argument; the test reaches its methods
    assert reaching(g, resolve_symbol(g, "Counter.Clamp")) == ["App.Tests.CounterTests.cs.CounterTests.Clicks"]


def test_razor_anchors_find_their_lines(tmp_path):
    write(tmp_path, BLAZOR)
    languages._registry = None
    razor = languages.get_language_registry().get_by_extension(tmp_path / "x.razor")
    source = (tmp_path / "App/Pages/Counter.razor").read_text()
    for el in razor.analyze_file(tmp_path / "App/Pages/Counter.razor", tmp_path):
        assert razor.generate_anchor_pattern(el).find_line(source) == el.line, el.name


def test_unity_and_aspnet_entry_points_are_not_orphans(tmp_path):
    write(tmp_path, {
        "Assets/Player.cs": "using UnityEngine;\npublic class Player : MonoBehaviour {\n  void Start() {}\n  void Update() { Move(); }\n"
                            "  void Move() {}\n  void Unused() {}\n}\n",
        "Assets/Tests/PlayerTests.cs": "using NUnit.Framework;\npublic class PlayerTests {\n  [UnityTest]\n  public System.Collections.IEnumerator Moves() { yield return null; }\n}\n",
        "Api/Controllers/OrdersController.cs": "public class OrdersController : ControllerBase {\n  public IActionResult Get() => Ok();\n}\n",
    })
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    languages._registry = None
    summary = detect_orphans(tmp_path, include_medium_confidence=True)
    flagged = {r.simple_name for reports in summary.orphans_by_module.values() for r in reports}
    assert "Unused" in flagged
    assert not {"Start", "Update", "Moves", "Get"} & flagged


def test_dotnet_runs_target_the_owning_test_project(tmp_path):
    write(tmp_path, {"Shop.Tests/Shop.Tests.csproj": "<Project/>", "Game/ProjectSettings/ProjectVersion.txt": "m_EditorVersion: 2022.3",
                     "Game/Assembly-CSharp.csproj": "<Project/>"})
    languages._registry = None
    runs, problems = plan_runs(tmp_path, ["Shop.Tests/CartTests.cs", "Shop.Tests/Sub/TaxTests.cs",
                                          "Game/Assets/Tests/PlayerTests.cs"], ["pytest"])
    assert [r.command for r in runs] == [["dotnet", "test", "Shop.Tests/Shop.Tests.csproj", "--nologo", "--filter",
                                          "FullyQualifiedName~CartTests|FullyQualifiedName~TaxTests"]]
    assert problems and "Unity" in problems[0]


# --- End to end with the .NET SDK -------------------------------------------------------------------------

CSPROJ = """<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup><TargetFramework>net{v}.0</TargetFramework><Nullable>enable</Nullable><ImplicitUsings>enable</ImplicitUsings></PropertyGroup>
</Project>
"""
TEST_CSPROJ = """<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup><TargetFramework>net{v}.0</TargetFramework><Nullable>enable</Nullable><ImplicitUsings>enable</ImplicitUsings>
    <IsPackable>false</IsPackable></PropertyGroup>
  <ItemGroup>
    <PackageReference Include="Microsoft.NET.Test.Sdk" Version="17.12.0" />
    <PackageReference Include="xunit" Version="2.9.2" />
    <PackageReference Include="xunit.runner.visualstudio" Version="2.8.2" />
  </ItemGroup>
  <ItemGroup><ProjectReference Include="../Shop/Shop.csproj" /></ItemGroup>
</Project>
"""
CALC = "namespace Shop;\npublic static class Calc\n{\n    public static int Double(int x) => Helper(x);\n    static int Helper(int x) => x * 2;\n}\n"


def _sdk_major():
    if shutil.which("dotnet") is None:
        return None
    out = subprocess.run(["dotnet", "--list-sdks"], capture_output=True, text=True).stdout
    majors = sorted({int(line.split(".")[0]) for line in out.splitlines() if line[:1].isdigit()})
    return majors[-1] if majors and majors[-1] >= 8 else None


def _git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True).stdout


@pytest.fixture(scope="module")
def dotnet_repo(tmp_path_factory):
    major = _sdk_major()
    if major is None:
        pytest.skip("needs the .NET 8+ SDK")
    repo = tmp_path_factory.mktemp("dn") / "repo"
    write(repo, {
        "Shop/Shop.csproj": CSPROJ.format(v=major),
        "Shop/Calc.cs": CALC,
        "Shop.Tests/Shop.Tests.csproj": TEST_CSPROJ.format(v=major),
        "Shop.Tests/CalcTests.cs": "using Shop;\nusing Xunit;\nnamespace Shop.Tests;\npublic class CalcTests\n{\n"
                                   "    [Fact]\n    public void Doubles() => Assert.Equal(4, Calc.Double(2));\n}\n",
        ".gitignore": "bin/\nobj/\n",
    })
    _git(repo.parent, "init", "-q", str(repo))
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "base")
    r = subprocess.run(["dotnet", "restore", "Shop.Tests"], cwd=repo, capture_output=True, text=True, timeout=600)
    if r.returncode != 0:
        pytest.skip(f"dotnet restore failed (offline without cached packages?): {r.stdout[-300:]}")
    languages._registry = None
    return repo


def _diff(repo, path, content):
    original = (repo / path).read_text()
    (repo / path).write_text(content)
    text = _git(repo, "diff", "--", path)
    (repo / path).write_text(original)
    return Diff.from_git_diff("wp-1", "w-1", text, "change")


def test_dotnet_change_is_built_and_tested_by_the_tests_that_reach_it(dotnet_repo):
    result = CausalSliceVerifier(dotnet_repo, typecheck_cmd=NOOP, lint_cmd=NOOP).verify(
        _diff(dotnet_repo, "Shop/Calc.cs", CALC.replace("x * 2", "x + x")))
    assert result.passed, result.to_dict()
    assert "Shop.Tests/CalcTests.cs" in result.tests_selected_by["palace"]
    assert result.tests_run == 1 and any("--filter FullyQualifiedName~CalcTests" in c for c in result.test_commands)


def test_dotnet_type_errors_fail_the_build_gate(dotnet_repo):
    broken = CALC.replace("static int Helper(int x) => x * 2;", "static int Helper(int x) => \"two\";")
    result = CausalSliceVerifier(dotnet_repo, typecheck_cmd=NOOP, lint_cmd=NOOP).verify(_diff(dotnet_repo, "Shop/Calc.cs", broken))
    assert result.compile_passed  # it parses; only the compiler knows a string isn't an int
    assert not result.typecheck_passed and any("CS0029" in e for e in result.typecheck_errors)
    assert not result.passed


def test_dotnet_failing_test_fails_verification(dotnet_repo):
    result = CausalSliceVerifier(dotnet_repo, typecheck_cmd=NOOP, lint_cmd=NOOP, build_gate=False).verify(
        _diff(dotnet_repo, "Shop/Calc.cs", CALC.replace("x * 2", "x * 3")))
    assert not result.passed and result.tests_failed == 1


def test_a_method_named_like_a_type_keeps_its_own_link(tmp_path):
    g = graph(tmp_path, {
        "T.cs": "namespace N { public class Total { } public class Order { } }\n",
        "Y.cs": "namespace N { public class Two {\n  int Total() => 1;\n  int Order() => 2;\n"
                "  public int U() => Total();\n  public int V() => Order();\n} }\n",
    })
    assert "Y.cs.Two.Total" in g.nodes["Y.cs.Two.U"].calls  # its own method, not only `new Total()`
    assert "Y.cs.Two.Order" in g.nodes["Y.cs.Two.V"].calls


def test_razor_blocks_survive_braces_in_strings_and_comments(tmp_path):
    write(tmp_path, {"Page.razor": "<h1>@Title()</h1>\n@code {\n    string close = \"}\";\n    char open = '{';\n"
                                   "    // a stray } in a comment\n    string Title() => \"x\";\n    void Save() { }\n}\n"})
    languages._registry = None
    razor = languages.get_language_registry().get_by_extension(tmp_path / "Page.razor")
    names = {e.name for e in razor.analyze_file(tmp_path / "Page.razor", tmp_path)}
    assert {"Page.Title", "Page.Save"} <= names


def test_razor_markup_references_in_lambdas_and_control_flow():
    from daedalus.labyrinth.razor import markup_references
    markup = ('<button @onclick="@(() => Save())">s</button>\n<button @onclick="async () => await Load()">l</button>\n'
              '<input @bind="name" />\n@foreach (var item in GetItems())\n{\n  <span>@item.ToString()</span>\n}\n'
              '@if (IsAdmin()) { <Layout.Header /> }\n<Grid<int> />\n')
    refs = set(markup_references(markup))
    assert {"Save", "Load", "GetItems", "IsAdmin", "Header", "Grid"} <= refs
    assert not {"name", "async", "ToString", "foreach", "if"} & refs


def test_build_gate_reports_what_it_could_not_build(tmp_path):
    from daedalus.ariadne.test_runners import dotnet_build
    write(tmp_path, {"tools/Loose.cs": "class Loose {}\n",
                     "Game/ProjectSettings/ProjectVersion.txt": "m_EditorVersion: 2022.3",
                     "Game/Assembly-CSharp.csproj": "<Project/>", "Game/Assets/P.cs": "class P {}\n"})
    passed, errors, skipped = dotnet_build(tmp_path, ["tools/Loose.cs", "Game/Assets/P.cs"])
    assert passed and errors == []
    assert any("tools/Loose.cs (no .csproj owns it)" in s for s in skipped)
    assert any("Unity project" in s for s in skipped)


def test_dotnet_filter_uses_the_classes_the_file_defines(tmp_path):
    write(tmp_path, {"Shop.Tests/Shop.Tests.csproj": "<Project/>",
                     "Shop.Tests/CalcTests.cs": "public class MathSpecs { [Fact] public void Adds() {} }\n"})
    languages._registry = None
    runs, _ = plan_runs(tmp_path, ["Shop.Tests/CalcTests.cs"], ["pytest"])
    assert runs[0].command[-1] == "FullyQualifiedName~MathSpecs"
