"""
TUI plugins (edict 0012): what a package outside Daedalus may add to the TUI, through the entry-point
group `daedalus.tui`.

A plugin registers like this, in its own pyproject.toml:

    [project.entry-points."daedalus.tui"]
    jira = "daedalus_jira.tui:JiraTui"

The entry point names a `TuiPlugin` subclass (instantiated with no arguments) or an instance. It may add
three things, and nothing else; the shell layout is not pluggable, because a fixed home screen is part of
what keeps it legible:

1. **A NeedsYou kind.** `tag` is the kind's short text tag (two or three capitals, e.g. `JR`), shown in
   place of colour. `needs_you(project_dir)` returns `NeedItem`s with `kind == tag`; `detail(item)`
   returns the text the expanded NeedsYou view shows for one; `actions` names what that view offers.
   Only `"send"` (hand it to Claude) is wired for a plugin kind: edict 0012 fixes the TUI's writes, and
   a plugin can't add to them.
2. **Explain cards.** `explain_cards()` returns `cards.Card`s. Each needs all three parts: what it is,
   where it lives, the CLI that shows it. A card with the same title as a built-in one replaces it.
3. **Menu screens.** `screens()` returns `(label, ScreenClass)` pairs. They're listed in the plugin
   menu (`m` on the shell) and constructed as `ScreenClass(app)`, like the core's screens. A screen
   follows the same rules: `esc` back, `?` an Explain card, and only the writes the edict allows.

Nothing here imports Textual, so a plugin can import this module cheaply. A plugin that raises is
skipped: one broken plugin never takes the TUI down.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Optional

from .state import NeedItem, plugins


class TuiPlugin:
    """Base class for a `daedalus.tui` plugin. Override only the hooks you use; each default adds nothing."""

    #: Shown in the plugin menu and in error messages.
    name: str = ""
    #: The NeedsYou kind's text tag (e.g. "JR"). Empty when the plugin adds no kind.
    tag: str = ""
    #: What the expanded NeedsYou view offers for this kind. Only "send" is wired for plugins.
    actions: tuple = ("send",)

    # ----- 1. a NeedsYou kind -----

    def needs_you(self, project_dir: Path) -> Iterable[NeedItem]:
        """What's waiting on the owner, as NeedItems whose `kind` is `self.tag`."""
        return []

    def detail(self, item: NeedItem) -> str:
        """The detail text for one of this plugin's items (plain text or Rich markup)."""
        return item.title

    # ----- 2. Explain cards -----

    def explain_cards(self) -> list:
        """Explain cards (`daedalus.tui.cards.Card`) for the concepts this plugin shows."""
        return []

    # ----- 3. menu screens -----

    def screens(self) -> list[tuple[str, Any]]:
        """`(label, ScreenClass)` pairs for the plugin menu."""
        return []


def plugin_for(kind: str) -> Optional[Any]:
    """The plugin that owns a NeedsYou kind, or None for the core's kinds."""
    for plugin in plugins():
        if getattr(plugin, "tag", "") == kind:
            return plugin
    return None


def detail_for(item: NeedItem) -> Optional[str]:
    """A plugin item's detail text (None when no plugin owns the kind, or it failed)."""
    plugin = plugin_for(item.kind)
    if plugin is None:
        return None
    try:
        return str(plugin.detail(item))
    except Exception:
        return None


def menu_entries() -> list[tuple[str, str, Any]]:
    """Every plugin screen: (plugin name, label, ScreenClass). A plugin whose screens() fails is skipped."""
    out = []
    for plugin in plugins():
        try:
            pairs = list(getattr(plugin, "screens", lambda: [])() or [])
        except Exception:
            continue
        name = getattr(plugin, "name", "") or type(plugin).__name__
        out += [(name, label, cls) for label, cls in pairs]
    return out
