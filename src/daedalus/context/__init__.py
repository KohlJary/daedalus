"""
The context map (edict 0015): how big the context is and what fills it, by subject and by task.

Library functions for the TUI (0012) and the CLI; `daedalus context --json` prints the same dict as
`measure`. Every number is labelled: `exact` (from the transcript's usage), `attributed` (an exact step
split by size among its entries) or `estimated` (characters at the session's measured ratio).
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from . import index as ix

DEFAULT_WINDOW = 200_000
# Known context windows by model prefix. A model not listed falls back to DEFAULT_WINDOW, and the result
# says the window is a guess; context.window_tokens overrides it.
WINDOWS: dict[str, int] = {}
QUIET_MINUTES = 60


def cache_root() -> Path:
    from ..config import get_cache_dir

    return get_cache_dir() / "context"


def index_path(session_id: str) -> Path:
    safe = "".join(c for c in session_id if c.isalnum() or c in "-_") or "unknown"
    return cache_root() / f"{safe}.json"


def load_index(session_id: str) -> Optional[dict]:
    try:
        data = json.loads(index_path(session_id).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def save_index(session_id: str, data: dict) -> None:
    path = index_path(session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def find_transcript(project_dir: Path, session_id: Optional[str] = None) -> Optional[Path]:
    """The session's transcript; without a session id, the project's most recently written one."""
    from ..reflection.digest import session_files, sessions_for_project

    if session_id:
        for f in session_files():
            if f.stem == session_id:
                return f
        return None
    found = sessions_for_project(Path(project_dir))
    return max(found, key=lambda f: f.stat().st_mtime) if found else None


def refresh(transcript: Path, session_id: Optional[str] = None, max_bytes: Optional[int] = None) -> tuple[dict, bool]:
    """Bring the session's index up to date (or a slice of it, with max_bytes) and save it."""
    session_id = session_id or Path(transcript).stem
    data, caught_up = ix.update(load_index(session_id), Path(transcript), max_bytes)
    save_index(session_id, data)
    return data, caught_up


def _minutes_since(stamp: Optional[str], now: datetime) -> Optional[float]:
    if not stamp:
        return None
    try:
        t = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return None
    return (now - t).total_seconds() / 60


LARGE_WINDOW = 1_000_000


def window_for(model: Optional[str], override: int = 0, seen: int = 0) -> tuple[int, bool]:
    """The model's context window and whether it is known. An unknown model gets DEFAULT_WINDOW, or the
    large window once the session has shown a bigger context: any request's size, or a compaction's
    preTokens, is a lower bound on the window. Nudges that depend on the window must check `known`."""
    if override:
        return override, True
    for prefix, size in WINDOWS.items():
        if model and model.startswith(prefix):
            return size, True
    return (LARGE_WINDOW if seen > DEFAULT_WINDOW else DEFAULT_WINDOW), False


