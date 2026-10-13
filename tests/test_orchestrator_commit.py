"""Tests for the commit-authorship wiring in daedalus.ariadne.orchestrator (_commit_args).

Ariadne performs real git commits on the user's behalf; this must honor the same
git.authorship config that templates/injector.py renders into CLAUDE.md, instead of a
hardcoded author.
"""

from daedalus.ariadne import orchestrator
from daedalus.config import DaedalusConfig, GitConfig, UserConfig


def _with_authorship(monkeypatch, authorship: str, email: str = None):
    config = DaedalusConfig(git=GitConfig(authorship=authorship))
    if email:
        config.user = UserConfig(email=email)
    monkeypatch.setattr(orchestrator, "load_config", lambda: config)


def test_daedalus_authorship_uses_author_flag(monkeypatch):
    _with_authorship(monkeypatch, "daedalus", email="daedalus@example.com")

    args = orchestrator._commit_args("Fix the thing")

    assert args[:2] == ["git", "commit"]
    assert "--author=Daedalus <daedalus@example.com>" in args
    assert args[-1] == "Fix the thing"


def test_user_authorship_has_no_author_flag_and_signs_off(monkeypatch):
    _with_authorship(monkeypatch, "user")

    args = orchestrator._commit_args("Fix the thing")

    assert not any(a.startswith("--author=") for a in args)
    assert args[:2] == ["git", "commit"]
    message = args[-1]
    assert message.startswith("Fix the thing")
    assert message.rstrip().endswith("- Daedalus")


def test_user_authorship_preserves_original_message_body(monkeypatch):
    _with_authorship(monkeypatch, "user")

    args = orchestrator._commit_args("Title\n\nBody line one\nBody line two")

    message = args[-1]
    assert "Title" in message
    assert "Body line one" in message
    assert message.count("- Daedalus") == 1
