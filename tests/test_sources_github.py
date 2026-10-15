"""The GitHub Issues source, sync, conflicts and write-back (edict 0011), against synthetic fixtures."""

import json

import pytest

from daedalus import doctor, roadmap
from daedalus.cli import gameplan as gp
from daedalus.sources import sync as sync_mod
from daedalus.sources.github import parse_remote

from sources_helpers import github_routes, index, offline, pending, project, run  # noqa: F401


@pytest.fixture
def gh(project, offline):
    """GitHub with a token from the environment variable the config names."""
    run("config", "--project", "sources.github.token_env", "TEST_GH_TOKEN")
    import os

    os.environ["TEST_GH_TOKEN"] = "t0ken"
    github_routes(offline["transport"])
    yield offline["transport"]
    os.environ.pop("TEST_GH_TOKEN", None)


def apply_all(project_dir):
    return run("gameplan", "pending", "apply", "all")


def test_remote_parsing():
    assert parse_remote("git@github.com:acme/widgets.git") == "acme/widgets"
    assert parse_remote("https://github.com/acme/widgets") == "acme/widgets"
    assert parse_remote("https://gitlab.com/acme/widgets.git") is None


def test_github_is_active_unconfigured_in_a_github_repo(project):
    out = run("source", "list")
    assert "github" in out.output and "active" in out.output


def test_dry_run_prints_and_writes_nothing(gh, project):
    before = (project / ".daedalus/roadmap/index.json").read_text()
    out = run("source", "sync", "github", "--dry-run")
    assert out.exit_code == 0, out.output
    assert "would propose 3" in out.output
    assert "new phase github-m1" in out.output and "new roadmap item github-13" in out.output
    assert pending(project) == []
    assert (project / ".daedalus/roadmap/index.json").read_text() == before
    assert not (project / ".daedalus/sources/state.json").exists()


def test_sync_maps_milestones_issues_and_sub_issues(gh, project):
    out = run("source", "sync")
    assert out.exit_code == 0, out.output
    props = pending(project)
    kinds = sorted((p["kind"], p.get("phase", {}).get("id") if p["kind"] == "new-phase" else p.get("item", {}).get("id"))
                   for p in props)
    assert kinds == [("new-phase", "github-m1"), ("roadmap-new", "github-12"), ("roadmap-new", "github-13")]
    phase = next(p for p in props if p["kind"] == "new-phase")["phase"]
    assert phase["roadmapItems"] == ["github-12"]
    # The sub-issue becomes a task, queued on the phase that references its parent's item
    assert [(t["id"], t["roadmapItem"], t["origin"]["external_id"]) for t in phase["tasks"]] == \
        [("github-14", "github-12", "14")]
    bug = next(p for p in props if p["kind"] == "roadmap-new" and p["item"]["id"] == "github-13")
    assert bug["item"]["item_type"] == "bug" and bug["item"]["status"] == "ready"
    assert bug["item"]["origin"] == {"source": "github", "external_id": "13",
                                     "url": "https://github.com/acme/widgets/issues/13"}
    # Pull requests are not intake
    assert not any("15" == str(p.get("origin", {}).get("external_id")) for p in props)
    # No write happened, and the token never reached a URL
    assert gh.writes() == []
    assert all("t0ken" not in c["url"] for c in gh.calls)


def test_sync_twice_adds_nothing_and_again_after_apply_adds_nothing(gh, project):
    run("source", "sync")
    first = pending(project)
    again = run("source", "sync")
    assert "proposed 0" in again.output
    assert pending(project) == first
    assert apply_all(project).exit_code == 0
    assert pending(project) == []
    after = run("source", "sync")
    assert "proposed 0" in after.output, after.output
    assert pending(project) == []
    data = gp.load_gameplan(project)
    phase = gp.find_phase(data, "github-m1")
    assert phase["roadmapItems"] == ["github-12"]
    assert phase["tasks"][0]["origin"]["external_id"] == "14"
    items = {i["id"]: i for i in index(project)["items"]}
    assert items["github-12"]["synced"]["fields"]["title"] == "Sync settings across devices"


