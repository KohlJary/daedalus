"""
Why things died (from the first dream, docs/dreams/2026-10-15.md, pick 14).

Dropping intake (a proposal for a new roadmap item, phase or task) leaves a one-line epitaph in
`.daedalus/epitaphs.jsonl`: what it was, where it came from, when, and, if the owner gave one, why. The
file is append-only and local, like the pending proposals it records.

A sync that stops re-proposing a dropped item is right, but it erases the signal that someone keeps
asking for the same thing. So `daedalus doctor` hints (never fails) when the same request, by key or by a
near-identical title, has been dropped three times or more: an unmet need, or a decision worth writing down.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

INTAKE_KINDS = ("roadmap-new", "new-phase", "new-task")
RECUR = 3


def path(project_dir: Path) -> Path:
    return Path(project_dir) / ".daedalus" / "epitaphs.jsonl"


def _title(p: dict[str, Any]) -> str:
    if p.get("kind") == "roadmap-new":
        return str((p.get("item") or {}).get("title", ""))
    if p.get("kind") == "new-phase":
        return str((p.get("phase") or {}).get("title", ""))
    return str(p.get("title", ""))


def _key(p: dict[str, Any]) -> str:
    o = p.get("origin") or {}
    if o.get("source"):
        return f"{o['source']}:{o.get('external_id')}"
    if p.get("kind") == "new-phase":
        return f"phase:{(p.get('phase') or {}).get('id')}"
    return f"{p.get('kind')}:{p.get('task') or (p.get('item') or {}).get('id')}"


def normalise(title: str) -> str:
    words = re.findall(r"[a-z0-9]+", title.lower())
    return " ".join(w for w in words if w not in ("a", "an", "the", "to", "of", "and", "for"))


def record(project_dir: Path, proposals: list[dict[str, Any]], why: Optional[str] = None) -> int:
    """An epitaph for each dropped intake proposal. Returns how many were written."""
    rows = []
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for p in proposals:
        if p.get("kind") not in INTAKE_KINDS:
            continue
        rows.append({"at": stamp, "kind": p["kind"], "key": _key(p), "title": _title(p)[:200],
                     "source": (p.get("origin") or {}).get("source") or p.get("source") or "local",
                     "why": (why or "").strip()[:300]})
    if rows:
        f = path(project_dir)
        f.parent.mkdir(parents=True, exist_ok=True)
        with f.open("a", encoding="utf-8") as out:
            for r in rows:
                out.write(json.dumps(r, ensure_ascii=False) + "\n")
    return len(rows)


def load(project_dir: Path) -> list[dict[str, Any]]:
    f = path(project_dir)
    if not f.exists():
        return []
    out = []
    for line in f.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def recurring(project_dir: Path, threshold: int = RECUR) -> list[dict[str, Any]]:
    """Requests dropped `threshold` times or more, grouped by key or by a near-identical title."""
    groups: dict[str, list] = {}
    for e in load(project_dir):
        title = normalise(e.get("title", ""))
        groups.setdefault(f"title:{title}" if title else f"key:{e.get('key')}", []).append(e)
    out = []
    for g, rows in groups.items():
        if len(rows) >= threshold:
            latest = rows[-1]
            out.append({"title": latest.get("title") or latest.get("key"), "count": len(rows),
                        "sources": sorted({r.get("source", "") for r in rows}),
                        "last_why": next((r["why"] for r in reversed(rows) if r.get("why")), "")})
    return sorted(out, key=lambda r: -r["count"])
