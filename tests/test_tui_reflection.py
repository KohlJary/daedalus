"""The Reflection screen (edict 0012's reflection amendment): five tabs, and the owner's own writes, each
through the same library function as its `daedalus reflect` command."""

import importlib
import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from daedalus.cli.main import main
from daedalus.tui.screens.reflection import ConfirmModal, EditEntry, ExportLog, ReflectionScreen
from daedalus.tui.widgets import ExplainCard, KeyBar

from reflection_helpers import install_fixtures
from tui_helpers import make_app, tui_project  # noqa: F401
from sources_helpers import offline, project  # noqa: F401

pytestmark = pytest.mark.asyncio


def _mod(name):
    """The reflection module as it is now. Another test re-imports daedalus.reflection.*, so a module object
    bound at import time here could be a stale copy whose models_dir still points at the real config dir."""
    return importlib.import_module(f"daedalus.reflection.{name}")


class _Models:
    def __getattr__(self, name):
        return getattr(_mod("models"), name)


m = _Models()


def use_models_root(monkeypatch, root: Path) -> Path:
    """Point the models (and the global config) at `root`: daedalus.config.get_config_dir, and the copy
    reflection.paths imported by name. Fails loudly if the models would land anywhere else."""
    root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("daedalus.config.get_config_dir", lambda: root)
    monkeypatch.setattr(_mod("paths"), "get_config_dir", lambda: root)
    assert _mod("models").history_path().is_relative_to(root)
    return root


