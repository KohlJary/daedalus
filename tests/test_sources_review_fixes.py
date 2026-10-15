"""Momus's review of the 0011 build (.daedalus/momus/trials/2026-10-15-edict-0011-build.md): each
finding fixed, with a test that fails on the code it reviewed."""

import json
import os
import subprocess
import sys

import pytest

from daedalus import doctor, roadmap, sources
from daedalus.cli import gameplan as gp
from daedalus.sources import credentials

from sources_helpers import fixture, github_routes, index, offline, pending, project, run  # noqa: F401


@pytest.fixture
def gh(project, offline):
    run("config", "--project", "sources.github.token_env", "TEST_GH_TOKEN")
    os.environ["TEST_GH_TOKEN"] = "t0ken"
    github_routes(offline["transport"])
    yield offline["transport"]
    os.environ.pop("TEST_GH_TOKEN", None)


def _issue(number, **kw):
    base = dict(fixture("github")["issues_open"][1], number=number, title=f"Issue {number}",
                html_url=f"https://github.com/acme/widgets/issues/{number}", labels=[])
    base.update(kw)
    return base


# ---------- finding 1: a mixed apply that fails midway ----------

def test_a_failing_apply_changes_nothing_local_and_can_be_retried(gh, project):
    run("source", "sync")
    good = [p for p in pending(project)]
    bad = {"id": "P9", "task": "nonexistent", "status": "done"}
    gp.save_pending(project, good[:1] + [bad] + good[1:])
    before = (project / ".daedalus/roadmap/index.json").read_text()
    out = run("gameplan", "pending", "apply", "all")
    assert out.exit_code == 1 and "still pending" in out.output
    assert (project / ".daedalus/roadmap/index.json").read_text() == before
    assert len(pending(project)) == 4
    run("gameplan", "pending", "drop", "P9")
    again = run("gameplan", "pending", "apply", "all")
    assert again.exit_code == 0, again.output
    assert {i["id"] for i in index(project)["items"]} == {"github-12", "github-13"}


# ---------- finding 2: a write-back's record survives a later failure ----------

def test_write_back_record_is_saved_even_if_the_rest_of_the_apply_fails(gh, project):
    gh.on("PATCH", "/issues/14", {"number": 14})
    run("source", "sync")
    run("gameplan", "pending", "apply", "all")
    run("gameplan", "phase", "activate", "github-m1")
    run("gameplan", "task", "status", "github-14", "done")
    [wb] = pending(project)
    gp.save_pending(project, [wb, {"id": "P9", "task": "nonexistent", "status": "done"}])
    assert run("gameplan", "pending", "apply", "all").exit_code == 1
    assert len(gh.writes()) == 1
    assert gp.load_gameplan(project)["activePhase"]["tasks"][0]["writeBack"] == "applied"
    assert [p["id"] for p in pending(project)] == ["P9"]
    assert doctor.check_sources(project) == []


# ---------- finding 3: a close between a sync and the apply ----------

def test_a_close_between_sync_and_apply_is_seen_on_the_next_sync(gh, project):
    open_issues = [_issue(13, updated_at="2026-10-11T08:30:00Z")]
    world = {"13": dict(open_issues[0])}

    def since_query(url):
        since = url.split("since=")[1].split("&")[0].replace("%3A", ":")
        return [i for i in world.values() if i["updated_at"] > since]

    github_routes(gh, issues=open_issues)
    gh.on("GET", "/repos/acme/widgets/issues?state=all", since_query)
    run("source", "sync")                                     # proposes 13
    world["13"] = dict(world["13"], state="closed", updated_at="2026-10-12T00:00:00Z")
    gh.on("GET", "/repos/acme/widgets/issues?state=open", [])
    run("source", "sync")                                     # 13 is only pending: nothing to do yet
    run("gameplan", "pending", "apply", "all")                # applies the stale, open version
    run("source", "sync")
    [p] = pending(project)
    assert p["kind"] == "roadmap-update" and p["changes"] == {"status": "done"}


# ---------- finding 4: sub-issues under an unassigned parent ----------

def test_a_sub_issues_unassigned_parent_is_fetched(gh, project):
    child = _issue(20, parent_issue_url="https://api.github.com/repos/acme/widgets/issues/99")
    github_routes(gh, issues=[child])
    gh.on("GET", "/repos/acme/widgets/issues/99", _issue(99, title="Parent epic-ish issue"))
    run("source", "sync")
    kinds = {(p["kind"], p.get("item", {}).get("id") if p["kind"] == "roadmap-new" else None) for p in pending(project)}
    assert ("roadmap-new", "github-99") in kinds


def test_a_task_waiting_for_a_phase_shows_in_status(gh, project):
    parent = _issue(30)
    child = _issue(31, parent_issue_url="https://api.github.com/repos/acme/widgets/issues/30")
    github_routes(gh, issues=[parent, child])
    run("source", "sync")
    status = run("source", "status").output
    assert "1 item(s) waiting for a phase" in status and "Sub-issue 31" in status


