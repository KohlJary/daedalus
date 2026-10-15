"""Issue #43: C# palace precision (receiver types, innermost callers), Windows paths, per-language run
commands, and the install check."""

import json
import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner

from daedalus.labyrinth import languages
from daedalus.labyrinth.query import build_query_graph, nodes_in_file

pytest.importorskip("tree_sitter")
pytest.importorskip("tree_sitter_c_sharp")

STORES = """namespace Shop;
public interface IInventoryStore { Item? Find(int sku); }
public interface IOrderStore     { Order? Find(int orderId); }
public class Restocker(IInventoryStore inventory) { void Run(int sku) => inventory.Find(sku); }
public class Shipper(IOrderStore orders)          { void Run(int id)  => orders.Find(id); }
public class SqlInventory : IInventoryStore { public Item? Find(int sku) => null; }
public class Sorter { public void Find(int x) {} }
public class Fielded {
    private readonly IOrderStore _orders;
    public Fielded(IOrderStore orders) { _orders = orders; }
    void Go() { this._orders.Find(1); }
    void Local() { var inv = new SqlInventory(); inv.Find(2); }
}
public class Logs(Microsoft.Extensions.Logging.ILogger log) { void W() { log.LogInformation("x"); } }
public static class LogExtensions { public static void Audit(this Microsoft.Extensions.Logging.ILogger l) {} }
public class Audited(Microsoft.Extensions.Logging.ILogger log) { void A() { log.Audit(); } }
public class Outer { public class Inner { void Go(Shipper s) { s.Run(1); } } }
"""


@pytest.fixture()
def g(tmp_path):
    (tmp_path / "Stores.cs").write_text(STORES)
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    languages._registry = None
    return build_query_graph(tmp_path).graph


def callers(g, node):
    return sorted(g.nodes[f"Stores.cs.{node}"].called_by)


def test_calls_resolve_through_the_receivers_declared_type(g):
    assert callers(g, "IInventoryStore.Find") == ["Stores.cs.Restocker.Run"]
    assert callers(g, "IOrderStore.Find") == ["Stores.cs.Fielded.Go", "Stores.cs.Shipper.Run"]  # also this._orders
    # an implementation is reachable through its interface; an unrelated Find is not
    assert callers(g, "SqlInventory.Find") == ["Stores.cs.Fielded.Local", "Stores.cs.Restocker.Run"]
    assert callers(g, "Sorter.Find") == []


def test_outside_types_link_nothing_but_extension_methods_still_resolve(g):
    assert g.nodes["Stores.cs.Logs.W"].calls == []
    assert g.nodes["Stores.cs.Audited.A"].calls == ["Stores.cs.LogExtensions.Audit"]


def test_only_the_innermost_method_is_a_caller(g):
    assert callers(g, "Shipper.Run") == ["Stores.cs.Inner.Go"]  # not Outer, not Inner


def test_windows_style_paths_find_the_files_symbols(g, tmp_path):
    assert nodes_in_file(g, "Stores.cs") == nodes_in_file(g, ".\\Stores.cs".lstrip(".\\"))
    (tmp_path / "My Tools.Core" / "Billing").mkdir(parents=True)
    (tmp_path / "My Tools.Core" / "Billing" / "Invoice.cs").write_text("namespace B; public class Invoice { void Total() {} }\n")
    languages._registry = None
    g2 = build_query_graph(tmp_path).graph
    assert nodes_in_file(g2, "My Tools.Core\\Billing\\Invoice.cs") == nodes_in_file(g2, "My Tools.Core/Billing/Invoice.cs") != []


def test_tests_for_suggests_dotnet_test_for_csharp(tmp_path, monkeypatch):
    from daedalus.cli.main import main

    (tmp_path / "Shop").mkdir()
    (tmp_path / "Shop" / "Calc.cs").write_text("namespace Shop; public static class Calc { public static int Add(int a) => a; }\n")
    (tmp_path / "Shop.Tests").mkdir()
    (tmp_path / "Shop.Tests" / "Shop.Tests.csproj").write_text("<Project/>")
    (tmp_path / "Shop.Tests" / "CalcTests.cs").write_text(
        "using Shop;\nnamespace Shop.Tests;\npublic class CalcTests { [Fact] public void Adds() { Calc.Add(1); } }\n")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    languages._registry = None
    monkeypatch.chdir(tmp_path)
    out = CliRunner().invoke(main, ["palace", "tests-for", "Shop\\Calc.cs"]).output
    assert "Shop.Tests/CalcTests.cs" in out
    assert "Run: dotnet test Shop.Tests/Shop.Tests.csproj --nologo --filter" in out and "FullyQualifiedName~CalcTests" in out
    assert "pytest" not in out
    out = CliRunner().invoke(main, ["palace", "impact", "Calc.Add", "--tests"]).output
    assert "dotnet test" in out and "pytest" not in out


