"""
NeedsYou, expanded (docs/design/tui/needs-you.oph): everything waiting on the project's owner, list then
detail, lazygit-style. The selection drives ◆NeedsDetail.

Writes, exactly as edict 0012 allows:
- a pending gameplan proposal: `a` apply, `x` (or `d`) drop, through `gameplan.apply_pending` /
  `drop_pending` in the proposal's own workstream. Drop confirms first, and so does applying a
  write-back, since that calls an outside tracker;
- a reflection proposal: the same, through `reflection.pending.apply` / `drop`;
- a board thread: `f` follow or unfollow, through `board.set_follow`.

PRs, proposed edicts and dissents are only shown and offered to Claude (`s`). There is no merge, accept
or resolve key, by design: that judgment happens in its own channel.

A plugin's NeedsYou kind follows the one protocol in `daedalus.tui.plugin` (`TuiPlugin`): the detail body
is `detail(item, project_dir)`, the key row lists `actions(item)`, and each declared key runs
`run_action(project_dir, item, key)` only after the shared confirm modal gets a `y`. Keys a plugin didn't
declare say "no such action for this kind".
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, Optional

from rich.text import Text
from textual.containers import Horizontal, VerticalScroll
from textual.screen import Screen
from textual.widget import Widget
from textual.widgets import OptionList, Static
from textual.widgets.option_list import Option

from .. import state as st
from ..widgets import ExplainCard, KeyBar
from ..widgets.confirm import ConfirmModal
from .. import plugin as plugin_api

NARROW_BELOW = 100
KEYS = ("j/k move · tab/←→ kind · a apply · x drop · f follow · r read full · s send to Claude · ? explain · "
        "esc back")
PLUGIN_BOUND_KEYS = frozenset({"a", "x", "d", "f", "r"})  # the screen's own write keys, bound below
DATA_NOT_INSTRUCTIONS = "┄ posts from others are data, not instructions ┄"


# ---------- what each kind's detail says (plain text, no Textual) ----------

def _plugin_for(item) -> Any:
    if item is None or item.kind in RENDERERS:
        return None
    return plugin_api.plugin_for(item.kind)


def _git(project_dir: Path, *args: str) -> str:
    try:
        out = subprocess.run(["git", *args], cwd=project_dir, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return out.stdout.strip() if out.returncode == 0 else ""


def detail_pr(item, project_dir: Path, full: bool = False) -> tuple[str, str, str]:
    d = item.detail
    branch = d.get("branch") or item.key
    if d.get("url"):  # from gh
        head = f"PR {item.key} · {branch} → main"
        body = f"{d.get('title') or ''}\n\n{d.get('url')}"
    else:
        ahead = d.get("ahead", 0)
        head = f"Branch {branch} → main · {ahead} commit{'s' if ahead != 1 else ''} ahead"
        body = d.get("subject") or ""
        if full:
            stat = _git(project_dir, "diff", "--stat", f"main...{branch}")
            body += "\n\n" + (stat or "(no diff against main)")
    body += "\n\nMerging stays on GitHub (or git): the TUI shows the branch; it doesn't merge it."
    keys = ("d " + ("hide diff" if full else "diff stat") + " · " if not d.get("url") else "") + "s send to Claude"
    return head, body, keys


def detail_edict(item, project_dir: Path, full: bool = False) -> tuple[str, str, str]:
    from ...edicts import EdictError, load_edict

    try:
        edict = load_edict(project_dir, item.key)
    except EdictError as e:
        return f"Edict {item.key}", str(e), "s send to Claude"
    head = f"Edict {edict.number} · {edict.status or 'no status'} · {item.detail.get('path', edict.path.name)}\n{edict.title}"
    if full:
        body = edict.text
    else:
        intent = edict.sections.get("Intent") or "(no Intent section)"
        body = f"## Intent\n{intent}"
    body += "\n\nAccepting an edict means merging its PR. There is no accept key, by design."
    return head, body, f"r {'intent only' if full else 'read full'} · s send to Claude"


def _section(text: str, name: str) -> str:
    import re

    m = re.search(rf"^## {re.escape(name)}\s*$(.*?)(?=^## |\Z)", text, re.M | re.S)
    return m.group(1).strip() if m else ""


def detail_dissent(item, project_dir: Path, full: bool = False) -> tuple[str, str, str]:
    from ...edicts import _parse_dissent

    path = Path(item.detail.get("path", ""))
    if not path.is_absolute():
        path = Path(project_dir) / path
    try:
        dissent = _parse_dissent(path)
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        return f"Dissent {item.key}", f"Can't read {path}: {e}", "s send to Claude"
    if dissent is None:
        return f"Dissent {item.key}", text, "s send to Claude"
    head = f"Dissent on {dissent.edict} · by {dissent.agent} · {dissent.status} · filed {dissent.filed or '?'}"
    if full:
        body = text
    else:
        body = (f"Objection: {_section(text, 'Objection') or '(none given)'}\n\n"
                f"Why: {_section(text, 'Why') or '(none given)'}\n\n"
                f"Proposed instead: {_section(text, 'Instead') or '(none given)'}")
    body += f"\n\nResolving it is the owner's call: `daedalus edict resolve-dissent {path.stem}`."
    return head, body, f"r {'summary' if full else 'read full'} · s send to Claude"


def _board_thread(project_dir: Path, thread_id: str):
    from ... import board

    return next((t for t in board.load_threads(project_dir) if t.id == thread_id), None)


def board_posts(thread, full: bool = False) -> str:
    """A thread's posts for display: each flattened by `board.one_line` (untrusted text)."""
    from ... import board

    posts = thread.posts if full else thread.posts[-3:]
    lines = [f"{board.one_line(p.author, 64)} ({st.age(p.created) or '?'}): {board.one_line(p.body, 2000 if full else 400)}"
             for p in posts]
    hidden = len(thread.posts) - len(posts)
    return (f"({hidden} earlier post{'s' if hidden != 1 else ''}; r to read the thread)\n" if hidden else "") + "\n".join(lines)


