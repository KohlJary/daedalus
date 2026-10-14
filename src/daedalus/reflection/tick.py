"""
`daedalus reflect tick` and the cleanup warning (edict 0010). Deterministic; safe from cron,
a systemd timer or Task Scheduler. Model calls happen only under the local or headless runner,
and only where `machine.employer` is false.
"""

from __future__ import annotations

import time
from datetime import date
from pathlib import Path
from typing import Optional

from ..config import get_project_settings
from .digest import digest_path, first_cwd, is_current, load_digests, session_files, digest_project
from .due import compute_due, load_state, write_due
from .fsutil import read_json
from .paths import claude_settings_file, owner_project

DEFAULT_CLEANUP_DAYS = 30


def cleanup_period_days() -> int:
    """Claude Code's cleanupPeriodDays from its settings, or 30 when it isn't set."""
    data = read_json(claude_settings_file(), {})
    value = data.get("cleanupPeriodDays") if isinstance(data, dict) else None
    return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else DEFAULT_CLEANUP_DAYS


def projects_with_sessions(claude_projects: Optional[Path] = None) -> dict[str, list[Path]]:
    """Every project (a directory with .daedalus/) that has transcripts, mapped by their cwd."""
    projects: dict[str, list[Path]] = {}
    for f in session_files(claude_projects):
        owner = owner_project(first_cwd(f) or "")
        if owner:
            projects.setdefault(owner, []).append(f)
    return projects


def update_due(project_dir: Path, today: Optional[date] = None):
    settings = get_project_settings(project_dir, "reflection")
    state = load_state(project_dir)
    due = compute_due(load_digests(project_dir), state, today or date.today(), int(settings["activity_threshold"]))
    write_due(project_dir, due)
    return due


def tick(claude_projects: Optional[Path] = None, today: Optional[date] = None) -> dict[str, dict]:
    """Digest every project's new or grown sessions, then update what is due. No model calls."""
    out = {}
    for project in sorted(projects_with_sessions(claude_projects)):
        result = digest_project(Path(project), claude_projects)
        due = update_due(Path(project), today)
        out[project] = {**result, "due": [d.describe() for d in due]}
    return out


def undigested_near_cleanup(project_dir: Path, warning_days: int, claude_projects: Optional[Path] = None,
                            now: Optional[float] = None) -> list[tuple[str, int]]:
    """
    Sessions not yet digested (or grown since) that Claude Code will delete within `warning_days`.
    Returns (session_id, days left). A transcript is dated by its modification time.
    """
    from .digest import sessions_for_project

    now = now or time.time()
    period = cleanup_period_days()
    out = []
    for f in sessions_for_project(project_dir, claude_projects):
        if is_current(read_json(digest_path(project_dir, f.stem)), f):
            continue
        age_days = (now - f.stat().st_mtime) / 86400
        left = int(period - age_days)
        if left <= warning_days:
            out.append((f.stem, max(left, 0)))
    return out


HEADLESS_PROMPT = (
    "Run the /reflect skill for the reflections due in this project. You are running unattended: "
    "write the report and have Momus review it, record the run, and stop. Do not import or apply "
    "any proposal; the next session presents the report to the user."
)


def unpresented_path(project_dir: Path) -> Path:
    from .paths import reflection_dir

    return reflection_dir(project_dir) / "unpresented.json"


MAX_HEADLESS_ATTEMPTS = 2


def run_due_headless(project_dir: Path) -> bool:
    """
    The headless runner: one `claude -p` run of /reflect. Callers check the runner first. A due
    set that has failed twice is not retried on every tick (it stays due for the next session).
    """
    import subprocess

    from .due import load_state
    from .fsutil import file_lock, write_json
    from .paths import reports_dir
    from .runners import resolve_runner, run_headless

    if resolve_runner().effective != "headless":
        raise RuntimeError("The headless runner is not allowed on this machine")
    state = load_state(project_dir)
    key = ",".join(f"{d['level']}:{d['period']}" for d in state.get("due", []))
    attempts = state.get("headless_attempts", {})
    if attempts.get(key, 0) >= MAX_HEADLESS_ATTEMPTS:
        return False
    before = {p.name for p in reports_dir(project_dir).glob("*.md")} if reports_dir(project_dir).is_dir() else set()
    try:
        result = run_headless(project_dir, HEADLESS_PROMPT)
        ok = result.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        ok = False
    if not ok:
        from .due import due_path

        with file_lock(due_path(project_dir)):
            state = load_state(project_dir)
            state.setdefault("headless_attempts", {})[key] = state.get("headless_attempts", {}).get(key, 0) + 1
            write_json(due_path(project_dir), state)
    after = sorted(p for p in reports_dir(project_dir).glob("*.md") if p.name not in before) \
        if reports_dir(project_dir).is_dir() else []
    if after:
        listed = read_json(unpresented_path(project_dir), []) or []
        write_json(unpresented_path(project_dir), listed + [str(p) for p in after])
    return ok


def take_unpresented(project_dir: Path) -> list[str]:
    """Reports an unattended run wrote, for inhale to present once."""
    path = unpresented_path(project_dir)
    listed = read_json(path, []) or []
    if listed:
        path.unlink()
    return listed
