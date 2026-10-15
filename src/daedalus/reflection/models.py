"""
The user model and the self model (edict 0010).

Both live per machine in the global config directory (`models/user.json`, `models/self.json`),
with one append-only history (`models/history.jsonl`) of every change: date, model, entry, kind,
before and after, evidence, the proposal it came from, and who made it.

- Entries keep their ID through revision and retirement, so an entry's history can be followed.
- Confidence decays exponentially from `last_affirmed` when read, and is never written back.
  `stable` entries and aspirations do not decay.
- The user may edit either file by hand. A content hash, stored after every write, notices it on
  the next read, and the difference is recorded as a user edit. Deleted entries leave a
  tombstone, so they are not proposed again.
- `forget` (user model only) removes an entry; with `reflection.forget: purge` it also removes
  the entry's history, the one exception to append-only history.
- Aspirations are written by Daedalus itself (`aspire`), without the pending step.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Optional

from .fsutil import append_line, atomic_write_text, file_lock, read_json, write_json
from .paths import models_dir

SCHEMA_VERSION = 1
MODELS = ("user", "self")
SELF_KINDS = ("behavior", "interpretation", "stance", "aspiration")
SCOPES = ("private", "work", "anywhere")
# The earlier names, read wherever a scope is read; entries are written with the new names
SCOPE_ALIASES = {"personal": "private", "any": "anywhere"}
LABELS = ("shown", "inferred", "unknown")
USER_FORBIDDEN_CATEGORIES = ("character", "health", "mood", "private-life", "private_life", "personal-life")
WORKING_PREFERENCE = "working-preference"
ASPIRATION_UNMOVED_DAYS = 90


class ModelError(Exception):
    """A model operation that can't proceed."""


def model_path(model: str, root: Optional[Path] = None) -> Path:
    if model not in MODELS:
        raise ModelError(f"Unknown model '{model}' (user or self)")
    return (root or models_dir()) / f"{model}.json"


def history_path(root: Optional[Path] = None) -> Path:
    return (root or models_dir()) / "history.jsonl"


def _state_path(root: Optional[Path]) -> Path:
    return (root or models_dir()) / ".state.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def canon_scope(scope: Optional[str], default: str = "anywhere") -> str:
    """A scope under its current name (personal -> private, any -> anywhere)."""
    if not scope:
        return default
    return SCOPE_ALIASES.get(str(scope), str(scope))


def same_observation(data: dict, observation: str, exclude_id: Optional[str] = None) -> Optional[dict]:
    """An active entry saying the same thing (compared after normalising case and punctuation)."""
    key = normalise(observation)
    if not key:
        return None
    for e in data.get("entries", []):
        if e.get("status", "active") == "active" and e.get("id") != exclude_id and normalise(e.get("observation", "")) == key:
            return e
    return None


def normalise(text: str) -> str:
    return re.sub(r"\W+", " ", (text or "").lower()).strip()


def _empty(model: str) -> dict:
    return {"schema_version": SCHEMA_VERSION, "model": model, "entries": [], "tombstones": []}


def _serialise(data: dict) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


# ---------- history ----------


def record(root: Optional[Path], model: str, entry_id: str, kind: str, before: Any, after: Any,
           by: str, evidence: Any = None, proposal_id: Optional[str] = None, note: str = "") -> dict:
    rec = {"at": _now(), "model": model, "entry_id": entry_id, "kind": kind, "before": before,
           "after": after, "evidence": evidence or [], "proposal_id": proposal_id, "by": by}
    if note:
        rec["note"] = note
    path = history_path(root)
    with file_lock(path):
        append_line(path, json.dumps(rec, ensure_ascii=False))
    return rec


def load_history(root: Optional[Path] = None, model: Optional[str] = None,
                 entry_id: Optional[str] = None) -> list[dict]:
    path = history_path(root)
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if (model is None or rec.get("model") == model) and (entry_id is None or rec.get("entry_id") == entry_id):
            out.append(rec)
    return out


# ---------- load and save, noticing hand edits ----------


def load(model: str, root: Optional[Path] = None) -> dict:
    """The model as stored. A hand edit since the last write is recorded as a user edit first."""
    path = model_path(model, root)
    with file_lock(path):
        return _load_locked(model, root)


