"""Tests for CLAUDE.md template injection (daedalus.templates.injector)."""

import pytest

from daedalus import config as config_module
from daedalus.config import DaedalusConfig
from daedalus.templates import injector
from daedalus.templates.injector import DAEDALUS_BEGIN, DAEDALUS_END, inject_claude_template


def make_template(body: str) -> str:
    return f"# Project\n\n{DAEDALUS_BEGIN}\n{body}\n{DAEDALUS_END}\n"


@pytest.fixture(autouse=True)
def no_user_config(monkeypatch, tmp_path_factory):
    # Keep tests independent of the machine's Daedalus config and git identity
    monkeypatch.setattr(injector, "load_daedalus_config", lambda config_path=None: {})
    monkeypatch.setattr(injector, "load_config", lambda: DaedalusConfig())
    monkeypatch.setattr(injector, "get_daedalus_email", lambda config: "daedalus@example.com")
    monkeypatch.setattr(config_module, "get_config_file", lambda: tmp_path_factory.mktemp("cfg") / "config.json")


def test_new_file_is_utf8(tmp_path):
    # An em dash and an arrow: cp1252 would write the dash as 0x97 and fail on the arrow
    assert inject_claude_template(str(tmp_path), template_content=make_template("breath \u2014 cycle \u2192 done"))

    data = (tmp_path / "CLAUDE.md").read_bytes()
    assert "breath \u2014 cycle \u2192 done" in data.decode("utf-8")


def test_update_keeps_existing_utf8_content(tmp_path):
    claude_md = tmp_path / "CLAUDE.md"
    claude_md.write_bytes(make_template("old").encode("utf-8") + "\nNotes \u2014 mine\n".encode("utf-8"))

    assert inject_claude_template(str(tmp_path), template_content=make_template("new \u2014 section"))

    text = claude_md.read_bytes().decode("utf-8")
    assert "new \u2014 section" in text
    assert "Notes \u2014 mine" in text
    assert "old" not in text


def test_backslashes_in_template_are_literal(tmp_path):
    claude_md = tmp_path / "CLAUDE.md"
    claude_md.write_bytes(make_template("old").encode("utf-8"))
    body = r"path C:\new\tools, group \1, regex \d+"

    assert inject_claude_template(str(tmp_path), template_content=make_template(body))

    assert body in claude_md.read_bytes().decode("utf-8")


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_update_preserves_line_endings(tmp_path, newline):
    claude_md = tmp_path / "CLAUDE.md"
    original = make_template("old") + "\nKeep this\nand this\n"
    claude_md.write_bytes(original.replace("\n", newline).encode("utf-8"))

    assert inject_claude_template(str(tmp_path), template_content=make_template("new\nsection"))

    data = claude_md.read_bytes()
    if newline == "\n":
        assert b"\r\n" not in data
    else:
        assert data.count(b"\n") == data.count(b"\r\n")
    assert b"Keep this" in data and b"new" in data


def test_prepend_when_no_markers(tmp_path):
    claude_md = tmp_path / "CLAUDE.md"
    claude_md.write_bytes("Existing \u2014 notes\n".encode("utf-8"))

    assert inject_claude_template(str(tmp_path), template_content=make_template("section"))

    text = claude_md.read_bytes().decode("utf-8")
    assert text.startswith(DAEDALUS_BEGIN)
    assert "Existing \u2014 notes" in text
