"""
The Gameplan screen (docs/design/tui/gameplan.oph, @expanded and @workstreams; the Roadmap tab is from the
README's screen map). Three tabs:

- Plan: phases, then the selected phase's tasks, then the detail (resolution, edict, roadmap item).
- Workstreams: one row per workstream (`daedalus workstream list`); enter shows that workstream's plan.
- Roadmap: the intake, each item with its origin, and its detail the way `daedalus roadmap show` prints it.

Read-only (edict 0012). The gameplan's only TUI writes are applying or dropping pending proposals, which
live in NeedsYou; here, `s` hands a change to Claude.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from rich.text import Text
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import OptionList, Static
from textual.widgets.option_list import Option

from ..widgets import ExplainCard, KeyBar

TABS = (("plan", "Plan"), ("workstreams", "Workstreams"), ("roadmap", "Roadmap"))
PHASE_MARKS = {"done": "[x]", "in_progress": "[>]", "planned": "[ ]"}
TASK_MARKS = {"done": "[x]", "in_progress": "[>]", "pending": "[ ]", "deferred": "[-]"}
CARDS = {"plan": "Gameplan", "workstreams": "Workstream", "roadmap": "Roadmap"}
KEYS = {
    "plan": "←/→ column · ↑/↓ select · s send to Claude · e edict · p/w/m tab · ? explain · esc back",
    "workstreams": "↑/↓ select · enter show its plan · s send to Claude · p/w/m tab · ? explain · esc back",
    "roadmap": "↑/↓ select · s send to Claude · p/w/m tab · ? explain · esc back",
}


def tab_strip(active: str) -> str:
    return " · ".join(f"[{name}]" if key == active else name for key, name in TABS)


# ---------- reading (library functions only) ----------

def load_plan(project_dir: Path, workstream: Optional[str]) -> dict:
    from ..state import gameplan

    return gameplan(project_dir, workstream)


def load_workstreams(project_dir: Path) -> list[dict]:
    from ... import workstreams as ws
    from ...cli import gameplan as gp
    from ...doctor import check_collisions

    plans, rows = {}, []
    current = ws.current(project_dir)
    for wid in ws.list_ids(project_dir):
        try:
            data = ws.load(project_dir, wid)
        except ws.WorkstreamError:
            continue
        plans[wid] = data
        path = gp.GameplanPaths.for_project(project_dir, wid).gameplan_file
        try:
            rel = str(path.relative_to(project_dir))
        except ValueError:
            rel = str(path)
        rows.append({"id": wid, "owner": ws.owner(data, wid), "claims": list(data.get("claims") or []),
                     "summary": ws.summary_line(data, wid), "plan": rel, "current": wid == current,
                     "active": (data.get("activePhase") or {}).get("id"), "next": _next_task(data)})
    collisions = check_collisions(plans)
    for row in rows:
        row["collisions"] = [f.message for f in collisions if f" {row['id']} " in f" {f.message} "]
    return rows


def _next_task(data: dict) -> Optional[str]:
    active = data.get("activePhase") or {}
    for status in ("in_progress", "pending"):
        for t in active.get("tasks", []):
            if t.get("status") == status:
                return t.get("id")
    return None


def load_roadmap(project_dir: Path) -> tuple[list[dict], Optional[str]]:
    from ... import roadmap as rm

    try:
        return list(rm.load_index(project_dir).get("items", [])), None
    except rm.RoadmapError as e:
        return [], str(e)


def phase_tasks(data: dict, phase: dict) -> list[dict]:
    """The tasks to list for a phase: the active phase's, or tasks queued on a planned one."""
    active = data.get("activePhase") or {}
    if active and active.get("id") == phase.get("id"):
        return list(active.get("tasks", [])) + [dict(t, status="deferred") for t in active.get("deferred", [])
                                                 if isinstance(t, dict)]
    return [t for t in (phase.get("tasks") or []) if isinstance(t, dict)]