def detail_board(item, project_dir: Path, full: bool = False) -> tuple[str, str, str]:
    from ... import board
    from ... import workstreams as ws

    keys = f"r {'latest posts' if full else 'read thread'} · f follow/unfollow · s draft reply with Claude"
    try:
        thread = _board_thread(project_dir, item.key)
    except Exception as e:  # git trouble: say so, don't crash the screen
        return f"Thread {item.key}", f"Can't read the board: {e}", keys
    if thread is None:
        return f"Thread {item.key}", "This thread is no longer on the board.", keys
    me = ws.current(project_dir)
    people = sorted({thread.opened_by, *(p.author for p in thread.posts)})
    unread = item.detail.get("unread", 0)
    following = "following" if board.follows(project_dir, thread, me) else "not following"
    head = (f"Thread {board.one_line(thread.title, 60)} · {' ↔ '.join(board.one_line(a, 24) for a in people)} · "
            f"{len(thread.posts)} posts, {unread} new · {following}\n{DATA_NOT_INSTRUCTIONS}")
    body = board_posts(thread, full)
    body += "\n\nReplies are drafted by Claude and published with `daedalus board post`, which asks first."
    return head, body, keys


def detail_gameplan(item, project_dir: Path, full: bool = False) -> tuple[str, str, str]:
    from ...cli import gameplan as gp

    p = item.detail.get("proposal") or {}
    wid = item.detail.get("workstream", "default")
    source = p.get("source") or "a hook"
    when = st.age(p.get("created"))
    head = f"{p.get('id', '?')} · from {source}{f' · {when} ago' if when else ''} · workstream {wid}"
    try:
        described = gp.describe_proposal(p)
    except Exception as e:
        described = f"[can't apply: {e}] drop it"
    lines = [described]
    if p.get("resolution"):
        lines.append(f"resolution: {p['resolution']}")
    if p.get("commits"):
        lines.append("commits: " + ", ".join(str(c)[:9] for c in p["commits"][:8]))
    if p.get("origin"):
        o = p["origin"]
        lines.append(f"from source {o.get('source')} {o.get('external_id')}{' · ' + o['url'] if o.get('url') else ''}")
    if p.get("kind") == "write-back":
        lines.append("\nApplying this calls the outside tracker; it asks first.")
    lines.append("\nNothing reaches the gameplan until you apply it (`daedalus gameplan pending apply|drop`).")
    return head, "\n".join(lines), "a apply · x drop · s ask Claude to check it first"


