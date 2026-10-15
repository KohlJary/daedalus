"""
The Daedalus TUI (edict 0012): the home screen from docs/design/tui/shell.oph.

- Left: what you would otherwise check with five commands (NeedsYou, Gameplan, Health). Right: a Claude
  Code session. At 100 columns or more, the desktop layout; below, one tab at a time.
- One file watcher (a single timer over .daedalus/, docs/edicts/ and the git HEAD) refreshes every panel
  from the same library functions the CLI uses. No panel polls on its own.
- While the Claude pane has focus every key goes to Claude except the escape chord. No priority bindings.
"""

from __future__ import annotations

import importlib
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from textual.app import App
from textual.containers import Vertical

from . import state as st
from .session import Backend, choose_backend, session_name
from .widgets import (ActiveTab, ClaudePane, ExplainCard, Gameplan, Header, Health, KeyBar, LastSession, NeedsYou,
                      SendToClaude, TabBar, Welcome)

NARROW_BELOW = 100

# Expanded screens, loaded when first opened: key -> "module:Class" under daedalus.tui.screens
SCREENS = {
    "needs": "needs_you:NeedsYouScreen",
    "gameplan": "gameplan:GameplanScreen",
    "health": "health:HealthScreen",
    "story": "story:StoryScreen",
    "edicts": "edicts:EdictsScreen",
    "board": "board:BoardScreen",
    "config": "config:ConfigScreen",
    "sources": "sources:SourcesScreen",
    "reflection": "reflection:ReflectionScreen",
    "dream": "dream:DreamScreen",
    "plugins": "plugins:PluginMenu",
}


@dataclass
class AppState:
    header: dict = field(default_factory=dict)
    last_session: Optional[str] = None
    needs: list = field(default_factory=list)
    gameplan: dict = field(default_factory=dict)
    findings: list = field(default_factory=list)
    hints: list = field(default_factory=list)
    first_run: bool = False
    claude_status: str = ""


def load_state(project_dir: Path, settings: dict) -> AppState:
    findings, hints = st.health(project_dir)
    return AppState(
        header=st.header(project_dir), last_session=st.last_session(project_dir),
        needs=st.needs_you(project_dir, settings.get("prs", "local")), gameplan=st.gameplan(project_dir),
        findings=findings, hints=hints, first_run=st.is_first_run(project_dir),
    )


def watched_files(project_dir: Path) -> list[Path]:
    """What the panels read, and nothing else: one cheap stat pass per tick (Momus F7)."""
    root = Path(project_dir)
    d = root / ".daedalus"
    files: list[Path] = [d / name for name in ("session-summaries.md", "decisions.md", "project-map.md",
                                               "lessons.md", "warnings.md", "config.json")]
    for folder in (d / "roadmap", d / "gameplans", d / "board", root / "docs" / "edicts",
                   root / "docs" / "edicts" / "dissents"):
        try:  # an unreadable folder is skipped, never fatal (Momus V1)
            if folder.is_dir():
                files += [p for p in folder.iterdir() if p.is_file()]
        except OSError:
            continue
    files += [d / "reflection" / "pending.json", d / "reflection" / "due.json", d / "sources" / "state.json",
              d / "dreams" / "due.json", d / "dreams" / "log.jsonl", d / "dreams" / "themes.json",
              d / "reflection" / "experiment-log.jsonl", root / "docs" / "status.md"]
    try:  # each dream's own files (meta, parts) feed the Dream screen
        if (d / "dreams").is_dir():
            files += [p for sub in (d / "dreams").iterdir() if sub.is_dir() for p in sub.iterdir() if p.is_file()]
    except OSError:
        pass
    gitdir = root / ".git"
    common = gitdir
    if gitdir.is_file():  # a worktree: .git points at its git dir; refs live in the common dir
        try:
            gitdir = Path(gitdir.read_text().split(":", 1)[1].strip())
            common = gitdir / (gitdir / "commondir").read_text().strip() if (gitdir / "commondir").exists() else gitdir
        except (OSError, IndexError):
            return files
    files.append(gitdir / "HEAD")
    heads = common / "refs" / "heads"
    try:
        if heads.is_dir():
            files += [p for p in heads.rglob("*") if p.is_file()]  # nested refs too (feat/*, fix/*)
    except OSError:
        pass
    files.append(common / "packed-refs")
    return files


