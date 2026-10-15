"""The Config screen and ◆EditSetting (edict 0012, docs/design/tui/config.oph).

Edits write at the chosen layer through the same functions as `daedalus config`, and round-trip
through it. A secret can't be read from the TUI.
"""

import json

import pytest

from daedalus import config as cfg
from daedalus.tui.screens.config import ConfigScreen, EditSetting, SettingCard, load_rows, write_setting
from daedalus.tui.widgets import KeyBar

from tui_helpers import make_app, tui_project  # noqa: F401
from sources_helpers import offline, project, run  # noqa: F401

pytestmark = pytest.mark.asyncio

TOKEN = "ghp_SECRETtoken_do_not_show_1234"


def everything_shown(app) -> str:
    """All text on screen, plus every option list's entries (including ones scrolled out of view)."""
    parts = [app.export_screenshot()]
    for screen in app.screen_stack:
        for olist in screen.query("OptionList"):
            parts += [str(olist.get_option_at_index(i).prompt) for i in range(olist.option_count)]
        for w in screen.query("Static, Input"):
            try:
                parts.append(str(w.render()))
            except Exception:
                pass
    return "\n".join(parts)


async def open_config(app, pilot, group=None):
    app.push_screen(ConfigScreen(app, group=group))
    await pilot.pause()
    return app.screen


async def pick(screen, pilot, key):
    """Highlight `key` in the keys column and open EditSetting on it."""
    screen.group = key.rsplit(".", 1)[0]
    screen.refresh_state()
    keys = screen.query_one("#config-keys")
    keys.highlighted = [r.setting.key for r in screen.shown_rows].index(key)
    keys.focus()
    await pilot.pause()
    screen.action_edit()
    await pilot.pause()
    return screen.app.screen


async def test_browse_shows_every_setting_with_its_layer(tui_project):
    cfg.set_project_value(tui_project, "doctor.stale_task_days", "5")
    app = make_app(tui_project)
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.pause()
        await pilot.press("comma")
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ConfigScreen)
        assert screen.query(KeyBar)
        from daedalus import config_schema

        shown = {r.setting.key for g in screen.groups for r in screen.rows[g]}
        assert set(config_schema.core_settings()) <= shown
        assert set(config_schema.source_settings("github")) <= shown  # active from the GitHub origin
        row = next(r for r in screen.rows["doctor"] if r.name == "stale_task_days")
        assert row.layer == "P" and row.value == 5
        screen.group = "doctor"
        screen.refresh_state()
        await pilot.pause()
        line = next(str(screen.query_one("#config-keys").get_option_at_index(i).prompt)
                    for i in range(len(screen.shown_rows)) if screen.shown_rows[i].name == "stale_task_days")
        assert "5" in line and line.rstrip().endswith("P")


async def test_question_mark_on_a_setting_shows_its_description(tui_project):
    app = make_app(tui_project)
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.pause()
        screen = await open_config(app, pilot, group="tui")
        keys = screen.query_one("#config-keys")
        keys.highlighted = [r.setting.key for r in screen.shown_rows].index("tui.escape")
        keys.focus()
        await pilot.press("question_mark")
        await pilot.pause()
        assert isinstance(app.screen, SettingCard)
        text = everything_shown(app)
        assert "returns focus from the Claude pane" in text and "daedalus config tui.escape" in text


async def test_edits_round_trip_through_daedalus_config(tui_project):
    app = make_app(tui_project)
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.pause()
        screen = await open_config(app, pilot)
        # A choice, saved for the user (tab switches the layer from project to user)
        modal = await pick(screen, pilot, "git.authorship")
        assert isinstance(modal, EditSetting) and modal.save_layer == "project"
        await pilot.press("tab")
        assert modal.save_layer == "user"
        modal.query_one("#edit-choices").highlighted = modal.choices.index("user")
        await pilot.press("enter")
        await pilot.pause()
        assert app.screen is screen
        # A number, saved for the project
        modal = await pick(screen, pilot, "doctor.stale_task_days")
        modal.query_one("#edit-input").value = "9"
        await pilot.press("enter")
        await pilot.pause()
        # A bool toggles
        modal = await pick(screen, pilot, "hooks.board")
        before = modal.query_one("#edit-choices").highlighted
        await pilot.press("space")
        assert modal.query_one("#edit-choices").highlighted == 1 - before
        await pilot.press("enter")
        await pilot.pause()
        row = next(r for r in screen.rows["git"] if r.name == "authorship")
        assert row.layer == "U" and row.value == "user"
    assert run("config", "git.authorship").output.strip() == "user"
    assert run("config", "--project", "doctor.stale_task_days").output.strip() == "9"
    assert run("config", "--project", "hooks.board").output.strip() == "False"
    assert run("config", "doctor.stale_task_days").output.strip() != "9"  # the project layer only
    assert "git" not in cfg.load_project_overrides(tui_project)  # the user layer only