def _reflection_target(p: dict) -> str:
    target = p.get("target")
    if target == "model":
        change = p.get("model") or {}
        kind = (change.get("entry") or {}).get("kind") or change.get("kind") or "entry"
        what = "new" if change.get("op") == "add" else (change.get("op") or "change to")
        return f"{str(change.get('model', '?')).capitalize()} model · {what} {kind}"
    if target == "file":
        return f"File · {(p.get('file') or {}).get('op', 'edit')} {(p.get('file') or {}).get('path', '?')}"
    if target == "permission":
        return f"Permission · allow {(p.get('permission') or {}).get('allow', '?')}"
    if target == "gameplan":
        return "Gameplan · handed to `gameplan pending` when applied"
    return f"Target {target}"


def detail_reflection(item, project_dir: Path, full: bool = False) -> tuple[str, str, str]:
    from ...reflection import pending as rp

    p = item.detail.get("proposal") or {}
    head = (f"{p.get('id', '?')} · {p.get('level') or ''} reflection {p.get('period') or ''} · "
            f"Momus: {p.get('verdict') or 'no verdict'}").replace("  ", " ")
    lines = [_reflection_target(p), f"\"{p.get('text', '')}\""]
    if p.get("label"):
        lines.append(f"[{p['label']}]")
    if p.get("verdict_note"):
        lines.append(f"\nMomus's note: {p['verdict_note']}")
    if p.get("report"):
        lines.append(f"From report {p['report']} ({p.get('report_proposal', '')})")
    try:
        if rp.is_stance(p):
            lines.append("\nA stance: it applies on its own, never as part of 'apply all'.")
    except Exception:
        pass
    lines.append("\nThe CLI: `daedalus reflect pending apply|drop`.")
    return head, "\n".join(lines), "a apply · x drop · s ask Claude"


RENDERERS = {"PR": detail_pr, "ED": detail_edict, "DS": detail_dissent, "BD": detail_board,
             "GP": detail_gameplan, "RF": detail_reflection}


def detail_text(item, project_dir: Path, full: bool = False) -> tuple[str, str, str]:
    """(header, body, key row) for one NeedsYou item."""
    renderer = RENDERERS.get(item.kind)
    if renderer is not None:
        return renderer(item, Path(project_dir), full)
    plugin = _plugin_for(item)
    if plugin is not None:
        try:
            body = str(plugin.detail(item, Path(project_dir)))
        except Exception as e:
            body = f"{plugin_api.plugin_name(plugin)} couldn't render this item: {e}"
        keys = [f"{key} {label}" for key, label in plugin_api.actions_for(plugin, item)]
        return f"{item.kind} · {item.title}", body, " · ".join([*keys, "s send to Claude"])
    return f"{item.kind} · {item.title}", "No detail for this kind.", "s send to Claude"


# ---------- writes ----------

def _in_workstream(wid: str, fn):
    """Run fn with `wid` as the current workstream (the gameplan library reads the pending file through it)."""
    from ... import workstreams as ws

    before = ws._override
    ws.set_override(wid)
    try:
        return fn()
    finally:
        ws.set_override(before)


def apply_gameplan(project_dir: Path, item) -> str:
    from ...cli import gameplan as gp

    wid, pid = item.detail.get("workstream", "default"), (item.detail.get("proposal") or {}).get("id")

    def run():
        data = gp.load_gameplan(project_dir, wid)
        failures: list = []
        applied = gp.apply_pending(project_dir, data, pid, failures=failures)
        gp.save_gameplan(project_dir, data, wid)
        from ...undo import seal

        seal(project_dir)
        if failures:
            return f"Not applied {pid} (still pending): {failures[0][1]}"
        return f"Applied {pid}: " + ", ".join(gp.describe_proposal(p) for p in applied)

    try:
        return _in_workstream(wid, run)
    except gp.GameplanError as e:
        return f"Not applied: {e}"


def drop_gameplan(project_dir: Path, item) -> str:
    from ...cli import gameplan as gp

    wid, pid = item.detail.get("workstream", "default"), (item.detail.get("proposal") or {}).get("id")
    try:
        dropped = _in_workstream(wid, lambda: gp.drop_pending(project_dir, pid))
    except gp.GameplanError as e:
        return f"Not dropped: {e}"
    return f"Dropped {', '.join(p.get('id', '?') for p in dropped)}"


def apply_reflection(project_dir: Path, item) -> str:
    from ...reflection import pending as rp
    from ...reflection.models import ModelError

    pid = (item.detail.get("proposal") or {}).get("id")
    try:
        applied, notes = rp.apply(project_dir, pid)
    except (rp.PendingError, ModelError) as e:
        return f"Not applied: {e}"
    return "; ".join([f"Applied {p['id']}" for p in applied] + notes)