def test_another_workstreams_pending_proposal_is_not_duplicated(gh, project):
    run("workstream", "new", "alice")
    run("source", "sync", "--workstream", "alice")
    assert len(pending(project, "alice")) == 3
    out = run("source", "sync")
    assert "proposed 0" in out.output
    assert pending(project) == []


def _apply_then_change(project, gh, local_title=None, remote_title=None, remote_state=None):
    run("source", "sync")
    apply_all(project)
    if local_title:
        data = index(project)
        next(i for i in data["items"] if i["id"] == "github-13")["title"] = local_title
        (project / ".daedalus/roadmap/index.json").write_text(json.dumps(data))
    issues = github_routes(gh)["issues_open"]
    for issue in issues:
        if issue["number"] == 13:
            if remote_title:
                issue["title"] = remote_title
            if remote_state:
                issue["state"] = remote_state
            issue["updated_at"] = "2026-10-14T00:00:00Z"
    github_routes(gh, issues=issues)


def test_remote_only_change_is_an_ordinary_update(gh, project):
    _apply_then_change(project, gh, remote_title="Crash when the cache is cold")
    run("source", "sync")
    [p] = pending(project)
    assert p["kind"] == "roadmap-update" and p["changes"] == {"title": "Crash when the cache is cold"}
    assert p["conflicts"] == {}
    apply_all(project)
    item = roadmap.find(index(project), "github-13")
    assert item["title"] == "Crash when the cache is cold"
    assert "proposed 0" in run("source", "sync").output


def test_local_only_change_stays_local(gh, project):
    _apply_then_change(project, gh, local_title="Our own wording")
    assert "proposed 0" in run("source", "sync").output
    assert roadmap.find(index(project), "github-13")["title"] == "Our own wording"


def test_conflict_propose_is_the_default(gh, project):
    _apply_then_change(project, gh, local_title="Ours", remote_title="Theirs")
    run("source", "sync")
    [p] = pending(project)
    assert p["kind"] == "roadmap-update"
    assert p["changes"] == {"title": "Theirs"}
    assert p["conflicts"]["title"]["local"] == "Ours"
    assert "changed here too: title" in gp.describe_proposal(p)
    assert roadmap.find(index(project), "github-13")["title"] == "Ours"
    # Re-syncing doesn't stack a second copy
    run("source", "sync")
    assert len(pending(project)) == 1


def test_conflict_source_takes_the_trackers_value_and_records_it(gh, project):
    run("config", "--project", "sources.github.on_conflict", "source")
    _apply_then_change(project, gh, local_title="Ours", remote_title="Theirs")
    out = run("source", "sync")
    assert "settled by on_conflict" in out.output
    assert pending(project) == []
    item = roadmap.find(index(project), "github-13")
    assert item["title"] == "Theirs"
    assert item["synced"]["history"][-1]["outcome"] == "took the source's value"
    assert "proposed 0" in run("source", "sync").output


def test_conflict_local_keeps_ours_and_records_it(gh, project):
    run("config", "--project", "sources.github.on_conflict", "local")
    _apply_then_change(project, gh, local_title="Ours", remote_title="Theirs")
    run("source", "sync")
    assert pending(project) == []
    item = roadmap.find(index(project), "github-13")
    assert item["title"] == "Ours"
    assert item["synced"]["fields"]["title"] == "Theirs"
    assert item["synced"]["history"][-1]["outcome"] == "kept the local value"
    assert "proposed 0" in run("source", "sync").output


