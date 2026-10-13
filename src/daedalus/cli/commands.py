"""
CLI command implementations.
"""

import json
import shutil
from pathlib import Path
from typing import Optional

import click

from ..config import get_config_dir
from ..plugin import get_agents_dir, get_skills_dir, list_skills


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
        identity_md.write_text(GLOBAL_IDENTITY_MD, encoding="utf-8")

    identity_json = config_dir / "identity.json"
    if not identity_json.exists():
        identity_json.write_text(GLOBAL_IDENTITY_JSON, encoding="utf-8")


def init_project(project_dir: Path, force: bool = False, hooks: bool = True, edicts: bool = False):
    """Initialize Daedalus in a project."""
    click.echo(f"Initializing Daedalus in {project_dir}")

    # Ensure global identity exists
    _ensure_global_identity()

    # Create .daedalus memory directory
    memory_dir = project_dir / ".daedalus"
    memory_dir.mkdir(exist_ok=True)

    # Create initial memory files. Optional ones (observations, lessons, warnings) appear when a
    # project starts using them, not as empty templates (edict 0007).
    memory_files = {
        "session-summaries.md": "# Session Summaries\n\n",
        "project-map.md": "# Project Map\n\n",
        "decisions.md": "# Decisions\n\n",
    }

    for filename, content in memory_files.items():
        file_path = memory_dir / filename
        if not file_path.exists() or force:
            file_path.write_text(content, encoding="utf-8")
            click.echo(f"  Created {filename}")

    # Create roadmap directory
    roadmap_dir = memory_dir / "roadmap"
    roadmap_dir.mkdir(exist_ok=True)
    index_file = roadmap_dir / "index.json"
    if not index_file.exists() or force:
        index_file.write_text('{"items": [], "version": 1}', encoding="utf-8")
        click.echo("  Created roadmap/index.json")

    from . import gameplan as gp

    if gp.ensure_gameplan(project_dir, force=force):
        click.echo("  Created roadmap/gameplan.json")
    _ensure_gameplan_tracked(project_dir)

    # Copy agents
    agents_dir = project_dir / ".claude" / "agents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    _copy_agents(agents_dir, force)

    # Install skills
    _copy_skills(project_dir / ".claude" / "skills", force)

    if hooks:
        _register_hooks(project_dir)

    if edicts:
        _enable_edicts(project_dir)

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


def hydrate_project(
    project_dir: Path, agents: bool = True, template: bool = True, dry_run: bool = False, skills: bool = True,
    hooks: bool = True,
):
    """Update Daedalus assets in project. With dry_run, report what would change and write nothing."""
    if hooks:
        _register_hooks(project_dir, dry_run=dry_run)

    if skills:
        skills_dir = project_dir / ".claude" / "skills"
        if dry_run:
            changed = _skills_that_would_change(skills_dir)
            click.echo("Skills that would be written: " + (", ".join(changed) if changed else "none"))
        else:
            _copy_skills(skills_dir, force=True)
            click.echo("Updated skills in .claude/skills/")

    if agents:
        agents_dir = project_dir / ".claude" / "agents"
        if dry_run:
            changed = [
                f.name for f in sorted(get_agents_dir().glob("*.md"))
                if not (agents_dir / f.name).exists() or (agents_dir / f.name).read_bytes() != f.read_bytes()
            ]
            click.echo("Agents that would be replaced: " + (", ".join(changed) if changed else "none"))
        else:
            agents_dir.mkdir(parents=True, exist_ok=True)
            _copy_agents(agents_dir, force=True)
            click.echo("Updated agents in .claude/agents/")

    if template:
        from ..templates.injector import build_claude_md, inject_claude_template
        from ..templates.render import TemplateError

        if dry_run:
            try:
                current, updated, warnings = build_claude_md(str(project_dir))
            except TemplateError as e:
                click.echo(f"Warning: could not render CLAUDE.md template: {e}", err=True)
                return
            for w in warnings:
                click.echo(f"Warning: {w}", err=True)
            if current == updated:
                click.echo("CLAUDE.md: no changes")
            else:
                import difflib
                diff = difflib.unified_diff(
                    (current or "").splitlines(keepends=True), updated.splitlines(keepends=True),
                    "CLAUDE.md (current)", "CLAUDE.md (after hydrate)",
                )
                click.echo("".join(diff).replace("\r", ""), nl=False)
            return

        warnings: list = []
        ok = inject_claude_template(str(project_dir), warnings=warnings)
        for w in warnings:
            click.echo(f"Warning: {w}", err=True)
        if ok:
            click.echo("Updated CLAUDE.md template")
        else:
            click.echo("Warning: Could not update CLAUDE.md template", err=True)


GITIGNORE_GAMEPLAN_BLOCK = """
# Daedalus: commit the gameplan, keep the rest of .daedalus/ local (edict 0007)
!.daedalus/
.daedalus/*
!.daedalus/roadmap/
.daedalus/roadmap/*
!.daedalus/roadmap/gameplan.json
"""