def test_install_check_flags_a_stale_install_and_missing_grammars(tmp_path, monkeypatch):
    from daedalus import doctor

    (tmp_path / "pyproject.toml").write_text('[project]\nname = "daedalus-cli"\nversion = "0.3.0"\n')
    found = doctor.check_install(lambda: ("0.1.3", tmp_path, False))
    assert [f.name for f in found] == ["install-stale"]
    assert "0.1.3" in found[0].message and "0.3.0" in found[0].message
    assert doctor.check_install(lambda: ("0.3.0", tmp_path, True)) == []
    assert doctor.check_install(lambda: ("0.3.0", None, False)) == []  # installed from PyPI: nothing to compare

    import importlib.util
    real = importlib.util.find_spec
    monkeypatch.setattr(importlib.util, "find_spec", lambda name, *a: None if name == "tree_sitter" else real(name, *a))
    assert [f.name for f in doctor.check_install(lambda: ("0.3.0", None, False))] == ["palace-grammars-missing"]


def test_inherited_methods_resolve_to_the_nearest_ancestor(tmp_path):
    (tmp_path / "A.cs").write_text("namespace S;\npublic class Base { public void Save() {} }\npublic class Mid : Base {}\n"
                                   "public class Leaf : Mid { }\npublic class Over : Mid { public new void Save() {} }\n"
                                   "public class Use(Mid m, Leaf l) { void A() { m.Save(); } void B() { l.Save(); } }\n")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    languages._registry = None
    g = build_query_graph(tmp_path).graph
    assert sorted(g.nodes["A.cs.Use.A"].calls) == ["A.cs.Base.Save", "A.cs.Over.Save"]  # inherited, plus an override below
    assert g.nodes["A.cs.Use.B"].calls == ["A.cs.Base.Save"]


def _graph(tmp_path, text):
    (tmp_path / "a.cs").write_text(text)
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    languages._registry = None
    return build_query_graph(tmp_path).graph


BASE = "namespace N;\npublic class A { public void Go() {} }\npublic class B { public void Go() {} }\n"


@pytest.mark.parametrize("body, expected", [
    # untyped declarations shadow the field `A x`, so the name rule decides (both Go's)
    ("A x; void M(System.Collections.Generic.List<B> bs) { bs.ForEach(x => x.Go()); }", {"A.Go", "B.Go"}),
    ("A x; void M(object o) { if (o is B x) x.Go(); }", {"B.Go"}),
    ("A x; void M() { var x = Make(); x.Go(); } object Make() => null;", {"A.Go", "B.Go"}),
    ("A x; void M(B[] xs) { foreach (var x in xs) x.Go(); }", {"A.Go", "B.Go"}),
    ("A x; void M() { Try(out var x); x.Go(); } void Try(out B b) { b = null; }", {"A.Go", "B.Go"}),
    ("A x; void M() { var (x, y) = (new B(), 1); x.Go(); }", {"A.Go", "B.Go"}),
    # a parameter shadows a field; this.x still means the field
    ("A x; void M(B x) { this.x.Go(); }", {"A.Go"}),
    ("A x; void M(B x) { x.Go(); }", {"B.Go"}),
])
def test_declarations_shadow_and_this_means_the_field(tmp_path, body, expected):
    g = _graph(tmp_path, BASE + f"public class U {{ {body} }}\n")
    calls = {c.split("a.cs.")[1] for c in g.nodes["a.cs.U.M"].calls}
    assert expected <= calls and not ({"A.Go", "B.Go"} - expected) & calls


def test_constructor_parameters_shadow_fields(tmp_path):
    g = _graph(tmp_path, BASE + "public class U { A f; public U(B f) { f.Go(); } }\n")
    assert g.nodes["a.cs.U.U"].calls == ["a.cs.B.Go"]


def test_generic_parameters_records_and_structs(tmp_path):
    g = _graph(tmp_path, "namespace N;\npublic interface IEntity { void Id(); }\npublic class E : IEntity { public void Id() {} }\n"
                         "public class Svc<T> where T : IEntity { void A(T item) { item.Id(); } }\n"
                         "public record R(int X) { public void Go() {} }\npublic struct St { public void Go() {} }\n"
                         "public class U { void M(R r, St s) { r.Go(); s.Go(); } }\n")
    assert g.nodes["a.cs.Svc.A"].calls  # T says nothing certain: the name rule links Id
    assert sorted(g.nodes["a.cs.U.M"].calls) == ["a.cs.R.Go", "a.cs.St.Go"]


