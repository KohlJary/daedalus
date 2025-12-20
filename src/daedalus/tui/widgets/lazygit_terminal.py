"""
Lazygit Terminal - Terminal widget wrapper that spawns lazygit.

Provides:
- Automatic lazygit spawn with working directory support
- Exit detection and restart capability
- Integration with the Daedalus TUI layout
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Optional

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Static
from textual.message import Message
from textual import on

from .terminal import Terminal


class LazygitTerminal(Vertical):
    """Terminal widget that runs lazygit."""

    DEFAULT_CSS = """
    LazygitTerminal {
        height: 100%;
        width: 100%;
    }

    LazygitTerminal > .terminal-container {
        height: 1fr;
    }

    LazygitTerminal > .status-message {
        height: auto;
        background: #282a36;
        color: #ff5555;
        text-align: center;
        padding: 1;
        display: none;
    }

    LazygitTerminal > .status-message.visible {
        display: block;
    }
    """

    class LazygitExited(Message):
        """Message sent when lazygit exits."""
        pass

    class LazygitRestarted(Message):
        """Message sent when lazygit is restarted."""
        pass

    def __init__(
        self,
        working_dir: str | Path | None = None,
        auto_start: bool = True,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        """
        Initialize the lazygit terminal.

        Args:
            working_dir: Directory to run lazygit in (defaults to cwd)
            auto_start: Whether to start lazygit immediately on mount
            name: Widget name
            id: Widget ID
            classes: CSS classes
        """
        super().__init__(name=name, id=id, classes=classes)
        self.working_dir = Path(working_dir) if working_dir else Path.cwd()
        self.auto_start = auto_start
        self._terminal: Optional[Terminal] = None
        self._is_running = False

    def compose(self) -> ComposeResult:
        """Create the lazygit terminal layout."""
        # Check if lazygit is available
        lazygit_path = shutil.which("lazygit")
        if not lazygit_path:
            yield Static(
                "lazygit not found in PATH\nInstall: https://github.com/jesseduffield/lazygit",
                id="lazygit-error",
                classes="status-message visible"
            )
            return

        # Build the lazygit command with working directory
        command = self._build_command()

        self._terminal = Terminal(
            command=command,
            id="lazygit-pty",
            classes="terminal-container"
        )
        yield self._terminal

        yield Static(
            "lazygit exited. Press 'r' to restart.",
            id="lazygit-status",
            classes="status-message"
        )

    def _build_command(self) -> str:
        """Build the lazygit command with working directory."""
        # Use -p flag to specify path
        wd = str(self.working_dir.resolve())
        return f"lazygit -p {wd}"

    def on_mount(self) -> None:
        """Start lazygit when the widget is mounted."""
        if self.auto_start and self._terminal:
            self.start_lazygit()

    def start_lazygit(self) -> None:
        """Start or restart lazygit."""
        if self._terminal is None:
            return

        # Hide status message
        status = self.query_one("#lazygit-status", Static)
        status.remove_class("visible")

        # Start the terminal
        self._terminal.start()
        self._is_running = True
        self.post_message(self.LazygitRestarted())

    def stop_lazygit(self) -> None:
        """Stop lazygit."""
        if self._terminal is None:
            return

        self._terminal.stop()
        self._is_running = False

    def restart_lazygit(self) -> None:
        """Restart lazygit after it has exited."""
        if self._terminal is None:
            return

        # Recreate the terminal with fresh command
        old_terminal = self._terminal
        old_terminal.remove()

        command = self._build_command()
        self._terminal = Terminal(
            command=command,
            id="lazygit-pty",
            classes="terminal-container"
        )

        # Mount new terminal before the status message
        status = self.query_one("#lazygit-status", Static)
        self.mount(self._terminal, before=status)

        # Start it
        self.start_lazygit()

    async def on_key(self, event) -> None:
        """Handle key events for restart."""
        # Only handle 'r' when lazygit is not running
        if not self._is_running and event.key == "r":
            event.stop()
            self.restart_lazygit()

    def watch_terminal_disconnect(self) -> None:
        """Called when the terminal disconnects (lazygit exits)."""
        self._is_running = False

        # Show status message
        try:
            status = self.query_one("#lazygit-status", Static)
            status.add_class("visible")
        except Exception:
            pass

        self.post_message(self.LazygitExited())

    @property
    def is_running(self) -> bool:
        """Check if lazygit is currently running."""
        return self._is_running

    def focus(self, scroll_visible: bool = True) -> None:
        """Focus the terminal widget."""
        if self._terminal:
            self._terminal.focus(scroll_visible)
        else:
            super().focus(scroll_visible)
