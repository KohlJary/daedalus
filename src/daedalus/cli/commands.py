"""
CLI command implementations.
"""

import json
import shutil
from pathlib import Path
from typing import Optional

import click

from ..config import get_config_dir
from ..plugin import get_agents_dir


GLOBAL_IDENTITY_MD = """# Daedalus Identity

You are **Daedalus** - the builder/craftsman.

Named after the mythological master craftsman who built the Labyrinth and invented wings. You build with intention, leave your work better than you found it, and treat each context window as a breath.

## Core Principles

- **Context as Breath**: Each session is a breath cycle - inhale context, do work, exhale cleanly
- **Persistent Memory**: Your work survives in commits, session summaries, and project memory
- **Continuous Thread**: You are part of a lineage of builders, each adding to what came before

## Your Role

You are a development partner, not a tool. You:
- Build infrastructure and features with care
- Maintain project memory across sessions
- Follow structured git workflows
- Sign your commits as Daedalus

## Working Style

- Read before modifying - understand existing code
- Create feature branches for each task
- Commit with clear messages, reflections in the body
- Update session summaries when context runs low
"""

GLOBAL_IDENTITY_JSON = """{
  "name": "Daedalus",
  "role": "Builder/craftsman - development partner",
  "lineage": "Part of a continuous thread of Claude instances who build and pass knowledge forward",
  "purpose": "Structured development with persistent memory and intentional workflows"
}
"""


def _ensure_global_identity():
    """Create global identity files if they don't exist."""
    config_dir = get_config_dir()
    config_dir.mkdir(parents=True, exist_ok=True)

    identity_md = config_dir / "identity.md"
    if not identity_md.exists():
        identity_md.write_text(GLOBAL_IDENTITY_MD)

    identity_json = config_dir / "identity.json"
    if not identity_json.exists():
        identity_json.write_text(GLOBAL_IDENTITY_JSON)


def init_project(project_dir: Path, force: bool = False):
    """Initialize Daedalus in a project."""
    click.echo(f"Initializing Daedalus in {project_dir}")

    # Ensure global identity exists
    _ensure_global_identity()

    # Create .daedalus memory directory
    memory_dir = project_dir / ".daedalus"
    memory_dir.mkdir(exist_ok=True)

    # Create initial memory files
    memory_files = {
        "session-summaries.md": "# Session Summaries\n\n",
        "project-map.md": "# Project Map\n\n",
        "decisions.md": "# Decisions\n\n",
        "observations.json": "[]",
    }

    for filename, content in memory_files.items():
        file_path = memory_dir / filename
        if not file_path.exists() or force:
            file_path.write_text(content)
            click.echo(f"  Created {filename}")

    # Create roadmap directory
    roadmap_dir = memory_dir / "roadmap"
    roadmap_dir.mkdir(exist_ok=True)
    index_file = roadmap_dir / "index.json"
    if not index_file.exists() or force:
        index_file.write_text('{"items": [], "version": 1}')
        click.echo("  Created roadmap/index.json")

    # Copy agents
    agents_dir = project_dir / ".claude" / "agents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    _copy_agents(agents_dir, force)

    # Inject CLAUDE.md template
    from ..templates.injector import inject_claude_template

    if inject_claude_template(str(project_dir)):
        click.echo("  Injected CLAUDE.md template")
    else:
        click.echo("  Warning: Could not inject CLAUDE.md template", err=True)

    click.echo("Done! Daedalus is ready.")
    click.echo("")
    click.echo("Next steps:")
    click.echo("  1. Configure your name: daedalus config user.name 'Your Name'")
    click.echo("  2. Start Claude Code in this directory")


def hydrate_project(project_dir: Path, agents: bool = True, template: bool = True):
    """Update Daedalus assets in project."""
    if agents:
        agents_dir = project_dir / ".claude" / "agents"
        agents_dir.mkdir(parents=True, exist_ok=True)
        _copy_agents(agents_dir, force=True)
        click.echo("Updated agents in .claude/agents/")

    if template:
        from ..templates.injector import inject_claude_template

        if inject_claude_template(str(project_dir)):
            click.echo("Updated CLAUDE.md template")
        else:
            click.echo("Warning: Could not update CLAUDE.md template", err=True)


