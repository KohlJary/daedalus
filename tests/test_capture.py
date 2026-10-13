"""Capture hook proposes gameplan updates from commits; pending apply/drop resolve them (edict 0007)."""

import json
import os
import subprocess
import time

import pytest
from click.testing import CliRunner

from daedalus import config as config_module
from daedalus.cli import gameplan as gp
from daedalus.cli.main import main
from daedalus.hooks import capture, propose_from_commits

ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
       "GIT_COMMITTER_EMAIL": "t@t", "PATH": os.environ["PATH"]}


@pytest.fixture(autouse=True)
def isolated_config(monkeypatch, tmp_path_factory):
    monkeypatch.setattr(config_module, "get_config_file", lambda: tmp_path_factory.mktemp("cfg") / "config.json")


def git(repo, *args):
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, env=ENV)


def commit(repo, msg):
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "--allow-empty", "-m", msg)


@pytest.fixture
def repo(tmp_path):
    git(tmp_path, "init", "-q")
    data = gp.empty_gameplan()
    gp.add_phase(data, "p2", "Memory backbone")
    gp.activate_phase(data, "p2")
    gp.add_task(data, "T-1", "Doctor")
    gp.add_task(data, "T-2", "Wire the session-start hook")
    gp.add_task(data, "T-10", "Something else")
    gp.add_task(data, "T-3", "Already done")
    gp.set_task_status(data, "T-3", "done")
    gp.save_gameplan(tmp_path, data)
    commit(tmp_path, "gameplan")
    return tmp_path


def run(repo, monkeypatch, *args):
    monkeypatch.chdir(repo)
    result = CliRunner().invoke(main, list(args))
    assert result.exit_code == 0, result.output
    return result.output


def test_proposes_done_for_tasks_named_in_new_commits(repo):
    commit(repo, "Add doctor (T-1)")
    commit(repo, "Wire the session-start hook into settings.json")
    commit(repo, "Touch T-3 again")          # already done: ignored
    commit(repo, "Unrelated work")
    proposals = {p["task"]: p for p in propose_from_commits(repo)}
    assert set(proposals) == {"T-1", "T-2"}   # T-10 is not matched by "T-1"
    assert proposals["T-1"]["status"] == "done"
    assert "Add doctor (T-1)" in proposals["T-1"]["resolution"]
    assert len(proposals["T-1"]["commits"]) == 1


def test_capture_never_touches_gameplan_and_dedupes(repo):
    before = gp.pending_path(repo).parent.joinpath("gameplan.json").read_text()
    commit(repo, "T-1 first pass")
    assert "T-1" in capture(repo)
    assert capture(repo) == ""                # same commits: nothing new
    commit(repo, "T-1 second pass")
    assert "T-1" in capture(repo)             # new evidence replaces the proposal
    proposals = gp.load_pending(repo)
    assert [p["id"] for p in proposals] == ["P1"] and len(proposals[0]["commits"]) == 2
    assert (repo / ".daedalus/roadmap/gameplan.json").read_text() == before


def test_untracked_gameplan_uses_file_time(tmp_path):
    git(tmp_path, "init", "-q")
    (tmp_path / ".gitignore").write_text(".daedalus/\n")   # like this repo: the gameplan has no commits
    commit(tmp_path, "T-1 before the plan existed")
    time.sleep(1.1)
    data = gp.empty_gameplan()
    gp.add_phase(data, "p", "P")
    gp.activate_phase(data, "p")
    gp.add_task(data, "T-1", "Doctor")
    gp.save_gameplan(tmp_path, data)        # never committed, like a gitignored gameplan
    time.sleep(1.1)
    assert propose_from_commits(tmp_path) == []
    commit(tmp_path, "T-1 after")
    assert [p["task"] for p in propose_from_commits(tmp_path)] == ["T-1"]


def test_pending_list_apply_drop(repo, monkeypatch):
    commit(repo, "T-1 done")
    commit(repo, "T-2 done")
    capture(repo)
    out = run(repo, monkeypatch, "gameplan", "pending")
    assert "P1: T-1 -> done" in out and "P2: T-2 -> done" in out

    assert "Applied P1: T-1 -> done" in run(repo, monkeypatch, "gameplan", "pending", "apply", "P1")
    task = gp.find_task(gp.load_gameplan(repo), "T-1")
    assert task["status"] == "done" and task["resolution"].startswith("Commits: ")

    assert "Dropped P2: T-2" in run(repo, monkeypatch, "gameplan", "pending", "drop", "all")
    assert gp.find_task(gp.load_gameplan(repo), "T-2")["status"] == "pending"
    assert "No pending gameplan updates." in run(repo, monkeypatch, "gameplan", "pending")
    assert not gp.pending_path(repo).exists()


def test_cli_hook_capture_is_quiet_without_news(repo, monkeypatch):
    assert run(repo, monkeypatch, "hook", "capture") == ""
    commit(repo, "T-2 shipped")
    assert "proposed gameplan updates for T-2" in run(repo, monkeypatch, "hook", "capture")


def test_unknown_proposal_is_an_error(repo, monkeypatch):
    monkeypatch.chdir(repo)
    result = CliRunner().invoke(main, ["gameplan", "pending", "apply", "P9"])
    assert "No pending proposal 'P9'" in result.output
