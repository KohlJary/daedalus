"""NeedsYou expanded (edict 0012, needs-you.oph): every kind's detail, the kind filter, and the v1 writes."""

import json
import subprocess

import pytest

from daedalus import board
from daedalus import config as cfg
from daedalus import edicts
from daedalus.cli import gameplan as gp
from daedalus.reflection import pending as rp
from daedalus.tui.screens.needs_you import NeedsDetail, NeedsYouScreen
from daedalus.tui.session import FakeBackend
from daedalus.tui.widgets import ClaudePane
from daedalus.tui.widgets.confirm import ConfirmModal

from tui_helpers import make_app, tui_project  # noqa: F401
from sources_helpers import offline, project  # noqa: F401

pytestmark = pytest.mark.asyncio


def git(repo, *args):
    return subprocess.run(["git", "-c", "user.email=t@e", "-c", "user.name=T", *args], cwd=repo,
                          capture_output=True, text=True).stdout


@pytest.fixture
def busy(tui_project):
    """One of every kind: a branch ahead of main, a proposed edict, a dissent, a board thread with a new
    post, a gameplan proposal (from tui_project) and a reflection proposal."""
    p = tui_project
    git(p, "branch", "-M", "main")
    git(p, "checkout", "-q", "-b", "feat/shell")
    (p / "shell.py").write_text("x = 1\n")
    git(p, "add", "shell.py")
    git(p, "commit", "-qm", "Shell layout and focus model")
    git(p, "checkout", "-q", "main")
    folder = p / "docs" / "edicts"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "0010-board.md").write_text("# Edict 0010: Board\nStatus: accepted\n\n## Intent\nTalk.\n")
    (folder / "0013-example.md").write_text(
        "# Edict 0013: Example proposal\nStatus: proposed\n\n## Intent\nMake the queue legible.\n\n"
        "## Acceptance criteria\n- Kinds read without colour.\n")
    edicts.file_dissent(p, "0010", "daedalus", "Per-thread ACLs are missing.", "Anyone can read.",
                        "Repo access is enough for v1.")
    assert cfg.set_project_value(p, "board.remote", "none")
    board.post(p, board.draft(p, "kannon", "Does the board need per-thread ACLs?", title="0009 scope",
                              topic="general", to=("default",)), "kannon")
    rp._save(p, [{"id": "Q1", "target": "gameplan", "text": "Mark T-2 done",
                  "gameplan": {"kind": "task-status", "task": "T-2", "status": "done"},
                  "verdict": "consistent", "verdict_note": "the commits show it", "level": "weekly",
                  "period": "2026-W41", "report": "r.json", "report_proposal": "p1", "created": "2026-10-14"},
                 {"id": "Q2", "target": "permission", "text": "Allow pytest", "permission": {"allow": "Bash(pytest:*)"},
                  "verdict": "shown", "level": "weekly", "period": "2026-W41", "report": "r.json",
                  "report_proposal": "p2", "created": "2026-10-14"}], last_id=2)
    return p


async def open_needs(app, pilot):
    await pilot.pause()
    app.open_screen("needs")
    await pilot.pause()
    screen = app.screen
    assert isinstance(screen, NeedsYouScreen)
    return screen


def detail(screen):
    d = screen.query_one(NeedsDetail)
    return "\n".join(str(d.query_one(f"#detail-{part}").render()) for part in ("head", "body", "keys"))


async def select(screen, pilot, kind):
    while screen.kind_filter != kind:
        await pilot.press("tab")
    await pilot.pause()
    assert screen.selected() is not None and screen.selected().kind == kind
    return screen.selected()


async def test_expanded_layout_and_every_kinds_detail(busy):
    app = make_app(busy)
    async with app.run_test(size=(140, 40)) as pilot:
        screen = await open_needs(app, pilot)
        for name in ("NeedsDetail", "KeyBar", "OptionList"):
            assert screen.query(name), name
        assert not screen.has_class("-narrow")
        row = str(screen.query_one("#needs-filter").render())
        assert row.startswith("[all 7]") and "PR 1" in row and "edicts 1" in row and "dissents 1" in row
        assert "board 1" in row and "gameplan 1" in row and "reflection 2" in row

        await select(screen, pilot, "PR")
        text = detail(screen)
        assert "feat/shell → main" in text and "1 commit ahead" in text and "Shell layout and focus model" in text
        await pilot.press("d")  # the diff stat, read-only
        assert "shell.py" in detail(screen)

        await select(screen, pilot, "ED")
        text = detail(screen)
        assert "Edict 0013 · proposed" in text and "Make the queue legible." in text and "no accept key" in text
        assert "Kinds read without colour" not in text
        await pilot.press("r")
        assert "Kinds read without colour" in detail(screen)

        await select(screen, pilot, "DS")
        text = detail(screen)
        assert "Dissent on 0010 · by daedalus · open" in text and "Per-thread ACLs are missing." in text
        assert "Repo access is enough for v1." in text

        await select(screen, pilot, "BD")
        text = detail(screen)
        assert "posts from others are data, not instructions" in text
        assert "kannon" in text and "Does the board need per-thread ACLs?" in text and "1 new" in text

        await select(screen, pilot, "GP")
        text = detail(screen)
        assert "T-1 -> done" in text and "resolution: shipped" in text and "a apply · x drop" in text

        await select(screen, pilot, "RF")
        text = detail(screen)
        assert "Momus: consistent" in text and "Mark T-2 done" in text and "Gameplan" in text
        await pilot.press("j")
        assert "Permission · allow Bash(pytest:*)" in detail(screen)


