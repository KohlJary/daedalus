"""
Daedalus CLI entry point.

Commands:
  init      Initialize Daedalus in current project
  hydrate   Inject/update templates and agents
  doctor    Check memory and plans for drift
  config    Manage global configuration
  palace    Mind Palace operations
"""

import click
from pathlib import Path

from ..config import (
    load_config,
    save_config,
    get_config_dir,
    get_nested_value,
    set_nested_value,
)


@click.group()
@click.version_option(package_name="daedalus-cli")
def main():
    """Daedalus - Claude Code plugin for structured development."""
    pass


@main.command()
@click.option("--force", is_flag=True, help="Overwrite existing files")
@click.option("--hooks/--no-hooks", default=True, help="Register Claude Code hooks in .claude/settings.json")
def init(force: bool, hooks: bool):
    """Initialize Daedalus in the current project.

    Creates:
      - .daedalus/        (project memory directory)
      - .claude/agents/   (copies bundled agents)
      - CLAUDE.md         (injects Daedalus section)
    """
    from .commands import init_project

    init_project(Path.cwd(), force=force, hooks=hooks)


@main.command()
@click.option("--agents/--no-agents", default=True, help="Copy agents to .claude/agents/")
@click.option("--template/--no-template", default=True, help="Inject CLAUDE.md template")
@click.option("--skills/--no-skills", default=True, help="Install plugin skills to .claude/skills/")
@click.option("--hooks/--no-hooks", default=True, help="Register Claude Code hooks in .claude/settings.json")
@click.option("--dry-run", is_flag=True, help="Show what would change (CLAUDE.md diff, agents, skills, hooks); write nothing")
def hydrate(agents: bool, template: bool, skills: bool, hooks: bool, dry_run: bool):
    """Update Daedalus assets in current project.

    Re-injects the CLAUDE.md template and optionally updates agents. Text inside the
    DAEDALUS_LOCAL slots of CLAUDE.md is kept; the rest of the managed section is replaced.
    """
    from .commands import hydrate_project

    hydrate_project(Path.cwd(), agents=agents, template=template, dry_run=dry_run, skills=skills, hooks=hooks)


@main.command("config")
@click.argument("key", required=False)
@click.argument("value", required=False)
@click.option("--project", is_flag=True, help="Template settings for this project (.daedalus/config.json)")
def config_cmd(key: str, value: str, project: bool):
    """View or set configuration.

    Examples:
      daedalus config                    # Show all config
      daedalus config user.name          # Show specific key
      daedalus config user.name "Kohl"   # Set value
      daedalus config --project                          # Template settings in effect here
      daedalus config --project git.authorship user      # Override for this project
      daedalus config --project sections.squash false
    """
    import json

    if project:
        from ..config import get_project_settings, get_template_settings, set_project_value

        if key is None or value is None:
            settings = get_template_settings(Path.cwd())
            for group in ("doctor", "hooks"):
                settings[group] = get_project_settings(Path.cwd(), group)
            if key is None:
                click.echo(json.dumps(settings, indent=2))
            else:
                group, _, name = key.partition(".")
                val = settings.get(group, {}).get(name)
                click.echo("(not a template setting)" if val is None else str(val))
        elif set_project_value(Path.cwd(), key, value):
            click.echo(f"Set {key} = {value} for this project (.daedalus/config.json)")
        else:
            click.echo(f"Unknown template setting or invalid value: {key} = {value}", err=True)
        return

    config = load_config()

    if key is None:
        # Show all config
        from dataclasses import asdict

        click.echo(json.dumps(asdict(config), indent=2))
    elif value is None:
        # Show specific key
        val = get_nested_value(config, key)
        click.echo(val if val else "(not set)")
    else:
        # Set value
        if set_nested_value(config, key, value):
            save_config(config)
            click.echo(f"Set {key} = {value}")
        else:
            click.echo(f"Unknown config key: {key}", err=True)


@main.group("hook")
def hook():
    """Claude Code hook entry points (registered by init/hydrate)."""
    pass


