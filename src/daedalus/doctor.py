"""
Memory drift checks (edict 0007).

`daedalus doctor` compares the gameplan, edicts, and memory files against the repository and
reports where they have fallen behind. Every check is deterministic: git, the file system, and
JSON, no model calls. Each finding has a stable name so hooks and CI can key on it.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Optional

from .cli import gameplan as gp
from .config import get_project_settings, load_project_overrides

EDICT_STATUSES = ("proposed", "accepted", "done")
EDICT_FILE = re.compile(r"^(\d{4})-.+\.md$")
STATUS_LINE = re.compile(r"^Status:\s*(.*?)\s*$", re.MULTILINE)

# Files the session-start hook reads, with the content `daedalus init` writes into them
SESSION_START_READS = {
    ".daedalus/session-summaries.md": "# Session Summaries",
    ".daedalus/roadmap/index.json": None,  # empty when it has no items
}

SKIP_DIRS = {"venv", ".venv", "env", "node_modules", "build", "dist", "site-packages", "__pycache__", "tests", "test"}


@dataclass
class Finding:
    name: str
    message: str


def _git(project_dir: Path, *args: str) -> Optional[str]:
    try:
        out = subprocess.run(
            ["git", *args], cwd=project_dir, capture_output=True, text=True, check=True
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    return out.stdout.strip()


def _is_git_repo(project_dir: Path) -> bool:
    return _git(project_dir, "rev-parse", "--is-inside-work-tree") == "true"


def _gameplan_rel(project_dir: Path, workstream: Optional[str] = None) -> str:
    return str(gp.GameplanPaths.for_project(project_dir, workstream).gameplan_file.relative_to(project_dir))


# ---------- gameplan ----------


def check_commits_after_gameplan(project_dir: Path, threshold: int, workstream: Optional[str] = None,
                                 author: Optional[str] = None) -> list[Finding]:
    """Commits since the plan last changed; for a workstream with an owner pattern, only theirs."""
    if not _is_git_repo(project_dir):
        return []
    rel = _gameplan_rel(project_dir, workstream)
    last = _git(project_dir, "log", "-1", "--format=%H %as", "--", rel)
    if not last:
        return []  # never committed: check_gameplan_ignored / untracked covers it
    sha, when = last.split()
    who = [f"--author={author}"] if author else []
    count = int(_git(project_dir, "rev-list", "--count", "--no-merges", *who, f"{sha}..HEAD") or 0)
    if count < threshold:
        return []
    whose = f" by {author}" if author else ""
    return [Finding(
        "commits-after-gameplan",
        f"{count} commits{whose} since the gameplan was last updated ({when}, {sha[:7]}). "
        "Record what shipped, or run /reconstruct.",
    )]


def check_phase_all_done(data: dict) -> list[Finding]:
    active = data.get("activePhase")
    if not active:
        return []
    tasks = active.get("tasks", [])
    phase = gp.find_phase(data, active.get("id", "")) or {}
    if tasks and all(t.get("status") == "done" for t in tasks) and phase.get("status", "in_progress") == "in_progress":
        return [Finding(
            "phase-tasks-all-done",
            f"Active phase {active.get('id')} is still in_progress but all {len(tasks)} tasks are done. "
            "Close it or add the remaining work.",
        )]
    return []


def check_stale_tasks(data: dict, max_days: int, today: Optional[date] = None) -> list[Finding]:
    active = data.get("activePhase")
    if not active:
        return []
    today = today or date.today()
    findings = []
    for task in active.get("tasks", []):
        if task.get("status") != "in_progress":
            continue
        since = task.get("updated") or active.get("started")
        try:
            age = (today - date.fromisoformat(since)).days
        except (TypeError, ValueError):
            continue
        if age > max_days:
            findings.append(Finding(
                "stale-task",
                f"Task {task.get('id')} has been in_progress for {age} days (since {since}).",
            ))
    return findings


def check_gameplan_ignored(project_dir: Path, workstream: Optional[str] = None) -> list[Finding]:
    if not _is_git_repo(project_dir):
        return []
    rel = _gameplan_rel(project_dir, workstream)
    try:
        ignored = subprocess.run(
            ["git", "check-ignore", "-q", rel], cwd=project_dir, capture_output=True
        ).returncode == 0
    except FileNotFoundError:
        return []
    if ignored:
        return [Finding(
            "gameplan-ignored",
            f"{rel} is ignored by git, so the plan never leaves this machine. "
            "Run `daedalus init` to fix .gitignore, or un-ignore it by hand.",
        )]
    return []


# ---------- edicts ----------


def edicts_dir(project_dir: Path) -> Path:
    return project_dir / "docs" / "edicts"


def edicts_enabled(project_dir: Path) -> bool:
    """edicts.enabled (edict 0005): project, then global config, else whether docs/edicts/ exists."""
    from .config import edicts_setting

    return edicts_setting(project_dir)[0]


def load_edicts(project_dir: Path) -> list[dict]:
    """[{number, file, status}] for every docs/edicts/NNNN-*.md (README and dissents excluded)."""
    folder = edicts_dir(project_dir)
    if not folder.is_dir():
        return []
    edicts = []
    for path in sorted(folder.glob("*.md")):
        m = EDICT_FILE.match(path.name)
        if not m:
            continue
        status = STATUS_LINE.search(path.read_text(encoding="utf-8"))
        edicts.append({"number": m.group(1), "file": path.name, "status": status.group(1) if status else None})
    return edicts


def check_edict_status(edicts: list[dict]) -> list[Finding]:
    return [
        Finding(
            "edict-bad-status",
            f"{e['file']}: Status is {e['status']!r}, not one of {', '.join(EDICT_STATUSES)}.",
        )
        for e in edicts
        if (e["status"] or "").lower() not in EDICT_STATUSES
    ]


def check_duplicate_edicts(edicts: list[dict]) -> list[Finding]:
    by_number: dict[str, list[str]] = {}
    for e in edicts:
        by_number.setdefault(e["number"], []).append(e["file"])
    return [
        Finding("edict-duplicate-number", f"Edict {n} is used by {len(files)} files: {', '.join(files)}.")
        for n, files in sorted(by_number.items())
        if len(files) > 1
    ]


def _referenced_edicts(data: dict) -> set[str]:
    refs = set()
    entries = list(data.get("phases", []))
    active = data.get("activePhase") or {}
    entries += [active] + active.get("tasks", []) + active.get("deferred", [])
    for entry in entries:
        if entry.get("edict"):
            refs.add(str(entry["edict"]).zfill(4))
    return refs


def check_unreferenced_edicts(edicts: list[dict], data) -> list[Finding]:
    """data: one gameplan, or a list of them (every workstream)."""
    plans = data if isinstance(data, list) else [data]
    refs = set().union(*(_referenced_edicts(d) for d in plans)) if plans else set()
    return [
        Finding(
            "edict-not-in-gameplan",
            f"Accepted edict {e['number']} ({e['file']}) is not referenced by any gameplan phase or task.",
        )
        for e in edicts
        if (e["status"] or "").lower() == "accepted" and e["number"] not in refs
    ]


# ---------- memory files ----------


def _root_packages(project_dir: Path, max_depth: int = 4) -> list[Path]:
    """Python packages whose parent is not a package, skipping venvs, build output, and tests."""
    found = []

    def walk(folder: Path, depth: int):
        if depth > max_depth:
            return
        for child in sorted(folder.iterdir()):
            if not child.is_dir() or child.name.startswith(".") or child.name in SKIP_DIRS \
                    or child.name.endswith(".egg-info"):
                continue
            if (child / "__init__.py").exists():
                found.append(child)
            else:
                walk(child, depth + 1)

    walk(project_dir, 0)
    return found


def source_packages(project_dir: Path) -> list[str]:
    """Top-level source packages: the root packages, or a lone root package's direct subpackages."""
    roots = _root_packages(project_dir)
    if len(roots) == 1:
        subs = [c for c in sorted(roots[0].iterdir()) if c.is_dir() and (c / "__init__.py").exists()
                and c.name not in SKIP_DIRS]
        if subs:
            return [c.name for c in subs]
    return [r.name for r in roots]


