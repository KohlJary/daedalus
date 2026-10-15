"""
How the Claude pane hosts its Claude Code session (edict 0012): behind a small backend interface, so the
mechanism can change without touching anything else.

- `TmuxBackend`: the session lives in a tmux server, so it survives the TUI exiting and can be reached from
  a plain terminal (`tmux attach -t <name>`). The pane runs a tmux *client* in a PTY. The session gets its
  own settings so tmux keeps out of the way: no status bar, no prefix key (so no key is stolen from Claude),
  mouse off. Its socket is `daedalus`, separate from the user's own tmux.
- `PtyBackend`: the fallback, always available on POSIX: Claude Code runs as a child in a PTY and ends when
  the TUI does. The pane says so.
- `FakeBackend`: in-memory, for tests.

`daedalus tui` picks the backend from `tui.backend` (auto: tmux when it is installed, else the PTY). The
choice and why are recorded in .daedalus/decisions.md by the PR that made it.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

TMUX_SOCKET = "daedalus"


class SessionError(Exception):
    pass


class Session(ABC):
    name: str
    persistent: bool

    @abstractmethod
    def read(self, timeout: float = 0.05) -> bytes:
        """Output since the last read (b"" when there is none within timeout)."""

    @abstractmethod
    def write(self, data: bytes) -> None: ...

    @abstractmethod
    def resize(self, cols: int, rows: int) -> None: ...

    @abstractmethod
    def alive(self) -> bool: ...

    @abstractmethod
    def close(self) -> None:
        """Stop showing the session. For a persistent backend the session itself keeps running."""


class Backend(ABC):
    name: str
    persistent: bool

    @abstractmethod
    def available(self) -> bool: ...

    @abstractmethod
    def start(self, name: str, command: list[str], cwd: Path, cols: int, rows: int) -> Session: ...

    def attach(self, name: str, cols: int, rows: int) -> Session:
        raise SessionError(f"The {self.name} backend can't attach to an existing session")

    def list(self) -> list[str]:
        return []


# ---------- PTY ----------

class PtySession(Session):
    persistent = False

    def __init__(self, name: str, command: list[str], cwd: Path, cols: int, rows: int, env: Optional[dict] = None):
        import pty

        self.name = name
        pid, fd = pty.fork()
        if pid == 0:  # child
            try:
                os.chdir(cwd)
                os.environ.update(env or {})
                os.environ.setdefault("TERM", "xterm-256color")
                os.execvp(command[0], command)
            except Exception as e:  # pragma: no cover - in the child
                sys.stderr.write(f"daedalus tui: couldn't start {command[0]}: {e}\n")
                os._exit(127)
        self.pid, self.fd = pid, fd
        os.set_blocking(fd, False)
        self.resize(cols, rows)
        self._exited = False

    def read(self, timeout: float = 0.05) -> bytes:
        import select

        if self._exited:
            return b""
        try:
            ready, _, _ = select.select([self.fd], [], [], timeout)
            if not ready:
                return b""
            return os.read(self.fd, 65536)
        except (OSError, ValueError):
            self._exited = True
            return b""

    def write(self, data: bytes) -> None:
        view = memoryview(data)
        while view:
            try:
                n = os.write(self.fd, view)
            except BlockingIOError:
                import select

                select.select([], [self.fd], [], 1.0)
                continue
            except OSError:
                return
            view = view[n:]

    def resize(self, cols: int, rows: int) -> None:
        import fcntl
        import struct
        import termios

        try:
            fcntl.ioctl(self.fd, termios.TIOCSWINSZ, struct.pack("HHHH", max(rows, 1), max(cols, 1), 0, 0))
        except OSError:
            pass

    def alive(self) -> bool:
        if self._exited:
            return False
        try:
            pid, _ = os.waitpid(self.pid, os.WNOHANG)
        except ChildProcessError:
            pid = self.pid
        if pid == self.pid:
            self._exited = True
        return not self._exited

    def close(self) -> None:
        if self.alive():
            try:
                os.kill(self.pid, 15)
            except OSError:
                pass
        try:
            os.close(self.fd)
        except OSError:
            pass
        self._exited = True


class PtyBackend(Backend):
    name = "pty"
    persistent = False

    def available(self) -> bool:
        return sys.platform != "win32"

    def start(self, name: str, command: list[str], cwd: Path, cols: int, rows: int) -> Session:
        if not self.available():
            raise SessionError("The PTY backend needs a POSIX system (Windows isn't supported in v1)")
        if not shutil.which(command[0]):
            raise SessionError(f"`{command[0]}` isn't on PATH, so there's nothing to start (is Claude Code installed?)")
        return PtySession(name, command, cwd, cols, rows)


# ---------- tmux ----------

class TmuxBackend(Backend):
    name = "tmux"
    persistent = True

    def __init__(self, socket: str = TMUX_SOCKET):
        self.socket = socket

    def _tmux(self, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        out = subprocess.run(["tmux", "-L", self.socket, *args], capture_output=True, text=True, timeout=10)
        if check and out.returncode != 0:
            raise SessionError(f"tmux {' '.join(args[:2])}: {out.stderr.strip() or out.returncode}")
        return out

    def available(self) -> bool:
        return shutil.which("tmux") is not None and sys.platform != "win32"

    def list(self) -> list[str]:
        if not self.available():
            return []
        out = self._tmux("list-sessions", "-F", "#{session_name}", check=False)
        return [s for s in out.stdout.split() if s] if out.returncode == 0 else []

    def _quiet(self, name: str) -> None:
        # Keep tmux out of Claude's way: no status bar, no prefix (so no key is stolen), no mouse capture
        for opt, value in (("status", "off"), ("prefix", "None"), ("prefix2", "None"), ("mouse", "off"),
                           ("escape-time", "0")):
            self._tmux("set-option", "-t", name, opt, value, check=False)

    def start(self, name: str, command: list[str], cwd: Path, cols: int, rows: int) -> Session:
        if name in self.list():
            return self.attach(name, cols, rows)
        if not shutil.which(command[0]):
            raise SessionError(f"`{command[0]}` isn't on PATH, so there's nothing to start (is Claude Code installed?)")
        self._tmux("-f", os.devnull, "new-session", "-d", "-s", name, "-x", str(cols), "-y", str(rows),
                   "-c", str(cwd), *command)
        self._quiet(name)
        return self.attach(name, cols, rows)

    def attach(self, name: str, cols: int, rows: int) -> Session:
        if name not in self.list():
            raise SessionError(f"No tmux session '{name}' (socket {self.socket})")
        self._quiet(name)
        client = PtySession(name, ["tmux", "-L", self.socket, "attach-session", "-t", name], Path.cwd(), cols, rows)
        client.persistent = True
        return client

    def kill(self, name: str) -> None:
        self._tmux("kill-session", "-t", name, check=False)


# ---------- fake (tests) ----------

class FakeSession(Session):
    def __init__(self, name: str, persistent: bool, store: dict):
        self.name, self.persistent, self._store = name, persistent, store
        self.received = store.setdefault(name, {"received": b"", "out": b"", "alive": True})
        self.cols = self.rows = 0

    def read(self, timeout: float = 0.05) -> bytes:
        out, self.received["out"] = self.received["out"], b""
        return out

    def write(self, data: bytes) -> None:
        self.received["received"] += data
        self.received["out"] += data  # echo, like a terminal in cooked mode

    def resize(self, cols: int, rows: int) -> None:
        self.cols, self.rows = cols, rows

    def alive(self) -> bool:
        return self.received["alive"]

    def close(self) -> None:
        if not self.persistent:
            self.received["alive"] = False


class FakeBackend(Backend):
    """Sessions live in a dict that outlives any one TUI, as a multiplexer's would (when persistent)."""

    name = "fake"

    def __init__(self, persistent: bool = True, store: Optional[dict] = None):
        self.persistent = persistent
        self.store = store if store is not None else {}
        self.started: list = []

    def available(self) -> bool:
        return True

    def list(self) -> list[str]:
        return [n for n, s in self.store.items() if s["alive"]] if self.persistent else []

    def start(self, name: str, command: list[str], cwd: Path, cols: int, rows: int) -> Session:
        self.started.append((name, command, str(cwd)))
        if self.persistent and name in self.list():
            return self.attach(name, cols, rows)
        self.store[name] = {"received": b"", "out": b"", "alive": True}
        session = FakeSession(name, self.persistent, self.store)
        session.resize(cols, rows)
        return session

    def attach(self, name: str, cols: int, rows: int) -> Session:
        if name not in self.list():
            raise SessionError(f"No session {name}")
        session = FakeSession(name, self.persistent, self.store)
        session.resize(cols, rows)
        return session


def choose_backend(setting: str = "auto") -> tuple[Backend, Optional[str]]:
    """(backend, why the fallback was used, or None)."""
    tmux, pty = TmuxBackend(), PtyBackend()
    if setting == "pty":
        return pty, "tui.backend is pty"
    if setting in ("auto", "tmux"):
        if tmux.available():
            return tmux, None
        return pty, "tmux isn't installed"
    return pty, f"unknown tui.backend {setting!r}"


def session_name(project_dir: Path) -> str:
    """One Claude session per project: daedalus-<folder name>-<6 hex of the full path>, safe for tmux. Two
    projects with the same folder name (or names that sanitise alike) get different sessions (Momus F5)."""
    import hashlib
    import re

    resolved = Path(project_dir).resolve()
    tag = hashlib.sha1(str(resolved).encode("utf-8")).hexdigest()[:6]
    return f"daedalus-{re.sub(r'[^A-Za-z0-9_-]', '-', resolved.name)[:40]}-{tag}"
