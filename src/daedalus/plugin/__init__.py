"""
Daedalus plugin assets.

Contains Claude Code plugin resources that are shipped with the package:
- agents/ - Specialized subagent definitions
- commands/ - Slash command definitions
- templates/ - CLAUDE.md template for injection
- hooks/ - Session lifecycle hooks
- skills/ - Reusable skill definitions
"""

from pathlib import Path

PLUGIN_ROOT = Path(__file__).parent


def get_agents_dir() -> Path:
    """Get path to bundled agents directory."""
    return PLUGIN_ROOT / "agents"


def get_commands_dir() -> Path:
    """Get path to bundled commands directory."""
    return PLUGIN_ROOT / "commands"


def get_templates_dir() -> Path:
    """Get path to bundled templates directory."""
    return PLUGIN_ROOT / "templates"


def get_hooks_dir() -> Path:
    """Get path to bundled hooks directory."""
    return PLUGIN_ROOT / "hooks"


def get_skills_dir() -> Path:
    """Get path to bundled skills directory."""
    return PLUGIN_ROOT / "skills"
