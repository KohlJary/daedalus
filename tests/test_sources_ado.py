"""The Azure DevOps source (edict 0011), against synthetic fixtures. Unverified live until Kohl runs it."""

import base64

import pytest

from daedalus.cli import gameplan as gp
from daedalus.sources import ado as ado_mod

from sources_helpers import fixture, index, offline, pending, project, run  # noqa: F401


@pytest.fixture
def ado(project, offline):
    for key, value in (("organization", "contoso"), ("project", "Reports"), ("team", "Exports Team"),
                       ("token_env", "TEST_ADO_PAT")):
        assert run("config", "--project", f"sources.ado.{key}", value).exit_code == 0
    import os

    os.environ["TEST_ADO_PAT"] = "pat-123"
    data = fixture("ado")
    t = offline["transport"]
    t.on("POST", "/_apis/wit/wiql", data["wiql"])
    t.on("GET", "/_apis/wit/workitems?ids=101,102,103", data["workitems_assigned"])
    t.on("GET", "/_apis/wit/workitems?ids=100", data["workitems_parents"])
    yield t
    os.environ.pop("TEST_ADO_PAT", None)


def test_unconfigured_ado_is_not_active(project):
    assert "ado" not in run("source", "list").output.split("Sources here")[1]


def test_query_defaults_to_my_open_items_in_the_current_iteration(ado, project):
    run("source", "sync", "ado")
    wiql = next(c for c in ado.calls if c["method"] == "POST")
    assert wiql["url"] == "https://dev.azure.com/contoso/Reports/Exports%20Team/_apis/wit/wiql?api-version=7.1"
    assert "@Me" in wiql["body"]["query"] and "@CurrentIteration" in wiql["body"]["query"]
    assert wiql["headers"]["Authorization"] == "Basic " + base64.b64encode(b":pat-123").decode()
    # The story's parent Feature isn't assigned to us, so it is fetched as a parent
    assert any("ids=100&" in c["url"] for c in ado.calls)


def test_default_mapping(ado, project):
    out = run("source", "sync", "ado")
    assert out.exit_code == 0, out.output
    props = pending(project)
    phase = next(p for p in props if p["kind"] == "new-phase")["phase"]
    assert (phase["id"], phase["roadmapItems"]) == ("ado-100", ["ado-101"])
    assert [(t["id"], t["roadmapItem"]) for t in phase["tasks"]] == [("ado-103", "ado-101")]
    items = {p["item"]["id"]: p["item"] for p in props if p["kind"] == "roadmap-new"}
    assert set(items) == {"ado-101", "ado-102"}
    assert items["ado-101"]["status"] == "in_progress" and items["ado-101"]["item_type"] == "feature"
    assert items["ado-102"]["status"] == "backlog" and items["ado-102"]["item_type"] == "bug"
    assert items["ado-101"]["origin"]["url"] == "https://dev.azure.com/contoso/Reports/_workitems/edit/101"
    assert ado.writes() == []


def test_status_is_unverified_until_run_live(ado, project):
    run("source", "sync", "ado")
    assert "unverified" in run("source", "status").output
    assert ado_mod.AdoSource.verified is False


def test_resync_and_apply_are_idempotent(ado, project):
    run("source", "sync", "ado")
    assert "proposed 0" in run("source", "sync", "ado").output
    run("gameplan", "pending", "apply", "all")
    assert "proposed 0" in run("source", "sync", "ado").output
    # Known items are fetched again by id so a closure is seen
    ids_calls = [c["url"] for c in ado.calls if "workitems?ids=" in c["url"]]
    assert "ids=101,102,103" in ids_calls[-1] or "ids=101,102,103" in ids_calls[-2]


def test_write_back_moves_the_item_to_the_done_state(ado, project):
    run("config", "--project", "sources.ado.write_back_comment", "true")
    run("config", "--project", "sources.ado.done_state", "Done")
    ado.on("PATCH", "/_apis/wit/workitems/103", {"id": 103}).on("POST", "/_apis/wit/workItems/103/comments", {"id": 1})
    run("source", "sync", "ado")
    run("gameplan", "pending", "apply", "all")
    run("gameplan", "phase", "activate", "ado-100")
    run("gameplan", "task", "status", "ado-103", "done", "-r", "Serializer merged")
    assert run("gameplan", "pending", "apply", "all").exit_code == 0
    patch, comment = ado.writes()
    assert patch["body"] == [{"op": "add", "path": "/fields/System.State", "value": "Done"}]
    assert patch["headers"]["Content-Type"] == "application/json-patch+json"
    assert comment["body"] == {"text": "Serializer merged"}
    assert gp.load_gameplan(project)["activePhase"]["tasks"][0]["writeBack"] == "applied"


def test_parent_id_from_relations_or_field():
    assert ado_mod.parent_id({"fields": {"System.Parent": 7}}) == 7
    assert ado_mod.parent_id({"fields": {}, "relations": [
        {"rel": "System.LinkTypes.Hierarchy-Forward", "url": "x/workItems/9"},
        {"rel": "System.LinkTypes.Hierarchy-Reverse", "url": "x/workItems/8"}]}) == 8
    assert ado_mod.parent_id({"fields": {}}) is None


def test_ado_dry_run_writes_nothing(ado, project):
    out = run("source", "sync", "ado", "--dry-run")
    assert out.exit_code == 0 and "would propose 3" in out.output
    assert pending(project) == [] and not (project / ".daedalus/sources/state.json").exists()