@pytest.fixture
def refl(tui_project, tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    use_models_root(monkeypatch, tmp_path / "models-root")
    return tui_project


async def open_reflection(app, pilot):
    await pilot.pause()
    await pilot.press("R")
    await pilot.pause()
    assert isinstance(app.screen, ReflectionScreen)
    return app.screen


def detail(screen) -> str:
    return str(screen.query_one("#refl-detail").render())


def add_user(observation="prefers terse status updates"):
    return m.apply_change("user", {"op": "add", "entry": {"observation": observation, "confidence": 0.9}}, by="user")


async def test_screen_mounts_every_tab_and_explains_each(refl):
    app = make_app(refl)
    async with app.run_test(size=(140, 40)) as pilot:
        screen = await open_reflection(app, pilot)
        assert screen.query(KeyBar) and screen.query("#refl-list") and screen.query("#refl-tabs")
        assert "Nothing due" in detail(screen)
        for key, tab, text in (("2", "reports", "No reports yet"), ("3", "user", "user model is empty"),
                               ("4", "self", "self model is empty"), ("5", "experiment", "Model summary at inhale")):
            await pilot.press(key)
            assert screen.tab == tab and text in detail(screen), tab
            await pilot.press("question_mark")
            assert isinstance(app.screen, ExplainCard)
            await pilot.press("escape")
        await pilot.press("right")
        assert screen.tab == "due"
        await pilot.press("escape")
        assert not isinstance(app.screen, ReflectionScreen)


async def test_no_apply_key_stances_are_applied_one_at_a_time_elsewhere():
    actions = {b[1] for b in ReflectionScreen.BINDINGS}
    assert not any("apply" in a or "accept" in a or "merge" in a or "post" in a for a in actions)


async def test_digest_now_and_due(refl):
    install_fixtures(refl)
    app = make_app(refl)
    async with app.run_test(size=(140, 40)) as pilot:
        screen = await open_reflection(app, pilot)
        assert not _mod("digest").load_digests(refl)
        await pilot.press("d")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert _mod("digest").load_digests(refl)  # the same digests `daedalus reflect digest` writes
        for f in (refl / ".daedalus/reflection/sessions").glob("*.json"):  # into a completed month
            d = json.loads(f.read_text(encoding="utf-8"))
            d["start"], d["end"] = "2026-09-15T10:00:00Z", "2026-09-15T11:00:00Z"
            d["event_days"] = {u: "2026-09-15" for u in d.get("event_days", {})}
            f.write_text(json.dumps(d), encoding="utf-8")
        await pilot.press("1")
        assert screen.rows[0]["key"] == "monthly:2026-09" and screen.rows[0]["state"] == "due"
        assert "Monthly 2026-09 is due" in detail(screen)
        assert not (refl / ".daedalus/reflection/due.json").exists()  # reading never writes the cache


async def test_reports_tab_reads_the_rendered_markdown(refl):
    folder = _mod("paths").reports_dir(refl)
    folder.mkdir(parents=True)
    (folder / "weekly-2026-W41.md").write_text(
        "# Reflection: weekly 2026-W41\n\n## Findings\n\n- **F1** (pattern): re-reads\n\n## Proposals\n\n"
        "- **Q1** [model, shown; Momus: holds]: one\n- **Q2** [model, shown; Momus: holds]: two\n")
    app = make_app(refl)
    async with app.run_test(size=(140, 40)) as pilot:
        screen = await open_reflection(app, pilot)
        await pilot.press("2")
        assert screen.rows[0]["title"] == "weekly 2026-W41" and screen.rows[0]["proposals"] == 2


async def test_user_model_edit_stable_forget_delete(refl):
    a = add_user()
    b = add_user("reviews PRs in batches")
    c = add_user("works late")
    app = make_app(refl)
    async with app.run_test(size=(140, 40)) as pilot:
        screen = await open_reflection(app, pilot)
        await pilot.press("3")
        assert "prefers terse status updates" in detail(screen)

        await pilot.press("e")
        await pilot.pause()
        modal = app.screen
        assert isinstance(modal, EditEntry)
        modal.query_one("#edit-observation").value = "prefers short status updates"
        modal.query_one("#edit-scope").value = "work"
        await pilot.press("enter")
        await pilot.pause()
        entry = m.find(m.load("user"), a["id"])
        assert entry["observation"] == "prefers short status updates" and entry["scope"] == "work"

        await pilot.press("S")
        assert m.find(m.load("user"), a["id"])["stable"] is True

        await pilot.press("down")
        await pilot.press("x")
        await pilot.pause()
        assert isinstance(app.screen, ConfirmModal)
        await pilot.press("escape")  # cancelled: nothing happens
        assert m.find(m.load("user"), b["id"])
        await pilot.press("x")
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        data = m.load("user")
        assert m.find(data, b["id"]) is None and m.is_tombstoned(data, entry_id=b["id"])

        await pilot.press("down")
        assert screen._selected()["key"] == c["id"]
        await pilot.press("f")
        await pilot.pause()
        assert isinstance(app.screen, ConfirmModal)
        await pilot.press("enter")
        await pilot.pause()
        assert m.find(m.load("user"), c["id"]) is None
        # reflection.forget defaults to purge: only the forget record itself is left
        assert [r["kind"] for r in m.load_history(model="user", entry_id=c["id"])] == ["forget"]


async def test_aspirations_are_deleted_never_edited(refl):
    asp = m.aspire("To ask before guessing", "claude-test", "2026-10")
    app = make_app(refl)
    async with app.run_test(size=(140, 40)) as pilot:
        screen = await open_reflection(app, pilot)
        await pilot.press("4")
        assert "✦ aspiration" in str(screen.query_one("#refl-list").get_option_at_index(0).prompt)
        await pilot.press("e")
        await pilot.press("S")
        await pilot.press("f")
        await pilot.pause()
        assert app.screen is screen
        assert m.find(m.load("self"), asp["id"]) == asp
        await pilot.press("x")
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert m.find(m.load("self"), asp["id"]) is None


async def test_export_the_experiment_log(refl):
    _mod("explog").record_arm(refl, "session-1", {"arm": "on", "mode": "ab", "seed": 4417})
    app = make_app(refl)
    async with app.run_test(size=(140, 40)) as pilot:
        screen = await open_reflection(app, pilot)
        await pilot.press("5")
        assert "A/B arms: ab:on 1" in detail(screen)
        await pilot.press("e")
        await pilot.pause()
        assert isinstance(app.screen, ExportLog)
        app.screen.query_one("#export-path").value = "out/log.jsonl"
        await pilot.press("enter")
        await pilot.pause()
    out = refl / "out" / "log.jsonl"
    assert out.read_text() == _mod("explog").log_path(refl).read_text()


def _comparable(records):
    return [{k: v for k, v in r.items() if k != "at"} for r in records]


async def test_a_tui_edit_records_the_same_history_as_the_cli(refl, tmp_path, monkeypatch):
    # The CLI on one models root
    use_models_root(monkeypatch, tmp_path / "cli-root")
    e = add_user()
    runner = CliRunner()
    for args in (["edit", e["id"], "--observation", "prefers short updates", "--confidence", "0.6", "--scope", "work"],
                 ["stable", e["id"]], ["delete", e["id"]]):
        assert runner.invoke(main, ["reflect", "model", "user", *args], catch_exceptions=False).exit_code == 0
    cli_history = m.load_history()

    # The TUI on another
    use_models_root(monkeypatch, tmp_path / "tui-root")
    add_user()
    app = make_app(refl)
    async with app.run_test(size=(140, 40)) as pilot:
        await open_reflection(app, pilot)
        await pilot.press("3")
        await pilot.press("e")
        await pilot.pause()
        modal = app.screen
        modal.query_one("#edit-observation").value = "prefers short updates"
        modal.query_one("#edit-confidence").value = "0.6"
        modal.query_one("#edit-scope").value = "work"
        await pilot.press("enter")
        await pilot.pause()
        await pilot.press("S")
        await pilot.press("x")
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
    tui_history = m.load_history()

    assert [r["kind"] for r in cli_history] == ["add", "user-edit", "stable", "user-delete"]
    assert _comparable(tui_history) == _comparable(cli_history)
    assert json.loads((tmp_path / "tui-root" / "models" / "user.json").read_text()) == \
        json.loads((tmp_path / "cli-root" / "models" / "user.json").read_text())
