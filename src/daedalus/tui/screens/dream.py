"""
Dream (docs/design/tui/dream.oph): what dreaming (edict 0013) has made, read-only.

- Dreams: every dream, newest first; the detail is exactly `daedalus dream show <id>`.
- Picks: every waking pick across dreams, with what became of it in the roadmap (its item is
  `dream-<dream-id>.p<n>`): built, in review, waiting, proposed, dropped, or not synced yet.
- Themes: the dream review's theme registry: elevated, covered, superseded, with dream and seed-set counts.
- Due: whether a dream and a dream review are due (computed, never written), and the experiment's lines.

Every dream text sits under the speculative label (◆SpeculativeLabel). Nothing here names the mode a
dream was made in: the edict keeps that from every reader. Running a dream and syncing picks are Claude's
job, so `s` hands them over; this screen writes nothing.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Markdown, OptionList, Static
from textual.widgets.option_list import Option

from ..widgets import ExplainCard, KeyBar

TABS = [("dreams", "Dreams"), ("picks", "Picks"), ("themes", "Themes"), ("due", "Due")]

SYNC = "daedalus source sync dream"

OFF = (
    "Dreaming is off.\n\n"
    "A dream is a protected phase where Daedalus generates widely about where this project could go: seeds "
    "from what it already keeps (stale tasks, open questions, backlog, dissents), the dream itself, then a cold "
    "waking pass that picks three to five ideas. You judge them afterwards. Picks reach the roadmap only as "
    "proposals you apply or drop, and a dream is never evidence: nothing in Daedalus reads one as fact.\n\n"
    "Turn it on:  daedalus config dream.enabled true   (add --project for this project only)\n"
    "Then a dream is due after each reflection run (inhale offers it), or ask for one any time with "
    "/dream [theme] in the Claude pane.\n\n"
    "s ask Claude about dreaming · ? explain · esc back"
)

EMPTY = {
    "dreams": "No dreams yet.\n\nA dream is due after a reflection run, and /inhale offers it. You can also ask for "
              "one any time: run /dream, or /dream about <a theme>, in the Claude pane (s hands it over). Each "
              "dream lands in .daedalus/dreams/<date>/ and shows up here.",
    "picks": "No picks yet.\n\nEach dream ends with a cold waking pass that picks three to five ideas. They appear "
             f"here with what became of them; `{SYNC}` brings them in as roadmap proposals you apply or drop.",
    "themes": "No themes yet.\n\nA dream review groups ideas that came back across dreams into themes. It is due "
              "once dream.review_min dreams (4 by default) have finished since the last one; Claude runs it "
              "(`daedalus dream review`). A theme that recurs from different material, and that nothing in the "
              "plan covers, is elevated to a roadmap proposal.",
}


class SpeculativeLabel(Static):
    """◆SpeculativeLabel: sits above every dream text. A text tag, not a colour."""

    DEFAULT_CSS = """
    SpeculativeLabel {
        height: auto;
        padding: 0 1;
        border-bottom: solid $panel;
        color: $warning;
    }
    """

    TEXT = ("◇ speculative: a dream, not a proposal, not evidence, not reviewed. "
            "Nothing in Daedalus reads it as fact.")

    def __init__(self, **kw):
        super().__init__(self.TEXT, markup=False, **kw)


# ---------- reading (library functions only) ----------

@dataclass
class Pick:
    id: str
    dream: str
    title: str
    text: str
    status: str        # built, in review, waiting, proposed, dropped, not synced yet, or the roadmap status
    item_id: str
    item_status: Optional[str] = None


def _settings(project_dir: Path) -> dict:
    from ...config import get_project_settings

    try:
        return get_project_settings(project_dir, "dream")
    except Exception:
        return {}


def enabled(project_dir: Path) -> bool:
    from ...dreams import store

    return store.dreaming_enabled(project_dir)


def dream_rows(project_dir: Path) -> list[dict]:
    """[{id, status, picks}], newest first. No mode: it is never shown."""
    from ...dreams import store

    out = []
    for dream_id in reversed(store.list_dreams(project_dir)):
        try:
            meta = store.load_meta(project_dir, dream_id)
        except store.DreamError:
            continue
        try:
            n = len(store.picks(project_dir, dream_id))
        except (OSError, store.DreamError):
            n = 0
        out.append({"id": dream_id, "status": str(meta.get("status") or "started"), "picks": n})
    return out


STATUS = {"done": "built", "review": "in review", "backlog": "waiting"}


def pick_status(item: Optional[dict], proposed: bool, dropped: bool) -> str:
    """What became of a pick: its roadmap item's status, else pending, dropped, or not synced yet."""
    if item is not None:
        status = str(item.get("status") or "backlog")
        return STATUS.get(status, status.replace("_", " "))
    if proposed:
        return "proposed"
    if dropped:
        return "dropped"
    return "not synced yet"


