"""
Workstreams (edict 0008): one committed plan per owner, so concurrent work doesn't share a
single active phase.

A workstream is `.daedalus/gameplans/<id>.json`: the gameplan schema plus an `owner` block
(`id`, `kind`: person or session, `git_author`: a pattern for `git --author`) and optional
`claims` (paths or globs the owner intends to change). The existing
`.daedalus/roadmap/gameplan.json` is the default workstream, so a project with one plan works as
it always has.

The current workstream comes from DAEDALUS_WORKSTREAM, then `workstream.current` in the local
project config (.daedalus/config.json, not committed), then the default.
"""

from __future__ import annotations

import fnmatch
import json
import os
import re
from pathlib import Path
from typing import Any, Optional

DEFAULT = "default"
ENV = "DAEDALUS_WORKSTREAM"
ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
KINDS = ("person", "session")

_override: Optional[str] = None  # set by the CLI's --workstream for one command


class WorkstreamError(Exception):
    pass


def validate_id(workstream: str) -> str:
    """A workstream id: 'default', or lowercase letters/digits/'.'/'_'/'-' not ending in '.pending'."""
    if workstream == DEFAULT:
        return workstream
    if not ID.match(workstream) or workstream.endswith(".pending"):
        raise WorkstreamError(f"'{workstream}' is not a workstream id (lowercase letters, digits, '.', '_' "
                              "or '-'; not ending in '.pending')")
    return workstream


def set_override(workstream: Optional[str]) -> None:
    global _override
    _override = validate_id(workstream) if workstream else None


def gameplans_dir(project_dir: Path) -> Path:
    return Path(project_dir) / ".daedalus" / "gameplans"


def file_for(project_dir: Path, workstream: str) -> Path:
    if workstream == DEFAULT:
        return Path(project_dir) / ".daedalus" / "roadmap" / "gameplan.json"
    return gameplans_dir(project_dir) / f"{workstream}.json"


def current(project_dir: Path) -> str:
    if _override:
        return _override
    if os.environ.get(ENV):
        return validate_id(os.environ[ENV])
    from .config import load_project_overrides

    setting = load_project_overrides(project_dir).get("workstream", {})
    if isinstance(setting, dict) and setting.get("current"):
        return validate_id(str(setting["current"]))
    return DEFAULT


def list_ids(project_dir: Path) -> list[str]:
    ids = [DEFAULT] if file_for(project_dir, DEFAULT).exists() else []
    folder = gameplans_dir(project_dir)
    if folder.is_dir():
        ids += sorted(p.stem for p in folder.glob("*.json")
                      if not p.name.endswith(".pending.json") and ID.match(p.stem))
    return ids


def load(project_dir: Path, workstream: str) -> dict[str, Any]:
    path = file_for(project_dir, workstream)
    if not path.exists():
        raise WorkstreamError(f"No workstream '{workstream}' ({path})")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise WorkstreamError(f"{path} is not valid JSON: {e}")


def author_pattern_ok(project_dir: Path, pattern: str) -> bool:
    """Whether git accepts a --author pattern (an invalid regex makes git fail, not match nothing)."""
    import subprocess

    try:
        return subprocess.run(["git", "log", "-1", f"--author={pattern}", "--format=%H"], cwd=project_dir,
                              capture_output=True).returncode == 0
    except FileNotFoundError:
        return True


def owner(data: dict[str, Any], workstream: str) -> dict[str, Any]:
    return data.get("owner") or {"id": workstream, "kind": "person", "git_author": None}


def create(project_dir: Path, workstream: str, kind: str = "person", git_author: Optional[str] = None) -> Path:
    from .cli.gameplan import empty_gameplan

    if workstream == DEFAULT:
        raise WorkstreamError("'default' is the existing gameplan; pick another id")
    validate_id(workstream)
    if git_author and not author_pattern_ok(project_dir, git_author):
        raise WorkstreamError(f"--author {git_author!r} is not a pattern git accepts (git log --author)")
    if kind not in KINDS:
        raise WorkstreamError(f"kind must be one of {', '.join(KINDS)}")
    path = file_for(project_dir, workstream)
    if path.exists():
        raise WorkstreamError(f"Workstream '{workstream}' already exists")
    data = empty_gameplan()
    data["owner"] = {"id": workstream, "kind": kind, "git_author": git_author}
    data["claims"] = []
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return path


