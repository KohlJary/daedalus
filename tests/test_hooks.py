"""Session-start hook: brief content and registration in .claude/settings.json (edict 0007)."""

import json

import pytest
from click.testing import CliRunner

from daedalus import config as config_module
from daedalus.cli import gameplan as gp
from daedalus.cli.main import main
from daedalus.hooks import (
    MAX_BRIEF_LINES, SESSION_START_COMMAND, latest_session_note, register_hooks, session_start_brief,
)


@pytest.fixture(autouse=True)
def isolated_config(monkeypatch, tmp_path_factory):
    monkeypatch.setattr(config_module, "get_config_file", lambda: tmp_path_factory.mktemp("cfg") / "config.json")


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def settings(project):
    return json.loads((project / ".claude" / "settings.json").read_text(encoding="utf-8"))


# ---------- brief ----------


def test_brief_leads_with_gameplan_then_note(tmp_path):
    data = gp.empty_gameplan()
    gp.add_phase(data, "p2", "Memory backbone", edict="0007")
    gp.activate_phase(data, "p2", goal="Gameplan at the center")
    gp.add_task(data, "T1", "Doctor")
    gp.set_task_status(data, "T1", "done")
    gp.add_task(data, "T2", "Wire the hook")
    gp.save_gameplan(tmp_path, data)
    write(tmp_path / ".daedalus/session-summaries.md",
          "# Session Summaries\n\n## 2026-10-12 - Older\nold\n\n## 2026-10-13 - Newer\nnew work\n")

    brief = session_start_brief(tmp_path).splitlines()
    assert brief[1] == "**Phase:** p2 — Memory backbone (edict 0007)"
    assert brief[2] == "**Goal:** Gameplan at the center"
    assert brief[3] == "**Next task:** T2 [pending] Wire the hook"
    assert "## 2026-10-13 - Newer" in brief and "## 2026-10-12 - Older" not in brief
    assert brief[-1] == "Run /inhale for the full pickup."


def test_brief_shows_doctor_findings(tmp_path):
    gp.ensure_gameplan(tmp_path)
    write(tmp_path / "docs/edicts/0001-x.md", "# Edict\nStatus: acccepted\n")
    assert "- edict-bad-status:" in session_start_brief(tmp_path)


def test_brief_stays_under_limit(tmp_path):
    data = gp.empty_gameplan()
    gp.add_phase(data, "p", "P")
    gp.activate_phase(data, "p")
    gp.save_gameplan(tmp_path, data)
    write(tmp_path / ".daedalus/session-summaries.md", "## 2026-10-13\n" + "line\n" * 200)
    for i in range(20):
        write(tmp_path / f"docs/edicts/{i:04d}-a.md", "Status: nope\n")
    lines = session_start_brief(tmp_path).splitlines()
    assert len(lines) <= MAX_BRIEF_LINES
    assert lines[-1] == "Run /inhale for the full pickup."


def test_empty_roadmap_prints_nothing_and_in_progress_items_show(tmp_path):
    gp.ensure_gameplan(tmp_path)
    write(tmp_path / ".daedalus/roadmap/index.json", json.dumps({"items": []}))
    assert "Roadmap" not in session_start_brief(tmp_path)
    write(tmp_path / ".daedalus/roadmap/index.json",
          json.dumps({"items": [{"title": "Ship it", "status": "in_progress"}]}))
    assert "**Roadmap in progress:** Ship it" in session_start_brief(tmp_path)


def test_brief_without_daedalus_is_silent(tmp_path, monkeypatch):
    assert session_start_brief(tmp_path) == ""
    monkeypatch.chdir(tmp_path)
    assert CliRunner().invoke(main, ["hook", "session-start"]).output == ""


def test_latest_note_handles_newest_first_and_undated():
    newest_first = "# S\n\n## 2026-02-25 - B\nb\n\n## 2025-12-19 - A\na\n"
    assert latest_session_note(newest_first).startswith("## 2026-02-25")
    assert latest_session_note("## one\n1\n## two\n2\n").startswith("## two")
    assert latest_session_note("# Session Summaries\n") is None