def roadmap_detail(project_dir: Path, item: dict) -> str:
    """One item as `daedalus roadmap show` prints it: origin and sync baseline, then phases, then tasks."""
    from ... import roadmap as rm

    o = rm.origin(item)
    lines = [f"{item.get('id')}: {item.get('title', 'Untitled')}",
             f"status: {item.get('status', 'backlog')}   priority: {item.get('priority', 'P2')}   "
             f"type: {item.get('item_type', 'task')}"]
    if o["source"] == "local":
        lines.append("origin: local (typed in here)")
    else:
        lines.append(f"origin: {o['source']} {o.get('external_id', '')}  {o.get('url', '')}".rstrip())
    if item.get("description"):
        lines += ["", "description:", str(item["description"]).strip()]
    synced = item.get("synced")
    if synced:
        lines += ["", "last sync saw:"]
        lines += [f"  {k}: {str(v).splitlines()[0] if str(v) else ''}" for k, v in synced.get("fields", {}).items()]
        if synced.get("remote_updated"):
            lines.append(f"  (changed in the tracker at {synced['remote_updated']})")
        if synced.get("write_back"):
            lines.append(f"write-back: {synced['write_back']}")
    phases, tasks = rm.references(project_dir, item.get("id", ""))
    lines += ["", "Phases:" if phases else "Phases: none list it"]
    lines += [f"  {w}/{p.get('id')} [{p.get('status', 'planned')}]: {p.get('title', '')}" for w, p in phases]
    lines.append("Tasks:" if tasks else "Tasks: none point to it")
    lines += [f"  {w}/{ph}/{t.get('id')} [{t.get('status', 'pending')}]: {t.get('title', '')}" for w, ph, t in tasks]
    lines += ["", f"CLI: daedalus roadmap show {str(item.get('id', ''))[:8]}"]
    return "\n".join(lines)


# ---------- the screen ----------

