"""The Gameplan screen (edict 0012, gameplan.oph @expanded and @workstreams, plus the Roadmap tab): every tab,
the roadmap detail, and that nothing here writes the gameplan."""

import json

import pytest

from daedalus import workstreams as ws
from daedalus.cli import gameplan as gp
from daedalus.tui.widgets import KeyBar, SendToClaude

from tui_helpers import make_app, tui_project  # noqa: F401
from sources_helpers import offline, project  # noqa: F401

pytestmark = pytest.mark.asyncio


@pytest.fixture
def plan_project(tui_project):
    index = {"version": 1, "items": [
        {"id": "local-1", "title": "Shell layout", "status": "in_progress", "priority": "P1", "item_type": "feature",
         "origin": {"source": "local"}},
        {"id": "github-12", "title": "Crash on start", "status": "backlog", "priority": "P0", "item_type": "bug",
         "description": "It crashes.", "origin": {"source": "github", "external_id": "#12",
                                                    "url": "https://github.com/acme/widgets/issues/12"},
         "synced": {"fields": {"title": "Crash on start", "status": "backlog"}}},
    ]}
    (tui_project / ".daedalus/roadmap/index.json").write_text(json.dumps(index))
    data = gp.load_gameplan(tui_project)
    data["phases"][0]["roadmapItems"] = ["local-1"]
    data["phases"][0]["edict"] = "0012"
    t1, t2 = data["activePhase"]["tasks"]
    t1.update(edict="0001", roadmapItem="local-1", details="Lay out the panels.")
    t2.update(status="done", resolution="shipped in abc123")
    gp.add_phase(data, "p2", "Second phase", roadmap_items=["github-12"])
    data["phases"][1]["tasks"] = [{"id": "T-9", "title": "Fix the crash", "status": "pending", "roadmapItem": "github-12"}]
    gp.save_gameplan(tui_project, data)
    ws.create(tui_project, "agent-a", kind="session")
    ws.set_claims(tui_project, "agent-a", add=["src/**"])
    other = ws.load(tui_project, "agent-a")
    gp.add_phase(other, "a1", "Agent phase")
    gp.activate_phase(other, "a1")
    gp.add_task(other, "A-1", "Agent task")
    gp.save_gameplan(tui_project, other, "agent-a")
    return tui_project


def _text(screen, selector):
    return str(screen.query_one(selector).render())


def _options(screen, selector):
    ol = screen.query_one(selector)
    return [str(ol.get_option_at_index(i).prompt) for i in range(ol.option_count)]


async def _open(app, pilot):
    await pilot.pause()
    app.open_screen("gameplan")
    await pilot.pause()
    return app.screen


async def test_plan_tab_phases_tasks_and_detail(plan_project):
    before = {p: p.read_bytes() for p in (plan_project / ".daedalus").rglob("*.json")}
    app = make_app(plan_project)
    async with app.run_test(size=(140, 40)) as pilot:
        screen = await _open(app, pilot)
        assert type(screen).__name__ == "GameplanScreen"
        assert screen.query(KeyBar)  # ◆KeyBar
        assert "[Plan]" in _text(screen, "#gp-tabs")
        phases = _options(screen, "#phases")
        assert phases[0].startswith("[>]*p1") and phases[1].startswith("[ ] p2")
        tasks = _options(screen, "#tasks")
        assert tasks[0].startswith("[>] T-1") and any("done (1)" in t for t in tasks) and tasks[-1].startswith("[x] T-2")
        detail = _text(screen, "#plan-detail")
        assert "p1 · in_progress · active" in detail and "edict: 0012" in detail and "Shell layout (local)" in detail

        await pilot.press("right")                     # into the tasks column
        assert screen.focused.id == "tasks"
        detail = _text(screen, "#plan-detail")
        assert "T-1 · in_progress" in detail and "edict: 0001" in detail and "roadmap item: local-1 Shell layout" in detail
        assert "Resolution:\n—" in detail
        await pilot.press("down")                      # past the done separator to T-2
        detail = _text(screen, "#plan-detail")
        assert "T-2 · done" in detail and "shipped in abc123" in detail

        await pilot.press("left", "down")              # a planned phase shows its queued tasks
        assert _options(screen, "#tasks")[0].startswith("[ ] T-9")
        assert "Tasks appear when" not in _text(screen, "#plan-detail")

        await pilot.press("question_mark")
        await pilot.pause()
        assert "Gameplan" in " ".join(str(w.render()) for w in app.screen.query("Static"))
        await pilot.press("escape")
        await pilot.press("escape")
        await pilot.pause()
        assert type(app.screen).__name__ != "GameplanScreen"
    assert {p: p.read_bytes() for p in (plan_project / ".daedalus").rglob("*.json")} == before  # no writes


