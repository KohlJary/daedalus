"""
Undo an applied proposal (from the first dream, docs/dreams/2026-10-15.md, idea 25).

Applying a pending proposal changes the plan; until now that was one-way. Each apply now records what the
gameplan, the roadmap index and the pending file looked like before it, and (once the apply is saved)
what they looked like after. `daedalus gameplan pending undo` restores the before state, and the proposals
are pending again, but only:
- within a day of the apply;
- if nothing has changed those files since (their contents still match the recorded after state), so an
  undo never throws away later work;
- if the apply made no outside call: a write-back already reached the tracker, and undoing the local
  record would make it lie. Those are refused, and say so.

The journal lives in `.daedalus/undo/` (local) and keeps the last 20 applies.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

KEEP = 20
WINDOW = timedelta(days=1)


def folder(project_dir: Path) -> Path:
    return Path(project_dir) / ".daedalus" / "undo"


def _files(project_dir: Path, workstream: Optional[str]) -> dict[str, Path]:
    from .cli import gameplan as gp

    paths = gp.GameplanPaths.for_project(project_dir, workstream)
    return {"gameplan": paths.gameplan_file, "pending": paths.pending_file,
            "roadmap": Path(project_dir) / ".daedalus" / "roadmap" / "index.json"}


def _read(p: Path) -> Optional[str]:
    try:
        return p.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _hash(text: Optional[str]) -> Optional[str]:
    return None if text is None else hashlib.sha256(text.encode("utf-8")).hexdigest()


def begin(project_dir: Path, workstream: Optional[str], proposals: list[dict[str, Any]]) -> Path:
    """Record the before state of an apply. Returns the journal entry's path."""
    from . import workstreams as ws

    wid = workstream or ws.current(project_dir)
    stamp = datetime.now(timezone.utc)
    entry = {"at": stamp.isoformat(timespec="seconds"), "workstream": wid,
             "proposals": [p.get("id") for p in proposals],
             "outside_call": any(p.get("kind") == "write-back" for p in proposals),
             "before": {k: _read(v) for k, v in _files(project_dir, wid).items()}, "after": None}
    f = folder(project_dir)
    f.mkdir(parents=True, exist_ok=True)
    path = f / f"{stamp.strftime('%Y%m%dT%H%M%S%f')}.json"
    path.write_text(json.dumps(entry), encoding="utf-8")
    for old in sorted(f.glob("*.json"))[:-KEEP]:
        old.unlink(missing_ok=True)
    return path


def seal(project_dir: Path) -> None:
    """After the apply is saved: record the after state of the newest unsealed entry."""
    entries = sorted(folder(project_dir).glob("*.json")) if folder(project_dir).is_dir() else []
    for path in reversed(entries):
        entry = json.loads(path.read_text(encoding="utf-8"))
        if entry.get("after") is None:
            entry["after"] = {k: _hash(_read(v)) for k, v in _files(project_dir, entry["workstream"]).items()}
            path.write_text(json.dumps(entry), encoding="utf-8")
            return


def latest(project_dir: Path) -> Optional[tuple[Path, dict]]:
    entries = sorted(folder(project_dir).glob("*.json")) if folder(project_dir).is_dir() else []
    for path in reversed(entries):
        entry = json.loads(path.read_text(encoding="utf-8"))
        if entry.get("after") is not None and not entry.get("undone"):
            return path, entry
    return None


def undo(project_dir: Path, now: Optional[datetime] = None) -> dict:
    """Undo the newest apply. Raises ValueError saying why when it can't."""
    found = latest(project_dir)
    if found is None:
        raise ValueError("Nothing to undo: no applied proposal is recorded.")
    path, entry = found
    now = now or datetime.now(timezone.utc)
    if now - datetime.fromisoformat(entry["at"]) > WINDOW:
        raise ValueError(f"The last apply ({', '.join(entry['proposals'])}, {entry['at'][:16]}) is over a day old.")
    if entry.get("outside_call"):
        raise ValueError("The last apply wrote back to an outside tracker; undoing it here would leave the plan "
                         "saying something the tracker doesn't. Change it by hand if you need to.")
    files = _files(project_dir, entry["workstream"])
    changed = [k for k, p in files.items() if _hash(_read(p)) != entry["after"].get(k)]
    if changed:
        raise ValueError(f"The {', '.join(changed)} changed after that apply, so undoing it would lose later work.")
    for k, p in files.items():
        before = entry["before"].get(k)
        if before is None:
            p.unlink(missing_ok=True)
        else:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(before, encoding="utf-8")
    entry["undone"] = now.isoformat(timespec="seconds")
    path.write_text(json.dumps(entry), encoding="utf-8")
    return entry
