"""
Daedalus TUI Application - Main Textual app with 3-column layout.

Layout:
+------------------+---------------------------+------------------+
|                  |                           |                  |
|    Daedalus      |      Icarus Swarm         |     Lazygit      |
|    Terminal      |   (worker visualization)  |     Terminal     |
|     (25%)        |          (50%)            |      (25%)       |
|                  |                           |                  |
+------------------+---------------------------+------------------+
|                        Status Bar                               |
+-----------------------------------------------------------------+
"""

from pathlib import Path

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Static, Footer, Header, Input
from textual.screen import ModalScreen
from textual import on

from .widgets import DaedalusTerminal, LazygitTerminal, SwarmGrid, StatusBar
from ..bus import IcarusBus, WorkPackage
from ..cli.config import get_config, tmux_session_exists


class DaedalusApp(App):
    """Main Daedalus TUI application."""

    CSS_PATH = "styles.css"
    TITLE = "Daedalus"

    BINDINGS = [
        ("ctrl+1", "focus_daedalus", "Daedalus"),
        ("ctrl+2", "focus_swarm", "Swarm"),
        ("ctrl+3", "focus_lazygit", "Lazygit"),
        ("ctrl+q", "quit", "Quit"),
        ("ctrl+n", "new_session", "New Session"),
        ("ctrl+k", "kill_session", "Kill Session"),
        # Worker management keybindings
        ("ctrl+w", "spawn_worker", "Spawn Worker"),
        ("ctrl+d", "dispatch_work", "Dispatch Work"),
        ("ctrl+x", "kill_swarm", "Kill Swarm"),
    ]

    def __init__(
        self,
        working_dir: str | None = None,
        **kwargs
    ):
        super().__init__(**kwargs)
        self.working_dir = working_dir or str(Path.cwd())
        self.bus = IcarusBus()
        self.config = get_config()

    def compose(self) -> ComposeResult:
        """Create the three-column layout."""
        yield Header()
        with Horizontal(id="main-container"):
            # Left column: Daedalus terminal (Claude Code)
            with Vertical(id="daedalus-column"):
                yield Static("Daedalus Terminal", id="daedalus-label", classes="column-label")
                yield DaedalusTerminal(
                    working_dir=self.working_dir,
                    id="daedalus-terminal",
                    auto_connect=True,
                )

            # Center column: Icarus swarm visualization
            with Vertical(id="swarm-column"):
                yield Static("Icarus Swarm", id="swarm-label", classes="column-label")
                yield SwarmGrid(id="swarm-grid")

            # Right column: Lazygit terminal
            with Vertical(id="lazygit-column"):
                yield Static("Lazygit", id="lazygit-label", classes="column-label")
                yield LazygitTerminal(
                    working_dir=self.working_dir,
                    id="lazygit-terminal"
                )

        yield StatusBar(id="status-bar")
        yield Footer()

    def action_focus_daedalus(self) -> None:
        """Focus the Daedalus terminal."""
        terminal = self.query_one("#daedalus-terminal", DaedalusTerminal)
        terminal.focus()

    def action_focus_swarm(self) -> None:
        """Focus the swarm grid."""
        grid = self.query_one("#swarm-grid", SwarmGrid)
        grid.focus()

    def action_focus_lazygit(self) -> None:
        """Focus the lazygit terminal."""
        terminal = self.query_one("#lazygit-terminal", LazygitTerminal)
        terminal.focus()

    async def action_new_session(self) -> None:
        """Start a new Daedalus session."""
        terminal = self.query_one("#daedalus-terminal", DaedalusTerminal)
        await terminal.new_session()

    async def action_kill_session(self) -> None:
        """Kill the current Daedalus session."""
        terminal = self.query_one("#daedalus-terminal", DaedalusTerminal)
        await terminal.kill_session()

    @on(DaedalusTerminal.SessionStarted)
    def on_session_started(self, event: DaedalusTerminal.SessionStarted) -> None:
        """Handle session start - update title."""
        self.title = f"Daedalus - {event.session_name}"

    @on(DaedalusTerminal.SessionEnded)
    def on_session_ended(self, event: DaedalusTerminal.SessionEnded) -> None:
        """Handle session end - reset title."""
        self.title = "Daedalus"

    # -------------------------------------------------------------------------
    # Worker Management Actions
    # -------------------------------------------------------------------------

    async def action_spawn_worker(self) -> None:
        """Spawn a new Icarus worker via headless spawn."""
        import subprocess
        import sys
        from datetime import datetime

        # Initialize bus if needed
        if not self.bus.is_initialized():
            self.bus.initialize()

        # Spawn a headless worker
        LOG_DIR = Path("/tmp/icarus-logs")
        LOG_DIR.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        worker_id = f"icarus-{timestamp}-tui"
        log_file = LOG_DIR / f"{worker_id}.log"

        # Create log file with header
        with open(log_file, "w") as f:
            f.write(f"=== Icarus Worker {worker_id} ===\n")
            f.write(f"Started: {datetime.now().isoformat()}\n")
            f.write(f"Project: {self.working_dir}\n")
            f.write("=" * 40 + "\n\n")

        # Spawn worker with output redirected to log file
        cmd = [
            sys.executable, "-m", "daedalus.worker",
            "--project", self.working_dir,
            "--claim",
        ]

        with open(log_file, "a") as log_f:
            subprocess.Popen(
                cmd,
                stdout=log_f,
                stderr=log_f,
                start_new_session=True,
            )

        self.notify(f"Spawned worker: {worker_id}")

        # Refresh status bar
        status_bar = self.query_one("#status-bar", StatusBar)
        status_bar.refresh_now()

    async def action_dispatch_work(self) -> None:
        """Open dispatch work modal."""
        await self.push_screen(DispatchWorkScreen())

    async def action_kill_swarm(self) -> None:
        """Kill all Icarus workers in the swarm."""
        cfg = self.config

        if not tmux_session_exists(cfg.swarm_session):
            self.notify("No swarm session found", severity="warning")
            return

        import subprocess
        subprocess.run(
            ["tmux", "kill-session", "-t", cfg.swarm_session],
            capture_output=True
        )

        self.notify("Swarm terminated")

        # Refresh status bar
        status_bar = self.query_one("#status-bar", StatusBar)
        status_bar.refresh_now()