async def test_a_source_setting_round_trips_at_both_layers(tui_project):
    assert write_setting(tui_project, "sources.github.on_conflict", "local", "project") is None
    assert write_setting(tui_project, "sources.github.assignee", "someone", "user") is None
    assert run("config", "--project", "sources.github.on_conflict").output.strip() == "local"
    assert run("config", "sources.github.assignee").output.strip() == "someone"


async def test_invalid_values_show_the_refusal(tui_project):
    app = make_app(tui_project)
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.pause()
        screen = await open_config(app, pilot)
        modal = await pick(screen, pilot, "doctor.stale_task_days")
        modal.query_one("#edit-input").value = "soon"
        await pilot.press("enter")
        await pilot.pause()
        assert app.screen is modal
        assert "whole number" in str(modal.query_one("#edit-error").render())
        await pilot.press("escape")
        await pilot.pause()
        # setting_refusal: the local runner needs machine.employer false first
        modal = await pick(screen, pilot, "reflection.runner")
        await pilot.press("tab")  # user
        modal.query_one("#edit-choices").highlighted = modal.choices.index("local")
        await pilot.press("enter")
        await pilot.pause()
        assert app.screen is modal and "machine.employer false" in str(modal.query_one("#edit-error").render())
    assert run("config", "reflection.runner").output.strip() == "inhale"
    assert run("config", "--project", "doctor.stale_task_days").output.strip() != "soon"


async def test_a_secret_cannot_be_read_from_the_tui(tui_project, offline, monkeypatch):
    from daedalus.sources.github import GitHubSource

    offline["keyring"]["github"] = TOKEN
    # A plugin setting marked secret, with a value someone left in the config file by hand
    monkeypatch.setattr(GitHubSource, "config_schema", GitHubSource.config_schema + [
        {"key": "app_key", "type": "str", "default": None, "description": "An app key.", "secret": True}])
    home = cfg.get_config_file()
    home.parent.mkdir(parents=True, exist_ok=True)
    home.write_text(json.dumps({"sources": {"github": {"app_key": TOKEN + "_file"}}}))
    app = make_app(tui_project)
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.pause()
        screen = await open_config(app, pilot, group="sources.github")
        await pilot.pause()
        text = everything_shown(app)
        assert TOKEN not in text
        assert "keyring ✓" in text
        for key in ("sources.github.credentials", "sources.github.app_key"):
            modal = await pick(screen, pilot, key)
            assert isinstance(modal, EditSetting) and not modal.query("Input") and not modal.query("OptionList")
            text = everything_shown(app)
            assert TOKEN not in text and "stored in the system keyring" in text
            await pilot.press("escape")
            await pilot.pause()
        for row in screen.rows["sources.github"]:
            if row.secret:
                assert row.value is None
    # Nor can one be written to a config file
    before = home.read_text()
    assert "never written to a config file" in write_setting(tui_project, "sources.github.credentials", TOKEN, "user")
    assert "never written" in write_setting(tui_project, "sources.github.app_key", "x", "project")
    assert home.read_text() == before
    assert not cfg.get_project_config_file(tui_project).exists() or \
        TOKEN not in cfg.get_project_config_file(tui_project).read_text()


async def test_no_keyring_token_says_not_set(tui_project):
    groups, rows, _ = load_rows(tui_project)
    cred = next(r for r in rows["sources.github"] if r.name == "credentials")
    assert cred.secret_status == "not set"
