"""Palace building beyond Python (T-e21): regions, buildings, rooms, drift, the cached graph, orphans and
annotations on a polyglot project."""

import subprocess

import pytest

from daedalus.labyrinth import languages
from daedalus.labyrinth.annotations import scan_directory
from daedalus.labyrinth.cartographer import Cartographer
from daedalus.labyrinth.orphan_detector import detect_orphans
from daedalus.labyrinth.pathfinding import CallGraph
from daedalus.labyrinth.storage import PalaceStorage

pytest.importorskip("tree_sitter")
for wheel in ("tree_sitter_go", "tree_sitter_typescript", "tree_sitter_javascript", "tree_sitter_rust"):
    pytest.importorskip(wheel)

FILES = {
    "shop/index.ts": "// Shop: carts and checkout.\nexport { Cart } from './cart';\nexport function boot() { return 1; }\n",
    "shop/cart.ts": "export class Cart {\n  total(): number { return addTax(1); }\n}\n"
                    "// MAP:ROOM cart-helpers\nfunction addTax(x: number): number { return x * 1.2; }\n",
    "shop/_internal.ts": "export function hidden() {}\n",
    "shop/Badge.tsx": "export function Badge() { return null; }\nexport function useBadge() { return 1; }\n",
    "calc/doc.go": "// Package calc does arithmetic.\npackage calc\n",
    "calc/calc.go": "package calc\n\ntype Num int\n\nfunc (n Num) String() string { return format(int(n)) }\n\n"
                    "func format(x int) string { return \"\" }\n\nfunc unusedHelper() {}\n\nfunc main() {}\n",
    "calc/calc_test.go": "package calc\n\nimport \"testing\"\n\nfunc TestString(t *testing.T) { _ = Num(1).String() }\n",
    "geo/mod.rs": "//! Geometry helpers.\npub fn area(w: i32, h: i32) -> i32 { w * h }\n",
    "py/_private.py": "def secret():\n    pass\n",
    "py/__init__.py": '"""Python package."""\n',
    "gen/out.ts": "export function generated() {}\n",
}


@pytest.fixture()
def project(tmp_path):
    for rel, text in FILES.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(text)
    (tmp_path / ".gitignore").write_text("gen/\n")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    languages._registry = None
    return tmp_path


@pytest.fixture()
def mapped(project):
    storage = PalaceStorage(project)
    palace = storage.initialize("poly")
    cart = Cartographer(palace, storage)
    for d in ("shop", "calc", "geo", "py", "gen"):
        if (project / d).exists():
            cart.map_directory(project / d)
    return cart


def test_buildings_and_rooms_for_every_language(mapped):
    buildings = {b.name for b in mapped.palace.buildings.values()}
    rooms = {r.name for r in mapped.palace.rooms.values()}
    assert "shop" in buildings          # index.ts stands for its directory
    assert "geo" in buildings           # so does mod.rs
    assert "_internal" in buildings     # the _private rule is Python's
    assert "_private" not in buildings  # ...and still applies there
    assert {"Cart.total", "Num.String", "area"} <= rooms
    assert "generated" not in rooms     # gen/ is git-ignored


def test_regions_take_their_description_from_the_package_doc(mapped):
    regions = {r.name: r for r in mapped.palace.regions.values()}
    assert regions["calc"].description == "Package calc does arithmetic."  # Go doc.go
    assert regions["shop"].description == "Shop: carts and checkout."      # index.ts comment
    assert regions["py"].description == "Python package."                   # __init__ docstring
    assert "calc/calc_test.go" not in regions["calc"].entry_points          # tests aren't entry points


def test_a_fresh_map_has_no_drift_and_rooms_resync(mapped, project):
    assert mapped.check_drift() == []
    path = project / "shop/cart.ts"
    path.write_text(path.read_text().replace("total(): number", "total(rate: number): number"))
    drift = mapped.check_drift()
    assert [(mapped.palace.rooms[r.room_name].name, r.issues) for r in drift] == [("Cart.total", ["Signature has changed"])]
    assert mapped.sync_room(drift[0].room_name) is not None


def test_cached_call_graph_resolves_calls_to_node_ids(mapped, project):
    graph = mapped.build_call_graph()
    assert graph["nodes"]["calc.calc.go.Num.String"]["calls"] == ["calc.calc.go.format"]
    assert {"source": "shop.cart.ts.Cart.total", "target": "shop.cart.ts.addTax", "type": "calls"} in graph["edges"]
    call_graph = CallGraph.from_project(project, use_cache=False)
    assert call_graph.callees("calc.calc.go.Num.String") == ["calc.calc.go.format"]


def test_orphans_know_each_languages_entry_points(project):
    summary = detect_orphans(project, include_medium_confidence=True)
    high = {r.simple_name for r in summary.high_confidence}
    flagged = {r.simple_name for reports in summary.orphans_by_module.values() for r in reports}
    assert "unusedHelper" in high
    assert not {"main", "String", "Badge", "useBadge", "TestString"} & flagged


def test_annotations_in_slash_comments_with_their_context(project):
    found = scan_directory(project, project)
    ann = found["shop/cart.ts"].annotations[0]
    assert (ann.type, ann.value, ann.context) == ("ROOM", "cart-helpers", "addTax")


def test_a_method_and_a_function_with_one_name_dont_drift_or_swap(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app/cart.py").write_text("class Cart:\n    def total(self, a):\n        return a\n\n\n"
                                          "def total(items):\n    return sum(items)\n")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    languages._registry = None
    storage = PalaceStorage(tmp_path)
    cart = Cartographer(storage.initialize("p"), storage)
    cart.map_directory(tmp_path / "app")
    assert cart.check_drift() == []  # unchanged code: no drift
    top = next(k for k, r in cart.palace.rooms.items() if r.name == "total")
    assert cart.sync_room(top).anchor.line == 6  # the top-level function, not Cart.total
