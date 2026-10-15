from __future__ import annotations

from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Static

from ..cards import card as get_card


class ExplainCard(ModalScreen):
    """◆ExplainCard: what it is, where it lives, the CLI that shows it. Always all three."""

    BINDINGS = [("escape", "dismiss", "close"), ("g", "glossary", "glossary")]
    DEFAULT_CSS = """
    ExplainCard {
        align: center middle;
    }
    ExplainCard > Vertical {
        width: 60;
        height: auto;
        border: round $accent;
        background: $surface;
        padding: 1 2;
    }
    """

    def __init__(self, name: str):
        super().__init__()
        self.card_name = name

    def compose(self):
        c = get_card(self.card_name)
        with Vertical():
            yield Static(f"[b]? {c.title}[/b]", id="card-title")
            yield Static(c.body, id="card-body")
            yield Static(f"\nLives in {c.lives or '(nowhere on disk)'}.", id="card-lives")
            yield Static(f"CLI: {c.cli or 'daedalus --help'}", id="card-cli")
            yield Static("\ng glossary · esc close", id="card-keys")

    def action_glossary(self) -> None:
        from ..cards import all_cards

        self.dismiss()
        self.app.push_screen(Glossary(sorted(all_cards())))


class Glossary(ModalScreen):
    """Every card, by title."""

    BINDINGS = [("escape", "dismiss", "close")]
    DEFAULT_CSS = """
    Glossary { align: center middle; }
    Glossary > Vertical { width: 70; height: 80%; border: round $accent; background: $surface; padding: 1 2; overflow-y: auto; }
    """

    def __init__(self, names: list[str]):
        super().__init__()
        self.names = names

    def compose(self):
        from ..cards import all_cards

        with Vertical():
            for name in self.names:
                c = all_cards()[name]
                yield Static(f"[b]{c.title}[/b]\n{c.body}\nCLI: {c.cli}\n")
