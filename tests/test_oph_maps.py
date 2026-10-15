"""`oph draw` / `oph map` (edict 0017): maps pass the lint, and the edges read back from the text alone match the data."""

import json

import pytest
from click.testing import CliRunner

from daedalus.cli.main import main
from daedalus.edicts import depends_on, load_edict
from daedalus.ophanic.lint import check_text
from daedalus.ophanic.maps import MAPS
from daedalus.ophanic.render import draw, read_edges

from sources_helpers import offline, project, run  # noqa: F401

GRAPH = {"title": "Deps", "nodes": [{"id": f"00{n}", "label": f"Edict {n}", "kind": "E"} for n in range(10, 16)],
         "edges": [{"from": "0015", "to": "0014"}, {"from": "0014", "to": "0013"}, {"from": "0015", "to": "0010"},
                   {"from": "0012", "to": "0011"}, {"from": "0013", "to": "0010"}]}


def edges_from_text(text):
    return {(e["from"], e["to"], e["state"]) for e in read_edges(text)}


def edges_from_data(data):
    slug = {n["id"]: n["slug"] for n in data["nodes"]}
    return {(slug[e["from"]], slug[e["to"]], e["state"]) for e in data["edges"]}


@pytest.mark.parametrize("width", [100, 60, 34])
def test_drawing_matches_data_both_ways_and_passes_the_lint(width):
    text, data = draw(GRAPH, width)
    assert edges_from_text(text) == edges_from_data(data)
    assert {e["state"] for e in data["edges"]} >= {"drawn"} or data["legend_only"]
    assert check_text("m.oph", "@x\n" + text) == []
    assert max(len(line) for line in text.splitlines() if line.startswith(("┌", "│", "└"))) <= width


def test_skipped_layers_are_listed_not_drawn():
    text, data = draw(GRAPH, 100)
    states = {(e["from"], e["to"]): e["state"] for e in data["edges"]}
    assert states[("0015", "0010")] == "listed" and states[("0015", "0014")] == "drawn"
    assert "█E15 ─▶ █E10" in text


def test_mutations_break_the_match():
    text, data = draw(GRAPH, 100)
    reversed_one = text.replace("█E15 ─▶ █E10", "█E10 ─▶ █E15", 1)
    assert edges_from_text(reversed_one) != edges_from_data(data)
    deleted_one = text.replace("─▶ █E13", "      ", 1)
    assert edges_from_text(deleted_one) != edges_from_data(data)


def test_depends_on_reads_numbers_and_externals(tmp_path):
    (tmp_path / "docs/edicts").mkdir(parents=True)
    (tmp_path / "docs/edicts/0013-x.md").write_text(
        "# Edict 0013: X\nStatus: accepted\nDepends on: Edict 0010 (digests; runners); Edict 0011 (the\nsource seam); "
        "Ariadne gate (`feat/x`)\n\n## Intent\n")
    nums, ext = depends_on(load_edict(tmp_path, "13"))
    assert nums == ["0010", "0011"] and ext == ["Ariadne gate"]


def test_maps_render_from_a_project(project):
    from daedalus.cli import gameplan as gp

    data = gp.load_gameplan(project)
    gp.add_phase(data, "p1", "First")
    gp.activate_phase(data, "p1")
    gp.add_task(data, "T-1", "Do it")
    gp.save_gameplan(project, data)
    for name in MAPS:
        out = run("oph", "map", name)
        assert out.exit_code == 0, (name, out.output)
        assert check_text("m.oph", "@x\n" + out.output) == [], name
    assert "T-1" in run("oph", "map", "plan").output
    js = json.loads(run("oph", "map", "plan", "--json").output)
    assert any(n["id"] == "T-1" and n["parent"] for n in js["nodes"])


# ---------- Momus's trial of the build (2026-10-15) ----------

