"""
Daedalus TUI - Textual-based workspace for Claude Code development.

Provides a 3-column layout:
- Left: Daedalus terminal (Claude Code)
- Center: Icarus swarm visualization
- Right: Lazygit
"""

from .app import DaedalusApp

__all__ = ["DaedalusApp"]
