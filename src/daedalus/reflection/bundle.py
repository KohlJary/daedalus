"""
What `delphi` reads (edict 0010): one bundle per reflection run, built deterministically.

A level bundle holds the period's digests, a spend summary of them, both models (with confidence after decay), the
tombstones not to propose again, and at the monthly level the evolution, lineage flags and
unmoved aspirations the report must list. On the first monthly run, with both models empty, it
also holds the seed sources: the identity files and Claude Code's memory notes for the project.

The aspiration bundle is asked cold: the identity, the month's digests and the self model's
behavior entries, and no aspirations, so earlier answers can't be restated before the new one
is written.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Optional

from . import models as m
from .digest import load_digests
from .due import month_of, session_day, session_days
from .fsutil import write_json
from .paths import reflection_dir
from .spend import summarize

BUNDLE_SCHEMA = "daedalus.reflection-bundle/1"
IN_USE_DAYS = 30
TENSION_PROMPTS = [
    "Where this month did you act in a way you wouldn't choose again?",
    "Where did a correction from the user surprise you?",
    "What did you keep doing that the record says isn't working?",
    "What would you want a session a year from now to have stopped, or started?",
]


def bundles_dir(project_dir: Path) -> Path:
    return reflection_dir(project_dir) / "bundles"


def period_bounds(level: str, period: str) -> tuple[date, date]:
    if level == "daily":
        day = date.fromisoformat(period)
        return day, day
    if level == "weekly":
        year, week = period.split("-W")
        start = date.fromisocalendar(int(year), int(week), 1)
        return start, start + timedelta(days=6)
    year, month = period.split("-")
    start, end, _ = month_of(date(int(year), int(month), 1))
    return start, end


def _digests_in(project_dir: Path, start: date, end: date) -> list[dict]:
    """The period's digests, leaving out the session running the reflection (it is not over)."""
    from .arms import current_session_id

    running = current_session_id()
    hidden = ("model_summary_arm", "model_summary_mode", "model_summary_seed")  # never shown to delphi
    return [{k: v for k, v in d.items() if k not in hidden} for d in load_digests(project_dir)
            if any(start <= day <= end for day in session_days(d)) and d.get("session_id") != running]


def _model_view(model: str, settings: dict, today: date, root: Optional[Path], aspirations: bool = True) -> dict:
    data = m.load(model, root)
    hl = m.half_life(model, settings)
    entries = []
    for e in data["entries"]:
        if not aspirations and e.get("kind") == "aspiration":
            continue
        entries.append({**e, "effective_confidence": round(m.effective_confidence(e, today, hl), 4)})
    return {"entries": entries, "tombstones": data.get("tombstones", [])}


def in_use_models(project_dir: Path, today: date) -> set[str]:
    since = today - timedelta(days=IN_USE_DAYS)
    digests = load_digests(project_dir)
    recent = {model for d in digests if (day := session_day(d)) and day >= since for model in d.get("models") or []}
    if recent or not digests:
        return recent
    # A quiet month doesn't retire every model: fall back to the latest session's
    latest = max(digests, key=lambda d: d.get("end") or "")
    return set(latest.get("models") or [])


def seed_sources(project_dir: Path) -> list[dict]:
    """The identity files and the project's Claude Code memory notes, for the first monthly run."""
    from ..config import get_config_dir
    sources = []
    for name in ("identity.md", "identity.json"):
        path = get_config_dir() / name
        if path.exists():
            sources.append({"source": str(path), "kind": "identity", "text": path.read_text(encoding="utf-8-sig")})
    # Memory notes from every project folder whose transcripts map to a project with .daedalus/
    from .tick import projects_with_sessions

    folders = {f.parent for files in projects_with_sessions().values() for f in files}
    for folder in sorted(folders):
        for note in sorted((folder / "memory").glob("*.md")):
            sources.append({"source": str(note), "kind": "memory-note", "text": note.read_text(encoding="utf-8-sig")})
    return sources


def build_bundle(project_dir: Path, level: str, period: str, settings: dict, scope: str,
                 root: Optional[Path] = None, today: Optional[date] = None) -> dict:
    today = today or date.today()
    start, end = period_bounds(level, period)
    digests = _digests_in(project_dir, start, end)
    if level in ("daily", "weekly"):
        # A session can run for days: say which of its events fall in this period. Only those may be cited.
        for d in digests:
            days = d.get("event_days") or {}
            d["in_period"] = {k: [u for u in v if start.isoformat() <= days.get(u, start.isoformat()) <= end.isoformat()]
                              for k, v in (d.get("events") or {}).items()}
            first, last = (d.get("start") or "")[:10], (d.get("end") or "")[:10]
            d["spans_days"] = bool(first and last and first != last)
    bundle = {
        "schema": BUNDLE_SCHEMA, "level": level, "period": period,
        "start": start.isoformat(), "end": end.isoformat(), "scope": scope,
        "digests": digests,
        "models": {model: _model_view(model, settings, today, root) for model in m.MODELS},
        # Where the period's tokens went (estimated), for tokens findings. Figures in a finding
        # still cite digest fields (turns.N.units, units, tokens_by_model...), not this summary.
        "spend": summarize(digests, start, end),
    }
    if level == "monthly":
        bundle["evolution"] = m.evolution(start, end, root)
        bundle["lineage"] = m.lineage_flags(in_use_models(project_dir, today), root)
        bundle["unmoved_aspirations"] = m.unmoved_aspirations(today, root)
        bundle["aspirations_active"] = [e["id"] for e in m.active_entries(m.load("self", root))
                                        if e.get("kind") == "aspiration"]
        bundle["model_dissents"] = [d["id"] for d in m.load_dissents(root, open_only=True)]
        bundle["model_dissent_details"] = m.load_dissents(root, open_only=True)
        if not any(bundle["models"][model]["entries"] for model in m.MODELS):
            bundle["seed_sources"] = seed_sources(project_dir)
    return bundle


def build_aspiration_bundle(project_dir: Path, period: str, settings: dict,
                            root: Optional[Path] = None, today: Optional[date] = None) -> dict:
    """Asked cold: no aspiration entries anywhere in it."""
    from ..config import get_config_dir

    today = today or date.today()
    start, end = period_bounds("monthly", period)
    self_view = _model_view("self", settings, today, root, aspirations=False)
    identity = {}
    for name in ("identity.md", "identity.json"):
        path = get_config_dir() / name
        if path.exists():
            identity[name] = path.read_text(encoding="utf-8-sig")
    return {
        "schema": BUNDLE_SCHEMA, "level": "aspiration", "period": period,
        "question": "Who do you want to be?",
        "tension_prompts": TENSION_PROMPTS,
        "identity": identity,
        "digests": _digests_in(project_dir, start, end),
        "behavior": [e for e in self_view["entries"] if e.get("kind") == "behavior"],
    }


def write_bundle(project_dir: Path, bundle: dict) -> Path:
    path = bundles_dir(project_dir) / f"{bundle['level']}-{bundle['period']}.json"
    write_json(path, bundle)
    return path