def all_picks(project_dir: Path) -> list[Pick]:
    from ... import roadmap
    from ...cli import gameplan as gp
    from ...dreams import store
    from ...sources import state as src_state
    from ...sources.sync import drop_records

    try:
        items = roadmap.by_external(roadmap.load_index(project_dir), "dream")
    except roadmap.RoadmapError:
        items = {}
    pending = {str((p.get("origin") or {}).get("external_id")) for p in gp.load_pending(project_dir)
               if isinstance(p.get("origin"), dict) and p["origin"].get("source") == "dream"}
    try:
        dropped = drop_records(src_state.load(project_dir).get("dream", {}))
    except Exception:
        dropped = {}
    out = []
    for row in dream_rows(project_dir):
        try:
            found = store.picks(project_dir, row["id"])
        except (OSError, store.DreamError):
            continue
        for p in found:
            item = items.get(p["id"])
            out.append(Pick(p["id"], row["id"], p["title"], p["text"],
                            pick_status(item, p["id"] in pending, f"src:dream:{p['id']}" in dropped),
                            roadmap.item_id_for("dream", p["id"]), item.get("status") if item else None))
    return out


def themes(project_dir: Path) -> list[dict]:
    from ...dreams import review

    try:
        registry = review.load_themes(project_dir)["themes"]
    except Exception:
        return []
    rows = [{"id": tid, **t} for tid, t in registry.items() if isinstance(t, dict)]
    return sorted(rows, key=lambda t: (bool(t.get("superseded")), not t.get("elevated"),
                                       -int(t.get("distinct_top_seeds") or 0), str(t["id"])))


def theme_state(t: dict) -> str:
    if t.get("superseded"):
        return f"superseded by {t['superseded_by']}" if t.get("superseded_by") else "superseded"
    if t.get("elevated"):
        return "elevated"
    if t.get("integrated_by"):
        return f"covered by {t['integrated_by']}"
    return "not elevated"


def due_lines(project_dir: Path) -> tuple[list[str], dict]:
    """What is due, from the same functions `dream due`, `dream review` and `dream log` use. Never writes."""
    from ...dreams import report, review, store

    settings = _settings(project_dir)
    try:
        due = store.compute_due(project_dir)
    except Exception as e:  # an unreadable log never takes the screen down
        due = {"due": False, "waiting": None, "error": str(e)}
    lines = []
    if due.get("error"):
        lines.append(f"Couldn't work out what is due: {due['error']}")
    elif due.get("due"):
        lines.append("A dream is due: a reflection ran since the last dream. Run /dream in the Claude pane (s).")
    else:
        lines.append("No dream is due. One is due after a reflection run newer than the last dream, at most one a "
                     "day; /dream runs one any time.")
    if due.get("waiting"):
        lines.append(f"Waiting: the dream from {due['waiting']} has picks not synced yet (`{SYNC}`).")
    try:
        since = len(review.dreams_since_last_review(project_dir))
        need = int(settings.get("review_min", 4))
        state = "due" if review.review_due(project_dir, settings) else "not due"
        lines.append(f"Dream review: {state} ({since} of {need} dreams since the last review).")
    except Exception:
        pass
    lines += ["", "Experiment (`daedalus dream log`)"]
    try:
        lines += report.summary(project_dir)
    except Exception as e:
        lines.append(f"Couldn't read the dream log: {e}")
    return lines, due


# ---------- the screen ----------

