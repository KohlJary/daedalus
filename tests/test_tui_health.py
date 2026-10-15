"""The Health screen (edict 0012, health.oph @expanded): findings and hints with their explanations, and
the doctor-fix allowlist: only hydrate and init run, only after a confirm modal, and nothing else has a run
action."""

import json

import pytest

from daedalus.board import POST_PERMISSION
from daedalus.tui.screens.health import FIX_FOR, RUNNABLE, ConfirmModal, Entry, entries, run_fix
from daedalus.tui.session import FakeBackend
from daedalus.tui.widgets import ClaudePane, KeyBar, SendToClaude

from tui_helpers import make_app, tui_project  # noqa: F401
from sources_helpers import offline, project  # noqa: F401

pytestmark = pytest.mark.asyncio


@pytest.fixture
def drifting(tui_project):
    (tui_project / ".daedalus/board").mkdir()             # uses the board, but no ask rule: hydrate fixes it
    (tui_project / "docs/edicts").mkdir(parents=True)     # an accepted edict nothing references: no run action
    (tui_project / "docs/edicts/0001-first.md").write_text("# Edict 0001: First\nStatus: accepted\n\nBody.\n")
    return tui_project


def _ask_rules(project_dir):
    path = project_dir / ".claude/settings.json"
    return json.loads(path.read_text()).get("permissions", {}).get("ask", []) if path.exists() else []


def _select(screen, name):
    ol = screen.query_one("#findings")
    ol.highlighted = next(i for i, e in enumerate(screen.entries) if e.name == name)


async def _open(app, pilot):
    await pilot.pause()
    app.open_screen("health")
    await pilot.pause()
    return app.screen


async def test_findings_are_listed_and_explained(drifting):
    app = make_app(drifting)
    async with app.run_test(size=(140, 40)) as pilot:
        screen = await _open(app, pilot)
        assert type(screen).__name__ == "HealthScreen" and screen.query(KeyBar)  # ◆KeyBar
        names = [e.name for e in screen.entries]
        assert "board-ask-rule-missing" in names and "edict-not-in-gameplan" in names
        assert "⚠" in str(screen.query_one("#health-title").render())
        _select(screen, "board-ask-rule-missing")
        await pilot.pause()
        detail = str(screen.query_one("#health-detail").render())
        assert "no permissions ask rule makes `daedalus board post`" in detail
        assert "Suggested fix: daedalus hydrate" in detail
        assert "f run fix (asks first)" in str(screen.query_one("#health-keys").render())
        await pilot.press("question_mark")
        await pilot.pause()
        assert "Doctor" in " ".join(str(w.render()) for w in app.screen.query("Static"))
        await pilot.press("escape", "escape")
        await pilot.pause()
        assert type(app.screen).__name__ != "HealthScreen"


async def test_hydrate_runs_only_after_confirming(drifting):
    app = make_app(drifting)
    async with app.run_test(size=(140, 40)) as pilot:
        screen = await _open(app, pilot)
        _select(screen, "board-ask-rule-missing")
        await pilot.press("f")
        await pilot.pause()
        assert isinstance(app.screen, ConfirmModal)
        assert POST_PERMISSION not in _ask_rules(drifting)       # nothing yet: it's asking
        await pilot.press("n")                                   # cancel
        await pilot.pause()
        await app.workers.wait_for_complete()
        assert app.screen is screen and POST_PERMISSION not in _ask_rules(drifting)

        await pilot.press("f")
        await pilot.pause()
        await pilot.press("y")
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert POST_PERMISSION in _ask_rules(drifting)           # the real library ran
        assert "board-ask-rule-missing" not in [e.name for e in screen.entries]   # rechecked


async def test_a_finding_off_the_allowlist_has_no_run_action(drifting):
    app = make_app(drifting)
    async with app.run_test(size=(140, 40)) as pilot:
        screen = await _open(app, pilot)
        _select(screen, "edict-not-in-gameplan")
        await pilot.pause()
        assert "f run fix" not in str(screen.query_one("#health-keys").render())
        assert "s hands it to Claude" in str(screen.query_one("#health-detail").render())
        await pilot.press("f")
        await pilot.pause()
        assert app.screen is screen                              # no confirm modal, nothing ran
        await pilot.press("s")
        await pilot.pause()
        assert isinstance(app.screen, SendToClaude) and "edict-not-in-gameplan" in app.screen.prompt
    assert not (drifting / ".claude").exists() and not (drifting / "CLAUDE.md").exists()   # hydrate never ran


async def test_send_pastes_into_claude_from_the_screen(drifting):
    backend = FakeBackend()
    app = make_app(drifting, backend=backend)
    async with app.run_test(size=(140, 40)) as pilot:
        pane = app.query_one(ClaudePane)
        pane.start_session()
        await _open(app, pilot)
        await pilot.press("s")
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        sent = backend.store[pane.session_name]["received"].decode()
        assert sent.startswith("`daedalus doctor` reports") and not sent.endswith("\n")
        assert type(app.screen).__name__ != "HealthScreen" and app.focused is pane   # Claude is shown


async def test_in_sync_says_so(tui_project):
    app = make_app(tui_project)
    async with app.run_test(size=(140, 40)) as pilot:
        screen = await _open(app, pilot)
        if not screen.entries:
            assert "In sync" in str(screen.query_one("#health-detail").render())


async def test_the_allowlist_is_hydrate_and_init_only(tmp_path):
    assert set(RUNNABLE) == {"daedalus hydrate", "daedalus init"}
    assert set(FIX_FOR.values()) <= set(RUNNABLE)
    with pytest.raises(KeyError):
        run_fix("daedalus doctor", tmp_path)
    assert Entry("source-drift", "closed upstream. Run `daedalus roadmap show x`.").fix is None
    assert Entry("source-drift", "Run `daedalus roadmap show x`.").fix_text == "daedalus roadmap show x"
    hint = entries([], ["No gameplan in this project. `daedalus init` creates one."])[0]
    assert hint.hint and hint.fix == "daedalus init"