class DispatchWorkScreen(ModalScreen):
    """Modal screen for dispatching work packages."""

    CSS = """
    DispatchWorkScreen {
        align: center middle;
    }

    #dispatch-dialog {
        width: 60;
        height: auto;
        padding: 1 2;
        background: #282a36;
        border: solid #bd93f9;
    }

    #dispatch-dialog Static {
        margin-bottom: 1;
    }

    #dispatch-dialog Input {
        margin-bottom: 1;
    }

    .dialog-buttons {
        height: 3;
        align: center middle;
    }
    """

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("enter", "submit", "Submit"),
    ]

    def compose(self) -> ComposeResult:
        """Compose the dispatch dialog."""
        with Vertical(id="dispatch-dialog"):
            yield Static("Dispatch Work Package", classes="dialog-title")
            yield Static("Type (impl/refactor/test/research):")
            yield Input(placeholder="impl", id="work-type")
            yield Static("Description:")
            yield Input(placeholder="Description of work to dispatch", id="work-description")
            with Horizontal(classes="dialog-buttons"):
                yield Static("[Enter] Submit  [Esc] Cancel")

    def action_cancel(self) -> None:
        """Cancel and close dialog."""
        self.dismiss()

    async def action_submit(self) -> None:
        """Submit the work package."""
        work_type = self.query_one("#work-type", Input).value or "impl"
        description = self.query_one("#work-description", Input).value

        if not description:
            self.app.notify("Description is required", severity="error")
            return

        bus = IcarusBus()
        if not bus.is_initialized():
            bus.initialize()

        work = WorkPackage(
            id="",
            type=work_type,
            description=description,
            inputs={},
            outputs={},
            priority=5,
        )
        work_id = bus.post_work(work)

        self.app.notify(f"Dispatched: {work_id}")
        self.dismiss()


def run_tui(working_dir: str | None = None) -> None:
    """Run the Daedalus TUI application."""
    app = DaedalusApp(working_dir=working_dir)
    app.run()


if __name__ == "__main__":
    run_tui()