HAND = {
    "side edge with a slug": ("""┌──────────┐       ┌──────────┐
│ █E13     │─█R11─▶│ █E10     │
└──────────┘       └──────────┘
█E13: edict 13
█E10: edict 10
█R11: depends on
""", [{"from": "█E13", "to": "█E10", "state": "drawn", "via": "█R11"}]),
    "plain side edge": ("""┌──────────┐       ┌──────────┐
│ █E13     │──────▶│ █E10     │
└──────────┘       └──────────┘
█E13: edict 13
█E10: edict 10
""", [{"from": "█E13", "to": "█E10", "state": "drawn"}]),
    "edge pointing left": ("""┌──────────┐       ┌──────────┐
│ █E13     │◀──────│ █E10     │
└──────────┘       └──────────┘
█E13: edict 13
█E10: edict 10
""", [{"from": "█E10", "to": "█E13", "state": "drawn"}]),
    "unnamed boxes": ("""┌──────┐      ┌──────┐
│ A    │┄┄┄┄┄▶│ B    │
└──────┘      └──────┘
""", [{"from": None, "to": None, "state": "drawn"}]),
}


@pytest.mark.parametrize("name", sorted(HAND))
def test_read_edges_reads_side_attached_edges(name):
    text, expected = HAND[name]
    assert check_text("h.oph", "@x\n" + text) == [], name
    assert read_edges(text) == expected


def test_check_json_reports_edges_per_file_and_per_diagram(tmp_path):
    two_variants = ("# Two\n\n@wide\n" + HAND["plain side edge"][0] + "\n@narrow\n"
                    + HAND["edge pointing left"][0])
    (tmp_path / "two.oph").write_text(two_variants, encoding="utf-8")
    (tmp_path / "doc.md").write_text("Prose.\n\n```oph\n" + HAND["side edge with a slug"][0] + "```\n",
                                     encoding="utf-8")
    out = CliRunner().invoke(main, ["oph", "check", str(tmp_path), "--json"])
    assert out.exit_code == 0, out.output
    edges = json.loads(out.output)["edges"]
    two = edges[str(tmp_path / "two.oph")]
    assert [(d["variant"], [(e["from"], e["to"]) for e in d["edges"]]) for d in two] == [
        ("wide", [("█E13", "█E10")]), ("narrow", [("█E10", "█E13")])]
    assert edges[str(tmp_path / "doc.md")][0]["edges"][0]["via"] == "█R11"


def test_wide_characters_keep_rows_equal():
    graph = {"title": "Wide", "nodes": [{"id": "a", "label": "日本語のラベルです" * 3, "kind": "N"},
                                         {"id": "b", "label": "éé combining", "kind": "N"}],
             "edges": [{"from": "a", "to": "b"}]}
    for w in (100, 60, 34):
        text, _ = draw(graph, w)
        assert check_text("m.oph", "@x\n" + text) == [], w


def test_more_than_99_of_a_kind_are_drawn_with_three_digits():
    graph = {"nodes": [{"id": f"t{i:03d}", "label": "task", "kind": "T"} for i in range(120)]
             + [{"id": "0001", "kind": "E"}, {"id": "0002", "kind": "E"}], "edges": []}
    text, data = draw(graph, 100)
    assert "█T001" in text and "█T120" in text and "█T120: t119" in text
    assert all(n["slug"] for n in data["nodes"])
    assert check_text("m.oph", "@x\n" + text) == []


def test_missing_nodes_and_orphans_are_listed_not_dropped():
    graph = {"nodes": [{"id": "0001", "kind": "E"}, {"id": "kid", "kind": "T", "parent": "gone"}],
             "edges": [{"from": "0001", "to": "0099"}]}
    text, data = draw(graph, 100)
    assert "missing: 0001 ─▶ 0099 (no node 0099)" in text
    assert "missing: kid is inside gone" in text
    assert len(data["missing"]) == 2
    assert check_text("m.oph", "@x\n" + text) == []


def test_duplicate_ids_get_their_own_slugs_and_a_warning():
    graph = {"nodes": [{"id": "0016", "label": "one", "kind": "E"}, {"id": "0016", "label": "two", "kind": "E"}],
             "edges": []}
    text, data = draw(graph, 100)
    slugs = [n["slug"] for n in data["nodes"]]
    assert len(set(slugs)) == 2
    assert "note: duplicate id 0016" in text
    assert check_text("m.oph", "@x\n" + text) == []


def test_labels_cannot_draw_or_forge_slugs():
    graph = {"nodes": [{"id": "a", "label": "x █E09 │ ─▶ █E02 ┌┐ ◆Thing", "kind": "N"},
                       {"id": "b", "label": "fine", "kind": "N"}], "edges": [{"from": "a", "to": "b"}]}
    text, data = draw(graph, 100)
    assert check_text("m.oph", "@x\n" + text) == []
    assert edges_from_text(text) == edges_from_data(data)


