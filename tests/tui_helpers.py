"""Shared setup for the TUI tests (edict 0012): sockets off, gh stubbed, keyring a dict, a fake session
backend, and a small project with something in every panel."""

from __future__ import annotations

import json
import subprocess

import pytest

from daedalus.cli import gameplan as gp
from daedalus.tui.session import FakeBackend

from sources_helpers import offline, project  # noqa: F401  (offline: sockets, tokens, keyring, gh)


@pytest.fixture
def tui_project(project):
    data = gp.load_gameplan(project)
    gp.add_phase(data, "p1", "First phase")
    gp.activate_phase(data, "p1")
    gp.add_task(data, "T-1", "Build the shell")
    gp.add_task(data, "T-2", "Write the tests")
    data["activePhase"]["tasks"][0]["status"] = "in_progress"
    gp.save_gameplan(project, data)
    gp.save_pending(project, [{"id": "P1", "task": "T-1", "status": "done", "resolution": "shipped", "created": "2026-10-14"}])
    (project / ".daedalus/session-summaries.md").write_text("# Session Summaries\n\n## 2026-10-14: Built the core\nDone.\n")
    subprocess.run(["git", "add", "-A"], cwd=project, capture_output=True)
    subprocess.run(["git", "-c", "user.email=t@e", "-c", "user.name=T", "commit", "-qm", "init"], cwd=project,
                   capture_output=True)
    return project


SETTINGS = {"prs": "local", "escape": "ctrl+]", "backend": "auto"}


def make_app(project_dir, backend=None, **kw):
    from daedalus.tui.app import DaedalusShell

    return DaedalusShell(project_dir, backend=backend or FakeBackend(), settings=dict(SETTINGS),
                         claude_command=["claude"], **kw)
