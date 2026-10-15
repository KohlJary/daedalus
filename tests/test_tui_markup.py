"""File text is never Rich markup (Momus F3, edict 0012 build). A closing-tag lookalike like `[/oops]` or an
unclosed `[bold` in any file the TUI reads must render literally, on the shell and on every screen, and
never raise MarkupError (which would brick the TUI at launch)."""

import importlib
import subprocess

import pytest

from daedalus import board
from daedalus import config as cfg
from daedalus.cli import gameplan as gp
from daedalus.edicts import file_dissent
from daedalus.tui.widgets import SendToClaude

from tui_helpers import make_app, tui_project  # noqa: F401
from sources_helpers import offline, project  # noqa: F401

pytestmark = pytest.mark.asyncio

BAD = "bad [/oops] and [bold unclosed"


def _git(p, *args):
    subprocess.run(["git", "-c", "user.email=t@e", "-c", "user.name=T", *args], cwd=p, capture_output=True,
                   check=True)


@pytest.fixture
def poisoned(tui_project, tmp_path, monkeypatch):
    p = tui_project
    # reflection models and the global config live under tmp, never the real config dir
    root = tmp_path / "models-root"
    root.mkdir()
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    monkeypatch.setattr("daedalus.config.get_config_dir", lambda: root)
    paths = importlib.import_module("daedalus.reflection.paths")
    models = importlib.import_module("daedalus.reflection.models")
    monkeypatch.setattr(paths, "get_config_dir", lambda: root)
    assert models.history_path().is_relative_to(root)

    # story files
    d = p / ".daedalus"
    (d / "session-summaries.md").write_text(f"# Session Summaries\n\n## 2026-10-15: {BAD}\nBody {BAD}.\n")
    (d / "decisions.md").write_text(f"# Decisions\n\n## 2026-10-15: {BAD}\nWhy: {BAD}\n")
    (p / "docs").mkdir(exist_ok=True)
    (p / "docs/status.md").write_text(f"# Status\n\n{BAD}\n")

    # gameplan: phase and task titles, and a pending proposal
    data = gp.load_gameplan(p)
    gp.add_phase(data, "p2", f"Phase {BAD}")
    data["activePhase"]["goal"] = f"Goal {BAD}"
    data["activePhase"]["tasks"][0]["title"] = f"Task {BAD}"
    gp.save_gameplan(p, data)
    gp.save_pending(p, [{"id": "P1", "task": "T-1", "status": "done", "resolution": f"res {BAD}",
                         "created": "2026-10-14"}])

    # an edict (proposed, so it waits on the owner) and a dissent
    folder = p / "docs/edicts"
    folder.mkdir(parents=True)
    (folder / "0001-oops.md").write_text(f"# Edict 0001: Fix {BAD}\nStatus: proposed\n\n## Intent\n{BAD}\n")
    file_dissent(p, "0001", "daedalus", f"Objection {BAD}", f"Why {BAD}", f"Instead {BAD}")

    # the board
    assert cfg.set_project_value(p, "board.remote", "none")
    board.post(p, board.draft(p, "kannon", f"Post {BAD}", title=f"Thread {BAD}", topic="general",
                              to=("default",)), "kannon")

    # a reflection report and a model observation
    reports = paths.reports_dir(p)
    reports.mkdir(parents=True, exist_ok=True)
    (reports / "weekly-2026-W41.md").write_text(f"# Reflection: weekly 2026-W41\n\n## Findings\n\n- {BAD}\n")
    models.apply_change("user", {"op": "add", "entry": {"observation": f"obs {BAD}", "confidence": 0.9}}, by="user")

    # a branch ahead of main whose commit subject carries it (git refuses `[` in a branch name)
    subprocess.run(["git", "branch", "-M", "main"], cwd=p, capture_output=True)
    _git(p, "add", "-A")
    _git(p, "commit", "-qm", "poison")
    _git(p, "checkout", "-qb", "feat/oops]")
    (p / "x.txt").write_text("x")
    _git(p, "add", "x.txt")
    _git(p, "commit", "-qm", f"Subject {BAD}")
    return p


def _text(screen) -> str:
    parts = []
    for w in screen.query("Static"):
        parts.append(str(w.render()))
    for ol in screen.query("OptionList"):
        parts += [str(ol.get_option_at_index(i).prompt) for i in range(ol.option_count)]
    for md in screen.query("Markdown"):
        parts.append(getattr(md, "source", "") or "")
    return "\n".join(parts)


async def _walk(pilot, keys):
    for k in keys:
        await pilot.press(k)
        await pilot.pause()


async def test_markup_lookalikes_in_files_render_literally_everywhere(poisoned):
    app = make_app(poisoned)
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.pause()
        shell = app.screen
        assert "[/oops]" in str(app.query_one("LastSession").render())
        assert "[/oops]" in _text(shell)  # NeedsYou and Gameplan panels carry it too

        seen = {}
        # each screen through its shell key, then its own tabs and selection keys
        for key, inner in [("1", ["j"] * 8 + ["r", "d", "r"]),
                           ("2", ["right", "down", "w", "m", "p"]),
                           ("3", ["down"]),
                           ("5", ["1", "2", "down", "3", "4", "5", "6"]),
                           ("e", ["r", "d", "r"]),
                           ("b", ["down", "up"]),
                           ("comma", ["down", "right", "down"]),
                           ("R", ["1", "2", "3", "4", "5"]),
                           ("S", ["down"]),
                           ("m", [])]:
            await _walk(pilot, [key])
            screen = app.screen
            assert screen is not shell, key
            seen[key] = _text(screen)
            for k in inner:
                await _walk(pilot, [k])
                seen[key] += "\n" + _text(app.screen)
            await _walk(pilot, ["question_mark"])
            await _walk(pilot, ["escape"])
            while app.screen is not shell:
                await _walk(pilot, ["escape"])

        for key in ("1", "2", "5", "e", "b", "R"):
            assert "[/oops]" in seen[key] and "[bold unclosed" in seen[key], key
        for key, literal in [("1", f"Subject {BAD}"), ("1", f"Thread {BAD}"), ("1", f"res {BAD}"),
                             ("1", f"Objection {BAD}"), ("2", f"Task {BAD}"), ("2", f"Phase {BAD}"),
                             ("5", f"2026-10-15: {BAD}"), ("e", f"Fix {BAD}"), ("b", f"Post {BAD}"),
                             ("R", f"obs {BAD}"), ("R", "weekly 2026-W41")]:
            assert literal in seen[key], (key, literal)

        app.ask_to_send("ED Fix the [/api] path", "x [/y]")
        await pilot.pause()
        assert isinstance(app.screen, SendToClaude)
        assert "ED Fix the [/api] path" in _text(app.screen)
        await _walk(pilot, ["escape"])
