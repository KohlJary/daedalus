"""
SwarmGrid - Dynamic grid container for Icarus worker terminals.

Watches for icarus-* tmux sessions and creates TmuxTerminal widgets for each.
Arranges terminals in a responsive grid based on worker count.
"""

from __future__ import annotations

import asyncio
import subprocess
from typing import Dict, Optional, Set

from textual.widget import Widget
from textual.widgets import Static
from textual.reactive import reactive

from .tmux_terminal import TmuxTerminal


def list_icarus_sessions() -> list[str]:
    """List all icarus-* tmux sessions."""
    try:
        result = subprocess.run(
            ["tmux", "list-sessions", "-F", "#{session_name}"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return []

        sessions = result.stdout.strip().split('\n') if result.stdout.strip() else []
        return sorted([s for s in sessions if s.startswith("icarus-")])
    except Exception:
        return []


class SwarmGrid(Widget):
    """
    Dynamic grid of worker terminals.

    Watches for icarus-* tmux sessions and creates TmuxTerminal widgets for each.
    Automatically arranges terminals in a grid layout.
    """

    DEFAULT_CSS = """
    SwarmGrid {
        width: 100%;
        height: 50%;
        layout: grid;
        grid-size: 2 2;
        grid-gutter: 1;
        background: #1e1e2e;
    }

    SwarmGrid.-single {
        grid-size: 1 1;
    }

    SwarmGrid.-double {
        grid-size: 2 1;
    }

    SwarmGrid.-quad {
        grid-size: 2 2;
    }

    SwarmGrid.-six {
        grid-size: 3 2;
    }

    SwarmGrid > .empty-state {
        width: 100%;
        height: 100%;
        content-align: center middle;
        color: #6272a4;
    }

    SwarmGrid > TmuxTerminal {
        width: 100%;
        height: 100%;
        min-height: 10;
        border: solid #44475a;
    }
    """

    worker_count: reactive[int] = reactive(0)

    def __init__(
        self,
        max_workers: int = 6,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(name=name, id=id, classes=classes)
        self.max_workers = max_workers
        self._workers: Dict[str, TmuxTerminal] = {}
        self._watch_task: Optional[asyncio.Task] = None
        self._known_sessions: Set[str] = set()

    def compose(self):
        """Initial empty state."""
        yield Static(
            "No active workers\n\nWorkers will appear here when spawned\n\nUse: daedalus spawn <count>",
            classes="empty-state",
            id="empty-state"
        )

    def on_mount(self) -> None:
        """Start watching for tmux sessions."""
        self.log.info("SwarmGrid mounted, starting session watch")
        self.notify("SwarmGrid mounted - watching for sessions")
        self._watch_task = asyncio.create_task(self._watch_sessions())

    def on_unmount(self) -> None:
        """Stop watching and clean up terminals."""
        if self._watch_task:
            self._watch_task.cancel()

        # Stop all terminal connections
        for terminal in self._workers.values():
            terminal.stop()

    async def _watch_sessions(self) -> None:
        """Watch for icarus-* tmux sessions."""
        try:
            while True:
                await self._scan_sessions()
                await asyncio.sleep(2.0)  # Scan every 2 seconds
        except asyncio.CancelledError:
            pass

    async def _scan_sessions(self) -> None:
        """Scan for icarus-* sessions and update terminals."""
        try:
            current_sessions = set(list_icarus_sessions())

            # Only notify on first scan or when sessions change
            if not self._known_sessions and current_sessions:
                self.notify(f"Found {len(current_sessions)} icarus sessions")

            # Find new sessions
            new_sessions = current_sessions - self._known_sessions
            if new_sessions:
                self.notify(f"Adding workers: {new_sessions}")

            # Find removed sessions
            removed_sessions = self._known_sessions - current_sessions

            # Add new worker terminals
            for session_name in sorted(new_sessions):
                if len(self._workers) < self.max_workers:
                    try:
                        await self._add_worker(session_name)
                    except Exception as e:
                        self.log.error(f"Failed to add worker {session_name}: {e}")

            # Remove terminated workers
            for session_name in removed_sessions:
                try:
                    self._remove_worker(session_name)
                except Exception as e:
                    self.log.error(f"Failed to remove worker {session_name}: {e}")

            self._known_sessions = current_sessions

            # Toggle empty state visibility
            if self._workers:
                try:
                    empty = self.query_one("#empty-state", Static)
                    empty.remove()
                except Exception:
                    pass
            elif not self.query("#empty-state"):
                await self.mount(Static(
                    "No active workers\n\nWorkers will appear here when spawned\n\nUse: daedalus spawn <count>",
                    classes="empty-state",
                    id="empty-state"
                ))
        except Exception as e:
            self.log.error(f"Scan error: {e}")

    async def _add_worker(self, session_name: str) -> None:
        """Add a new worker terminal."""
        if session_name in self._workers:
            return

        self.log.info(f"Adding worker terminal for {session_name}")

        terminal = TmuxTerminal(
            tmux_session=session_name,
            id=f"worker-{session_name}"
        )
        self._workers[session_name] = terminal
        await self.mount(terminal)
        self.log.info(f"Mounted terminal for {session_name}")

        # Start the terminal connection
        terminal.start()
        self.log.info(f"Started terminal for {session_name}")

        self.worker_count = len(self._workers)
        self._update_grid_layout()
        self.log.info(f"Worker count now: {self.worker_count}")

    def _remove_worker(self, session_name: str) -> None:
        """Remove a worker terminal."""
        if session_name not in self._workers:
            return

        terminal = self._workers.pop(session_name)
        terminal.stop()
        terminal.remove()

        self.worker_count = len(self._workers)
        self._update_grid_layout()

    def _update_grid_layout(self) -> None:
        """Update grid CSS based on worker count."""
        # Remove old layout classes
        for cls in ["-single", "-double", "-quad", "-six"]:
            self.remove_class(cls)

        # Apply new layout class
        count = len(self._workers)
        if count <= 1:
            self.add_class("-single")
        elif count <= 2:
            self.add_class("-double")
        elif count <= 4:
            self.add_class("-quad")
        else:
            self.add_class("-six")

    def watch_worker_count(self, old_count: int, new_count: int) -> None:
        """React to worker count changes."""
        pass  # Could emit events or update status bar

    def clear_all(self) -> None:
        """Remove all worker terminals."""
        for session_name in list(self._workers.keys()):
            self._remove_worker(session_name)

    def refresh_sessions(self) -> None:
        """Force a session scan."""
        if self._watch_task:
            # Clear known sessions to force re-scan
            self._known_sessions.clear()
