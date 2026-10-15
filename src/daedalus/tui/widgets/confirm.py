"""A yes/no question before a destructive or outward-facing write (edict 0012: drop, forget, delete, a doctor
fix, a write-back to an outside tracker, a plugin's action). Dismisses with True only on an explicit `y`:
enter does not confirm, so a stray enter can never drop or delete anything. This is the one confirm modal;
every screen imports it from here."""

from __future__ import annotations

from rich.text import Text
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Static


class ConfirmModal(ModalScreen[bool]):
    """`push_screen(ConfirmModal("Drop P1?"), callback)`: the callback gets True for y, False for n or esc.
    Enter is bound to nothing here on purpose."""

    BINDINGS = [("y", "answer(True)", "yes"), ("n", "answer(False)", "no"), ("escape", "answer(False)", "cancel")]
    DEFAULT_CSS = """
    ConfirmModal { align: center middle; }
    ConfirmModal > Vertical {
        width: 64;
        height: auto;
        border: round $warning;
        background: $surface;
        padding: 1 2;
    }
    ConfirmModal #confirm-keys { color: $text-muted; }
    """

    def __init__(self, question: str, detail: str = ""):
        super().__init__()
        self.question, self.detail = question, detail

    def compose(self):
        with Vertical():
            yield Static(Text(self.question, style="bold"), id="confirm-question", markup=False)
            if self.detail:
                yield Static(self.detail, id="confirm-detail", markup=False)
            yield Static("\ny yes · n / esc cancel", id="confirm-keys")

    def action_answer(self, yes: bool) -> None:
        self.dismiss(bool(yes))
