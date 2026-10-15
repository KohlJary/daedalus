from __future__ import annotations

from textual.widgets import Static

DASHBOARD = "1-5 panel · enter expand · s send to Claude · c focus Claude · e edicts · b board · , config · R reflection · ? help · q quit"
MODAL = "enter confirm · esc cancel"


class KeyBar(Static):
    """◆KeyBar: always says which mode you're in. While Claude has focus, every key goes to Claude."""

    DEFAULT_CSS = """
    KeyBar {
        height: 1;
        background: $boost;
        padding: 0 1;
    }
    KeyBar.-claude {
        background: $accent;
        color: $text;
    }
    """

    def show_dashboard(self, extra: str = "") -> None:
        self.remove_class("-claude")
        self.update(extra or DASHBOARD)

    def show_claude(self, escape: str) -> None:
        self.add_class("-claude")
        width = max(self.size.width - 2, 40)
        left, right = "● every key goes to Claude", f"{escape} back to dashboard"
        self.update(left + " " * max(2, width - len(left) - len(right)) + right)

    def show_modal(self) -> None:
        self.remove_class("-claude")
        self.update(MODAL)
