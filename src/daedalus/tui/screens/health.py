"""
The Health screen (docs/design/tui/health.oph, @expanded): `daedalus doctor`'s findings and hints, each with
what it means and how to fix it. Rerun with `r`, and on every watched-file change.

Fixes are an allowlist (edict 0012): only `daedalus hydrate` and `daedalus init` can run from here, only for
the findings they actually fix, and only after a confirmation modal. They call the same library functions
as the CLI (`hydrate_project`, `init_project`) in a worker. Every other fix is shown, and offered to Claude.
"""

from __future__ import annotations

import contextlib
import io
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

from rich.text import Text
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import OptionList, Static
from textual.widgets.option_list import Option

from ..widgets import ExplainCard, KeyBar
from ..widgets.confirm import ConfirmModal  # noqa: F401  (the shared one; tests import it from here)


# ---------- the allowlist ----------

def _hydrate(project_dir: Path) -> None:
    from ...cli.commands import hydrate_project

    hydrate_project(project_dir)        # as `daedalus hydrate` with its defaults


def _init(project_dir: Path) -> None:
    from ...cli.commands import init_project

    init_project(project_dir)           # as `daedalus init` with its defaults (never --force)


# The only commands the TUI runs: command -> library function
# What each runnable fix writes, said in its confirm (Momus: the modal under-described hydrate)
WRITES = {
    "daedalus hydrate": "it rewrites the managed section of CLAUDE.md, replaces .claude/agents/ and .claude/skills/ with "
                        "the shipped versions, and updates hooks and permission rules in .claude/settings.json.",
    "daedalus init": "it creates any missing .daedalus/ files, adds .gitignore rules, installs agents, skills and hooks, "
                     "and injects the CLAUDE.md section. Existing memory files are kept.",
}

RUNNABLE: dict[str, Callable[[Path], None]] = {"daedalus hydrate": _hydrate, "daedalus init": _init}

# Which finding each runnable command fixes. A finding not listed here has no run action.
FIX_FOR = {
    "board-ask-rule-missing": "daedalus hydrate",   # hydrate registers the hooks and their ask rules
    "gameplan-ignored": "daedalus init",            # init fixes .gitignore
    "palace-dispatch-ignored": "daedalus init",     # the .gitignore fix lives in init, not hydrate
    "no-gameplan": "daedalus init",                 # the hint: no gameplan in this project
}

# What each finding means, in plain words. The finding's own message follows it.
EXPLAIN = {
    "commits-after-gameplan": "Commits have landed since the gameplan last changed, so it may not say what was done.",
    "phase-tasks-all-done": "Every task in the active phase is done, but the phase is still open.",
    "stale-task": "A task has been in progress a long time without an update.",
    "gameplan-ignored": "Git ignores the gameplan, so the plan never leaves this machine.",
    "gameplan-unreadable": "A gameplan file can't be read, so nothing that depends on it can run.",
    "workstream-author-invalid": "A workstream's git author isn't a pattern git accepts, so its drift can't be measured.",
    "collision-edict": "Two workstreams have open work on the same edict.",
    "collision-claims": "Two workstreams claim paths that overlap.",
    "edict-bad-status": "An edict's Status line isn't proposed, accepted or done.",
    "edict-duplicate-number": "Two edict files share a number.",
    "edict-not-in-gameplan": "An accepted edict isn't referenced by any phase or task, so nothing says it's being built.",
    "board-ask-rule-missing": "This checkout uses the board, but no permissions ask rule makes `daedalus board post` "
                              "ask first.",
    "undigested-sessions-near-cleanup": "Claude Code will soon delete session transcripts reflection hasn't read.",
    "palace-dispatch-invalid": "Some of the palace's dispatch rules are malformed, so it skips them.",
    "palace-dispatch-ignored": "Git ignores the palace's dispatch rules, so teammates won't get them.",
    "project-map-missing-packages": "The project map doesn't mention some of the code's packages.",
    "empty-file-read-by-hook": "The session-start hook reads a file that has stayed an empty template.",
    "source-auth-failed": "A source couldn't log in to its tracker at its last sync.",
    "source-unreachable": "A source couldn't reach its tracker at its last sync.",
    "source-drift": "An item is closed in its tracker but still open here.",
    "source-write-back-missing": "A task is done, but nothing has told its tracker.",
    "install-stale": "The installed daedalus-cli is older or newer than the checkout it came from.",
    "palace-grammars-missing": "tree-sitter isn't installed, so the palace only reads Python.",
    "doctor-failed": "Doctor itself failed, so the checks didn't run.",
    "hint": "A hint: informational, it never fails doctor.",
    "no-gameplan": "There's no gameplan here yet.",
}


