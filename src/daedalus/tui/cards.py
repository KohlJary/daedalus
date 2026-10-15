"""
Explain cards (edict 0012): the text behind `?` on every panel. It ships as package data, copied from
docs/design/tui/glossary.md (a test keeps the two identical), so the text is written once and reviewed
like any other doc. Plugins add cards through the `daedalus.tui` entry point.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from importlib.resources import files
from typing import Optional


@dataclass
class Card:
    title: str
    body: str          # what it is
    lives: str         # where it lives
    cli: str           # the CLI that shows it


def _parse(text: str) -> dict[str, Card]:
    cards: dict[str, Card] = {}
    for m in re.finditer(r"^## (.+?)\n(.*?)(?=^## |\Z)", text, re.M | re.S):
        title = re.sub(r"\s*\(.*?\)\s*$", "", m.group(1)).strip()
        body = m.group(2).strip()
        lives = cli = ""
        lm = re.search(r"\*Lives in\*\s*(.*?)(?:\.\s*\*CLI:\*|\*CLI:\*|$)", body, re.S)
        cm = re.search(r"\*CLI:\*\s*(.*)$", body, re.S)
        if lm:
            lives = " ".join(lm.group(1).split()).rstrip(".")
        if cm:
            cli = " ".join(cm.group(1).split())
        prose = re.split(r"\*Lives in\*|\*CLI:\*", body)[0]
        cards[title.lower()] = Card(title, _plain(" ".join(prose.split())), _plain(lives), _plain(cli))
    return cards


def _plain(text: str) -> str:
    """Markdown emphasis and code marks off: a card is plain text in the terminal."""
    return re.sub(r"\*\*(.+?)\*\*|\*(.+?)\*|`(.+?)`", lambda m: next(g for g in m.groups() if g is not None), text)


_cards: Optional[dict[str, Card]] = None


def all_cards() -> dict[str, Card]:
    global _cards
    if _cards is None:
        text = files("daedalus.tui").joinpath("data/glossary.md").read_text(encoding="utf-8")
        _cards = _parse(text)
        from .state import plugins

        for plugin in plugins():
            try:
                extra = list(getattr(plugin, "explain_cards", lambda: [])() or [])
            except Exception:  # one broken plugin never takes the TUI down
                continue
            for card in extra:
                _cards[card.title.lower()] = card
    return _cards


def card(name: str) -> Card:
    found = all_cards().get(name.lower())
    if found is None:
        return Card(name, f"No card for {name} yet.", "", "daedalus --help")
    return found


# Which card each panel shows on `?`
PANEL_CARDS = {
    "NeedsYou": "Pending proposal", "Gameplan": "Gameplan", "Health": "Doctor / drift",
    "ClaudePane": "Claude pane", "LastSession": "Story", "Header": "Gameplan", "Welcome": "Gameplan",
    "Edicts": "Edict", "Board": "Board", "Story": "Story", "Config": "Config", "Sources": "Source",
    "Reflection": "Reflection", "Workstreams": "Workstream", "Roadmap": "Roadmap",
    "Experiment": "A/B experiment", "Plugins": "TUI plugin", "Dream": "Dream",
}
