"""Proposal kinds, roadmap storage and the glossary (edict 0011)."""

import json
import re
import subprocess
from pathlib import Path

import pytest

from daedalus.cli import gameplan as gp
from daedalus.cli.commands import GITIGNORE_WORKSTREAMS_BLOCK, _ensure_gameplan_tracked

from sources_helpers import offline, pending, project, run  # noqa: F401

ORIGIN = {"source": "github", "external_id": "7", "url": "u"}


def test_keys_follow_the_edict():
    assert gp.proposal_key({"kind": "roadmap-new", "origin": ORIGIN, "item": {"id": "github-7"}}) == "src:github:7"
    assert gp.proposal_key({"kind": "roadmap-update", "origin": ORIGIN, "item": "github-7"}) == "src:github:7"
    assert gp.proposal_key({"kind": "write-back", "origin": ORIGIN, "task": "T1"}) == "wb:github:7:T1"
    assert gp.proposal_key({"task": "T1", "status": "done"}) == "task:T1"
    assert gp.proposal_key({"kind": "new-task", "task": "T2"}) == "new-task:T2"


def test_every_kind_is_described_and_unknown_kinds_raise():
    samples = {
        "task-status": {"task": "T1", "status": "done"},
        "new-phase": {"kind": "new-phase", "phase": {"id": "p", "title": "P"}},
        "roadmap-status": {"kind": "roadmap-status", "item": "i", "status": "done"},
        "new-task": {"kind": "new-task", "task": "T", "title": "t"},
        "roadmap-new": {"kind": "roadmap-new", "origin": ORIGIN, "item": {"id": "github-7", "title": "x"}},
        "roadmap-update": {"kind": "roadmap-update", "origin": ORIGIN, "item": "github-7", "changes": {"title": "y"}},
        "write-back": {"kind": "write-back", "origin": ORIGIN, "task": "T1"},
    }
    assert set(samples) == set(gp.PROPOSAL_KINDS)
    for p in samples.values():
        assert gp.describe_proposal(p)
    with pytest.raises(gp.GameplanError):
        gp.proposal_key({"kind": "mystery"})
    with pytest.raises(gp.GameplanError):
        gp.describe_proposal({"kind": "mystery"})


def test_apply_pending_raises_on_an_unknown_kind_and_changes_nothing(project):
    gp.save_pending(project, [
        {"id": "P1", "kind": "new-phase", "phase": {"id": "p1", "title": "P"}},
        {"id": "P2", "kind": "mystery", "task": "T1", "status": "done"},
    ])
    data = gp.load_gameplan(project)
    with pytest.raises(gp.GameplanError, match="Unknown proposal kind 'mystery'"):
        gp.apply_pending(project, data, "all")
    assert gp.find_phase(data, "p1") is None
    assert len(pending(project)) == 2


def test_a_changed_update_replaces_the_pending_one(project):
    base = {"kind": "roadmap-update", "origin": ORIGIN, "item": "github-7", "changes": {"title": "a"}}
    gp.add_proposals(project, [dict(base)])
    assert gp.add_proposals(project, [dict(base)]) == []
    gp.add_proposals(project, [dict(base, changes={"title": "b"})])
    [p] = pending(project)
    assert p["changes"] == {"title": "b"} and p["id"] == "P1"


def test_commit_kinds_still_replace_only_with_new_commits(project):
    gp.add_proposals(project, [{"task": "T1", "status": "done", "commits": ["a"], "resolution": "x"}])
    assert gp.add_proposals(project, [{"task": "T1", "status": "done", "commits": ["a"], "resolution": "y"}]) == []
    assert len(gp.add_proposals(project, [{"task": "T1", "status": "done", "commits": ["a", "b"]}])) == 1


def test_activating_a_phase_keeps_its_queued_tasks():
    data = gp.empty_gameplan()
    gp.add_phase(data, "p", "P")
    gp.find_phase(data, "p")["tasks"] = [{"id": "t", "title": "T", "status": "pending"}]
    active = gp.activate_phase(data, "p")
    assert [t["id"] for t in active["tasks"]] == ["t"]
    assert "tasks" not in gp.find_phase(data, "p")


def test_local_items_record_their_origin(project):
    run("roadmap", "add", "An idea")
    [item] = json.loads((project / ".daedalus/roadmap/index.json").read_text())["items"]
    assert item["origin"] == {"source": "local"}
    shown = run("roadmap", "show", item["id"][:8]).output
    assert "origin: local" in shown and "Phases: none list it" in shown


def ignored(repo, rel):
    return subprocess.run(["git", "check-ignore", "-q", rel], cwd=repo).returncode == 0


def test_existing_block_without_the_index_gets_the_negation(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    old_block = GITIGNORE_WORKSTREAMS_BLOCK.replace("!.daedalus/roadmap/index.json\n", "")
    (tmp_path / ".gitignore").write_text(".daedalus/\n" + old_block)
    assert ignored(tmp_path, ".daedalus/roadmap/index.json")
    _ensure_gameplan_tracked(tmp_path)
    assert not ignored(tmp_path, ".daedalus/roadmap/index.json")
    assert ignored(tmp_path, ".daedalus/gameplans/x.pending.json")
    assert ignored(tmp_path, ".daedalus/session-summaries.md")
    text = (tmp_path / ".gitignore").read_text()
    assert text.count("!.daedalus/roadmap/index.json") == 1
    _ensure_gameplan_tracked(tmp_path)
    assert (tmp_path / ".gitignore").read_text() == text


def test_glossary_names_the_commands_that_ship():
    from daedalus.cli.main import main

    text = (Path(__file__).parents[1] / "docs" / "design" / "tui" / "glossary.md").read_text(encoding="utf-8")
    cards = dict(re.findall(r"^## (.+?)\n(.*?)(?=^## |\Z)", text, re.S | re.M))
    for card, group in (("Roadmap", "roadmap"), ("Source", "source")):
        named = re.findall(rf"`daedalus {group} (\w[\w-]*)", cards[card])
        assert named, card
        assert set(named) <= set(main.commands[group].commands), (card, named)


def test_a_bare_list_index_from_ariadnes_tracker_still_reads(tmp_path):
    from daedalus import roadmap

    path = roadmap.index_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text('[{"id": "abc", "title": "From Ariadne", "status": "ready"}]')
    assert roadmap.find(roadmap.load_index(tmp_path), "abc")["title"] == "From Ariadne"
