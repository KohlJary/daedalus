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
LOCK_WAIT = 2.0


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
        "budget_log": [],
        "fired": {},
        "dropped": {},
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


class locked:
    """An exclusive lock on a session's state, for the length of one dispatch. Yields whether it was had:
    after LOCK_WAIT seconds without it, the caller goes on without saving (a hook must never hang)."""

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.fd = None

    def __enter__(self) -> bool:
        if not self.session_id:
            return False
        try:
            state_dir().mkdir(parents=True, exist_ok=True)
            self.fd = os.open(str(state_path(self.session_id)) + ".lock", os.O_RDWR | os.O_CREAT, 0o600)
        except OSError:
            return False
        deadline = time.monotonic() + LOCK_WAIT
        while True:
            try:
                _lock(self.fd)
                return True
            except OSError:
                if time.monotonic() > deadline:
                    os.close(self.fd)
                    self.fd = None
                    return False
                time.sleep(0.005)

    def __exit__(self, *exc) -> None:
        if self.fd is not None:
            try:
                _unlock(self.fd)
            finally:
                os.close(self.fd)
                self.fd = None


def _lock(fd: int) -> None:
    if os.name == "nt":
        import msvcrt
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
    else:
        import fcntl
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock(fd: int) -> None:
    if os.name == "nt":
        import msvcrt
        os.lseek(fd, 0, 0)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    else:
        import fcntl
        fcntl.flock(fd, fcntl.LOCK_UN)


def prune(now: float | None = None) -> None:
    now = time.time() if now is None else now
    try:
        files = list(state_dir().glob("*.json"))
    except OSError:
        return
    for p in files:
        try:
            if now - p.stat().st_mtime > STATE_DAYS * 86400:
                p.unlink()
        except OSError:  # one locked or vanished file (Windows) doesn't stop the rest
            continue
    for lock in state_dir().glob("*.json.lock"):
        # a lock file goes only with its state (flock never touches mtime, so age says nothing)
        try:
            if not lock.with_suffix("").exists():
                lock.unlink()
        except OSError:
            continue


def heartbeat_path() -> Path:
    return state_dir() / "last-run.json"


def heartbeat(event: str, now: float) -> None:
    """Record that a dispatcher ran, so doctor can tell a registered hook that never runs (its command
    isn't on the PATH Claude Code uses) from one that does."""
    path = heartbeat_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        data = data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        data = {}
    if now - float(data.get(event, 0) or 0) < 3600:
        return
    data[event] = now
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps(data), encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        pass
