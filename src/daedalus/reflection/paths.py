"""Where things live: Claude Code's directory, a project's reflection directory, the models."""

from __future__ import annotations

import ntpath
import os
import posixpath
from pathlib import Path
from typing import Optional

from ..config import get_config_dir

REFLECTION_DIR = Path(".daedalus") / "reflection"


def claude_dir() -> Path:
    """Claude Code's directory: CLAUDE_CONFIG_DIR when set, otherwise ~/.claude (on every OS)."""
    override = os.environ.get("CLAUDE_CONFIG_DIR")
    return Path(override).expanduser() if override else Path.home() / ".claude"


def projects_dir() -> Path:
    return claude_dir() / "projects"


def claude_settings_file() -> Path:
    return claude_dir() / "settings.json"


def reflection_dir(project_dir: Path) -> Path:
    return Path(project_dir) / REFLECTION_DIR


def sessions_dir(project_dir: Path) -> Path:
    return reflection_dir(project_dir) / "sessions"


def reports_dir(project_dir: Path) -> Path:
    return reflection_dir(project_dir) / "reports"


def models_dir() -> Path:
    """The user and self models are per machine, in the global config directory, not in any repo."""
    return get_config_dir() / "models"


def norm_path(path: str, windows: Optional[bool] = None) -> str:
    """
    Normalise a path for comparison. On Windows (or with windows=True, for tests on other systems)
    separators become backslashes and case is folded, so `C:\\Repo` and `c:/repo` match.
    """
    if windows is None:
        windows = os.name == "nt"
    if windows:
        return ntpath.normcase(ntpath.normpath(path))
    return posixpath.normpath(path)


def owner_project(cwd: str, windows: Optional[bool] = None) -> Optional[str]:
    """
    The project a session belongs to: the deepest directory at or above `cwd` that has a
    `.daedalus/` directory, normalised. None when there is none (or cwd no longer exists).
    Nested projects (a repo inside another) each own their own sessions.
    """
    if not cwd:
        return None
    current = Path(cwd)
    while True:
        if (current / ".daedalus").is_dir():
            try:
                current = current.resolve()  # same form as the project path it is compared with
            except OSError:
                pass
            return norm_path(str(current), windows)
        if current.parent == current:
            return None
        current = current.parent
