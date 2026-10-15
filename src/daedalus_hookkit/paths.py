"""Daedalus's config and cache directories, found the way platformdirs finds them, without importing it."""

import os
import sys
from pathlib import Path

APP = "daedalus"


def config_dir() -> Path:
    """platformdirs.user_config_dir("daedalus")."""
    if sys.platform == "win32":
        return _windows_local() / APP / APP
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP
    return Path(os.environ.get("XDG_CONFIG_HOME", "").strip() or Path.home() / ".config") / APP


def cache_dir() -> Path:
    """platformdirs.user_cache_dir("daedalus")."""
    if sys.platform == "win32":
        return _windows_local() / APP / APP / "Cache"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / APP
    return Path(os.environ.get("XDG_CACHE_HOME", "").strip() or Path.home() / ".cache") / APP


def _windows_local() -> Path:
    return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
