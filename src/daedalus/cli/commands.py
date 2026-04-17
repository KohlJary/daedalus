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

    from . import gameplan as gp

    if gp.ensure_gameplan(project_dir, force=force):
        click.echo("  Created roadmap/gameplan.json")

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


# ---------- gameplan commands ----------


def _gameplan_run(project_dir: Path, fn, *args, **kwargs):
    """Load, mutate, save — with uniform error handling."""
    from . import gameplan as gp

    try:
        data = gp.load_gameplan(project_dir)
    except gp.GameplanError as e:
        click.echo(str(e), err=True)
        return None
    try:
        result = fn(data, *args, **kwargs)
    except gp.GameplanError as e:
        click.echo(str(e), err=True)
        return None
    gp.save_gameplan(project_dir, data)
    return result


def _phase_status_icon(status: str) -> str:
    return {"planned": "[ ]", "in_progress": "[>]", "done": "[x]"}.get(status, "[?]")


def _task_status_icon(status: str) -> str:
    return {"pending": "[ ]", "in_progress": "[>]", "done": "[x]"}.get(status, "[?]")


def show_gameplan(project_dir: Path, as_json: bool = False):
    """Display the full gameplan."""
    from . import gameplan as gp

    try:
        data = gp.load_gameplan(project_dir)
    except gp.GameplanError as e:
        click.echo(str(e), err=True)
        return

    if as_json:
        click.echo(json.dumps(data, indent=2))
        return

    phases = data.get("phases", [])
    click.echo(f"Phases ({len(phases)}):")
    for phase in phases:
        icon = _phase_status_icon(phase.get("status", "planned"))
        item_count = len(phase.get("roadmapItems", []))
        click.echo(f"  {icon} {phase.get('id')}: {phase.get('title')} ({item_count} items)")

    active = data.get("activePhase")
    if not active:
        click.echo("\nNo active phase.")
        return

    click.echo(f"\nActive: {active.get('id')} — {active.get('title')}")
    if active.get("started"):
        click.echo(f"Started: {active['started']}")
    if active.get("goal"):
        click.echo(f"Goal: {active['goal']}")
    if active.get("sequencing"):
        click.echo(f"Sequencing: {active['sequencing']}")

    tasks = active.get("tasks", [])
    click.echo(f"\nTasks ({len(tasks)}):")
    for task in tasks:
        icon = _task_status_icon(task.get("status", "pending"))
        click.echo(f"  {icon} {task.get('id')}: {task.get('title')}")

    deferred = active.get("deferred", [])
    if deferred:
        click.echo(f"\nDeferred ({len(deferred)}):")
        for entry in deferred:
            click.echo(f"  - {entry.get('id')}: {entry.get('title')}")


def list_gameplan_phases(project_dir: Path):
    from . import gameplan as gp

    try:
        data = gp.load_gameplan(project_dir)
    except gp.GameplanError as e:
        click.echo(str(e), err=True)
        return

    phases = data.get("phases", [])
    if not phases:
        click.echo("No phases.")
        return

    active_id = (data.get("activePhase") or {}).get("id")
    for phase in phases:
        icon = _phase_status_icon(phase.get("status", "planned"))
        marker = " *" if phase.get("id") == active_id else ""
        click.echo(f"{icon} {phase.get('id')}: {phase.get('title')}{marker}")


def add_gameplan_phase(
    project_dir: Path,
    phase_id: str,
    title: str,
    roadmap_items: list,
    notes: str,
    status: str,
):
    from . import gameplan as gp

    def _add(data):
        return gp.add_phase(
            data,
            phase_id=phase_id,
            title=title,
            roadmap_items=roadmap_items,
            notes=notes,
            status=status,
        )

    if _gameplan_run(project_dir, _add):
        click.echo(f"Added phase: {phase_id}")


def set_gameplan_phase_status(project_dir: Path, phase_id: str, status: str):
    from . import gameplan as gp

    if _gameplan_run(project_dir, lambda d: gp.set_phase_status(d, phase_id, status)):
        click.echo(f"Phase '{phase_id}' -> {status}")


def activate_gameplan_phase(
    project_dir: Path, phase_id: str, goal: str, sequencing: str
):
    from . import gameplan as gp

    if _gameplan_run(
        project_dir,
        lambda d: gp.activate_phase(d, phase_id, goal=goal, sequencing=sequencing),
    ):
        click.echo(f"Active phase: {phase_id}")


def add_gameplan_task(project_dir: Path, task_id: str, title: str, details: str):
    from . import gameplan as gp

    if _gameplan_run(
        project_dir, lambda d: gp.add_task(d, task_id, title, details=details)
    ):
        click.echo(f"Added task: {task_id}")


def set_gameplan_task_status(
    project_dir: Path, task_id: str, status: str, resolution: str
):
    from . import gameplan as gp

    if _gameplan_run(
        project_dir,
        lambda d: gp.set_task_status(d, task_id, status, resolution=resolution),
    ):
        click.echo(f"Task '{task_id}' -> {status}")


def defer_gameplan_task(project_dir: Path, task_id: str, reason: str):
    from . import gameplan as gp

    if _gameplan_run(project_dir, lambda d: gp.defer_task(d, task_id, reason=reason)):
        click.echo(f"Deferred task: {task_id}")