def snapshot(files: list[Path]) -> dict:
    out = {}
    for f in files:
        try:
            out[str(f)] = f.stat().st_mtime_ns
        except OSError:
            continue
    return out


class DaedalusShell(App, inherit_bindings=False):
    """The home screen (◆DaedalusShell in shell.oph).

    `inherit_bindings=False` and no command palette: Textual's own ctrl+q (priority), ctrl+c and ctrl+p would
    otherwise reach past the Claude pane (Momus F1). The only bindings are the ones below, none priority.
    """

    TITLE = "Daedalus"
    ENABLE_COMMAND_PALETTE = False
    CSS = """
    Screen { layout: vertical; }
    #left { width: 1fr; min-width: 34; }
    #right { width: 2fr; }
    DaedalusShell.-narrow #left { width: 1fr; }
    """
    BINDINGS = [
        ("1", "panel('needs')", "Needs you"), ("2", "panel('gameplan')", "Gameplan"),
        ("3", "panel('health')", "Health"), ("4", "focus_claude", "Claude"), ("5", "panel('story')", "Story"),
        ("w", "panel('story')", "Story"), ("c", "focus_claude", "Claude"), ("e", "panel('edicts')", "Edicts"),
        ("b", "panel('board')", "Board"), ("comma", "panel('config')", "Config"),
        ("R", "panel('reflection')", "Reflection"), ("S", "panel('sources')", "Sources"),
        ("D", "panel('dream')", "Dream"),
        ("enter", "expand", "Expand"), ("question_mark", "explain", "Explain"),
        ("s", "send", "Send to Claude"), ("q", "quit", "Quit"), ("t", "theme", "Theme"),
        ("m", "plugins", "Plugins"),
    ]

    def __init__(self, project_dir: Path, backend: Optional[Backend] = None, settings: Optional[dict] = None,
                 claude_command: Optional[list[str]] = None, watch_interval: float = 1.0):
        super().__init__()
        self.project_dir = Path(project_dir)
        self.settings = settings if settings is not None else _tui_settings(self.project_dir)
        if backend is None:
            backend, why = choose_backend(self.settings.get("backend", "auto"))
        else:
            why = None
        self.backend, self.fallback_reason = backend, why
        self.claude_command = claude_command or ["claude"]
        self.watch_interval = watch_interval
        self.state = AppState()
        self._snapshot: dict = {}
        self.narrow = False
        self.active_tab = "1"

    # ----- layout -----

    def compose(self):
        yield Header()
        yield LastSession()
        yield TabBar()
        with ActiveTab():
            with Vertical(id="left"):
                yield Welcome(id="welcome")
                yield NeedsYou(id="needs")
                yield Gameplan(id="gameplan")
                yield Health(id="health")
            with Vertical(id="right"):
                yield ClaudePane(self.backend, session_name(self.project_dir), self.project_dir, self.claude_command,
                                 escape=self.settings.get("escape", "ctrl+]"), fallback_reason=self.fallback_reason,
                                 id="claude")
        yield KeyBar()

    def on_mount(self) -> None:
        self.reload()
        self.set_interval(self.watch_interval, self._watch)
        pane = self.query_one(ClaudePane)
        if session_name(self.project_dir) in pane.existing():
            pane.attach_session()
        self.query_one(KeyBar).show_dashboard()
        self.query_one(NeedsYou).focus()
        self._layout(self.size.width)

    def on_resize(self, event) -> None:
        self._layout(event.size.width)
        pane = self.query_one(ClaudePane)
        if self.focused is pane and self.narrow and self.active_tab != "4":
            self.on_claude_pane_escape(ClaudePane.Escape())  # the pane is hidden now: don't claim keys go to it
        elif self.focused is pane:
            self.query_one(KeyBar).show_claude(self.settings.get("escape", "ctrl+]"))

    def _layout(self, width: int) -> None:
        self.narrow = width < NARROW_BELOW
        self.set_class(self.narrow, "-narrow")
        self.query_one(TabBar).styles.display = "block" if self.narrow else "none"
        self.query_one(LastSession).styles.display = "none" if self.narrow else "block"
        self._show_tab(self.active_tab)

    def _show_tab(self, tab: str) -> None:
        self.active_tab = tab
        first = self.state.first_run
        left, right = self.query_one("#left"), self.query_one("#right")
        panels = {"1": "needs", "2": "gameplan", "3": "health"}
        if not self.narrow:
            left.styles.display = right.styles.display = "block"
            self.query_one("#welcome").styles.display = "block" if first else "none"
            for pid in panels.values():
                self.query_one(f"#{pid}").styles.display = "none" if first else "block"
            return
        right.styles.display = "block" if tab == "4" else "none"
        left.styles.display = "none" if tab == "4" else "block"
        self.query_one("#welcome").styles.display = "block" if first and tab != "4" else "none"
        for key, pid in panels.items():
            self.query_one(f"#{pid}").styles.display = "block" if (key == tab and not first) else "none"
        counts = {"1": len(self.state.needs), "3": len(self.state.findings)}
        self.query_one(TabBar).show(tab, counts)

    # ----- state -----

    def reload(self) -> None:
        self.state = load_state(self.project_dir, self.settings)
        self.state.claude_status = getattr(self, "_claude_status", "")
        for widget in (Header, LastSession, NeedsYou, Gameplan, Health):
            self.query_one(widget).refresh_state(self.state)
        self._show_tab(self.active_tab)
        for screen in self.screen_stack[1:]:
            if hasattr(screen, "refresh_state"):
                screen.refresh_state(self.state)

    def _watch(self) -> None:
        snap = snapshot(watched_files(self.project_dir))
        if snap != self._snapshot:
            first = not self._snapshot
            self._snapshot = snap
            if not first:
                self.reload()

    def on_claude_pane_status(self, message: ClaudePane.Status) -> None:
        self._claude_status = message.status
        self.state.claude_status = message.status
        self.query_one(Header).refresh_state(self.state)

    # ----- focus -----

    def action_focus_claude(self) -> None:
        if self.narrow:
            self._show_tab("4")
        self.query_one(ClaudePane).focus()
        self.query_one(KeyBar).show_claude(self.settings.get("escape", "ctrl+]"))

    def on_claude_pane_escape(self, message: ClaudePane.Escape) -> None:
        if self.narrow:
            self._show_tab("1")
        self.query_one(NeedsYou).focus()
        self.query_one(KeyBar).show_dashboard()

    # ----- actions -----

    def _focused_panel(self) -> str:
        w = self.focused
        while w is not None and getattr(w, "id", None) not in ("needs", "gameplan", "health", "welcome", "claude"):
            w = w.parent
        return getattr(w, "id", None) or "needs"

    def action_panel(self, key: str) -> None:
        if self.narrow and key in ("needs", "gameplan", "health"):
            tab = {"needs": "1", "gameplan": "2", "health": "3"}[key]
            if self.active_tab != tab:
                self._show_tab(tab)
                self.query_one(f"#{key}").focus()
                return
        self.open_screen(key)

    def open_screen(self, key: str) -> None:
        target = SCREENS.get(key)
        if target is None:
            self.notify(f"No screen {key}")
            return
        module, cls = target.split(":")
        try:
            screen_cls = getattr(importlib.import_module(f"daedalus.tui.screens.{module}"), cls)
        except (ImportError, AttributeError):
            self.notify(f"The {key} screen isn't built yet")
            return
        self.push_screen(screen_cls(self))

    def action_plugins(self) -> None:
        """The plugin menu: screens that `daedalus.tui` plugins add (daedalus.tui.plugin)."""
        self.open_screen("plugins")

    def action_expand(self) -> None:
        panel = self._focused_panel()
        if panel in ("needs", "gameplan", "health"):
            self.open_screen(panel)

    def action_explain(self) -> None:
        from .cards import PANEL_CARDS

        name = {"needs": "NeedsYou", "gameplan": "Gameplan", "health": "Health", "welcome": "Welcome",
                "claude": "ClaudePane"}.get(self._focused_panel(), "Gameplan")
        self.push_screen(ExplainCard(PANEL_CARDS.get(name, name)))

    def action_send(self, source: Optional[str] = None, prompt: Optional[str] = None) -> None:
        panel = snapshot = None
        if source is None:
            focused = self._focused_panel()
            item = self.state.needs[0] if self.state.needs and focused == "needs" else None
            source, prompt = send_prompt(item, self.state)
            panel, snapshot = panel_snapshot(focused, self.state)
        self.ask_to_send(source, prompt, panel, snapshot)

    def ask_to_send(self, source: str, prompt: str, panel: Optional[str] = None,
                    snapshot: Optional[Callable[[str], Optional[str]]] = None) -> None:
        """Open Send to Claude. `panel` names the panel for the send log; `snapshot(form)` draws its state as
        text or as a diagram (tui.send_form), and is only called when one of those is chosen."""
        from . import sendform

        setting = self.settings.get("send_form", "prose")
        pre = sendform.preview(setting, prompt, snapshot)

        def done(text: Optional[str]) -> None:
            if text:
                try:
                    text = sendform.finish(self.project_dir, setting, pre, text, panel or "other", prompt, snapshot)
                except Exception:  # the form and its log must never stop a send
                    pass
                while len(self.screen_stack) > 1:  # back to the shell from an expanded screen, to show Claude
                    self.pop_screen()
                pane = self.query_one(ClaudePane)
                if pane.session is None:
                    pane.start_session()
                pane.paste(text)
                while len(self.screen_stack) > 1:  # sent from an expanded screen: back to the shell, Claude in view
                    self.pop_screen()
                self.action_focus_claude()
        self.query_one(KeyBar).show_modal()
        self.push_screen(SendToClaude(source, pre["shown"], sendform.setting_note(setting)), done)

    def action_theme(self) -> None:
        self.theme = "textual-light" if self.theme != "textual-light" else "textual-dark"