def view(data: dict, session_id: str, now: Optional[datetime] = None, quiet_minutes: int = QUIET_MINUTES,
         window_tokens: int = 0) -> dict:
    """The context map from an index: the dict `measure` returns."""
    now = now or datetime.now(timezone.utc)
    seg = data["segment"]
    used = seg["last_ctx"] or 0
    rate = ix.ratio(data)
    window, known = window_for(data.get("model"), window_tokens, max(used, int(data.get("max_seen") or 0)))

    def quiet(stamp):
        m = _minutes_since(stamp, now)
        return m is not None and m > quiet_minutes

    pending: dict[str, float] = {}
    for subject, _, chars, _, is_output in seg["pending"]:
        if not is_output:  # the last request's own output is known exactly: last_output, below
            pending[subject] = pending.get(subject, 0) + chars / rate
    if seg["last_ctx"] is not None and seg["last_output"]:
        pending["output:output"] = pending.get("output:output", 0) + seg["last_output"]
    subjects = []
    if seg["base"] is not None:
        breakdown = {seg["subjects"][k]["label"]: round(c / rate) for k, c in seg["base_estimate"].items()
                     if k in seg["subjects"]}
        breakdown["system, tools and preserved messages"] = max(seg["base"] - sum(breakdown.values()), 0)
        subjects.append({"key": "base", "subject": "base (at the first request after the last compaction)",
                         "kind": "base", "tokens": seg["base"], "how": "exact", "quiet": False,
                         "last_touched": seg.get("started"), "breakdown": breakdown,
                         "breakdown_how": "estimated"})
    for key, s in seg["subjects"].items():
        tokens = round(s["tokens"])
        if not tokens and not pending.get(key):
            continue
        how = "exact" if s["kind"] == "output" and seg["exact"] else s["how"]
        subjects.append({"key": key, "subject": s["label"], "kind": s["kind"], "tokens": tokens, "how": how,
                         "quiet": quiet(s["last_touched"]), "last_touched": s["last_touched"],
                         "pending_tokens": round(pending.get(key, 0))})
    subjects.sort(key=lambda x: -x["tokens"])
    tasks = [{"key": k, "task": k.split(":", 1)[-1] if ":" in k else k, "tokens": round(t["tokens"]),
              "quiet": quiet(t["last_touched"]), "last_touched": t["last_touched"]}
             for k, t in seg["tasks"].items() if round(t["tokens"])]
    tasks.sort(key=lambda x: -x["tokens"])
    if seg["base"] is not None:
        tasks.append({"key": "base", "task": "base (before any task since the compaction)", "tokens": seg["base"],
                      "quiet": False, "last_touched": seg.get("started")})
    for row in subjects + tasks:
        row["share"] = round(row["tokens"] / used, 4) if used else 0.0
    quiet_tokens = sum(r["tokens"] for r in subjects if r["quiet"] and r["kind"] != "base")
    return {
        "session_id": session_id,
        "measured_at": now.isoformat(timespec="seconds"),
        "model": data.get("model"),
        "window_tokens": window,
        "window_known": known,
        "used_tokens": used,
        "measured": seg["last_ctx"] is not None,
        "exact": seg["exact"],
        "ratio_chars_per_token": round(rate, 2),
        "pending_tokens": round(sum(pending.values())),
        "quiet_minutes": quiet_minutes,
        "quiet_tokens": quiet_tokens,
        "quiet_share": round(quiet_tokens / used, 4) if used else 0.0,
        "compactions_seen": len(data.get("finished", [])),
        "by_subject": subjects,
        "by_task": tasks,
        "plan": [],
        "pins": [],
    }


def measure(project_dir: Path, session_id: Optional[str] = None, transcript: Optional[Path] = None,
            now: Optional[datetime] = None, quiet_minutes: Optional[int] = None,
            window_tokens: Optional[int] = None) -> dict:
    """The context map of a session (the latest of the project's, by default). Updates the index first."""
    transcript = Path(transcript) if transcript else find_transcript(project_dir, session_id)
    if transcript is None:
        raise FileNotFoundError("no Claude Code transcript found for this project or session")
    session_id = session_id or transcript.stem
    data, _ = refresh(transcript, session_id)
    settings = _settings(project_dir)
    return view(data, session_id, now,
                quiet_minutes if quiet_minutes is not None else settings["quiet_minutes"],
                window_tokens if window_tokens is not None else settings["window_tokens"])


def _settings(project_dir: Path) -> dict:
    """context.* settings, read raw (the group registers with the rest of 0015's keys)."""
    out = {"quiet_minutes": QUIET_MINUTES, "window_tokens": 0}
    for path in (None, Path(project_dir) / ".daedalus" / "config.json"):
        try:
            if path is None:
                from ..config import get_config_file
                path = get_config_file()
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError, ImportError):
            continue
        group = data.get("context") if isinstance(data, dict) else None
        if isinstance(group, dict):
            for k in out:
                if isinstance(group.get(k), int) and not isinstance(group.get(k), bool):
                    out[k] = group[k]
    return out