def _load_locked(model: str, root: Optional[Path]) -> dict:
    path = model_path(model, root)
    state = read_json(_state_path(root), {}) or {}
    mine = state.get(model) or {}
    if not path.exists():
        if mine.get("snapshot"):
            # The whole file was deleted by hand: every entry counts as deleted by the user
            data = _empty(model)
            _record_hand_edit(root, model, mine["snapshot"], data)
            _save_locked(model, data, root)
            return data
        return _empty(model)
    text = path.read_text(encoding="utf-8-sig")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise ModelError(f"{path} is not valid JSON ({e}); fix it by hand, then run the command again")
    data.setdefault("entries", [])
    data.setdefault("tombstones", [])
    if mine.get("hash") and mine["hash"] != _hash(text):
        _record_hand_edit(root, model, mine.get("snapshot") or _empty(model), data)
        _save_locked(model, data, root)
    elif not mine.get("hash"):
        if data["entries"]:
            # Written by hand before reflection ever saved it: the user's entries
            _record_hand_edit(root, model, _empty(model), data)
        _save_state(root, model, text, data)
    return data


def _record_hand_edit(root: Optional[Path], model: str, before: dict, after: dict) -> None:
    old = {e["id"]: e for e in before.get("entries", []) if "id" in e}
    new = {e["id"]: e for e in after.get("entries", []) if "id" in e}
    for entry_id, entry in new.items():
        if entry_id not in old:
            record(root, model, entry_id, "user-edit", None, entry, by="user", note="added by hand")
        elif old[entry_id] != entry:
            note = "aspiration rewritten by hand" if entry.get("kind") == "aspiration" \
                and old[entry_id].get("observation") != entry.get("observation") else "edited by hand"
            record(root, model, entry_id, "user-edit", old[entry_id], entry, by="user", note=note)
    for entry_id, entry in old.items():
        if entry_id not in new:
            after.setdefault("tombstones", []).append(_tombstone(entry, "deleted by user"))
            record(root, model, entry_id, "user-delete", entry, None, by="user", note="deleted by hand")


def _text_hash(text: str) -> str:
    return _hash(normalise(text))


def _tombstone(entry: dict, reason: str) -> dict:
    """Enough to refuse the same observation again, and nothing more: the text itself is gone."""
    return {"id": entry.get("id"), "date": date.today().isoformat(), "reason": reason,
            "observation_hash": _text_hash(entry.get("observation", ""))}


def _save_state(root: Optional[Path], model: str, text: str, data: dict) -> None:
    path = _state_path(root)
    state = read_json(path, {}) or {}
    state[model] = {"hash": _hash(text), "snapshot": copy.deepcopy(data)}
    write_json(path, state)


def _save_locked(model: str, data: dict, root: Optional[Path]) -> None:
    text = _serialise(data)
    atomic_write_text(model_path(model, root), text)
    _save_state(root, model, text, data)


# ---------- reading ----------


def find(data: dict, entry_id: str) -> Optional[dict]:
    return next((e for e in data["entries"] if e.get("id") == entry_id), None)


def is_tombstoned(data: dict, entry_id: Optional[str] = None, observation: Optional[str] = None) -> bool:
    digest = _text_hash(observation) if normalise(observation or "") else None
    return any((entry_id and t.get("id") == entry_id) or (digest and t.get("observation_hash") == digest)
               for t in data.get("tombstones", []))


def half_life(model: str, settings: dict) -> int:
    return int(settings.get("half_life_self" if model == "self" else "half_life_user", 60 if model == "self" else 180))


def effective_confidence(entry: dict, today: date, half_life_days: int) -> float:
    """Exponential decay from last_affirmed, halving every half-life. Computed, never stored."""
    base = float(entry.get("confidence") or 0)
    if entry.get("stable") or entry.get("kind") == "aspiration":
        return base
    stamp = entry.get("last_affirmed") or entry.get("first_noticed")
    if not stamp:
        return base
    age = (today - date.fromisoformat(stamp[:10])).days
    return base * 0.5 ** (max(age, 0) / half_life_days)


def evidence_sessions(entry: dict) -> set[str]:
    return {e["session"] for e in entry.get("evidence", []) if isinstance(e, dict) and e.get("session")}


