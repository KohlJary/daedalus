"""
Memory reconstruction (edict 0006).

When the gameplan has fallen behind the code, the missing period is rebuilt from evidence:

1. `gather` (here, deterministic, no model calls) finds the gap and writes an evidence bundle:
   every commit in the window with a score for how much its message says, diffs for the commits
   whose messages say little (plus a sample of the rest, to keep the score honest), release
   commits, documents added in the window, roadmap changes, the open gameplan tasks and roadmap
   items, and listings of configured evidence paths outside git.
2. The `mnemosyne` agent turns the bundle into a proposal (PROPOSAL_SCHEMA below).
3. `check` (here, deterministic) validates the proposal against the repository.
4. Momus reviews it; a human imports it into `daedalus gameplan pending` and applies or drops
   each entry. Nothing here writes to the gameplan or roadmap.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from .cli import gameplan as gp
from .config import get_project_settings, load_project_overrides

BUNDLE_SCHEMA = "daedalus.reconstruction-bundle/1"
PROPOSAL_SCHEMA = "daedalus.reconstruction/1"
OUT_DIR = Path(".daedalus") / "reconstruction"

GENERIC_SUBJECT = re.compile(
    r"^\W*(fix(es|ed)?|wip|update[sd]?|changes?|stuff|misc|tmp|temp|minor|cleanup|tweaks?|more|"
    r"work|edits?|refactor|test(s|ing)?|commit|save|asdf|\.+)\W*(stuff|things|changes|fixes)?\W*$",
    re.IGNORECASE,
)
REFERENCE = re.compile(
    r"(#\d+|\b[A-Z][A-Za-z]*-[a-z]{0,3}\d+\b|\bedict \d{4}\b|\bP\d+[a-z]?\b|\b[A-Z]{2,}-\d+\b)"
)
MAX_FILES = 30  # per commit in the bundle; files_changed has the full count
RELEASE_SUBJECT = re.compile(r"^(release\b|v?\d+\.\d+\.\d+\b|bump version)", re.IGNORECASE)


# ---------- scoring ----------


@dataclass
class Score:
    total: int
    has_body: bool
    body_chars: int
    references: list[str]
    specific_subject: bool
    message_to_diff: Optional[float]  # message chars per changed line; None when nothing changed


def score_message(subject: str, body: str, lines_changed: int) -> Score:
    """
    How much a commit message tells a reader, 0-100. Deterministic.

    has a body: 30; body length: up to 20 (one point per 40 chars); references a task, issue, or
    edict ID: 20; a specific subject (not "fix", "wip", "updates"; at least 3 words): 20; message
    size relative to the diff: up to 10 (full marks at one message char per changed line).
    """
    body = body.strip()
    refs = sorted(set(REFERENCE.findall(f"{subject}\n{body}")))
    specific = not GENERIC_SUBJECT.match(subject) and len(subject.split()) >= 3
    msg_chars = len(subject) + len(body)
    ratio = msg_chars / lines_changed if lines_changed else None
    total = (
        (30 if body else 0)
        + min(20, len(body) // 40)
        + (20 if refs else 0)
        + (20 if specific else 0)
        + (10 if ratio is None else min(10, int(ratio * 10)))
    )
    return Score(total, bool(body), len(body), refs, specific, None if ratio is None else round(ratio, 2))


# ---------- git helpers ----------


def _git(project_dir: Path, *args: str, check: bool = True) -> str:
    try:
        return subprocess.run(
            ["git", *args], cwd=project_dir, capture_output=True, text=True, check=check,
            encoding="utf-8", errors="replace",
        ).stdout
    except (subprocess.CalledProcessError, FileNotFoundError):
        return ""


def find_window(project_dir: Path, since: Optional[str] = None) -> Optional[dict]:
    """
    The gap: from the gameplan's last commit (or `since`) to HEAD. A gameplan that was never
    committed falls back to its file time. Returns None when there is no gameplan and no `since`.
    """
    head = _git(project_dir, "rev-parse", "HEAD").strip()
    if not head:
        return None
    rel = str(gp.GameplanPaths.for_project(project_dir).gameplan_file.relative_to(project_dir))
    if since:
        base = _git(project_dir, "rev-parse", since).strip()
        if not base:
            raise ValueError(f"Unknown revision: {since}")
        return {"from": base, "from_date": _git(project_dir, "log", "-1", "--format=%as", base).strip(),
                "to": head, "range": [f"{base}..HEAD"], "anchor": f"--since {since}"}
    last = _git(project_dir, "log", "-1", "--format=%H %as", "--", rel).strip()
    if last:
        base, when = last.split()
        return {"from": base, "from_date": when, "to": head, "range": [f"{base}..HEAD"],
                "anchor": "last gameplan commit"}
    path = gp.GameplanPaths.for_project(project_dir).gameplan_file
    if not path.exists():
        return None
    stamp = datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds")
    return {"from": None, "from_date": stamp[:10], "to": head, "range": [f"--since={stamp}", "HEAD"],
            "anchor": "gameplan file time (gameplan has no commits)"}


def window_commits(project_dir: Path, window: dict) -> list[dict]:
    out = _git(project_dir, "log", "--reverse", "--no-merges",
               "--format=%x1e%H%x1f%as%x1f%s%x1f%b%x1f", "--numstat", *window["range"])
    commits = []
    for record in out.split("\x1e"):
        if not record.strip():
            continue
        sha, day, subject, body, stats = (record.split("\x1f") + ["", "", "", "", ""])[:5]
        files, lines = [], 0
        for row in stats.strip().splitlines():
            parts = row.split("\t")
            if len(parts) == 3:
                added, removed, name = parts
                files.append(name)
                lines += (int(added) if added.isdigit() else 0) + (int(removed) if removed.isdigit() else 0)
        commits.append({"sha": sha.strip(), "date": day, "subject": subject, "body": body.strip(),
                        "files": files[:MAX_FILES], "files_changed": len(files), "lines_changed": lines})
    merges = _git(project_dir, "rev-list", "--count", "--merges", *window["range"]).strip()
    window["merge_commits"] = int(merges or 0)
    return commits


def _diff(project_dir: Path, sha: str, cap: int) -> dict:
    stat = _git(project_dir, "show", "--stat", "--format=", sha).strip()
    patch = _git(project_dir, "show", "--format=", "--no-color", sha)
    truncated = len(patch) > cap
    return {"stat": stat, "patch": patch[:cap], "truncated": truncated}


# ---------- gather ----------


@dataclass
class Bundle:
    schema: str
    created: str
    project: str
    window: dict
    evidence_scope: str
    settings: dict
    commits: list = field(default_factory=list)
    releases: list = field(default_factory=list)
    documents_added: list = field(default_factory=list)
    roadmap_diff: dict = field(default_factory=dict)
    open_tasks: list = field(default_factory=list)
    open_roadmap_items: list = field(default_factory=list)
    outside_git: list = field(default_factory=list)


def _open_tasks(project_dir: Path) -> list[dict]:
    try:
        data = gp.load_gameplan(project_dir)
    except (gp.GameplanError, json.JSONDecodeError):
        return []
    active = data.get("activePhase") or {}
    return [
        {"phase": active.get("id"), "id": t.get("id"), "title": t.get("title"),
         "status": t.get("status"), "details": t.get("details", "")}
        for t in active.get("tasks", []) if t.get("status") != "done"
    ]


def _open_roadmap(project_dir: Path) -> list[dict]:
    path = project_dir / ".daedalus" / "roadmap" / "index.json"
    try:
        items = json.loads(path.read_text(encoding="utf-8")).get("items", [])
    except (OSError, json.JSONDecodeError, AttributeError):
        return []
    return [{"id": i.get("id"), "title": i.get("title"), "status": i.get("status")}
            for i in items if i.get("status") != "done"]


def _outside_git(project_dir: Path, paths: list[str], since_date: str, limit: int = 200) -> list[dict]:
    """Listings (name, size, modified) of configured evidence paths, newest first, since the window."""
    listings = []
    for rel in paths:
        root = project_dir / rel
        if not root.exists():
            listings.append({"path": rel, "missing": True, "files": []})
            continue
        files = [p for p in root.rglob("*") if p.is_file()] if root.is_dir() else [root]
        rows = []
        for f in files:
            modified = datetime.fromtimestamp(f.stat().st_mtime)
            if modified.date().isoformat() >= since_date:
                rows.append({"file": str(f.relative_to(project_dir)), "bytes": f.stat().st_size,
                             "modified": modified.isoformat(timespec="seconds")})
        rows.sort(key=lambda r: r["modified"], reverse=True)
        listings.append({"path": rel, "missing": False, "count": len(rows), "files": rows[:limit],
                         "truncated": len(rows) > limit})
    return listings


def reconstruct_settings(project_dir: Path) -> dict:
    """reconstruct.* from config, plus evidence_paths (a list, set in .daedalus/config.json)."""
    settings = get_project_settings(project_dir, "reconstruct")
    override = load_project_overrides(project_dir).get("reconstruct", {})
    paths = override.get("evidence_paths", []) if isinstance(override, dict) else []
    settings["evidence_paths"] = [p for p in paths if isinstance(p, str)]
    return settings


def gather(project_dir: Path, since: Optional[str] = None) -> Optional[Bundle]:
    """Build the evidence bundle, or None when there is no gap."""
    project_dir = Path(project_dir)
    window = find_window(project_dir, since)
    if window is None:
        raise ValueError("No gameplan and no --since revision: nothing to measure the gap from.")
    commits = window_commits(project_dir, window)
    if not commits:
        return None
    settings = reconstruct_settings(project_dir)

    scored = []
    for c in commits:
        s = score_message(c["subject"], c["body"], c["lines_changed"])
        c["score"] = asdict(s)
        scored.append(c)
    low = [c for c in scored if c["score"]["total"] < settings["score_threshold"]]
    high = sorted((c for c in scored if c["score"]["total"] >= settings["score_threshold"]),
                  key=lambda c: c["sha"])  # hash order: deterministic but unrelated to content
    sample = {c["sha"] for c in high[: settings["sample_size"]]}
    for c in scored:
        if c in low:
            c["diff"], c["diff_reason"] = _diff(project_dir, c["sha"], settings["diff_cap"]), "low score"
        elif c["sha"] in sample:
            c["diff"], c["diff_reason"] = _diff(project_dir, c["sha"], settings["diff_cap"]), "calibration sample"

    doc_prefixes = tuple(settings["doc_paths"])
    added = _git(project_dir, "log", "--diff-filter=A", "--no-merges", "--format=%x1e%H",
                 "--name-only", *window["range"])
    documents = []
    for record in added.split("\x1e"):
        lines = [l for l in record.strip().splitlines() if l]
        if len(lines) > 1:
            documents += [{"sha": lines[0], "file": f} for f in lines[1:]
                          if f.startswith(doc_prefixes) or f in doc_prefixes]

    roadmap_rel = ".daedalus/roadmap/index.json"
    committed = (_git(project_dir, "diff", window["from"], "HEAD", "--", roadmap_rel)
                 if window["from"] else "")
    uncommitted = _git(project_dir, "diff", "HEAD", "--", roadmap_rel)

    outside = _outside_git(project_dir, settings["evidence_paths"], window["from_date"])
    return Bundle(
        schema=BUNDLE_SCHEMA,
        created=date.today().isoformat(),
        project=project_dir.name,
        window={**{k: v for k, v in window.items() if k != "range"}, "commits": len(commits)},
        evidence_scope="git+paths" if settings["evidence_paths"] else "git",
        settings=settings,
        commits=scored,
        releases=[{"sha": c["sha"], "date": c["date"], "subject": c["subject"]}
                  for c in scored if RELEASE_SUBJECT.match(c["subject"])],
        documents_added=documents,
        roadmap_diff={"committed": committed, "uncommitted": uncommitted},
        open_tasks=_open_tasks(project_dir),
        open_roadmap_items=_open_roadmap(project_dir),
        outside_git=outside,
    )


def write_bundle(project_dir: Path, bundle: Bundle) -> Path:
    out = Path(project_dir) / OUT_DIR / f"bundle-{bundle.created}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(asdict(bundle), indent=2) + "\n", encoding="utf-8")
    return out


# ---------- proposal check ----------
#
# A proposal (written by the mnemosyne agent) looks like:
#
# {
#   "schema": "daedalus.reconstruction/1",
#   "window": {"from": "<sha or null>", "from_date": "YYYY-MM-DD", "to": "<sha>"},   # from the bundle
#   "evidence_scope": "git" | "git+paths",
#   "updates": [   # status changes to existing gameplan tasks
#     {"task": "T-a1", "proposed_status": "done" | "in_progress" | "pending" | "needs-confirmation",
#      "confidence": "shown" | "inferred" | "unknown", "basis": "messages" | "diffs" | "both" | "outside-git",
#      "resolution": "...", "commits": ["<sha>"], "files": ["path"], "cheapest_check": "..."}
#   ],
#   "phases": [    # missing phases, each with its tasks
#     {"id": "...", "title": "...", "status": "done", "confidence": ..., "basis": ..., "goal": "...",
#      "commits": [...], "tasks": [{"id", "title", "status", "confidence", "basis", "resolution", "commits"}]}
#   ],
#   "roadmap": [   # roadmap items whose status disagrees with the evidence
#     {"item": "<id>", "current_status": "backlog", "proposed_status": "done", "confidence": ..., "basis": ...,
#      "commits": [...]}
#   ],
#   "conflicts": [{"about": "...", "sources": ["<sha or path>", ...]}],   # both recorded, neither chosen
#   "context_commits": ["<sha>"],   # commits before the window cited as background
#   "files": ["path"]               # other files the proposal relies on
# }

CONFIDENCE = ("shown", "inferred", "unknown")
BASIS = ("messages", "diffs", "both", "outside-git")
UPDATE_STATUSES = ("done", "in_progress", "pending", "needs-confirmation")
HASH = re.compile(r"\b(?=[0-9a-f]*[a-f])(?=[0-9a-f]*\d)[0-9a-f]{7,40}\b")
PATH_REF = re.compile(r"(?<![\w/.-])((?:[\w.-]+/)*[\w.-]+\.(?:md|json|jsonl|py|ya?ml|txt|toml))(?::\d+(?:-\d+)?)?\b")
TEXT_FIELDS = ("resolution", "note", "notes", "goal", "evidence", "cheapest_check", "about", "title")


@dataclass
class CheckResult:
    errors: list = field(default_factory=list)
    uncited: list = field(default_factory=list)
    labels: dict = field(default_factory=dict)
    entries: int = 0


def _entries(proposal: dict):
    """(where, entry, kind) for every labelled entry in the proposal."""
    for i, u in enumerate(proposal.get("updates", [])):
        yield f"updates[{i}] ({u.get('task')})", u, "update"
    for i, ph in enumerate(proposal.get("phases", [])):
        yield f"phases[{i}] ({ph.get('id')})", ph, "phase"
        for j, t in enumerate(ph.get("tasks", [])):
            yield f"phases[{i}].tasks[{j}] ({t.get('id')})", t, "task"
    for i, r in enumerate(proposal.get("roadmap", [])):
        yield f"roadmap[{i}] ({r.get('item')})", r, "roadmap"


def _cited(entry: dict) -> list[str]:
    shas = list(entry.get("commits", []))
    for key in TEXT_FIELDS:
        if isinstance(entry.get(key), str):
            shas += HASH.findall(entry[key])
    return shas


def _text_paths(obj) -> list[str]:
    found = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in TEXT_FIELDS or k == "description":
                found += _text_paths(v) if not isinstance(v, str) else PATH_REF.findall(v)
            elif isinstance(v, (dict, list)):
                found += _text_paths(v)
    elif isinstance(obj, list):
        for v in obj:
            found += _text_paths(v)
    return found


def _file_exists(project_dir: Path, rel: str, tracked: list[str]) -> bool:
    if (project_dir / rel).exists():
        return True
    name = rel.rsplit("/", 1)[-1]
    return any(t == rel or t.endswith("/" + rel) or (rel == name and t.rsplit("/", 1)[-1] == name)
               for t in tracked)


def check_proposal(project_dir: Path, proposal: dict) -> CheckResult:
    project_dir = Path(project_dir)
    result = CheckResult()
    err = result.errors.append

    if proposal.get("schema") != PROPOSAL_SCHEMA:
        err(f"schema is {proposal.get('schema')!r}, expected {PROPOSAL_SCHEMA!r}")
    window = proposal.get("window") or {}
    to = window.get("to") or "HEAD"
    if window.get("from"):
        rng = [f"{window['from']}..{to}"]
    elif window.get("from_date"):
        rng = [f"--since={window['from_date']}", to]
    else:
        err("window has neither 'from' nor 'from_date'")
        rng = [to]
    in_window = _git(project_dir, "rev-list", *rng).split()
    non_merge = _git(project_dir, "rev-list", "--no-merges", *rng).split()
    context = proposal.get("context_commits", [])

    def resolve(sha: str) -> Optional[str]:
        full = _git(project_dir, "rev-parse", "--verify", "--quiet", f"{sha}^{{commit}}", check=False).strip()
        return full or None

    tracked = _git(project_dir, "ls-files").splitlines()
    open_tasks = {t["id"] for t in _open_tasks(project_dir)}
    cited_all: set[str] = set()

    for c in context:
        if not resolve(c):
            err(f"context_commits: {c} is not a commit in this repository")

    for where, entry, kind in _entries(proposal):
        result.entries += 1
        conf = entry.get("confidence")
        result.labels[conf] = result.labels.get(conf, 0) + 1
        if conf not in CONFIDENCE:
            err(f"{where}: confidence is {conf!r}, not one of {', '.join(CONFIDENCE)}")
        if conf != "unknown" and entry.get("basis") not in BASIS:
            err(f"{where}: basis is {entry.get('basis')!r}, not one of {', '.join(BASIS)}")

        shas = _cited(entry)
        if conf in ("shown", "inferred") and kind != "phase" and not shas:
            err(f"{where}: confidence {conf} but cites no commit")
        for sha in shas:
            full = resolve(sha)
            if not full:
                err(f"{where}: {sha} is not a commit in this repository")
            elif full not in in_window and not any(full.startswith(c) or c.startswith(full[:len(c)]) for c in context):
                err(f"{where}: {sha} is outside the window and not listed in context_commits")
            else:
                cited_all.add(full)

        for rel in entry.get("files", []):
            if not _file_exists(project_dir, rel, tracked):
                err(f"{where}: file {rel} does not exist")

        if kind == "update":
            status = entry.get("proposed_status")
            if status not in UPDATE_STATUSES:
                err(f"{where}: proposed_status {status!r}, not one of {', '.join(UPDATE_STATUSES)}")
            if status == "done" and conf != "shown":
                err(f"{where}: proposes done on {conf!r} evidence; done needs 'shown' "
                    "(use needs-confirmation with a cheapest_check)")
            if status == "needs-confirmation" and not entry.get("cheapest_check"):
                err(f"{where}: needs-confirmation without a cheapest_check")
            if entry.get("task") not in open_tasks:
                err(f"{where}: task {entry.get('task')!r} is not an open task in the active phase")

    for i, c in enumerate(proposal.get("conflicts", [])):
        if len(c.get("sources", [])) < 2:
            err(f"conflicts[{i}]: a conflict records at least two sources")
        for sha in HASH.findall(" ".join(c.get("sources", []))):
            full = resolve(sha)
            if full:
                cited_all.add(full)

    for rel in proposal.get("files", []) + _text_paths(proposal):
        if not _file_exists(project_dir, rel, tracked):
            err(f"file {rel} is referenced but does not exist")

    result.uncited = [sha for sha in non_merge if sha not in cited_all]
    return result
