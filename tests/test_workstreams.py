"""Workstreams (edict 0008): concurrent plans, per-owner drift, collisions, the brief."""

import json
import os
import subprocess

import pytest
from click.testing import CliRunner

from daedalus import config as config_module
from daedalus import workstreams as ws
from daedalus.cli import gameplan as gp
from daedalus.cli.main import main
from daedalus.doctor import run_checks
from daedalus.hooks import MAX_BRIEF_LINES, session_start_brief
from daedalus.reconstruct import gather


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path_factory):
    monkeypatch.setattr(config_module, "get_config_file", lambda: tmp_path_factory.mktemp("cfg") / "config.json")
    monkeypatch.delenv(ws.ENV, raising=False)
    yield
    ws.set_override(None)


def git(repo, *args, author="kohl"):
    env = {**os.environ, "GIT_AUTHOR_NAME": author, "GIT_AUTHOR_EMAIL": f"{author}@x",
           "GIT_COMMITTER_NAME": author, "GIT_COMMITTER_EMAIL": f"{author}@x"}
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, env=env).stdout


def commit(repo, msg, author="kohl", files=None):
    for name, text in (files or {}).items():
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).write_text(text)
    git(repo, "add", "-A", author=author)
    git(repo, "commit", "-q", "--allow-empty", "-m", msg, author=author)


def cli(repo, monkeypatch, *args, code=0):
    monkeypatch.chdir(repo)
    result = CliRunner().invoke(main, list(args))
    ws.set_override(None)
    assert result.exit_code == code, result.output
    return result.output


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "repo"
    r.mkdir()
    git(r, "init", "-q")
    gp.ensure_gameplan(r)
    commit(r, "init")
    return r


def two_sessions(repo, monkeypatch):
    """2026-10-13: an Ariadne session and a memory session at work in the same repository."""
    cli(repo, monkeypatch, "workstream", "new", "ariadne", "--kind", "session", "--author", "ariadne-session")
    cli(repo, monkeypatch, "workstream", "new", "memory", "--kind", "session", "--author", "memory-session")
    for wid, phase, task, edict in (("ariadne", "p1-edicts-ariadne", "T-e5", "0002"),
                                    ("memory", "p2b-reconstruction", "T-r1", "0006")):
        cli(repo, monkeypatch, "gameplan", "-w", wid, "phase", "add", phase, f"{wid} work", "--edict", edict)
        cli(repo, monkeypatch, "gameplan", "-w", wid, "phase", "activate", phase)
        cli(repo, monkeypatch, "gameplan", "-w", wid, "task", "add", task, f"{wid} task", "--edict", edict)
    commit(repo, "workstreams")


def test_single_plan_projects_are_unchanged(repo, monkeypatch):
    cli(repo, monkeypatch, "gameplan", "phase", "add", "p1", "Plain")
    assert gp.find_phase(json.loads((repo / ".daedalus/roadmap/gameplan.json").read_text()), "p1")
    assert not ws.gameplans_dir(repo).exists()
    assert ws.current(repo) == "default"


def test_two_sessions_each_keep_an_active_phase(repo, monkeypatch):
    two_sessions(repo, monkeypatch)
    ariadne, memory = gp.load_gameplan(repo, "ariadne"), gp.load_gameplan(repo, "memory")
    assert ariadne["activePhase"]["id"] == "p1-edicts-ariadne" and ariadne["activePhase"]["tasks"][0]["id"] == "T-e5"
    assert memory["activePhase"]["id"] == "p2b-reconstruction" and memory["activePhase"]["tasks"][0]["id"] == "T-r1"
    assert gp.load_gameplan(repo, "default")["activePhase"] is None       # the default plan untouched

    cli(repo, monkeypatch, "gameplan", "-w", "memory", "task", "status", "T-r1", "done", "-r", "shipped")
    assert gp.find_task(gp.load_gameplan(repo, "ariadne"), "T-e5")["status"] == "pending"


def test_current_workstream_precedence(repo, monkeypatch):
    two_sessions(repo, monkeypatch)
    cli(repo, monkeypatch, "workstream", "use", "memory")
    assert ws.current(repo) == "memory"
    monkeypatch.setenv(ws.ENV, "ariadne")
    assert ws.current(repo) == "ariadne"
    ws.set_override("default")
    assert ws.current(repo) == "default"
    ws.set_override(None)
    out = cli(repo, monkeypatch, "workstream", "list")
    assert "* ariadne (session): p1-edicts-ariadne - next T-e5 [pending] ariadne task" in out
    assert "  memory (session): p2b-reconstruction" in out


def test_pending_proposals_are_per_workstream(repo, monkeypatch):
    two_sessions(repo, monkeypatch)
    assert gp.GameplanPaths.for_project(repo, "memory").pending_file.name == "memory.pending.json"
    assert gp.GameplanPaths.for_project(repo, "default").pending_file.name == "pending.json"


def test_drift_counts_only_the_owners_commits(repo, monkeypatch):
    two_sessions(repo, monkeypatch)
    for i in range(12):
        commit(repo, f"ariadne work {i}", author="ariadne-session")
    commit(repo, "memory work", author="memory-session")
    drift = [f.message for f in run_checks(repo)[0] if f.name == "commits-after-gameplan"]
    assert any(m.startswith("[ariadne] 12 commits by ariadne-session") for m in drift)
    assert not any(m.startswith("[memory]") for m in drift)