@dataclass
class Entry:
    name: str
    message: str
    hint: bool = False

    @property
    def fix(self) -> Optional[str]:
        """The allowlisted command that fixes this, or None."""
        return FIX_FOR.get(self.name)

    @property
    def fix_text(self) -> str:
        import re

        if self.fix:
            return self.fix
        m = re.search(r"(?:Run|run|Fix[^:]*:)\s*`([^`]+)`", self.message) or re.search(r"`(daedalus [^`]+)`", self.message)
        return m.group(1) if m else "(doctor names no command; ask Claude, or fix it by hand)"


def entries(findings: list, hints: list) -> list[Entry]:
    out = [Entry(f.name, f.message) for f in findings]
    for h in hints:
        if h.startswith("No gameplan in this project"):
            out.append(Entry("no-gameplan", h, hint=True))
        else:
            name, sep, msg = h.partition(": ")
            out.append(Entry(name, msg, True) if sep and " " not in name else Entry("hint", h, True))
    return out


def run_fix(command: str, project_dir: Path) -> str:
    """Run an allowlisted command through its library function; return what it printed."""
    fn = RUNNABLE[command]          # KeyError for anything off the allowlist
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        fn(Path(project_dir))
    return out.getvalue()


# ---------- the screen ----------

class HealthScreen(Screen):
    """The expanded Health: doctor's findings, each explained, with the fix (run, if allowlisted)."""

    BINDINGS = [
        ("escape", "back", "back"), ("question_mark", "explain", "explain"), ("s", "send", "send to Claude"),
        ("r", "recheck", "recheck"), ("f", "fix", "run fix"), ("j", "cursor('down')", "down"),
        ("k", "cursor('up')", "up"),
    ]
    DEFAULT_CSS = """
    HealthScreen { layout: vertical; }
    HealthScreen #health-title { height: 1; padding: 0 1; background: $boost; text-style: bold; }
    HealthScreen #health-main { height: 1fr; }
    HealthScreen #findings { width: 2fr; height: 1fr; border: round $panel; }
    HealthScreen #findings:focus { border: round $accent; }
    HealthScreen #health-detail-box { width: 3fr; border: round $panel; }
    HealthScreen #health-detail-scroll { height: 1fr; padding: 0 1; }
    HealthScreen #health-keys { height: 1; padding: 0 1; color: $text-muted; border-top: solid $panel; }
    """

    def __init__(self, app: Any):
        super().__init__()
        self.project_dir = Path(app.project_dir)
        self.entries: list[Entry] = []
        self.last_output: Optional[str] = None

    def compose(self):
        yield Static("Health", id="health-title", markup=False)
        with Horizontal(id="health-main"):
            yield OptionList(id="findings", markup=False)
            with Vertical(id="health-detail-box"):
                with VerticalScroll(id="health-detail-scroll"):
                    yield Static("", id="health-detail", markup=False)
                yield Static("", id="health-keys", markup=False)
        yield KeyBar()

    def on_mount(self) -> None:
        self.refresh_state(getattr(self.app, "state", None))
        self.query_one(KeyBar).show_dashboard("↑/↓ select · f run fix (asks first) · s send to Claude · r recheck · "
                                              "? explain · esc back")
        self.query_one("#findings", OptionList).focus()

    # ----- data -----

    def refresh_state(self, state: Any = None) -> None:
        if state is not None and hasattr(state, "findings"):
            findings, hints = state.findings, state.hints
        else:
            from ..state import health

            findings, hints = health(self.project_dir)
        self.entries = entries(findings, hints)
        n = sum(1 for e in self.entries if not e.hint)
        self.query_one("#health-title", Static).update(
            f"Health  ({'⚠ ' + str(n) + ' finding' + ('s' if n != 1 else '') if n else '✓ in sync'})")
        ol = self.query_one("#findings", OptionList)
        keep = ol.highlighted_option.id if ol.highlighted_option else None
        ol.clear_options()
        ol.add_options([Option(Text(f"{'·' if e.hint else '⚠'} {e.name}" + ("  [hint]" if e.hint else "")),
                               id=f"e{i}:{e.name}") for i, e in enumerate(self.entries)])
        if not self.entries:
            self.query_one("#health-detail", Static).update(
                "✓ In sync. Doctor found nothing to fix.\n\nDoctor compares the gameplan, edicts and memory files "
                "with the repo, and lists here where they've fallen behind. It reruns whenever a watched file "
                "changes.\n\nCLI: daedalus doctor")
            self.query_one("#health-keys", Static).update("s send to Claude · r recheck")
            return
        ids = [ol.get_option_at_index(i).id for i in range(ol.option_count)]
        ol.highlighted = ids.index(keep) if keep in ids else 0
        self._show(ol.highlighted)

    def selected(self) -> Optional[Entry]:
        ol = self.query_one("#findings", OptionList)
        if ol.highlighted is None or not (0 <= ol.highlighted < len(self.entries)):
            return None
        return self.entries[ol.highlighted]

    def _show(self, index: Optional[int]) -> None:
        if index is None or not (0 <= index < len(self.entries)):
            return
        e = self.entries[index]
        lines = [e.name + ("  [hint]" if e.hint else ""), "", EXPLAIN.get(e.name, ""), "", e.message,
                 "", f"Suggested fix: {e.fix_text}"]
        if e.fix:
            lines.append(f"(f runs `{e.fix}` here after you confirm)")
        else:
            lines.append("(not run from here: s hands it to Claude)")
        if self.last_output:
            lines += ["", "Last fix printed:", self.last_output.strip()]
        self.query_one("#health-detail", Static).update("\n".join(l for l in lines if l is not None))
        keys = ("f run fix (asks first) · " if e.fix else "") + "s send to Claude · r recheck"
        self.query_one("#health-keys", Static).update(keys)

    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        self._show(event.option_index)

    # ----- actions -----

    def action_fix(self) -> None:
        e = self.selected()
        if e is None or e.fix is None or e.fix not in RUNNABLE:
            self.notify("Doctor names no command the TUI can run for this. Press s to hand it to Claude.", markup=False)
            return
        command = e.fix

        def confirmed(yes: Optional[bool]) -> None:
            self.query_one(KeyBar).show_dashboard("↑/↓ select · f run fix (asks first) · s send to Claude · "
                                                  "r recheck · ? explain · esc back")
            if yes:
                self.run_worker(lambda: run_fix(command, self.project_dir), thread=True, name=f"fix:{command}",
                                group="doctor-fix", exclusive=True)

        self.query_one(KeyBar).show_modal()
        self.app.push_screen(ConfirmModal(f"Run `{command}`?",
                                          f"For: {e.name}\nIn: {self.project_dir}\n\n"
                                          f"This writes files the way `{command}` does from the command line: "
                                          + WRITES.get(command, "") ),
                             confirmed)

    def on_worker_state_changed(self, event) -> None:
        from textual.worker import WorkerState

        if event.worker.group != "doctor-fix":
            return
        if event.state == WorkerState.SUCCESS:
            self.last_output = event.worker.result or ""
            self.notify(f"{event.worker.name[4:]} done. Rechecking.", markup=False)
            self.action_recheck()
        elif event.state == WorkerState.ERROR:
            self.last_output = f"Failed: {event.worker.error}"
            self.notify(self.last_output, severity="error", markup=False)
            self._show(self.query_one("#findings", OptionList).highlighted)

    def action_recheck(self) -> None:
        if hasattr(self.app, "reload"):
            self.app.reload()           # reruns doctor and refreshes every panel, this screen included
        else:
            self.refresh_state(None)

    def action_cursor(self, direction: str) -> None:
        getattr(self.query_one("#findings", OptionList), f"action_cursor_{direction}")()

    def action_back(self) -> None:
        self.app.pop_screen()

    def action_explain(self) -> None:
        from ..cards import PANEL_CARDS

        self.app.push_screen(ExplainCard(PANEL_CARDS.get("Health", "Doctor / drift")))

    def send_target(self) -> tuple[str, str]:
        e = self.selected()
        if e is None:
            return ("Health", "Run `daedalus doctor` and tell me whether anything needs attention.")
        return (f"Doctor: {e.name}",
                f"`daedalus doctor` reports {e.name}: {e.message}\nExplain what it means here and propose a fix "
                f"(suggested: {e.fix_text}). Don't apply it until I agree.")

    def action_send(self) -> None:
        source, prompt = self.send_target()
        state = getattr(self.app, "state", None)
        self.app.ask_to_send(source, prompt, "health", lambda: self.snapshot(state))

    def snapshot(self, state: Any = None) -> str:
        from ..sendform import health_snapshot

        if state is not None and hasattr(state, "findings"):
            return health_snapshot(state.findings, state.hints)
        from ..state import health

        return health_snapshot(*health(self.project_dir))
