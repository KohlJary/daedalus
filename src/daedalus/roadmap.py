"""
The roadmap as committed intake (edict 0011).

Everything that has been asked for, from any source, lives in `.daedalus/roadmap/index.json`: ideas
and bugs typed in locally, and items a source brought in from an outside tracker. The gameplan is
the plan; its phases pull roadmap items in by id (`roadmapItems`) and its tasks point back at one
(`roadmapItem`).

Each item records where it came from: `origin: {"source", "external_id", "url"}` for a sourced
item, `{"source": "local"}` for one typed in here (an item without `origin` is local). A sourced
item also keeps `synced`: the fields its source owns as the last sync saw them, which is the
baseline a conflict is measured against.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Optional

STATUSES = ("backlog", "ready", "in_progress", "review", "done")
LOCAL = {"source": "local"}


class RoadmapError(Exception):
    pass


def index_path(project_dir: Path) -> Path:
    return Path(project_dir) / ".daedalus" / "roadmap" / "index.json"


def load_index(project_dir: Path) -> dict[str, Any]:
    """The roadmap index; an empty one when the file is missing."""
    path = index_path(project_dir)
    if not path.exists():
        return {"items": [], "version": 1}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise RoadmapError(f"{path} is not valid JSON: {e}")
    if isinstance(data, list):
        # Ariadne's tracker writes the index as a bare list of item summaries
        data = {"items": data, "version": 1}
    if not isinstance(data, dict):
        raise RoadmapError(f"{path} isn't a roadmap index (expected an object with \"items\")")
    data.setdefault("items", [])
    return data


def save_index(project_dir: Path, data: dict[str, Any]) -> None:
    path = index_path(project_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def origin(item: dict[str, Any]) -> dict[str, Any]:
    o = item.get("origin")
    return o if isinstance(o, dict) and o.get("source") else dict(LOCAL)


def is_sourced(item: dict[str, Any]) -> bool:
    return origin(item)["source"] != "local"


def origin_label(item: dict[str, Any]) -> str:
    o = origin(item)
    if o["source"] == "local":
        return "local"
    return f"{o['source']} {o.get('external_id', '')}".strip()


def item_id_for(source: str, external_id: str) -> str:
    """The roadmap id a sourced item gets: stable, so a phase can list it before it is applied."""
    return re.sub(r"[^A-Za-z0-9._-]+", "-", f"{source}-{external_id}")


def find(data: dict[str, Any], item_id: str) -> dict[str, Any]:
    """An item by id or unique id prefix (list shows the first 8 characters)."""
    items = data.get("items", [])
    for item in items:
        if item.get("id") == item_id:
            return item
    matches = [i for i in items if str(i.get("id", "")).startswith(item_id)]
    if len(matches) == 1:
        return matches[0]
    if matches:
        raise RoadmapError(f"'{item_id}' matches {len(matches)} items: "
                           + ", ".join(str(i.get("id")) for i in matches[:5]))
    raise RoadmapError(f"No roadmap item '{item_id}'")


def by_external(data: dict[str, Any], source: str) -> dict[str, dict[str, Any]]:
    """{external_id: item} for one source's items."""
    out = {}
    for item in data.get("items", []):
        o = origin(item)
        if o["source"] == source and o.get("external_id") is not None:
            out[str(o["external_id"])] = item
    return out


# ---------- where an item is used ----------


def _plans(project_dir: Path) -> dict[str, dict[str, Any]]:
    from . import workstreams as ws
    from .cli import gameplan as gp

    plans = {}
    for wid in ws.list_ids(project_dir):
        try:
            plans[wid] = gp.load_gameplan(project_dir, wid)
        except gp.GameplanError:
            continue
    return plans


def all_tasks(data: dict[str, Any]):
    """(phase_id, task) for the active phase's tasks and the tasks queued on other phases."""
    active = data.get("activePhase") or {}
    for task in active.get("tasks", []) or []:
        yield active.get("id"), task
    for phase in data.get("phases", []):
        if phase.get("id") == active.get("id"):
            continue
        for task in phase.get("tasks", []) or []:
            if isinstance(task, dict):
                yield phase.get("id"), task


def references(project_dir: Path, item_id: str) -> tuple[list[tuple], list[tuple]]:
    """(phases, tasks) that use an item, across workstreams: [(workstream, phase)], [(workstream, phase_id, task)]."""
    phases, tasks = [], []
    for wid, data in _plans(project_dir).items():
        for phase in data.get("phases", []):
            if item_id in (phase.get("roadmapItems") or []):
                phases.append((wid, phase))
        for phase_id, task in all_tasks(data):
            if task.get("roadmapItem") == item_id:
                tasks.append((wid, phase_id, task))
    return phases, tasks


def add_local_item(project_dir: Path, title: str, description: str = "", priority: str = "P2",
                   item_type: str = "task") -> dict[str, Any]:
    import uuid
    from datetime import datetime, timezone

    data = load_index(project_dir)
    item = {
        "id": str(uuid.uuid4()),
        "title": title,
        "description": description or "",
        "priority": priority,
        "item_type": item_type,
        "status": "backlog",
        "created_at": datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),
        "created_by": "daedalus",
        "origin": dict(LOCAL),
    }
    data["items"].append(item)
    save_index(project_dir, data)
    return item


def find_optional(data: dict[str, Any], item_id: Optional[str]) -> Optional[dict[str, Any]]:
    if not item_id:
        return None
    for item in data.get("items", []):
        if item.get("id") == item_id:
            return item
    return None
