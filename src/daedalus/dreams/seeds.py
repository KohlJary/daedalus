"""
Seeds (edict 0013, amended): what a dream starts from, chosen deterministically by readiness.

Seed kinds in v1, each read from something Daedalus already keeps:
- `stale_task`: tasks in progress past doctor.stale_task_days, in any workstream (aged by `updated`);
- `dissent`: open dissents (aged by their filing date);
- `backlog`: roadmap items in `backlog` (aged by `created_at`);
- `coverage_gap`: rows of docs/design/tui/coverage.md's detail tables whose mark cell is `○` (aged by the
  file's last commit). Header rows, legend rows (first cell a mark), summary and totals rows (bold, empty,
  or a "Group"/"Total(s)"/"CLI"/"All" first cell), and the summary tables' `○` *columns* are not gaps;
- `finding`: the latest reflection report's findings (aged by the end of the report's period: a date,
  a week such as `2026-W42`, or a month such as `2026-10`);
- `open_question`: bullets under a `## Open questions` heading in docs/status.md (aged by its last commit).

Readiness = 0.4·age + 0.3·recurrence + 0.2·activity + 0.1·convergence, each normalised to 0..1 over the
candidates:
- age: days since the seed's date;
- recurrence: how many earlier dreams' seeds have the same key, plus how many reflection reports name
  the key as a whole token (`T-e1` doesn't recur in a report that names only `T-e12`; an empty key never
  recurs);
- activity: 1 if the thing changed in the last 7 days, else 0;
- convergence: how many other seed kinds share a roadmap item ID, task ID or path with it.
Ties break by seed ID. A theme the owner gives is always first. The clock is injectable (`today`).

Recency penalty: seeds are deterministic, so with the project unchanged the same seed would top every
night, and a theme could never recur across dreams with different top seeds (F7). So a candidate that was
the top seed of either of the two latest dreams ranks after every other candidate, keeping its order
among the penalised by readiness. The penalty is in the ranking only; readiness itself is unchanged and
reported as computed. With unchanged state the top seed therefore cycles through at least three
candidates, where there are three.
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


MARKS = set("●◐→○–")
NOT_A_ROW = {"group", "total", "totals", "cli", "all", "surface", "mark"}


def _period_end(period: str) -> Optional[str]:
    """The last day of a reflection period (a date, `YYYY-Www` or `YYYY-MM`), or None if it isn't one."""
    from ..reflection.bundle import period_bounds

    period = str(period or "")
    for level, pattern in (("daily", r"\d{4}-\d{2}-\d{2}"), ("weekly", r"\d{4}-W\d{1,2}"), ("monthly", r"\d{4}-\d{2}")):
        if re.fullmatch(pattern, period):
            try:
                return period_bounds(level, period)[1].isoformat()
            except (ValueError, TypeError):
                return None
    return None


def _coverage_gaps(text: str) -> list[tuple[str, str]]:
    """(name, note) for each `○` row of coverage.md's detail tables. A table's first row is its header; a
    gap is a body row with a cell that is exactly `○` under a column whose header isn't itself `○` (the
    summary tables have a `○` column of counts or command names, not gaps)."""
    out, table = [], []
    for line in text.splitlines() + [""]:
        if line.lstrip().startswith("|"):
            table.append([c.strip() for c in line.strip().strip("|").split("|")])
            continue
        if table:
            header, body = table[0], [r for r in table[1:] if not all(set(c) <= set("-: ") for c in r)]
            for cells in body:
                first = cells[0] if cells else ""
                name = re.sub(r"[`*]", "", first).strip()
                if (not name or first.startswith("**") or set(name) <= MARKS | {" "}
                        or re.sub(r"\W.*", "", name.lower()) in NOT_A_ROW):
                    continue
                marked = [k for k, c in enumerate(cells) if k > 0 and c == "○"
                          and (k >= len(header) or header[k] != "○")]
                if marked:
                    note = " ".join(c for k, c in enumerate(cells[1:], 1) if c and c != "○")
                    out.append((name, note))
            table = []
    return out


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
        for name, note in _coverage_gaps(coverage.read_text(encoding="utf-8")):
            key = re.sub(r"\W+", "-", name.lower()).strip("-")[:60]
            if key:
                out.append(_seed("coverage_gap", key, f"Not visible in the TUI: {name}. {note}", dated, today,
                                 _days(dated, today) <= 7))

    reports = sorted((project_dir / ".daedalus" / "reflection" / "reports").glob("*.json"))
    reports = [r for r in reports if not r.name.endswith(".verdicts.json")]
    if reports:
        latest = read_json(reports[-1], {}) or {}
        dated = _period_end(str(latest.get("period", ""))) \
            or _last_commit(project_dir, str(reports[-1].relative_to(project_dir)))
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
    if not key:
        return 0
    token = re.compile(rf"(?<![\w-]){re.escape(key)}(?![\w-])")
    dreams = Path(project_dir) / ".daedalus" / "dreams"
    for f in dreams.glob("*/seeds.json") if dreams.is_dir() else []:
        data = read_json(f, {}) or {}
        n += sum(1 for s in data.get("seeds", []) if s.get("key") == key)
    for f in (Path(project_dir) / ".daedalus" / "reflection" / "reports").glob("*.json"):
        try:
            n += bool(token.search(f.read_text(encoding="utf-8")))
        except OSError:
            continue
    return n


def _norm(values: list[float]) -> list[float]:
    lo, hi = min(values, default=0), max(values, default=0)
    return [0.0 if hi == lo else (v - lo) / (hi - lo) for v in values]


def recent_tops(project_dir: Path, last: int = 2) -> set[str]:
    """The top seeds (first in seeds.json) of the `last` latest dreams."""
    from . import store

    tops = set()
    for dream_id in store.list_dreams(project_dir)[-last:] if last else []:
        data = read_json(store.dream_dir(project_dir, dream_id) / "seeds.json", {}) or {}
        if data.get("seeds"):
            tops.add(data["seeds"][0].get("id"))
    return tops


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
    recent = recent_tops(project_dir)
    for s in seeds:
        s["recent_top"] = s["id"] in recent
    return sorted(seeds, key=lambda s: (s["recent_top"], -s["readiness"], s["id"]))


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
