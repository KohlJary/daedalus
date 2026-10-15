"""
`daedalus dream`: the deterministic parts of dreaming (edict 0013). The /dream skill drives them: it
starts a dream, hands each prompt to the agent the command names, writes what comes back through these
commands, and finishes with `dream done`. Nothing here calls a model.
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path
from typing import Optional

import click


def _settings(project_dir: Path) -> dict:
    from ..config import get_project_settings

    return get_project_settings(project_dir, "dream")


def _fail(e: Exception):
    click.echo(str(e), err=True)
    raise SystemExit(1)


def _text(file: Optional[str]) -> str:
    return Path(file).read_text(encoding="utf-8") if file else sys.stdin.read()


@click.group("dream")
def dream():
    """Dreaming (edict 0013): speculative, generated before it's judged, kept out of the plan.

    A dream starts from seeds, is dreamt hot, and is read back cold by an agent that didn't dream it.
    Its picks reach the roadmap only through `daedalus source sync dream`, as proposals you apply or
    drop. Nothing reads a dream as evidence.
    """


@dream.command("seeds")
@click.option("--theme", default=None, help="A theme to dream about; it becomes the first seed")
@click.option("--all", "show_all", is_flag=True, help="Every candidate with its score, not just the chosen ones")
def dream_seeds(theme, show_all):
    """The seeds a dream would start from now, by readiness."""
    from ..dreams import seeds as s

    project = Path.cwd()
    items = s.score(project, s.candidates(project, _settings(project), date.today())) if show_all \
        else s.select_seeds(project, _settings(project), theme=theme)
    if not items:
        click.echo("No seeds: nothing stalled, waiting, open or unexplained. Give a theme with --theme.")
    for it in items:
        score = "theme" if it.get("readiness") is None else f"{it['readiness']:.2f}"
        click.echo(f"{score:>5}  {it['id']}: {it['text'][:110]}")


@dream.command("start")
@click.option("--theme", default=None, help="A theme to dream about")
@click.option("--mode", type=click.Choice(["list", "narrative", "plain"]), default=None,
              help="Force a mode (outside the A/B comparison); default: dream.mode")
def dream_start(theme, mode):
    """Start a dream: choose the seeds, draw the mode in code, and log both."""
    from ..dreams import prompts, store

    project = Path.cwd()
    try:
        meta = store.start(project, _settings(project), theme=theme, mode=mode)
    except store.DreamError as e:
        _fail(e)
    click.echo(f"Started dream {meta['id']}. Next: `daedalus dream prompt {meta['id']} "
               f"{prompts.next_step(project, meta['id'], _settings(project))}`")


@dream.command("bundle")
@click.argument("dream_id")
def dream_bundle(dream_id):
    """Print a dream's seeds bundle (what the dreamer is given), as JSON."""
    from ..dreams import store
    from ..reflection.fsutil import read_json

    try:
        click.echo(json.dumps(read_json(store.dream_dir(Path.cwd(), dream_id) / "seeds.json", {}), indent=2))
    except store.DreamError as e:
        _fail(e)


@dream.command("prompt")
@click.argument("dream_id")
@click.argument("role", type=click.Choice(["dreamer", "narrator", "waking", "next"]))
def dream_prompt(dream_id, role):
    """Print the prompt for a step. The first line names the agent to hand it to."""
    from ..dreams import prompts, store

    project = Path.cwd()
    try:
        if role == "next":
            role = prompts.next_step(project, dream_id, _settings(project)) or "done"
            if role == "done":
                click.echo(f"Nothing left to dream: finish with `daedalus dream done {dream_id}`.")
                return
        agent, text = prompts.build(project, dream_id, role, _settings(project))
    except store.DreamError as e:
        _fail(e)
    click.echo(f"AGENT: {agent} ({role})")
    click.echo("---")
    click.echo(text)


@dream.command("turn")
@click.argument("dream_id")
@click.argument("speaker", type=click.Choice(["narrator", "dreamer"]))
@click.option("--file", "file", type=click.Path(exists=True, dir_okay=False), default=None)
def dream_turn(dream_id, speaker, file):
    """Narrative mode: append one turn (from FILE or stdin)."""
    from ..dreams import prompts, store

    project = Path.cwd()
    try:
        store.append_turn(project, dream_id, speaker, _text(file), _settings(project))
    except store.DreamError as e:
        _fail(e)
    click.echo(f"Next: {prompts.next_step(project, dream_id, _settings(project))}")


@dream.command("write")
@click.argument("dream_id")
@click.argument("part", type=click.Choice(["dream", "waking"]))
@click.option("--file", "file", type=click.Path(exists=True, dir_okay=False), default=None)
def dream_write(dream_id, part, file):
    """Write the dream (list and plain modes) or the waking pass, from FILE or stdin. The label is added."""
    from ..dreams import prompts, store

    project = Path.cwd()
    try:
        path = store.write_part(project, dream_id, part, _text(file), _settings(project))
    except store.DreamError as e:
        _fail(e)
    click.echo(f"Wrote {path}. Next: {prompts.next_step(project, dream_id, _settings(project))}")