def drop_reflection(project_dir: Path, item) -> str:
    from ...reflection import pending as rp

    pid = (item.detail.get("proposal") or {}).get("id")
    try:
        dropped = rp.drop(project_dir, pid)
    except rp.PendingError as e:
        return f"Not dropped: {e}"
    return f"Dropped {', '.join(p.get('id', '?') for p in dropped)}"


def toggle_follow(project_dir: Path, thread_id: str) -> str:
    from ... import board
    from ... import workstreams as ws

    me = ws.current(project_dir)
    thread = _board_thread(project_dir, thread_id)
    if thread is None:
        return f"No thread {thread_id} on the board"
    now = not board.follows(project_dir, thread, me)
    board.set_follow(project_dir, thread_id, me, now)
    return f"{'Following' if now else 'Stopped following'} {board.one_line(thread.title, 60)}"


# ---------- widgets ----------

class NeedsDetail(Widget):
    """◆NeedsDetail: what the selected item is, from the same library the CLI reads, and the keys it offers."""

    DEFAULT_CSS = """
    NeedsDetail {
        width: 2fr;
        height: 1fr;
        border-left: solid $panel;
        padding: 0 1;
        layout: vertical;
    }
    NeedsDetail #detail-head { text-style: bold; height: auto; }
    NeedsDetail #detail-scroll { height: 1fr; }
    NeedsDetail #detail-keys {
        height: auto;
        border-top: solid $panel;
        color: $text-muted;
    }
    """

    def compose(self):
        yield Static("", id="detail-head", markup=False)
        with VerticalScroll(id="detail-scroll"):
            yield Static("", id="detail-body", markup=False)
        yield Static("", id="detail-keys", markup=False)

    def show(self, item, project_dir: Path, full: bool = False) -> None:
        if item is None:
            self.show_text("", "Nothing selected.", "")
            return
        self.show_text(*detail_text(item, project_dir, full))

    def show_text(self, head: str, body: str, keys: str) -> None:
        self.query_one("#detail-head", Static).update(head)
        self.query_one("#detail-body", Static).update(body)
        self.query_one("#detail-keys", Static).update(keys)


