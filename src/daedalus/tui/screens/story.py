"""
Story (docs/design/tui/story.oph): "where are we, and how did we get here?"

The narrative half of memory, read-only: docs/status.md (now), .daedalus/session-summaries.md (then,
newest first), decisions.md (why), lessons.md and warnings.md (watch out), project-map.md (what's where).
Now and Map are one rendered document each; the others are list-then-detail. A missing file shows an
empty state that says what goes there and how it gets written.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Markdown, OptionList, Static
from textual.widgets.option_list import Option

from ..widgets import ExplainCard, KeyBar

# (key, label, path relative to the project, list-then-detail?)
TABS = [
    ("now", "Now", "docs/status.md", False),
    ("sessions", "Sessions", ".daedalus/session-summaries.md", True),
    ("decisions", "Decisions", ".daedalus/decisions.md", True),
    ("lessons", "Lessons", ".daedalus/lessons.md", True),
    ("warnings", "Warnings", ".daedalus/warnings.md", True),
    ("map", "Map", ".daedalus/project-map.md", False),
]

EMPTY = {
    "now": "No status note yet.\n\n`docs/status.md` is the short note each working session ends with: what happened, "
           "open dissents, anything the gameplan can't say. A fresh Claude context reads it first with `/inhale`, "
           "and `/exhale` writes it. Run `/exhale` in the Claude pane at your next breakpoint to start it.",
    "sessions": "No session notes yet.\n\nEach session adds a dated `## YYYY-MM-DD: what happened` entry to "
                "`.daedalus/session-summaries.md`, newest shown first here. `/exhale` in the Claude pane writes one.",
    "decisions": "No decisions recorded yet.\n\nKey decisions and their rationale go in `.daedalus/decisions.md`, "
                 "one `## Title` entry each, so the next person knows why, not just what. Ask Claude to record one "
                 "when a choice is made.",
    "lessons": "No lessons yet.\n\n`.daedalus/lessons.md` holds what was learned the hard way, one `## Title` "
               "entry each. Claude adds to it at `/exhale` when a session taught something.",
    "warnings": "No warnings yet.\n\n`.daedalus/warnings.md` lists hazards to watch for in this codebase, one "
                "`## Title` entry each. Add one when something bites.",
    "map": "No project map yet.\n\n`.daedalus/project-map.md` describes the architecture: modules, patterns, data "
           "flow. `daedalus init` creates it; Claude fills it in as it learns the code.",
}

HEADING = re.compile(r"^## (.*)$", re.M)
DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
TASK_ID = re.compile(r"\bT-[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*\b")


@dataclass
class Entry:
    title: str
    body: str      # the whole entry, heading included, as Markdown
    date: str = ""


def entries(text: str) -> list[Entry]:
    """The `## ` entries of a memory file, in file order."""
    starts = [m.start() for m in HEADING.finditer(text)]
    out = []
    for a, b in zip(starts, starts[1:] + [len(text)]):
        chunk = text[a:b].strip()
        title = chunk.splitlines()[0][3:].strip()
        m = DATE.search(title)
        out.append(Entry(title, chunk, m.group(0) if m else ""))
    return out


def newest_first(items: list[Entry]) -> list[Entry]:
    """Dated entries newest first; undated ones after them, latest in the file first."""
    dated = sorted((e for e in items if e.date), key=lambda e: e.date, reverse=True)
    return dated + [e for e in reversed(items) if not e.date]


def task_ids(entry: Entry) -> list[str]:
    seen: list[str] = []
    for tid in TASK_ID.findall(entry.body):
        if tid not in seen:
            seen.append(tid)
    return seen


def label(entry: Entry, width: int = 34) -> str:
    title = entry.title
    if entry.date:
        rest = title.replace(entry.date, "", 1).strip(" :-–—/0123456789")
        title = f"{entry.date}  {rest or title}"
    return title if len(title) <= width else title[: width - 1] + "…"


def read(project_dir: Path, rel: str) -> Optional[str]:
    path = Path(project_dir) / rel
    try:
        return path.read_text(encoding="utf-8") if path.is_file() else None
    except OSError:
        return None


def last_updated(project_dir: Path, rel: str) -> str:
    """When the file last changed: its last commit's date, else its modification date."""
    try:
        out = subprocess.run(["git", "log", "-1", "--format=%cs", "--", rel], cwd=project_dir,
                             capture_output=True, text=True, timeout=10)
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass
    try:
        from datetime import datetime

        return datetime.fromtimestamp((Path(project_dir) / rel).stat().st_mtime).strftime("%Y-%m-%d")
    except OSError:
        return ""


