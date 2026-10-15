"""
Reflection (edict 0010, shown by edict 0012): docs/design/tui/reflection.oph.

Five tabs: what's due, the rendered reports, the user model, the self model, and the A/B experiment. It
reads through the same library functions as `daedalus reflect`, and writes only what edict 0012's
reflection amendment allows, each through the function its `daedalus reflect` command calls:

- edit an entry: `models.user_edit` (reflect model <m> edit);
- mark stable or let it decay again: `models.set_stable` (reflect model <m> stable [--off]);
- forget a user entry: `models.forget` with `reflection.forget`, then `pending.forget_queued`
  (reflect model user forget);
- delete an entry: `models.delete` (reflect model <m> delete);
- digest now: `digest.digest_project` (reflect digest);
- export the experiment log: `explog.export` (reflect log export).

Forget and delete confirm in a modal first. Aspirations are Daedalus's own words: they can be deleted
here, never edited or made stable. Applying proposals (stances one at a time) happens in Needs you, not
here; running a reflection is Claude's job, so `s` hands it over.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any, Optional

from rich.markdown import Markdown
from textual import work
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen, Screen
from textual.widgets import Input, OptionList, Static
from textual.widgets.option_list import Option

from ..widgets import ExplainCard, KeyBar
from ..widgets.confirm import ConfirmModal  # noqa: F401  (the shared one; tests import it from here)

TABS = ("due", "reports", "user", "self", "experiment")
TAB_LABELS = {"due": "Due", "reports": "Reports", "user": "User model", "self": "Self model",
              "experiment": "Experiment"}
TAB_CARDS = {"due": "Due", "reports": "Reflection", "user": "User model", "self": "Self model",
             "experiment": "A/B experiment"}
SCOPES = ("private", "work", "anywhere", "personal", "any")  # as `reflect model edit --scope` takes them


# ---------- reading (the same library functions as `daedalus reflect`) ----------

def reflection_settings(project_dir: Path) -> dict:
    from ...config import get_project_settings

    try:
        return get_project_settings(project_dir, "reflection")
    except Exception:
        from dataclasses import asdict

        from ...config import ReflectionConfig

        return asdict(ReflectionConfig())


def runner_label() -> str:
    try:
        from ...reflection.runners import resolve_runner

        r = resolve_runner()
        return r.effective
    except Exception:
        return "inhale"


def due_rows(project_dir: Path, settings: dict, today: Optional[date] = None) -> list[dict]:
    """What's due, read-only (`reflect due` also caches the list in due.json; the TUI doesn't write it)."""
    from ...reflection import due as dm
    from ...reflection.digest import load_digests

    try:
        due = dm.compute_due(load_digests(project_dir), dm.load_state(project_dir), today or date.today(),
                             int(settings.get("activity_threshold", 20)))
    except Exception:
        return []
    rows = []
    for d in due:
        rows.append({"key": f"{d.level}:{d.period}", "level": d.level, "period": d.period, "state": "due", "due": d})
        for absorbed in d.absorbs:
            rows.append({"key": f"in:{absorbed}", "level": "", "period": absorbed,
                         "state": f"rolled into {d.period}", "due": d})
    return rows


def undigested_warning(project_dir: Path, settings: dict) -> list[tuple[str, int]]:
    """Sessions Claude Code will delete before they're digested (doctor's warning, shown here too)."""
    try:
        from ...reflection.tick import undigested_near_cleanup

        return undigested_near_cleanup(project_dir, int(settings.get("cleanup_warning_days", 7)))
    except Exception:
        return []


def report_rows(project_dir: Path) -> list[dict]:
    """Rendered reports, newest first. `reflect render` writes the .md only after Momus has ruled."""
    from ...reflection.paths import reports_dir

    folder = reports_dir(project_dir)
    files = sorted(folder.glob("*.md"), key=lambda f: f.stat().st_mtime, reverse=True) if folder.is_dir() else []
    rows = []
    for f in files:
        try:
            text = f.read_text(encoding="utf-8")
        except OSError:
            continue
        first = text.splitlines()[0].lstrip("# ").strip() if text else f.stem
        title = first.split(":", 1)[1].strip() if first.lower().startswith("reflection:") else first
        rows.append({"key": f.name, "title": title or f.stem, "path": f, "text": text,
                     "proposals": count_proposals(text)})
    return rows


def count_proposals(markdown: str) -> int:
    section = markdown.split("## Proposals", 1)[1] if "## Proposals" in markdown else ""
    section = section.split("\n## ", 1)[0]
    return sum(1 for line in section.splitlines() if line.startswith("- **"))


def model_rows(model: str, settings: dict, today: Optional[date] = None) -> tuple[list[dict], Optional[str]]:
    """(rows, error). Each row: the entry, its effective confidence, and its open dissents."""
    from ...reflection import models as m

    try:
        data = m.load(model)
    except m.ModelError as e:
        return [], str(e)
    hl = m.half_life(model, settings)
    today = today or date.today()
    dissents: dict[str, list] = {}
    if model == "self":
        for d in m.load_dissents(open_only=True):
            dissents.setdefault(d.get("entry_id"), []).append(d)
    rows = []
    for e in data.get("entries", []):
        rows.append({"key": e.get("id"), "entry": e, "confidence": m.effective_confidence(e, today, hl),
                     "dissents": dissents.get(e.get("id"), [])})
    return rows, None


def experiment_lines(project_dir: Path) -> list[str]:
    from ...config import load_config
    from ...reflection import explog
    from ...reflection.arms import current_session_id, load_arms

    mode = load_config().reflection.model_summary
    meaning = {"ab": "A/B test", "on": "always shown", "off": "never shown"}.get(mode, mode)
    lines = [f"Model summary at inhale: {meaning} (reflection.model_summary = {mode})", ""]
    arms = load_arms(project_dir)
    sid = current_session_id()
    if sid and sid in arms:
        entry = arms[sid]
        seed = f" · seed {entry['seed']}" if "seed" in entry else ""
        lines.append(f"This session's arm: {entry.get('arm')}{seed}")
    elif sid:
        lines.append("This session's arm: not drawn yet (inhale draws it)")
    else:
        lines.append("This session's arm: none (this TUI isn't inside a Claude Code session)")
    counts: dict[str, int] = {}
    for entry in arms.values():
        if isinstance(entry, dict):
            counts[entry.get("arm", "none")] = counts.get(entry.get("arm", "none"), 0) + 1
    lines.append("Sessions so far: " + (" · ".join(f"{n} {arm}" for arm, n in sorted(counts.items())) or "none"))
    lines += ["", "The log records runs, resolutions, arms and model changes (counts and IDs only):", ""]
    try:
        lines += explog.summary(explog.load(project_dir))
    except Exception as e:
        lines.append(f"(can't read the log: {e})")
    return lines


def entry_row(model: str, row: dict) -> str:
    e = row["entry"]
    text = " ".join(str(e.get("observation", "")).split())
    status = e.get("status", "active")
    if e.get("kind") == "aspiration":
        label = f"✦ aspiration: {text}"
        tag = ""
    else:
        label = text
        tag = "stable" if e.get("stable") else f"{row['confidence']:.1f}"
    if status != "active":
        tag = f"[{status}]"
    flag = "⚑ " if row["dissents"] else ""
    width = 30
    label = (flag + label)
    label = label if len(label) <= width else label[:width - 1] + "…"
    return f"{label:<{width}} {tag:>6}"


def entry_detail(model: str, row: dict, today: Optional[date] = None) -> str:
    e = row["entry"]
    today = today or date.today()
    lines = [str(e.get("observation", "")), ""]
    if e.get("kind") == "aspiration":
        lines.append(f"aspiration · written by Daedalus ({e.get('period', '')}) · binds nothing")
    else:
        parts = [p for p in (e.get("kind"), e.get("label")) if p]
        parts.append(f"confidence {row['confidence']:.2f}")
        parts.append("stable" if e.get("stable") else "decays")
        stamp = e.get("last_affirmed") or e.get("first_noticed")
        if stamp:
            try:
                ago = (today - date.fromisoformat(stamp[:10])).days
                parts.append(f"affirmed {ago}d ago" if ago else "affirmed today")
            except ValueError:
                pass
        lines.append(" · ".join(parts))
    from ...reflection.models import canon_scope

    lines.append(f"id {e.get('id')} · scope {canon_scope(e.get('scope'))}"
                 + (f" · category {e['category']}" if e.get("category") else "")
                 + (f" · {e['status']}" if e.get("status", "active") != "active" else ""))
    sessions = sorted({ev.get("session", "")[:8] for ev in e.get("evidence", []) if isinstance(ev, dict) and ev.get("session")})
    if sessions:
        lines.append("from sessions: " + ", ".join(sessions))
    for d in row["dissents"]:
        lines += ["", f"⚑ Dissent {d.get('id')} ({d.get('agent')}, {d.get('filed')}): \"{d.get('objection')}\"",
                  "Dissents block nothing; they're shown with the entry."]
    return "\n".join(lines)


def history_text(model: str, entry_id: str) -> str:
    from ...reflection.models import load_history

    recs = load_history(model=model, entry_id=entry_id)
    if not recs:
        return f"No history for {entry_id}."
    lines = [f"History of {entry_id} (models/history.jsonl):", ""]
    for rec in recs:
        after, before = rec.get("after") or {}, rec.get("before") or {}
        text = after.get("observation") or before.get("observation") or rec.get("note", "")
        lines.append(f"{rec.get('at', '')[:10]} {rec.get('kind')} by {rec.get('by')}: {text}")
    return "\n".join(lines)


# ---------- modals ----------

class EditEntry(ModalScreen):
    """Edit a model entry's observation, confidence, scope and category. Returns only what changed."""

    BINDINGS = [("escape", "cancel", "cancel")]
    DEFAULT_CSS = """
    EditEntry { align: center middle; }
    EditEntry > Vertical { width: 72; height: auto; border: round $accent; background: $surface; padding: 1 2; }
    EditEntry Input { margin-bottom: 1; }
    EditEntry #edit-error { color: $error; }
    EditEntry .hint { color: $text-muted; }
    """

    FIELDS = ("observation", "confidence", "scope", "category")

    def __init__(self, model: str, entry: dict):
        super().__init__()
        self.model, self.entry = model, entry

    def compose(self):
        with Vertical():
            yield Static(f"Edit {self.entry.get('id')} ({self.model} model)", markup=False)
            for name in self.FIELDS:
                value = self.entry.get(name)
                yield Static(name, classes="hint")
                yield Input("" if value is None else str(value), id=f"edit-{name}")
            yield Static("", id="edit-error", markup=False)
            yield Static("enter save · esc cancel · every change goes to history.jsonl", classes="hint")

    def on_mount(self) -> None:
        self.query_one("#edit-observation", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        changes, error = self.changes()
        if error:
            self.query_one("#edit-error", Static).update(error)
            return
        self.dismiss(changes)

    def changes(self) -> tuple[dict, Optional[str]]:
        out: dict[str, Any] = {}
        for name in self.FIELDS:
            raw = self.query_one(f"#edit-{name}", Input).value.strip()
            old = self.entry.get(name)
            if raw == ("" if old is None else str(old)):
                continue
            if name == "confidence":
                try:
                    out[name] = float(raw)
                except ValueError:
                    return {}, "confidence is a number, e.g. 0.6"
            elif name == "scope":
                if raw not in SCOPES:
                    return {}, "scope is private, work or anywhere"
                out[name] = raw
            elif name == "observation" and not raw:
                return {}, "an observation can't be empty; delete the entry instead"
            else:
                out[name] = raw
        return out, None

    def action_cancel(self) -> None:
        self.dismiss(None)


class ExportLog(ModalScreen):
    """Where to export the experiment log. Relative paths are from the project."""

    BINDINGS = [("escape", "cancel", "cancel")]
    DEFAULT_CSS = """
    ExportLog { align: center middle; }
    ExportLog > Vertical { width: 72; height: auto; border: round $accent; background: $surface; padding: 1 2; }
    ExportLog .hint { color: $text-muted; }
    """

    def compose(self):
        with Vertical():
            yield Static("Export the experiment log to:")
            yield Input("reflection-experiment-log.jsonl", id="export-path")
            yield Static("A copy, wherever you choose; committing it is your call. enter export · esc cancel",
                         classes="hint")

    def on_mount(self) -> None:
        self.query_one(Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        value = event.value.strip()
        self.dismiss(value or None)

    def action_cancel(self) -> None:
        self.dismiss(None)


# ---------- the screen ----------

class ReflectionScreen(Screen):
    """Reflection: due, reports, user model, self model, experiment (reflection.oph)."""

    BINDINGS = [
        ("escape", "back", "back"), ("question_mark", "explain", "explain"),
        ("1", "tab('due')", "Due"), ("2", "tab('reports')", "Reports"), ("3", "tab('user')", "User model"),
        ("4", "tab('self')", "Self model"), ("5", "tab('experiment')", "Experiment"),
        ("left", "step(-1)", "previous tab"), ("right", "step(1)", "next tab"),
        ("d", "digest", "digest now"), ("s", "send", "send to Claude"), ("e", "edit_or_export", "edit"),
        ("S", "stable", "stable"), ("f", "forget", "forget"), ("x", "delete", "delete"),
        ("h", "history", "history"), ("p", "proposals", "proposals"),
    ]
    DEFAULT_CSS = """
    ReflectionScreen { layout: vertical; }
    ReflectionScreen #refl-header { height: 1; background: $boost; padding: 0 1; }
    ReflectionScreen #refl-tabs { height: 1; padding: 0 1; color: $text-muted; }
    ReflectionScreen #refl-main { height: 1fr; }
    ReflectionScreen #refl-list { width: 40; border: round $panel; }
    ReflectionScreen #refl-list:focus { border: round $accent; }
    ReflectionScreen #refl-right { width: 1fr; border: round $panel; }
    ReflectionScreen #refl-detail-scroll { height: 1fr; padding: 0 1; }
    ReflectionScreen #refl-actions { height: auto; border-top: solid $panel; padding: 0 1; color: $text-muted; }
    ReflectionScreen #refl-warning { color: $warning; padding: 0 1; }
    """

    def __init__(self, app=None):
        super().__init__()
        self.shell = app
        self.tab = "due"
        self.rows: list[dict] = []
        self.history_for: Optional[str] = None
        self.warning: list = []

    @property
    def project_dir(self) -> Path:
        return Path(getattr(self.shell or self.app, "project_dir", Path.cwd()))

    def compose(self):
        yield Static("", id="refl-header", markup=False)
        yield Static("", id="refl-tabs", markup=False)
        with Horizontal(id="refl-main"):
            yield OptionList(id="refl-list", markup=False)
            with Vertical(id="refl-right"):
                with VerticalScroll(id="refl-detail-scroll"):
                    yield Static("", id="refl-detail", markup=False)
                yield Static("", id="refl-warning", markup=False)
                yield Static("", id="refl-actions", markup=False)
        yield KeyBar()

    def on_mount(self) -> None:
        self.settings = reflection_settings(self.project_dir)
        self.warning = undigested_warning(self.project_dir, self.settings)
        self.query_one(KeyBar).show_dashboard("1-5 or ←→ tab · ? explain · s send to Claude · esc back")
        self._load()
        self.query_one(OptionList).focus()

    # ----- state -----

    def refresh_state(self, state) -> None:
        """Called by the app's file watcher."""
        self._load()

    def _load(self) -> None:
        self.settings = reflection_settings(self.project_dir)
        width = self.size.width or 100
        self.query_one("#refl-header", Static).update(
            "Reflection" + " " * max(2, width - 34) + f"runner: {runner_label()} · esc back")
        self.query_one("#refl-tabs", Static).update(
            " · ".join(f"[{TAB_LABELS[t]}]" if t == self.tab else TAB_LABELS[t] for t in TABS))
        keep = self._selected_key()
        if self.tab == "due":
            self.rows = due_rows(self.project_dir, self.settings)
        elif self.tab == "reports":
            self.rows = report_rows(self.project_dir)
        elif self.tab in ("user", "self"):
            self.rows, error = model_rows(self.tab, self.settings)
            if error:
                self.app.notify(error, severity="error", markup=False)
        else:
            self.rows = []
        listing = self.query_one(OptionList)
        listing.display = self.tab != "experiment"
        listing.clear_options()
        listing.add_options([Option(self._row_text(r), id=str(i)) for i, r in enumerate(self.rows)])
        if self.rows:
            index = next((i for i, r in enumerate(self.rows) if r["key"] == keep), 0)
            listing.highlighted = index
        self._show_detail()

    def _row_text(self, row: dict) -> str:
        if self.tab == "due":
            return f"{row['level']:<8} {row['period']:<10} {row['state']}"
        if self.tab == "reports":
            n = row["proposals"]
            return f"{row['title'][:24]:<24} {n} proposal{'s' if n != 1 else ''}"
        return entry_row(self.tab, row)

    def _selected(self) -> Optional[dict]:
        if not self.rows:
            return None
        index = self.query_one(OptionList).highlighted
        return self.rows[index] if index is not None and 0 <= index < len(self.rows) else None

    def _selected_key(self) -> Optional[str]:
        row = self._selected() if self.rows else None
        return row["key"] if row else None

    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        self.history_for = None
        self._show_detail()

    def _show_detail(self) -> None:
        detail = self.query_one("#refl-detail", Static)
        actions = self.query_one("#refl-actions", Static)
        warning = self.query_one("#refl-warning", Static)
        warning.update("")
        row = self._selected()
        if self.tab == "due":
            if self.warning:
                days = min(left for _, left in self.warning)
                warning.update(f"⚠ {len(self.warning)} session(s) undigested; Claude Code deletes them in {days}d. "
                               "Press d to digest now.")
            if row is None:
                detail.update("Nothing due.\n\nA reflection becomes due when a day, week or month that had sessions "
                              "ends. Sessions are digested by `daedalus reflect tick` (or d here); Claude runs the "
                              "reflection with /reflect.\n\nCLI: daedalus reflect due")
            else:
                d = row["due"]
                n = len(d.sessions)
                text = f"{d.level.capitalize()} {d.period} is due\n\n{n} session{'s' if n != 1 else ''}, " \
                       f"{d.tool_calls} tool calls ({d.start} to {d.end})."
                if d.absorbs:
                    text += f"\nSmall days and weeks roll up into it: {', '.join(d.absorbs)}."
                detail.update(text)
            actions.update("d digest now · s ask Claude to run /reflect")
        elif self.tab == "reports":
            if row is None:
                detail.update("No reports yet.\n\nA report appears here once a reflection has run, passed "
                              "`daedalus reflect check` and Momus has ruled on its proposals. Ask Claude to run "
                              "/reflect when one is due.\n\nLives in .daedalus/reflection/reports/")
                actions.update("")
            else:
                detail.update(Markdown(row["text"]))
                actions.update(f"{row['path'].name} · p its proposals (in Needs you) · s ask Claude about it")
        elif self.tab in ("user", "self"):
            if row is None:
                who = "you" if self.tab == "user" else "itself"
                detail.update(f"The {TAB_LABELS[self.tab].lower()} is empty.\n\nWhat Daedalus learns about {who} "
                              "arrives as reflection proposals; it's added here when you apply one.\n\n"
                              f"CLI: daedalus reflect model {self.tab}")
                actions.update("")
            else:
                if self.history_for == row["key"]:
                    detail.update(history_text(self.tab, row["key"]))
                else:
                    detail.update(entry_detail(self.tab, row))
                actions.update(self._model_actions(row) + "\nevery change is recorded in history.jsonl")
        else:
            detail.update("\n".join(experiment_lines(self.project_dir)))
            actions.update("e export the log · ? what is this experiment")

    def _model_actions(self, row: dict) -> str:
        if row["entry"].get("kind") == "aspiration":
            return "h history · x delete  (aspirations are Daedalus's to write: delete only)"
        keys = ["h history", "e edit", "S stable" if not row["entry"].get("stable") else "S let it decay"]
        if self.tab == "user":
            keys.append(f"f forget ({self.settings.get('forget', 'purge')})")
        keys.append("x delete")
        return " · ".join(keys)

    # ----- navigation -----

    def action_back(self) -> None:
        self.app.pop_screen()

    def action_tab(self, tab: str) -> None:
        self.tab, self.history_for = tab, None
        self._load()

    def action_step(self, delta: int) -> None:
        self.action_tab(TABS[(TABS.index(self.tab) + delta) % len(TABS)])

    def action_explain(self) -> None:
        self.app.push_screen(ExplainCard(TAB_CARDS[self.tab]))

    def action_history(self) -> None:
        row = self._model_row()
        if row:
            self.history_for = None if self.history_for == row["key"] else row["key"]
            self._show_detail()

    def action_proposals(self) -> None:
        if self.tab == "reports" and hasattr(self.app, "open_screen"):
            self.app.open_screen("needs")

    def action_send(self) -> None:
        row = self._selected()
        if self.tab == "due":
            what = f" ({', '.join(r['level'] + ' ' + r['period'] for r in self.rows if r['state'] == 'due')})" \
                if self.rows else ""
            source, prompt = "Reflection due", f"Run /reflect for the reflections due here{what}."
        elif self.tab == "reports" and row:
            source = f"Report {row['title']}"
            prompt = (f"Read the reflection report {row['path'].relative_to(self.project_dir)} and walk me through "
                      "its findings and proposals, one at a time.")
        elif self.tab in ("user", "self") and row:
            e = row["entry"]
            source = f"{TAB_LABELS[self.tab]} {e.get('id')}"
            prompt = (f"Look at {self.tab} model entry {e.get('id')} (\"{e.get('observation', '')}\") and its history "
                      f"(`daedalus reflect model {self.tab} --history {e.get('id')}`). Is it still accurate?")
        elif self.tab == "experiment":
            source, prompt = "Experiment", "Summarise the reflection experiment log (`daedalus reflect log`) for me."
        else:
            return
        if hasattr(self.app, "ask_to_send"):
            self.app.ask_to_send(source, prompt)

    # ----- writes (edict 0012's reflection amendment, through the reflect commands' functions) -----

    def _model_row(self) -> Optional[dict]:
        return self._selected() if self.tab in ("user", "self") else None

    @work(thread=True, exclusive=True, group="digest")
    def action_digest(self) -> None:
        """Digest now: `daedalus reflect digest`, through digest_project."""
        if self.tab != "due":
            return
        from ...reflection.digest import digest_project

        self.app.call_from_thread(self.app.notify, "Digesting this project's sessions…")
        try:
            result = digest_project(self.project_dir)
        except Exception as e:
            self.app.call_from_thread(self.app.notify, f"Digest failed: {e}", severity="error")
            return
        self.warning = undigested_warning(self.project_dir, self.settings)
        self.app.call_from_thread(self.app.notify, f"Digested {len(result['written'])} session(s); "
                                                   f"{len(result['unchanged'])} unchanged.")
        self.app.call_from_thread(self._load)

    def action_edit_or_export(self) -> None:
        if self.tab == "experiment":
            self.app.push_screen(ExportLog(), self._export)
            return
        row = self._model_row()
        if row is None:
            return
        if row["entry"].get("kind") == "aspiration":
            self.app.notify("An aspiration is Daedalus's own words: you can delete it, not edit it.", markup=False)
            return
        self.app.push_screen(EditEntry(self.tab, row["entry"]), lambda changes: self._edit(row, changes))

    def _edit(self, row: dict, changes: Optional[dict]) -> None:
        from ...reflection import models as m

        if not changes:
            return
        try:
            m.user_edit(self.tab, row["key"], changes)
        except m.ModelError as e:
            self.app.notify(str(e), severity="error", markup=False)
            return
        self.app.notify(f"Edited {row['key']}.", markup=False)
        self._load()

    def _export(self, dest: Optional[str]) -> None:
        from ...reflection import explog

        if not dest:
            return
        path = Path(dest).expanduser()
        if not path.is_absolute():
            path = self.project_dir / path
        try:
            out = explog.export(self.project_dir, path)
        except OSError as e:
            self.app.notify(f"Couldn't export: {e}", severity="error", markup=False)
            return
        self.app.notify(f"Exported {len(explog.load(self.project_dir))} records to {out}", markup=False)

    def action_stable(self) -> None:
        from ...reflection import models as m

        row = self._model_row()
        if row is None:
            return
        if row["entry"].get("kind") == "aspiration":
            self.app.notify("An aspiration is Daedalus's own: it never decays, and you can only delete it.", markup=False)
            return
        on = not row["entry"].get("stable")
        try:
            m.set_stable(self.tab, row["key"], on)
        except m.ModelError as e:
            self.app.notify(str(e), severity="error", markup=False)
            return
        self.app.notify(f"{row['key']}: stable {'on' if on else 'off'}.", markup=False)
        self._load()

    def action_forget(self) -> None:
        row = self._model_row()
        if row is None:
            return
        if self.tab != "user":
            self.app.notify("Only the user model has forget; a self entry can be deleted, or disputed with a dissent.", markup=False)
            return
        from ...config import load_config

        mode = load_config().reflection.forget
        what = "its history is removed too" if mode == "purge" else "its history is kept"
        body = (f"\"{row['entry'].get('observation', '')}\"\n\nreflection.forget is {mode}: the entry goes, a "
                f"tombstone keeps it from being proposed again, and {what}. Queued proposals about it are dropped.")
        self.app.push_screen(ConfirmModal(f"Forget {row['key']}?", body), lambda ok: ok and self._forget(row, mode))

    def _forget(self, row: dict, mode: str) -> None:
        from ...reflection import models as m
        from ...reflection.pending import forget_queued

        try:
            entry = m.forget(row["key"], mode)
        except m.ModelError as e:
            self.app.notify(str(e), severity="error", markup=False)
            return
        dropped = forget_queued(self.project_dir, entry)
        self.app.notify(f"Forgot {row['key']} ({mode})." + (f" Dropped {dropped} queued proposal(s) about it."
                                                             if dropped else ""), markup=False)
        self._load()

    def action_delete(self) -> None:
        row = self._model_row()
        if row is None:
            return
        body = (f"\"{row['entry'].get('observation', '')}\"\n\nThe entry goes from the {self.tab} model. A tombstone "
                "keeps it from being proposed again; its history stays.")
        self.app.push_screen(ConfirmModal(f"Delete {row['key']}?", body), lambda ok: ok and self._delete(row))

    def _delete(self, row: dict) -> None:
        from ...reflection import models as m

        try:
            m.delete(self.tab, row["key"])
        except m.ModelError as e:
            self.app.notify(str(e), severity="error", markup=False)
            return
        self.app.notify(f"Deleted {row['key']}.", markup=False)
        self._load()
