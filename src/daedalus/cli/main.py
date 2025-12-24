"""
Daedalus CLI entry point.

Commands:
  init      Initialize Daedalus in current project
  hydrate   Inject/update templates and agents
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
@click.version_option(package_name="daedalus")
def main():
    """Daedalus - Claude Code plugin for structured development."""
    pass


@main.command()
@click.option("--force", is_flag=True, help="Overwrite existing files")
def init(force: bool):
    """Initialize Daedalus in the current project.

    Creates:
      - .daedalus/        (project memory directory)
      - .claude/agents/   (copies bundled agents)
      - CLAUDE.md         (injects Daedalus section)
    """
    from .commands import init_project

    init_project(Path.cwd(), force=force)


@main.command()
@click.option("--agents/--no-agents", default=True, help="Copy agents to .claude/agents/")
@click.option("--template/--no-template", default=True, help="Inject CLAUDE.md template")
def hydrate(agents: bool, template: bool):
    """Update Daedalus assets in current project.

    Re-injects the CLAUDE.md template and optionally updates agents.
    """
    from .commands import hydrate_project

    hydrate_project(Path.cwd(), agents=agents, template=template)


@main.command("config")
@click.argument("key", required=False)
@click.argument("value", required=False)
def config_cmd(key: str, value: str):
    """View or set global configuration.

    Examples:
      daedalus config                    # Show all config
      daedalus config user.name          # Show specific key
      daedalus config user.name "Kohl"   # Set value
    """
    import json

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


if __name__ == "__main__":
    main()