def test_source_never_touches_a_task_resolution_or_unowned_fields(gh, project):
    run("config", "--project", "sources.github.on_conflict", "source")
    _apply_then_change(project, gh, local_title="Ours", remote_title="Theirs")
    data = index(project)
    item = next(i for i in data["items"] if i["id"] == "github-13")
    item["priority"] = "P0"
    (project / ".daedalus/roadmap/index.json").write_text(json.dumps(data))
    run("source", "sync")
    assert roadmap.find(index(project), "github-13")["priority"] == "P0"


def test_a_closed_issue_is_seen_through_the_since_query(gh, project):
    _apply_then_change(project, gh)
    data = github_routes(gh)
    closed = dict(next(i for i in data["issues_open"] if i["number"] == 13), state="closed")
    github_routes(gh, issues=[i for i in data["issues_open"] if i["number"] != 13], since=[closed])
    run("source", "sync")
    [p] = pending(project)
    assert p["changes"] == {"status": "done"}
    # Dropping it keeps the item open here: doctor then reports the drift
    run("gameplan", "pending", "drop", p["id"])
    names = [f.name for f in doctor.check_sources(project)]
    assert "source-drift" in names


def test_a_failed_sync_is_a_doctor_finding_not_a_crash(gh, project):
    gh.on("GET", "api.github.com/user", {"message": "Bad credentials"}, status=401)
    out = run("source", "sync", "github")
    assert out.exit_code == 1 and "auth-failed" in out.output
    names = [f.name for f in doctor.check_sources(project)]
    assert names == ["source-auth-failed"]
    assert "auth-failed" in run("source", "status").output
    # The rest of Daedalus works as before
    assert run("gameplan", "show").exit_code == 0


def test_no_token_anywhere_is_auth_failed(project, offline):
    out = run("source", "sync", "github")
    assert out.exit_code == 1 and "No GitHub token" in out.output


def test_unreachable(gh, project):
    from daedalus.sources.base import SourceError

    def down(*a):
        raise SourceError("Couldn't reach api.github.com: timed out", "unreachable")

    from daedalus.sources import http
    http.set_transport(down)
    assert run("source", "sync").exit_code == 1
    assert [f.name for f in doctor.check_sources(project)] == ["source-unreachable"]


def test_status_and_roadmap_views(gh, project):
    assert "never-synced" in run("source", "status").output
    run("source", "sync")
    apply_all(project)
    status = run("source", "status").output
    assert "github" in status and "unverified" in status and "2 item(s)" in status
    listed = run("roadmap", "list").output
    assert "[github 13]" in listed and "(github-13)" in listed
    run("roadmap", "add", "A local idea")
    assert "[local]" in run("roadmap", "list").output
    shown = run("roadmap", "show", "github-12").output
    assert "origin: github 12  https://github.com/acme/widgets/issues/12" in shown
    assert "last sync saw:" in shown
    assert "Phases:\n  default/github-m1" in shown
    assert "Tasks:\n  default/github-m1/github-14" in shown


# ---------- write-back ----------


def _activate_with_sub_issue(project):
    run("source", "sync")
    apply_all(project)
    out = run("gameplan", "phase", "activate", "github-m1")
    assert out.exit_code == 0, out.output
    data = gp.load_gameplan(project)
    assert [t["id"] for t in data["activePhase"]["tasks"]] == ["github-14"]


def test_done_task_proposes_a_write_back_and_applying_calls_the_tracker(gh, project):
    gh.on("PATCH", "/issues/14", {"number": 14, "state": "closed"})
    _activate_with_sub_issue(project)
    out = run("gameplan", "task", "status", "github-14", "done", "-r", "Endpoint shipped")
    assert "write back to github 14" in out.output
    [p] = pending(project)
    assert p["kind"] == "write-back" and p["target"] == "task" and p["comment"] is None
    assert gh.writes() == []
    assert apply_all(project).exit_code == 0
    [call] = gh.writes()
    assert call["method"] == "PATCH" and call["url"].endswith("/repos/acme/widgets/issues/14")
    assert call["body"] == {"state": "closed", "state_reason": "completed"}
    task = gp.load_gameplan(project)["activePhase"]["tasks"][0]
    assert task["writeBack"] == "applied"
    assert doctor.check_sources(project) == []


