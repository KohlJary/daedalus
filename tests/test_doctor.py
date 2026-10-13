"""`daedalus doctor` finds memory drift (edict 0007).

Three fixtures model real states seen on 2026-10-13:
- wonderland-ai: a well-used gameplan that stopped being updated while work went on
- cass-vessel: no gameplan, a project map missing most packages, an empty roadmap the hook still reads
- daedalus itself: a gitignored gameplan, edict numbering and status mistakes, an untracked edict
"""

import json
import os
import subprocess
from datetime import date

import pytest
from click.testing import CliRunner

from daedalus import config as config_module
from daedalus.cli import gameplan as gp
from daedalus.cli.main import main
from daedalus.doctor import run_checks, source_packages

TODAY = date(2026, 10, 13)


@pytest.fixture(autouse=True)
def isolated_config(monkeypatch, tmp_path_factory):
    monkeypatch.setattr(config_module, "get_config_file", lambda: tmp_path_factory.mktemp("cfg") / "config.json")


def git(repo, *args):
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True,
                   env={"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
                        "GIT_COMMITTER_EMAIL": "t@t", "PATH": "/usr/bin:/bin"})


def commit_all(repo, msg):
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "--allow-empty", "-m", msg)


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def names(findings):
    return sorted(f.name for f in findings)


@pytest.fixture
def wonderland_like(tmp_path):
    repo = tmp_path / "wonderland"
    repo.mkdir()
    git(repo, "init", "-q")
    data = gp.empty_gameplan()
    gp.add_phase(data, "p20-autonomous-pilot", "Tier 2 autonomous pilot")
    gp.activate_phase(data, "p20-autonomous-pilot", started="2026-05-18")
    gp.add_task(data, "T-a1", "Trace M1 milestone deletion")
    data["activePhase"]["tasks"][0].update(status="in_progress", updated="2026-05-18")
    gp.add_task(data, "T-a7", "Pilot")
    data["activePhase"]["tasks"][1].update(status="done", resolution="shipped")
    gp.save_gameplan(repo, data)
    commit_all(repo, "release(0.8.0)")
    for i in range(12):
        write(repo / f"src/f{i}.py", "x = 1\n")
        commit_all(repo, f"feat: work {i}")
    return repo


@pytest.fixture
def cass_vessel_like(tmp_path):
    repo = tmp_path / "cass-vessel"
    repo.mkdir()
    git(repo, "init", "-q")
    for pkg in ("memory", "handlers", "thymos", "dreaming", "outreach"):
        write(repo / "backend" / pkg / "__init__.py", "")
    write(repo / "backend" / "venv" / "lib" / "junk" / "__init__.py", "")
    write(repo / ".daedalus/project-map.md", "# Project Map\n\n## memory\nHierarchical memory.\n\n## handlers\nTool handlers.\n")
    write(repo / ".daedalus/session-summaries.md", "# Session Summaries\n\n## 2026-02-25 - Work\nDid things.\n")
    write(repo / ".daedalus/roadmap/index.json", json.dumps({"items": [], "projects": []}))
    write(repo / ".claude/settings.json", json.dumps({"hooks": {"SessionStart": [{"hooks": [
        {"type": "command", "command": "daedalus hook session-start"}]}]}}))
    old = 1735000000  # 2024-12-24: the roadmap has sat empty since then
    os.utime(repo / ".daedalus/roadmap/index.json", (old, old))
    commit_all(repo, "init")
    return repo


@pytest.fixture
def daedalus_like(tmp_path):
    repo = tmp_path / "daedalus"
    repo.mkdir()
    git(repo, "init", "-q")
    write(repo / ".gitignore", ".daedalus/\n")
    write(repo / "docs/edicts/README.md", "# Edicts\nStatus: proposed | accepted | done\n")
    write(repo / "docs/edicts/0001-intent.md", "# Edict 0001\nStatus: acccepted\n")
    write(repo / "docs/edicts/0004-exhale-inhale.md", "# Edict 0004\nStatus: accepted\n")
    write(repo / "docs/edicts/0004-memory-backbone.md", "# Edict 0004\nStatus: accepted\n")
    write(repo / "docs/edicts/0005-opt-in.md", "# Edict 0005\nStatus: done\n")
    data = gp.empty_gameplan()
    gp.add_phase(data, "p2", "Memory backbone", edict="0004")
    gp.activate_phase(data, "p2")
    gp.add_task(data, "T1", "Doctor")
    gp.set_task_status(data, "T1", "done", resolution="built")
    gp.save_gameplan(repo, data)
    commit_all(repo, "init")
    return repo


