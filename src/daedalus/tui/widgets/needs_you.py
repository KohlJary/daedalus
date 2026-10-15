from __future__ import annotations

from textual.widgets import Static

from .panel import Panel


class NeedsYou(Panel):
    """◆NeedsYou: everything waiting on the project's owner, a two-letter tag per kind (not colour alone)."""

    card = "Pending proposal"
    DEFAULT_CSS = """
    NeedsYou {
        height: 1fr;
        min-height: 4;
    }
    NeedsYou .title { text-style: bold; }
    """

    def compose(self):
        yield Static("Needs you", classes="title", id="needs-title")
        yield Static("", id="needs-body")

    def refresh_state(self, state) -> None:
        items = state.needs
        self.query_one("#needs-title", Static).update(f"Needs you{' ' * 20}{len(items) or ''}")
        if not items:
            self.query_one("#needs-body", Static).update(
                "\n  ✓ nothing waiting on you\n\n  PRs, proposed edicts, dissents, board posts and\n"
                "  pending proposals appear here.")
            return
        rows = [f"{'▸' if i == 0 else ' '} {it.kind} {it.title}"[:60] for i, it in enumerate(items)]
        self.query_one("#needs-body", Static).update("\n".join(rows))