def test_collisions(repo, monkeypatch):
    two_sessions(repo, monkeypatch)
    assert not [f for f in run_checks(repo)[0] if f.name.startswith("collision")]

    cli(repo, monkeypatch, "gameplan", "-w", "memory", "task", "add", "T-r2", "Help with casting", "--edict", "0002")
    cli(repo, monkeypatch, "workstream", "use", "ariadne")
    cli(repo, monkeypatch, "workstream", "claim", "src/daedalus/ariadne/")
    cli(repo, monkeypatch, "workstream", "use", "memory")
    cli(repo, monkeypatch, "workstream", "claim", "src/daedalus/ariadne/orchestrator.py", "docs/*.md")
    found = {f.name: f.message for f in run_checks(repo)[0] if f.name.startswith("collision")}
    assert "both have open work on edict 0002" in found["collision-edict"]
    assert "src/daedalus/ariadne/ / src/daedalus/ariadne/orchestrator.py" in found["collision-claims"]

    cli(repo, monkeypatch, "workstream", "claim", "--release", "src/daedalus/ariadne/orchestrator.py")
    cli(repo, monkeypatch, "gameplan", "-w", "memory", "task", "status", "T-r2", "done")
    assert not [f for f in run_checks(repo)[0] if f.name.startswith("collision")]


def test_claims_overlap_rules():
    assert ws.claims_overlap("src/", "src/a.py")
    assert ws.claims_overlap("docs/*.md", "docs/status.md")
    assert not ws.claims_overlap("src/a.py", "src/b.py")
    assert not ws.claims_overlap("docs/*.md", "src/x.md")


def test_edict_references_count_from_every_workstream(repo, monkeypatch):
    (repo / "docs/edicts").mkdir(parents=True)
    for n in ("0002", "0006"):
        (repo / f"docs/edicts/{n}-x.md").write_text(f"# Edict {n}: X\nStatus: accepted\n")
    two_sessions(repo, monkeypatch)
    assert "edict-not-in-gameplan" not in [f.name for f in run_checks(repo)[0]]


def test_brief_leads_with_mine_and_lists_the_others(repo, monkeypatch):
    two_sessions(repo, monkeypatch)
    monkeypatch.setenv(ws.ENV, "memory")
    lines = session_start_brief(repo).splitlines()
    assert lines[1] == "**Workstream:** memory"
    assert lines[2].startswith("**Phase:** p2b-reconstruction")
    others = lines[lines.index("**Other workstreams:**") + 1:]
    assert others[0].startswith("- ariadne (session): p1-edicts-ariadne - next T-e5")
    assert not any(l.startswith("- memory") for l in others)
    assert len(lines) <= MAX_BRIEF_LINES


def test_reconstruct_a_workstream(repo, monkeypatch):
    two_sessions(repo, monkeypatch)
    commit(repo, "ariadne: T-e5 local backend", author="ariadne-session")
    commit(repo, "memory: unrelated", author="memory-session")
    bundle = gather(repo, workstream="ariadne")
    assert [c["subject"] for c in bundle.commits] == ["ariadne: T-e5 local backend"]
    assert bundle.window["workstream"] == "ariadne" and bundle.window["author"] == "ariadne-session"
    assert [t["id"] for t in bundle.open_tasks] == ["T-e5"]


def test_workstream_ids_are_validated(repo, monkeypatch):
    out = cli(repo, monkeypatch, "workstream", "new", "Default", code=1)
    assert "lowercase" in out
    cli(repo, monkeypatch, "workstream", "new", "kohl")
    assert "already exists" in cli(repo, monkeypatch, "workstream", "new", "kohl", code=1)



def test_reconstruction_imports_into_its_workstream(repo, monkeypatch, tmp_path):
    from daedalus.reconstruct import PROPOSAL_SCHEMA, write_bundle
    two_sessions(repo, monkeypatch)
    commit(repo, "T-e5 local backend", author="ariadne-session")
    bundle = gather(repo, workstream="ariadne")
    rel = str(write_bundle(repo, bundle).relative_to(repo))
    sha = bundle.commits[0]["sha"]
    proposal = {"schema": PROPOSAL_SCHEMA, "bundle": rel, "window": bundle.window, "evidence_scope": "git",
                "updates": [{"task": "T-e5", "proposed_status": "done", "confidence": "shown", "basis": "messages",
                             "resolution": "Shipped.", "commits": [sha]}],
                "phases": [], "roadmap": [], "roadmap_unchanged": [], "conflicts": [], "context_commits": [], "files": []}
    f = tmp_path / "p.json"
    f.write_text(json.dumps(proposal))
    out = cli(repo, monkeypatch, "gameplan", "pending", "import", str(f))   # current workstream is default
    assert "Importing into workstream ariadne" in out
    assert (ws.gameplans_dir(repo) / "ariadne.pending.json").exists()
    assert not (repo / ".daedalus/roadmap/pending.json").exists()
