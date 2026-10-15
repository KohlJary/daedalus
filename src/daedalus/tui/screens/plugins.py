"""
The plugin menu (edict 0012, plugins): every screen a `daedalus.tui` plugin adds, reached with `m` from
the shell. The menu lists; the plugins' screens do the rest. The shell layout itself is not pluggable.
"""

from __future__ import annotations

from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import OptionList, Static
from textual.widgets.option_list import Option

from ..plugin import menu_entries
from ..widgets import ExplainCard, KeyBar

EMPTY = ("No TUI plugins are installed.\n\n"
         "A package adds screens here, a kind of item to Needs you, or Explain cards, through the\n"
         "`daedalus.tui` entry point. See the TuiPlugin class in daedalus.tui.plugin to write one.")


class PluginMenu(Screen):
    """The screens plugins add, by plugin and label. enter opens one; esc goes back."""

    BINDINGS = [("escape", "back", "back"), ("question_mark", "explain", "explain"), ("enter", "open", "open")]
    DEFAULT_CSS = """
    PluginMenu { layout: vertical; }
    PluginMenu #plugins-title { height: 1; background: $boost; padding: 0 1; text-style: bold; }
    PluginMenu #plugins-body { height: 1fr; border: round $panel; padding: 0 1; }
    PluginMenu OptionList { height: 1fr; border: none; }
    PluginMenu #plugins-empty { color: $text-muted; }
    """

    def __init__(self, app=None):
        super().__init__()
        self.entries = menu_entries()

    def compose(self):
        yield Static("Plugins · esc back", id="plugins-title", markup=False)
        with Vertical(id="plugins-body"):
            if self.entries:
                yield OptionList(*[Option(f"{label}  ({name})", id=str(i))
                                   for i, (name, label, _) in enumerate(self.entries)], id="plugins-list", markup=False)
            else:
                yield Static(EMPTY, id="plugins-empty", markup=False)
        yield KeyBar()

    def on_mount(self) -> None:
        self.query_one(KeyBar).show_dashboard("enter open · ? what plugins are · esc back")
        if self.entries:
            self.query_one(OptionList).focus()

    def refresh_state(self, state) -> None:
        """Plugins load once per run; nothing on disk changes this list."""

    def action_back(self) -> None:
        self.app.pop_screen()

    def action_explain(self) -> None:
        self.app.push_screen(ExplainCard("TUI plugin"))

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self._open(int(event.option.id))

    def action_open(self) -> None:
        if self.entries:
            index = self.query_one(OptionList).highlighted
            self._open(index or 0)

    def _open(self, index: int) -> None:
        name, label, cls = self.entries[index]
        try:
            screen = cls(self.app)
        except Exception as e:  # a broken plugin screen never takes the TUI down
            self.app.notify(f"{name}: couldn't open {label} ({e})", severity="error", markup=False)
            return
        self.app.push_screen(screen)
