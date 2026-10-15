"""The Edicts screen (edict 0012, edicts.oph @expanded): a read-only browser with status, where the gameplan
tracks each edict, the edict text and its dissents. There is no accept key."""

import pytest

from daedalus.cli import gameplan as gp
from daedalus.edicts import file_dissent
from daedalus.tui.widgets import KeyBar, SendToClaude

from tui_helpers import make_app, tui_project  # noqa: F401
from sources_helpers import offline, project  # noqa: F401

pytestmark = pytest.mark.asyncio


@pytest.fixture
def edict_project(tui_project):
    folder = tui_project / "docs/edicts"
    folder.mkdir(parents=True)
    (folder / "0001-first.md").write_text("# Edict 0001: First thing\nStatus: accepted\n\n## Intent\nBuild the first thing.\n")
    (folder / "0002-second.md").write_text("# Edict 0002: Second thing\nStatus: proposed\n\n## Intent\nMaybe later.\n")
    data = gp.load_gameplan(tui_project)
    data["activePhase"]["tasks"][0]["edict"] = "0001"
    gp.save_gameplan(tui_project, data)
    file_dissent(tui_project, "0002", "daedalus", "It's vague.", "Nothing is testable.", "Add criteria.")
    return tui_project


def _head(screen):
    return str(screen.query_one("#edict-head").render())


def _options(screen, selector):
    ol = screen.query_one(selector)
    return [str(ol.get_option_at_index(i).prompt) for i in range(ol.option_count)]


async def _open(app, pilot):
    await pilot.pause()
    await pilot.press("e")
    await pilot.pause()
    return app.screen


async def test_edicts_tab_status_tracking_text_and_dissents(edict_project):
    edict_files = {p: p.read_bytes() for p in (edict_project / "docs/edicts").rglob("*.md")}
    app = make_app(edict_project)
    async with app.run_test(size=(140, 40)) as pilot:
        screen = await _open(app, pilot)
        assert type(screen).__name__ == "EdictsScreen" and screen.query(KeyBar)  # ◆KeyBar
        assert "[Edicts]" in str(screen.query_one("#edicts-tabs").render())
        rows = _options(screen, "#edict-list")
        assert rows[0].startswith("0001 accepted") and "First thing" in rows[0]
        assert rows[1].startswith("0002 proposed") and "[1 dissent]" in rows[1]
        assert "0001 · accepted · task T-1 [in_progress]" in _head(screen)
        assert "Build the first thing." in screen.query_one("#edict-body").source
        await pilot.press("down")
        head = _head(screen)
        assert "0002 · proposed · not in the gameplan" in head and "dissents: 0002-daedalus [open]" in head

        await pilot.press("r")                         # read full: the list hides
        assert screen.has_class("-full")
        await pilot.press("escape")                    # first esc leaves full view
        assert not screen.has_class("-full") and app.screen is screen

        await pilot.press("s")
        await pilot.pause()
        assert isinstance(app.screen, SendToClaude) and "0002" in app.screen.prompt and "ready to build" in app.screen.prompt
        await pilot.press("escape")
        await pilot.pause()

        await pilot.press("a")                         # no accept key, nor any binding that accepts
        assert not any("accept" in str(b) for b in type(screen).BINDINGS)
        await pilot.press("question_mark")
        await pilot.pause()
        assert "Edict" in " ".join(str(w.render()) for w in app.screen.query("Static"))
        await pilot.press("escape", "escape")
        await pilot.pause()
        assert type(app.screen).__name__ != "EdictsScreen"
    assert {p: p.read_bytes() for p in (edict_project / "docs/edicts").rglob("*.md")} == edict_files


async def test_dissents_tab(edict_project):
    app = make_app(edict_project)
    async with app.run_test(size=(140, 40)) as pilot:
        screen = await _open(app, pilot)
        await pilot.press("d")
        assert "[Dissents]" in str(screen.query_one("#edicts-tabs").render())
        rows = _options(screen, "#dissent-list")
        assert rows == ["0002 open      0002-daedalus"]
        head = _head(screen)
        assert "0002-daedalus · open · on edict 0002 Second thing" in head and "by daedalus" in head
        assert "It's vague." in screen.query_one("#edict-body").source
        await pilot.press("s")
        await pilot.pause()
        assert isinstance(app.screen, SendToClaude) and "Resolving it is my call" in app.screen.prompt


async def test_empty_states_teach(tui_project):
    app = make_app(tui_project)
    async with app.run_test(size=(140, 40)) as pilot:
        screen = await _open(app, pilot)
        assert "No edicts yet." in _head(screen) and "docs/edicts" in screen.query_one("#edict-body").source
        await pilot.press("d")
        assert "No dissents." in _head(screen)