def _ensure_gameplan_tracked(project_dir: Path):
    """If git ignores the gameplan, append negations to .gitignore so it can be committed."""
    import subprocess

    from . import gameplan as gp

    rel = str(gp.GameplanPaths.for_project(project_dir).gameplan_file.relative_to(project_dir))

    def ignored() -> bool:
        try:
            return subprocess.run(
                ["git", "check-ignore", "-q", rel], cwd=project_dir, capture_output=True
            ).returncode == 0
        except FileNotFoundError:
            return False

    if not ignored():
        return
    gitignore = project_dir / ".gitignore"
    text = gitignore.read_text(encoding="utf-8") if gitignore.exists() else ""
    if GITIGNORE_GAMEPLAN_BLOCK.strip() not in text:
        sep = "" if not text or text.endswith("\n") else "\n"
        gitignore.write_text(text + sep + GITIGNORE_GAMEPLAN_BLOCK, encoding="utf-8")
    if ignored():
        click.echo(f"  Warning: {rel} is still ignored by git (a rule outside .gitignore?). "
                   f"See `git check-ignore -v {rel}`.", err=True)
    else:
        click.echo(f"  Un-ignored {rel} in .gitignore so the gameplan can be committed")


def _enable_edicts(project_dir: Path):
    """Turn edicts on for this project and scaffold docs/edicts/ (edict 0005)."""
    from ..config import set_project_value
    from ..plugin import PLUGIN_ROOT

    set_project_value(project_dir, "edicts.enabled", "true")
    folder = project_dir / "docs" / "edicts"
    (folder / "dissents").mkdir(parents=True, exist_ok=True)
    keep = folder / "dissents" / ".gitkeep"
    if not keep.exists():
        keep.write_text("", encoding="utf-8")
    readme = folder / "README.md"
    if not readme.exists():
        shutil.copy2(PLUGIN_ROOT / "templates" / "EDICTS_README.md", readme)
        click.echo("  Created docs/edicts/README.md and docs/edicts/dissents/")
    click.echo("  Edicts enabled for this project (edicts.enabled = true)")


def _register_hooks(project_dir: Path, dry_run: bool = False):
    """Register the hooks enabled in config (hooks.session_start, hooks.capture) in .claude/settings.json."""
    from ..config import get_project_settings
    from ..hooks import register_hooks

    settings = get_project_settings(project_dir, "hooks")
    added, removed, error = register_hooks(
        project_dir, session_start=settings["session_start"], capture=settings["capture"], dry_run=dry_run
    )
    if error:
        click.echo(f"  Warning: {error}", err=True)
        return
    if dry_run:
        click.echo("Hooks that would be registered: " + (", ".join(added) if added else "none"))
        if removed:
            click.echo("Hooks that would be removed (disabled in config): " + ", ".join(removed))
        return
    if added:
        click.echo(f"  Registered hooks in .claude/settings.json: {', '.join(added)}")
    if removed:
        click.echo(f"  Removed disabled hooks from .claude/settings.json: {', '.join(removed)}")


def _skill_files(name: str):
    """(relative path, source file) for every file in a bundled skill's folder."""
    src = get_skills_dir() / name
    return [(f.relative_to(src), f) for f in sorted(src.rglob("*")) if f.is_file() and "__pycache__" not in f.parts]


def _skills_that_would_change(dest_dir: Path) -> list:
    """Bundled skills whose installed copy is missing or differs."""
    changed = []
    for name in list_skills():
        files = _skill_files(name)
        if any(not (dest_dir / name / rel).exists() or (dest_dir / name / rel).read_bytes() != f.read_bytes()
               for rel, f in files):
            changed.append(name)
    return changed


def _copy_skills(dest_dir: Path, force: bool = False):
    """Install each skill listed in plugin.yaml into dest_dir/<name>/ (the project's .claude/skills)."""
    for name in list_skills():
        target = dest_dir / name
        if target.exists() and not force:
            click.echo(f"  Skipping skill {name} (exists)")
            continue
        for rel, f in _skill_files(name):
            (target / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, target / rel)
        click.echo(f"  Installed skill {name}")


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
    # Palace.regions/buildings/rooms/entities are flat dicts keyed by slug (not nested
    # Region -> Building -> Room containers), so count them directly.
    click.echo(f"Regions: {len(palace.regions)}")
    click.echo(f"Buildings: {len(palace.buildings)}")
    click.echo(f"Rooms: {len(palace.rooms)}")
    click.echo(f"Entities: {len(palace.entities)}")


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

    data = json.loads(roadmap_file.read_text(encoding="utf-8"))
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

    data = json.loads(roadmap_file.read_text(encoding="utf-8"))

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
    roadmap_file.write_text(json.dumps(data, indent=2), encoding="utf-8")

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


def _edict_tag(entry: dict) -> str:
    return f" [edict {entry['edict']}]" if entry.get("edict") else ""


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
        click.echo(f"  {icon} {phase.get('id')}: {phase.get('title')} ({item_count} items){_edict_tag(phase)}")

    active = data.get("activePhase")
    if not active:
        click.echo("\nNo active phase.")
        return

    click.echo(f"\nActive: {active.get('id')} — {active.get('title')}{_edict_tag(active)}")
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
        click.echo(f"  {icon} {task.get('id')}: {task.get('title')}{_edict_tag(task)}")

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
        click.echo(f"{icon} {phase.get('id')}: {phase.get('title')}{_edict_tag(phase)}{marker}")


