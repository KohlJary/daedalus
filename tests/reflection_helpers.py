"""Shared setup for the reflection tests (edict 0010)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures" / "reflection" / "claude" / "projects" / "-fixture-project"
REAL_SESSION = "5e51440f-8672-4dc8-91d8-fcda6d34b22e"     # failures, classifier denials, a subagent
INTERRUPT_SESSION = "c78bf037-f898-413e-a7a4-9541fb43a511"  # rejection, interruptions
FIXTURE_CWD = "/fixture/project"


def claude_home() -> Path:
    return Path(os.environ["CLAUDE_CONFIG_DIR"])


def make_project(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    (path / ".daedalus").mkdir(exist_ok=True)
    return path


def install_fixtures(project: Path, folder: str = "-fixture-project") -> Path:
    """Copy the real (scrubbed) fixtures into the test's Claude dir, with cwd set to `project`."""
    dest = claude_home() / "projects" / folder
    shutil.copytree(FIXTURES, dest, dirs_exist_ok=True)
    for f in dest.rglob("*.jsonl"):
        lines = []
        for line in f.read_text(encoding="utf-8").splitlines():
            ev = json.loads(line)
            if ev.get("cwd") == FIXTURE_CWD:
                ev["cwd"] = str(project)
            lines.append(json.dumps(ev))
        f.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return dest


def write_session(folder: Path, session_id: str, events: list[dict]) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{session_id}.jsonl"
    path.write_text("".join(json.dumps(e) + "\n" for e in events), encoding="utf-8")
    return path


class Builder:
    """Synthetic transcript events, for heuristics no real fixture shows."""

    def __init__(self, cwd: str, session_id: str = "synthetic-1", start: str = "2026-10-05T12:00:00Z"):
        self.cwd, self.session_id, self.n, self.events = cwd, session_id, 0, []
        self.start = start

    def _uuid(self) -> str:
        self.n += 1
        return f"{self.session_id}-ev{self.n:03d}"

    def _base(self, etype: str) -> dict:
        return {"type": etype, "uuid": self._uuid(), "sessionId": self.session_id, "cwd": self.cwd,
                "timestamp": self.start, "version": "9.9.9", "gitBranch": "main"}

    def prompt(self, text: str = "do something") -> str:
        ev = self._base("user")
        ev["message"] = {"role": "user", "content": text}
        self.events.append(ev)
        return ev["uuid"]

    def call(self, tool: str, tool_id: str, **inp) -> str:
        ev = self._base("assistant")
        ev["message"] = {"id": f"msg-{tool_id}", "role": "assistant", "model": "claude-test",
                         "content": [{"type": "tool_use", "id": tool_id, "name": tool, "input": inp}],
                         "usage": {"input_tokens": 1, "output_tokens": 10, "cache_read_input_tokens": 100,
                                   "cache_creation_input_tokens": 5}}
        self.events.append(ev)
        return ev["uuid"]

    def result(self, tool_id: str, text: str = "ok", is_error: bool = False) -> str:
        ev = self._base("user")
        ev["message"] = {"role": "user", "content": [{"type": "tool_result", "tool_use_id": tool_id,
                                                       "is_error": is_error, "content": text}]}
        self.events.append(ev)
        return ev["uuid"]

    def reply(self, text: str = "done", message_id: str | None = None) -> str:
        ev = self._base("assistant")
        ev["message"] = {"id": message_id or f"msg-reply-{self.n}", "role": "assistant", "model": "claude-test",
                         "content": [{"type": "text", "text": text}],
                         "usage": {"input_tokens": 1, "output_tokens": 20, "cache_read_input_tokens": 100,
                                   "cache_creation_input_tokens": 0}}
        self.events.append(ev)
        return ev["uuid"]

    def raw(self, event: dict) -> None:
        self.events.append(event)


def git_init(path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
