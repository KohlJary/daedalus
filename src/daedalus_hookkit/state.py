"""
Per-session hook state (edict 0016): <cache>/hooks/<session_id>.json, written atomically.

The shape is shared with the TUI (edict 0012), which reads it through `daedalus.hookstate.load`:

    {"session_id", "started_at",
     "events": [{"at", "hook", "event", "nudge", "followed", "tool"}],   # plus "dropped": true when over budget
     "gate": {"blocks", "passes", "skips", "allowed_by_error"},
     "budget": {"per_hour", "used"},
     ...}                                                               # features keep their own keys

`followed` is null until known. Features may add their own top-level keys (files edited, PRs created,
compaction times). Files older than STATE_DAYS are pruned at session start.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from . import paths

STATE_DAYS = 7
MAX_EVENTS = 500


def state_dir() -> Path:
    return paths.cache_dir() / "hooks"


def _safe(session_id: str) -> str:
    return "".join(c for c in session_id if c.isalnum() or c in "-_") or "unknown"


def state_path(session_id: str) -> Path:
    return state_dir() / f"{_safe(session_id)}.json"


def empty(session_id: str, now: float) -> dict:
    return {
        "session_id": session_id,
        "started_at": now,
        "events": [],
        "gate": {"blocks": 0, "passes": 0, "skips": 0, "allowed_by_error": 0},
        "budget": {"per_hour": 0, "used": 0},
    }


def load(session_id: str, now: float | None = None) -> dict:
    now = time.time() if now is None else now
    try:
        data = json.loads(state_path(session_id).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return empty(session_id, now)
    if not isinstance(data, dict):
        return empty(session_id, now)
    base = empty(session_id, now)
    for key, value in base.items():
        if not isinstance(data.get(key), type(value)):
            data[key] = value
    return data


def save(state: dict) -> None:
    """Write atomically: a temp file in the same directory, then a rename."""
    import tempfile

    path = state_path(str(state.get("session_id", "")))
    path.parent.mkdir(parents=True, exist_ok=True)
    state["events"] = state["events"][-MAX_EVENTS:]
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(state, f)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def prune(now: float | None = None) -> None:
    now = time.time() if now is None else now
    try:
        for p in state_dir().glob("*.json"):
            if now - p.stat().st_mtime > STATE_DAYS * 86400:
                p.unlink()
    except OSError:
        pass
