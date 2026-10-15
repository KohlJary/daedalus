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
