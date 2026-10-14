"""
The reflection pending queue (edict 0010). Separate from 0007's `gameplan pending`.

A checked report's proposals are imported with Momus's verdicts. Entries he marked
`contradicted` are not imported. The user applies or drops each one, in a session:

- model proposals change the user or self model (recorded in its history);
- file proposals edit a skill, agent, CLAUDE.md or memory note;
- permission proposals add an allow rule to the project's .claude/settings.json;
- gameplan proposals are handed to `gameplan pending`, not applied here.

Stance proposals are applied one at a time, never as part of `all`.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Optional

from . import models as m
from .check import check_report
from .fsutil import atomic_write_text, file_lock, read_json, write_json
from .paths import reflection_dir

VERDICTS = ("shown", "consistent", "untested", "contradicted")


class PendingError(Exception):
    """A pending operation that can't proceed."""


def pending_path(project_dir: Path) -> Path:
    return reflection_dir(project_dir) / "pending.json"


def load_pending(project_dir: Path) -> list[dict]:
    data = read_json(pending_path(project_dir), {})
    return data.get("proposals", []) if isinstance(data, dict) else []


def _last_id(project_dir: Path) -> int:
    data = read_json(pending_path(project_dir), {})
    return int(data.get("last_id", 0)) if isinstance(data, dict) else 0


def _save(project_dir: Path, proposals: list[dict], last_id: Optional[int] = None) -> None:
    # IDs never repeat, even after the queue empties: the model history cites them
    last = max(last_id if last_id is not None else _last_id(project_dir),
               max((int(q["id"][1:]) for q in proposals if str(q.get("id", ""))[1:].isdigit()), default=0))
    write_json(pending_path(project_dir), {"proposals": proposals, "last_id": last})


def verdicts_path(report_path: Path) -> Path:
    return Path(report_path).with_suffix(".verdicts.json")


def import_report(project_dir: Path, report_path: Path, models_root: Optional[Path] = None,
                  bundle: Optional[dict] = None, scope: str = "work") -> tuple[list[dict], list[str]]:
    """Load a checked, reviewed report's proposals. Returns (added, notes)."""
    report = read_json(report_path)
    if not isinstance(report, dict):
        raise PendingError(f"{report_path} is not a JSON report")
    result = check_report(project_dir, report, models_root, bundle, scope)
    if result.errors:
        raise PendingError("The report does not pass `daedalus reflect check`:\n" + "\n".join(result.errors))
    verdicts = read_json(verdicts_path(report_path), {})
    if not isinstance(verdicts, dict):
        verdicts = {}
    notes: list[str] = []
    to_add = []
    for p in report.get("proposals") or []:
        v = verdicts.get(p.get("id")) or {}
        verdict = v.get("verdict") if isinstance(v, dict) else v
        if verdict not in VERDICTS:
            raise PendingError(f"Proposal {p.get('id')} has no Momus verdict in {verdicts_path(report_path).name}; "
                               "every proposal is reviewed before it is presented")
        if verdict == "contradicted":
            notes.append(f"{p.get('id')}: not imported, Momus found it contradicted ({v.get('note', '') if isinstance(v, dict) else ''})")
            continue
        to_add.append({**p, "verdict": verdict, "verdict_note": v.get("note", "") if isinstance(v, dict) else "",
                       "report": str(Path(report_path).name), "report_proposal": p.get("id"),
                       "level": report.get("level"), "period": report.get("period"),
                       "created": date.today().isoformat()})
    path = pending_path(project_dir)
    with file_lock(path):
        proposals = load_pending(project_dir)
        seen = {(q.get("report"), q.get("report_proposal")) for q in proposals}
        n = max(_last_id(project_dir),
                max((int(q["id"][1:]) for q in proposals if str(q.get("id", ""))[1:].isdigit()), default=0))
        added = []
        for q in to_add:
            if (q["report"], q["report_proposal"]) in seen:
                continue
            n += 1
            q["id"] = f"Q{n}"
            proposals.append(q)
            added.append(q)
        _save(project_dir, proposals, n)
    return added, notes