class StoryScreen(Screen):
    """The Story screen: now · sessions · decisions · lessons · warnings · map. Read-only."""

    BINDINGS = [
        ("escape", "back", "back"), ("question_mark", "explain", "explain"), ("s", "send", "send to Claude"),
        ("g", "goto_task", "open task"), ("right", "tab(1)", "next tab"), ("left", "tab(-1)", "previous tab"),
        ("l", "tab(1)", "next tab"), ("h", "tab(-1)", "previous tab"),
        ("1", "show('now')", "Now"), ("2", "show('sessions')", "Sessions"), ("3", "show('decisions')", "Decisions"),
        ("4", "show('lessons')", "Lessons"), ("5", "show('warnings')", "Warnings"), ("6", "show('map')", "Map"),
    ]
    DEFAULT_CSS = """
    StoryScreen { layout: vertical; }
    StoryScreen #story-title { height: 1; background: $boost; padding: 0 1; text-style: bold; }
    StoryScreen #story-tabs { height: 2; padding: 0 1; border-bottom: solid $panel; }
    StoryScreen #story-doc { height: 1fr; padding: 0 1; }
    StoryScreen #story-split { height: 1fr; }
    StoryScreen #story-list { width: 40; border-right: solid $panel; }
    StoryScreen #story-right { width: 1fr; }
    StoryScreen #story-detail { height: 1fr; padding: 0 1; }
    StoryScreen #story-keys { height: 2; padding: 0 1; color: $text-muted; border-top: solid $panel; }
    StoryScreen #story-updated { color: $text-muted; padding: 0 1; }
    """

    def __init__(self, app, tab: str = "now"):
        super().__init__()
        self.shell = app
        self.project_dir = Path(app.project_dir)
        self.tab = tab
        self.items: list[Entry] = []
        self.texts: dict[str, Optional[str]] = {}

    def compose(self):
        yield Static("Story", id="story-title", markup=False)
        yield Static("", id="story-tabs")
        with VerticalScroll(id="story-doc"):
            yield Static("", id="story-updated", markup=False)
            yield Markdown("", id="story-doc-body")
        with Horizontal(id="story-split"):
            yield OptionList(id="story-list", markup=False)
            with Vertical(id="story-right"):
                with VerticalScroll(id="story-detail"):
                    yield Markdown("", id="story-detail-body")
                yield Static("", id="story-keys", markup=False)
        yield KeyBar()

    def on_mount(self) -> None:
        self.query_one(KeyBar).show_dashboard(
            "←/→ tab · ↑/↓ entry · g open task in Gameplan · s send to Claude · ? explain · esc back")
        self.refresh_state(getattr(self.shell, "state", None))

    # ----- state -----

    def refresh_state(self, state=None) -> None:
        self.texts = {key: read(self.project_dir, rel) for key, _, rel, _ in TABS}
        self._redraw()

    def _redraw(self) -> None:
        width = max(self.size.width - 20, 40)
        title = "Story"
        self.query_one("#story-title", Static).update(title + " " * max(2, width - len(title)) + "esc back")
        self.query_one("#story-tabs", Static).update(
            " · ".join(f"[reverse] {lab} [/reverse]" if key == self.tab else lab for key, lab, _, _ in TABS))
        key, _, rel, is_list = next(t for t in TABS if t[0] == self.tab)
        text = self.texts.get(key)
        doc, split = self.query_one("#story-doc"), self.query_one("#story-split")
        doc.styles.display = "none" if is_list else "block"
        split.styles.display = "block" if is_list else "none"
        if not is_list:
            updated = self.query_one("#story-updated", Static)
            if text is None:
                updated.update("")
                self.query_one("#story-doc-body", Markdown).update(EMPTY[key])
            else:
                when = last_updated(self.project_dir, rel)
                updated.update(f"{rel}" + (f" · last updated {when}" if when else ""))
                self.query_one("#story-doc-body", Markdown).update(text)
            return
        found = entries(text) if text else []
        self.items = newest_first(found) if key == "sessions" else found
        olist = self.query_one("#story-list", OptionList)
        keep = olist.highlighted
        olist.clear_options()
        if not self.items:
            olist.add_option(Option("(none yet)", disabled=True))
            self.query_one("#story-detail-body", Markdown).update(EMPTY[key])
            self.query_one("#story-keys", Static).update(f"{rel} · ? explain")
            return
        olist.add_options([Option(label(e), id=str(i)) for i, e in enumerate(self.items)])
        olist.highlighted = keep if keep is not None and keep < len(self.items) else 0
        self._show_detail()

    def _selected(self) -> Optional[Entry]:
        if not self._is_list() or not self.items:
            return None
        idx = self.query_one("#story-list", OptionList).highlighted
        return self.items[idx] if idx is not None and idx < len(self.items) else None

    def _is_list(self) -> bool:
        return next(t[3] for t in TABS if t[0] == self.tab)

    def _show_detail(self) -> None:
        entry = self._selected()
        if entry is None:
            return
        self.query_one("#story-detail-body", Markdown).update(entry.body)
        keys = "s send to Claude"
        if self.tab == "sessions" and task_ids(entry):
            keys = "g open task in Gameplan · " + keys
        rel = next(t[2] for t in TABS if t[0] == self.tab)
        self.query_one("#story-keys", Static).update(f"{keys} · {rel}")

    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        self._show_detail()

    # ----- actions -----

    def action_show(self, tab: str) -> None:
        self.tab = tab
        self._redraw()
        if self._is_list():
            self.query_one("#story-list").focus()
        else:
            self.query_one("#story-doc").focus()

    def action_tab(self, step: int) -> None:
        keys = [t[0] for t in TABS]
        self.action_show(keys[(keys.index(self.tab) + step) % len(keys)])

    def action_back(self) -> None:
        self.app.pop_screen()

    def action_explain(self) -> None:
        from ..cards import PANEL_CARDS

        self.app.push_screen(ExplainCard(PANEL_CARDS.get("Story", "Story")))

    def action_send(self) -> None:
        key, lab, rel, _ = next(t for t in TABS if t[0] == self.tab)
        entry = self._selected()
        if entry is not None:
            source = f"{lab}: {entry.title}"
            prompt = (f"Read the entry \"{entry.title}\" in {rel} and tell me what it means for the work in "
                      "flight now. Check it against the gameplan and the code; say if anything in it is stale.")
        elif self.texts.get(key) is not None:
            source = rel
            prompt = f"Read {rel} and tell me where things stand and what's next."
        else:
            source = rel
            prompt = f"{rel} doesn't exist yet. Draft it from what you know of this project, for me to review."
        self.shell.ask_to_send(source, prompt)

    def action_goto_task(self) -> None:
        entry = self._selected()
        ids = task_ids(entry) if entry is not None and self.tab == "sessions" else []
        if not ids:
            self.notify("No task IDs in this entry.", markup=False)
            return
        self.notify(f"Tasks in this entry: {', '.join(ids)}", markup=False)
        self.shell.open_screen("gameplan")
