"""reconstruct gather: gap detection, message scoring, diffs for weak messages (edict 0006)."""

import json
import os
import subprocess

import pytest
from click.testing import CliRunner

from daedalus import config as config_module
from daedalus.cli import gameplan as gp
from daedalus.cli.main import main
from daedalus.reconstruct import gather, score_message

ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
       "GIT_COMMITTER_EMAIL": "t@t", "PATH": os.environ["PATH"]}


@pytest.fixture(autouse=True)
def isolated_config(monkeypatch, tmp_path_factory):
    monkeypatch.setattr(config_module, "get_config_file", lambda: tmp_path_factory.mktemp("cfg") / "config.json")


def git(repo, *args):
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, env=ENV)


def commit(repo, msg, files=None):
    for name, text in (files or {}).items():
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).write_text(text, encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "--allow-empty", "-m", msg)


RICH = ("Add the convergence-failure detector (T-a3)\n\n"
        "Detects when the same finding recurs across three review passes on one feature and pauses "
        "the loop for the operator. Stops the oscillation that burned five passes on mvp-demo F1.")


@pytest.fixture
def repo(tmp_path):
    git(tmp_path, "init", "-q")
    data = gp.empty_gameplan()
    gp.add_phase(data, "p1", "Pilot")
    gp.activate_phase(data, "p1")
    gp.add_task(data, "T-a3", "Convergence-failure detection")
    gp.save_gameplan(tmp_path, data)
    (tmp_path / ".daedalus/roadmap/index.json").write_text(json.dumps(
        {"items": [{"id": "r1", "title": "Detector", "status": "backlog"}]}))
    commit(tmp_path, "gameplan")
    commit(tmp_path, RICH, {"src/convergence.py": "def detect():\n    return True\n"})
    commit(tmp_path, "fix stuff", {"src/a.py": "x = 1\n" * 40})
    commit(tmp_path, "wip", {"src/b.py": "y = 2\n"})
    commit(tmp_path, "release: 0.9.0", {"release-notes/0.9.0.md": "notes\n"})
    commit(tmp_path, "Write up the pilot results in an analysis", {"analyses/046-receipt.md": "# 046\n"})
    return tmp_path


def by_subject(bundle):
    return {c["subject"]: c for c in bundle.commits}


def test_scores_separate_rich_from_bare():
    rich = score_message(*RICH.split("\n\n", 1), lines_changed=2)
    bare = score_message("fix stuff", "", lines_changed=40)
    wip = score_message("wip", "", lines_changed=1)
    assert rich.total >= 80 and rich.references == ["T-a3"] and rich.specific_subject
    assert bare.total < 20 and not bare.specific_subject and not bare.has_body
    assert wip.total < 20


def test_bare_commits_get_diffs_rich_do_not(repo):
    bundle = gather(repo)
    commits = by_subject(bundle)
    assert bundle.window["commits"] == 5 and bundle.window["anchor"] == "last gameplan commit"
    for bare in ("fix stuff", "wip"):
        assert commits[bare]["diff_reason"] == "low score"
        assert "src/" in commits[bare]["diff"]["stat"]
    rich = commits[RICH.split("\n")[0]]
    assert rich["score"]["total"] >= 50
    # rich commits get a diff only as part of the calibration sample
    assert rich.get("diff_reason") in (None, "calibration sample")


def test_calibration_sample_is_deterministic_and_bounded(repo):
    (repo / ".daedalus/config.json").write_text(json.dumps({"reconstruct": {"sample_size": 1}}))
    first = [c["sha"] for c in gather(repo).commits if c.get("diff_reason") == "calibration sample"]
    second = [c["sha"] for c in gather(repo).commits if c.get("diff_reason") == "calibration sample"]
    assert len(first) == 1 and first == second


