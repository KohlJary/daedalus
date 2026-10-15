"""`daedalus context`: the context map (edict 0015). The hooks are the normal path; this is for looking."""

import json
from pathlib import Path

import click


def _table(rows: list, label: str, limit: int) -> list[str]:
    lines = []
    for r in rows[:limit]:
        quiet = "quiet" if r.get("quiet") else ""
        how = r.get("how", "attributed")
        lines.append(f"  {r['share'] * 100:5.1f}%  {r['tokens']:>8}  {how:<10} {quiet:<5}  {r[label]}")
    if len(rows) > limit:
        lines.append(f"  ... {len(rows) - limit} more (--all)")
    return lines


@click.group("context", invoke_without_command=True)
@click.option("--by", "by", type=click.Choice(["subject", "task"]), default="subject", help="Group by subject or by task")
@click.option("--all", "show_all", is_flag=True, help="Every line, not just the ten largest")
@click.option("--json", "as_json", is_flag=True, help="The full map as JSON (the dict context.measure returns)")
@click.option("--session", default=None, help="A session id (default: this project's latest session)")
@click.pass_context
def context(ctx, by, show_all, as_json, session):
    """How big the context is and what fills it, since the last compaction (edict 0015)."""
    if ctx.invoked_subcommand:
        return
    from .. import context as cmap

    try:
        m = cmap.measure(Path.cwd(), session_id=session)
    except FileNotFoundError as e:
        raise click.ClickException(str(e))
    if as_json:
        click.echo(json.dumps(m, indent=2))
        return
    if not m["measured"]:
        click.echo("No request since the last compaction yet: nothing measured.")
        return
    window = f"{m['window_tokens']:,}" + ("" if m["window_known"] else " (a guess; set context.window_tokens)")
    click.echo(f"Context: {m['used_tokens']:,} tokens (exact) of {window}, "
               f"{m['used_tokens'] / m['window_tokens'] * 100:.0f}%. Session {m['session_id']}.")
    click.echo("Shares within each step are attributed by size; 'estimated' lines came from a step smaller than "
               "Daedalus's own output.")
    rows = m["by_subject"] if by == "subject" else m["by_task"]
    label = "subject" if by == "subject" else "task"
    click.echo("\n".join(_table(rows, label, len(rows) if show_all else 10)))
    if m["pending_tokens"]:
        click.echo(f"  pending: about {m['pending_tokens']:,} tokens added since the last request (estimated)")
    click.echo(f"Quiet for {m['quiet_minutes']} min: {m['quiet_share'] * 100:.0f}% "
               f"({m['quiet_tokens']:,} tokens): what an exhale could let go.")
