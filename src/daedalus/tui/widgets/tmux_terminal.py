"""
TmuxTerminal - A Terminal widget that connects to tmux sessions.

Extends the patched Terminal to support attaching to existing
or newly spawned tmux sessions, providing the same performance benefits
(batched output, debounced refresh) with tmux session persistence.

Ported from cass-vessel/tui-frontend/widgets/daedalus/tmux_terminal.py
"""

from __future__ import annotations

import os
import pty
import asyncio
import fcntl
import struct
import termios
import signal
import subprocess
from collections import deque
from datetime import datetime
from typing import Optional, List, Dict

from textual import events

from .terminal import Terminal, TerminalPyteScreen
import pyte


def debug_log(message: str, level: str = "info") -> None:
    """Log a debug message."""
    # Simple print for now - can be enhanced later
    pass  # Quiet by default


class TerminalOutputBuffer:
    """
    Circular buffer for storing terminal output history.
    Stores both raw output and parsed lines for different use cases.
    """

    def __init__(self, max_lines: int = 1000, max_raw_chars: int = 100000):
        self.max_lines = max_lines
        self.max_raw_chars = max_raw_chars
        self._lines: deque = deque(maxlen=max_lines)
        self._raw_buffer: deque = deque(maxlen=max_raw_chars)
        self._timestamps: deque = deque(maxlen=max_lines)

    def append(self, data: str) -> None:
        """Append raw data to the buffer."""
        now = datetime.now()
        for char in data:
            self._raw_buffer.append(char)

        lines = data.replace('\r\n', '\n').replace('\r', '\n').split('\n')
        for line in lines:
            clean_line = self._strip_ansi(line)
            if clean_line.strip():
                self._lines.append(clean_line)
                self._timestamps.append(now)

    @staticmethod
    def _strip_ansi(text: str) -> str:
        """Strip ANSI escape codes from text."""
        import re
        ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
        return ansi_escape.sub('', text)

    def get_lines(self, count: Optional[int] = None) -> List[str]:
        """Get recent lines from the buffer."""
        if count is None:
            return list(self._lines)
        return list(self._lines)[-count:]

    def get_raw(self, count: Optional[int] = None) -> str:
        """Get raw output from the buffer."""
        if count is None:
            return ''.join(self._raw_buffer)
        return ''.join(list(self._raw_buffer)[-count:])

    def search(self, pattern: str, case_sensitive: bool = False) -> List[Dict]:
        """Search for a pattern in the buffer."""
        import re
        flags = 0 if case_sensitive else re.IGNORECASE
        try:
            regex = re.compile(pattern, flags)
        except re.error:
            regex = re.compile(re.escape(pattern), flags)

        results = []
        for i, (line, ts) in enumerate(zip(self._lines, self._timestamps)):
            if regex.search(line):
                results.append({
                    "line": line,
                    "index": i,
                    "timestamp": ts.isoformat()
                })
        return results

    def clear(self) -> None:
        """Clear the buffer."""
        self._lines.clear()
        self._raw_buffer.clear()
        self._timestamps.clear()

    @property
    def line_count(self) -> int:
        return len(self._lines)

    @property
    def char_count(self) -> int:
        return len(self._raw_buffer)