def test_bundle_contents(repo):
    bundle = gather(repo)
    assert [r["subject"] for r in bundle.releases] == ["release: 0.9.0"]
    assert {d["file"] for d in bundle.documents_added} == {"analyses/046-receipt.md", "release-notes/0.9.0.md"}
    assert [t["id"] for t in bundle.open_tasks] == ["T-a3"]
    assert [i["id"] for i in bundle.open_roadmap_items] == ["r1"]
    assert bundle.evidence_scope == "git"


def test_diff_is_capped(repo):
    (repo / ".daedalus/config.json").write_text(json.dumps({"reconstruct": {"diff_cap": 100}}))
    diff = by_subject(gather(repo))["fix stuff"]["diff"]
    assert len(diff["patch"]) == 100 and diff["truncated"]


def test_outside_git_evidence_paths(repo):
    runs = repo / "projects/wwu/runs"
    runs.mkdir(parents=True)
    (runs / "run1.jsonl").write_text("{}\n")
    (repo / ".daedalus/config.json").write_text(json.dumps({"reconstruct": {"evidence_paths": ["projects", "gone"]}}))
    bundle = gather(repo)
    assert bundle.evidence_scope == "git+paths"
    listing = {l["path"]: l for l in bundle.outside_git}
    assert listing["projects"]["files"][0]["file"] == "projects/wwu/runs/run1.jsonl"
    assert listing["gone"]["missing"]


def test_no_gap_and_cli(repo, monkeypatch):
    monkeypatch.chdir(repo)
    runner = CliRunner()
    out = runner.invoke(main, ["reconstruct", "gather"]).output
    assert "Gap: 5 commits" in out and "Bundle: .daedalus/reconstruction/bundle-" in out
    bundle_file = next((repo / ".daedalus/reconstruction").glob("bundle-*.json"))
    assert json.loads(bundle_file.read_text())["schema"] == "daedalus.reconstruction-bundle/1"

    commit(repo, "gameplan: record what shipped", {".daedalus/roadmap/gameplan.json": "{}\n"})
    assert "No gap: the gameplan is current." in runner.invoke(main, ["reconstruct", "gather"]).output


def test_since_overrides_the_anchor(repo):
    first = subprocess.run(["git", "rev-list", "--max-parents=0", "HEAD"], cwd=repo,
                           capture_output=True, text=True).stdout.strip()
    bundle = gather(repo, since=first)
    assert bundle.window["commits"] == 5 and bundle.window["anchor"].startswith("--since")


def test_no_gameplan_needs_since(tmp_path, monkeypatch):
    git(tmp_path, "init", "-q")
    commit(tmp_path, "one")
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(main, ["reconstruct", "gather"])
    assert result.exit_code == 2 and "--since" in result.output


def test_until_and_author_narrow_the_window(repo):
    log = subprocess.run(["git", "log", "--reverse", "--format=%H"], cwd=repo, capture_output=True,
                         text=True).stdout.split()
    bundle = gather(repo, until=log[3])                 # gameplan..(fix stuff, wip) + rich
    assert [c["subject"] for c in bundle.commits][-1] == "wip"
    assert bundle.window["until"] == log[3] and bundle.window["to"] == log[3]

    env = {**ENV, "GIT_AUTHOR_NAME": "Frank"}
    subprocess.run(["git", "commit", "-q", "--allow-empty", "-m", "Frank's June work on the parser"],
                   cwd=repo, check=True, env=env)
    frank = gather(repo, author="Frank")
    assert [(c["author"], c["subject"]) for c in frank.commits] == [("Frank", "Frank's June work on the parser")]
    assert frank.window["author"] == "Frank"


def test_date_windows(repo):
    today = subprocess.run(["git", "log", "-1", "--format=%as"], cwd=repo, capture_output=True,
                           text=True).stdout.strip()
    assert gather(repo, since=today, until=today).window["commits"] >= 5
    assert gather(repo, since="2001-01-01", until="2001-01-31") is None


def test_bundle_names_do_not_collide(repo, monkeypatch):
    from daedalus.reconstruct import write_bundle
    a = write_bundle(repo, gather(repo))
    b = write_bundle(repo, gather(repo, author="t"))
    assert a != b and a.exists() and b.exists()
