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
    followed. decision: a gate's "deny" or "allow". cycle: the feature's cycle (a commit, a compaction):
    a nudge id prints at most once per cycle. limit: the line's length cap (MAX_LINE unless the feature
    needs its whole text, such as a board note's "data, not instructions" tail).
    """

    __slots__ = ("text", "kind", "nudge", "tool", "decision", "cycle", "limit")

    def __init__(self, text: str, kind: str = "nudge", nudge: str = "", tool: str = "", decision: str = "",
                 cycle: str = "", limit: int = 0):
        self.text, self.kind, self.nudge, self.tool, self.decision = text, kind, nudge, tool, decision
        self.cycle, self.limit = cycle, limit


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
    """Apply the noise budget to nudges: at most budget_per_hour per session-hour, one per call, and a
    nudge id at most once per cycle. Printed nudges are logged for efficacy; dropped ones are counted.

    The budget is counted from its own list of timestamps (budget_log), which nothing trims inside the
    hour, so a flood of attempts can't push counted nudges out of the event log and refill it."""
    per_hour = int(ctx.settings.get("hooks", "budget_per_hour"))
    st = ctx.state
    hour_ago = ctx.now - 3600
    log = [t for t in st.get("budget_log", []) if isinstance(t, (int, float)) and t >= hour_ago]
    fired = st.setdefault("fired", {})
    kept, spoke = [], False
    for line in lines:
        if line.kind != "nudge":
            kept.append(line)
            continue
        ctx.dirty = True
        if line.cycle and fired.get(line.nudge) == line.cycle:
            continue  # already said this cycle: not a drop, just not news
        if spoke or len(log) >= per_hour:
            # one dropped event per nudge id, updated in place, so drops can never evict the counted
            # nudges efficacy reads; the totals are in st["dropped"]
            dropped = st.setdefault("dropped", {})
            dropped[line.nudge] = dropped.get(line.nudge, 0) + 1
            entry = next((e for e in st["events"] if e.get("dropped") and e.get("nudge") == line.nudge), None)
            if entry is None:
                st["events"].append({"at": ctx.now, "hook": line.nudge.split(":")[0], "event": ctx.event,
                                     "nudge": line.nudge, "followed": None, "tool": line.tool, "dropped": True,
                                     "dropped_count": 1})
            else:
                entry["at"], entry["dropped_count"] = ctx.now, entry.get("dropped_count", 1) + 1
            continue
        log.append(ctx.now)
        spoke = True
        if line.cycle:
            fired[line.nudge] = line.cycle
        st["events"].append({"at": ctx.now, "hook": line.nudge.split(":")[0], "event": ctx.event,
                             "nudge": line.nudge, "followed": None, "tool": line.tool, "counted": True})
        kept.append(line)
    st["budget_log"] = log
    st["budget"] = {"per_hour": per_hour, "used": len(log)}
    return kept


def _cut(line: Line) -> str:
    limit = line.limit or MAX_LINE
    if line.kind == "brief" or len(line.text) <= limit:
        return line.text
    return line.text[:limit - 1] + "…"


def render(event: str, lines: list) -> str:
    if event in SILENT_EVENTS or not lines:
        return ""
    texts = [_cut(ln) for ln in lines if ln.decision != "deny"]
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
    if event in ("SessionStart", "SessionEnd"):
        state_mod.prune(ctx.now)
    if event == "SessionStart":
        state_mod.heartbeat(event, ctx.now)
    # One dispatcher of a session at a time: parallel tool calls fire parallel hooks, and state is
    # load-modify-save. A lock that can't be had in time means this call reads but doesn't write.
    with state_mod.locked(ctx.session_id) as have_lock:
        out = _run(ctx, event, features, counted=have_lock or not ctx.session_id)
        if ctx.dirty and ctx.session_id and have_lock:
            try:
                state_mod.save(ctx.state)
            except OSError:
                pass
    return out


def _run(ctx: Ctx, event: str, features: list, counted: bool = True) -> str:
    """counted=False when the state can't be saved (the lock wasn't had): nudges are then held back,
    since a nudge the budget can't count would let a stuck holder push the budget over."""
    settings = ctx.settings
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
    if not counted:
        lines = [ln for ln in lines if ln.kind != "nudge"]
    lines = _budgeted(ctx, lines) if any(ln.kind == "nudge" for ln in lines) else lines
    return render(event, lines)