class TmuxTerminalEmulator:
    """
    Terminal emulator that connects to a tmux session via PTY.

    Unlike the base TerminalEmulator which spawns a new process,
    this one attaches to an existing tmux session.
    """

    def __init__(self, tmux_session: str, cols: int = 80, rows: int = 24):
        self.tmux_session = tmux_session
        self.ncol = cols
        self.nrow = rows
        self.data_buffer: list[str] = []
        self.run_task: asyncio.Task = None
        self.send_task: asyncio.Task = None
        self.pid: Optional[int] = None
        self.fd: Optional[int] = None
        self.p_out = None

        self.recv_queue = asyncio.Queue()
        self.send_queue = asyncio.Queue()
        self.event = asyncio.Event()

        self.output_buffer = TerminalOutputBuffer()

        self._attach_to_tmux()

    def _attach_to_tmux(self) -> None:
        """Fork a PTY and attach to the tmux session."""
        debug_log(f"Attaching to tmux session: {self.tmux_session}", "info")

        self.pid, self.fd = pty.fork()

        if self.pid == 0:
            # Child process - exec tmux attach
            os.execlp("tmux", "tmux", "attach-session", "-t", self.tmux_session)
            os._exit(1)
        else:
            debug_log(f"Forked PTY: pid={self.pid}, fd={self.fd}", "debug")
            self._set_nonblocking(self.fd)
            self._set_pty_size(self.fd, self.ncol, self.nrow)
            self.p_out = os.fdopen(self.fd, "w+b", 0)

    @staticmethod
    def _set_nonblocking(fd: int) -> None:
        """Set file descriptor to non-blocking mode."""
        flags = fcntl.fcntl(fd, fcntl.F_GETFL)
        fcntl.fcntl(fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)

    @staticmethod
    def _set_pty_size(fd: int, cols: int, rows: int) -> None:
        """Set PTY terminal size."""
        winsize = struct.pack("HHHH", rows, cols, 0, 0)
        fcntl.ioctl(fd, termios.TIOCSWINSZ, winsize)

    def start(self):
        """Start the read/write tasks."""
        self.run_task = asyncio.create_task(self._run())
        self.send_task = asyncio.create_task(self._send_data())

    def stop(self):
        """Stop and clean up."""
        if self.run_task:
            self.run_task.cancel()
        if self.send_task:
            self.send_task.cancel()

        if self.p_out:
            try:
                self.p_out.close()
            except OSError:
                pass

        # Send SIGHUP to detach from tmux (don't kill the session)
        if self.pid:
            try:
                os.kill(self.pid, signal.SIGHUP)
                os.waitpid(self.pid, os.WNOHANG)
            except (OSError, ChildProcessError):
                pass

    async def _run(self):
        """Main read loop - reads from PTY and queues data."""
        loop = asyncio.get_running_loop()

        def on_output():
            try:
                data = self.p_out.read(65536).decode(errors='replace')
                self.data_buffer.append(data)
                self.event.set()
            except UnicodeDecodeError:
                pass
            except Exception:
                loop.remove_reader(self.p_out)
                self.data_buffer = None
                self.event.set()

        loop.add_reader(self.p_out, on_output)
        await self.send_queue.put(["setup", {}])

        try:
            while True:
                msg = await self.recv_queue.get()
                if msg[0] == "stdin":
                    self.p_out.write(msg[1].encode())
                elif msg[0] == "set_size":
                    rows, cols = msg[1], msg[2]
                    self._set_pty_size(self.fd, cols, rows)
                    self._resize_tmux(cols, rows)
                elif msg[0] == "click":
                    x, y, button = msg[1] + 1, msg[2] + 1, msg[3]
                    if button == 1:
                        self.p_out.write(f"\x1b[<0;{x};{y}M".encode())
                        self.p_out.write(f"\x1b[<0;{x};{y}m".encode())
                elif msg[0] == "scroll":
                    direction, x, y = msg[1], msg[2] + 1, msg[3] + 1
                    if direction == "up":
                        self.p_out.write(f"\x1b[<64;{x};{y}M".encode())
                    elif direction == "down":
                        self.p_out.write(f"\x1b[<65;{x};{y}M".encode())
        except asyncio.CancelledError:
            pass
        finally:
            try:
                loop.remove_reader(self.p_out)
            except (ValueError, KeyError):
                pass

    def _resize_tmux(self, cols: int, rows: int) -> None:
        """Resize the tmux window to match."""
        try:
            subprocess.run(
                ["tmux", "resize-window", "-t", self.tmux_session, "-x", str(cols), "-y", str(rows)],
                capture_output=True,
                timeout=5
            )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

    async def _send_data(self):
        """Send batched data to the widget."""
        try:
            while True:
                await self.event.wait()
                self.event.clear()

                if self.data_buffer is None:
                    await self.send_queue.put(["disconnect", 1])
                    break

                if self.data_buffer:
                    combined = "".join(self.data_buffer)
                    self.data_buffer.clear()
                    self.output_buffer.append(combined)
                    await self.send_queue.put(["stdout", combined])

        except asyncio.CancelledError:
            pass


