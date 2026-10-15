"""The Story screen (edict 0012, docs/design/tui/story.oph): read-only narrative, newest sessions first."""

import pytest

from daedalus.tui.screens.story import StoryScreen, entries, newest_first, task_ids
from daedalus.tui.session import FakeBackend
from daedalus.tui.widgets import ClaudePane, ExplainCard, KeyBar

from tui_helpers import make_app, tui_project  # noqa: F401
from sources_helpers import offline, project  # noqa: F401

pytestmark = pytest.mark.asyncio

SESSIONS = """# Session Summaries

## 2025-12-19 - Initial setup
Early days.

## 2026-10-14: Built the core
Done: T-1 and T-2.

## 2026-10-13: Released 0.2.0
Shipped.
"""


def _text(screen) -> str:
    parts = []
    for w in screen.query("Static, Markdown, MarkdownBlock, OptionList"):
        try:
            parts.append(str(w.render()))
        except Exception:
            continue
    return "\n".join(parts)


def _md(screen, wid) -> str:
    return screen.query_one(f"#{wid}").source


async def test_entries_are_sorted_newest_first():
    found = newest_first(entries(SESSIONS))
    assert [e.date for e in found] == ["2026-10-14", "2026-10-13", "2025-12-19"]
    assert task_ids(found[0]) == ["T-1", "T-2"]


async def test_story_opens_on_now_and_lists_sessions_newest_first(tui_project):
    (tui_project / "docs").mkdir(exist_ok=True)
    (tui_project / "docs/status.md").write_text("# Status\n\nThe core is built.\n")
    (tui_project / ".daedalus/session-summaries.md").write_text(SESSIONS)
    (tui_project / ".daedalus/decisions.md").write_text("# Decisions\n\n## File-based bus (Dec 2025)\nBecause.\n")
    app = make_app(tui_project)
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.pause()
        await pilot.press("w")
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, StoryScreen)
        assert screen.query(KeyBar)  # the diagram's ◆ components
        assert "The core is built." in _md(screen, "story-doc-body")
        assert "docs/status.md" in str(screen.query_one("#story-updated").render())
        await pilot.press("right")
        await pilot.pause()
        assert screen.tab == "sessions"
        assert [e.date for e in screen.items] == ["2026-10-14", "2026-10-13", "2025-12-19"]
        assert "Built the core" in _md(screen, "story-detail-body")
        await pilot.press("down")
        await pilot.pause()
        assert "Released 0.2.0" in _md(screen, "story-detail-body")
        await pilot.press("3")
        await pilot.pause()
        assert screen.tab == "decisions" and "Because." in _md(screen, "story-detail-body")
        await pilot.press("question_mark")
        await pilot.pause()
        assert isinstance(app.screen, ExplainCard)
        assert "Story" in _text(app.screen)
        await pilot.press("escape")
        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, StoryScreen)


async def test_missing_files_teach(tui_project):
    (tui_project / ".daedalus/session-summaries.md").unlink()
    app = make_app(tui_project)
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.pause()
        app.open_screen("story")
        await pilot.pause()
        screen = app.screen
        assert "/exhale" in _md(screen, "story-doc-body")  # no docs/status.md
        for key, phrase in (("sessions", "session-summaries.md"), ("decisions", "decisions.md"),
                            ("lessons", "lessons.md"), ("warnings", "warnings.md")):
            screen.action_show(key)
            await pilot.pause()
            assert phrase in _md(screen, "story-detail-body"), key
        screen.action_show("map")
        await pilot.pause()
        assert "project-map.md" in _md(screen, "story-doc-body")


async def test_refresh_picks_up_a_new_entry(tui_project):
    app = make_app(tui_project)
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.pause()
        app.open_screen("story")
        await pilot.pause()
        screen = app.screen
        screen.action_show("sessions")
        (tui_project / ".daedalus/session-summaries.md").write_text(SESSIONS)
        app.reload()
        await pilot.pause()
        assert len(screen.items) == 3


async def test_send_to_claude_from_a_session_entry(tui_project):
    backend = FakeBackend()
    app = make_app(tui_project, backend=backend)
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.pause()
        pane = app.query_one(ClaudePane)
        pane.start_session()
        app.open_screen("story")
        await pilot.pause()
        app.screen.action_show("sessions")
        await pilot.pause()
        await pilot.press("s")
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        sent = backend.store[pane.session_name]["received"].decode()
        assert "Built the core" in sent and not sent.endswith("\n")