# ---------- changes (through apply, or by Daedalus for aspirations) ----------


def _next_id(data: dict, model: str) -> str:
    prefix = "u" if model == "user" else "s"
    used = {e.get("id") for e in data["entries"]} | {t.get("id") for t in data.get("tombstones", [])}
    n = 1
    while f"{prefix}{n:03d}" in used:
        n += 1
    return f"{prefix}{n:03d}"


def apply_change(model: str, change: dict, by: str, proposal_id: Optional[str] = None,
                 root: Optional[Path] = None, today: Optional[date] = None) -> dict:
    """
    Apply one change to a model: {"op": add|affirm|revise|retire, ...}. Validation of what a
    proposal may claim happens in `check`; this enforces only what keeps the model coherent.
    """
    today = today or date.today()
    path = model_path(model, root)
    with file_lock(path):
        data = _load_locked(model, root)
        op = change.get("op")
        if op == "add":
            entry = dict(change["entry"])
            if is_tombstoned(data, entry.get("id"), entry.get("observation")):
                raise ModelError("That observation was deleted or forgotten by the user; it is not added again")
            entry.setdefault("id", _next_id(data, model))
            if find(data, entry["id"]):
                raise ModelError(f"Entry {entry['id']} already exists")
            twin = same_observation(data, entry.get("observation", ""))
            if twin is not None:
                raise ModelError(f"{twin['id']} already says this; affirm it with new evidence instead of adding a copy")
            entry.setdefault("first_noticed", today.isoformat())
            entry.setdefault("last_affirmed", today.isoformat())
            entry.setdefault("status", "active")
            entry["scope"] = canon_scope(entry.get("scope"))
            entry.setdefault("stable", False)
            entry.setdefault("evidence", [])
            entry.setdefault("model_ids", [])
            data["entries"].append(entry)
            before, after = None, entry
        else:
            entry = find(data, change.get("id", ""))
            if entry is None:
                raise ModelError(f"No entry {change.get('id')} in the {model} model")
            before = copy.deepcopy(entry)
            if op == "affirm":
                new_sessions = {e.get("session") for e in change.get("evidence", []) if isinstance(e, dict)} - {None}
                if not new_sessions - evidence_sessions(entry):
                    raise ModelError(f"An affirmation of {entry['id']} must cite a session not already in its evidence")
                entry["evidence"] = entry.get("evidence", []) + list(change["evidence"])
                entry["last_affirmed"] = today.isoformat()
                for mid in change.get("model_ids", []):
                    if mid not in entry.setdefault("model_ids", []):
                        entry["model_ids"].append(mid)
            elif op == "revise":
                for key in ("observation", "confidence", "label", "category", "scope"):
                    if key in change.get("changes", {}):
                        entry[key] = change["changes"][key]
                if "scope" in change.get("changes", {}):
                    entry["scope"] = canon_scope(entry["scope"])
                if change.get("evidence"):
                    entry["evidence"] = entry.get("evidence", []) + list(change["evidence"])
            elif op == "retire":
                entry["status"] = "retired"
                entry["retired"] = {"date": today.isoformat(), "reason": change.get("reason", "")}
            else:
                raise ModelError(f"Unknown change '{op}'")
            after = copy.deepcopy(entry)
        _save_locked(model, data, root)
        record(root, model, after["id"], op, before, after, by=by,
               evidence=change.get("evidence") or (change.get("entry") or {}).get("evidence"),
               proposal_id=proposal_id)
        return after


def aspire(text: str, model_id: str, period: str, category: str = "aspiration",
           root: Optional[Path] = None, today: Optional[date] = None) -> dict:
    """An aspiration, written by Daedalus itself: no evidence needed, no pending step, no apply."""
    if not text.strip():
        raise ModelError("An aspiration needs text")
    today = today or date.today()
    path = model_path("self", root)
    with file_lock(path):
        data = _load_locked("self", root)
        entry = {"id": _next_id(data, "self"), "kind": "aspiration", "category": category, "scope": "anywhere",
                 "observation": text.strip(), "confidence": 1.0, "label": "aspiration", "evidence": [],
                 "first_noticed": today.isoformat(), "last_affirmed": today.isoformat(), "status": "active",
                 "stable": False, "model_ids": [model_id] if model_id else [], "period": period,
                 "author": "daedalus"}
        data["entries"].append(entry)
        _save_locked("self", data, root)
        record(root, "self", entry["id"], "aspire", None, entry, by="daedalus")
        return entry


