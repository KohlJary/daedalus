"""
Efficacy (edict 0016): did a nudge lead to the tool it names?

Each nudge is logged with the tool its advice points to: "agent:momus", "skill:exhale",
"bash:daedalus gameplan pending" or "tool:Read". A pending nudge ages only on events that could show it
was followed. Tool calls (PostToolUse) count for every kind. A prompt counts only for a skill, since a
typed `/exhale` follows skill:exhale. So a nudge that needs a tool call stays pending, never "ignored",
while no PostToolUse hook is registered to see one. It is followed when a matching event comes within
hooks.efficacy_window of its own observable events, and ignored once that window has passed. While
nothing is pending, this feature reads the state and writes nothing.
"""

from ..core import Ctx
from ..shell import commands


def _segments(command: str) -> list:
    """Each command in a shell line as text (quote-aware, heredoc bodies dropped)."""
    return [" ".join(words) for words in commands(command)]


def _skill_name(name: str) -> str:
    """`exhale` or `daedalus:exhale` -> exhale; another plugin's skill keeps its prefix."""
    return name[len("daedalus:"):] if name.startswith("daedalus:") else name


def observable(spec: str, event: str) -> bool:
    return event == "PostToolUse" or (event == "UserPromptSubmit" and spec.startswith("skill:"))


def _matches(spec: str, tool_name: str, tool_input: dict, prompt: str) -> bool:
    kind, _, want = spec.partition(":")
    if not want:
        return False
    if prompt:
        words = prompt.split()
        return kind == "skill" and bool(words) and _skill_name(words[0].lstrip("/")) == want \
            and words[0].startswith("/")
    if kind == "agent":
        agent = _skill_name(str(tool_input.get("subagent_type") or "general-purpose"))
        return tool_name in ("Agent", "Task") and agent == want
    if kind == "skill":
        return tool_name == "Skill" and _skill_name(str(tool_input.get("skill") or "")) == want
    if kind == "bash":
        return tool_name == "Bash" and any(s == want or s.startswith(want + " ")
                                           for s in _segments(str(tool_input.get("command") or "")))
    if kind == "tool":
        return tool_name == want
    return False


def run(ctx: Ctx) -> list:
    st = ctx.state
    pending = [e for e in st["events"] if e.get("counted") and e.get("followed") is None and e.get("tool")
               and observable(e["tool"], ctx.event)]
    if not pending:
        return []
    window = int(ctx.settings.get("hooks", "efficacy_window"))
    ctx.touch()
    p = ctx.payload
    tool_name = str(p.get("tool_name") or "")
    tool_input = p.get("tool_input") if isinstance(p.get("tool_input"), dict) else {}
    prompt = str(p.get("prompt") or "") if ctx.event == "UserPromptSubmit" else ""
    for e in pending:
        e["age"] = int(e.get("age", 0)) + 1
        if _matches(e["tool"], tool_name, tool_input, prompt):
            e["followed"] = True
            e["followed_after"] = e["age"]
        elif e["age"] >= window:
            e["followed"] = False
    return []