def is_stance(p: dict) -> bool:
    change = p.get("model") or {}
    return p.get("target") == "model" and ((change.get("entry") or {}).get("kind") == "stance"
                                           or change.get("kind") == "stance")


def _select(proposals: list[dict], which: str) -> list[dict]:
    chosen = proposals if which == "all" else [p for p in proposals if p.get("id") == which]
    if not chosen:
        raise PendingError(f"No pending reflection proposal '{which}'")
    return chosen


def apply(project_dir: Path, which: str, models_root: Optional[Path] = None) -> tuple[list[dict], list[str]]:
    """Apply one proposal (or all but stances). Returns (applied, notes)."""
    path = pending_path(project_dir)
    with file_lock(path):
        proposals = load_pending(project_dir)
        chosen = _select(proposals, which)
        applied, notes = [], []
        for p in chosen:
            if which == "all" and is_stance(p):
                notes.append(f"{p['id']}: a stance; apply it on its own (`daedalus reflect pending apply {p['id']}`)")
                continue
            _apply_one(project_dir, p, models_root, notes)
            applied.append(p)
        _save(project_dir, [p for p in proposals if p not in applied])
    return applied, notes


def drop(project_dir: Path, which: str) -> list[dict]:
    path = pending_path(project_dir)
    with file_lock(path):
        proposals = load_pending(project_dir)
        chosen = _select(proposals, which)
        _save(project_dir, [p for p in proposals if p not in chosen])
    return chosen


def _apply_one(project_dir: Path, p: dict, models_root: Optional[Path], notes: list[str]) -> None:
    target = p.get("target")
    if target == "model":
        change = dict(p["model"])
        model = change.pop("model")
        if change.get("op") == "add":
            entry = dict(change.get("entry") or {})
            entry.setdefault("label", p.get("label"))
            change["entry"] = entry
        m.apply_change(model, change, by="proposal", proposal_id=p["id"], root=models_root)
    elif target == "file":
        _apply_file(project_dir, p["file"])
    elif target == "permission":
        _apply_permission(project_dir, p["permission"])
    elif target == "gameplan":
        from ..cli import gameplan as gp

        spec = dict(p["gameplan"])
        spec.update({"source": "reflection", "created": date.today().isoformat(),
                     "resolution": spec.get("resolution", "")})
        if spec["kind"] == "task-status":
            spec.pop("kind")
        gp.add_proposals(project_dir, [spec])
        notes.append(f"{p['id']}: handed to `daedalus gameplan pending`; apply it there")
    else:
        raise PendingError(f"{p.get('id')}: unknown target {target}")


def _resolve(project_dir: Path, path: str) -> Path:
    target = Path(path)
    return target if target.is_absolute() else Path(project_dir) / target


def _apply_file(project_dir: Path, spec: dict) -> None:
    path = _resolve(project_dir, spec["path"])
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    if spec["op"] == "append":
        addition = spec.get("text", "")
        new = text + ("" if not text or text.endswith("\n") else "\n") + addition.rstrip("\n") + "\n"
    else:
        old = spec.get("old", "")
        if not old or text.count(old) != 1:
            raise PendingError(f"{spec['path']}: the text to replace must occur exactly once")
        new = text.replace(old, spec.get("new", ""))
    atomic_write_text(path, new)


def _apply_permission(project_dir: Path, spec: dict) -> None:
    path = _resolve(project_dir, spec.get("path") or ".claude/settings.json")
    data = read_json(path, {}) if path.exists() else {}
    if not isinstance(data, dict):
        raise PendingError(f"{path} is not a JSON object")
    allow = data.setdefault("permissions", {}).setdefault("allow", [])
    if spec["allow"] not in allow:
        allow.append(spec["allow"])
    atomic_write_text(path, json.dumps(data, indent=2) + "\n")
