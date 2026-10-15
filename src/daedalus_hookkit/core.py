"""
The dispatcher: one per event. It reads the hook input once, runs each enabled feature, applies the
noise budget, logs nudges for efficacy, and renders the output the docs give that event.

Output channels (code.claude.com/docs/en/hooks):
- SessionStart and UserPromptSubmit: plain stdout reaches the model.
- PostToolUse: only `hookSpecificOutput.additionalContext` does; plain stdout doesn't.
- PreToolUse: a gate's `permissionDecision` (deny, with its reason shown to Claude); anything else goes
  in `additionalContext`, which arrives with the tool result, after the call has run.
- Stop, SubagentStop, PreCompact and SessionEnd: nothing is printed. Stop output continues the turn
  (a full extra turn), and the others never reach the model. Features there may only update state.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from . import state as state_mod
from .settings import Settings

SILENT_EVENTS = {"Stop", "SubagentStop", "PreCompact", "SessionEnd"}
MAX_LINE = 300


class Line:
    """One thing a feature has to say.

    kind: "nudge" counts against the budget; "brief" (SessionStart), "gate" and "notice" don't.
    nudge: the nudge's id, logged for efficacy. tool: what using the nudge's advice looks like
    ("agent:momus", "skill:exhale", "bash:daedalus gameplan pending"), so a later tool call can mark it
    followed. decision: a gate's "deny" or "allow".
    """

    __slots__ = ("text", "kind", "nudge", "tool", "decision")

    def __init__(self, text: str, kind: str = "nudge", nudge: str = "", tool: str = "", decision: str = ""):
        self.text, self.kind, self.nudge, self.tool, self.decision = text, kind, nudge, tool, decision


class Ctx:
    """What a feature sees: the event, its input, the project, settings, the clock and session state."""

    def __init__(self, event: str, payload: dict, project_dir: Path, settings: Settings, now: float):
        self.event = event
        self.payload = payload
        self.project_dir = project_dir
        self.settings = settings
        self.now = now
        self.session_id = str(payload.get("session_id") or "")
        self._state: dict | None = None
        self.dirty = False

    @property
    def state(self) -> dict:
        if self._state is None:
            self._state = state_mod.load(self.session_id or "unknown", self.now)
        return self._state

    def touch(self) -> dict:
        """The state, marked to be saved."""
        self.dirty = True
        return self.state


class Feature:
    """A kit feature: its name, the events it runs on, the hooks.* setting that turns it on, its function
    (Ctx -> list of Line), and whether it is a gate (a gate that errors allows the call, visibly)."""

    __slots__ = ("name", "events", "key", "run", "gate")

    def __init__(self, name: str, events: frozenset, key: str, run, gate: bool = False):
        self.name, self.events, self.key, self.run, self.gate = name, events, key, run, gate


def project_dir_for(payload: dict) -> Path:
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    if env:
        return Path(env)
    return Path(payload.get("cwd") or os.getcwd())


def _budgeted(ctx: Ctx, lines: list) -> list:
    """Drop nudges over budget (and all but the first in one call), logging each nudge."""
    per_hour = int(ctx.settings.get("hooks", "budget_per_hour"))
    st = ctx.state
    events = st["events"]
    hour_ago = ctx.now - 3600
    used = sum(1 for e in events if e.get("counted") and e.get("at", 0) >= hour_ago)
    kept, spoke = [], False
    for line in lines:
        if line.kind != "nudge":
            kept.append(line)
            continue
        entry = {"at": ctx.now, "hook": line.nudge.split(":")[0] if line.nudge else "", "event": ctx.event,
                 "nudge": line.nudge, "followed": None, "tool": line.tool, "seq": int(st.get("event_seq", 0))}
        if spoke or used >= per_hour:
            entry["dropped"] = True
        else:
            entry["counted"] = True
            used += 1
            spoke = True
            kept.append(line)
        events.append(entry)
        ctx.dirty = True
    st["budget"] = {"per_hour": per_hour, "used": used}
    return kept


def render(event: str, lines: list) -> str:
    if event in SILENT_EVENTS or not lines:
        return ""
    texts = [ln.text if len(ln.text) <= MAX_LINE or ln.kind == "brief" else ln.text[:MAX_LINE - 1] + "…"
             for ln in lines if ln.decision != "deny"]
    if event in ("SessionStart", "UserPromptSubmit"):
        return "\n".join(texts)
    out: dict = {"hookEventName": event}
    if event == "PreToolUse":
        denies = [ln.text for ln in lines if ln.decision == "deny"]
        if denies:
            out["permissionDecision"] = "deny"
            out["permissionDecisionReason"] = "\n".join(denies)
    if texts:
        out["additionalContext"] = "\n".join(texts)
    if len(out) == 1:
        return ""
    return json.dumps({"hookSpecificOutput": out})


def dispatch(event: str, payload: dict, features: list | None = None, now: float | None = None) -> str:
    """Run the event's enabled features and return what to print ("" for nothing)."""
    project_dir = project_dir_for(payload)
    if not (project_dir / ".daedalus").is_dir():
        return ""
    if features is None:
        from .features import FEATURES
        features = FEATURES
    settings = Settings(project_dir)
    ctx = Ctx(event, payload, project_dir, settings, time.time() if now is None else now)
    lines: list = []
    for feature in features:
        if event not in feature.events or (feature.key and not settings.enabled(feature.key)):
            continue
        try:
            lines.extend(feature.run(ctx) or [])
        except Exception as e:  # a feature never breaks the hook
            if feature.gate:
                ctx.touch()["gate"]["allowed_by_error"] = ctx.state["gate"].get("allowed_by_error", 0) + 1
                lines.append(Line(f"Daedalus: the {feature.name} check didn't run ({type(e).__name__}: {e}); "
                                  "the call was allowed.", kind="notice"))
    lines = _budgeted(ctx, lines) if any(ln.kind == "nudge" for ln in lines) else lines
    if ctx.dirty and ctx.session_id:
        try:
            state_mod.save(ctx.state)
        except OSError:
            pass
    return render(event, lines)