def add_gameplan_phase(
    project_dir: Path,
    phase_id: str,
    title: str,
    roadmap_items: list,
    notes: str,
    status: str,
    edict: str = "",
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
            edict=edict,
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


def add_gameplan_task(project_dir: Path, task_id: str, title: str, details: str, edict: str = ""):
    from . import gameplan as gp

    if _gameplan_run(
        project_dir, lambda d: gp.add_task(d, task_id, title, details=details, edict=edict)
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


def list_pending(project_dir: Path):
    from . import gameplan as gp

    proposals = gp.load_pending(project_dir)
    if not proposals:
        click.echo("No pending gameplan updates.")
        return
    for p in proposals:
        click.echo(f"{p['id']}: {gp.describe_proposal(p)}  ({p.get('source', '')}, {p.get('created', '')})")
        if p.get("resolution"):
            click.echo(f"    {p['resolution']}")


def apply_pending(project_dir: Path, which: str):
    from . import gameplan as gp

    applied = _gameplan_run(project_dir, lambda d: gp.apply_pending(project_dir, d, which))
    for p in applied or []:
        click.echo(f"Applied {p['id']}: {gp.describe_proposal(p)}")


def drop_pending(project_dir: Path, which: str):
    from . import gameplan as gp

    try:
        dropped = gp.drop_pending(project_dir, which)
    except gp.GameplanError as e:
        click.echo(str(e), err=True)
        return
    for p in dropped:
        click.echo(f"Dropped {p['id']}: {gp.describe_proposal(p)}")


def import_reconstruction(project_dir: Path, proposal_file: Path):
    """Load a checked reconstruction proposal into the pending file (edict 0006)."""
    from . import gameplan as gp
    from ..reconstruct import check_proposal

    try:
        data = json.loads(Path(proposal_file).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        click.echo(f"Could not read {proposal_file}: {e}", err=True)
        raise SystemExit(1)
    result = check_proposal(project_dir, data)
    if result.errors:
        for e in result.errors:
            click.echo(f"error: {e}", err=True)
        click.echo("Not imported: fix the proposal so `daedalus reconstruct check` passes.", err=True)
        raise SystemExit(1)
    proposals, skipped = gp.proposals_from_reconstruction(data)
    added = gp.add_proposals(project_dir, proposals)
    for p in added:
        click.echo(f"Pending {p['id']}: {gp.describe_proposal(p)}")
    for s in skipped:
        click.echo(f"Not imported, {s}")
    if result.uncited:
        click.echo(f"Note: {len(result.uncited)} commits in the window are cited by no entry.")
    click.echo("Review with `daedalus gameplan pending`; apply or drop each one.")


# ---------- edicts ----------


def _edict_title(path: Path) -> str:
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("# "):
            return line[2:].split(":", 1)[-1].strip()
    return path.stem


def _gameplan_refs(project_dir: Path) -> dict:
    """{edict number: [(where, status)]} from the gameplan's phases and tasks."""
    from . import gameplan as gp

    try:
        data = gp.load_gameplan(project_dir)
    except (gp.GameplanError, json.JSONDecodeError):
        return {}
    refs: dict = {}

    def add(entry, where):
        if entry.get("edict"):
            refs.setdefault(str(entry["edict"]).zfill(4), []).append((where, entry.get("status", "?")))

    for phase in data.get("phases", []):
        add(phase, f"phase {phase.get('id')}")
    active = data.get("activePhase") or {}
    for task in active.get("tasks", []):
        add(task, f"task {task.get('id')}")
    return refs


def list_edicts(project_dir: Path):
    from ..doctor import edicts_dir, load_edicts

    edicts = load_edicts(project_dir)
    if not edicts:
        click.echo("No edicts in docs/edicts/.")
        return
    refs = _gameplan_refs(project_dir)
    for e in edicts:
        title = _edict_title(edicts_dir(project_dir) / e["file"])
        tracked = refs.get(e["number"], [])
        where = "; ".join(f"{w} [{s}]" for w, s in tracked) if tracked else "not in the gameplan"
        click.echo(f"{e['number']}  {(e['status'] or '?'):<9} {title}  ({where})")


def show_edict(project_dir: Path, number: str):
    from ..doctor import edicts_dir, load_edicts

    number = number.zfill(4)
    matches = [e for e in load_edicts(project_dir) if e["number"] == number]
    if not matches:
        click.echo(f"No edict {number} in docs/edicts/.", err=True)
        raise SystemExit(1)
    for i, e in enumerate(matches):
        if i:
            click.echo("\n" + "-" * 72 + "\n")
        click.echo((edicts_dir(project_dir) / e["file"]).read_text(encoding="utf-8"))
    refs = _gameplan_refs(project_dir).get(number, [])
    click.echo("Gameplan: " + ("; ".join(f"{w} [{s}]" for w, s in refs) if refs else "not referenced"))
