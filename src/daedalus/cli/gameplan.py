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

    @classmethod
    def for_project(cls, project_dir: Path) -> "GameplanPaths":
        roadmap_dir = project_dir / ".daedalus" / "roadmap"
        return cls(roadmap_dir=roadmap_dir, gameplan_file=roadmap_dir / GAMEPLAN_FILENAME)


def empty_gameplan() -> dict[str, Any]:
    return {
        "description": DEFAULT_DESCRIPTION,
        "phases": [],
        "activePhase": None,
    }


def load_gameplan(project_dir: Path) -> dict[str, Any]:
    paths = GameplanPaths.for_project(project_dir)
    if not paths.gameplan_file.exists():
        raise GameplanError(
            f"No gameplan found at {paths.gameplan_file}. Run: daedalus init"
        )
    return json.loads(paths.gameplan_file.read_text(encoding="utf-8"))


def save_gameplan(project_dir: Path, data: dict[str, Any]) -> None:
    paths = GameplanPaths.for_project(project_dir)
    paths.roadmap_dir.mkdir(parents=True, exist_ok=True)
    paths.gameplan_file.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def ensure_gameplan(project_dir: Path, force: bool = False) -> bool:
    """Create an empty gameplan if missing. Returns True if created."""
    paths = GameplanPaths.for_project(project_dir)
    if paths.gameplan_file.exists() and not force:
        return False
    paths.roadmap_dir.mkdir(parents=True, exist_ok=True)
    save_gameplan(project_dir, empty_gameplan())
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
        "tasks": [],
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


def pending_path(project_dir: Path) -> Path:
    return GameplanPaths.for_project(project_dir).roadmap_dir / PENDING_FILENAME


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
    by_task = {p.get("task"): p for p in proposals}
    next_num = max((int(p["id"][1:]) for p in proposals if p.get("id", "")[1:].isdigit()), default=0) + 1
    added = []
    for proposal in new:
        old = by_task.get(proposal["task"])
        if old and set(proposal.get("commits", [])) <= set(old.get("commits", [])):
            continue
        if old:
            proposal["id"] = old["id"]
            proposals[proposals.index(old)] = proposal
        else:
            proposal["id"] = f"P{next_num}"
            next_num += 1
            proposals.append(proposal)
        by_task[proposal["task"]] = proposal
        added.append(proposal)
    save_pending(project_dir, proposals)
    return added


def _select(proposals: list[dict[str, Any]], which: str) -> list[dict[str, Any]]:
    chosen = proposals if which == "all" else [p for p in proposals if p.get("id") == which]
    if not chosen:
        raise GameplanError(f"No pending proposal '{which}'")
    return chosen


def apply_pending(project_dir: Path, data: dict[str, Any], which: str) -> list[dict[str, Any]]:
    """Apply proposals (an id or 'all') to the gameplan data; removes them from the pending file."""
    proposals = load_pending(project_dir)
    chosen = _select(proposals, which)
    for p in chosen:
        set_task_status(data, p["task"], p["status"], resolution=p.get("resolution", ""))
    save_pending(project_dir, [p for p in proposals if p not in chosen])
    return chosen


def drop_pending(project_dir: Path, which: str) -> list[dict[str, Any]]:
    proposals = load_pending(project_dir)
    chosen = _select(proposals, which)
    save_pending(project_dir, [p for p in proposals if p not in chosen])
    return chosen
