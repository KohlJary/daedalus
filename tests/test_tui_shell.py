"""The TUI shell (edict 0012): layout, focus model, the Claude pane, Send to Claude, Explain cards."""

import pytest

from daedalus.tui.session import FakeBackend
from daedalus.tui.widgets import ClaudePane, KeyBar, NeedsYou

from tui_helpers import make_app, tui_project  # noqa: F401
from sources_helpers import offline, project  # noqa: F401

pytestmark = pytest.mark.asyncio


async def test_desktop_layout_shows_the_shell(tui_project):
    app = make_app(tui_project)
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.pause()
        for name in ("Header", "LastSession", "NeedsYou", "Gameplan", "Health", "ClaudePane", "KeyBar", "ActiveTab"):
            assert app.query(name), name
        assert not app.narrow
        assert "T-1" in str(app.query_one("#plan-body").render())
        assert app.query_one("#welcome").styles.display == "none"


async def test_narrow_layout_uses_tabs(tui_project):
    app = make_app(tui_project)
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        assert app.narrow and app.query_one("TabBar").styles.display == "block"
        await pilot.press("2")
        assert app.active_tab == "2" and app.query_one("#gameplan").styles.display == "block"
        assert app.query_one("#needs").styles.display == "none"


async def test_first_run_shows_welcome(project):
    app = make_app(project)
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.pause()
        assert app.state.first_run
        assert app.query_one("#welcome").styles.display == "block"
        assert app.query_one("#needs").styles.display == "none"


async def test_keys_reach_claude_and_only_the_escape_chord_comes_back(tui_project):
    backend = FakeBackend()
    app = make_app(tui_project, backend=backend)
    async with app.run_test(size=(140, 40)) as pilot:
        pane = app.query_one(ClaudePane)
        pane.start_session()
        await pilot.press("c")
        assert app.focused is pane and "every key goes to Claude" in str(app.query_one(KeyBar).render())
        await pilot.press("j", "k", "q", "question_mark")
        sent = backend.store[pane.session_name]["received"]
        assert sent == b"jkq?"
        assert app.is_running  # q went to Claude, not to quit
        await pilot.press("ctrl+right_square_bracket")
        assert isinstance(app.focused, NeedsYou)
        assert "every key goes to Claude" not in str(app.query_one(KeyBar).render())


async def test_send_to_claude_pastes_without_a_newline(tui_project):
    backend = FakeBackend()
    app = make_app(tui_project, backend=backend)
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.pause()
        pane = app.query_one(ClaudePane)
        pane.start_session()
        app.query_one(NeedsYou).focus()
        await pilot.press("s")
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        sent = backend.store[pane.session_name]["received"].decode()
        assert sent.startswith("Check pending proposal") and not sent.endswith("\n") and "\r" not in sent
        assert app.focused is pane


async def test_explain_card_on_a_panel(tui_project):
    app = make_app(tui_project)
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.pause()
        app.query_one("#gameplan").focus()
        await pilot.press("question_mark")
        await pilot.pause()
        text = " ".join(str(w.render()) for w in app.screen.query("Static"))
        assert "Gameplan" in text and "Lives in" in text and "CLI: daedalus gameplan show" in text
        await pilot.press("escape")


async def test_a_persistent_session_survives_quitting_and_relaunching(tui_project):
    store = {}
    first = make_app(tui_project, backend=FakeBackend(persistent=True, store=store))
    async with first.run_test(size=(140, 40)) as pilot:
        first.query_one(ClaudePane).start_session()
        await pilot.pause()
    second = make_app(tui_project, backend=FakeBackend(persistent=True, store=store))
    async with second.run_test(size=(140, 40)) as pilot:
        await pilot.pause()
        assert second.query_one(ClaudePane).session is not None  # attached on start


async def test_the_fallback_says_the_session_wont_outlive_the_tui(tui_project):
    app = make_app(tui_project, backend=FakeBackend(persistent=False))
    app.fallback_reason = "tmux isn't installed"
    async with app.run_test(size=(140, 40)) as pilot:
        pane = app.query_one(ClaudePane)
        pane.fallback_reason = app.fallback_reason
        pane.start_session()
        await pilot.pause()
        assert "this session ends when the TUI quits" in str(pane.render())