def _is_empty_template(rel: str, text: str) -> bool:
    if rel.endswith("index.json"):
        try:
            return not json.loads(text).get("items")
        except (json.JSONDecodeError, AttributeError):
            return False
    return text.strip() == SESSION_START_READS[rel]


def check_project_map(project_dir: Path) -> list[Finding]:
    path = project_dir / ".daedalus" / "project-map.md"
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    if text.strip() in ("", "# Project Map"):
        return []  # an empty map isn't stale, just unwritten
    lowered = text.lower()
    missing = [
        name for name in source_packages(project_dir)
        if name.lower() not in lowered and name.lower().replace("_", "-") not in lowered
    ]
    if not missing:
        return []
    return [Finding(
        "project-map-missing-packages",
        f"project-map.md doesn't mention {len(missing)} source package(s): {', '.join(missing)}.",
    )]


def session_start_hook_registered(project_dir: Path) -> bool:
    for name in ("settings.json", "settings.local.json"):
        path = project_dir / ".claude" / name
        if path.exists() and ("daedalus hook session-start" in path.read_text(encoding="utf-8")
                              or "session-start.sh" in path.read_text(encoding="utf-8")):
            return True
    return False


def check_empty_templates_read(project_dir: Path, max_days: int, today: Optional[date] = None) -> list[Finding]:
    """Empty templates the hook reads that have stayed empty past max_days (a fresh init is fine)."""
    if not session_start_hook_registered(project_dir):
        return []
    today = today or date.today()
    findings = []
    for rel in SESSION_START_READS:
        path = project_dir / rel
        if not path.exists() or not _is_empty_template(rel, path.read_text(encoding="utf-8")):
            continue
        age = (today - date.fromtimestamp(path.stat().st_mtime)).days
        if age > max_days:
            findings.append(Finding(
                "empty-file-read-by-hook",
                f"{rel} has been an empty template for {age} days, but the session-start hook reads it "
                "every session. Start using it, or stop the hook reading it.",
            ))
    return findings


