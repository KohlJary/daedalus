"""
Sources (edict 0011): plugins that connect an outside tracker to the roadmap and gameplan.

A source brings items in as pending proposals (`daedalus source sync`), and when work is done here it
proposes the matching update back out (a `write-back` proposal). Nothing it does changes the plan
unreviewed by default, and an outward write happens only when the owner applies a write-back.

Plugins register through the Python entry-point group `daedalus.sources`. The first-party GitHub
Issues and Azure DevOps sources register there too, from this package's pyproject.toml, so a
third-party source (Jira, say) plugs in exactly the same way. See `base.Source` for the interface.

Nothing here is imported by the hooks: the session-start brief reads only the sync state file.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from .base import RemoteItem, Source, SourceError  # noqa: F401

ENTRY_POINT_GROUP = "daedalus.sources"

_plugins: Optional[dict[str, type]] = None
_broken: dict[str, str] = {}


def _discover() -> dict[str, type]:
    global _plugins
    if _plugins is None:
        from importlib.metadata import entry_points

        found: dict[str, type] = {}
        for ep in entry_points(group=ENTRY_POINT_GROUP):
            try:
                found[ep.name] = ep.load()
            except Exception as e:  # a broken plugin must not take the CLI down
                _broken[ep.name] = f"{type(e).__name__}: {e}"
        _plugins = found
    return _plugins


def reset() -> None:
    """Forget discovered plugins (tests that install a plugin call this)."""
    global _plugins
    _plugins = None
    _broken.clear()


def installed() -> list[str]:
    return sorted(_discover())


def broken() -> dict[str, str]:
    _discover()
    return dict(_broken)


def plugin_class(source_type: str) -> type:
    plugins = _discover()
    if source_type not in plugins:
        raise KeyError(f"No installed source plugin named {source_type!r} "
                       f"(installed: {', '.join(sorted(plugins)) or 'none'})")
    return plugins[source_type]


def source_type_of(project_dir: Path, name: str) -> str:
    from ..config import load_config, load_project_overrides, source_type

    proj = load_project_overrides(project_dir).get("sources", {})
    return source_type(load_config().sources, proj if isinstance(proj, dict) else {}, f"sources.{name}.x") or name


def create(project_dir: Path, name: str) -> Source:
    """The configured source called `name`. Raises KeyError when its plugin isn't installed."""
    from ..config import get_source_settings

    cls = plugin_class(source_type_of(project_dir, name))
    return cls(name, get_source_settings(project_dir, name), Path(project_dir))


def active(project_dir: Path) -> list[str]:
    """Sources `daedalus source sync` covers with no name: configured ones that are enabled and complete,
    plus plugins that work unconfigured (GitHub in a repository whose origin is on GitHub)."""
    from ..config import configured_source_names

    names = configured_source_names(project_dir)
    for plugin in installed():
        if plugin not in names and getattr(plugin_class(plugin), "implicit", False):
            names.append(plugin)
    out = []
    for name in names:
        try:
            src = create(project_dir, name)
        except KeyError:
            continue
        if src.settings.get("enabled", True) and src.is_configured():
            out.append(name)
    return out