class DreamScreen(Screen):
    """The Dream screen: dreams · picks · themes · due. Read-only."""

    BINDINGS = [
        ("escape", "back", "back"), ("question_mark", "explain", "explain"), ("s", "send", "send to Claude"),
        ("right", "tab(1)", "next tab"), ("left", "tab(-1)", "previous tab"),
        ("l", "tab(1)", "next tab"), ("h", "tab(-1)", "previous tab"),
        ("1", "show('dreams')", "Dreams"), ("2", "show('picks')", "Picks"), ("3", "show('themes')", "Themes"),
        ("4", "show('due')", "Due"),
    ]
    DEFAULT_CSS = """
    DreamScreen { layout: vertical; }
    DreamScreen #dream-title { height: 1; background: $boost; padding: 0 1; text-style: bold; }
    DreamScreen #dream-tabs { height: 2; padding: 0 1; border-bottom: solid $panel; }
    DreamScreen #dream-doc { height: 1fr; padding: 0 1; }
    DreamScreen #dream-split { height: 1fr; }
    DreamScreen #dream-list { width: 40; border-right: solid $panel; }
    DreamScreen #dream-right { width: 1fr; }
    DreamScreen #dream-detail { height: 1fr; padding: 0 1; }
    DreamScreen #dream-keys { height: 2; padding: 0 1; color: $text-muted; border-top: solid $panel; }
    """

    def __init__(self, app, tab: str = "dreams"):
        super().__init__()
        self.shell = app
        self.project_dir = Path(app.project_dir)
        self.tab = tab
        self.on = False
        self.dreams: list[dict] = []
        self.picks: list[Pick] = []
        self.themes: list[dict] = []
        self.due: dict = {}
        self.due_text: list[str] = []

    def compose(self):
        yield Static("Dream", id="dream-title", markup=False)
        yield Static("", id="dream-tabs")
        with VerticalScroll(id="dream-doc"):
            yield Static("", id="dream-doc-body", markup=False)
        with Horizontal(id="dream-split"):
            yield OptionList(id="dream-list", markup=False)
            with Vertical(id="dream-right"):
                yield SpeculativeLabel(id="dream-label")
                with VerticalScroll(id="dream-detail"):
                    yield Markdown("", id="dream-detail-md")
                    yield Static("", id="dream-detail-text", markup=False)
                yield Static("", id="dream-keys", markup=False)
        yield KeyBar()

    def on_mount(self) -> None:
        self.query_one(KeyBar).show_dashboard("←/→ tab · ↑/↓ item · s send to Claude · ? explain · esc back")
        self.refresh_state(getattr(self.shell, "state", None))
        self.query_one("#dream-list" if self.on and self.tab != "due" else "#dream-doc").focus()

    # ----- state -----

    def refresh_state(self, state=None) -> None:
        self.on = enabled(self.project_dir)
        if self.on:
            self.dreams = dream_rows(self.project_dir)
            self.picks = all_picks(self.project_dir)
            self.themes = themes(self.project_dir)
            self.due_text, self.due = due_lines(self.project_dir)
        self._redraw()

    def _redraw(self) -> None:
        width = max(self.size.width - 2, 40)
        right = "speculative · esc back"
        self.query_one("#dream-title", Static).update("Dream" + " " * max(2, width - 5 - len(right)) + right)
        tabs, doc, split = self.query_one("#dream-tabs", Static), self.query_one("#dream-doc"), \
            self.query_one("#dream-split")
        if not self.on:
            tabs.styles.display = split.styles.display = "none"
            doc.styles.display = "block"
            self.query_one("#dream-doc-body", Static).update(OFF)
            return
        tabs.styles.display = "block"
        tabs.update(" · ".join(f"[reverse] {lab} [/reverse]" if key == self.tab else lab for key, lab in TABS))
        if self.tab == "due":
            split.styles.display = "none"
            doc.styles.display = "block"
            keys = "s ask Claude to run /dream" if self.due.get("due") else (
                f"s ask Claude to run {SYNC}" if self._unsynced() else "? explain")
            self.query_one("#dream-doc-body", Static).update("\n".join(self.due_text + ["", keys]))
            return
        doc.styles.display = "none"
        split.styles.display = "block"
        olist = self.query_one("#dream-list", OptionList)
        keep = olist.highlighted
        olist.clear_options()
        labels = self._labels()
        if not labels:
            olist.add_option(Option("(none yet)", disabled=True))
            self._detail(None, EMPTY[self.tab])
            self.query_one("#dream-keys", Static).update("s send to Claude · ? explain")
            return
        olist.add_options([Option(text, id=str(i)) for i, text in enumerate(labels)])
        olist.highlighted = keep if keep is not None and keep < len(labels) else 0
        self._show_detail()

    def _labels(self) -> list[str]:
        if self.tab == "dreams":
            return [f"{d['id']:<13} {d['status']:<8}" + (f" {d['picks']} picks" if d["picks"] else "")
                    for d in self.dreams]
        if self.tab == "picks":
            return [f"{p.id:<17} {p.status}" for p in self.picks]
        return [f"{t['id']:<4} {theme_state(t)[:12]:<12} {int(t.get('dreams') or 0)} dreams · "
                f"{int(t.get('distinct_top_seeds') or 0)} sets" for t in self.themes]

    def _unsynced(self) -> list[Pick]:
        return [p for p in self.picks if p.status == "not synced yet"]

    def _index(self) -> Optional[int]:
        idx = self.query_one("#dream-list", OptionList).highlighted
        n = {"dreams": len(self.dreams), "picks": len(self.picks), "themes": len(self.themes)}.get(self.tab, 0)
        return idx if idx is not None and idx < n else None

    def _detail(self, markdown: Optional[str], text: str = "") -> None:
        """Dream text is Markdown (no Rich markup); anything else is plain text."""
        md, plain = self.query_one("#dream-detail-md", Markdown), self.query_one("#dream-detail-text", Static)
        md.styles.display = "block" if markdown is not None else "none"
        plain.styles.display = "none" if markdown is not None else "block"
        md.update(markdown or "")
        plain.update(text)

    def _show_detail(self) -> None:
        from ...dreams import store

        idx = self._index()
        if idx is None:
            return
        keys = "s send to Claude · ? explain"
        if self.tab == "dreams":
            try:
                self._detail(store.show(self.project_dir, self.dreams[idx]["id"]))
            except (OSError, store.DreamError) as e:
                self._detail(None, f"Couldn't read this dream: {e}")
        elif self.tab == "picks":
            p = self.picks[idx]
            item = f"{p.item_id} · {p.status}" + (f" ({p.item_status})" if p.item_status else "")
            self._detail(f"**{p.id}** · {p.title}\n\nroadmap: `{item}`\n\n{p.text}")
            if p.status == "not synced yet":
                keys = f"s ask Claude to run {SYNC} · ? explain"
        else:
            t = self.themes[idx]
            lines = [f"{t['id']} · {t.get('title', '')}", theme_state(t),
                     f"in {int(t.get('dreams') or 0)} dreams, {int(t.get('distinct_top_seeds') or 0)} distinct "
                     "seed sets", "", str(t.get("summary") or ""), "",
                     "ideas: " + ", ".join(map(str, t.get("ideas") or [])),
                     f"last review: {t.get('last_review') or '-'}", "",
                     "How often an idea came back says nothing about whether it's right."]
            self._detail(None, "\n".join(lines))
        self.query_one("#dream-keys", Static).update(keys)

    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        self._show_detail()

    # ----- actions -----

    def action_show(self, tab: str) -> None:
        if tab != self.tab:
            self.query_one("#dream-list", OptionList).highlighted = None  # a new tab starts at its first row
        self.tab = tab
        self._redraw()
        target = "#dream-list" if self.on and tab != "due" else "#dream-doc"
        self.query_one(target).focus()

    def action_tab(self, step: int) -> None:
        if not self.on:
            return
        keys = [k for k, _ in TABS]
        self.action_show(keys[(keys.index(self.tab) + step) % len(keys)])

    def action_back(self) -> None:
        self.app.pop_screen()

    def action_explain(self) -> None:
        self.app.push_screen(ExplainCard("Dream"))

    def send_prompt(self) -> Optional[tuple[str, str]]:
        """What `s` hands Claude: a due dream first, then unsynced picks, then the selection."""
        if not self.on:
            return ("Dreaming", "Explain what dreaming (edict 0013) would do in this project and help me decide "
                                "whether to turn it on (`daedalus config dream.enabled true`).")
        if self.due.get("due"):
            return ("Dream due", "A dream is due. Run /dream.")
        idx = self._index() if self.tab != "due" else None
        if self.tab == "picks" and idx is not None and self.picks[idx].status != "not synced yet":
            p = self.picks[idx]
            return (f"Pick {p.id}", f"Pick {p.id} (\"{p.title}\") is speculative, from a dream "
                                    f"(`daedalus dream show {p.dream}`). It is {p.status}. Tell me what building it "
                                    "would take; don't treat it as a plan.")
        unsynced = self._unsynced()
        if unsynced:
            return ("Unsynced dream picks", f"Run `{SYNC}` to bring {len(unsynced)} dream pick(s) in as roadmap "
                                            "proposals, then tell me what came in so I can apply or drop each.")
        if self.tab == "dreams" and idx is not None:
            d = self.dreams[idx]["id"]
            return (f"Dream {d}", f"Read `daedalus dream show {d}` and talk its picks through with me. It's "
                                  "speculative: not a proposal and not evidence.")
        if self.tab == "themes" and idx is not None:
            t = self.themes[idx]
            return (f"Theme {t['id']}", f"Dream theme {t['id']} (\"{t.get('title', '')}\") came back in "
                                        f"{t.get('dreams')} dreams. Read `daedalus dream review show` and tell me "
                                        "whether anything in the plan already covers it.")
        return None

    def action_send(self) -> None:
        found = self.send_prompt()
        if found is None:
            self.notify("Nothing to hand over: no dream is due and every pick is synced.", markup=False)
            return
        self.shell.ask_to_send(*found)