def test_write_back_comment_posts_the_resolution(gh, project):
    run("config", "--project", "sources.github.write_back_comment", "true")
    gh.on("PATCH", "/issues/14", {"number": 14}).on("POST", "/issues/14/comments", {"id": 1})
    _activate_with_sub_issue(project)
    run("gameplan", "task", "status", "github-14", "done", "-r", "Endpoint shipped")
    apply_all(project)
    assert [c["body"] for c in gh.writes()] == [{"state": "closed", "state_reason": "completed"},
                                                 {"body": "Endpoint shipped"}]


def test_dropping_a_write_back_calls_nothing_and_is_recorded(gh, project):
    _activate_with_sub_issue(project)
    run("gameplan", "task", "status", "github-14", "done")
    [p] = pending(project)
    run("gameplan", "pending", "drop", p["id"])
    assert gh.writes() == []
    assert gp.load_gameplan(project)["activePhase"]["tasks"][0]["writeBack"] == "dropped"
    assert doctor.check_sources(project) == []


def test_a_failed_write_back_stays_pending(gh, project):
    gh.on("PATCH", "/issues/14", {"message": "nope"}, status=500)
    _activate_with_sub_issue(project)
    run("gameplan", "task", "status", "github-14", "done")
    out = run("gameplan", "pending", "apply", "all")
    assert out.exit_code == 1 and "still pending" in out.output
    assert [p["kind"] for p in pending(project)] == ["write-back"]


def test_done_without_a_write_back_is_a_doctor_finding(gh, project):
    _activate_with_sub_issue(project)
    data = gp.load_gameplan(project)
    gp.set_task_status(data, "github-14", "done")  # bypasses the CLI, so no proposal is made
    gp.save_gameplan(project, data)
    assert [f.name for f in doctor.check_sources(project)] == ["source-write-back-missing"]


def test_item_origin_write_back_and_tasks_with_neither_never_write_back(gh, project):
    run("source", "sync")
    apply_all(project)
    run("gameplan", "phase", "activate", "github-m1")
    # A local task pointing at a sourced item writes back to that item
    run("gameplan", "task", "add", "polish", "Polish the sync UI")
    data = gp.load_gameplan(project)
    gp.find_task(data, "polish")["roadmapItem"] = "github-12"
    gp.add_task(data, "unrelated", "Refactor config loading")  # neither origin nor roadmapItem
    gp.save_gameplan(project, data)
    run("gameplan", "task", "status", "polish", "done")
    run("gameplan", "task", "status", "unrelated", "done")
    [p] = pending(project)
    assert (p["task"], p["target"], p["item"], p["origin"]["external_id"]) == ("polish", "item", "github-12", "12")
    gh.on("PATCH", "/issues/12", {"number": 12})
    apply_all(project)
    assert roadmap.find(index(project), "github-12")["synced"]["write_back"] == "applied"


def test_session_start_brief_shows_last_sync_without_network(gh, project):
    from daedalus.hooks import session_start_brief

    run("source", "sync")
    calls = len(gh.calls)
    brief = session_start_brief(project)
    assert "**Sources last synced:** github 20" in brief
    assert len(gh.calls) == calls


def test_sync_module_compare():
    item = {"title": "B", "status": "ready", "synced": {"fields": {"title": "A", "status": "ready"}}}
    changes, conflicts, agreed = sync_mod.compare(item, {"title": "C", "status": "done"})
    assert changes == {"status": "done"} and list(conflicts) == ["title"] and agreed == []
    changes, conflicts, agreed = sync_mod.compare(item, {"title": "B", "status": "ready"})
    assert (changes, conflicts, agreed) == ({}, {}, ["title"])
