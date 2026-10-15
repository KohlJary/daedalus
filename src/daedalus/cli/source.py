"""
`daedalus source`: connect outside trackers to the roadmap and gameplan (edict 0011).

Imports of the sources package stay inside the commands, so loading the CLI (which the hooks do on
every session start) never discovers plugins.
"""

from __future__ import annotations

from pathlib import Path

import click


@click.group("source")
def source():
    """Sources: outside trackers (GitHub Issues, Azure DevOps, plugins) feeding the roadmap.

    A sync turns the tracker's items into pending proposals (`daedalus gameplan pending`); nothing
    changes the plan until you apply them. Finishing sourced work proposes a write-back, which
    calls the tracker only when you apply it.
    """


@source.command("list")
def source_list():
    """Installed source plugins, and the sources configured or active here."""
    from .. import sources
    from ..config import configured_source_names

    project_dir = Path.cwd()
    click.echo("Installed plugins:")
    for name in sources.installed():
        cls = sources.plugin_class(name)
        notes = ["write-back" if cls.supports_write_back else "read-only"]
        if not cls.verified:
            notes.append("unverified")
        click.echo(f"  {name:10} {cls.title} ({', '.join(notes)})")
    for name, error in sources.broken().items():
        click.echo(f"  {name:10} failed to load: {error}")
    if not sources.installed() and not sources.broken():
        click.echo("  none: the install's metadata registers no sources. It's probably stale (an editable install "
                   "made before sources existed). Run `daedalus doctor` for how to reinstall.")
    configured = configured_source_names(project_dir)
    active = sources.active(project_dir)
    names = configured + [n for n in active if n not in configured]
    click.echo("Sources here:" if names else "Sources here: none (configure one with `daedalus config sources.<name>.<key>`)")
    for name in names:
        try:
            src = sources.create(project_dir, name)
        except KeyError as e:
            click.echo(f"  {name:10} {str(e).strip(chr(39))}")
            continue
        status = "active" if name in active else ("disabled" if not src.settings.get("enabled", True)
                                                   else "not configured yet")
        stype = sources.source_type_of(project_dir, name)
        kind = "" if stype == name else f" ({stype})"
        click.echo(f"  {name:10}{kind} {status}, on_conflict={src.settings.get('on_conflict')}")


@source.command("sync")
@click.argument("name", required=False)
@click.option("--dry-run", is_flag=True, help="Print the proposals a sync would make; write nothing")
@click.option("--workstream", "-w", default=None, help="Write proposals for this workstream (default: the current one)")
def source_sync(name, dry_run, workstream):
    """Bring a source's items in as pending proposals (all active sources when NAME is omitted).

    Run the first sync of each source with --dry-run.
    """
    from .. import sources
    from .. import workstreams as ws
    from ..sources import sync as sync_mod
    from . import gameplan as gp

    project_dir = Path.cwd()
    try:
        ws.validate_id(workstream) if workstream else None
    except ws.WorkstreamError as e:
        raise click.UsageError(str(e))
    if workstream and workstream not in ws.list_ids(project_dir):
        raise click.UsageError(f"No workstream '{workstream}' here. Create it with `daedalus workstream new "
                               f"{workstream}`, or see `daedalus workstream list`.")
    ws.set_override(workstream)
    try:
        _sync(project_dir, name, dry_run)
    finally:
        ws.set_override(None)


def _sync(project_dir, name, dry_run):
    from .. import sources
    from .. import workstreams as ws
    from ..sources import sync as sync_mod
    from . import gameplan as gp

    names = [name] if name else sources.active(project_dir)
    if not names:
        click.echo("No active sources here. See `daedalus source list`.")
        return
    failed = False
    for n in names:
        try:
            result = sync_mod.sync(project_dir, n, dry_run=dry_run)
        except KeyError as e:
            click.echo(f"{n}: {str(e).strip(chr(39))}", err=True)
            failed = True
            continue
        if result.error:
            click.echo(f"{n}: {result.health}: {result.error}", err=True)
            failed = True
            continue
        verb = "would propose" if dry_run else "proposed"
        target = ws.current(project_dir)
        click.echo(f"{n}: {verb} {len(result.proposals)} update(s) for workstream {target}"
                   + ("" if result.health == "ok" else f" [{result.health}]"))
        for p in result.proposals:
            label = p.get("id", "-")
            click.echo(f"  {label}: {gp.describe_proposal(p)}")
        for line in result.resolved:
            click.echo(f"  {'would settle' if dry_run else 'settled'} by on_conflict: {line}")
        for line in result.skipped:
            click.echo(f"  skipped: {line}")
    if not dry_run and any(True for _ in names):
        click.echo("Review with `daedalus gameplan pending`; apply or drop each.")
    if failed:
        raise SystemExit(1)


@source.command("status")
def source_status():
    """Each source's last sync, item count and health (ok, unverified, never-synced, auth-failed, unreachable)."""
    from .. import roadmap, sources
    from ..config import configured_source_names
    from ..sources import state

    project_dir = Path.cwd()
    states = state.load(project_dir)
    names = configured_source_names(project_dir)
    names += [n for n in sources.active(project_dir) if n not in names]
    names += [n for n in states if n not in names]
    if not names:
        click.echo("No sources here. See `daedalus source list`.")
        return
    index = roadmap.load_index(project_dir)
    for n in names:
        entry = states.get(n, {})
        count = len(roadmap.by_external(index, n))
        health = entry.get("health") or "never-synced"
        last = entry.get("last_sync") or "never"
        click.echo(f"{n:10} {health:13} last sync {last}, {count} item(s)")
        if entry.get("error") and health in ("auth-failed", "unreachable"):
            click.echo(f"           {entry['error']}")
        if entry.get("skipped"):
            click.echo(f"           {len(entry['skipped'])} item(s) waiting for a phase; first: {entry['skipped'][0]}")
        if entry.get("dropped"):
            click.echo(f"           {len(entry['dropped'])} dropped item(s) a sync won't propose again")


@source.command("login")
@click.argument("name")
def source_login(name):
    """Store a source's token in the system keyring (never in a config file)."""
    from .. import sources
    from ..sources import credentials

    try:
        sources.create(Path.cwd(), name)
    except KeyError as e:
        raise click.UsageError(str(e).strip(chr(39)))
    token = click.prompt(f"Token for {name}", hide_input=True)
    try:
        credentials.store(name, token.strip())
    except Exception as e:
        click.echo(f"Couldn't store it in the keyring: {e}. Set sources.{name}.token_env to an environment "
                   "variable instead.", err=True)
        raise SystemExit(1)
    click.echo(f"Stored the token for {name} in the system keyring.")
