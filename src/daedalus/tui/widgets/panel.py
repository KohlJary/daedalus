"""The shared base of the dashboard's panels: a title row, a body, `?` for the panel's Explain card."""

from __future__ import annotations

from textual.widget import Widget


class Panel(Widget):
    """A focusable dashboard panel. `card` names its Explain card; `screen_key` the key that expands it."""

    can_focus = True
    card = ""
    DEFAULT_CSS = """
    Panel {
        border: round $panel;
        padding: 0 1;
        height: auto;
    }
    Panel:focus-within, Panel:focus {
        border: round $accent;
    }
    """

    def refresh_state(self, state) -> None:  # pragma: no cover - overridden
        """Redraw from the app's latest state (called by the one file watcher)."""
