"""
What the TUI shows, read through the same library functions the CLI uses (edict 0012: one source of
truth; the TUI never parses CLI output). Nothing here imports Textual, so it is tested on its own and
loaded only by `daedalus tui`.

Each reader returns plain data and never raises for a missing or broken file: a panel shows what's
there, or an empty state that says what would appear.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


@dataclass
class NeedItem:
    kind: str          # PR, ED, DS, BD, GP, RF, or a plugin's tag
    key: str           # stable within its kind (branch, edict number, proposal ID, ...)
    title: str
    when: Optional[str] = None   # ISO time, for the age column
    detail: dict = field(default_factory=dict)
    actions: tuple = ()          # what the detail view offers: "apply", "drop", "follow", "send"


KIND_ORDER = ("PR", "ED", "DS", "BD", "GP", "RF")
KIND_NAMES = {"PR": "PR", "ED": "edicts", "DS": "dissents", "BD": "board", "GP": "gameplan", "RF": "reflection"}


def _git(project_dir: Path, *args: str) -> Optional[str]:
    try:
        out = subprocess.run(["git", *args], cwd=project_dir, capture_output=True, text=True, timeout=10)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def age(when: Optional[str], now: Optional[datetime] = None) -> str:
    """A short age: 10m, 5h, 2d."""
    if not when:
        return ""
    try:
        moment = datetime.fromisoformat(str(when).replace("Z", "+00:00"))
    except ValueError:
        try:
            moment = datetime.fromisoformat(str(when)[:10])
        except ValueError:
            return ""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    secs = max(0, ((now or datetime.now(timezone.utc)) - moment).total_seconds())
    if secs < 3600:
        return f"{int(secs // 60)}m"
    if secs < 86400:
        return f"{int(secs // 3600)}h"
    return f"{int(secs // 86400)}d"


# ---------- header ----------

def header(project_dir: Path) -> dict:
    from ..cli import gameplan as gp
    from ..hooks import _next_task

    branch = _git(project_dir, "rev-parse", "--abbrev-ref", "HEAD") or ""
    phase = task = None
    try:
        active = gp.load_gameplan(project_dir).get("activePhase") or {}
        phase = active.get("id")
        nt = _next_task(active) if active else None
        task = f"{nt['id']} {nt.get('title', '')}" if nt else None
    except gp.GameplanError:
        pass
    return {"project": Path(project_dir).resolve().name, "branch": branch, "phase": phase, "task": task}


def last_session(project_dir: Path) -> Optional[str]:
    from ..hooks import latest_session_note

    path = Path(project_dir) / ".daedalus" / "session-summaries.md"
    if not path.exists():
        return None
    note = latest_session_note(path.read_text(encoding="utf-8"))
    return note.splitlines()[0].lstrip("# ").strip() if note else None


def is_first_run(project_dir: Path) -> bool:
    """No gameplan with anything in it, no edicts, no session notes: show Welcome."""
    from ..cli import gameplan as gp

    project_dir = Path(project_dir)
    try:
        data = gp.load_gameplan(project_dir)
        if data.get("phases") or data.get("activePhase"):
            return False
    except gp.GameplanError:
        pass
    if any((project_dir / "docs" / "edicts").glob("[0-9][0-9][0-9][0-9]-*.md")):
        return False
    return last_session(project_dir) is None


# ---------- needs you ----------

def local_prs(project_dir: Path, base: str = "main") -> list[NeedItem]:
    """Local branches ahead of main (the default `tui.prs: local`)."""
    out = _git(project_dir, "for-each-ref", "--format=%(refname:short)|%(committerdate:iso-strict)", "refs/heads")
    items = []
    for line in (out or "").splitlines():
        name, _, when = line.partition("|")
        if name in (base, "master") or name.startswith("daedalus/board"):
            continue
        ahead = _git(project_dir, "rev-list", "--count", f"{base}..{name}")
        if ahead and ahead.isdigit() and int(ahead) > 0:
            subject = _git(project_dir, "log", "-1", "--format=%s", name) or ""
            items.append(NeedItem("PR", name, name, when, {"ahead": int(ahead), "subject": subject, "branch": name},
                                  ("send",)))
    return items


def gh_prs(project_dir: Path) -> list[NeedItem]:
    """Open PRs from the GitHub CLI (`tui.prs: gh`). Falls back to nothing if gh is missing or not logged in."""
    import json

    try:
        out = subprocess.run(["gh", "pr", "list", "--json", "number,title,headRefName,updatedAt,url"],
                             cwd=project_dir, capture_output=True, text=True, timeout=15)
        rows = json.loads(out.stdout) if out.returncode == 0 else []
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError, ValueError):
        rows = []
    return [NeedItem("PR", f"#{r['number']}", f"#{r['number']} {r.get('headRefName', '')}", r.get("updatedAt"),
                     {"title": r.get("title"), "url": r.get("url"), "branch": r.get("headRefName")}, ("send",))
            for r in rows if isinstance(r, dict) and "number" in r]


def needs_you(project_dir: Path, prs: str = "local") -> list[NeedItem]:
    from .. import workstreams as ws
    from ..cli import gameplan as gp
    from ..doctor import load_edicts

    project_dir = Path(project_dir)
    items: list[NeedItem] = []
    items += gh_prs(project_dir) if prs == "gh" else local_prs(project_dir)
    for e in load_edicts(project_dir):
        if e.get("status") == "proposed":
            path = project_dir / "docs" / "edicts" / e["file"]
            first = path.read_text(encoding="utf-8").splitlines()[0] if path.exists() else ""
            title = first.split(":", 1)[1].strip() if ":" in first else e["file"]
            items.append(NeedItem("ED", e["number"], f"{e['number']} {title}", None,
                                  {"path": f"docs/edicts/{e['file']}"}, ("send",)))
    try:
        from ..edicts import list_dissents

        for d in list_dissents(project_dir):
            items.append(NeedItem("DS", d.path.stem, f"{d.edict}: dissent by {d.agent}", d.filed,
                                  {"path": str(d.path)}, ("send",)))
    except Exception:
        pass
    try:
        from .. import board

        me = ws.current(project_dir)
        for thread, posts in board.unread(project_dir, me):
            items.append(NeedItem("BD", thread.id, board.one_line(thread.title, 60), posts[-1].created if posts else None,
                                  {"unread": len(posts), "topic": thread.topic}, ("follow", "send")))
    except Exception:
        pass
    for wid in ws.list_ids(project_dir):
        path = gp.GameplanPaths.for_project(project_dir, wid).pending_file
        try:
            import json

            props = json.loads(path.read_text(encoding="utf-8")).get("proposals", []) if path.exists() else []
        except (OSError, ValueError, AttributeError):
            props = []
        for p in props:
            try:
                text = gp.describe_proposal(p)
            except Exception:
                text = f"[can't apply: unknown kind {p.get('kind')!r}]"
            items.append(NeedItem("GP", f"{wid}/{p.get('id')}", text, p.get("created"),
                                  {"workstream": wid, "proposal": p}, ("apply", "drop", "send")))
    try:
        from ..reflection import pending as rp

        for p in rp.load_pending(project_dir):
            items.append(NeedItem("RF", str(p.get("id")), str(p.get("text", ""))[:80], p.get("queued"),
                                  {"proposal": p}, ("apply", "drop", "send")))
    except Exception:
        pass
    for plugin in _plugins():
        try:
            items += list(plugin.needs_you(project_dir))
        except Exception:
            continue
    order = {k: i for i, k in enumerate(KIND_ORDER)}
    return sorted(items, key=lambda it: (order.get(it.kind, len(order)), str(it.when or "")))


def counts(items: list[NeedItem]) -> dict[str, int]:
    out: dict[str, int] = {}
    for it in items:
        out[it.kind] = out.get(it.kind, 0) + 1
    return out


# ---------- gameplan, health ----------

def gameplan(project_dir: Path, workstream: Optional[str] = None) -> dict:
    from ..cli import gameplan as gp

    try:
        return gp.load_gameplan(project_dir, workstream)
    except gp.GameplanError:
        return {}


def workstreams(project_dir: Path) -> list[dict]:
    from .. import workstreams as ws

    out = []
    for wid in ws.list_ids(project_dir):
        try:
            data = ws.load(project_dir, wid)
        except ws.WorkstreamError:
            continue
        out.append({"id": wid, "summary": ws.summary_line(data, wid), "owner": ws.owner(data, wid),
                    "current": wid == ws.current(project_dir)})
    return out


def health(project_dir: Path) -> tuple[list[Any], list[str]]:
    from ..doctor import run_checks

    try:
        return run_checks(Path(project_dir))
    except Exception as e:  # doctor must never take the TUI down
        from ..doctor import Finding

        return [Finding("doctor-failed", str(e))], []


# ---------- plugins (entry-point group daedalus.tui) ----------

_plugin_cache: Optional[list] = None


def _plugins() -> list:
    global _plugin_cache
    if _plugin_cache is None:
        from importlib.metadata import entry_points

        found = []
        for ep in entry_points(group="daedalus.tui"):
            try:
                obj = ep.load()
                found.append(obj() if isinstance(obj, type) else obj)
            except Exception:
                continue
        _plugin_cache = found
    return _plugin_cache


def reset_plugins() -> None:
    global _plugin_cache
    _plugin_cache = None


def plugins() -> list:
    return list(_plugins())
