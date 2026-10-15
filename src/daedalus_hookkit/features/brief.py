"""SessionStart: the gameplan-first brief (edict 0007). Exempt from the kit's speed target and budget."""

from ..core import Ctx, Line


def run(ctx: Ctx) -> list:
    try:
        from daedalus.hooks import session_start_brief
        text = session_start_brief(ctx.project_dir)
    except Exception as e:  # a broken brief must not block the session
        text = f"## Daedalus\n(session brief unavailable: {e}) Run /inhale."
    return [Line(text, kind="brief")] if text else []
