"""TUI plugins (edict 0012): a package outside Daedalus adds a NeedsYou kind, an Explain card and a menu
screen through the `daedalus.tui` entry point, and a broken plugin is skipped."""

import sys
import textwrap

import pytest

from daedalus.tui import cards, state
from daedalus.tui.plugin import TuiPlugin, detail_for, menu_entries
from daedalus.tui.screens.needs_you import NeedsDetail, NeedsYouScreen
from daedalus.tui.screens.plugins import PluginMenu
from daedalus.tui.widgets import ExplainCard, NeedsYou
from daedalus.tui.widgets.confirm import ConfirmModal

from tui_helpers import make_app, tui_project  # noqa: F401
from sources_helpers import offline, project  # noqa: F401

pytestmark = pytest.mark.asyncio

PLUGIN = '''
from textual.screen import Screen
from textual.widgets import Static

from daedalus.tui.cards import Card
from daedalus.tui.plugin import TuiPlugin
from daedalus.tui.state import NeedItem


CALLS = []


class JiraBoard(Screen):
    BINDINGS = [("escape", "app.pop_screen", "back")]

    def __init__(self, app):
        super().__init__()

    def compose(self):
        yield Static("Jira board", id="jira-board")


class FakeJiraTui(TuiPlugin):
    name = "Fake Jira"
    tag = "JR"

    def needs_you(self, project_dir):
        return [NeedItem("JR", "J-7", "J-7 Fix the login bug", None, {"status": "In review"}, ("send",))]

    def detail(self, item, project_dir):
        return f"{item.key} is {item.detail['status']} [/oops]"

    def actions(self, item):
        return [("t", "transition to Done")]

    def run_action(self, project_dir, item, key):
        CALLS.append((key, item.key))
        return f"{item.key} moved to Done"

    def explain_cards(self):
        return [Card("Jira issue", "A work item in Jira.", "your Jira site", "jira issue view <key>")]

    def screens(self):
        return [("Jira board", JiraBoard)]


class Broken(TuiPlugin):
    tag = "XX"

    def needs_you(self, project_dir):
        raise RuntimeError("boom")

    def explain_cards(self):
        raise RuntimeError("boom")

    def screens(self):
        raise RuntimeError("boom")
'''


@pytest.fixture
def plugin(tmp_path, monkeypatch, offline):
    site = tmp_path / "site"
    (site / "faketui").mkdir(parents=True)
    (site / "faketui" / "__init__.py").write_text(textwrap.dedent(PLUGIN))
    dist = site / "faketui-0.1.dist-info"
    dist.mkdir()
    (dist / "METADATA").write_text("Metadata-Version: 2.1\nName: faketui\nVersion: 0.1\n")
    (dist / "entry_points.txt").write_text("[daedalus.tui]\njira = faketui:FakeJiraTui\nbroken = faketui:Broken\n")
    monkeypatch.syspath_prepend(str(site))
    state.reset_plugins()
    cards._cards = None
    yield
    sys.modules.pop("faketui", None)
    state.reset_plugins()
    cards._cards = None


@pytest.fixture
def no_plugins(monkeypatch):
    state.reset_plugins()
    cards._cards = None
    monkeypatch.setattr(state, "_plugin_cache", [])
    yield
    state.reset_plugins()
    cards._cards = None


async def test_a_plugin_adds_a_needs_you_kind_a_card_and_a_screen(plugin, tui_project):
    loaded = state.plugins()
    assert sorted(type(p).__name__ for p in loaded) == ["Broken", "FakeJiraTui"]
    assert all(isinstance(p, TuiPlugin) for p in loaded)

    app = make_app(tui_project)
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.pause()
        item = next(it for it in app.state.needs if it.kind == "JR")
        assert detail_for(item, tui_project) == "J-7 is In review [/oops]"
        assert "JR J-7 Fix the login bug" in str(app.query_one("#needs-body").render())

        assert cards.card("Jira issue").cli == "jira issue view <key>"
        app.push_screen(ExplainCard("Jira issue"))
        await pilot.pause()
        assert "A work item in Jira." in str(app.screen.query_one("#card-body").render())
        await pilot.press("escape")

        app.query_one(NeedsYou).focus()
        await pilot.press("m")
        await pilot.pause()
        assert isinstance(app.screen, PluginMenu)
        assert [(name, label) for name, label, _ in menu_entries()] == [("Fake Jira", "Jira board")]
        await pilot.press("enter")
        await pilot.pause()
        assert app.screen.query("#jira-board")
        await pilot.press("escape")
        await pilot.press("escape")
        assert not isinstance(app.screen, PluginMenu)


async def test_the_plugin_menu_teaches_when_there_are_none(no_plugins, tui_project):
    app = make_app(tui_project)
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.pause()
        await pilot.press("m")
        await pilot.pause()
        assert isinstance(app.screen, PluginMenu)
        assert "No TUI plugins are installed" in str(app.screen.query_one("#plugins-empty").render())
        await pilot.press("question_mark")
        assert isinstance(app.screen, ExplainCard)
        await pilot.press("escape")
        await pilot.press("escape")
        assert not isinstance(app.screen, PluginMenu)


async def test_a_plugin_kind_drives_the_expanded_needs_you_view(plugin, tui_project):
    """The one protocol: detail() is the body, actions() fill the key row, and run_action runs only after
    the shared confirm gets a y."""
    state.plugins()  # loads the entry point
    calls = sys.modules["faketui"].CALLS
    app = make_app(tui_project)
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.pause()
        app.open_screen("needs")
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, NeedsYouScreen)
        while screen.kind_filter != "JR":
            await pilot.press("tab")
        await pilot.pause()
        assert screen.selected().kind == "JR"

        d = screen.query_one(NeedsDetail)
        assert "J-7 is In review [/oops]" in str(d.query_one("#detail-body").render())
        assert "t transition to Done" in str(d.query_one("#detail-keys").render())

        await pilot.press("a")  # not declared for this kind
        await pilot.pause()
        assert app.screen is screen and calls == []

        await pilot.press("t")
        await pilot.pause()
        assert isinstance(app.screen, ConfirmModal)
        assert "Fake Jira" in app.screen.question and "transition to Done" in app.screen.question
        await pilot.press("enter")  # enter never confirms
        await pilot.pause()
        assert isinstance(app.screen, ConfirmModal) and calls == []
        await pilot.press("n")  # declined: never runs
        await pilot.pause()
        assert app.screen is screen and calls == []

        await pilot.press("t")
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        assert app.screen is screen and calls == []

        await pilot.press("t")
        await pilot.pause()
        await pilot.press("y")
        await pilot.pause()
        assert calls == [("t", "J-7")]
        assert app.screen is screen
