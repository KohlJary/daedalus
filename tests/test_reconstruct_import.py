"""gameplan pending import: checked reconstruction proposals become pending items (edict 0006)."""

import json

import pytest
from click.testing import CliRunner

from daedalus.cli import gameplan as gp
from daedalus.cli.main import main

from test_reconstruct_check import commit, git, isolated_config, proposal, repo  # noqa: F401


def run(path, monkeypatch, *args, code=0):
    monkeypatch.chdir(path)
    result = CliRunner().invoke(main, list(args))
    assert result.exit_code == code, result.output
    return result.output


@pytest.fixture
def with_roadmap(repo):
    return repo


def test_import_apply_all_kinds(with_roadmap, monkeypatch, tmp_path_factory):
    path, shas = with_roadmap
    p = proposal(shas)
    p["updates"].append({"task": "T-a6", "proposed_status": "in_progress", "confidence": "shown",
                         "basis": "messages", "resolution": "Started.", "commits": [shas["fix"]]})
    f = tmp_path_factory.mktemp("p") / "proposal.json"
    f.write_text(json.dumps(p))

    out = run(path, monkeypatch, "gameplan", "pending", "import", str(f))
    assert "Pending P1: T-a6 -> in_progress" in out
    assert "Pending P2: new phase p21-diagrams (done, 1 tasks): Diagrams" in out
    assert "Pending P3: roadmap r1 -> done" in out
    assert "Not imported, T-a1: needs confirmation (Replay the 03:08:49 utterance" in out
    before = (path / ".daedalus/roadmap/gameplan.json").read_text()
    assert gp.load_gameplan(path) == json.loads(before)        # import never touches the gameplan

    run(path, monkeypatch, "gameplan", "pending", "apply", "all")
    data = gp.load_gameplan(path)
    assert gp.find_task(data, "T-a6")["status"] == "in_progress"
    phase = gp.find_phase(data, "p21-diagrams")
    assert phase["status"] == "done" and phase["tasks"][0]["resolution"] == "Registry shipped."
    assert "[reconstructed; shown, from messages]" in phase["notes"]
    roadmap = json.loads((path / ".daedalus/roadmap/index.json").read_text())
    assert roadmap["items"][0]["status"] == "done"
    assert gp.load_pending(path) == []


def test_import_refuses_a_proposal_that_fails_check(with_roadmap, monkeypatch, tmp_path_factory):
    path, shas = with_roadmap
    p = proposal(shas)
    p["updates"][0]["proposed_status"] = "done"                # done on inferred evidence
    f = tmp_path_factory.mktemp("p") / "bad.json"
    f.write_text(json.dumps(p))
    out = run(path, monkeypatch, "gameplan", "pending", "import", str(f), code=1)
    assert "Not imported" in out
    assert gp.load_pending(path) == []


def test_reimport_is_idempotent_and_drop_works(with_roadmap, monkeypatch, tmp_path_factory):
    path, shas = with_roadmap
    f = tmp_path_factory.mktemp("p") / "proposal.json"
    f.write_text(json.dumps(proposal(shas)))
    run(path, monkeypatch, "gameplan", "pending", "import", str(f))
    run(path, monkeypatch, "gameplan", "pending", "import", str(f))
    assert len(gp.load_pending(path)) == 2
    assert "Dropped P1: new phase p21-diagrams" in run(path, monkeypatch, "gameplan", "pending", "drop", "P1")
    assert gp.find_phase(gp.load_gameplan(path), "p21-diagrams") is None


def test_roadmap_item_removed_after_import_fails_cleanly(repo, monkeypatch, tmp_path_factory):
    path, shas = repo
    f = tmp_path_factory.mktemp("p") / "proposal.json"
    f.write_text(json.dumps(proposal(shas, phases=[], updates=[])))
    run(path, monkeypatch, "gameplan", "pending", "import", str(f))
    (path / ".daedalus/roadmap/index.json").write_text(json.dumps({"items": []}))
    out = run(path, monkeypatch, "gameplan", "pending", "apply", "all")
    assert "Roadmap item 'r1' not found" in out
    assert len(gp.load_pending(path)) == 1                     # nothing applied, nothing lost