@dream.command("done")
@click.argument("dream_id")
@click.option("--tokens", type=int, default=None, help="Tokens the dream's agents spent (from their notices)")
@click.option("--dreamer-model", default=None)
@click.option("--waking-model", default=None)
def dream_done(dream_id, tokens, dreamer_model, waking_model):
    """Finish a dream: count its ideas and picks (by code) and log the run."""
    from ..dreams import store

    project = Path.cwd()
    models = {k: v for k, v in {"dreamer": dreamer_model, "waking": waking_model}.items() if v}
    try:
        # No runner can set a temperature yet (edict 0013, amendment F1), so it is always logged as unset
        meta = store.done(project, dream_id, models, tokens, "unset")
    except store.DreamError as e:
        _fail(e)
    click.echo(f"Dream {dream_id}: {meta['ideas']} ideas, {meta['picks']} picks. Read it with "
               f"`daedalus dream show {dream_id}`; bring the picks in with `daedalus source sync dream`.")


@dream.command("due")
def dream_due():
    """Whether a dream is due (after a reflection run, at most one a day) and whether one is waiting."""
    from ..dreams import review, store

    project = Path.cwd()
    state = store.refresh_due(project)
    click.echo("A dream is due." if state["due"] else "No dream is due.")
    if state["waiting"]:
        click.echo(f"The dream from {state['waiting']} is waiting: `daedalus dream show {state['waiting']}`.")
    if review.review_due(project, _settings(project)):
        click.echo("A dream review is due: `daedalus dream review bundle`.")


@dream.command("show")
@click.argument("dream_id", required=False)
def dream_show(dream_id):
    """Print a dream (the newest by default), its waking pass and its picks."""
    from ..dreams import store

    try:
        click.echo(store.show(Path.cwd(), dream_id))
    except store.DreamError as e:
        _fail(e)


@dream.command("keep")
@click.argument("dream_id")
@click.option("--include-private", is_flag=True, help="Keep it even though a seed was private (work projects)")
def dream_keep(dream_id, include_private):
    """Copy a dream to docs/dreams/<id>.md, for you to commit if you choose."""
    from ..config import get_project_settings
    from ..dreams import store

    project = Path.cwd()
    scope = get_project_settings(project, "reflection").get("scope", "work")
    try:
        path = store.keep(project, dream_id, include_private, scope)
    except store.DreamError as e:
        _fail(e)
    click.echo(f"Kept {path}. Committing it is your choice.")


@dream.command("log")
def dream_log():
    """The experiment: dreams per mode, picks applied and built, against non-dream intake."""
    from ..dreams.report import summary

    for line in summary(Path.cwd()):
        click.echo(line)


@dream.group("review")
def dream_review():
    """Themes that recur across dreams (monthly, or on request)."""


@dream_review.command("bundle")
def dream_review_bundle():
    """Write the review bundle and print the prompt for the review agent."""
    from ..dreams import review
    from ..reflection.fsutil import write_json

    project = Path.cwd()
    bundle = review.build_bundle(project)
    if not bundle["dreams"]:
        _fail(Exception("No finished dreams since the last review."))
    path = review.reviews_dir(project) / f"{bundle['date']}.bundle.json"
    write_json(path, bundle)
    click.echo(f"BUNDLE: {path}")
    click.echo("AGENT: general-purpose (review)")
    click.echo("---")
    click.echo(review.prompt(bundle))


@dream_review.command("record")
@click.argument("answer", type=click.Path(exists=True, dir_okay=False))
@click.option("--bundle", "bundle_file", type=click.Path(exists=True, dir_okay=False), required=True)
def dream_review_record(answer, bundle_file):
    """Check the review agent's themes, count them, and elevate the recurring ones nothing covers."""
    from ..dreams import review, store

    project = Path.cwd()
    try:
        out = review.record(project, json.loads(Path(bundle_file).read_text(encoding="utf-8")),
                            Path(answer).read_text(encoding="utf-8"), _settings(project))
    except (store.DreamError, ValueError) as e:
        _fail(e)
    elevated = [t for t in out["themes"] if t["elevated"]]
    click.echo(f"Review {out['review']}: {len(out['themes'])} theme(s), {len(elevated)} elevated"
               + (f", {len(out['dropped'])} dropped for unknown IDs" if out["dropped"] else ""))
    if elevated:
        click.echo("Bring them in with `daedalus source sync dream`.")


@dream_review.command("show")
def dream_review_show():
    """Print the newest dream review."""
    from ..dreams import review

    files = sorted(p for p in review.reviews_dir(Path.cwd()).glob("*.md")) if review.reviews_dir(Path.cwd()).is_dir() else []
    if not files:
        _fail(Exception("No dream reviews yet."))
    click.echo(files[-1].read_text(encoding="utf-8"))