# ---------- entry point ----------


def check_collisions(plans: dict) -> list[Finding]:
    """Two workstreams with open work citing the same edict, or with overlapping path claims."""
    from . import workstreams as ws

    findings = []
    ids = sorted(plans)
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            shared = ws.open_edicts(plans[a]) & ws.open_edicts(plans[b])
            for number in sorted(shared):
                findings.append(Finding(
                    "collision-edict",
                    f"Workstreams {a} and {b} both have open work on edict {number}. Agree who takes what.",
                ))
            pairs = sorted({(x, y) for x in plans[a].get("claims", []) for y in plans[b].get("claims", [])
                            if ws.claims_overlap(x, y)})
            if pairs:
                listed = "; ".join(f"{x} / {y}" for x, y in pairs[:4]) + (" ..." if len(pairs) > 4 else "")
                findings.append(Finding(
                    "collision-claims",
                    f"Workstreams {a} and {b} claim overlapping paths: {listed}.",
                ))
    return findings


def run_checks(project_dir: Path, today: Optional[date] = None) -> tuple[list[Finding], list[str]]:
    """(findings, hints). Hints are informational and never fail the run."""
    from . import workstreams as ws

    project_dir = Path(project_dir)
    settings = get_project_settings(project_dir, "doctor")
    findings: list[Finding] = []
    hints: list[str] = []

    plans: dict = {}
    ids = ws.list_ids(project_dir)
    if not ids:
        hints.append("No gameplan in this project. `daedalus init` creates one.")
    several = len(ids) > 1
    for wid in ids:
        label = (lambda f, wid=wid: Finding(f.name, f"[{wid}] {f.message}")) if several else (lambda f: f)
        try:
            data = gp.load_gameplan(project_dir, wid)
        except json.JSONDecodeError as e:
            findings.append(label(Finding("gameplan-unreadable", f"{_gameplan_rel(project_dir, wid)} is not valid JSON: {e}")))
            continue
        plans[wid] = data
        author = ws.owner(data, wid).get("git_author") if wid != ws.DEFAULT else None
        found = check_commits_after_gameplan(project_dir, settings["stale_commits"], wid, author)
        found += check_phase_all_done(data)
        found += check_stale_tasks(data, settings["stale_task_days"], today=today)
        found += check_gameplan_ignored(project_dir, wid)
        findings += [label(f) for f in found]
    findings += check_collisions(plans)

    edicts = load_edicts(project_dir)
    findings += check_edict_status(edicts)
    findings += check_duplicate_edicts(edicts)
    if plans and edicts_enabled(project_dir):
        findings += check_unreferenced_edicts(edicts, list(plans.values()))

    findings += check_project_map(project_dir)
    findings += check_empty_templates_read(project_dir, settings["stale_task_days"], today=today)
    return findings, hints