def test_cli_hook_session_start(tmp_path, monkeypatch):
    gp.ensure_gameplan(tmp_path)
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(main, ["hook", "session-start"])
    assert result.exit_code == 0 and result.output.startswith("## Daedalus")


# ---------- registration ----------


def test_register_merges_and_is_idempotent(tmp_path):
    write(tmp_path / ".claude/settings.json", json.dumps({
        "permissions": {"allow": ["Bash(ls)"]},
        "hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": "echo hi"}]}]},
    }))
    added, removed, err = register_hooks(tmp_path)
    assert (added, removed, err) == (["SessionStart"], [], None)
    s = settings(tmp_path)
    assert s["permissions"] == {"allow": ["Bash(ls)"]}
    commands = [h["command"] for g in s["hooks"]["SessionStart"] for h in g["hooks"]]
    assert commands == ["echo hi", SESSION_START_COMMAND]

    assert register_hooks(tmp_path) == ([], [], None)
    assert settings(tmp_path) == s


def test_register_never_clobbers_bad_json(tmp_path):
    write(tmp_path / ".claude/settings.json", "{not json")
    added, _, err = register_hooks(tmp_path)
    assert added == [] and "not valid JSON" in err
    assert (tmp_path / ".claude/settings.json").read_text() == "{not json"


def test_capture_registered_only_when_enabled(tmp_path):
    register_hooks(tmp_path)
    assert set(settings(tmp_path)["hooks"]) == {"SessionStart"}
    register_hooks(tmp_path, capture=True)
    assert set(settings(tmp_path)["hooks"]) == {"SessionStart", "SessionEnd", "PreCompact"}


def test_dry_run_writes_nothing(tmp_path):
    added, _, _ = register_hooks(tmp_path, dry_run=True)
    assert added == ["SessionStart"]
    assert not (tmp_path / ".claude").exists()


def test_hydrate_registers_respects_flags_and_config(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    flags = ["hydrate", "--no-agents", "--no-template", "--no-skills"]

    out = runner.invoke(main, flags + ["--dry-run"]).output
    assert "Hooks that would be registered: SessionStart" in out
    assert not (tmp_path / ".claude/settings.json").exists()

    runner.invoke(main, flags + ["--no-hooks"])
    assert "hooks" not in settings(tmp_path)                 # no hooks; the board's ask rule still lands

    runner.invoke(main, flags)
    assert SESSION_START_COMMAND in (tmp_path / ".claude/settings.json").read_text()

    runner.invoke(main, ["config", "--project", "hooks.capture", "true"])
    runner.invoke(main, flags)
    assert "PreCompact" in settings(tmp_path)["hooks"]


@pytest.mark.parametrize("bad", [{"hooks": []}, {"hooks": {"SessionStart": ["x"]}},
                                 {"hooks": {"SessionStart": [{"hooks": "x"}]}}])
def test_register_reports_wrong_shapes_without_writing(tmp_path, bad):
    write(tmp_path / ".claude/settings.json", json.dumps(bad))
    added, removed, err = register_hooks(tmp_path)
    assert added == removed == [] and "hooks not registered" in err
    assert json.loads((tmp_path / ".claude/settings.json").read_text()) == bad


def test_disabling_capture_removes_only_daedalus_entries(tmp_path):
    write(tmp_path / ".claude/settings.json", json.dumps({"hooks": {"PreCompact": [
        {"hooks": [{"type": "command", "command": "echo mine"}]}]}}))
    register_hooks(tmp_path, capture=True)
    added, removed, _ = register_hooks(tmp_path, capture=False)
    assert added == [] and sorted(removed) == ["PreCompact", "SessionEnd"]
    hooks = settings(tmp_path)["hooks"]
    assert "SessionEnd" not in hooks
    assert [h["command"] for g in hooks["PreCompact"] for h in g["hooks"]] == ["echo mine"]