def panel_snapshot(panel: str, state: AppState) -> tuple[str, Optional[Callable[[str], str]]]:
    """(panel name for the send log, a function drawing its snapshot in a form) for a home-screen panel."""
    from . import sendform

    if panel == "needs":
        return "needs", lambda form: sendform.needs_snapshot(state.needs, form=form)
    if panel == "gameplan":
        return "gameplan", lambda form: sendform.plan_snapshot(state.gameplan, form=form)
    if panel == "health":
        return "health", lambda form: sendform.health_snapshot(state.findings, state.hints, form=form)
    return panel or "other", None


def send_prompt(item: Any, state: AppState) -> tuple[str, str]:
    """The prompt Send to Claude starts from, for a NeedsYou item (or the active task)."""
    if item is None:
        active = (state.gameplan or {}).get("activePhase") or {}
        task = next((t for t in active.get("tasks", []) if t.get("status") in ("in_progress", "pending")), None)
        if task:
            return (f"Task {task['id']}", f"Pick up task {task['id']} ({task.get('title', '')}) from the gameplan. "
                                         "Read its details and the gameplan first, then propose the next step.")
        return ("Daedalus", "Run /inhale and tell me where things stand.")
    prompts = {
        "PR": f"Review branch {item.key} against the edict it implements. Report gaps; don't fix them.",
        "ED": f"Read edict {item.key} and tell me whether it's ready to build: what's unclear or untestable.",
        "DS": f"Read the dissent {item.key} and the edict it objects to, and summarise both sides.",
        "BD": f"Read board thread {item.key} (`daedalus board read {item.key}`) and draft a reply for me to review.",
        "GP": f"Check pending proposal {item.key} against the repo: should I apply or drop it?",
        "RF": f"Explain reflection proposal {item.key} and the evidence behind it.",
    }
    return (f"{item.kind} {item.title}", prompts.get(item.kind, f"Look at {item.kind} {item.title}."))


def _tui_settings(project_dir: Path) -> dict:
    from ..config import get_project_settings

    try:
        return get_project_settings(project_dir, "tui")
    except Exception:
        return {"prs": "local", "escape": "ctrl+]", "backend": "auto"}


def run(project_dir: Path) -> None:
    DaedalusShell(project_dir).run()