async def test_send_to_claude_from_a_task(plan_project):
    app = make_app(plan_project)
    async with app.run_test(size=(140, 40)) as pilot:
        screen = await _open(app, pilot)
        await pilot.press("right")
        await pilot.press("s")
        await pilot.pause()
        assert isinstance(app.screen, SendToClaude)
        assert app.screen.source == "Task T-1" and "T-1" in app.screen.prompt
        await pilot.press("escape")
        await pilot.pause()
        assert app.screen is screen


async def test_e_opens_the_cited_edict(plan_project):
    (plan_project / "docs/edicts").mkdir(parents=True)
    (plan_project / "docs/edicts/0001-first.md").write_text("# Edict 0001: First\nStatus: accepted\n\nBody.\n")
    app = make_app(plan_project)
    async with app.run_test(size=(140, 40)) as pilot:
        await _open(app, pilot)
        await pilot.press("right", "e")
        await pilot.pause()
        assert type(app.screen).__name__ == "EdictsScreen"
        assert "0001 · accepted" in str(app.screen.query_one("#edict-head").render())


async def test_workstreams_tab_and_showing_another_plan(plan_project):
    app = make_app(plan_project)
    async with app.run_test(size=(140, 40)) as pilot:
        screen = await _open(app, pilot)
        await pilot.press("w")
        assert "[Workstreams]" in _text(screen, "#gp-tabs")
        rows = _options(screen, "#workstream-list")
        assert rows[0].startswith("* default") and "p1 ▸ T-1" in rows[0]
        assert "agent-a" in rows[1] and "session" in rows[1] and "a1 ▸ A-1" in rows[1]
        detail = _text(screen, "#workstream-detail")
        assert "default · owner: person" in detail and "plan: .daedalus/roadmap/gameplan.json" in detail
        assert "claims: (none)" in detail and "collisions: none" in detail
        await pilot.press("down")
        detail = _text(screen, "#workstream-detail")
        assert "claims: src/**" in detail and "plan: .daedalus/gameplans/agent-a.json" in detail
        await pilot.press("enter")                    # show its plan, read-only
        await pilot.pause()
        assert screen.tab == "plan" and screen.workstream == "agent-a"
        assert _options(screen, "#phases")[0].startswith("[>]*a1")
        assert "agent-a workstream" in _text(screen, "#gp-title")
        assert ws.current(plan_project) == "default"  # showing it doesn't switch the current workstream


async def test_roadmap_tab_lists_origins_and_shows_the_item(plan_project):
    app = make_app(plan_project)
    async with app.run_test(size=(140, 40)) as pilot:
        screen = await _open(app, pilot)
        await pilot.press("m")
        assert "[Roadmap]" in _text(screen, "#gp-tabs")
        rows = _options(screen, "#roadmap-list")
        assert "local" in rows[0] and "Shell layout" in rows[0]
        assert "github #12" in rows[1] and "Crash on start" in rows[1]
        detail = _text(screen, "#roadmap-detail")
        assert "origin: local" in detail and "default/p1 [in_progress]: First phase" in detail
        assert "default/p1/T-1 [in_progress]: Build the shell" in detail
        await pilot.press("down")
        detail = _text(screen, "#roadmap-detail")
        assert "origin: github #12  https://github.com/acme/widgets/issues/12" in detail
        assert "last sync saw:" in detail and "status: backlog" in detail and "It crashes." in detail
        assert "default/p2/T-9 [pending]: Fix the crash" in detail
        await pilot.press("s")
        await pilot.pause()
        assert isinstance(app.screen, SendToClaude) and "github-12" in app.screen.prompt


async def test_empty_states_teach(project):
    app = make_app(project)
    async with app.run_test(size=(140, 40)) as pilot:
        screen = await _open(app, pilot)
        assert "daedalus gameplan phase add" in _text(screen, "#plan-detail")
        await pilot.press("m")
        assert "daedalus roadmap add" in _text(screen, "#roadmap-detail")