def test_wonderland_like(wonderland_like):
    findings, hints = run_checks(wonderland_like, today=TODAY)
    assert names(findings) == ["commits-after-gameplan", "stale-task"]
    by_name = {f.name: f.message for f in findings}
    assert by_name["commits-after-gameplan"].startswith("12 commits since the gameplan was last updated")
    assert "T-a1" in by_name["stale-task"] and "148 days" in by_name["stale-task"]
    assert hints == []


def test_cass_vessel_like(cass_vessel_like):
    findings, hints = run_checks(cass_vessel_like, today=TODAY)
    assert names(findings) == ["empty-file-read-by-hook", "project-map-missing-packages"]
    by_name = {f.name: f.message for f in findings}
    assert "3 source package(s): dreaming, outreach, thymos" in by_name["project-map-missing-packages"]
    assert ".daedalus/roadmap/index.json" in by_name["empty-file-read-by-hook"]
    assert any("No gameplan" in h for h in hints)


def test_daedalus_like(daedalus_like):
    findings, _ = run_checks(daedalus_like, today=TODAY)
    # 0004 is referenced by the phase and 0005 is done, so no edict is unreferenced here
    assert names(findings) == [
        "edict-bad-status", "edict-duplicate-number", "gameplan-ignored", "phase-tasks-all-done",
    ]
    msgs = " ".join(f.message for f in findings)
    assert "'acccepted'" in msgs
    assert "0004-exhale-inhale.md, 0004-memory-backbone.md" in msgs


def test_unreferenced_edict_reported_only_when_accepted(daedalus_like):
    write(daedalus_like / "docs/edicts/0006-reconstruct.md", "# Edict 0006\nStatus: accepted\n")
    findings, _ = run_checks(daedalus_like, today=TODAY)
    unref = [f.message for f in findings if f.name == "edict-not-in-gameplan"]
    assert len(unref) == 1 and "0006" in unref[0]


def test_edicts_disabled_skips_reference_check(daedalus_like):
    write(daedalus_like / ".daedalus/config.json", json.dumps({"edicts": {"enabled": False}}))
    write(daedalus_like / "docs/edicts/0006-reconstruct.md", "# Edict 0006\nStatus: accepted\n")
    findings, _ = run_checks(daedalus_like, today=TODAY)
    assert "edict-not-in-gameplan" not in names(findings)


def test_thresholds_come_from_config(wonderland_like):
    write(wonderland_like / ".daedalus/config.json",
          json.dumps({"doctor": {"stale_commits": 50, "stale_task_days": 200}}))
    findings, _ = run_checks(wonderland_like, today=TODAY)
    assert findings == []


def test_clean_project_passes_and_cli_exit_codes(tmp_path, monkeypatch, wonderland_like):
    repo = tmp_path / "clean"
    repo.mkdir()
    git(repo, "init", "-q")
    gp.ensure_gameplan(repo)
    commit_all(repo, "init")
    runner = CliRunner()

    monkeypatch.chdir(repo)
    result = runner.invoke(main, ["doctor"])
    assert result.exit_code == 0 and "No drift found." in result.output

    monkeypatch.chdir(wonderland_like)
    result = runner.invoke(main, ["doctor", "--json"])
    assert result.exit_code == 1
    assert {f["name"] for f in json.loads(result.output)["findings"]} == {"commits-after-gameplan", "stale-task"}


def test_project_without_daedalus_is_a_hint_not_a_failure(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(main, ["doctor"])
    assert result.exit_code == 0
    assert "hint: No gameplan" in result.output


def test_src_layout_checks_subpackages(tmp_path):
    for pkg in ("ariadne", "bus", "cli"):
        write(tmp_path / "src/daedalus" / pkg / "__init__.py", "")
    write(tmp_path / "src/daedalus/__init__.py", "")
    write(tmp_path / "tests/helpers/__init__.py", "")
    assert source_packages(tmp_path) == ["ariadne", "bus", "cli"]


def test_fresh_init_reports_no_drift(tmp_path, monkeypatch):
    from daedalus.config import DaedalusConfig
    from daedalus.templates import injector
    monkeypatch.setattr(injector, "load_daedalus_config", lambda config_path=None: {})
    monkeypatch.setattr(injector, "load_config", lambda: DaedalusConfig())
    monkeypatch.setattr(injector, "get_daedalus_email", lambda config: "daedalus@example.com")
    monkeypatch.setattr("daedalus.cli.commands.get_config_dir", lambda: tmp_path / "cfg")
    repo = tmp_path / "fresh"
    repo.mkdir()
    git(repo, "init", "-q")
    monkeypatch.chdir(repo)
    assert CliRunner().invoke(main, ["init"]).exit_code == 0
    result = CliRunner().invoke(main, ["doctor"])
    assert result.exit_code == 0, result.output
