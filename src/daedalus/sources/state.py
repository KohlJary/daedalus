"""
Per-machine sync state: when each source last synced, how it went, and how many items it has.

Stored in `.daedalus/sources/state.json`, which stays local like the rest of `.daedalus/`. The
session-start brief and doctor read it; neither touches the network.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def path(project_dir: Path) -> Path:
    return Path(project_dir) / ".daedalus" / "sources" / "state.json"


def load(project_dir: Path) -> dict[str, dict[str, Any]]:
    p = path(project_dir)
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def record(project_dir: Path, name: str, **fields: Any) -> dict[str, Any]:
    data = load(project_dir)
    entry = data.setdefault(name, {})
    entry.update(fields)
    p = path(project_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return entry


def brief_line(project_dir: Path) -> str:
    """One line for the session-start brief: each source's last sync, or '' when none has synced."""
    data = load(project_dir)
    parts = []
    for name in sorted(data):
        entry = data[name]
        when = entry.get("last_sync") or "never"
        health = entry.get("health")
        parts.append(f"{name} {when}" + (f" ({health})" if health and health != "ok" else ""))
    return ("Sources last synced: " + "; ".join(parts)) if parts else ""