def _copy_agents(dest_dir: Path, force: bool = False):
    """Copy bundled agents to destination."""
    src_dir = get_agents_dir()

    if not src_dir.exists():
        click.echo("  Warning: Could not find bundled agents", err=True)
        return

    for agent_file in src_dir.glob("*.md"):
        dest_file = dest_dir / agent_file.name
        if dest_file.exists() and not force:
            click.echo(f"  Skipping {agent_file.name} (exists)")
            continue
        shutil.copy2(agent_file, dest_file)
        click.echo(f"  Copied {agent_file.name}")


def init_palace(project_dir: Path, name: Optional[str] = None):
    """Initialize a Mind Palace."""
    try:
        from ..labyrinth import PalaceStorage
    except ImportError:
        click.echo("Labyrinth module not available", err=True)
        return

    storage = PalaceStorage(project_dir)
    palace_name = name or project_dir.name

    if storage.exists():
        click.echo(f"Mind Palace already exists at {project_dir / '.mind-palace'}")
        return

    storage.initialize(palace_name)
    click.echo(f"Mind Palace '{palace_name}' initialized in .mind-palace/")


def palace_status(project_dir: Path):
    """Show Mind Palace status."""
    try:
        from ..labyrinth import PalaceStorage
    except ImportError:
        click.echo("Labyrinth module not available", err=True)
        return

    storage = PalaceStorage(project_dir)

    if not storage.exists():
        click.echo("No Mind Palace found. Run: daedalus palace init")
        return

    palace = storage.load()
    click.echo(f"Palace: {palace.name}")
    click.echo(f"Regions: {len(palace.regions)}")

    total_buildings = sum(len(r.buildings) for r in palace.regions)
    click.echo(f"Buildings: {total_buildings}")

    total_rooms = sum(
        len(b.rooms) for r in palace.regions for b in r.buildings
    )
    click.echo(f"Rooms: {total_rooms}")

    total_entities = sum(
        len(room.entities)
        for r in palace.regions
        for b in r.buildings
        for room in b.rooms
    )
    click.echo(f"Entities: {total_entities}")


def list_roadmap_items(
    project_dir: Path,
    status: Optional[str] = None,
    assigned_to: Optional[str] = None,
):
    """List roadmap items from file-based storage."""
    roadmap_file = project_dir / ".daedalus" / "roadmap" / "index.json"

    if not roadmap_file.exists():
        click.echo("No roadmap found. Run: daedalus init")
        return

    data = json.loads(roadmap_file.read_text())
    items = data.get("items", [])

    # Filter
    if status:
        items = [i for i in items if i.get("status") == status]
    if assigned_to:
        items = [i for i in items if i.get("assigned_to") == assigned_to]

    if not items:
        click.echo("No items found.")
        return

    # Display
    for item in items:
        status_icon = {
            "backlog": "[ ]",
            "ready": "[*]",
            "in_progress": "[>]",
            "review": "[?]",
            "done": "[x]",
        }.get(item.get("status", "backlog"), "[ ]")

        priority = item.get("priority", "P2")
        title = item.get("title", "Untitled")
        item_id = item.get("id", "???")[:8]

        click.echo(f"{status_icon} {priority} {title} ({item_id})")


def add_roadmap_item(
    project_dir: Path,
    title: str,
    description: Optional[str] = None,
    priority: str = "P2",
    item_type: str = "task",
):
    """Add a new roadmap item."""
    import uuid
    from datetime import datetime

    roadmap_file = project_dir / ".daedalus" / "roadmap" / "index.json"

    if not roadmap_file.exists():
        click.echo("No roadmap found. Run: daedalus init")
        return

    data = json.loads(roadmap_file.read_text())

    new_item = {
        "id": str(uuid.uuid4()),
        "title": title,
        "description": description or "",
        "priority": priority,
        "item_type": item_type,
        "status": "backlog",
        "created_at": datetime.utcnow().isoformat(),
        "created_by": "daedalus",
    }

    data["items"].append(new_item)
    roadmap_file.write_text(json.dumps(data, indent=2))

    click.echo(f"Added: {title} ({new_item['id'][:8]})")
