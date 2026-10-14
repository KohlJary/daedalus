"""Tests for template conditionals and local slots (daedalus.templates.render), and how hydrate uses them."""

import json

import pytest
from click.testing import CliRunner

from daedalus import config as config_module
from daedalus.cli.main import main
from daedalus.config import DaedalusConfig
from daedalus.templates import injector
from daedalus.templates.injector import get_template_content, inject_claude_template
from daedalus.templates.render import TemplateError, extract_slots, fill_slots, render_conditionals

SETTINGS = {"git": {"authorship": "daedalus"}, "sections": {"squash": True, "versioning": False}}


@pytest.fixture(autouse=True)
def isolated_config(monkeypatch, tmp_path_factory):
    # No real global config, git identity or user settings
    monkeypatch.setattr(config_module, "get_config_file", lambda: tmp_path_factory.mktemp("cfg") / "config.json")
    monkeypatch.setattr(injector, "load_daedalus_config", lambda config_path=None: {})
    monkeypatch.setattr(injector, "load_config", lambda: DaedalusConfig())
    monkeypatch.setattr(injector, "get_daedalus_email", lambda config: "daedalus@example.com")


def slot(name, body=""):
    return f"<!-- DAEDALUS_LOCAL {name} -->\n{body}<!-- /DAEDALUS_LOCAL -->\n"


# --- conditionals ---------------------------------------------------------------------------------

def test_truthy_and_equality_conditions():
    text = (
        "a\n"
        "<!-- DAEDALUS_IF sections.squash -->\nsquash\n<!-- /DAEDALUS_IF -->\n"
        "<!-- DAEDALUS_IF sections.versioning -->\nversioning\n<!-- /DAEDALUS_IF -->\n"
        "<!-- DAEDALUS_IF git.authorship=daedalus -->\nas daedalus\n<!-- /DAEDALUS_IF -->\n"
        "<!-- DAEDALUS_IF git.authorship=user -->\nas user\n<!-- /DAEDALUS_IF -->\n"
        "b\n"
    )
    assert render_conditionals(text, SETTINGS) == "a\nsquash\nas daedalus\nb\n"


def test_unknown_setting_is_an_error_not_false():
    with pytest.raises(TemplateError, match="sections.sqaush"):
        render_conditionals("<!-- DAEDALUS_IF sections.sqaush -->\nx\n<!-- /DAEDALUS_IF -->\n", SETTINGS)


def test_nested_or_unbalanced_block_is_an_error():
    with pytest.raises(TemplateError):
        render_conditionals("<!-- DAEDALUS_IF sections.squash -->\nx\n", SETTINGS)


# --- slots ----------------------------------------------------------------------------------------

def test_slot_contents_carry_over_and_empty_slots_stay_empty():
    rendered = "top\n" + slot("breath") + "mid\n" + slot("lessons") + slot("end")
    filled, warnings = fill_slots(rendered, {"breath": "my exhale notes\n"})

    assert extract_slots(filled) == {"breath": "my exhale notes\n", "lessons": "", "end": ""}
    assert "top\n" in filled and "mid\n" in filled
    assert warnings == []


def test_removed_slot_moves_to_end_with_a_warning():
    filled, warnings = fill_slots(slot("breath") + slot("end"), {"oldname": "keep me\n", "end": "already here\n"})

    assert extract_slots(filled)["end"] == "already here\n<!-- from removed slot: oldname -->\nkeep me\n"
    assert len(warnings) == 1 and "oldname" in warnings[0]


def test_removed_empty_slot_is_dropped_quietly():
    filled, warnings = fill_slots(slot("end"), {"oldname": "  \n"})
    assert extract_slots(filled)["end"] == "" and warnings == []


def test_removed_slot_without_end_slot_is_an_error():
    with pytest.raises(TemplateError):
        fill_slots(slot("breath"), {"oldname": "keep me\n"})


# --- the bundled template -------------------------------------------------------------------------

def render_bundled(tmp_path, project_config=None):
    if project_config:
        (tmp_path / ".daedalus").mkdir()
        (tmp_path / ".daedalus" / "config.json").write_text(json.dumps(project_config), encoding="utf-8")
    assert inject_claude_template(str(tmp_path))
    return (tmp_path / "CLAUDE.md").read_bytes().decode("utf-8")


