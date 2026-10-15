"""
Sync: turning a tracker's items into pending proposals, and applying the ones the owner accepts
(edict 0011).

A sync is deterministic and on demand: no model calls, no daemon. It reads the tracker through the
source plugin, compares with the roadmap index and every workstream's plan, and writes proposals for
the current workstream (or `--workstream`):

- a tracker kind mapped to `phase` -> `new-phase` (its child items listed up front, its tasks queued);
- one mapped to `item` -> `roadmap-new`, or `roadmap-update` when the tracker changed it;
- one mapped to `task` -> `new-task` in the phase that references its parent's item.

Re-syncing skips any external id already in the roadmap, already in a plan, or already pending in
any workstream, so syncing twice adds nothing, and so does syncing after the proposals are applied.

**Conflicts are measured against the last sync.** A sourced item keeps `synced.fields`: the owned
fields as the tracker last had them. A field changed only in the tracker is an ordinary update (a
proposal). A field changed on both sides is a conflict, settled by `sources.<name>.on_conflict`:
`propose` (default) proposes the tracker's value and says what it would overwrite; `source` takes the
tracker's value and records it; `local` keeps ours and records it. A sync never touches a field the
mapping doesn't own, a task, or a task's resolution.

**Write-back.** Marking a task done whose own origin, or whose roadmap item's origin, is a source
that supports write-back creates a `write-back` proposal. Applying it calls the tracker; dropping it
calls nothing. Either way the outcome is recorded (`writeBack` on the task, `synced.write_back` on the
item it closed), so doctor can tell a dropped write-back from a forgotten one.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Optional

from .. import roadmap
from .. import workstreams as ws
from ..cli import gameplan as gp
from . import create, state
from .base import ITEM, PHASE, TASK, RemoteItem, SourceError


@dataclass
class SyncResult:
    name: str
    proposals: list = field(default_factory=list)   # added (or, in a dry run, that would be)
    resolved: list = field(default_factory=list)    # conflicts settled by on_conflict source/local
    skipped: list = field(default_factory=list)     # items it couldn't place yet, with why
    error: Optional[str] = None
    health: str = ""
    dry_run: bool = False


def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _origin(name: str, r: RemoteItem) -> dict[str, Any]:
    return {"source": name, "external_id": r.external_id, "url": r.url}


def _plans(project_dir: Path) -> dict[str, dict[str, Any]]:
    plans = {}
    for wid in ws.list_ids(project_dir):
        try:
            plans[wid] = gp.load_gameplan(project_dir, wid)
        except gp.GameplanError:
            continue
    return plans


def pending_by_workstream(project_dir: Path) -> dict[str, list[dict[str, Any]]]:
    import json

    out = {}
    for wid in ws.list_ids(project_dir):
        path = gp.GameplanPaths.for_project(project_dir, wid).pending_file
        try:
            out[wid] = json.loads(path.read_text(encoding="utf-8")).get("proposals", []) if path.exists() else []
        except (OSError, ValueError, AttributeError):
            out[wid] = []
    return out


def _safe_key(p: dict[str, Any]) -> Optional[str]:
    try:
        return gp.proposal_key(p)
    except (gp.GameplanError, KeyError, TypeError):
        return None


def _phase_with_item(data: dict[str, Any], item_id: str) -> Optional[dict[str, Any]]:
    for phase in data.get("phases", []):
        if item_id in (phase.get("roadmapItems") or []):
            return phase
    return None


def compare(item: dict[str, Any], remote_fields: dict[str, Any]) -> tuple[dict, dict, list]:
    """(changes, conflicts, agreed) for one sourced item against the last sync's baseline.

    changes: fields only the tracker changed {field: remote value}. conflicts: fields changed on both
    sides {field: {"local", "remote", "base"}}. agreed: fields both sides changed to the same value
    (only the baseline needs to move). A field with no baseline counts as changed here.
    """
    base = (item.get("synced") or {}).get("fields", {})
    changes, conflicts, agreed = {}, {}, []
    for f, remote in remote_fields.items():
        local = item.get(f)
        if f in base and remote == base[f]:
            continue  # the tracker didn't change it; a local edit stays local
        if local == remote:
            if base.get(f) != remote:
                agreed.append(f)
            continue
        if f in base and local == base[f]:
            changes[f] = remote
        else:
            conflicts[f] = {"local": local, "remote": remote, "base": base.get(f)}
    return changes, conflicts, agreed


def sync(project_dir: Path, name: str, dry_run: bool = False) -> SyncResult:
    """Sync one source into proposals for the current workstream. Never raises for the tracker's
    failures: they come back as `error` and `health`, and are recorded for doctor."""
    project_dir = Path(project_dir)
    result = SyncResult(name=name, dry_run=dry_run)
    stamp = now_utc()
    src = create(project_dir, name)
    on_conflict = src.settings.get("on_conflict") or "propose"
    index = roadmap.load_index(project_dir)
    if dry_run:
        index = copy.deepcopy(index)
    plans = _plans(project_dir)
    pendings = pending_by_workstream(project_dir)
    target = ws.current(project_dir)
    target_plan = plans.get(target, {})

    pending_keys: dict[str, str] = {}
    pending_task_origins: set[str] = set()
    for wid, props in pendings.items():
        for p in props:
            key = _safe_key(p)
            if key:
                pending_keys[key] = wid
            for t in (p.get("phase") or {}).get("tasks", []) if p.get("kind") == "new-phase" else []:
                o = t.get("origin") if isinstance(t, dict) else None
                if o and o.get("source") == name:
                    pending_task_origins.add(str(o.get("external_id")))
    known_items = roadmap.by_external(index, name)
    phase_origins, task_origins, phase_ids = set(), set(), set()
    for data in plans.values():
        for phase in data.get("phases", []):
            phase_ids.add(phase.get("id"))
            o = phase.get("origin") or {}
            if o.get("source") == name:
                phase_origins.add(str(o.get("external_id")))
        for _, task in roadmap.all_tasks(data):
            o = task.get("origin") or {}
            if o.get("source") == name:
                task_origins.add(str(o.get("external_id")))

    prior = state.load(project_dir).get(name, {})
    try:
        remote = src.fetch(sorted(known_items), prior.get("last_sync"))
    except SourceError as e:
        result.error, result.health = str(e), e.health
        if not dry_run:
            state.record(project_dir, name, last_attempt=stamp, health=e.health, error=str(e),
                         supports_write_back=bool(src.supports_write_back))
        return result

    today = date.today().isoformat()
    provenance = f"sync:{name}"
    roles = {r.external_id: src.role(r) for r in remote}
    by_id = {r.external_id: r for r in remote}
    proposals: list[dict[str, Any]] = []
    index_dirty = False

    def phase_id(ext: str) -> str:
        return roadmap.item_id_for(name, ext).lower()

    # ----- phases -----
    new_phases: dict[str, dict[str, Any]] = {}
    for r in remote:
        if roles[r.external_id] != PHASE:
            continue
        pid = phase_id(r.external_id)
        if (r.external_id in phase_origins or pid in phase_ids or f"phase:{pid}" in pending_keys
                or src.status_for(r) == "done"):
            continue
        children = [roadmap.item_id_for(name, c.external_id) for c in remote
                    if c.parent == r.external_id and roles[c.external_id] == ITEM]
        spec = {"id": pid, "title": r.title, "status": "planned",
                "notes": f"From {src.title}: {r.url}".strip(), "origin": _origin(name, r),
                "roadmapItems": children, "tasks": []}
        new_phases[r.external_id] = spec
        proposals.append({"kind": "new-phase", "phase": spec, "origin": _origin(name, r),
                          "source": provenance, "created": today})

    # ----- roadmap items -----
    for r in remote:
        if roles[r.external_id] != ITEM:
            continue
        o = _origin(name, r)
        key = f"src:{name}:{r.external_id}"
        remote_fields = src.fields(r)
        item = known_items.get(r.external_id)
        if item is None:
            if key in pending_keys or remote_fields.get("status") == "done":
                continue  # already proposed, or closed before it was ever taken in
            new_item = {"id": roadmap.item_id_for(name, r.external_id), "title": r.title,
                        "description": r.description or "", "status": "backlog", "priority": "P2",
                        "item_type": src.item_type(r), "created_at": stamp, "created_by": provenance, "origin": o}
            new_item.update(remote_fields)
            parent_phase = phase_id(r.parent) if r.parent and roles.get(r.parent) == PHASE else None
            proposals.append({"kind": "roadmap-new", "origin": o, "item": new_item,
                              "synced": {"fields": remote_fields, "remote_updated": r.updated},
                              **({"phase": parent_phase} if parent_phase else {}),
                              "source": provenance, "created": today})
            continue
        if pending_keys.get(key, target) != target:
            continue  # another workstream has this item's update pending
        changes, conflicts, agreed = compare(item, remote_fields)
        synced = item.setdefault("synced", {})
        base = synced.setdefault("fields", {})
        for f in agreed:
            base[f] = remote_fields[f]
            index_dirty = True
        if conflicts and on_conflict in ("source", "local"):
            for f, c in conflicts.items():
                if on_conflict == "source":
                    item[f] = c["remote"]
                base[f] = c["remote"]
                synced.setdefault("history", []).append({
                    "at": stamp, "field": f, "local": c["local"], "remote": c["remote"],
                    "outcome": "took the source's value" if on_conflict == "source" else "kept the local value"})
                result.resolved.append(f"{item['id']}.{f}: {'took ' + name if on_conflict == 'source' else 'kept local'}")
            synced["remote_updated"] = r.updated
            index_dirty = True
            conflicts = {}
        if conflicts:
            changes.update({f: c["remote"] for f, c in conflicts.items()})
        if changes:
            proposals.append({"kind": "roadmap-update", "origin": o, "item": item["id"], "changes": changes,
                              "conflicts": conflicts,
                              "synced": {"fields": {f: remote_fields[f] for f in changes}, "remote_updated": r.updated},
                              "source": provenance, "created": today})

    # ----- tasks -----
    for r in remote:
        if roles[r.external_id] != TASK:
            continue
        key = f"src:{name}:{r.external_id}"
        if (r.external_id in task_origins or r.external_id in pending_task_origins or key in pending_keys
                or src.status_for(r) == "done"):
            continue
        parent_item = roadmap.item_id_for(name, r.parent) if r.parent else None
        task = {"id": roadmap.item_id_for(name, r.external_id).lower(), "title": r.title, "details": r.url,
                "origin": _origin(name, r), "roadmapItem": parent_item}
        parent = by_id.get(r.parent) if r.parent else None
        grandparent = parent.parent if parent else None
        if grandparent in new_phases and roles.get(r.parent) == ITEM:
            # Its phase is being proposed in this same sync: queue the task on it
            new_phases[grandparent]["tasks"].append({**task, "status": "pending", "updated": today})
            continue
        phase = _phase_with_item(target_plan, parent_item) if parent_item else None
        if phase is None:
            result.skipped.append(f"{r.kind} {r.external_id} ({r.title}): its parent {r.parent or '(none)'} "
                                  f"isn't in a phase of workstream {target} yet; sync again once it is")
            continue
        proposals.append({"kind": "new-task", "task": task["id"], "title": r.title, "details": r.url,
                          "phase": phase["id"], "origin": task["origin"], "roadmapItem": parent_item,
                          "source": provenance, "created": today})

    if dry_run:
        result.proposals = proposals
        result.health = src.health_when_ok()
        return result
    if index_dirty:
        roadmap.save_index(project_dir, index)
    result.proposals = gp.add_proposals(project_dir, proposals) if proposals else []
    result.health = src.health_when_ok()
    state.record(project_dir, name, last_sync=stamp, last_attempt=stamp, health=result.health, error=None,
                 supports_write_back=bool(src.supports_write_back))
    return result


# ---------- applying and dropping (called from gameplan.apply_pending / drop_pending) ----------


def apply_roadmap_proposal(project_dir: Path, data: dict[str, Any], p: dict[str, Any]) -> None:
    index = roadmap.load_index(project_dir)
    if p["kind"] == "roadmap-new":
        item = dict(p["item"])
        if roadmap.find_optional(index, item["id"]):
            raise gp.GameplanError(f"Roadmap item {item['id']} already exists")
        item["synced"] = copy.deepcopy(p.get("synced") or {})
        index["items"].append(item)
        phase = gp.find_phase(data, p["phase"]) if p.get("phase") else None
        if phase is not None and item["id"] not in phase.setdefault("roadmapItems", []):
            phase["roadmapItems"].append(item["id"])
    else:
        item = roadmap.find_optional(index, p["item"])
        if item is None:
            raise gp.GameplanError(f"Roadmap item {p['item']} not found")
        for f, value in p.get("changes", {}).items():
            item[f] = value
        if "status" in p.get("changes", {}):
            item["status_changed_at"] = datetime.now().isoformat(timespec="seconds")
        synced = item.setdefault("synced", {})
        synced.setdefault("fields", {}).update((p.get("synced") or {}).get("fields", {}))
        if (p.get("synced") or {}).get("remote_updated"):
            synced["remote_updated"] = p["synced"]["remote_updated"]
    roadmap.save_index(project_dir, index)


def write_back_proposal(project_dir: Path, task: dict[str, Any]) -> Optional[dict[str, Any]]:
    """The write-back a done task calls for, or None (no sourced origin, or a source without write-back)."""
    if task.get("writeBack"):
        return None
    index = roadmap.load_index(project_dir)
    item = roadmap.find_optional(index, task.get("roadmapItem"))
    origin, target = task.get("origin"), "task"
    if not (isinstance(origin, dict) and origin.get("source") not in (None, "local")):
        if item is None or not roadmap.is_sourced(item):
            return None
        origin, target = roadmap.origin(item), "item"
    try:
        src = create(project_dir, origin["source"])
    except KeyError:
        return None
    if not src.supports_write_back:
        return None
    comment = task.get("resolution") if src.settings.get("write_back_comment") else None
    return {"kind": "write-back",
            "origin": {"source": origin["source"], "external_id": str(origin.get("external_id")),
                       "url": origin.get("url", "")},
            "task": task["id"], "item": item["id"] if item is not None else None,
            "target": target, "comment": comment or None, "source": "task-done",
            "created": date.today().isoformat()}


def propose_write_back(project_dir: Path, data: dict[str, Any], task: dict[str, Any]) -> Optional[dict[str, Any]]:
    p = write_back_proposal(project_dir, task)
    if p is None:
        return None
    added = gp.add_proposals(project_dir, [p])
    return added[0] if added else None


def _record_write_back(project_dir: Path, data: Optional[dict[str, Any]], p: dict[str, Any], outcome: str) -> None:
    if data is not None:
        for _, task in roadmap.all_tasks(data):
            if task.get("id") == p["task"]:
                task["writeBack"] = outcome
    if p.get("target") == "item" and p.get("item"):
        index = roadmap.load_index(project_dir)
        item = roadmap.find_optional(index, p["item"])
        if item is not None:
            item.setdefault("synced", {})["write_back"] = outcome
            roadmap.save_index(project_dir, index)


def apply_write_back(project_dir: Path, data: dict[str, Any], p: dict[str, Any]) -> None:
    """Make the outside call, then record it. Raises (SourceError, KeyError) and records nothing on failure."""
    src = create(project_dir, p["origin"]["source"])
    if not src.supports_write_back:
        raise SourceError(f"{src.name} doesn't support write-back")
    src.write_back(str(p["origin"]["external_id"]), p.get("comment"))
    _record_write_back(project_dir, data, p, "applied")


def record_drops(project_dir: Path, proposals: list[dict[str, Any]]) -> None:
    try:
        data = gp.load_gameplan(project_dir)
    except gp.GameplanError:
        data = None
    stamp = now_utc()
    index = roadmap.load_index(project_dir)
    index_dirty = False
    for p in proposals:
        if p.get("kind") == "roadmap-update":
            item = roadmap.find_optional(index, p.get("item"))
            if item is None:
                continue
            synced = item.setdefault("synced", {})
            synced.setdefault("fields", {}).update((p.get("synced") or {}).get("fields", {}))
            if (p.get("synced") or {}).get("remote_updated"):
                synced["remote_updated"] = p["synced"]["remote_updated"]
            synced.setdefault("history", []).append({
                "at": stamp, "fields": sorted(p.get("changes", {})), "outcome": "update dropped; kept the local values"})
            index_dirty = True
    if index_dirty:
        roadmap.save_index(project_dir, index)
    wbs = [p for p in proposals if p.get("kind") == "write-back"]
    for p in wbs:
        _record_write_back(project_dir, data, p, "dropped")
    if wbs and data is not None:
        gp.save_gameplan(project_dir, data)