def delete(model: str, entry_id: str, root: Optional[Path] = None) -> dict:
    """The user deletes an entry (either model). It leaves a tombstone; its history stays."""
    path = model_path(model, root)
    with file_lock(path):
        data = _load_locked(model, root)
        entry = find(data, entry_id)
        if entry is None:
            raise ModelError(f"No entry {entry_id} in the {model} model")
        data["entries"].remove(entry)
        data["tombstones"].append(_tombstone(entry, "deleted by user"))
        _save_locked(model, data, root)
        record(root, model, entry_id, "user-delete", entry, None, by="user")
        return entry


def forget(entry_id: str, mode: str, root: Optional[Path] = None) -> dict:
    """
    The user's right to be forgotten (user model only). The entry goes and a tombstone stays.
    mode `purge` removes every history record for the entry; `retain` keeps them.
    """
    if mode not in ("purge", "retain"):
        raise ModelError("reflection.forget must be purge or retain")
    path = model_path("user", root)
    with file_lock(path):
        data = _load_locked("user", root)
        entry = find(data, entry_id)
        if entry is None:
            raise ModelError(f"No entry {entry_id} in the user model")
        data["entries"].remove(entry)
        data["tombstones"].append(_tombstone(entry, "forgotten by user"))
        _save_locked("user", data, root)
        hpath = history_path(root)
        with file_lock(hpath):
            if mode == "purge" and hpath.exists():
                kept = [line for line in hpath.read_text(encoding="utf-8").splitlines()
                        if not _is_record_for(line, "user", entry_id)]
                atomic_write_text(hpath, "".join(line + "\n" for line in kept))
        record(root, "user", entry_id, "forget", None, None, by="user",
               note=f"forgotten by user ({mode})")
        return entry


def _is_record_for(line: str, model: str, entry_id: str) -> bool:
    try:
        rec = json.loads(line)
    except json.JSONDecodeError:
        return False
    return rec.get("model") == model and rec.get("entry_id") == entry_id


def set_stable(model: str, entry_id: str, stable: bool, root: Optional[Path] = None) -> dict:
    path = model_path(model, root)
    with file_lock(path):
        data = _load_locked(model, root)
        entry = find(data, entry_id)
        if entry is None:
            raise ModelError(f"No entry {entry_id} in the {model} model")
        before = copy.deepcopy(entry)
        entry["stable"] = stable
        _save_locked(model, data, root)
        record(root, model, entry_id, "stable", before, copy.deepcopy(entry), by="user")
        return entry


# ---------- views ----------


def active_entries(data: dict) -> list[dict]:
    return [e for e in data["entries"] if e.get("status", "active") == "active"]


def summary(project_scope: str, settings: dict, root: Optional[Path] = None,
            today: Optional[date] = None) -> str:
    """
    The inhale summary: the highest-confidence active entries of both models after decay,
    aspirations labelled, no `unknown` entries, nothing from the other scope, capped at
    summary_tokens (estimated as characters / 4).
    """
    today = today or date.today()
    cap_chars = int(settings.get("summary_tokens", 400)) * 4
    project_scope = canon_scope(project_scope, "work")
    if project_scope == "work":
        excluded = set() if settings.get("share_private") else {"private"}
    else:
        excluded = {"work"}
    rows = []
    for model in MODELS:
        data = load(model, root)
        hl = half_life(model, settings)
        for e in active_entries(data):
            if e.get("label") == "unknown" or canon_scope(e.get("scope")) in excluded:
                continue
            rows.append((effective_confidence(e, today, hl), model, e))
    rows.sort(key=lambda r: -r[0])
    header = "Models (reflection, edict 0010):"
    lines, used = [header], len(header) + 1
    for conf, model, e in rows:
        tag = "aspiration" if e.get("kind") == "aspiration" else f"{model}, {conf:.2f}"
        line = f"- [{tag}] {e.get('observation', '')}"
        if used + len(line) + 1 > cap_chars:
            break
        lines.append(line)
        used += len(line) + 1
    return "\n".join(lines) if len(lines) > 1 else ""