class GameplanScreen(Screen):
    """The expanded Gameplan: plan, workstreams and roadmap tabs. Read-only."""

    BINDINGS = [
        ("escape", "back", "back"), ("question_mark", "explain", "explain"), ("s", "send", "send to Claude"),
        ("e", "edict", "edict"), ("p", "tab('plan')", "plan"), ("w", "tab('workstreams')", "workstreams"),
        ("m", "tab('roadmap')", "roadmap"), ("left", "column(-1)", "column"), ("right", "column(1)", "column"),
        ("h", "column(-1)", "column"), ("l", "column(1)", "column"), ("j", "cursor('down')", "down"),
        ("k", "cursor('up')", "up"),
    ]
    DEFAULT_CSS = """
    GameplanScreen { layout: vertical; }
    GameplanScreen #gp-title { height: 1; padding: 0 1; background: $boost; text-style: bold; }
    GameplanScreen #gp-tabs { height: 1; padding: 0 1; color: $text-muted; }
    GameplanScreen .gp-body { height: 1fr; }
    GameplanScreen OptionList { height: 1fr; border: round $panel; }
    GameplanScreen OptionList:focus { border: round $accent; }
    GameplanScreen #phases { width: 26; }
    GameplanScreen #tasks { width: 1fr; }
    GameplanScreen #workstream-list, GameplanScreen #roadmap-list { width: 2fr; }
    GameplanScreen .detail { width: 3fr; border: round $panel; }
    GameplanScreen #plan-detail-box { width: 1fr; }
    GameplanScreen .detail-body { height: 1fr; padding: 0 1; }
    GameplanScreen .detail-keys { height: 1; padding: 0 1; color: $text-muted; border-top: solid $panel; }
    """

    def __init__(self, app: Any, tab: str = "plan", workstream: Optional[str] = None):
        super().__init__()
        self.project_dir = Path(app.project_dir)
        self.tab = tab
        self.workstream = workstream          # None: the current workstream
        self.plan: dict = {}
        self.phases: list[dict] = []
        self.tasks: list[dict] = []
        self.workstream_rows: list[dict] = []
        self.items: list[dict] = []
        self.roadmap_error: Optional[str] = None
        self.selected_phase: Optional[str] = None
        self.selected_task: Optional[str] = None
        self.focus_on = "phase"                 # what the plan detail shows: the phase or the task

    def compose(self):
        yield Static("Gameplan", id="gp-title")
        yield Static("", id="gp-tabs", markup=False)
        with Horizontal(id="tab-plan", classes="gp-body"):
            yield OptionList(id="phases")
            yield OptionList(id="tasks")
            with Vertical(id="plan-detail-box", classes="detail"):
                with VerticalScroll(classes="detail-body"):
                    yield Static("", id="plan-detail", markup=False)
                yield Static("s send to Claude · e edict", id="plan-keys", classes="detail-keys")
        with Horizontal(id="tab-workstreams", classes="gp-body"):
            yield OptionList(id="workstream-list")
            with Vertical(classes="detail"):
                with VerticalScroll(classes="detail-body"):
                    yield Static("", id="workstream-detail", markup=False)
                yield Static("enter show its plan · s send to Claude", classes="detail-keys")
        with Horizontal(id="tab-roadmap", classes="gp-body"):
            yield OptionList(id="roadmap-list")
            with Vertical(classes="detail"):
                with VerticalScroll(classes="detail-body"):
                    yield Static("", id="roadmap-detail", markup=False)
                yield Static("s send to Claude", classes="detail-keys")
        yield KeyBar()

    def on_mount(self) -> None:
        self.reload()
        self.action_tab(self.tab)

    # ----- data -----

    def refresh_state(self, state: Any = None) -> None:
        self.reload()

    def reload(self) -> None:
        self.plan = load_plan(self.project_dir, self.workstream)
        self.phases = list(self.plan.get("phases", []))
        self.workstream_rows = load_workstreams(self.project_dir)
        self.items, self.roadmap_error = load_roadmap(self.project_dir)
        self._fill_phases()
        self._fill_workstreams()
        self._fill_roadmap()
        self._title()

    def _title(self) -> None:
        wid = self.workstream or next((r["id"] for r in self.workstream_rows if r["current"]), "default")
        active = self.plan.get("activePhase") or {}
        tasks = active.get("tasks", [])
        done = sum(1 for t in tasks if t.get("status") == "done")
        tag = f"{active.get('id')} · {done}/{len(tasks)}" if active else "no active phase"
        self.query_one("#gp-title", Static).update(f"Gameplan  ({wid} workstream · {tag})")

    def _fill(self, widget_id: str, options: list, keep: Optional[str]) -> None:
        ol = self.query_one(f"#{widget_id}", OptionList)
        ol.clear_options()
        ol.add_options(options)
        ids = [o.id for o in options if isinstance(o, Option) and o.id]
        if keep in ids:
            ol.highlighted = ol.get_option_index(keep)
        elif ids:
            ol.highlighted = ol.get_option_index(ids[0])

    def _fill_phases(self) -> None:
        active_id = (self.plan.get("activePhase") or {}).get("id")
        if not self.phases:
            self.query_one("#phases", OptionList).clear_options()
            self.query_one("#tasks", OptionList).clear_options()
            self.query_one("#plan-detail", Static).update(
                "No phases yet.\n\nA phase groups roadmap items into one stretch of work; the active phase "
                "breaks into tasks.\n\nStart one:\n  daedalus gameplan phase add p1 \"First phase\"\n"
                "  daedalus gameplan phase activate p1\n\nOr press s and ask Claude to draft a plan.")
            return
        options = []
        for p in self.phases:
            mark = PHASE_MARKS.get(p.get("status"), "[ ]")
            star = "*" if p.get("id") == active_id else " "
            options.append(Option(Text(f"{mark}{star}{p.get('id', '')}  {p.get('title', '')}"), id=f"phase:{p.get('id')}"))
        keep = f"phase:{self.selected_phase}" if self.selected_phase else (f"phase:{active_id}" if active_id else None)
        self._fill("phases", options, keep)
        self._show_phase(self._phase_at(self.query_one("#phases", OptionList).highlighted))

    def _phase_at(self, index: Optional[int]) -> Optional[dict]:
        if index is None or not (0 <= index < len(self.phases)):
            return None
        return self.phases[index]

    def _show_phase(self, phase: Optional[dict]) -> None:
        if phase is None:
            return
        self.selected_phase = phase.get("id")
        tasks = phase_tasks(self.plan, phase)
        open_ = [t for t in tasks if t.get("status") == "in_progress"] + \
                [t for t in tasks if t.get("status") == "pending"] + \
                [t for t in tasks if t.get("status") == "deferred"]
        done = [t for t in tasks if t.get("status") == "done"]
        self.tasks = open_ + done
        options: list = [Option(Text(f"{TASK_MARKS.get(t.get('status'), '[ ]')} {t.get('id', '')}  {t.get('title', '')}"),
                                id=f"task:{t.get('id')}") for t in open_]
        if done:
            options.append(None)
            options.append(Option(Text(f"─ done ({len(done)}) ─"), id="done-sep", disabled=True))
            options += [Option(Text(f"[x] {t.get('id', '')}  {t.get('title', '')}"), id=f"task:{t.get('id')}")
                        for t in done]
        ol = self.query_one("#tasks", OptionList)
        ol.clear_options()
        ol.add_options(options)
        ids = [o.id[5:] for o in options if o and o.id and o.id.startswith("task:")]
        if self.selected_task not in ids:
            self.selected_task = ids[0] if ids else None
        if self.selected_task:
            ol.highlighted = ol.get_option_index(f"task:{self.selected_task}")
        if self.focus_on == "task" and self._current_task():
            self._show_task_detail(self._current_task())
        else:
            self._show_phase_detail(phase, bool(tasks))

    def _show_phase_detail(self, phase: dict, has_tasks: bool) -> None:
        from ... import roadmap as rm

        active = self.plan.get("activePhase") or {}
        is_active = active.get("id") == phase.get("id")
        lines = [f"{phase.get('id')} · {phase.get('status', 'planned')}" + (" · active" if is_active else ""),
                 phase.get("title", "")]
        if phase.get("edict"):
            lines.append(f"edict: {phase['edict']}  (e to open)")
        if is_active:
            if active.get("goal"):
                lines += ["", "Goal:", active["goal"]]
            if active.get("sequencing"):
                lines += ["", "Sequencing:", active["sequencing"]]
        if phase.get("notes"):
            lines += ["", "Notes:", phase["notes"]]
        items = phase.get("roadmapItems") or []
        if items:
            index = {i.get("id"): i for i in self.items}
            lines += ["", "Roadmap items:"]
            lines += [f"  {str(i)[:8]}  " + (f"{index[i].get('title', '')} ({rm.origin_label(index[i])})"
                                             if i in index else "(not in the roadmap)") for i in items]
        if not has_tasks:
            lines += ["", "No tasks listed." if is_active else
                      ("Its tasks were recorded while it was active; git history has them." if phase.get("status") == "done"
                       else "Tasks appear when this phase is activated:\n  daedalus gameplan phase activate "
                            f"{phase.get('id')}")]
        self.query_one("#plan-detail", Static).update("\n".join(lines))
        self.query_one("#plan-keys", Static).update("s send to Claude" + (" · e edict" if phase.get("edict") else ""))

    def _current_task(self) -> Optional[dict]:
        if not self.selected_task:
            return None
        return next((t for t in self.tasks if t.get("id") == self.selected_task), None)

    def _show_task_detail(self, task: dict) -> None:
        from ... import roadmap as rm

        lines = [f"{task.get('id')} · {task.get('status', 'pending')}", task.get("title", "")]
        if task.get("details"):
            lines += ["", task["details"]]
        if task.get("edict"):
            lines += ["", f"edict: {task['edict']}  (e to open)"]
        if task.get("roadmapItem"):
            item = rm.find_optional({"items": self.items}, task["roadmapItem"])
            label = f"{item.get('title', '')} ({rm.origin_label(item)})" if item else "(not in the roadmap)"
            lines += [f"roadmap item: {str(task['roadmapItem'])[:8]} {label}"]
        origin = task.get("origin")
        if isinstance(origin, dict) and origin.get("source") not in (None, "local"):
            lines.append(f"from: {origin['source']} {origin.get('external_id', '')}".rstrip())
        if task.get("updated"):
            lines.append(f"updated: {task['updated']}")
        if task.get("reason"):
            lines += ["", "Deferred because:", str(task["reason"])]
        lines += ["", "Resolution:", task.get("resolution") or "—"]
        self.query_one("#plan-detail", Static).update("\n".join(lines))
        self.query_one("#plan-keys", Static).update("s send to Claude" + (" · e edict" if task.get("edict") else ""))

    def _fill_workstreams(self) -> None:
        if not self.workstream_rows:
            self.query_one("#workstream-list", OptionList).clear_options()
            self.query_one("#workstream-detail", Static).update(
                "No workstreams yet.\n\nA workstream is one owner's committed plan. The default one is "
                ".daedalus/roadmap/gameplan.json, which `daedalus init` creates.\n\n"
                "Add another: daedalus workstream new <id>")
            return
        options = []
        for r in self.workstream_rows:
            mark = "*" if r["current"] else " "
            where = f"{r['active']} ▸ {r['next']}" if r["active"] and r["next"] else (r["active"] or "no active phase")
            options.append(Option(Text(f"{mark} {r['id']:<10} {r['owner'].get('kind', 'person'):<7} {where}"),
                                  id=f"ws:{r['id']}"))
        ol = self.query_one("#workstream-list", OptionList)
        keep = ol.highlighted_option.id if ol.highlighted_option else None
        self._fill("workstream-list", options, keep)
        self._show_workstream(ol.highlighted)

    def _show_workstream(self, index: Optional[int]) -> None:
        if index is None or not (0 <= index < len(self.workstream_rows)):
            return
        r = self.workstream_rows[index]
        o = r["owner"]
        who = f"{o.get('kind', 'person')}" + (f" (git author {o['git_author']})" if o.get("git_author") else "")
        lines = [f"{r['id']} · owner: {who}" + ("  (current)" if r["current"] else ""),
                 f"plan: {r['plan']}",
                 "claims: " + (", ".join(r["claims"]) if r["claims"] else "(none)"),
                 "collisions: " + ("\n  ".join([""] + r["collisions"]) if r["collisions"] else "none"),
                 "", r["summary"], "", f"CLI: daedalus workstream show {r['id']}"]
        self.query_one("#workstream-detail", Static).update("\n".join(lines))

    def _fill_roadmap(self) -> None:
        from ... import roadmap as rm

        if self.roadmap_error or not self.items:
            self.query_one("#roadmap-list", OptionList).clear_options()
            self.query_one("#roadmap-detail", Static).update(self.roadmap_error or (
                "The roadmap is empty.\n\nIt's the intake: what's been asked for, typed in here or brought in "
                "from a tracker by a source. Phases pull items in; tasks point back at one.\n\n"
                "Add one: daedalus roadmap add \"Title\"\nOr sync a source: daedalus source sync"))
            return
        options = [Option(Text(f"{str(i.get('status', 'backlog')):<11} {rm.origin_label(i):<14} {i.get('title', '')}"),
                          id=f"item:{i.get('id')}") for i in self.items]
        ol = self.query_one("#roadmap-list", OptionList)
        keep = ol.highlighted_option.id if ol.highlighted_option else None
        self._fill("roadmap-list", options, keep)
        self._show_item(ol.highlighted)

    def _show_item(self, index: Optional[int]) -> None:
        if index is None or not (0 <= index < len(self.items)):
            return
        self.query_one("#roadmap-detail", Static).update(roadmap_detail(self.project_dir, self.items[index]))

    # ----- events -----

    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        wid = event.option_list.id
        if wid == "phases":
            phase = self._phase_at(event.option_index)
            if phase and phase.get("id") != self.selected_phase:
                self.selected_task = None
            self.focus_on = "phase"
            self._show_phase(phase)
        elif wid == "tasks":
            oid = event.option.id or ""
            if oid.startswith("task:"):
                self.selected_task = oid[5:]
                if self.focused is event.option_list:
                    self.focus_on = "task"
                    self._show_task_detail(self._current_task() or {})
        elif wid == "workstream-list":
            self._show_workstream(event.option_index)
        elif wid == "roadmap-list":
            self._show_item(event.option_index)

    def on_descendant_focus(self, event) -> None:
        if getattr(event.widget, "id", None) == "tasks" and self._current_task():
            self.focus_on = "task"
            self._show_task_detail(self._current_task())
        elif getattr(event.widget, "id", None) == "phases":
            self.focus_on = "phase"
            phase = self._phase_at(self.query_one("#phases", OptionList).highlighted)
            if phase:
                self._show_phase_detail(phase, bool(phase_tasks(self.plan, phase)))

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option_list.id == "workstream-list":
            self.show_workstream_plan(self.workstream_rows[event.option_index]["id"])
        elif event.option_list.id == "phases":
            self.query_one("#tasks", OptionList).focus()

    # ----- actions -----

    def show_workstream_plan(self, wid: str) -> None:
        """Show another workstream's plan in the Plan tab (reading it only; the current one doesn't change)."""
        self.workstream = wid
        self.selected_phase = self.selected_task = None
        self.focus_on = "phase"
        self.reload()
        self.action_tab("plan")

    def action_tab(self, tab: str) -> None:
        self.tab = tab
        for key, _ in TABS:
            self.query_one(f"#tab-{key}").styles.display = "block" if key == tab else "none"
        self.query_one("#gp-tabs", Static).update(tab_strip(tab))
        self.query_one(KeyBar).show_dashboard(KEYS[tab])
        first = {"plan": "#phases", "workstreams": "#workstream-list", "roadmap": "#roadmap-list"}[tab]
        self.query_one(first, OptionList).focus()

    def action_column(self, step: int) -> None:
        if self.tab != "plan":
            return
        order = ["#phases", "#tasks"]
        now = "#tasks" if getattr(self.focused, "id", None) == "tasks" else "#phases"
        target = order[max(0, min(1, order.index(now) + step))]
        self.query_one(target, OptionList).focus()

    def action_cursor(self, direction: str) -> None:
        if isinstance(self.focused, OptionList):
            getattr(self.focused, f"action_cursor_{direction}")()

    def action_back(self) -> None:
        self.app.pop_screen()

    def action_explain(self) -> None:
        from ..cards import PANEL_CARDS

        name = CARDS[self.tab]
        self.app.push_screen(ExplainCard(PANEL_CARDS.get(name, name)))

    def _selected_edict(self) -> Optional[str]:
        if self.tab != "plan":
            return None
        if self.focus_on == "task" and self._current_task():
            return self._current_task().get("edict") or None
        phase = next((p for p in self.phases if p.get("id") == self.selected_phase), None)
        return (phase or {}).get("edict") or None

    def action_edict(self) -> None:
        number = self._selected_edict()
        if not number:
            self.notify("Nothing selected cites an edict.")
            return
        from .edicts import EdictsScreen

        self.app.push_screen(EdictsScreen(self.app, select=str(number).zfill(4)))

    def send_target(self) -> tuple[str, str]:
        """(source, prompt) for Send to Claude from the current selection."""
        wid = self.workstream or "the current"
        if self.tab == "workstreams":
            ol = self.query_one("#workstream-list", OptionList)
            if ol.highlighted is not None and self.workstream_rows:
                r = self.workstream_rows[ol.highlighted]
                return (f"Workstream {r['id']}",
                        f"Look at workstream {r['id']} (`daedalus workstream show {r['id']}`): its plan, claims and "
                        "any collisions. Tell me what needs attention and propose changes; don't make them yet.")
            return ("Workstreams", "Explain this project's workstreams and whether it needs more than one.")
        if self.tab == "roadmap":
            ol = self.query_one("#roadmap-list", OptionList)
            if ol.highlighted is not None and self.items:
                i = self.items[ol.highlighted]
                return (f"Roadmap item {str(i.get('id'))[:8]}",
                        f"Read roadmap item {i.get('id')} (`daedalus roadmap show {str(i.get('id'))[:8]}`): "
                        f"\"{i.get('title', '')}\". Propose where it belongs in the gameplan, as a phase or tasks. "
                        "Don't change the gameplan until I agree.")
            return ("Roadmap", "Help me fill the roadmap: what has been asked for in this project?")
        task = self._current_task() if self.focus_on == "task" else None
        if task:
            return (f"Task {task.get('id')}",
                    f"Look at task {task.get('id')} ({task.get('title', '')}) in {wid} workstream's gameplan. "
                    "Read its details and the gameplan first, then propose the next step or any change to it.")
        if self.selected_phase:
            return (f"Phase {self.selected_phase}",
                    f"Look at phase {self.selected_phase} in {wid} workstream's gameplan (`daedalus gameplan show`). "
                    "Propose any changes to its tasks or status; don't make them until I agree.")
        return ("Gameplan", "Help me start a gameplan for this project: propose the first phase and its tasks.")

    def action_send(self) -> None:
        source, prompt = self.send_target()
        self.app.ask_to_send(source, prompt)
