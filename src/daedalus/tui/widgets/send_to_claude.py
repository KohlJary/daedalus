from __future__ import annotations

from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Static, TextArea


class SendToClaude(ModalScreen):
    """◆SendToClaude: a prompt built from the selection. Enter pastes it into Claude's input and never
    submits: you press enter in the pane yourself."""

    BINDINGS = [("escape", "cancel", "cancel"), ("enter", "paste", "paste"), ("e", "edit", "edit")]
    DEFAULT_CSS = """
    SendToClaude { align: center middle; }
    SendToClaude > Vertical { width: 64; height: auto; border: round $accent; background: $surface; padding: 1 2; }
    SendToClaude TextArea { height: 8; }
    """

    def __init__(self, source: str, prompt: str):
        super().__init__()
        self.source, self.prompt = source, prompt

    def compose(self):
        with Vertical():
            yield Static("[b]Send to Claude[/b]")
            yield Static(f"From: {self.source}")
            yield TextArea(self.prompt, id="prompt", read_only=True)
            yield Static("e edit · enter paste into prompt · esc cancel", id="send-keys")

    def action_edit(self) -> None:
        area = self.query_one("#prompt", TextArea)
        area.read_only = False
        area.focus()
        self.query_one("#send-keys", Static).update("ctrl+s paste into prompt · esc cancel")

    def key_ctrl_s(self) -> None:
        self.action_paste()

    def action_paste(self) -> None:
        area = self.query_one("#prompt", TextArea)
        if not area.read_only and self.focused is area:
            return  # enter is a newline while editing; ctrl+s pastes
        self.dismiss(area.text.rstrip("\n"))

    def action_cancel(self) -> None:
        self.dismiss(None)
