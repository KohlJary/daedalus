from __future__ import annotations

from rich.text import Text
from textual.widgets import Static


class Header(Static):
    """◆Header: project, branch, active phase ▸ next task; counts that mirror the panels."""

    DEFAULT_CSS = """
    Header {
        height: 1;
        background: $boost;
        color: $text;
        padding: 0 1;
    }
    """

    _state = None

    def on_resize(self, event) -> None:
        if self._state is not None:
            self.refresh_state(self._state)

    def refresh_state(self, state) -> None:
        self._state = state
        h = state.header
        plan = f"{h.get('phase')} ▸ {h.get('task')}" if h.get("phase") and h.get("task") else (h.get("phase") or "no active phase")
        claude = "● claude " + (state.claude_status or "no session")
        right = f"needs {len(state.needs)} · drift {len(state.findings)} · {claude}"
        left = f"{h.get('project', '')}  {h.get('branch', '')}  {plan}"
        width = max((self.size.width or self.app.size.width) - 2, 40)
        gap = max(2, width - len(left) - len(right))
        self.update(Text(left[: max(10, width - len(right) - 2)] + " " * gap + right))  # branch names are not markup