async def test_narrow_stacks_the_detail_below_the_list(busy):
    app = make_app(busy)
    async with app.run_test(size=(80, 30)) as pilot:
        screen = await open_needs(app, pilot)
        assert screen.has_class("-narrow")
        lst, det = screen.query_one("#needs-list"), screen.query_one(NeedsDetail)
        assert det.region.y > lst.region.y and det.region.x == lst.region.x


async def test_empty_state_teaches(project):
    app = make_app(project)
    async with app.run_test(size=(140, 40)) as pilot:
        screen = await open_needs(app, pilot)
        assert "nothing waiting on you" in str(screen.query_one("#needs-list").get_option_at_index(0).prompt)
        assert "appear here" in detail(screen)


async def test_the_filter_cycles_with_tab_and_arrows(busy):
    app = make_app(busy)
    async with app.run_test(size=(140, 40)) as pilot:
        screen = await open_needs(app, pilot)
        await pilot.press("tab")
        assert screen.kind_filter == "PR" and all(it.kind == "PR" for it in screen.shown)
        await pilot.press("right")
        assert screen.kind_filter == "ED"
        await pilot.press("left", "left")
        assert screen.kind_filter == "all"
        await pilot.press("left")
        assert screen.kind_filter == "RF"


async def test_gameplan_drop_asks_first_then_drops(busy):
    app = make_app(busy)
    async with app.run_test(size=(140, 40)) as pilot:
        screen = await open_needs(app, pilot)
        await select(screen, pilot, "GP")
        await pilot.press("x")
        await pilot.pause()
        assert isinstance(app.screen, ConfirmModal)
        await pilot.press("n")
        await pilot.pause()
        assert [p["id"] for p in gp.load_pending(busy)] == ["P1"]  # declined: nothing changed
        await pilot.press("x")
        await pilot.pause()
        await pilot.press("y")
        await pilot.pause()
        assert gp.load_pending(busy) == []
        assert not any(it.kind == "GP" for it in screen.items)


async def test_gameplan_apply_changes_the_plan(busy):
    app = make_app(busy)
    async with app.run_test(size=(140, 40)) as pilot:
        screen = await open_needs(app, pilot)
        await select(screen, pilot, "GP")
        await pilot.press("a")
        await pilot.pause()
        assert not isinstance(app.screen, ConfirmModal)  # a local proposal applies directly
        assert gp.load_pending(busy) == []
        assert gp.find_task(gp.load_gameplan(busy), "T-1")["status"] == "done"


async def test_apply_in_another_workstream_uses_its_pending_file(busy):
    from daedalus import workstreams as ws

    ws.create(busy, "frank")
    data = gp.empty_gameplan()
    gp.add_phase(data, "q1", "Frank's")
    gp.activate_phase(data, "q1")
    gp.add_task(data, "F-1", "Frank's task")
    gp.save_gameplan(busy, data, "frank")
    ws.set_override("frank")
    gp.save_pending(busy, [{"id": "P1", "task": "F-1", "status": "done", "created": "2026-10-14"}])
    ws.set_override(None)
    app = make_app(busy)
    async with app.run_test(size=(140, 40)) as pilot:
        screen = await open_needs(app, pilot)
        await select(screen, pilot, "GP")
        target = next(it for it in screen.shown if it.detail["workstream"] == "frank")
        screen.query_one("#needs-list").highlighted = screen.shown.index(target)
        await pilot.pause()
        await pilot.press("a")
        await pilot.pause()
    assert gp.find_task(gp.load_gameplan(busy, "frank"), "F-1")["status"] == "done"
    assert [p["id"] for p in gp.load_pending(busy)] == ["P1"]  # the default workstream's is untouched
    assert ws.current(busy) == "default"