def test_inherited_overloads_and_multiline_extensions(tmp_path):
    g = _graph(tmp_path, "namespace N;\npublic class Base { public void Save(string s) {} }\n"
                         "public class D : Base { public void Save(int i) {} }\n"
                         "public static class Ext { public static void Audit(\n    this Microsoft.Extensions.Logging.ILogger l) {} }\n"
                         "public class U(Microsoft.Extensions.Logging.ILogger log, System.Threading.Tasks.Task t) {\n"
                         "  void M(D d) { d.Save(\"x\"); log.Audit(); t.Wait(); }\n}\n"
                         "public class Task { public void Wait() {} }\n")
    calls = sorted(g.nodes["a.cs.U.M"].calls)
    assert "a.cs.Base.Save" in calls and "a.cs.D.Save" in calls  # an overload in the base isn't dropped
    assert "a.cs.Ext.Audit" in calls                              # extension on an outside type, multi-line
    assert "a.cs.Task.Wait" not in calls                          # System.Threading.Tasks.Task isn't ours


def test_framework_called_methods_are_reached_from_the_class(tmp_path):
    g = _graph(tmp_path, "using UnityEngine;\npublic class Player : MonoBehaviour { void Update() { Move(); } void Move() {} }\n"
                         "public class Svc : Base, System.IDisposable { public override void Run() {} public void Dispose() {} }\n"
                         "public class Base { public virtual void Run() {} }\n"
                         "public class Cart { public void Update() {} public void Reset() {} }\n"
                         "public class T { [Fact] public void Spawns() { new Player(); } }\n")
    assert "a.cs.Player.Update" in g.nodes["a.cs.Player"].calls
    assert {"a.cs.Svc.Run", "a.cs.Svc.Dispose"} <= set(g.nodes["a.cs.Svc"].calls)  # an override; IDisposable
    assert g.nodes["a.cs.Cart.Update"].called_by == [] and g.nodes["a.cs.Cart.Reset"].called_by == []  # plain class


def test_nested_types_qualified_by_their_outer_type(tmp_path):
    g = _graph(tmp_path, "namespace N1;\npublic class Outer { public class Node { public void Run() {} } }\n"
                         "public class U { Outer.Node n; void A() { n.Run(); } }\n")
    assert g.nodes["a.cs.U.A"].calls == ["a.cs.Node.Run"]


def test_razor_components_reach_their_lifecycle_methods(tmp_path):
    (tmp_path / "Counter.razor").write_text("<h1>Hi</h1>\n@code {\n  protected override async Task OnInitializedAsync() { await Load(); }\n"
                                            "  Task Load() => Task.CompletedTask;\n}\n")
    (tmp_path / "Other.razor").write_text("@code { protected override void OnInitialized() { } }\n")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    languages._registry = None
    g = build_query_graph(tmp_path).graph
    assert "Counter.razor.Counter.OnInitializedAsync" in g.nodes["Counter.razor.Counter"].calls
    assert "Counter.razor.Counter.Load" not in g.nodes["Counter.razor.Counter"].calls  # reached through the lifecycle
    assert "Other.razor.Other.OnInitialized" not in g.nodes["Counter.razor.Counter"].calls


def test_run_lines_quote_odd_paths_and_name_the_directory(tmp_path):
    from daedalus.cli.palace_query import _run_lines
    (tmp_path / "web app").mkdir()
    (tmp_path / "web app" / "package.json").write_text('{"devDependencies": {"jest": "1"}}')
    languages._registry = None
    line = _run_lines(tmp_path, ["web app/src/o'brien (1).test.ts"])[0]
    assert line.startswith("Run (in web app): ")
    assert "'src/o'\"'\"'brien (1).test.ts'" in line or '"src/o\'brien (1).test.ts"' in line


def test_install_versions_compare_by_value_and_read_the_project_table(tmp_path):
    from daedalus import doctor
    (tmp_path / "pyproject.toml").write_text('[tool.x]\nversion = "9.9"\n\n[project]\nname = "daedalus-cli"\nversion = "0.2"\n')
    assert doctor._source_version(tmp_path) == "0.2"
    assert doctor.check_install(lambda: ("0.2.0", tmp_path, False)) == []
    assert doctor._same_version("1.0rc1", "1.0-rc.1") and not doctor._same_version("0.2.0", "0.2.1")


def test_install_findings_are_hints_not_failures(tmp_path, monkeypatch):
    from daedalus import doctor
    monkeypatch.delenv("DAEDALUS_DOCTOR_SKIP_INSTALL")
    monkeypatch.setattr(doctor, "check_install", lambda: [doctor.Finding("install-stale", "old")])
    findings, hints = doctor.run_checks(tmp_path)
    assert not any(f.name == "install-stale" for f in findings) and "install-stale: old" in hints
