"""
Gameplan data layer.

A gameplan is a compaction-survival planning layer that sits above
individual roadmap items. It groups items into phases and breaks the
currently active phase into concrete tasks with a sequencing narrative.

Storage: .daedalus/roadmap/gameplan.json

Schema:
  {
    "description": "...",
    "phases": [
      {
        "id": "phase-slug",
        "title": "...",
        "status": "planned" | "in_progress" | "done",
        "roadmapItems": ["<item_id>", ...],   # references by id
        "notes": "...",
        "edict": "NNNN"                        # optional: the edict this phase implements
      }
    ],
    "activePhase": {
      "id": "phase-slug",
      "title": "...",
      "started": "YYYY-MM-DD",
      "goal": "...",
      "sequencing": "...",
      "tasks": [
        {
          "id": "task-slug",
          "title": "...",
          "status": "pending" | "in_progress" | "done",
          "details": "...",
          "edict": "NNNN",      # optional: the edict this task implements
          "updated": "YYYY-MM-DD",  # last status change
          "resolution": "..."   # only when done
        }
      ],
      "deferred": []
    } | null
  }
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Optional

GAMEPLAN_FILENAME = "gameplan.json"
PHASE_STATUSES = ("planned", "in_progress", "done")
TASK_STATUSES = ("pending", "in_progress", "done")

DEFAULT_DESCRIPTION = (
    "Multi-phase plans currently in flight. Each phase references roadmap "
    "item ids; the activePhase section breaks the current phase into "
    "concrete tasks with status. Survives conversation compactions — a "
    "fresh session can pick up by reading this file."
)


class GameplanError(Exception):
    """Raised for invalid gameplan operations."""


@dataclass
class GameplanPaths:
    roadmap_dir: Path
    gameplan_file: Path
    pending_file: Path = None  # type: ignore[assignment]
    workstream: str = "default"

    @classmethod
    def for_project(cls, project_dir: Path, workstream: Optional[str] = None) -> "GameplanPaths":
        """Paths for a workstream's plan (edict 0008); the current workstream when not given."""
        from .. import workstreams as ws

        project_dir = Path(project_dir)
        workstream = workstream or ws.current(project_dir)
        roadmap_dir = project_dir / ".daedalus" / "roadmap"
        gameplan_file = ws.file_for(project_dir, workstream)
        pending = roadmap_dir / PENDING_FILENAME if workstream == ws.DEFAULT \
            else ws.gameplans_dir(project_dir) / f"{workstream}.pending.json"
        return cls(roadmap_dir=roadmap_dir, gameplan_file=gameplan_file, pending_file=pending,
                   workstream=workstream)


def empty_gameplan() -> dict[str, Any]:
    return {
        "description": DEFAULT_DESCRIPTION,
        "phases": [],
        "activePhase": None,
    }