def test_empty_and_unfit_maps_say_which():
    assert "Nothing to map" in draw({"nodes": [], "edges": []}, 100)[0]


def test_draw_rejects_malformed_json_cleanly(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{nope", encoding="utf-8")
    out = CliRunner().invoke(main, ["oph", "draw", str(bad)])
    assert out.exit_code == 1 and "not valid JSON" in out.output and "Traceback" not in out.output
    bad.write_text('{"nodes": [{"id": "a"}], "edges": [{"from": "a"}]}', encoding="utf-8")
    out = CliRunner().invoke(main, ["oph", "draw", str(bad)])
    assert out.exit_code == 1 and "needs both from and to" in out.output


def test_map_finds_the_project_root_from_a_subdirectory(project, monkeypatch):
    from daedalus.cli import gameplan as gp

    data = gp.load_gameplan(project)
    gp.add_phase(data, "p1", "First")
    gp.activate_phase(data, "p1")
    gp.add_task(data, "T-1", "Do it")
    gp.add_task(data, "T-2", "Done already")
    gp.set_task_status(data, "T-2", "done")
    gp.save_gameplan(project, data)
    (project / "docs").mkdir()
    monkeypatch.chdir(project / "docs")
    out = run("oph", "map", "plan").output
    assert "T-1" in out and "~done" not in out


def test_map_edicts_lists_a_dependency_on_a_missing_edict(project):
    (project / "docs/edicts").mkdir(parents=True)
    (project / "docs/edicts/0001-a.md").write_text("# Edict 0001: A\nStatus: accepted\nDepends on: Edict 0042\n\n"
                                                    "## Intent\n", encoding="utf-8")
    out = run("oph", "map", "edicts").output
    assert "missing: 0001 ─▶ 0042 (no node 0042)" in out


def test_map_workstreams_draws_collisions_as_their_own_boxes(project):
    from daedalus import workstreams as ws
    from daedalus.doctor import collisions

    for wid, claims in (("alpha", ["src/a/**"]), ("beta", ["src/a/x.py", "docs/**"])):
        ws.create(project, wid)
        ws.set_claims(project, wid, add=claims)
    plans = {w: ws.load(project, w) for w in ("alpha", "beta")}
    assert collisions(plans) == [("claims", "alpha", "beta", "src/a/** / src/a/x.py")]
    out = run("oph", "map", "workstreams").output
    js = json.loads(run("oph", "map", "workstreams", "--json").output)
    assert check_text("m.oph", "@x\n" + out) == []
    assert "claim docs/**" in out and "beta:docs" not in out
    assert "alpha collides with beta" in out
    coll = next(n for n in js["nodes"] if n["id"].startswith("collision"))
    assert coll["slug"].startswith("█C")
    assert {(e["from"], e["to"]) for e in js["edges"]} == {(coll["id"], "alpha"), (coll["id"], "beta")}


def test_depends_on_ignores_glosses_and_reads_short_numbers(tmp_path):
    (tmp_path / "docs/edicts").mkdir(parents=True)
    (tmp_path / "docs/edicts/0020-x.md").write_text(
        "# Edict 0020: X\nStatus: accepted\nDepends on: Edict 0010 (unlike 0003, which is a gloss); Edict 11; "
        "edict 7\n\n## Intent\n")
    nums, ext = depends_on(load_edict(tmp_path, "20"))
    assert nums == ["0007", "0010", "0011"] and ext == []


REAL_DEPS = {"0006": ["0007"], "0007": ["0004"], "0008": ["0006", "0007"], "0009": ["0008"],
             "0010": ["0004", "0006", "0007"], "0011": ["0007", "0008"],
             "0012": ["0007", "0008", "0009", "0010", "0011"], "0013": ["0006", "0010", "0011"],
             "0014": ["0007", "0011"], "0017": ["0008", "0011", "0012", "0013"]}


def test_depends_on_keeps_the_real_edges():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    for number, deps in REAL_DEPS.items():
        assert depends_on(load_edict(root, number))[0] == deps, number
    assert sum(len(d) for d in REAL_DEPS.values()) == 24
