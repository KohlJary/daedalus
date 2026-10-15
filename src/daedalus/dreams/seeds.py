"""
Seeds (edict 0013, amended): what a dream starts from, chosen deterministically by readiness.

Seed kinds in v1, each read from something Daedalus already keeps:
- `stale_task`: tasks in progress past doctor.stale_task_days, in any workstream (aged by `updated`);
- `dissent`: open dissents (aged by their filing date);
- `backlog`: roadmap items in `backlog` (aged by `created_at`);
- `coverage_gap`: rows marked `○` in docs/design/tui/coverage.md (aged by the file's last commit);
- `finding`: the latest reflection report's findings (aged by the report's period);
- `open_question`: bullets under a `## Open questions` heading in docs/status.md (aged by its last commit).

Readiness = 0.4·age + 0.3·recurrence + 0.2·activity + 0.1·convergence, each normalised to 0..1 over the
candidates:
- age: days since the seed's date;
- recurrence: how many earlier dreams' seeds and reflection reports name the same key;
- activity: 1 if the thing changed in the last 7 days, else 0;
- convergence: how many other seed kinds share a roadmap item ID, task ID or path with it.
Ties break by seed ID. A theme the owner gives is always first. The clock is injectable (`today`).
"""

from __future__ import annotations

import re
import subprocess
from datetime import date
from pathlib import Path
from typing import Optional

from ..reflection.fsutil import read_json

WEIGHTS = {"age": 0.4, "recurrence": 0.3, "activity": 0.2, "convergence": 0.1}
REF = re.compile(r"\b(T-[a-z]+\d+|p\d+[a-z]?-[a-z0-9-]+|[\w-]+-\d+(?:\.\w+)?|(?:src|docs|tests)/[\w./-]+)\b")


def _days(since: Optional[str], today: date) -> int:
    try:
        return max(0, (today - date.fromisoformat(str(since)[:10])).days)
    except (TypeError, ValueError):
        return 0


def _last_commit(project_dir: Path, rel: str) -> Optional[str]:
    try:
        out = subprocess.run(["git", "log", "-1", "--format=%cs", "--", rel], cwd=project_dir,
                             capture_output=True, text=True, timeout=10)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    return out.stdout.strip() or None


def _seed(kind: str, key: str, text: str, dated: Optional[str], today: date, active: bool, scope: str = "work") -> dict:
    return {"id": f"{kind}:{key}", "kind": kind, "key": key, "text": text.strip()[:400], "date": dated,
            "age_days": _days(dated, today), "active": active, "scope": scope}


def candidates(project_dir: Path, settings: dict, today: date) -> list[dict]:
    from .. import roadmap
    from .. import workstreams as ws
    from ..cli import gameplan as gp
    from ..config import get_project_settings

    project_dir = Path(project_dir)
    out: list[dict] = []
    stale_days = int(get_project_settings(project_dir, "doctor").get("stale_task_days", 14))

    for wid in ws.list_ids(project_dir):
        try:
            data = gp.load_gameplan(project_dir, wid)
        except gp.GameplanError:
            continue
        for _, task in roadmap.all_tasks(data):
            if task.get("status") == "in_progress" and _days(task.get("updated"), today) >= stale_days:
                out.append(_seed("stale_task", task["id"], f"{task['id']}: {task.get('title', '')}. "
                                 f"{task.get('details', '')}", task.get("updated"), today, False))

    try:
        from ..edicts import list_dissents

        for d in list_dissents(project_dir):
            text = d.path.read_text(encoding="utf-8") if d.path.exists() else ""
            out.append(_seed("dissent", d.path.stem, f"Dissent on edict {d.edict}: {text[:300]}", d.filed, today,
                             _days(d.filed, today) <= 7))
    except Exception:
        pass

    try:
        index = roadmap.load_index(project_dir)
    except roadmap.RoadmapError:
        index = {"items": []}
    for item in index.get("items", []):
        if item.get("status", "backlog") == "backlog" and roadmap.origin(item)["source"] != "dream":
            out.append(_seed("backlog", item["id"], f"{item.get('title', '')}. {item.get('description', '')}",
                             item.get("created_at"), today, _days(item.get("status_changed_at"), today) <= 7
                             if item.get("status_changed_at") else False))

    coverage = project_dir / "docs" / "design" / "tui" / "coverage.md"
    if coverage.exists():
        dated = _last_commit(project_dir, "docs/design/tui/coverage.md")
        for line in coverage.read_text(encoding="utf-8").splitlines():
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if line.lstrip().startswith("|") and "○" in cells and len(cells) >= 3 and not cells[0].startswith("**"):
                name = re.sub(r"[`*]", "", cells[0])
                note = " ".join(c for c in cells[2:] if c and c != "○")
                out.append(_seed("coverage_gap", re.sub(r"\W+", "-", name.lower()).strip("-")[:60],
                                 f"Not visible in the TUI: {name}. {note}", dated, today, _days(dated, today) <= 7))

    reports = sorted((project_dir / ".daedalus" / "reflection" / "reports").glob("*.json"))
    reports = [r for r in reports if not r.name.endswith(".verdicts.json")]
    if reports:
        latest = read_json(reports[-1], {}) or {}
        dated = str(latest.get("period", ""))[:10] if re.match(r"\d{4}-\d{2}-\d{2}", str(latest.get("period", ""))) \
            else _last_commit(project_dir, str(reports[-1].relative_to(project_dir)))
        for f in latest.get("findings") or []:
            text = re.sub(r"\[s:[^\]]+\]", "", str(f.get("text", "")))
            out.append(_seed("finding", f"{reports[-1].stem}.{f.get('id', '')}", text, dated, today, True))

    status = project_dir / "docs" / "status.md"
    if status.exists():
        dated = _last_commit(project_dir, "docs/status.md")
        section = re.search(r"^##\s+Open questions\s*$(.*?)(?=^##\s|\Z)", status.read_text(encoding="utf-8"),
                            re.M | re.S | re.I)
        for n, bullet in enumerate(re.findall(r"^\s*[-*]\s+(.+)$", section.group(1) if section else "", re.M), 1):
            slug = re.sub(r"\W+", "-", bullet.lower())[:40].strip("-")
            out.append(_seed("open_question", f"q{n}-{slug}", bullet, dated, today, _days(dated, today) <= 7))
    return out