@hook.command("session-start")
def hook_session_start():
    """Print the gameplan-first session brief. Never fails the session."""
    from ..hooks import session_start_brief

    try:
        brief = session_start_brief(Path.cwd())
    except Exception as e:  # a broken brief must not block the session
        brief = f"## Daedalus\n(session brief unavailable: {e}) Run /inhale."
    if brief:
        click.echo(brief)


@hook.command("capture")
def hook_capture():
    """Propose gameplan updates from commits (SessionEnd/PreCompact). Never fails the session."""
    from ..hooks import capture

    try:
        note = capture(Path.cwd())
    except Exception as e:  # a failed capture must not block the session
        note = f"Daedalus: capture hook skipped ({e})"
    if note:
        click.echo(note)


@main.group("reconstruct")
def reconstruct():
    """Rebuild a gameplan period that went unrecorded, from git evidence (edict 0006).

    Run /reconstruct in a Claude Code session for the full flow: gather, the mnemosyne agent,
    check, and a Momus review. These subcommands are its deterministic parts.
    """
    pass


@reconstruct.command("gather")
@click.option("--since", default=None, help="Start the window at this revision instead of the gameplan's last commit")
def reconstruct_gather(since: str | None):
    """Find the gap and write the evidence bundle to .daedalus/reconstruction/."""
    from ..reconstruct import gather, write_bundle

    try:
        bundle = gather(Path.cwd(), since=since)
    except ValueError as e:
        click.echo(str(e), err=True)
        raise SystemExit(2)
    if bundle is None:
        click.echo("No gap: the gameplan is current.")
        return
    path = write_bundle(Path.cwd(), bundle)
    w = bundle.window
    diffs = sum(1 for c in bundle.commits if "diff" in c)
    low = sum(1 for c in bundle.commits if c.get("diff_reason") == "low score")
    click.echo(f"Gap: {w['commits']} commits ({w['merge_commits']} merges not counted) since "
               f"{w['from_date']} ({w['anchor']}).")
    click.echo(f"Messages scored: {low} below {bundle.settings['score_threshold']} got their diffs; "
               f"{diffs - low} more for calibration.")
    click.echo(f"Releases: {len(bundle.releases)}; documents added: {len(bundle.documents_added)}; "
               f"open tasks: {len(bundle.open_tasks)}; open roadmap items: {len(bundle.open_roadmap_items)}.")
    click.echo(f"Evidence scope: {bundle.evidence_scope}.")
    click.echo(f"Bundle: {path.relative_to(Path.cwd())}")


