from __future__ import annotations

from textual.widgets import Static

from .panel import Panel


class Health(Panel):
    """◆Health: `daedalus doctor`. One line when in sync."""

    card = "Doctor / drift"
    DEFAULT_CSS = """
    Health {
        height: auto;
        max-height: 8;
    }
    """

    def compose(self):
        yield Static("", id="health-body", markup=False)

    def refresh_state(self, state) -> None:
        findings = state.findings
        if not findings:
            text = "Health               ✓ in sync"
        else:
            text = f"Health               ⚠ {len(findings)}\n" + "\n".join(f.name for f in findings[:5])
        self.query_one("#health-body", Static).update(text)
