"""UserPromptSubmit: note new posts in followed board threads (edict 0009). Throttled by the board itself."""

from ..core import Ctx, Line


def run(ctx: Ctx) -> list:
    from daedalus.hooks import board_check

    note = board_check(ctx.project_dir)
    return [Line(note, nudge="board", tool="bash:daedalus board read")] if note else []
