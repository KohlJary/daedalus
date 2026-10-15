"""
TUI plugins (edict 0012): what a package outside Daedalus may add to the TUI, through the entry-point
group `daedalus.tui`. This module is the one protocol; the NeedsYou screen, the plugin menu and the
Explain cards all call exactly these hooks.

A plugin registers like this, in its own pyproject.toml:

    [project.entry-points."daedalus.tui"]
    jira = "daedalus_jira.tui:JiraTui"

The entry point names a `TuiPlugin` subclass (instantiated with no arguments) or an instance. It may add
three things, and nothing else; the shell layout is not pluggable, because a fixed home screen is part of
what keeps it legible:

1. **A NeedsYou kind.**
   - `tag`: the kind's short text tag (two or three capitals, e.g. `JR`), shown in place of colour.
   - `needs_you(project_dir) -> [NeedItem]`: items whose `kind == tag`.
   - `detail(item, project_dir) -> str`: the body of the expanded NeedsYou view for one item. It is
     shown as plain text, never parsed as Rich markup.
   - `actions(item) -> [(key, label)]`: the keys the expanded view offers for that item. Each one is
     shown in the view's key row, as `key label`.
   - `run_action(project_dir, item, key) -> str | None`: runs one of those actions; the returned text is
     shown as a notification.

   **Plugin writes.** Edict 0012 fixes the TUI's own writes, and also lets a plugin add a NeedsYou kind
   with its actions. Both hold this way: a plugin action is allowed, but it never runs unannounced.
   Every plugin action runs behind the shared confirm modal (`daedalus.tui.widgets.confirm.ConfirmModal`),
   whose question names the plugin and the action ("Fake Jira: run 'transition' on J-7?"). Only `y`
   runs it; `n` or `esc` cancels and `run_action` is not called. A key the plugin didn't declare for
   that item does nothing and says "no such action for this kind"; it is never passed to the plugin.
   The core's navigation keys can't be claimed: `s` (send to Claude), `?`, `esc`, `enter`, `tab`,
   `j`/`k` and the arrows keep their meaning, and a plugin action declaring one is ignored.
2. **Explain cards.** `explain_cards() -> [Card]` returns `cards.Card`s. Each needs all three parts: what
   it is, where it lives, the CLI that shows it. A card with the same title as a built-in one replaces it.
3. **Menu screens.** `screens() -> [(label, ScreenClass)]`. They're listed in the plugin menu (`m` on
   the shell) and constructed as `ScreenClass(app)`, like the core's screens. A screen follows the same
   rules: `esc` back, `?` an Explain card, and only the writes the edict allows.

Nothing here imports Textual, so a plugin can import this module cheaply. A plugin that raises is
skipped: one broken plugin never takes the TUI down.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Optional

from .state import NeedItem, plugins

#: Keys the NeedsYou screen keeps for itself; a plugin action declaring one of them is ignored.
RESERVED_KEYS = frozenset({"s", "question_mark", "?", "escape", "enter", "tab", "shift+tab", "j", "k",
                           "up", "down", "left", "right"})


class TuiPlugin:
    """Base class for a `daedalus.tui` plugin. Override only the hooks you use; each default adds nothing."""

    #: Shown in the plugin menu, in confirm questions and in error messages.
    name: str = ""
    #: The NeedsYou kind's text tag (e.g. "JR"). Empty when the plugin adds no kind.
    tag: str = ""

    # ----- 1. a NeedsYou kind -----

    def needs_you(self, project_dir: Path) -> Iterable[NeedItem]:
        """What's waiting on the owner, as NeedItems whose `kind` is `self.tag`."""
        return []

    def detail(self, item: NeedItem, project_dir: Path) -> str:
        """The expanded view's body for one of this plugin's items (plain text; never parsed as markup)."""
        return item.title

    def actions(self, item: NeedItem) -> list[tuple[str, str]]:
        """`(key, label)` pairs the expanded view offers for this item. Each runs behind a confirm."""
        return []

    def run_action(self, project_dir: Path, item: NeedItem, key: str) -> Optional[str]:
        """Run the action bound to `key` (only ever one `actions(item)` declared, after a yes)."""
        return None

    # ----- 2. Explain cards -----

    def explain_cards(self) -> list:
        """Explain cards (`daedalus.tui.cards.Card`) for the concepts this plugin shows."""
        return []

    # ----- 3. menu screens -----

    def screens(self) -> list[tuple[str, Any]]:
        """`(label, ScreenClass)` pairs for the plugin menu."""
        return []


def plugin_name(plugin: Any) -> str:
    return getattr(plugin, "name", "") or type(plugin).__name__


def plugin_for(kind: str) -> Optional[Any]:
    """The plugin that owns a NeedsYou kind, or None for the core's kinds."""
    for plugin in plugins():
        if getattr(plugin, "tag", "") == kind:
            return plugin
    return None


def detail_for(item: NeedItem, project_dir: Path = Path(".")) -> Optional[str]:
    """A plugin item's detail text (None when no plugin owns the kind, or it failed)."""
    plugin = plugin_for(item.kind)
    if plugin is None:
        return None
    try:
        return str(plugin.detail(item, Path(project_dir)))
    except Exception:
        return None


def actions_for(plugin: Any, item: NeedItem) -> list[tuple[str, str]]:
    """The plugin's declared `(key, label)` actions for an item, minus reserved keys. [] if it fails."""
    try:
        pairs = list(getattr(plugin, "actions", lambda _i: [])(item) or [])
    except Exception:
        return []
    out = []
    for pair in pairs:
        try:
            key, label = pair
        except (TypeError, ValueError):
            continue
        key = str(key)
        if key and key not in RESERVED_KEYS and key not in dict(out):
            out.append((key, str(label)))
    return out


def run_action(plugin: Any, project_dir: Path, item: NeedItem, key: str) -> str:
    """Call the plugin's run_action (the caller has already confirmed). Never raises."""
    try:
        note = plugin.run_action(Path(project_dir), item, key)
    except Exception as e:
        return f"{plugin_name(plugin)}'s action failed: {e}"
    return str(note) if note else f"{plugin_name(plugin)}: ran {key} on {item.key}"


def menu_entries() -> list[tuple[str, str, Any]]:
    """Every plugin screen: (plugin name, label, ScreenClass). A plugin whose screens() fails is skipped."""
    out = []
    for plugin in plugins():
        try:
            pairs = list(getattr(plugin, "screens", lambda: [])() or [])
        except Exception:
            continue
        name = plugin_name(plugin)
        out += [(name, label, cls) for label, cls in pairs]
    return out
