"""
Efficacy (edict 0016): did a nudge lead to the tool it names?

Each nudge is logged with the tool its advice points to ("agent:momus", "skill:exhale",
"bash:daedalus gameplan pending", "tool:Read"). Once a nudge is pending, every later tool call (and
prompt) is an event. A nudge is followed when a matching call comes within hooks.efficacy_window events,
and ignored once the window has passed. While nothing is pending this feature reads the state and
writes nothing, so it costs almost nothing.
"""

from ..core import Ctx


def _matches(spec: str, tool_name: str, tool_input: dict, prompt: str) -> bool:
    kind, _, want = spec.partition(":")
    if not want:
        return False
    if prompt:
        # a slash command typed by the user counts for its skill (`/exhale` for skill:exhale)
        return kind == "skill" and prompt.lstrip().split(" ", 1)[0] in (f"/{want}", f"/daedalus:{want}")
    if kind == "agent":
        return tool_name in ("Agent", "Task") and str(tool_input.get("subagent_type") or "general-purpose") == want
    if kind == "skill":
        name = str(tool_input.get("skill") or tool_input.get("command") or "")
        return tool_name == "Skill" and name.rsplit(":", 1)[-1] == want
    if kind == "bash":
        return tool_name == "Bash" and want in str(tool_input.get("command") or "")
    if kind == "tool":
        return tool_name == want
    return False


def run(ctx: Ctx) -> list:
    st = ctx.state
    pending = [e for e in st["events"] if e.get("counted") and e.get("followed") is None and e.get("tool")]
    if not pending:
        return []
    window = int(ctx.settings.get("hooks", "efficacy_window"))
    st = ctx.touch()
    seq = st["event_seq"] = int(st.get("event_seq", 0)) + 1
    p = ctx.payload
    tool_name = str(p.get("tool_name") or "")
    tool_input = p.get("tool_input") if isinstance(p.get("tool_input"), dict) else {}
    prompt = str(p.get("prompt") or "") if ctx.event == "UserPromptSubmit" else ""
    for e in pending:
        start = int(e.get("seq", seq - 1))
        if _matches(e["tool"], tool_name, tool_input, prompt):
            e["followed"] = True
            e["followed_after"] = seq - start
        elif seq - start >= window:
            e["followed"] = False
    return []

