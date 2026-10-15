"""
What reflection is due (edict 0010). Deterministic: digests plus `due.json`, against a clock.

- A level (daily, weekly, monthly) is due only for completed periods that have sessions newer
  than what that level has covered. Days with no sessions produce nothing.
- A day below the activity threshold (tool calls across its sessions) is not due as a daily; its
  sessions roll into the week.
- A higher level absorbs the lower levels in its window: when a week is complete, its days are
  the weekly's; when a month is complete, its weeks and days are the monthly's. After a month
  away, the monthly runs once.

Periods are local calendar days, ISO weeks (Monday to Sunday) and calendar months.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone, tzinfo
from pathlib import Path
from typing import Optional

from .fsutil import file_lock, read_json, write_json
from .paths import reflection_dir

LEVELS = ("daily", "weekly", "monthly")


def due_path(project_dir: Path) -> Path:
    return reflection_dir(project_dir) / "due.json"


def load_state(project_dir: Path) -> dict:
    data = read_json(due_path(project_dir), {})
    if not isinstance(data, dict):
        data = {}
    data.setdefault("covered_through", {level: None for level in LEVELS})
    data.setdefault("runs", [])
    return data


def session_day(digest: dict, tz: Optional[tzinfo] = None) -> Optional[date]:
    """The local day a session belongs to: the day it ended."""
    stamp = digest.get("end") or digest.get("start")
    if not stamp:
        return None
    moment = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(tz).date()


def week_of(day: date) -> tuple[date, date, str]:
    start = day - timedelta(days=day.weekday())
    year, week, _ = day.isocalendar()
    return start, start + timedelta(days=6), f"{year}-W{week:02d}"


def month_of(day: date) -> tuple[date, date, str]:
    start = day.replace(day=1)
    following = (start + timedelta(days=32)).replace(day=1)
    return start, following - timedelta(days=1), f"{day.year}-{day.month:02d}"


@dataclass
class Due:
    level: str
    period: str
    start: date
    end: date
    sessions: list = field(default_factory=list)
    tool_calls: int = 0
    absorbs: list = field(default_factory=list)  # lower-level periods this run covers

    def to_dict(self) -> dict:
        return {"level": self.level, "period": self.period, "start": self.start.isoformat(),
                "end": self.end.isoformat(), "sessions": self.sessions, "tool_calls": self.tool_calls,
                "absorbs": self.absorbs}

    def describe(self) -> str:
        n = len(self.sessions)
        text = f"{self.level} reflection due for {self.period}: {n} session{'s' if n != 1 else ''}, {self.tool_calls} tool calls"
        if self.absorbs:
            text += f" (covers {', '.join(self.absorbs)})"
        return text


def session_days(digest: dict, tz: Optional[tzinfo] = None) -> dict[date, int]:
    """{day: tool calls that day} for every local day a session has events on. A session can run for
    days; each day's reflection covers that day's part of it. Digests from before event_days
    (schema 1) belong to the day they ended, with all their calls."""
    days = digest.get("event_days") or {}
    calls = [c.get("uuid") for c in digest.get("calls") or []]
    if days and calls:
        out: dict[date, int] = {}
        for uuid in calls:
            if uuid in days:
                d = date.fromisoformat(days[uuid])
                out[d] = out.get(d, 0) + 1
        if out:
            return out
    day = session_day(digest, tz)
    return {day: int(digest.get("tool_calls") or 0)} if day else {}


def compute_due(digests: list[dict], state: dict, today: date, threshold: int,
                tz: Optional[tzinfo] = None) -> list[Due]:
    """Due reflections, highest level first. Only completed periods (ending before today) count."""
    covered = {level: _parse(state.get("covered_through", {}).get(level)) for level in LEVELS}
    by_day: dict[date, list[dict]] = {}
    for d in digests:
        for day, calls in session_days(d, tz).items():
            if day < today:
                by_day.setdefault(day, []).append({**d, "tool_calls": calls})

    taken: set[date] = set()  # days already inside a higher level's due run

    def uncovered(level: str, start: date, end: date) -> list[dict]:
        line = covered[level]
        return [d for day, ds in by_day.items() if start <= day <= end and day not in taken
                and (line is None or day > line) for d in ds]

    result: list[Due] = []
    for level, period_of in (("monthly", month_of), ("weekly", week_of)):
        periods = {}
        for day in by_day:
            start, end, name = period_of(day)
            if end < today and day not in taken:
                periods[name] = (start, end)
        for name, (start, end) in sorted(periods.items(), key=lambda kv: kv[1][0]):
            sessions = uncovered(level, start, end)
            if not sessions:
                continue
            absorbs = _absorbed(level, start, end, by_day, covered, threshold)
            result.append(Due(level, name, start, end, sorted({d["session_id"] for d in sessions}),
                              sum(int(d.get("tool_calls") or 0) for d in sessions), absorbs))
            taken.update(day for day in by_day if start <= day <= end)
    for day in sorted(by_day):
        if day in taken or not (covered["daily"] is None or day > covered["daily"]):
            continue
        sessions = by_day[day]
        calls = sum(int(d.get("tool_calls") or 0) for d in sessions)
        if calls >= threshold:
            result.append(Due("daily", day.isoformat(), day, day, sorted(d["session_id"] for d in sessions), calls))
    order = {level: i for i, level in enumerate(reversed(LEVELS))}
    return sorted(result, key=lambda d: (order[d.level], d.start))


def _absorbed(level: str, start: date, end: date, by_day: dict, covered: dict, threshold: int) -> list[str]:
    """The lower-level periods inside [start, end] that would otherwise have been due."""
    names = []
    if level == "monthly":
        weeks = sorted({week_of(day)[2] for day in by_day if start <= day <= end
                        and (covered["weekly"] is None or day > covered["weekly"])})
        names += weeks
    for day in sorted(by_day):
        if start <= day <= end and (covered["daily"] is None or day > covered["daily"]):
            if sum(int(d.get("tool_calls") or 0) for d in by_day[day]) >= threshold:
                names.append(day.isoformat())
    return names


def mark_done(project_dir: Path, level: str, period_end: date, period: str) -> dict:
    """Record a finished run. It covers its own level and every lower level through its end."""
    path = due_path(project_dir)
    with file_lock(path):
        state = load_state(project_dir)
        for lower in LEVELS[: LEVELS.index(level) + 1]:
            current = _parse(state["covered_through"].get(lower))
            if current is None or period_end > current:
                state["covered_through"][lower] = period_end.isoformat()
        state["runs"].append({"level": level, "period": period, "end": period_end.isoformat(),
                              "at": datetime.now(timezone.utc).isoformat(timespec="seconds")})
        write_json(path, state)
    return state


def write_due(project_dir: Path, due: list[Due]) -> None:
    path = due_path(project_dir)
    with file_lock(path):
        state = load_state(project_dir)
        state["due"] = [d.to_dict() for d in due]
        state["checked_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        write_json(path, state)


def _parse(value: Optional[str]) -> Optional[date]:
    return date.fromisoformat(value) if value else None
