"""
The `self` source (from the first dream, idea 23): intake from the codebase's own pain.

Sources made intake pluggable. The most honest tracker Daedalus can read is itself: reflection already
counts failures and retries, and doctor already finds drift. This source turns those into roadmap
proposals, so the friction Daedalus keeps hitting is visible beside the work people asked for, instead of
only in a report. Like every source it only proposes: the owner applies or drops each item.

It reads three local things, with no network and no model:
- **patterns:** reflection findings of type `pattern` (`.daedalus/reflection/reports/*.json`);
- **drift:** each `daedalus doctor` finding, while it persists. When a finding goes away, the item's tracker
  state becomes closed, so its next sync proposes `done`;
- **friction:** a tool call that keeps failing the same way (the same tool and command head or path) in
  `sources.self.friction_sessions` or more sessions (default 3), from the session digests.

Every item says in its description that it is Daedalus's own observation. It is on only where the project
turns it on: `daedalus config --project sources.self.enabled true`.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

from .base import ITEM, RemoteItem, Source

LABEL = "Daedalus's own observation (the `self` source), not a request from a person."


def _head(call: str) -> str:
    """A failing call's stable part: the command's first word (or two, for git/gh/daedalus), or a path's file name."""
    call = call.strip()
    words = call.split()
    if not words:
        return ""
    if "/" in words[0] and len(words) == 1:
        return Path(words[0]).name
    head = words[0]
    if head in ("git", "gh", "daedalus", "python", "python3", "uv", "npm", "pnpm", "cargo", "dotnet") and len(words) > 1:
        head += " " + words[1]
    return re.sub(r"[^\w .:+-]", "", head)[:60]


class SelfSource(Source):
    title = "Daedalus itself (its own friction)"
    supports_write_back = False
    verified = True  # local files only
    implicit = False
    config_schema = [
        {"key": "friction_sessions", "type": "int", "default": 3,
         "description": "Sessions a repeated failure must appear in before it becomes an intake item."},
    ]
    default_mapping = {"owned": ["title", "status"],
                       "kinds": {"Pattern": ITEM, "Drift": ITEM, "Friction": ITEM},
                       "states": {"open": "backlog", "closed": "done"}}

    def item_type(self, remote: RemoteItem) -> str:
        return "observation"

    def fetch(self, known_ids: list[str], since: Optional[str]) -> list[RemoteItem]:
        out = self._patterns() + self._drift(known_ids) + self._friction()
        return out

    def _patterns(self) -> list[RemoteItem]:
        out = []
        reports = Path(self.project_dir) / ".daedalus" / "reflection" / "reports"
        for f in sorted(reports.glob("*.json")) if reports.is_dir() else []:
            if f.name.endswith(".verdicts.json"):
                continue
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            for finding in data.get("findings") or []:
                if finding.get("type") != "pattern":
                    continue
                text = re.sub(r"\s*\[s:[^\]]+\]", "", str(finding.get("text", ""))).strip()
                title = text.split(". ")[0][:100] or "A pattern from reflection"
                out.append(RemoteItem(external_id=f"pattern-{f.stem}-{finding.get('id')}", kind="Pattern", title=title,
                                      state="open", description=f"{LABEL}\n\nFrom reflection report {f.stem}: {text}",
                                      url=f"daedalus reflect render (report {f.stem})"))
        return out

    def _drift(self, known_ids: list[str]) -> list[RemoteItem]:
        from ..doctor import run_checks

        try:
            findings, _ = run_checks(self.project_dir)
        except Exception:
            return []
        current = {}
        for f in findings:
            if f.name in ("source-auth-failed", "source-unreachable", "source-drift", "source-write-back-missing"):
                continue  # about sources themselves: doctor already says so, and it would loop
            current.setdefault(f.name, f.message)
        out = [RemoteItem(external_id=f"drift-{name}", kind="Drift", title=f"Fix doctor's {name}", state="open",
                          description=f"{LABEL}\n\n`daedalus doctor` keeps reporting: {msg}", url="daedalus doctor")
               for name, msg in sorted(current.items())]
        # A finding that went away: its item is closed, so a sync proposes it done
        for ext in known_ids:
            if ext.startswith("drift-") and ext[len("drift-"):] not in current:
                out.append(RemoteItem(external_id=ext, kind="Drift", title=f"Fix doctor's {ext[len('drift-'):]}",
                                      state="closed", description=LABEL, url="daedalus doctor"))
        return out

    def _friction(self) -> list[RemoteItem]:
        sessions = Path(self.project_dir) / ".daedalus" / "reflection" / "sessions"
        seen: dict[tuple, set] = {}
        sample: dict[tuple, str] = {}
        for f in sorted(sessions.glob("*.json")) if sessions.is_dir() else []:
            try:
                digest = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            failures = set((digest.get("events") or {}).get("failures") or [])
            for uuid, d in (digest.get("details") or {}).items():
                if uuid not in failures or not isinstance(d, dict):
                    continue
                key = (d.get("tool", "?"), _head(str(d.get("call", ""))))
                if not key[1]:
                    continue
                seen.setdefault(key, set()).add(digest.get("session_id", f.stem))
                sample.setdefault(key, str(d.get("summary", ""))[:160])
        need = int(self.settings.get("friction_sessions") or 3)
        out = []
        for (tool, head), sess in sorted(seen.items()):
            if len(sess) < need:
                continue
            slug = re.sub(r"[^a-z0-9]+", "-", f"{tool} {head}".lower()).strip("-")
            out.append(RemoteItem(
                external_id=f"friction-{slug}", kind="Friction", title=f"{tool} `{head}` keeps failing", state="open",
                description=(f"{LABEL}\n\nFailed in {len(sess)} sessions. A recent error: "
                             f"{' '.join(sample[(tool, head)].split())}"),
                url="daedalus reflect digest"))
        return out