def test_bundled_template_defaults(tmp_path):
    text = render_bundled(tmp_path)

    assert "DAEDALUS_IF" not in text
    assert text.count('--author="Daedalus <daedalus@example.com>"') == 2  # rule + squash step
    assert "### Squash for Merge" in text and "### Versioning" in text
    assert set(extract_slots(text)) == {"identity", "breath", "working-with", "git", "lessons", "end"}
    assert "{{" not in text


def test_bundled_template_user_authorship_and_toggles(tmp_path):
    text = render_bundled(tmp_path, {"git": {"authorship": "user"}, "sections": {"squash": False, "versioning": False}})

    assert '--author="' not in text  # the rule itself says "never pass `--author`"
    assert "`- Daedalus` sign-off" in text
    assert "### Squash for Merge" not in text and "### Versioning" not in text
    assert "### Code Style" in text


def test_squash_step_follows_authorship(tmp_path):
    text = render_bundled(tmp_path, {"git": {"authorship": "user"}})
    assert "4. Commit: `git commit` with the combined message" in text


# --- hydrate with an existing CLAUDE.md -----------------------------------------------------------

def test_hydrate_keeps_slot_contents_and_line_endings(tmp_path):
    first = render_bundled(tmp_path)
    edited = first.replace(
        "<!-- DAEDALUS_LOCAL breath -->\n",
        "<!-- DAEDALUS_LOCAL breath -->\nIn this repo, exhaling means — commits pushed.\n",
    ).replace("\n", "\r\n")
    (tmp_path / "CLAUDE.md").write_bytes(edited.encode("utf-8"))

    assert inject_claude_template(str(tmp_path))

    data = (tmp_path / "CLAUDE.md").read_bytes()
    assert data.count(b"\n") == data.count(b"\r\n")
    assert extract_slots(data.decode("utf-8").replace("\r\n", "\n"))["breath"] == "In this repo, exhaling means — commits pushed.\n"


def test_unknown_setting_in_template_fails_with_reason(tmp_path):
    template = "<!-- DAEDALUS_BEGIN -->\n<!-- DAEDALUS_IF sections.nope -->\nx\n<!-- /DAEDALUS_IF -->\n<!-- DAEDALUS_END -->\n"
    warnings = []

    assert not inject_claude_template(str(tmp_path), template_content=template, warnings=warnings)
    assert any("sections.nope" in w for w in warnings)
    assert not (tmp_path / "CLAUDE.md").exists()


def test_project_config_ignores_unknown_keys(tmp_path):
    text = render_bundled(tmp_path, {"sections": {"squash": False, "bogus": True}, "user": {"name": "x"}})
    assert "### Squash for Merge" not in text


# --- CLI ------------------------------------------------------------------------------------------

def test_dry_run_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(main, ["hydrate", "--dry-run"])

    assert result.exit_code == 0, result.output
    assert "CLAUDE.md (after hydrate)" in result.output
    assert not (tmp_path / "CLAUDE.md").exists()
    assert not (tmp_path / ".claude").exists()


def test_config_project_set_and_show(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()

    assert runner.invoke(main, ["config", "--project", "git.authorship", "user"]).exit_code == 0
    assert runner.invoke(main, ["config", "--project", "sections.squash", "false"]).exit_code == 0
    bad = runner.invoke(main, ["config", "--project", "git.authorship", "nobody"])

    assert "invalid value" in bad.output
    saved = json.loads((tmp_path / ".daedalus" / "config.json").read_text(encoding="utf-8"))
    assert saved == {"git": {"authorship": "user"}, "sections": {"squash": False}}
    shown = json.loads(runner.invoke(main, ["config", "--project"]).output)
    assert shown == {
        "git": {"authorship": "user"},
        "sections": {"squash": False, "versioning": True},
        "edicts": {"enabled": False},
        "doctor": {"stale_commits": 10, "stale_task_days": 14},
        "hooks": {"session_start": True, "capture": False, "board": True},
    }
    assert runner.invoke(main, ["config", "--project", "doctor.stale_commits", "25"]).exit_code == 0
    assert json.loads(runner.invoke(main, ["config", "--project"]).output)["doctor"]["stale_commits"] == 25


def test_dropped_sections_leave_no_blank_line_runs(tmp_path):
    text = render_bundled(tmp_path, {"sections": {"squash": False, "versioning": False}})
    assert "\n\n\n" not in text


def test_bundled_template_is_ascii():
    # Projects edit CLAUDE.md in plain editors; non-ASCII here once turned into stray 0x97 bytes
    assert get_template_content().isascii()