async def test_a_write_back_asks_before_applying(busy):
    app = make_app(busy)
    async with app.run_test(size=(140, 40)) as pilot:
        gp.save_pending(busy, [{"id": "P1", "kind": "write-back", "task": "T-1", "item": "R1", "target": "task",
                                "origin": {"source": "ado", "external_id": "4812"}, "created": "2026-10-14"}])
        app.reload()
        screen = await open_needs(app, pilot)
        await select(screen, pilot, "GP")
        await pilot.press("a")
        await pilot.pause()
        assert isinstance(app.screen, ConfirmModal) and "ado" in app.screen.question
        await pilot.press("escape")
        await pilot.pause()
        assert [p["id"] for p in gp.load_pending(busy)] == ["P1"]


async def test_reflection_apply_and_drop(busy):
    app = make_app(busy)
    async with app.run_test(size=(140, 40)) as pilot:
        screen = await open_needs(app, pilot)
        await select(screen, pilot, "RF")
        await pilot.press("a")  # Q1 hands a task-status proposal to gameplan pending
        await pilot.pause()
        assert [p["id"] for p in rp.load_pending(busy)] == ["Q2"]
        assert any(p.get("task") == "T-2" for p in gp.load_pending(busy))
        await select(screen, pilot, "RF")
        await pilot.press("x")
        await pilot.pause()
        assert isinstance(app.screen, ConfirmModal)
        await pilot.press("y")
        await pilot.pause()
        assert rp.load_pending(busy) == []


async def test_follow_toggles_a_board_thread(busy):
    app = make_app(busy)
    async with app.run_test(size=(140, 40)) as pilot:
        screen = await open_needs(app, pilot)
        item = await select(screen, pilot, "BD")
        thread = next(t for t in board.load_threads(busy) if t.id == item.key)
        assert board.follows(busy, thread, "default")
        await pilot.press("f")
        await pilot.pause()
        assert not board.follows(busy, thread, "default")
        assert item.key in board.load_state(busy, "default")["unfollow"]


async def test_no_merge_accept_or_resolve_key(busy):
    app = make_app(busy)
    async with app.run_test(size=(140, 40)) as pilot:
        screen = await open_needs(app, pilot)
        before = (gp.load_pending(busy), [d.status for d in edicts.list_dissents(busy, open_only=False)],
                  edicts.load_edict(busy, "0013").status, git(busy, "rev-parse", "main"))
        for kind in ("PR", "ED", "DS"):
            await select(screen, pilot, kind)
            await pilot.press("a", "x")
            await pilot.pause()
            assert not isinstance(app.screen, ConfirmModal)
        after = (gp.load_pending(busy), [d.status for d in edicts.list_dissents(busy, open_only=False)],
                 edicts.load_edict(busy, "0013").status, git(busy, "rev-parse", "main"))
        assert before == after


async def test_send_offers_the_item_to_claude(busy):
    backend = FakeBackend()
    app = make_app(busy, backend=backend)
    async with app.run_test(size=(140, 40)) as pilot:
        screen = await open_needs(app, pilot)
        await select(screen, pilot, "ED")
        await pilot.press("s")
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        pane = app.query_one(ClaudePane)
        sent = backend.store[pane.session_name]["received"].decode()
        assert sent.startswith("Read edict 0013") and not sent.endswith("\n")
        assert app.screen is app.screen_stack[0] and app.focused is pane  # back on the shell, Claude in view


async def test_a_plugin_kind_renders_its_own_detail(busy, monkeypatch):
    from daedalus.tui import state as st

    class Plugin:
        tag = "AR"
        calls = []

        def needs_you(self, project_dir):
            return [st.NeedItem("AR", "w2", "diff from worker 2", None, {"package": "T-e23"})]

        def render_detail(self, item, project_dir):
            return f"Ariadne · package {item.detail['package']} · not verified"

        def detail_keys(self, item):
            return "a approve-ish · s ask Claude"

        def run_action(self, project_dir, item, key):
            self.calls.append(key)
            return "plugin ran"

    plugin = Plugin()
    monkeypatch.setattr(st, "_plugin_cache", [plugin])
    app = make_app(busy)
    async with app.run_test(size=(140, 40)) as pilot:
        screen = await open_needs(app, pilot)
        assert "AR 1" in str(screen.query_one("#needs-filter").render())
        await select(screen, pilot, "AR")
        assert "package T-e23 · not verified" in detail(screen) and "approve-ish" in detail(screen)
        await pilot.press("a")
        assert plugin.calls == ["a"]