@reconstruct.command("check")
@click.argument("proposal", type=click.Path(exists=True, dir_okay=False))
def reconstruct_check(proposal: str):
    """Validate a reconstruction proposal: hashes, window, labels, files, coverage. Exit 1 on errors."""
    import json

    from ..reconstruct import check_proposal

    try:
        data = json.loads(Path(proposal).read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        click.echo(f"{proposal} is not valid JSON: {e}", err=True)
        raise SystemExit(1)
    result = check_proposal(Path.cwd(), data)
    for e in result.errors:
        click.echo(f"error: {e}")
    labels = ", ".join(f"{k}: {v}" for k, v in sorted(result.labels.items(), key=lambda kv: str(kv[0])))
    click.echo(f"Entries: {result.entries} ({labels or 'none'})")
    if result.uncited:
        click.echo(f"Uncited commits in the window ({len(result.uncited)}):")
        for sha in result.uncited:
            click.echo(f"  {sha[:10]}")
    else:
        click.echo("Coverage: every commit in the window is cited.")
    click.echo("OK" if not result.errors else f"{len(result.errors)} error(s)")
    raise SystemExit(1 if result.errors else 0)


@main.command("doctor")
@click.option("--json", "as_json", is_flag=True, help="Print findings as JSON")
def doctor(as_json: bool):
    """Check whether the gameplan, edicts, and memory have fallen behind the code.

    Exits 1 when anything is found, so it can run in CI.
    """
    import json
    from dataclasses import asdict

    from ..doctor import run_checks

    findings, hints = run_checks(Path.cwd())
    if as_json:
        click.echo(json.dumps({"findings": [asdict(f) for f in findings], "hints": hints}, indent=2))
    else:
        for f in findings:
            click.echo(f"{f.name}: {f.message}")
        for h in hints:
            click.echo(f"hint: {h}")
        if not findings:
            click.echo("No drift found.")
    raise SystemExit(1 if findings else 0)


@main.command("digest")
@click.option(
    "--run", "run_id",
    default=None,
    help="Run ID (default: latest run in .wonderland/telemetry/).",
)
@click.option(
    "--print", "print_only",
    is_flag=True,
    help="Print digest to stdout instead of writing to .wonderland/digests/.",
)
def digest(run_id: str | None, print_only: bool):
    """Build a digest for a Wonderland run.

    Reads .wonderland/telemetry, feature-states, phase-events, and
    artifacts to produce a markdown summary covering cost, lifecycle
    deltas, M8 verdicts, and artifact counts. Default destination
    is .wonderland/digests/run-<id>.md; pass --print to dump to
    stdout instead.

    Run from the wonderland project root (the directory containing
    the .wonderland/ folder).
    """
    from ..digest import build_digest, latest_run_id, write_digest

    project_dir = Path.cwd()
    if run_id is None:
        run_id = latest_run_id(project_dir)
        if run_id is None:
            click.echo(
                f"No telemetry found in {project_dir / '.wonderland' / 'telemetry'}",
                err=True,
            )
            raise click.Abort()
        click.echo(f"(latest run: {run_id})")

    if print_only:
        click.echo(build_digest(project_dir, run_id))
    else:
        path = write_digest(project_dir, run_id)
        click.echo(f"Wrote digest: {path.relative_to(project_dir)}")


@main.group()
def palace():
    """Mind Palace operations."""
    pass


@palace.command("init")
@click.argument("name", required=False)
def palace_init(name: str):
    """Initialize a Mind Palace for the current project."""
    from .commands import init_palace

    init_palace(Path.cwd(), name)


@palace.command("status")
def palace_status():
    """Show Mind Palace status."""
    from .commands import palace_status as _palace_status

    _palace_status(Path.cwd())


@main.group()
def roadmap():
    """Roadmap operations."""
    pass


@roadmap.command("list")
@click.option("--status", "-s", help="Filter by status (backlog, ready, in_progress, review, done)")
@click.option("--assigned", "-a", help="Filter by assignee")
def roadmap_list(status: str, assigned: str):
    """List roadmap items."""
    from .commands import list_roadmap_items

    list_roadmap_items(Path.cwd(), status=status, assigned_to=assigned)


@roadmap.command("add")
@click.argument("title")
@click.option("--description", "-d", help="Item description")
@click.option("--priority", "-p", default="P2", help="Priority (P0-P3)")
@click.option("--type", "-t", "item_type", default="task", help="Item type (task, feature, bug)")
def roadmap_add(title: str, description: str, priority: str, item_type: str):
    """Add a new roadmap item."""
    from .commands import add_roadmap_item

    add_roadmap_item(
        Path.cwd(),
        title=title,
        description=description,
        priority=priority,
        item_type=item_type,
    )


@main.group()
def gameplan():
    """Multi-phase plan tracking (survives compactions).

    A gameplan groups roadmap items into phases and breaks the currently
    active phase into concrete tasks. Stored at .daedalus/roadmap/gameplan.json
    so a fresh session can pick up in-flight work.
    """
    pass


@gameplan.command("show")
@click.option("--json", "as_json", is_flag=True, help="Dump raw JSON")
def gameplan_show(as_json: bool):
    """Show the current gameplan."""
    from .commands import show_gameplan

    show_gameplan(Path.cwd(), as_json=as_json)


@gameplan.group("phase")
def gameplan_phase():
    """Phase operations."""
    pass


@gameplan_phase.command("list")
def gameplan_phase_list():
    """List all phases."""
    from .commands import list_gameplan_phases

    list_gameplan_phases(Path.cwd())


@gameplan_phase.command("add")
@click.argument("phase_id")
@click.argument("title")
@click.option("--items", "-i", multiple=True, help="Roadmap item id(s) to include")
@click.option("--notes", "-n", default="", help="Phase notes")
@click.option("--status", "-s", default="planned", help="planned | in_progress | done")
@click.option("--edict", "-e", default="", help="Edict this phase implements (e.g. 0007)")
def gameplan_phase_add(phase_id: str, title: str, items: tuple, notes: str, status: str, edict: str):
    """Add a phase referencing roadmap item ids."""
    from .commands import add_gameplan_phase

    add_gameplan_phase(
        Path.cwd(),
        phase_id=phase_id,
        title=title,
        roadmap_items=list(items),
        notes=notes,
        status=status,
        edict=edict,
    )


@gameplan_phase.command("status")
@click.argument("phase_id")
@click.argument("status")
def gameplan_phase_status(phase_id: str, status: str):
    """Set phase status (planned | in_progress | done)."""
    from .commands import set_gameplan_phase_status

    set_gameplan_phase_status(Path.cwd(), phase_id=phase_id, status=status)


@gameplan_phase.command("activate")
@click.argument("phase_id")
@click.option("--goal", "-g", default="", help="Phase goal")
@click.option("--sequencing", "-q", default="", help="Sequencing narrative")
def gameplan_phase_activate(phase_id: str, goal: str, sequencing: str):
    """Promote a phase to activePhase (marks it in_progress, clears task list)."""
    from .commands import activate_gameplan_phase

    activate_gameplan_phase(
        Path.cwd(),
        phase_id=phase_id,
        goal=goal,
        sequencing=sequencing,
    )


@gameplan.group("task")
def gameplan_task():
    """Active-phase task operations."""
    pass


@gameplan_task.command("add")
@click.argument("task_id")
@click.argument("title")
@click.option("--details", "-d", default="", help="Task details")
@click.option("--edict", "-e", default="", help="Edict this task implements (e.g. 0007)")
def gameplan_task_add(task_id: str, title: str, details: str, edict: str):
    """Add a task to the active phase."""
    from .commands import add_gameplan_task

    add_gameplan_task(Path.cwd(), task_id=task_id, title=title, details=details, edict=edict)


@gameplan_task.command("status")
@click.argument("task_id")
@click.argument("status")
@click.option("--resolution", "-r", default="", help="Resolution note (for done)")
def gameplan_task_status(task_id: str, status: str, resolution: str):
    """Set task status (pending | in_progress | done)."""
    from .commands import set_gameplan_task_status

    set_gameplan_task_status(
        Path.cwd(), task_id=task_id, status=status, resolution=resolution
    )


@gameplan_task.command("defer")
@click.argument("task_id")
@click.option("--reason", "-r", default="", help="Reason for deferring")
def gameplan_task_defer(task_id: str, reason: str):
    """Move a task from active tasks into the deferred list."""
    from .commands import defer_gameplan_task

    defer_gameplan_task(Path.cwd(), task_id=task_id, reason=reason)


@gameplan.group("pending", invoke_without_command=True)
@click.pass_context
def gameplan_pending(ctx):
    """Proposed gameplan updates (from the capture hook). Lists them; apply or drop each one."""
    if ctx.invoked_subcommand is None:
        from .commands import list_pending

        list_pending(Path.cwd())


@gameplan_pending.command("apply")
@click.argument("proposal_id")
def gameplan_pending_apply(proposal_id: str):
    """Apply a proposal (P1, P2, ... or 'all') to the gameplan."""
    from .commands import apply_pending

    apply_pending(Path.cwd(), proposal_id)


@gameplan_pending.command("drop")
@click.argument("proposal_id")
def gameplan_pending_drop(proposal_id: str):
    """Discard a proposal (P1, P2, ... or 'all')."""
    from .commands import drop_pending

    drop_pending(Path.cwd(), proposal_id)


if __name__ == "__main__":
    main()
