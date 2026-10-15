"""
The few settings the kit reads, from the same files `daedalus.config` uses, as raw JSON.

Defaults here must match the schema registry; tests/test_hookkit.py checks that they do. A project's
`.daedalus/config.json` overrides the global config for the groups it may override.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import paths

DEFAULTS: dict[str, dict[str, object]] = {
    "hooks": {
        "session_start": True,
        "capture": False,
        "board": True,
        "budget_per_hour": 6,
        "efficacy_window": 20,
    },
}
PROJECT_GROUPS = {"hooks"}


def _read(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


class Settings:
    def __init__(self, project_dir: Path):
        self._global = _read(paths.config_dir() / "config.json")
        self._project = _read(Path(project_dir) / ".daedalus" / "config.json")

    def get(self, group: str, key: str) -> object:
        default = DEFAULTS.get(group, {}).get(key)
        value = default
        g = self._global.get(group)
        if isinstance(g, dict) and key in g:
            value = g[key]
        p = self._project.get(group)
        if group in PROJECT_GROUPS and isinstance(p, dict) and key in p:
            value = p[key]
        if default is not None and not isinstance(value, type(default)):
            return default  # a mistyped value never breaks a hook
        return value

    def enabled(self, key: str) -> bool:
        return bool(self.get("hooks", key))