def load_gameplan(project_dir: Path, workstream: Optional[str] = None) -> dict[str, Any]:
    paths = GameplanPaths.for_project(project_dir, workstream)
    if not paths.gameplan_file.exists():
        hint = "Run: daedalus init" if paths.workstream == "default" \
            else f"Run: daedalus workstream new {paths.workstream}"
        raise GameplanError(f"No gameplan found at {paths.gameplan_file}. {hint}")
    try:
        return json.loads(paths.gameplan_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise GameplanError(f"{paths.gameplan_file} is not valid JSON: {e}")


def save_gameplan(project_dir: Path, data: dict[str, Any], workstream: Optional[str] = None) -> None:
    paths = GameplanPaths.for_project(project_dir, workstream)
    paths.gameplan_file.parent.mkdir(parents=True, exist_ok=True)
    paths.gameplan_file.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def ensure_gameplan(project_dir: Path, force: bool = False) -> bool:
    """Create an empty default gameplan if missing. Returns True if created."""
    paths = GameplanPaths.for_project(project_dir, "default")
    if paths.gameplan_file.exists() and not force:
        return False
    paths.roadmap_dir.mkdir(parents=True, exist_ok=True)
    save_gameplan(project_dir, empty_gameplan(), "default")
    return True


# ---------- phase operations ----------


def find_phase(data: dict[str, Any], phase_id: str) -> Optional[dict[str, Any]]:
    for phase in data.get("phases", []):
        if phase.get("id") == phase_id:
            return phase
    return None


def add_phase(
    data: dict[str, Any],
    phase_id: str,
    title: str,
    roadmap_items: Optional[list[str]] = None,
    notes: str = "",
    status: str = "planned",
    edict: str = "",
) -> dict[str, Any]:
    if status not in PHASE_STATUSES:
        raise GameplanError(f"Invalid phase status: {status}. Use one of {PHASE_STATUSES}")
    if find_phase(data, phase_id):
        raise GameplanError(f"Phase '{phase_id}' already exists")
    phase = {
        "id": phase_id,
        "title": title,
        "status": status,
        "roadmapItems": roadmap_items or [],
        "notes": notes,
    }
    if edict:
        phase["edict"] = edict
    data.setdefault("phases", []).append(phase)
    return phase


def set_phase_status(data: dict[str, Any], phase_id: str, status: str) -> dict[str, Any]:
    if status not in PHASE_STATUSES:
        raise GameplanError(f"Invalid phase status: {status}. Use one of {PHASE_STATUSES}")
    phase = find_phase(data, phase_id)
    if not phase:
        raise GameplanError(f"Phase '{phase_id}' not found")
    phase["status"] = status
    return phase


def activate_phase(
    data: dict[str, Any],
    phase_id: str,
    goal: str = "",
    sequencing: str = "",
    started: Optional[str] = None,
) -> dict[str, Any]:
    phase = find_phase(data, phase_id)
    if not phase:
        raise GameplanError(f"Phase '{phase_id}' not found")
    phase["status"] = "in_progress"
    data["activePhase"] = {
        "id": phase["id"],
        "title": phase["title"],
        "started": started or date.today().isoformat(),
        "goal": goal,
        "sequencing": sequencing,
        # Tasks queued on the phase while it was planned (from a source, edict 0011) become its tasks
        "tasks": [t for t in (phase.pop("tasks", None) or []) if isinstance(t, dict)],
        "deferred": [],
    }
    if phase.get("edict"):
        data["activePhase"]["edict"] = phase["edict"]
    return data["activePhase"]


def clear_active_phase(data: dict[str, Any]) -> None:
    data["activePhase"] = None


# ---------- task operations ----------


def _require_active(data: dict[str, Any]) -> dict[str, Any]:
    active = data.get("activePhase")
    if not active:
        raise GameplanError("No active phase. Run: daedalus gameplan phase activate <id>")
    return active


def find_task(data: dict[str, Any], task_id: str) -> Optional[dict[str, Any]]:
    active = data.get("activePhase")
    if not active:
        return None
    for task in active.get("tasks", []):
        if task.get("id") == task_id:
            return task
    return None


def add_task(
    data: dict[str, Any],
    task_id: str,
    title: str,
    details: str = "",
    status: str = "pending",
    edict: str = "",
) -> dict[str, Any]:
    if status not in TASK_STATUSES:
        raise GameplanError(f"Invalid task status: {status}. Use one of {TASK_STATUSES}")
    active = _require_active(data)
    if find_task(data, task_id):
        raise GameplanError(f"Task '{task_id}' already exists in active phase")
    task = {
        "id": task_id,
        "title": title,
        "status": status,
        "details": details,
        "updated": date.today().isoformat(),
    }
    if edict:
        task["edict"] = edict
    active.setdefault("tasks", []).append(task)
    return task


def set_task_status(
    data: dict[str, Any],
    task_id: str,
    status: str,
    resolution: str = "",
) -> dict[str, Any]:
    if status not in TASK_STATUSES:
        raise GameplanError(f"Invalid task status: {status}. Use one of {TASK_STATUSES}")
    task = find_task(data, task_id)
    if not task:
        raise GameplanError(f"Task '{task_id}' not found in active phase")
    task["status"] = status
    task["updated"] = date.today().isoformat()
    if status == "done" and resolution:
        task["resolution"] = resolution
    return task


def defer_task(data: dict[str, Any], task_id: str, reason: str = "") -> dict[str, Any]:
    active = _require_active(data)
    task = find_task(data, task_id)
    if not task:
        raise GameplanError(f"Task '{task_id}' not found in active phase")
    active["tasks"] = [t for t in active["tasks"] if t.get("id") != task_id]
    entry = {"id": task["id"], "title": task["title"], "reason": reason}
    active.setdefault("deferred", []).append(entry)
    return entry


# ---------- pending proposals (edict 0007) ----------
#
# Hooks never edit the gameplan. They write proposals here; a human or a session applies or
# drops each one with `daedalus gameplan pending apply|drop`.

PENDING_FILENAME = "pending.json"

# Proposal kinds. A proposal without "kind" is a task-status change (the capture hook's shape).
#   task-status:    {"task", "status", "resolution"}
#   new-phase:      {"phase": {"id", "title", "status", "notes", "tasks": [...], ...}}
#   roadmap-status: {"item", "status"}
#   new-task:       {"task", "title", "details", ["phase", "origin", "roadmapItem"]} (reflection, sources)
# From sources (edict 0011), each carrying "origin": {"source", "external_id", "url"}:
#   roadmap-new:    {"item": {<the new roadmap item>}, "synced": {...}}
#   roadmap-update: {"item": <id>, "changes": {field: value}, "conflicts": {...}, "synced": {...}}
#   write-back:     {"task", "item", "target": "task" | "item", "comment"}
PROPOSAL_KINDS = ("task-status", "new-phase", "roadmap-status", "new-task",
                  "roadmap-new", "roadmap-update", "write-back")
# Kinds whose proposals carry commits: a newer one replaces a pending one only when it brings new commits
COMMIT_KINDS = ("task-status", "new-phase", "roadmap-status")
# Kinds a source makes whose drop is remembered, so a re-sync doesn't bring them back
SOURCE_DROP_KINDS = ("roadmap-new", "roadmap-update", "write-back", "new-phase", "new-task")


def proposal_kind(proposal: dict[str, Any]) -> str:
    kind = proposal.get("kind", "task-status")
    if kind not in PROPOSAL_KINDS:
        raise GameplanError(f"Unknown proposal kind {kind!r} (known: {', '.join(PROPOSAL_KINDS)})")
    return kind


def _src_key(proposal: dict[str, Any]) -> str:
    o = proposal["origin"]
    return f"src:{o['source']}:{o['external_id']}"


def proposal_key(proposal: dict[str, Any]) -> str:
    kind = proposal_kind(proposal)
    if kind == "task-status":
        return f"task:{proposal['task']}"
    if kind == "new-phase":
        return f"phase:{proposal['phase']['id']}"
    if kind == "roadmap-status":
        return f"roadmap:{proposal['item']}"
    if kind == "new-task":
        return _src_key(proposal) if proposal.get("origin") else f"new-task:{proposal['task']}"
    if kind in ("roadmap-new", "roadmap-update"):
        return _src_key(proposal)
    if kind == "write-back":
        o = proposal["origin"]
        return f"wb:{o['source']}:{o['external_id']}:{proposal['task']}"
    raise GameplanError(f"Unknown proposal kind {kind!r}")


def describe_proposal(proposal: dict[str, Any]) -> str:
    kind = proposal_kind(proposal)
    if kind == "task-status":
        return f"{proposal['task']} -> {proposal['status']}"
    if kind == "new-phase":
        ph = proposal["phase"]
        return f"new phase {ph['id']} ({ph.get('status', 'planned')}, {len(ph.get('tasks', []))} tasks): {ph.get('title', '')}"
    if kind == "roadmap-status":
        return f"roadmap {proposal['item']} -> {proposal['status']}"
    if kind == "new-task":
        where = f" in {proposal['phase']}" if proposal.get("phase") else ""
        return f"new task {proposal['task']}{where}: {proposal.get('title', '')}"
    if kind == "roadmap-new":
        item = proposal["item"]
        return f"new roadmap item {item['id']} ({item.get('status', 'backlog')}): {item.get('title', '')}"
    if kind == "roadmap-update":
        changes = ", ".join(f"{k} -> {_short(v)}" for k, v in proposal.get("changes", {}).items())
        conflict = " [changed here too: " + ", ".join(proposal["conflicts"]) + "]" if proposal.get("conflicts") else ""
        return f"roadmap {proposal['item']} from {proposal['origin']['source']}: {changes}{conflict}"
    if kind == "write-back":
        o = proposal["origin"]
        extra = " with a comment" if proposal.get("comment") else ""
        return f"write back to {o['source']} {o['external_id']}: done{extra} (task {proposal['task']})"
    raise GameplanError(f"Unknown proposal kind {kind!r}")


def _short(value: Any, width: int = 40) -> str:
    text = str(value).replace("\n", " ")
    return text if len(text) <= width else text[:width - 1] + "…"


def pending_path(project_dir: Path) -> Path:
    return GameplanPaths.for_project(project_dir).pending_file


def load_pending(project_dir: Path) -> list[dict[str, Any]]:
    path = pending_path(project_dir)
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("proposals", [])
    except (json.JSONDecodeError, AttributeError):
        return []


def save_pending(project_dir: Path, proposals: list[dict[str, Any]]) -> None:
    path = pending_path(project_dir)
    if not proposals:
        if path.exists():
            path.unlink()
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"proposals": proposals}, indent=2) + "\n", encoding="utf-8")