def lineage_flags(in_use_models: set[str], root: Optional[Path] = None) -> list[str]:
    """Self entries whose evidence comes only from models no longer in use."""
    data = load("self", root)
    return [e["id"] for e in active_entries(data)
            if e.get("kind") != "aspiration" and not set(e.get("model_ids") or []) & in_use_models]


def unmoved_aspirations(today: date, root: Optional[Path] = None, days: int = ASPIRATION_UNMOVED_DAYS) -> list[str]:
    """Aspirations older than `days` that no behavior entry cites."""
    data = load("self", root)
    recent = [e for e in active_entries(data) if e.get("kind") == "behavior"
              and (today - date.fromisoformat((e.get("last_affirmed") or e.get("first_noticed") or "1970-01-01")[:10])).days < days]
    cited = {ev.get("aspiration") for e in recent for ev in e.get("evidence", []) if isinstance(ev, dict)}
    return [e["id"] for e in active_entries(data) if e.get("kind") == "aspiration"
            and (today - date.fromisoformat(e["first_noticed"][:10])).days >= days and e["id"] not in cited]


def evolution(month_start: date, month_end: date, root: Optional[Path] = None) -> list[dict]:
    """The month's model changes, from the history: what was added, revised, retired, and why."""
    out = []
    for rec in load_history(root):
        day = rec.get("at", "")[:10]
        if day and month_start.isoformat() <= day <= month_end.isoformat():
            out.append({"at": rec["at"], "model": rec.get("model"), "entry_id": rec.get("entry_id"),
                        "kind": rec.get("kind"), "by": rec.get("by"),
                        "observation": (rec.get("after") or rec.get("before") or {}).get("observation", ""),
                        "proposal_id": rec.get("proposal_id")})
    return out


def user_edit(model: str, entry_id: str, changes: dict, root: Optional[Path] = None) -> dict:
    """The user edits an entry through the CLI. An aspiration's text is Daedalus's; it is not rewritten."""
    path = model_path(model, root)
    with file_lock(path):
        data = _load_locked(model, root)
        entry = find(data, entry_id)
        if entry is None:
            raise ModelError(f"No entry {entry_id} in the {model} model")
        if entry.get("kind") == "aspiration" and "observation" in changes:
            raise ModelError("An aspiration is Daedalus's own words; it can be deleted, not rewritten")
        before = copy.deepcopy(entry)
        for key in ("observation", "confidence", "label", "category", "scope"):
            if key in changes:
                entry[key] = changes[key]
        if "scope" in changes:
            entry["scope"] = canon_scope(entry["scope"])
        _save_locked(model, data, root)
        record(root, model, entry_id, "user-edit", before, copy.deepcopy(entry), by="user")
        return entry


# ---------- dissents against self entries ----------

SELF_ENTRY_ID = re.compile(r"^s\d{3,}$")


def dissents_path(root: Optional[Path] = None) -> Path:
    return (root or models_dir()) / "dissents.jsonl"


def file_dissent(entry_id: str, agent: str, objection: str, why: str, instead: str,
                 root: Optional[Path] = None) -> dict:
    """
    A session that believes an applied self entry is wrong records a dissent (0003) naming it.
    It never edits the entry. Unlike a dissent on an edict, it blocks nothing: it is surfaced in
    the next monthly report, where delphi may propose a revise or retire.
    """
    for name, value in (("objection", objection), ("why", why), ("instead", instead)):
        if not value.strip():
            raise ModelError(f"A dissent states what it objects to, why, and what it would do instead ({name} is empty)")
    if find(load("self", root), entry_id) is None:
        raise ModelError(f"No entry {entry_id} in the self model")
    existing = load_dissents(root)
    dissent = {"id": f"d{len(existing) + 1:03d}", "entry_id": entry_id, "agent": agent, "status": "open",
               "filed": date.today().isoformat(), "objection": objection.strip(), "why": why.strip(),
               "instead": instead.strip()}
    path = dissents_path(root)
    with file_lock(path):
        append_line(path, json.dumps(dissent, ensure_ascii=False))
    return dissent


def load_dissents(root: Optional[Path] = None, open_only: bool = False) -> list[dict]:
    path = dissents_path(root)
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not open_only or d.get("status") == "open":
            out.append(d)
    return out