# ---------- finding 5: a dropped intake proposal stays dropped ----------

def test_dropped_intake_is_not_proposed_again(gh, project):
    run("source", "sync")
    bug = next(p for p in pending(project) if p.get("item", {}).get("id") == "github-13")
    run("gameplan", "pending", "drop", bug["id"])
    assert "proposed 0" in run("source", "sync").output
    assert "1 dropped item(s)" in run("source", "status").output


# ---------- finding 7: a malformed response ----------

def test_a_malformed_response_is_a_finding_not_a_crash(gh, project):
    github_routes(gh, issues={"message": "Not what you expected"})
    out = run("source", "sync")
    assert out.exit_code == 1 and "expected shape" in out.output
    assert [f.name for f in doctor.check_sources(project)] == ["source-unreachable"]


# ---------- finding 8: --workstream must exist ----------

def test_sync_into_a_missing_workstream_is_refused(gh, project):
    out = run("source", "sync", "-w", "nope")
    assert out.exit_code == 2 and "No workstream 'nope'" in out.output
    assert not (project / ".daedalus/gameplans/nope.pending.json").exists()


# ---------- finding 9: token_env is a name, never a token ----------

def test_a_pasted_token_is_refused_as_token_env(offline):
    out = run("config", "sources.github.token_env", "ghp_abcdefghijklmnop1234567890")
    assert out.exit_code == 1 and "NAME of an environment variable" in out.output
    assert run("config", "sources.github.token_env", "GITHUB_TOKEN").exit_code == 0


# ---------- finding 10: an unknown kind can still be listed and dropped ----------

def test_an_unknown_kind_can_be_listed_and_dropped(project):
    gp.save_pending(project, [{"id": "P1", "kind": "from-the-future", "x": 1}])
    listed = run("gameplan", "pending")
    assert listed.exit_code == 0 and "can't apply" in listed.output
    assert run("gameplan", "pending", "drop", "P1").exit_code == 0
    assert pending(project) == []


# ---------- the test gaps ----------

def test_open_issues_are_filtered_to_the_token_user_by_default(gh, project):
    run("source", "sync")
    url = next(c["url"] for c in gh.calls if "state=open" in c["url"])
    assert "assignee=octo-owner" in url
    run("config", "--project", "sources.github.assignee", "*")
    run("source", "sync")
    assert "assignee=%2A" in [c["url"] for c in gh.calls if "state=open" in c["url"]][-1]


def test_hooks_and_doctor_never_load_plugins(gh, project):
    from daedalus.hooks import session_start_brief

    run("source", "sync")
    sources.reset()
    session_start_brief(project)
    doctor.run_checks(project)
    assert sources._plugins is None


def test_init_writes_the_index_negation_in_a_fresh_project(tmp_path, monkeypatch, offline):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    monkeypatch.chdir(tmp_path)
    run("init", "--no-hooks")
    assert "!.daedalus/roadmap/index.json" in (tmp_path / ".gitignore").read_text()
    assert subprocess.run(["git", "check-ignore", "-q", ".daedalus/roadmap/index.json"], cwd=tmp_path).returncode == 1


def test_token_from_the_keyring_then_gh(project, offline):
    github_routes(offline["transport"])
    offline["keyring"]["github"] = "from-keyring"
    run("source", "sync")
    assert offline["transport"].calls[0]["headers"]["Authorization"] == "Bearer from-keyring"
    del offline["keyring"]["github"]
    credentials_gh = credentials.from_gh
    try:
        credentials.from_gh = lambda: "from-gh"
        run("source", "sync")
    finally:
        credentials.from_gh = credentials_gh
    assert offline["transport"].calls[-1]["headers"]["Authorization"] == "Bearer from-gh"


def test_login_stores_in_the_keyring_not_config(project, offline):
    from click.testing import CliRunner
    from daedalus.cli.main import main

    out = CliRunner().invoke(main, ["source", "login", "github"], input="secret-xyz\n")
    assert out.exit_code == 0 and offline["keyring"]["github"] == "secret-xyz"
    for path in project.rglob("*.json"):
        assert "secret-xyz" not in path.read_text()


def test_ok_health_for_a_verified_source(gh, project, monkeypatch):
    from daedalus.sources.github import GitHubSource

    monkeypatch.setattr(GitHubSource, "verified", True)
    run("source", "sync")
    assert "github     ok " in run("source", "status").output


def test_dropped_item_write_back_is_recorded_on_the_item(gh, project):
    run("source", "sync")
    run("gameplan", "pending", "apply", "all")
    run("gameplan", "phase", "activate", "github-m1")
    run("gameplan", "task", "add", "polish", "Polish")
    data = gp.load_gameplan(project)
    gp.find_task(data, "polish")["roadmapItem"] = "github-12"
    gp.save_gameplan(project, data)
    run("gameplan", "task", "status", "polish", "done")
    [p] = pending(project)
    run("gameplan", "pending", "drop", p["id"])
    assert roadmap.find(index(project), "github-12")["synced"]["write_back"] == "dropped"
    assert gh.writes() == []