def use(project_dir: Path, workstream: str) -> None:
    """Make a workstream current in this checkout (local config, not committed)."""
    from .config import get_project_config_file, load_project_overrides

    validate_id(workstream)
    if workstream != DEFAULT and not file_for(project_dir, workstream).exists():
        raise WorkstreamError(f"No workstream '{workstream}'")
    path = get_project_config_file(project_dir)
    if path.exists():
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            raise WorkstreamError(f"{path} is not valid JSON; fix it before switching workstreams")
    data = load_project_overrides(project_dir)
    data.setdefault("workstream", {})["current"] = workstream
    path = get_project_config_file(project_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def set_claims(project_dir: Path, workstream: str, add=(), remove=()) -> list[str]:
    path = file_for(project_dir, workstream)
    data = load(project_dir, workstream)
    claims = [c for c in data.get("claims", []) if c not in remove]
    claims += [c for c in add if c not in claims]
    data["claims"] = claims
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return claims


# ---------- open work and collisions ----------


def open_edicts(data: dict[str, Any]) -> set[str]:
    """Edicts cited by open work: phases not done, and the active phase's tasks not done."""
    found = set()
    for phase in data.get("phases", []):
        if phase.get("edict") and phase.get("status") != "done":
            found.add(str(phase["edict"]).zfill(4))
    active = data.get("activePhase") or {}
    for task in active.get("tasks", []):
        if task.get("edict") and task.get("status") != "done":
            found.add(str(task["edict"]).zfill(4))
    return found


def _segments(claim: str) -> list[str]:
    parts = [p for p in claim.strip().split("/") if p not in ("", ".")]
    return parts


def _seg_overlap(x: str, y: str) -> bool:
    if x == y or fnmatch.fnmatchcase(x, y) or fnmatch.fnmatchcase(y, x):
        return True
    # Two globs in one segment (e.g. "a*" and "*b") can usually name the same file
    return any(c in x for c in "*?[") and any(c in y for c in "*?[")


def claims_overlap(a: str, b: str) -> bool:
    """
    Whether two path claims (files, directories, or globs; '**' spans directories) can name the
    same file. A shorter claim covers everything beneath it, like a directory.
    """
    def walk(xs: list[str], ys: list[str]) -> bool:
        if not xs or not ys:
            return True  # one claim is a prefix (directory) of the other
        if xs[0] == "**":
            return walk(xs[1:], ys) or walk(xs, ys[1:])
        if ys[0] == "**":
            return walk(xs, ys[1:]) or walk(xs[1:], ys)
        return _seg_overlap(xs[0], ys[0]) and walk(xs[1:], ys[1:])

    return walk(_segments(a), _segments(b))


def summary_line(data: dict[str, Any], workstream: str) -> str:
    """One line: owner, active phase, next open task."""
    who = owner(data, workstream)
    active = data.get("activePhase") or {}
    if not active:
        return f"{workstream} ({who.get('kind')}): no active phase"
    task = next((t for status in ("in_progress", "pending") for t in active.get("tasks", [])
                 if t.get("status") == status), None)
    nxt = f"next {task['id']} [{task['status']}] {task.get('title', '')}" if task else "no open task"
    return f"{workstream} ({who.get('kind')}): {active.get('id')} - {nxt}"


def others(project_dir: Path, me: str) -> list[str]:
    """
    The workstreams that make this a shared project, from `me`'s point of view: every workstream but
    `me`, leaving out the default one while nobody uses it (no active phase and no claims). A solo
    user with their own named workstream and an untouched default has none.
    """
    result = []
    for wid in list_ids(project_dir):
        if wid == me:
            continue
        if wid == DEFAULT:
            try:
                data = load(project_dir, wid)
            except WorkstreamError:
                continue
            if not data.get("activePhase") and not data.get("claims"):
                continue
        result.append(wid)
    return result