class TmuxTerminal(Terminal):
    """
    Terminal widget that connects to tmux sessions.

    Extends the fast Terminal with tmux session management,
    allowing attachment to existing sessions or spawning new ones.
    """

    DEFAULT_CSS = """
    TmuxTerminal {
        background: $background;
        height: 1fr;
        width: 1fr;
    }
    """

    def __init__(
        self,
        tmux_session: str,
        default_colors: str | None = "textual",
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        self.tmux_session = tmux_session

        # Initialize Widget directly (skip Terminal's command logic)
        from textual.widget import Widget
        Widget.__init__(self, name=name, id=id, classes=classes)

        self.command = f"tmux attach-session -t {tmux_session}"
        self.default_colors = default_colors

        if default_colors == "textual":
            self.textual_colors = self.detect_textual_colors()
        else:
            self.textual_colors = None

        self.ncol = 80
        self.nrow = 24
        self.mouse_tracking = False

        self.emulator: TmuxTerminalEmulator = None
        self.send_queue: asyncio.Queue = None
        self.recv_queue: asyncio.Queue = None
        self.recv_task: asyncio.Task = None

        self._pending_refresh = False
        self._refresh_scheduled = False

        # Key mappings from parent
        self.ctrl_keys = {
            "up": "\x1bOA",
            "down": "\x1bOB",
            "right": "\x1bOC",
            "left": "\x1bOD",
            "home": "\x1bOH",
            "end": "\x1b[F",
            "delete": "\x1b[3~",
            "pageup": "\x1b[5~",
            "pagedown": "\x1b[6~",
            "shift+tab": "\x1b[Z",
            "f1": "\x1bOP",
            "f2": "\x1bOQ",
            "f3": "\x1bOR",
            "f4": "\x1bOS",
            "f5": "\x1b[15~",
            "f6": "\x1b[17~",
            "f7": "\x1b[18~",
            "f8": "\x1b[19~",
            "f9": "\x1b[20~",
            "f10": "\x1b[21~",
            "f11": "\x1b[23~",
            "f12": "\x1b[24~",
            "f13": "\x1b[25~",
            "f14": "\x1b[26~",
            "f15": "\x1b[28~",
            "f16": "\x1b[29~",
            "f17": "\x1b[31~",
            "f18": "\x1b[32~",
            "f19": "\x1b[33~",
            "f20": "\x1b[34~",
            "ctrl+a": "\x01",
            "ctrl+b": "\x02",
            "ctrl+c": "\x03",
            "ctrl+d": "\x04",
            "ctrl+e": "\x05",
            "ctrl+f": "\x06",
            "ctrl+g": "\x07",
            "ctrl+h": "\x08",
            "ctrl+i": "\x09",
            "ctrl+j": "\x0a",
            "ctrl+k": "\x0b",
            "ctrl+l": "\x0c",
            "ctrl+m": "\x0d",
            "ctrl+n": "\x0e",
            "ctrl+o": "\x0f",
            "ctrl+p": "\x10",
            "ctrl+q": "\x11",
            "ctrl+r": "\x12",
            "ctrl+s": "\x13",
            "ctrl+t": "\x14",
            "ctrl+u": "\x15",
            "ctrl+v": "\x16",
            "ctrl+w": "\x17",
            "ctrl+x": "\x18",
            "ctrl+y": "\x19",
            "ctrl+z": "\x1a",
            "escape": "\x1b",
            "ctrl+[": "\x1b",
            "ctrl+\\": "\x1c",
            "ctrl+]": "\x1d",
            "ctrl+^": "\x1e",
            "ctrl+_": "\x1f",
        }

        self._display = self.initial_display()
        self._screen = TerminalPyteScreen(self.ncol, self.nrow)
        self.stream = pyte.Stream(self._screen)

    def start(self) -> None:
        """Start the terminal by connecting to the tmux session."""
        if self.emulator is not None:
            return

        debug_log(f"Starting TmuxTerminal for session: {self.tmux_session}", "info")

        self.emulator = TmuxTerminalEmulator(
            tmux_session=self.tmux_session,
            cols=self.ncol,
            rows=self.nrow
        )
        self.emulator.start()
        self.send_queue = self.emulator.recv_queue
        self.recv_queue = self.emulator.send_queue
        self.recv_task = asyncio.create_task(self.recv())

    def stop(self) -> None:
        """Stop the terminal (detach from tmux, don't kill session)."""
        if self.emulator is None:
            return

        debug_log(f"Stopping TmuxTerminal for session: {self.tmux_session}", "info")

        self._display = self.initial_display()

        if self.recv_task:
            self.recv_task.cancel()

        self.emulator.stop()
        self.emulator = None

    @property
    def is_connected(self) -> bool:
        """Check if connected to a tmux session."""
        return self.emulator is not None

    async def on_resize(self, event: events.Resize) -> None:
        """Handle resize - also resize tmux."""
        if self.emulator is None:
            return

        self.ncol = self.size.width
        self.nrow = self.size.height
        await self.send_queue.put(["set_size", self.nrow, self.ncol])
        self._screen.resize(self.nrow, self.ncol)

    def send_data(self, data: str) -> None:
        """Send data to the terminal."""
        if self.emulator and self.send_queue:
            asyncio.create_task(self.send_queue.put(["stdin", data]))

    # Output capture methods
    def get_output_lines(self, count: Optional[int] = None) -> List[str]:
        """Get recent output lines from the buffer."""
        if self.emulator is None:
            return []
        return self.emulator.output_buffer.get_lines(count)

    def get_output_raw(self, count: Optional[int] = None) -> str:
        """Get raw output from the buffer."""
        if self.emulator is None:
            return ""
        return self.emulator.output_buffer.get_raw(count)

    def search_output(self, pattern: str, case_sensitive: bool = False) -> List[Dict]:
        """Search output buffer for a pattern."""
        if self.emulator is None:
            return []
        return self.emulator.output_buffer.search(pattern, case_sensitive)

    def clear_output_buffer(self) -> None:
        """Clear the output buffer."""
        if self.emulator is not None:
            self.emulator.output_buffer.clear()

    def get_output_stats(self) -> Dict:
        """Get output buffer statistics."""
        if self.emulator is None:
            return {"line_count": 0, "char_count": 0, "connected": False}
        return {
            "line_count": self.emulator.output_buffer.line_count,
            "char_count": self.emulator.output_buffer.char_count,
            "connected": True,
            "session": self.tmux_session
        }


def check_tmux_available() -> bool:
    """Check if tmux is installed and available."""
    try:
        result = subprocess.run(
            ["tmux", "-V"],
            capture_output=True,
            timeout=5
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
