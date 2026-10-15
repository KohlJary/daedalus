"""
The hook kit's per-session state (edict 0016), for the TUI (0012) and reflection digests (0010).

The kit writes it (`daedalus_hookkit.state`); this module only reads and summarizes it. Shape:
{"session_id", "started_at", "events": [{"at", "hook", "event", "nudge", "followed", "tool", ...}],
 "gate": {"blocks", "passes", "skips", "allowed_by_error"}, "budget": {"per_hour", "used"}, ...}.
"""

from pathlib import Path
from typing import Optional


def state_path(session_id: str) -> Path:
    """Where the kit keeps a session's hook state (the file the TUI watches)."""
    from daedalus_hookkit import state

    return state.state_path(session_id)


def load(project_dir: Optional[Path], session_id: str) -> dict:
    """A session's hook state; an empty state when the kit never wrote one. `project_dir` is accepted for
    symmetry with the other library calls: the state is per session, in the cache directory."""
    from daedalus_hookkit import state

    return state.load(session_id)


def exists(session_id: str) -> bool:
    return state_path(session_id).exists()


def summarize(st: dict) -> dict:
    """Per nudge id: how often it was shown, followed, ignored, still pending, or dropped over budget; the
    gate's counts; and the budget. What a digest records and the TUI's efficacy view shows."""
    nudges: dict[str, dict] = {}
    for e in st.get("events", []):
        if not isinstance(e, dict) or not e.get("nudge"):
            continue
        n = nudges.setdefault(e["nudge"], {"shown": 0, "followed": 0, "ignored": 0, "pending": 0, "dropped": 0,
                                           "tool": e.get("tool", "")})
        if e.get("dropped"):
            n["dropped"] += 1
            continue
        n["shown"] += 1
        f = e.get("followed")
        n["followed" if f is True else "ignored" if f is False else "pending"] += 1
    return {"nudges": dict(sorted(nudges.items())), "gate": dict(st.get("gate", {})),
            "budget": dict(st.get("budget", {}))}
