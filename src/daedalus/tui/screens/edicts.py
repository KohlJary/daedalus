"""
The Edicts screen (docs/design/tui/edicts.oph, @expanded): a read-only browser over docs/edicts/.

Each edict shows its status, where the gameplan tracks it (as `daedalus edict list` does), its text, and
the dissents filed on it; the Dissents tab lists every dissent, open or resolved. The owner writes and
accepts edicts through git: there is no accept key here (edict 0012), only Send to Claude.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from rich.text import Text
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Markdown, OptionList, Static
from textual.widgets.option_list import Option

from ..widgets import ExplainCard, KeyBar

TABS = (("edicts", "Edicts"), ("dissents", "Dissents"))
KEYS = {
    "edicts": "↑/↓ select · r read full · s send to Claude · d dissents · ? explain · esc back",
    "dissents": "↑/↓ select · r read full · s send to Claude · E edicts · ? explain · esc back",
}


def tab_strip(active: str) -> str:
    return " · ".join(f"[{name}]" if key == active else name for key, name in TABS)


# ---------- reading (library functions only) ----------

def load_rows(project_dir: Path) -> list[dict]:
    """Every edict: number, file, status, title, where the gameplan tracks it, its dissents."""
    from ...cli.commands import _edict_title, _gameplan_refs
    from ...doctor import edicts_dir, load_edicts
    from ...edicts import list_dissents

    folder = edicts_dir(project_dir)
    refs = _gameplan_refs(project_dir)
    dissents = list_dissents(project_dir, open_only=False)
    rows = []
    for e in load_edicts(project_dir):
        path = folder / e["file"]
        rows.append({"number": e["number"], "file": e["file"], "path": path, "status": e["status"] or "?",
                     "title": _edict_title(path), "tracked": refs.get(e["number"], []),
                     "dissents": [d for d in dissents if d.edict == e["number"]]})
    return rows


def load_dissents(project_dir: Path) -> list:
    from ...edicts import list_dissents

    return list_dissents(project_dir, open_only=False)


def tracked_label(tracked: list) -> str:
    return "; ".join(f"{w} [{s}]" for w, s in tracked) if tracked else "not in the gameplan"


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as e:
        return f"(can't read {path}: {e})"


# ---------- the screen ----------

class EdictsScreen(Screen):
    """The edict browser. Read-only: no accept key; s hands an edict or dissent to Claude."""

    BINDINGS = [
        ("escape", "back", "back"), ("question_mark", "explain", "explain"), ("s", "send", "send to Claude"),
        ("r", "read_full", "read full"), ("d", "tab('dissents')", "dissents"), ("E", "tab('edicts')", "edicts"),
        ("j", "cursor('down')", "down"), ("k", "cursor('up')", "up"),
    ]
    DEFAULT_CSS = """
    EdictsScreen { layout: vertical; }
    EdictsScreen #edicts-title { height: 1; padding: 0 1; background: $boost; text-style: bold; }
    EdictsScreen #edicts-tabs { height: 1; padding: 0 1; color: $text-muted; }
    EdictsScreen #edicts-main { height: 1fr; }
    EdictsScreen OptionList { width: 2fr; height: 1fr; border: round $panel; }
    EdictsScreen OptionList:focus { border: round $accent; }
    EdictsScreen #edict-detail-box { width: 3fr; border: round $panel; }
    EdictsScreen #edict-head { height: auto; padding: 0 1; text-style: bold; }
    EdictsScreen #edict-scroll { height: 1fr; padding: 0 1; }
    EdictsScreen #edict-keys { height: 1; padding: 0 1; color: $text-muted; border-top: solid $panel; }
    EdictsScreen.-full OptionList { display: none; }
    """

    def __init__(self, app: Any, select: Optional[str] = None, tab: str = "edicts"):
        super().__init__()
        self.project_dir = Path(app.project_dir)
        self.select = select
        self.tab = tab
        self.rows: list[dict] = []
        self.dissents: list = []

    def compose(self):
        yield Static("Edicts", id="edicts-title")
        yield Static("", id="edicts-tabs", markup=False)
        with Horizontal(id="edicts-main"):
            yield OptionList(id="edict-list")
            yield OptionList(id="dissent-list")
            with Vertical(id="edict-detail-box"):
                yield Static("", id="edict-head", markup=False)
                with VerticalScroll(id="edict-scroll"):
                    yield Markdown("", id="edict-body")
                yield Static("r read full · s send to Claude", id="edict-keys")
        yield KeyBar()

    def on_mount(self) -> None:
        self.refresh_state(None)
        self.action_tab(self.tab)

    # ----- data -----

    def refresh_state(self, state: Any = None) -> None:
        self.rows = load_rows(self.project_dir)
        self.dissents = load_dissents(self.project_dir)
        counts: dict[str, int] = {}
        for r in self.rows:
            counts[r["status"]] = counts.get(r["status"], 0) + 1
        summary = " · ".join(f"{n} {s}" for s, n in sorted(counts.items()))
        self.query_one("#edicts-title", Static).update(f"Edicts  ({summary or 'none yet'})")

        el = self.query_one("#edict-list", OptionList)
        keep = self.select or (el.highlighted_option.id[2:] if el.highlighted_option else None)
        el.clear_options()
        el.add_options([Option(Text(f"{r['number']} {r['status']:<9} {r['title']}"
                                    + (f"  [{sum(1 for d in r['dissents'] if d.status == 'open')} dissent]"
                                       if any(d.status == "open" for d in r["dissents"]) else "")),
                               id=f"e:{r['number']}:{i}") for i, r in enumerate(self.rows)])
        if self.rows:
            idx = next((i for i, r in enumerate(self.rows) if r["number"] == (keep or "").split(":")[0]), 0)
            el.highlighted = idx

        dl = self.query_one("#dissent-list", OptionList)
        dkeep = dl.highlighted
        dl.clear_options()
        dl.add_options([Option(Text(f"{d.edict} {d.status:<9} {d.path.stem}"
                                    + (f"  ({d.outcome})" if d.outcome else "")), id=f"d:{d.path.name}")
                        for d in self.dissents])
        if self.dissents:
            dl.highlighted = dkeep if dkeep is not None and dkeep < len(self.dissents) else 0
        self._show_current()

    def _show_current(self) -> None:
        if self.tab == "edicts":
            self._show_edict(self.query_one("#edict-list", OptionList).highlighted)
        else:
            self._show_dissent(self.query_one("#dissent-list", OptionList).highlighted)

    def _set(self, head: str, body: str, keys: str) -> None:
        self.query_one("#edict-head", Static).update(head)
        self.query_one("#edict-body", Markdown).update(body)
        self.query_one("#edict-keys", Static).update(keys)

    def _show_edict(self, index: Optional[int]) -> None:
        if not self.rows:
            self._set("No edicts yet.",
                      "An **edict** is a design decision from the project's owner: what to build and why, with "
                      "acceptance criteria the work is judged against. Edicts live in `docs/edicts/NNNN-slug.md` "
                      "and are accepted by merging them on main.\n\nTo start: `daedalus init --edicts`, then write "
                      "`docs/edicts/0001-<slug>.md` (or press **s** and ask Claude to draft one for you to review).",
                      "s send to Claude")
            return
        if index is None or not (0 <= index < len(self.rows)):
            return
        r = self.rows[index]
        self.select = r["number"]
        head = [f"{r['number']} · {r['status']} · {tracked_label(r['tracked'])}", r["title"]]
        if r["dissents"]:
            head.append("dissents: " + ", ".join(f"{d.path.stem} [{d.status}]" for d in r["dissents"]))
        head.append(f"docs/edicts/{r['file']}")
        self._set("\n".join(head), _read(r["path"]), "r read full · s send to Claude · d dissents")

    def _show_dissent(self, index: Optional[int]) -> None:
        if not self.dissents:
            self._set("No dissents.",
                      "A **dissent** is an objection filed against an edict, by an agent or a person: what it "
                      "objects to, why, and what it would do instead. Work on that edict pauses until the owner "
                      "resolves it.\n\nThey live in `docs/edicts/dissents/`. CLI: `daedalus edict dissent <number>`.",
                      "E edicts")
            return
        if index is None or not (0 <= index < len(self.dissents)):
            return
        d = self.dissents[index]
        title = next((r["title"] for r in self.rows if r["number"] == d.edict), "")
        head = f"{d.path.stem} · {d.status}" + (f" ({d.outcome})" if d.outcome else "") + \
               f" · on edict {d.edict} {title}\nby {d.agent}" + (f" · filed {d.filed}" if d.filed else "")
        self._set(head, _read(d.path), "r read full · s send to Claude · E edicts")

    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        if event.option_list.id == "edict-list" and self.tab == "edicts":
            self._show_edict(event.option_index)
        elif event.option_list.id == "dissent-list" and self.tab == "dissents":
            self._show_dissent(event.option_index)

    # ----- actions -----

    def action_tab(self, tab: str) -> None:
        self.tab = tab
        self.query_one("#edict-list").styles.display = "block" if tab == "edicts" else "none"
        self.query_one("#dissent-list").styles.display = "block" if tab == "dissents" else "none"
        self.query_one("#edicts-tabs", Static).update(tab_strip(tab))
        self.query_one(KeyBar).show_dashboard(KEYS[tab])
        self.query_one("#edict-list" if tab == "edicts" else "#dissent-list", OptionList).focus()
        self._show_current()

    def action_read_full(self) -> None:
        """Toggle reading the selected text full width (the list hides; r again brings it back)."""
        self.toggle_class("-full")
        if self.has_class("-full"):
            self.query_one("#edict-scroll").focus()
        else:
            self.query_one("#edict-list" if self.tab == "edicts" else "#dissent-list", OptionList).focus()

    def action_cursor(self, direction: str) -> None:
        if isinstance(self.focused, OptionList):
            getattr(self.focused, f"action_cursor_{direction}")()
        else:
            self.query_one("#edict-scroll").scroll_relative(y=1 if direction == "down" else -1)

    def action_back(self) -> None:
        if self.has_class("-full"):
            self.action_read_full()
            return
        self.app.pop_screen()

    def action_explain(self) -> None:
        from ..cards import PANEL_CARDS

        self.app.push_screen(ExplainCard("Dissent" if self.tab == "dissents" else PANEL_CARDS.get("Edicts", "Edict")))

    def send_target(self) -> tuple[str, str]:
        if self.tab == "dissents":
            idx = self.query_one("#dissent-list", OptionList).highlighted
            if self.dissents and idx is not None:
                d = self.dissents[idx]
                return (f"Dissent {d.path.stem}",
                        f"Read the dissent {d.path.relative_to(self.project_dir) if d.path.is_relative_to(self.project_dir) else d.path} "
                        f"and edict {d.edict} it objects to, and summarise both sides for me. Resolving it is my call.")
            return ("Dissents", "Explain how dissents work in this project.")
        idx = self.query_one("#edict-list", OptionList).highlighted
        if self.rows and idx is not None:
            r = self.rows[idx]
            if r["status"] == "proposed":
                ask = "Tell me whether it's ready to build: what's unclear or untestable. Accepting it is my call."
            elif r["status"] == "accepted":
                ask = ("Check how far the work on it has got against its acceptance criteria and the gameplan "
                       f"({tracked_label(r['tracked'])}). Report gaps; don't fix them yet.")
            else:
                ask = "Summarise what it decided and where that lives in the code."
            return (f"Edict {r['number']}", f"Read edict {r['number']} (docs/edicts/{r['file']}). {ask}")
        return ("Edicts", "Help me draft a first edict for this project, for me to review and accept.")

    def action_send(self) -> None:
        source, prompt = self.send_target()
        self.app.ask_to_send(source, prompt)
