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


def set_override(workstream: Optional[str]) -> None:
    global _override
    _override = workstream


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
        return os.environ[ENV]
    from .config import load_project_overrides

    setting = load_project_overrides(project_dir).get("workstream", {})
    if isinstance(setting, dict) and setting.get("current"):
        return str(setting["current"])
    return DEFAULT


def list_ids(project_dir: Path) -> list[str]:
    ids = [DEFAULT] if file_for(project_dir, DEFAULT).exists() else []
    folder = gameplans_dir(project_dir)
    if folder.is_dir():
        ids += sorted(p.stem for p in folder.glob("*.json") if not p.name.endswith(".pending.json"))
    return ids


def load(project_dir: Path, workstream: str) -> dict[str, Any]:
    path = file_for(project_dir, workstream)
    if not path.exists():
        raise WorkstreamError(f"No workstream '{workstream}' ({path})")
    return json.loads(path.read_text(encoding="utf-8"))


def owner(data: dict[str, Any], workstream: str) -> dict[str, Any]:
    return data.get("owner") or {"id": workstream, "kind": "person", "git_author": None}


def create(project_dir: Path, workstream: str, kind: str = "person", git_author: Optional[str] = None) -> Path:
    from .cli.gameplan import empty_gameplan

    if workstream == DEFAULT or not ID.match(workstream):
        raise WorkstreamError("A workstream id is lowercase letters, digits, '.', '_' or '-', and not 'default'")
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

    if workstream != DEFAULT and not file_for(project_dir, workstream).exists():
        raise WorkstreamError(f"No workstream '{workstream}'")
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


def claims_overlap(a: str, b: str) -> bool:
    """Whether two path claims (paths, directories, or globs) can name the same file."""
    a, b = a.rstrip("/"), b.rstrip("/")
    if a == b or fnmatch.fnmatch(a, b) or fnmatch.fnmatch(b, a):
        return True
    return a.startswith(b + "/") or b.startswith(a + "/")


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