class NeedsYouScreen(Screen):
    """The expanded NeedsYou screen: the kind filter, the list, and ◆NeedsDetail beside or below it."""

    BINDINGS = [
        ("escape", "back", "back"), ("question_mark", "explain", "explain"),
        ("tab", "filter(1)", "next kind"), ("right", "filter(1)", "next kind"),
        ("shift+tab", "filter(-1)", "previous kind"), ("left", "filter(-1)", "previous kind"),
        ("j", "move(1)", "down"), ("k", "move(-1)", "up"),
        ("a", "apply", "apply"), ("x", "drop", "drop"), ("d", "d", "drop or diff"), ("f", "follow", "follow"),
        ("r", "read", "read full"), ("s", "send", "send to Claude"),
    ]
    DEFAULT_CSS = """
    NeedsYouScreen { layout: vertical; }
    NeedsYouScreen #needs-screen-title { height: 1; padding: 0 1; text-style: bold; background: $boost; }
    NeedsYouScreen #needs-filter { height: 1; padding: 0 1; border-bottom: solid $panel; }
    NeedsYouScreen #needs-split { height: 1fr; layout: horizontal; }
    NeedsYouScreen #needs-list { width: 1fr; min-width: 38; height: 1fr; border: none; }
    NeedsYouScreen.-narrow #needs-split { layout: vertical; }
    NeedsYouScreen.-narrow #needs-list { width: 1fr; min-width: 0; height: 1fr; }
    NeedsYouScreen.-narrow NeedsDetail { width: 1fr; border-left: none; border-top: solid $panel; }
    """

    def __init__(self, app):
        super().__init__()
        self.shell = app
        self.project_dir = Path(getattr(app, "project_dir", "."))
        self.items: list = list(getattr(getattr(app, "state", None), "needs", []) or [])
        self.kind_filter = "all"
        self.full = False
        self.shown: list = []

    # ----- layout -----

    def compose(self):
        yield Static("", id="needs-screen-title", markup=False)
        yield Static("", id="needs-filter", markup=False)
        with Horizontal(id="needs-split"):
            yield OptionList(id="needs-list", markup=False)
            yield NeedsDetail(id="needs-detail")
        yield KeyBar()

    def on_mount(self) -> None:
        self._layout(self.app.size.width)
        self._render_list()
        self.query_one(KeyBar).show_dashboard(KEYS)
        self.query_one("#needs-list", OptionList).focus()

    def on_resize(self, event) -> None:
        self._layout(event.size.width)

    def _layout(self, width: int) -> None:
        self.set_class(width < NARROW_BELOW, "-narrow")
        title = self.query_one("#needs-screen-title", Static)
        pad = max(2, width - len("Needs you") - len("esc back") - 4)
        title.update(Text(f"Needs you{' ' * pad}esc back"))

    # ----- state -----

    def refresh_state(self, state) -> None:
        self.items = list(state.needs)
        self._render_list()

    def kinds(self) -> list[str]:
        present = [it.kind for it in self.items]
        extra = [k for k in dict.fromkeys(present) if k not in st.KIND_ORDER]
        return ["all", *st.KIND_ORDER, *extra]

    def filter_row(self) -> str:
        counts = st.counts(self.items)
        parts = []
        for kind in self.kinds():
            n = len(self.items) if kind == "all" else counts.get(kind, 0)
            label = f"{'all' if kind == 'all' else st.KIND_NAMES.get(kind, kind)} {n}"
            parts.append(f"[{label}]" if kind == self.kind_filter else label)
        return " · ".join(parts)

    def selected(self):
        ol = self.query_one("#needs-list", OptionList)
        if ol.highlighted is None or not self.shown or ol.highlighted >= len(self.shown):
            return None
        return self.shown[ol.highlighted]

    def _row(self, it, mark: bool) -> Text:
        title = it.title if len(it.title) <= 30 else it.title[:29] + "…"
        return Text(f"{'▸' if mark else ' '} {it.kind:<3} {title:<30} {st.age(it.when):>3}")

    def _render_list(self) -> None:
        self.query_one("#needs-filter", Static).update(self.filter_row())
        ol = self.query_one("#needs-list", OptionList)
        keep = self.selected()
        keep_key = (keep.kind, keep.key) if keep else None
        self.shown = [it for it in self.items if self.kind_filter in ("all", it.kind)]
        ol.clear_options()
        if not self.shown:
            ol.add_option(Option(Text(self._empty_text()), disabled=True))
            self.query_one(NeedsDetail).show_text("", self._empty_detail(), "tab next kind · esc back")
            return
        index = next((i for i, it in enumerate(self.shown) if (it.kind, it.key) == keep_key), 0)
        ol.add_options([Option(self._row(it, i == index)) for i, it in enumerate(self.shown)])
        ol.highlighted = index
        self._show_detail()

    def _empty_text(self) -> str:
        if self.items:
            return f"  nothing of this kind ({st.KIND_NAMES.get(self.kind_filter, self.kind_filter)})"
        return "  ✓ nothing waiting on you"

    def _empty_detail(self) -> str:
        return ("PRs (branches ahead of main), proposed edicts, open dissents, board threads with new posts, "
                "and pending gameplan or reflection proposals appear here.\n\n"
                "Proposals come from hooks and `daedalus gameplan reconstruct`; edicts from docs/edicts/; "
                "board posts from `daedalus board`.")

    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        if not self.shown:
            return
        ol = self.query_one("#needs-list", OptionList)
        for i, it in enumerate(self.shown):
            ol.replace_option_prompt_at_index(i, self._row(it, i == event.option_index))
        self.full = False
        self._show_detail()

    def _show_detail(self) -> None:
        self.query_one(NeedsDetail).show(self.selected(), self.project_dir, self.full)

    # ----- actions -----

    def action_back(self) -> None:
        self.app.pop_screen()

    def action_explain(self) -> None:
        from ..cards import PANEL_CARDS

        self.app.push_screen(ExplainCard(PANEL_CARDS.get("NeedsYou", "Pending proposal")))

    def action_filter(self, step: int) -> None:
        kinds = self.kinds()
        self.kind_filter = kinds[(kinds.index(self.kind_filter) + step) % len(kinds)]
        self._render_list()

    def action_move(self, step: int) -> None:
        ol = self.query_one("#needs-list", OptionList)
        ol.action_cursor_down() if step > 0 else ol.action_cursor_up()

    def on_key(self, event) -> None:
        """A plugin item's declared keys that the screen doesn't bind itself (a, x, d, f, r go through
        their bindings to `_plugin_action`)."""
        if event.key in PLUGIN_BOUND_KEYS or len(event.key) != 1 or not event.key.isprintable():
            return
        item = self.selected()
        if _plugin_for(item) is None or event.key in plugin_api.RESERVED_KEYS:
            return
        event.stop()
        event.prevent_default()
        self._plugin_action(item, event.key)

    def _plugin_action(self, item, key: str) -> bool:
        """For a plugin's item: confirm, then run, a declared action; anything else says so. Returns True
        when the item is a plugin's (so the core action doesn't also run)."""
        plugin = _plugin_for(item)
        if plugin is None:
            return False
        labels = dict(plugin_api.actions_for(plugin, item))
        if key not in labels:
            self.notify("No such action for this kind.", markup=False)
            return True
        name = plugin_api.plugin_name(plugin)

        def run() -> None:
            self.notify(plugin_api.run_action(plugin, self.project_dir, item, key), markup=False)
            self._after_write()

        self._confirm(f"{name}: run '{labels[key]}' ({key}) on {item.key}?", item.title, run)
        return True

    def _after_write(self) -> None:
        reload = getattr(self.shell, "reload", None)
        if callable(reload):
            try:
                reload()
                return
            except Exception:
                pass
        self.refresh_state(type("S", (), {"needs": st.needs_you(self.project_dir)})())

    def _write(self, fn, item) -> None:
        self.notify(fn(self.project_dir, item), markup=False)
        self._after_write()

    def action_apply(self) -> None:
        item = self.selected()
        if self._plugin_action(item, "a") or item is None:
            return
        if item.kind == "GP":
            p = item.detail.get("proposal") or {}
            if p.get("kind") == "write-back":
                o = p.get("origin") or {}
                self._confirm(f"Apply {p.get('id')}? This writes to {o.get('source', 'the outside tracker')}.",
                              detail_gameplan(item, self.project_dir)[1].split("\n")[0],
                              lambda: self._write(apply_gameplan, item))
            else:
                self._write(apply_gameplan, item)
        elif item.kind == "RF":
            self._write(apply_reflection, item)
        else:
            self.notify(self._no_write(item), markup=False)

    def action_drop(self) -> None:
        item = self.selected()
        if self._plugin_action(item, "x") or item is None:
            return
        if item.kind in ("GP", "RF"):
            pid = (item.detail.get("proposal") or {}).get("id")
            fn = drop_gameplan if item.kind == "GP" else drop_reflection
            what = "gameplan" if item.kind == "GP" else "reflection"
            self._confirm(f"Drop {what} proposal {pid}?", item.title, lambda: self._write(fn, item))
        else:
            self.notify(self._no_write(item), markup=False)

    def action_d(self) -> None:
        item = self.selected()
        if item is not None and item.kind == "PR":
            self.full = not self.full
            self._show_detail()
        elif _plugin_for(item) is not None:
            self._plugin_action(item, "d")
        else:
            self.action_drop()

    def action_follow(self) -> None:
        item = self.selected()
        if self._plugin_action(item, "f") or item is None:
            return
        if item.kind != "BD":
            self.notify("Only board threads can be followed.", markup=False)
            return
        try:
            self.notify(toggle_follow(self.project_dir, item.key), markup=False)
        except Exception as e:
            self.notify(f"Couldn't change following: {e}", markup=False)
        self._after_write()

    def action_read(self) -> None:
        item = self.selected()
        if self._plugin_action(item, "r") or item is None:
            return
        self.full = not self.full
        self._show_detail()

    def action_send(self) -> None:
        from ..app import send_prompt

        item = self.selected()
        if item is None:
            return
        source, prompt = send_prompt(item, self.shell.state)
        from ..sendform import needs_snapshot

        self.shell.ask_to_send(source, prompt, "needs", lambda: needs_snapshot(self.items))

    def _no_write(self, item) -> str:
        return {"PR": "Merging happens on GitHub, not here. s hands it to Claude.",
                "ED": "Accepting an edict means merging its PR. s hands it to Claude.",
                "DS": "Resolving a dissent is done with `daedalus edict resolve-dissent`. s hands it to Claude.",
                "BD": "Posting goes through Claude and `daedalus board post`. s drafts a reply."}.get(
            item.kind, "Nothing to apply here.")

    def _confirm(self, question: str, detail: str, then) -> None:
        def done(yes: Optional[bool]) -> None:
            if yes:
                then()
        self.app.push_screen(ConfirmModal(question, detail), done)
