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
        "notes": "..."
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
    return json.loads(paths.gameplan_file.read_text())


def save_gameplan(project_dir: Path, data: dict[str, Any]) -> None:
    paths = GameplanPaths.for_project(project_dir)
    paths.roadmap_dir.mkdir(parents=True, exist_ok=True)
    paths.gameplan_file.write_text(json.dumps(data, indent=2) + "\n")


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
    }
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
