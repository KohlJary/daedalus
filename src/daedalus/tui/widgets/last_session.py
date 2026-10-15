from __future__ import annotations

from rich.text import Text
from textual.widgets import Static


class LastSession(Static):
    """◆LastSession: one line, the newest session note's headline. 5 or w opens Story."""

    DEFAULT_CSS = """
    LastSession {
        height: 1;
        color: $text-muted;
        padding: 0 1;
    }
    """

    def refresh_state(self, state) -> None:
        text = state.last_session
        self.update(Text(f"Last session: {text}" if text else
                         "No session notes yet: /exhale writes one at the end of a session (.daedalus/session-summaries.md)"))
