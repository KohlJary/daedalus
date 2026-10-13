"""
Claude Code hooks (edict 0007).

`daedalus hook session-start` prints a short, gameplan-first brief that Claude Code adds to the
context of every new session. `init` and `hydrate` register it in the project's
.claude/settings.json. Hooks are deterministic: no model calls, and they never write to the
gameplan, status, or edicts.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

from .cli import gameplan as gp

MAX_BRIEF_LINES = 40
MAX_NOTE_LINES = 12
SESSION_START_COMMAND = "daedalus hook session-start"
SUMMARY_HEADING = re.compile(r"^## .*$", re.MULTILINE)
DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


# ---------- session-start brief ----------


def latest_session_note(text: str) -> Optional[str]:
    """The newest '## ' entry of a session-summaries file: the latest dated heading, else the last one."""
    starts = [m.start() for m in SUMMARY_HEADING.finditer(text)]
    if not starts:
        return None
    entries = [text[a:b].strip() for a, b in zip(starts, starts[1:] + [len(text)])]
    dated = [(DATE.search(e.splitlines()[0]), i) for i, e in enumerate(entries)]
    dated = [(m.group(0), i) for m, i in dated if m]
    if dated:
        return entries[max(dated)[1]]
    return entries[-1]


def _next_task(active: dict) -> Optional[dict]:
    tasks = active.get("tasks", [])
    for status in ("in_progress", "pending"):
        for task in tasks:
            if task.get("status") == status:
                return task
    return None


def _roadmap_in_progress(project_dir: Path) -> list[str]:
    path = project_dir / ".daedalus" / "roadmap" / "index.json"
    try:
        items = json.loads(path.read_text(encoding="utf-8")).get("items", [])
    except (OSError, json.JSONDecodeError, AttributeError):
        return []
    return [i.get("title", "Untitled") for i in items if i.get("status") == "in_progress"]


def _first_line(text: str, width: int = 160) -> str:
    line = " ".join(text.split())
    return line if len(line) <= width else line[: width - 1] + "…"


def session_start_brief(project_dir: Path) -> str:
    """Active goal and next task, doctor findings, then the latest session note. Under 40 lines."""
    from .doctor import run_checks

    project_dir = Path(project_dir)
    lines = ["## Daedalus"]

    try:
        data = gp.load_gameplan(project_dir)
    except (gp.GameplanError, json.JSONDecodeError):
        data = None
    active = (data or {}).get("activePhase")
    if active:
        tag = f" (edict {active['edict']})" if active.get("edict") else ""
        lines.append(f"**Phase:** {active.get('id')} — {active.get('title')}{tag}")
        if active.get("goal"):
            lines.append(f"**Goal:** {_first_line(active['goal'])}")
        task = _next_task(active)
        if task:
            lines.append(f"**Next task:** {task.get('id')} [{task.get('status')}] {task.get('title')}")
        else:
            lines.append("**Next task:** none open in this phase")
    elif data is not None:
        lines.append("**Phase:** none active (`daedalus gameplan phase activate <id>`)")

    roadmap = _roadmap_in_progress(project_dir)
    if roadmap:
        lines.append("**Roadmap in progress:** " + "; ".join(roadmap[:3]))

    findings, _ = run_checks(project_dir)
    if findings:
        lines.append("**Drift (daedalus doctor):**")
        lines += [f"- {f.name}: {_first_line(f.message, 200)}" for f in findings[:8]]

    note = None
    summaries = project_dir / ".daedalus" / "session-summaries.md"
    if summaries.exists():
        note = latest_session_note(summaries.read_text(encoding="utf-8"))
    if note:
        note_lines = [l for l in note.splitlines() if l.strip()]
        lines.append("**Last session:**")
        lines += note_lines[:MAX_NOTE_LINES]
        if len(note_lines) > MAX_NOTE_LINES:
            lines.append("… (rest in .daedalus/session-summaries.md)")

    lines.append("Run /inhale for the full pickup.")
    if len(lines) > MAX_BRIEF_LINES:
        lines = lines[: MAX_BRIEF_LINES - 2] + ["…", "Run /inhale for the full pickup."]
    return "\n".join(lines)


# ---------- registration in .claude/settings.json ----------


def _hook_commands(settings: dict, event: str) -> list[str]:
    return [
        h.get("command", "")
        for group in settings.get("hooks", {}).get(event, [])
        for h in group.get("hooks", [])
    ]


def wanted_hooks(session_start: bool, capture: bool) -> dict[str, str]:
    """{event: command} that should be registered."""
    wanted = {}
    if session_start:
        wanted["SessionStart"] = SESSION_START_COMMAND
    if capture:
        wanted["SessionEnd"] = "daedalus hook capture"
        wanted["PreCompact"] = "daedalus hook capture"
    return wanted


def register_hooks(
    project_dir: Path, session_start: bool = True, capture: bool = False, dry_run: bool = False
) -> tuple[list[str], Optional[str]]:
    """
    Merge Daedalus hooks into .claude/settings.json, keeping everything already there.

    Returns (events that were or would be added, error). Hooks already present are left alone.
    An unreadable settings file is never overwritten: it is reported as the error.
    """
    path = Path(project_dir) / ".claude" / "settings.json"
    settings: dict = {}
    if path.exists():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            return [], f"{path} is not valid JSON ({e}); hooks not registered"
        if not isinstance(loaded, dict):
            return [], f"{path} is not a JSON object; hooks not registered"
        settings = loaded

    added = []
    for event, command in wanted_hooks(session_start, capture).items():
        if command in _hook_commands(settings, event):
            continue
        settings.setdefault("hooks", {}).setdefault(event, []).append(
            {"hooks": [{"type": "command", "command": command}]}
        )
        added.append(event)

    if added and not dry_run:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
    return added, None