def _recurrence(project_dir: Path, seed: dict) -> int:
    key = seed["key"]
    n = 0
    dreams = Path(project_dir) / ".daedalus" / "dreams"
    for f in dreams.glob("*/seeds.json") if dreams.is_dir() else []:
        data = read_json(f, {}) or {}
        n += sum(1 for s in data.get("seeds", []) if s.get("key") == key)
    for f in (Path(project_dir) / ".daedalus" / "reflection" / "reports").glob("*.json"):
        try:
            n += key in f.read_text(encoding="utf-8")
        except OSError:
            continue
    return n


def _norm(values: list[float]) -> list[float]:
    lo, hi = min(values, default=0), max(values, default=0)
    return [0.0 if hi == lo else (v - lo) / (hi - lo) for v in values]


def score(project_dir: Path, seeds: list[dict]) -> list[dict]:
    refs = [set(REF.findall(s["text"] + " " + s["key"])) for s in seeds]
    for s, mine in zip(seeds, refs):
        s["recurrence"] = _recurrence(project_dir, s)
        s["convergence"] = len({o["kind"] for o, theirs in zip(seeds, refs)
                                if o is not s and o["kind"] != s["kind"] and mine & theirs})
    parts = {
        "age": _norm([s["age_days"] for s in seeds]),
        "recurrence": _norm([s["recurrence"] for s in seeds]),
        "activity": [1.0 if s["active"] else 0.0 for s in seeds],
        "convergence": _norm([s["convergence"] for s in seeds]),
    }
    for i, s in enumerate(seeds):
        s["readiness"] = round(sum(WEIGHTS[k] * parts[k][i] for k in WEIGHTS), 4)
    return sorted(seeds, key=lambda s: (-s["readiness"], s["id"]))


def select_seeds(project_dir: Path, settings: dict, theme: Optional[str] = None,
                 today: Optional[date] = None) -> list[dict]:
    """The dream's seeds: at most dream.seeds, from at least two kinds where there are two, theme first."""
    today = today or date.today()
    limit = int(settings.get("seeds", 5))
    ranked = score(project_dir, candidates(project_dir, settings, today))
    chosen = ranked[: max(0, limit - (1 if theme else 0))]
    kinds = {s["kind"] for s in chosen}
    if len(kinds) == 1 and chosen:
        other = next((s for s in ranked if s["kind"] not in kinds), None)
        if other is not None:
            chosen[-1] = other
    if theme:
        slug = re.sub(r"\W+", "-", theme.lower()).strip("-")[:60] or "owner"
        chosen.insert(0, {"id": f"theme:{slug}", "kind": "theme", "key": slug, "text": theme.strip()[:400],
                          "date": today.isoformat(), "age_days": 0, "active": True, "scope": "work",
                          "readiness": None})
    return chosen


def as_text(seeds: list[dict]) -> str:
    """The seeds as the dreamer reads them: the material, without scores or kinds' plumbing."""
    names = {"theme": "A theme the owner gave", "stale_task": "Work that has stalled", "dissent": "An open dissent",
             "backlog": "Something asked for and waiting", "coverage_gap": "Something the project can't show yet",
             "finding": "From the last reflection", "open_question": "An open question"}
    return "\n".join(f"{n}. {names.get(s['kind'], s['kind'])}: {s['text']}" for n, s in enumerate(seeds, 1))
