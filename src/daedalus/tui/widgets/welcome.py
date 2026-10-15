from __future__ import annotations

from textual.widgets import Static

from .panel import Panel


class Welcome(Panel):
    """◆Welcome: the first-run left column. An empty state teaches; it never just says "no data"."""

    card = "Gameplan"
    DEFAULT_CSS = """
    Welcome {
        height: 1fr;
    }
    """

    def compose(self):
        yield Static(
            "[b]Welcome to Daedalus[/b]\n\n"
            "Nothing here yet. Daedalus fills these panels as you work:\n\n"
            " · a gameplan (what's next)\n"
            " · edicts (your decisions)\n"
            " · session notes (what happened)\n\n"
            "? what is all this\n"
            "c ask Claude to start a plan")
