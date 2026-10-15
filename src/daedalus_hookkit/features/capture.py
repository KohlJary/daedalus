"""SessionEnd and PreCompact: propose gameplan updates from new commits (edict 0007). State only: these
events never reach the model, so the proposals are surfaced by the SessionStart brief instead."""

from ..core import Ctx


def run(ctx: Ctx) -> list:
    from daedalus.hooks import capture

    capture(ctx.project_dir)
    return []
