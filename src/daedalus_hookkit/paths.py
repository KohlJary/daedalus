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
    return _xdg("XDG_CONFIG_HOME", ".config") / APP


def cache_dir() -> Path:
    """platformdirs.user_cache_dir("daedalus")."""
    if sys.platform == "win32":
        return _windows_local() / APP / APP / "Cache"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / APP
    return _xdg("XDG_CACHE_HOME", ".cache") / APP


def _xdg(var: str, default: str) -> Path:
    """An XDG directory: the variable as given when it is set (platformdirs uses it literally), else the default."""
    value = os.environ.get(var, "")
    return Path(value) if value.strip() else Path.home() / default


def _windows_local() -> Path:
    return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
