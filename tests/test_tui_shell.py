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


async def test_the_header_names_the_branch_and_phase(tui_project):
    app = make_app(tui_project)
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.pause()
        text = str(app.query_one("Header").render())
        assert "p1 ▸ T-1" in text and "needs" in text


# ---------- Momus's review of the build (F1, F4-F8) ----------

async def test_no_inherited_key_reaches_past_the_claude_pane(tui_project):
    """F1: Textual's ctrl+q (priority), ctrl+c and the ctrl+p command palette must go to Claude."""
    backend = FakeBackend()
    app = make_app(tui_project, backend=backend)
    async with app.run_test(size=(140, 40)) as pilot:
        pane = app.query_one(ClaudePane)
        pane.start_session()
        await pilot.press("c")
        stack = len(app.screen_stack)
        await pilot.press("ctrl+p", "ctrl+q", "ctrl+c", "tab", "shift+tab", "ctrl+d")
        await pilot.pause()
        assert app.is_running and len(app.screen_stack) == stack and app.focused is pane
        assert backend.store[pane.session_name]["received"] == b"\x10\x11\x03\t\x1b[Z\x04"
    assert not [b for b in app._bindings if getattr(b, "priority", False)] if hasattr(app, "_bindings") else True


async def test_paste_is_bracketed_and_modified_enter_is_a_newline(tui_project):
    from textual import events

    backend = FakeBackend()
    app = make_app(tui_project, backend=backend)
    async with app.run_test(size=(140, 40)) as pilot:
        pane = app.query_one(ClaudePane)
        pane.start_session()
        await pilot.press("c")
        pane.post_message(events.Paste("line one\nline two"))
        await pilot.pause()
        await pilot.press("shift+enter", "alt+x", "ctrl+left", "f5")
        got = backend.store[pane.session_name]["received"]
        assert got.startswith(b"\x1b[200~line one\nline two\x1b[201~")
        assert got.endswith(b"\x1b\r\x1bx\x1b[1;5D\x1b[15~")


def test_session_names_differ_for_projects_with_the_same_folder_name(tmp_path):
    from daedalus.tui.session import session_name

    a, b = tmp_path / "x" / "app", tmp_path / "y" / "app"
    a.mkdir(parents=True), b.mkdir(parents=True)
    assert session_name(a) != session_name(b) and session_name(a).startswith("daedalus-app-")


async def test_a_dead_session_returns_to_no_session(tui_project):
    backend = FakeBackend()
    app = make_app(tui_project, backend=backend)
    async with app.run_test(size=(140, 40)) as pilot:
        pane = app.query_one(ClaudePane)
        pane.start_session()
        backend.store[pane.session_name]["alive"] = False
        for _ in range(30):
            await pilot.pause(0.05)
            if pane.session is None:
                break
        assert pane.session is None and "ended" in (pane.error or "")


def test_escape_chord_is_limited_to_safe_choices(offline):
    from sources_helpers import run

    assert run("config", "tui.escape", "j").exit_code == 1
    assert run("config", "tui.escape", "ctrl+\\").exit_code == 0


def test_the_watcher_sees_reflection_proposals_and_nested_refs(tui_project):
    import subprocess

    from daedalus.tui.app import watched_files

    subprocess.run(["git", "branch", "feat/nested"], cwd=tui_project, capture_output=True)
    files = {str(p) for p in watched_files(tui_project)}
    assert str(tui_project / ".daedalus/reflection/pending.json") in files
    assert any(f.endswith("refs/heads/feat/nested") for f in files)


async def test_resizing_away_from_the_pane_gives_focus_back(tui_project):
    app = make_app(tui_project)
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.press("c")
        await pilot.resize_terminal(60, 30)
        await pilot.pause()
        assert app.focused is not app.query_one(ClaudePane) or app.active_tab == "4"
        if app.focused is not app.query_one(ClaudePane):
            assert "every key goes to Claude" not in str(app.query_one(KeyBar).render())


async def test_an_unreadable_watched_folder_is_skipped_not_fatal(tui_project):
    import os
    import sys

    if sys.platform == "win32" or os.geteuid() == 0:
        return
    board = tui_project / ".daedalus" / "board"
    board.mkdir(exist_ok=True)
    board.chmod(0)
    try:
        app = make_app(tui_project, watch_interval=0.05)
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.pause(0.3)
            assert app.is_running
    finally:
        board.chmod(0o755)


async def test_a_wrong_shape_gameplan_shows_empty_not_a_crash(tui_project):
    (tui_project / ".daedalus/roadmap/gameplan.json").write_text("[]")
    app = make_app(tui_project)
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.pause()
        assert app.is_running and app.state.gameplan == {}
