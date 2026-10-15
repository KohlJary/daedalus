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
    assert 'Run: dotnet test Shop.Tests/Shop.Tests.csproj --nologo --filter FullyQualifiedName~CalcTests' in out
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
