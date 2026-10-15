"""The `self` source (dream idea 23): Daedalus's own friction as intake."""

import json

import pytest

from daedalus import roadmap, sources
from daedalus.sources.self_source import SelfSource

from sources_helpers import index, offline, pending, project, run  # noqa: F401


@pytest.fixture
def selfproj(project):
    reports = project / ".daedalus/reflection/reports"
    reports.mkdir(parents=True)
    (reports / "weekly-2026-W42.json").write_text(json.dumps({"findings": [
        {"id": "F1", "type": "pattern", "text": "Edits fail on unread files. They happen weekly [s:a e:b]"},
        {"id": "F2", "type": "failed_tool_call", "text": "x"}]}))
    sess = project / ".daedalus/reflection/sessions"
    sess.mkdir(parents=True)
    for n in range(3):
        sess.joinpath(f"s{n}.json").write_text(json.dumps({
            "session_id": f"s{n}", "events": {"failures": [f"u{n}", f"v{n}"]},
            "details": {f"u{n}": {"tool": "Bash", "call": "python -m build -q", "summary": "Exit code 2 no such option"},
                        f"v{n}": {"tool": "Bash", "call": ["ls /tmp", "grep -n x", "cat y"][n], "summary": "nope"}}}))
    (project / "docs/edicts").mkdir(parents=True)
    (project / "docs/edicts/0001-x.md").write_text("# Edict 0001: X\nStatus: maybe\n")
    assert run("config", "--project", "sources.self.enabled", "true").exit_code == 0
    return project


def test_self_registers_and_is_off_until_turned_on(project):
    assert "self" in sources.installed()
    assert "self" not in sources.active(project)


def test_patterns_drift_and_friction_become_observations(selfproj):
    out = run("source", "sync", "self")
    assert out.exit_code == 0, out.output
    items = {p["item"]["id"]: p["item"] for p in pending(selfproj) if p["kind"] == "roadmap-new"}
    assert "self-pattern-weekly-2026-W42-F1" in items
    assert "self-friction-bash-python-m" in items or any(k.startswith("self-friction-bash-python") for k in items)
    assert not any(k.endswith(("-ls", "-grep", "-cat")) for k in items)  # different commands, once each
    drift = [k for k in items if k.startswith("self-drift-")]
    assert drift and all(i["item_type"] == "observation" for i in items.values())
    assert all("own observation" in i["description"] for i in items.values())


def test_a_drift_that_goes_away_is_proposed_done(selfproj):
    run("source", "sync", "self")
    run("gameplan", "pending", "apply", "all")
    (selfproj / "docs/edicts/0001-x.md").write_text("# Edict 0001: X\nStatus: accepted\n")
    run("source", "sync", "self")
    done = [p for p in pending(selfproj) if p["kind"] == "roadmap-update" and p["changes"].get("status") == "done"]
    assert done and all(p["item"].startswith("self-drift-") for p in done)