def add_proposals(project_dir: Path, new: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Merge proposals into the pending file. A proposal for a task that already has one replaces it
    when it brings commits the old one didn't have; otherwise it is skipped. Returns what was added.
    """
    proposals = load_pending(project_dir)
    by_key = {}
    for p in proposals:
        try:
            by_key[proposal_key(p)] = p
        except (GameplanError, KeyError, TypeError):
            continue  # an entry this version doesn't know; left alone (drop it with `pending drop`)
    next_num = max((int(p["id"][1:]) for p in proposals if p.get("id", "")[1:].isdigit()), default=0) + 1
    added = []
    for proposal in new:
        old = by_key.get(proposal_key(proposal))
        if old and proposal_kind(proposal) in COMMIT_KINDS:
            if set(proposal.get("commits", [])) <= set(old.get("commits", [])):
                continue
        elif old and _same_content(old, proposal):
            continue
        if old:
            proposal["id"] = old["id"]
            proposals[proposals.index(old)] = proposal
        else:
            proposal["id"] = f"P{next_num}"
            next_num += 1
            proposals.append(proposal)
        by_key[proposal_key(proposal)] = proposal
        added.append(proposal)
    save_pending(project_dir, proposals)
    return added


def _same_content(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """Whether two proposals say the same thing (ignoring id and creation date)."""
    strip = lambda p: {k: v for k, v in p.items() if k not in ("id", "created")}  # noqa: E731
    return strip(a) == strip(b)


def _select(proposals: list[dict[str, Any]], which: str) -> list[dict[str, Any]]:
    chosen = proposals if which == "all" else [p for p in proposals if p.get("id") == which]
    if not chosen:
        raise GameplanError(f"No pending proposal '{which}'")
    return chosen


def apply_pending(project_dir: Path, data: dict[str, Any], which: str,
                  failures: Optional[list] = None) -> list[dict[str, Any]]:
    """Apply proposals (an id or 'all') to the gameplan data; removes them from the pending file.

    Write-backs go first, one at a time, because each calls the outside tracker: one that fails stays
    pending, and is added to `failures` as (proposal, error) when a list is given (otherwise the error
    is raised). Every kind is handled explicitly; an unknown kind raises before anything changes.
    """
    proposals = load_pending(project_dir)
    chosen = _select(proposals, which)
    for p in chosen:
        proposal_kind(p)  # raises on an unknown kind, before anything is applied
    from .. import undo

    undo.begin(project_dir, None, chosen)  # the before state, so the apply can be undone (sealed after the save)
    applied: list[dict[str, Any]] = []
    from ..sources import sync as source_sync

    for p in [p for p in chosen if proposal_kind(p) == "write-back"]:
        try:
            source_sync.apply_write_back(project_dir, data, p)
        except Exception as e:  # SourceError, or a plugin that isn't installed
            if failures is None:
                raise GameplanError(f"{p.get('id')}: write-back failed: {e}")
            failures.append((p, str(e)))
            continue
        applied.append(p)
    if applied:
        # The outside call happened: record it and take it off the pending list now, whatever happens next
        save_gameplan(project_dir, data)
        save_pending(project_dir, [p for p in proposals if p not in applied])
    # The local part is all or nothing: a failure partway restores the roadmap index and raises, so the
    # gameplan isn't saved and every local proposal stays pending as it was.
    from .. import roadmap as rm

    index_file = rm.index_path(project_dir)
    index_before = index_file.read_bytes() if index_file.exists() else None
    try:
        done_tasks = _apply_local(project_dir, data, chosen, applied)
    except Exception:
        if index_before is None:
            index_file.unlink(missing_ok=True)
        else:
            index_file.write_bytes(index_before)
        raise
    save_pending(project_dir, [p for p in proposals if p not in applied])
    for task in done_tasks:
        source_sync.propose_write_back(project_dir, data, task)
    return applied


def _apply_local(project_dir: Path, data: dict[str, Any], chosen: list, applied: list) -> list:
    from ..sources import sync as source_sync

    roadmap_changes = []
    done_tasks = []
    for p in chosen:
        kind = proposal_kind(p)
        if kind == "write-back":
            continue
        if kind == "new-phase":
            spec = p["phase"]
            phase = add_phase(data, spec["id"], spec["title"], notes=spec.get("notes", ""),
                              status=spec.get("status", "planned"), edict=spec.get("edict", ""))
            for key in ("goal", "dates", "tasks", "provenance", "origin"):
                if spec.get(key):
                    phase[key] = spec[key]
            if spec.get("roadmapItems"):
                phase["roadmapItems"] = list(spec["roadmapItems"])
        elif kind == "roadmap-status":
            roadmap_changes.append(p)
        elif kind == "new-task":
            # From reflection (edict 0010): new work a pattern in the session logs calls for. From a source
            # (edict 0011): a tracker's task, placed in the phase that references its parent's item.
            _apply_new_task(data, p)
        elif kind in ("roadmap-new", "roadmap-update"):
            source_sync.apply_roadmap_proposal(project_dir, data, p)
        elif kind == "task-status":
            task = set_task_status(data, p["task"], p["status"], resolution=p.get("resolution", ""))
            if p["status"] == "done":
                done_tasks.append(task)
        else:  # proposal_kind() already refused unknown kinds; this keeps a new kind from falling through
            raise GameplanError(f"No handler for proposal kind {kind!r}")
        applied.append(p)
    if roadmap_changes:
        _apply_roadmap_status(project_dir, roadmap_changes)
    return done_tasks


def _apply_new_task(data: dict[str, Any], p: dict[str, Any]) -> dict[str, Any]:
    extra = {k: p[k] for k in ("origin", "roadmapItem") if p.get(k)}
    active = data.get("activePhase") or {}
    if p.get("phase") and p["phase"] != active.get("id"):
        phase = find_phase(data, p["phase"])
        if phase is None:
            raise GameplanError(f"Phase '{p['phase']}' not found for task {p['task']}")
        if any(t.get("id") == p["task"] for t in phase.get("tasks", []) if isinstance(t, dict)):
            raise GameplanError(f"Task '{p['task']}' already exists in phase {p['phase']}")
        task = {"id": p["task"], "title": p.get("title", ""), "status": "pending", "details": p.get("details", ""),
                "updated": date.today().isoformat(), **extra}
        phase.setdefault("tasks", []).append(task)
        return task
    task = add_task(data, p["task"], p.get("title", ""), details=p.get("details", ""))
    task.update(extra)
    return task


def _apply_roadmap_status(project_dir: Path, changes: list[dict[str, Any]]) -> None:
    from datetime import datetime

    path = GameplanPaths.for_project(project_dir).roadmap_dir / "index.json"
    if not path.exists():
        raise GameplanError(f"No roadmap at {path}")
    roadmap = json.loads(path.read_text(encoding="utf-8"))
    items = {i.get("id"): i for i in roadmap.get("items", [])}
    for change in changes:
        item = items.get(change["item"])
        if item is None:
            raise GameplanError(f"Roadmap item '{change['item']}' not found")
    for change in changes:
        items[change["item"]]["status"] = change["status"]
        items[change["item"]]["status_changed_at"] = datetime.now().isoformat(timespec="seconds")
    path.write_text(json.dumps(roadmap, indent=2) + "\n", encoding="utf-8")


def proposals_from_reconstruction(reconstruction: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    """
    Turn a reconstruction proposal (edict 0006) into pending proposals.

    Returns (proposals, skipped). needs-confirmation updates are not imported: they are questions
    with a cheapest check, for a person to settle first.
    """
    today = date.today().isoformat()
    source = "reconstruction"
    proposals, skipped = [], []

    def label(entry):
        return f"[reconstructed; {entry.get('confidence')}, from {entry.get('basis', 'no evidence')}]"

    for u in reconstruction.get("updates", []):
        if u.get("proposed_status") == "needs-confirmation":
            skipped.append(f"{u.get('task')}: needs confirmation ({u.get('cheapest_check', '')})")
            continue
        proposals.append({
            "task": u["task"], "status": u["proposed_status"],
            "resolution": f"{u.get('resolution') or ''} {label(u)}".strip(),
            "commits": u.get("commits", []), "source": source, "created": today,
        })
    for ph in reconstruction.get("phases", []):
        tasks = [
            {"id": t.get("id"), "title": t.get("title"), "status": t.get("status"),
             **({"resolution": t["resolution"]} if t.get("resolution") else {}),
             "provenance": label(t)}
            for t in ph.get("tasks", [])
        ]
        proposals.append({
            "kind": "new-phase",
            "phase": {"id": ph["id"], "title": ph["title"], "status": ph.get("status", "done"),
                      "notes": f"{ph.get('notes') or ph.get('goal') or ''} {label(ph)}".strip(),
                      "goal": ph.get("goal", ""), "dates": ph.get("dates", ""), "tasks": tasks,
                      "provenance": label(ph)},
            "commits": ph.get("commits", []), "source": source, "created": today,
        })
    for r in reconstruction.get("roadmap", []):
        proposals.append({
            "kind": "roadmap-status", "item": r["item"], "status": r["proposed_status"],
            "resolution": f"was {r.get('current_status')} {label(r)}",
            "commits": r.get("commits", []), "source": source, "created": today,
        })
    return proposals, skipped


def drop_pending(project_dir: Path, which: str, why: Optional[str] = None) -> list[dict[str, Any]]:
    """Discard proposals. Dropping a source's proposal is remembered so the next sync doesn't bring it
    back: a dropped update keeps the local values (its remote values become the baseline), and a dropped
    write-back is recorded as `dropped` (doctor then knows it wasn't forgotten). Nothing is called."""
    proposals = load_pending(project_dir)
    chosen = _select(proposals, which)
    if any(p.get("kind") in ("roadmap-update", "write-back") or p.get("origin") for p in chosen):
        from ..sources import sync as source_sync

        source_sync.record_drops(project_dir, [p for p in chosen if p.get("kind") in SOURCE_DROP_KINDS])
    from .. import epitaphs

    epitaphs.record(project_dir, chosen, why)  # dropped intake keeps a one-line epitaph
    save_pending(project_dir, [p for p in proposals if p not in chosen])
    return chosen
