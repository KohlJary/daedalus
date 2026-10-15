"""The Sources screen (edict 0012, docs/design/tui/sources.oph): health, last sync, items and mapping, with
no key that touches the network."""

import json
import subprocess
from datetime import datetime, timedelta, timezone

import pytest

from daedalus import config as cfg
from daedalus.sources import state as source_state
from daedalus.tui.screens.config import ConfigScreen
from daedalus.tui.screens.sources import SourcesScreen
from daedalus.tui.session import FakeBackend
from daedalus.tui.widgets import ClaudePane, ExplainCard, KeyBar

from tui_helpers import make_app, tui_project  # noqa: F401
from sources_helpers import offline, project  # noqa: F401

pytestmark = pytest.mark.asyncio


def seed(project_dir):
    when = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    source_state.record(project_dir, "github", health="ok", last_sync=when)
    source_state.record(project_dir, "jira", health="auth-failed", error="401 from jira", last_sync=None)
    index = {"version": 1, "items": [
        {"id": "github-7", "title": "Fix the widget", "origin": {"source": "github", "external_id": "7"}},
        {"id": "github-8", "title": "Ship it", "origin": {"source": "github", "external_id": "8"}},
        {"id": "local-1", "title": "Local idea"},
    ]}
    (project_dir / ".daedalus/roadmap/index.json").write_text(json.dumps(index))


def detail(screen) -> str:
    return str(screen.query_one("#sources-detail-body").render())


async def test_sources_show_health_items_and_mapping(tui_project):
    seed(tui_project)
    app = make_app(tui_project)
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.pause()
        await pilot.press("S")
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, SourcesScreen) and screen.query(KeyBar)
        names = [r["name"] for r in screen.sources]
        assert names[0] == "github" and "jira" in names
        olist = screen.query_one("#sources-list")
        lines = [str(olist.get_option_at_index(i).prompt) for i in range(olist.option_count)]
        assert lines[0].startswith("● github") and "synced 5m" in lines[0] and "2 items" in lines[0]
        jira = next(line for line in lines if "jira" in line)
        assert jira.startswith("⚠")  # a text tag, not colour alone
        text = detail(screen)
        assert "acme/widgets (from origin)" in text
        assert "Milestone → phase" in text and "Issue → roadmap item" in text
        assert "asks first" in text and "Auth: not set" in text
        await pilot.press("down")
        await pilot.pause()
        assert "jira" in detail(screen) and "plugin" in detail(screen).lower()
        await pilot.press("question_mark")
        await pilot.pause()
        assert isinstance(app.screen, ExplainCard)


async def test_no_key_syncs_and_send_offers_a_dry_run(tui_project, offline):
    backend = FakeBackend()
    app = make_app(tui_project, backend=backend)
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.pause()
        pane = app.query_one(ClaudePane)
        pane.start_session()
        app.open_screen("sources")
        await pilot.pause()
        screen = app.screen
        keys = {b[0] if isinstance(b, tuple) else b.key for b in screen.BINDINGS}
        assert "r" not in keys
        await pilot.press("r")
        await pilot.pause()
        assert offline["transport"].calls == []  # nothing reached for the tracker
        await pilot.press("s")
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        sent = backend.store[pane.session_name]["received"].decode()
        assert "daedalus source sync github --dry-run" in sent and not sent.endswith("\n")
    assert offline["transport"].calls == []


async def test_configure_opens_config_on_that_source(tui_project):
    app = make_app(tui_project)
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.pause()
        app.open_screen("sources")
        await pilot.pause()
        await pilot.press("c")
        await pilot.pause()
        assert isinstance(app.screen, ConfigScreen) and app.screen.group == "sources.github"
        assert all(r.group == "sources.github" for r in app.screen.shown_rows)


async def test_a_keyring_token_shows_as_set_and_never_as_itself(tui_project, offline):
    offline["keyring"]["github"] = "ghp_TOKENVALUE_hidden"
    app = make_app(tui_project)
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.pause()
        app.open_screen("sources")
        await pilot.pause()
        text = detail(app.screen)
        assert "stored in the system keyring ✓ set" in text
        assert "ghp_TOKENVALUE_hidden" not in app.export_screenshot() + text


async def test_with_no_source_the_screen_teaches(tmp_path, offline, monkeypatch):
    repo = tmp_path / "plain"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    monkeypatch.chdir(repo)
    app = make_app(repo)
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.pause()
        app.open_screen("sources")
        await pilot.pause()
        screen = app.screen
        assert screen.sources == []
        assert screen.query_one("#sources-empty").styles.display == "block"
        assert "daedalus source list" in str(screen.query_one("#sources-empty").render())


async def test_a_configured_source_appears(tui_project):
    assert cfg.set_project_value(tui_project, "sources.work.type", "ado")
    assert cfg.set_project_value(tui_project, "sources.work.organization", "acme")
    app = make_app(tui_project)
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.pause()
        app.open_screen("sources")
        await pilot.pause()
        work = next(r for r in app.screen.sources if r["name"] == "work")
        assert work["title"] == "Azure DevOps" and work["where"].startswith("acme/")
