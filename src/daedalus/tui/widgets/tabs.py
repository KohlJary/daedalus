from __future__ import annotations

from textual.containers import Horizontal
from textual.widgets import Static

TABS = [("1", "Needs"), ("2", "Plan"), ("3", "Health"), ("4", "Claude"), ("5", "Story")]


class TabBar(Static):
    """◆TabBar: the narrow layout's tabs (under ~100 columns each panel is a tab; 4 is Claude, full width)."""

    DEFAULT_CSS = """
    TabBar {
        height: 1;
        padding: 0 1;
        display: none;
    }
    """

    def show(self, active: str, counts: dict) -> None:
        parts = []
        for key, name in TABS:
            label = f"{key} {name}" + (f" {counts[key]}" if counts.get(key) else "")
            parts.append(f"[reverse]{label}[/reverse]" if key == active else label)
        self.update("  ".join(parts))


class ActiveTab(Horizontal):
    """◆ActiveTab: the body. On a wide terminal it holds both columns; on a narrow one, the active tab only."""

    DEFAULT_CSS = """
    ActiveTab {
        height: 1fr;
    }
    """
