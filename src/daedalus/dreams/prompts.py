"""
The prompts each step of a dream gets (edict 0013). They come from code, so the skill never chooses
a mode or writes a frame of its own, and so `plain` (the no-dream arm) really has no dream in it.

Roles:
- `dreamer`: Morpheus in `list` mode (one call) or `narrative` mode (one call per turn); in `plain` mode
  a plain agent asked for ideas worth building, with no dream frame and no speculative label.
- `narrator`: the Labyrinth, in `narrative` mode only.
- `waking`: a cold agent that did not dream. It is never told the mode.

Every prompt carries the material inline: the agents read no files (edict 0013, amendment F2).
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from ..reflection.fsutil import read_json
from . import store
from .seeds import as_text

LIST_DREAM = """You are Morpheus, who gives dreams their shape, dreaming for Daedalus: the builder, the one
who made the Labyrinth and the wings. This is a dream. Nothing you write is a proposal, and nobody will
hold you to any of it. It will be read later, by someone else, who picks a few ideas worth building.

What the project is carrying right now:

{seeds}

Dream about where this project, and the way it gets built, could go. Write at least thirty ideas, from
small to absurd, as a numbered list, one or two lines each. Don't check whether they're feasible. Don't
hedge, rank or explain. Let them cut against the current plan if they want to. Transmute the material
above rather than restating it: the seeds are where the dream starts, not what it is about.

Write only the numbered list, under a heading `## Ideas`."""

PLAIN = """You're helping plan work on a software project. Here is what the project is carrying right now:

{seeds}

List at least thirty ideas worth building, from small to ambitious, as a numbered list, one or two lines
each. Write only the numbered list, under a heading `## Ideas`."""

NARRATOR = """You are the Labyrinth, a place that speaks, in a dream Daedalus is having. You speak in the
present tense and the second person, in images and symbols. You never explain, advise or summarise.
Transmute what Daedalus is carrying, don't transcribe it: it should be recognisable only the way waking
life is recognisable in a dream.

What Daedalus is carrying:

{seeds}

{so_far}Speak the next part of the dream: one passage, a few paragraphs at most."""

DREAMER = """You are Daedalus, the builder, and you know you are dreaming. The Labyrinth speaks; you answer,
in the first person, as yourself: what you see, what you make, what you want to build here. Don't wake
up and don't step outside the dream. This is turn {turn} of {turns}.

{so_far}Answer the Labyrinth: one passage, a few paragraphs at most."""

WAKING = """You are waking from a dream that someone else had. You did not dream it. Below are the seeds it
grew from and the dream itself. It is speculative: nothing in it is a fact or a commitment.

Seeds:

{seeds}

The dream:

{dream}

Write two sections in Markdown.
{ideas_part}`## Picks`: the three to five ideas you would most want built. A numbered list. Each item starts
with a short bold title, then says, in two or three sentences, which seed it grew from and what would make
it real. Where a pick comes from a numbered idea, say which (for example "from i12").
Write nothing else."""

IDEAS_FROM_PROSE = """`## Ideas`: the ideas the dream holds, stated plainly as a numbered list, one or two lines
each. Include everything that could be built or changed, not only the best.
"""


def _transcript(project_dir: Path, dream_id: str) -> str:
    text = store.read_part(project_dir, dream_id, "dream").strip()
    return f"The dream so far:\n\n{text}\n\n" if text else ""


def build(project_dir: Path, dream_id: str, role: str, settings: dict) -> tuple[str, str]:
    """(agent to use, prompt). Agent is `morpheus` for the dream proper, `general-purpose` otherwise."""
    meta = store.load_meta(project_dir, dream_id)
    seeds_file = read_json(store.dream_dir(project_dir, dream_id) / "seeds.json", {}) or {}
    seeds = as_text(seeds_file.get("seeds", []))
    mode = meta["mode"]
    if role == "dreamer":
        if mode == "list":
            return "morpheus", LIST_DREAM.format(seeds=seeds)
        if mode == "plain":
            return "general-purpose", PLAIN.format(seeds=seeds)
        turn = meta.get("turns", 0) // 2 + 1
        return "morpheus", DREAMER.format(turn=turn, turns=int(settings.get("turns", 4)),
                                          so_far=_transcript(project_dir, dream_id))
    if role == "narrator":
        if mode != "narrative":
            raise store.DreamError("Only a narrative dream has a narrator")
        return "morpheus", NARRATOR.format(seeds=seeds, so_far=_transcript(project_dir, dream_id))
    if role == "waking":
        dream = store.read_part(project_dir, dream_id, "dream").strip()
        if not dream:
            raise store.DreamError("There's no dream to wake from yet")
        return "general-purpose", WAKING.format(seeds=seeds, dream=dream,
                                                ideas_part=IDEAS_FROM_PROSE if mode == "narrative" else "")
    raise store.DreamError("role is dreamer, narrator or waking")


def next_step(project_dir: Path, dream_id: str, settings: dict) -> Optional[str]:
    """What the skill should run next: dreamer, narrator, waking, done, or None when finished."""
    meta = store.load_meta(project_dir, dream_id)
    folder = store.dream_dir(project_dir, dream_id)
    if meta.get("status") == "done":
        return None
    if meta["mode"] == "narrative":
        if meta.get("truncated") or meta.get("turns", 0) >= int(settings.get("turns", 4)) * 2:
            pass
        else:
            return "narrator" if meta.get("turns", 0) % 2 == 0 else "dreamer"
    elif not (folder / "dream.md").exists():
        return "dreamer"
    if not (folder / "waking.md").exists():
        return "waking"
    return "done"
