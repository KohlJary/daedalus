"""
Daedalus Terminal - Claude Code terminal widget with tmux session management.

Uses TmuxTerminal for rendering and PTYManager for session coordination.
Provides session controls: spawn, attach, detach, kill.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
from datetime import datetime
from typing import Optional, List, Dict

from rich.text import Text

from textual.widget import Widget
from textual.widgets import Static, Button
from textual.containers import Container, Vertical
from textual.app import ComposeResult
from textual import on
from textual.message import Message
from textual.reactive import reactive

from .tmux_terminal import TmuxTerminal, check_tmux_available


# Session prefix for tmux sessions (distinct from cass-vessel's "daedalus-*" sessions)
SESSION_PREFIX = "dtui"


def list_daedalus_sessions() -> List[str]:
    """List existing daedalus-* tmux sessions."""
    try:
        result = subprocess.run(
            ["tmux", "list-sessions", "-F", "#{session_name}"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            return [
                s.strip() for s in result.stdout.strip().split('\n')
                if s.strip().startswith(f'{SESSION_PREFIX}-')
            ]
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return []


def tmux_session_exists(session_name: str) -> bool:
    """Check if a specific tmux session exists."""
    try:
        result = subprocess.run(
            ["tmux", "has-session", "-t", session_name],
            capture_output=True,
            timeout=5
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def load_daedalus_identity() -> Optional[str]:
    """Load Daedalus identity from config directory."""
    from pathlib import Path
    identity_file = Path.home() / ".config" / "daedalus" / "identity.md"
    if identity_file.exists():
        return identity_file.read_text()
    return None


def create_tmux_session(
    session_name: str,
    command: str = "claude",
    cols: int = 120,
    rows: int = 40,
    working_dir: Optional[str] = None,
    system_prompt: Optional[str] = None,
) -> bool:
    """Create a new tmux session with optional system prompt injection."""
    if tmux_session_exists(session_name):
        return True

    # Build claude command with optional system prompt
    if system_prompt and command == "claude":
        # Escape for shell
        import shlex
        escaped_prompt = shlex.quote(system_prompt)
        command = f"claude --append-system-prompt {escaped_prompt}"

    shell_command = f"bash -l -c '{command}'"

    create_cmd = [
        "tmux", "new-session",
        "-d",
        "-s", session_name,
        "-x", str(cols),
        "-y", str(rows),
    ]

    if working_dir and os.path.isdir(working_dir):
        create_cmd.extend(["-c", working_dir])

    create_cmd.append(shell_command)

    try:
        result = subprocess.run(create_cmd, capture_output=True, timeout=10)
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def kill_tmux_session(session_name: str) -> bool:
    """Kill a tmux session."""
    try:
        result = subprocess.run(
            ["tmux", "kill-session", "-t", session_name],
            capture_output=True,
            timeout=5
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


class DaedalusTerminal(Widget, can_focus=True):
    """
    Daedalus terminal widget with tmux session persistence.

    Features:
    - Spawns Claude Code in a tmux session
    - Attaches to existing sessions on startup
    - Session controls: detach, kill, new session
    - Full terminal emulation via TmuxTerminal
    """

    DEFAULT_CSS = """
    DaedalusTerminal {
        height: 1fr;
        width: 1fr;
    }

    DaedalusTerminal .daedalus-content {
        height: 1fr;
        width: 1fr;
        background: #1e1e1e;
        padding: 0;
    }

    DaedalusTerminal .daedalus-no-session {
        height: 1fr;
        width: 1fr;
        align: center middle;
        padding: 2;
    }

    DaedalusTerminal .session-info {
        text-align: center;
        margin-bottom: 2;
    }

    DaedalusTerminal .spawn-btn {
        margin: 1;
    }

    DaedalusTerminal .session-list {
        height: auto;
        max-height: 50%;
        margin-top: 2;
    }

    DaedalusTerminal .session-item {
        margin: 0 2;
    }

    DaedalusTerminal .hidden {
        display: none;
    }

    DaedalusTerminal TmuxTerminal {
        height: 1fr;
        width: 1fr;
    }
    """

    # Reactive properties
    session_name: reactive[Optional[str]] = reactive(None)
    is_connected: reactive[bool] = reactive(False)

    class SessionStarted(Message):
        """Emitted when a session starts."""
        def __init__(self, session_name: str) -> None:
            self.session_name = session_name
            super().__init__()

    class SessionEnded(Message):
        """Emitted when a session ends."""
        def __init__(self, session_name: str) -> None:
            self.session_name = session_name
            super().__init__()

    def __init__(
        self,
        working_dir: str | None = None,
        command: str = "claude",
        auto_connect: bool = True,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(name=name, id=id, classes=classes)

        self.working_dir = working_dir or os.getcwd()
        self.command = command
        self.auto_connect = auto_connect
        self._terminal: Optional[TmuxTerminal] = None
        self._current_tmux_session: Optional[str] = None

    def compose(self) -> ComposeResult:
        """Compose the widget layout."""
        # No-session view
        with Vertical(id="no-session-view", classes="daedalus-no-session"):
            yield Static(
                Text("Daedalus", style="bold cyan") +
                Text("\nClaude Code Terminal", style="dim"),
                classes="session-info"
            )

            if not check_tmux_available():
                yield Static(
                    Text("tmux not installed\n", style="yellow") +
                    Text("Session persistence requires tmux", style="dim"),
                    classes="session-info"
                )
            else:
                yield Button("Start New Session", id="spawn-session-btn", variant="primary", classes="spawn-btn")

                # Existing sessions list
                with Container(id="existing-sessions", classes="session-list"):
                    yield Static("", id="sessions-list-content")

        # Terminal container (hidden initially)
        yield Container(id="terminal-container", classes="daedalus-content hidden")

    async def on_mount(self) -> None:
        """Initialize on mount - check for existing sessions."""
        await self._refresh_session_list()

        if self.auto_connect and check_tmux_available():
            # Try to connect to existing session
            existing = list_daedalus_sessions()
            if existing:
                await self._connect_to_session(existing[0])

    async def _refresh_session_list(self) -> None:
        """Refresh the list of existing tmux sessions."""
        if not check_tmux_available():
            return

        sessions = list_daedalus_sessions()

        try:
            content = self.query_one("#sessions-list-content", Static)
            container = self.query_one("#existing-sessions", Container)

            # Remove old session buttons
            for btn in container.query(".session-btn"):
                btn.remove()

            if sessions:
                text = Text("Existing Sessions:\n", style="bold")
                for session in sessions:
                    text.append(f"  {session}\n", style="cyan")
                content.update(text)

                # Add buttons for existing sessions
                for session in sessions:
                    btn = Button(f"Attach: {session}", id=f"attach-{session}", classes="session-btn session-item")
                    await container.mount(btn)
            else:
                content.update(Text("No existing sessions", style="dim"))
        except Exception:
            pass

    def watch_is_connected(self, connected: bool) -> None:
        """React to connection state changes."""
        try:
            no_session = self.query_one("#no-session-view")
            terminal_container = self.query_one("#terminal-container")

            if connected:
                no_session.add_class("hidden")
                terminal_container.remove_class("hidden")
            else:
                no_session.remove_class("hidden")
                terminal_container.add_class("hidden")
        except Exception:
            pass

    async def spawn_session(self, session_name: Optional[str] = None) -> bool:
        """Spawn a new Claude Code session with Daedalus identity."""
        if not check_tmux_available():
            return False

        # Generate name if not provided
        if not session_name:
            session_name = f"{SESSION_PREFIX}-{datetime.now().strftime('%H%M%S')}"
        elif not session_name.startswith(f"{SESSION_PREFIX}-"):
            session_name = f"{SESSION_PREFIX}-{session_name}"

        # Get widget size
        cols = max(80, self.size.width)
        rows = max(24, self.size.height)

        # Load Daedalus identity for system prompt injection
        identity = load_daedalus_identity()

        # Create the tmux session with identity
        if not create_tmux_session(
            session_name,
            command=self.command,
            cols=cols,
            rows=rows,
            working_dir=self.working_dir,
            system_prompt=identity,
        ):
            return False

        # Small delay for session to initialize
        await asyncio.sleep(0.3)

        # Connect to the session
        await self._connect_to_session(session_name)
        return True

    async def attach_session(self, tmux_session: str) -> bool:
        """Attach to an existing tmux session."""
        if not tmux_session_exists(tmux_session):
            return False

        await self._connect_to_session(tmux_session)
        return True

    async def _connect_to_session(self, tmux_session: str) -> None:
        """Connect to a tmux session using TmuxTerminal."""
        self._current_tmux_session = tmux_session
        self.session_name = tmux_session

        # Create TmuxTerminal widget
        self._terminal = TmuxTerminal(
            tmux_session=tmux_session,
            default_colors="textual",
            id="daedalus-tmux-terminal"
        )

        # Mount the terminal in the container
        try:
            container = self.query_one("#terminal-container")

            # Remove any existing terminal
            for existing in container.query("TmuxTerminal"):
                existing.remove()

            await container.mount(self._terminal)

            # Start the terminal
            self._terminal.start()

            self.is_connected = True

            # Focus the terminal
            self._terminal.focus()

            self.post_message(self.SessionStarted(tmux_session))

        except Exception as e:
            self._terminal = None
            self._current_tmux_session = None

    @on(Button.Pressed, "#spawn-session-btn")
    async def on_spawn_session(self, event: Button.Pressed) -> None:
        """Handle spawn session button click."""
        await self.spawn_session()

    @on(Button.Pressed, ".session-btn")
    async def on_attach_session(self, event: Button.Pressed) -> None:
        """Handle attach session button click."""
        btn_id = event.button.id
        if btn_id and btn_id.startswith("attach-"):
            session_name = btn_id[7:]  # Remove "attach-" prefix
            await self.attach_session(session_name)

    async def disconnect(self, refresh_list: bool = True) -> None:
        """Disconnect from current session (without killing tmux)."""
        if self._terminal:
            self._terminal.stop()
            try:
                self._terminal.remove()
            except Exception:
                pass
            self._terminal = None

        session_name = self._current_tmux_session
        self._current_tmux_session = None
        self.session_name = None
        self.is_connected = False

        if session_name:
            self.post_message(self.SessionEnded(session_name))

        if refresh_list:
            await self._refresh_session_list()

    async def kill_session(self) -> None:
        """Kill the current session entirely."""
        if self._current_tmux_session:
            session_name = self._current_tmux_session

            # Disconnect first
            await self.disconnect(refresh_list=False)

            # Kill tmux session
            kill_tmux_session(session_name)

            # Small delay for cleanup
            await asyncio.sleep(0.1)

            # Refresh the list
            await self._refresh_session_list()

    async def new_session(self) -> bool:
        """Start a new session (kills current if any)."""
        if self._current_tmux_session:
            await self.kill_session()
        return await self.spawn_session()

    def render(self) -> Text:
        """Render the widget."""
        return Text("")

    async def cleanup(self) -> None:
        """Clean up resources on shutdown."""
        if self._terminal:
            self._terminal.stop()

    def send_input(self, data: str) -> None:
        """Send input to the terminal."""
        if self._terminal and self.is_connected:
            self._terminal.send_data(data)

    def get_output_lines(self, count: Optional[int] = None) -> List[str]:
        """Get lines from the terminal output buffer."""
        if self._terminal:
            return self._terminal.get_output_lines(count)
        return []

    def get_output_raw(self, count: Optional[int] = None) -> str:
        """Get raw output from the terminal buffer."""
        if self._terminal:
            return self._terminal.get_output_raw(count)
        return ""

    def search_output(self, pattern: str, case_sensitive: bool = False) -> List[Dict]:
        """Search the terminal output buffer."""
        if self._terminal:
            return self._terminal.search_output(pattern, case_sensitive)
        return []

    def list_available_sessions(self) -> List[str]:
        """List available daedalus-* tmux sessions."""
        return list_daedalus_sessions()
