"""
◆ClaudePane: a real Claude Code session, rendered through a terminal emulator (pyte).

While it has focus, every key goes to Claude except the escape chord (`tui.escape`, default ctrl+]).
It never binds a priority key, so nothing is stolen from the terminal. Text sent from the dashboard is
pasted into Claude's input without a newline: a person presses enter.
"""

from __future__ import annotations

from typing import Optional

from rich.style import Style
from rich.text import Text
from textual import events
from textual.message import Message
from textual.widget import Widget

from ..session import Backend, Session, SessionError

# Textual key names -> the bytes a terminal sends
KEYS = {
    "enter": b"\r", "tab": b"\t", "shift+tab": b"\x1b[Z", "backspace": b"\x7f", "escape": b"\x1b",
    "up": b"\x1b[A", "down": b"\x1b[B", "right": b"\x1b[C", "left": b"\x1b[D", "home": b"\x1b[H",
    "end": b"\x1b[F", "pageup": b"\x1b[5~", "pagedown": b"\x1b[6~", "delete": b"\x1b[3~", "insert": b"\x1b[2~",
    "space": b" ",
}
COLOURS = {"default": None, "black": "black", "red": "red", "green": "green", "brown": "yellow", "yellow": "yellow",
           "blue": "blue", "magenta": "magenta", "cyan": "cyan", "white": "white"}


def escape_key(setting: str) -> str:
    """`ctrl+]` (config) -> `ctrl+right_square_bracket` (Textual's name for it)."""
    names = {"]": "right_square_bracket", "[": "left_square_bracket", "\\": "backslash", "^": "circumflex_accent",
             "_": "underscore"}
    mod, _, key = setting.rpartition("+")
    return f"{mod}+{names.get(key, key)}" if mod else names.get(key, key)


def key_bytes(event: events.Key) -> Optional[bytes]:
    if event.key in KEYS:
        return KEYS[event.key]
    if event.key.startswith("ctrl+") and len(event.key) == 6 and event.key[-1].isalpha():
        return bytes([ord(event.key[-1].lower()) - 96])
    if event.character:
        return event.character.encode("utf-8")
    return None


class ClaudePane(Widget, can_focus=True):
    DEFAULT_CSS = """
    ClaudePane {
        border: round $panel;
        height: 1fr;
        width: 2fr;
    }
    ClaudePane:focus {
        border: round $accent;
    }
    """

    class Escape(Message):
        """The escape chord: give focus back to the dashboard."""

    class Status(Message):
        def __init__(self, status: str):
            super().__init__()
            self.status = status

    def __init__(self, backend: Backend, session_name: str, cwd, command: list[str], escape: str = "ctrl+]",
                 fallback_reason: Optional[str] = None, **kw):
        super().__init__(**kw)
        self.backend, self.session_name, self.cwd, self.command = backend, session_name, cwd, command
        self.escape_setting = escape
        self.escape_key = escape_key(escape)
        self.fallback_reason = fallback_reason
        self.session: Optional[Session] = None
        self._screen = None
        self._stream = None
        self.error: Optional[str] = None

    # ----- session lifecycle -----

    def _term_size(self) -> tuple[int, int]:
        return max(self.size.width - 2, 20), max(self.size.height - 3, 5)

    def _emulator(self, cols: int, rows: int) -> None:
        import pyte

        self._screen = pyte.Screen(cols, rows)
        self._stream = pyte.ByteStream(self._screen)

    def start_session(self) -> None:
        cols, rows = self._term_size()
        try:
            self.session = self.backend.start(self.session_name, self.command, self.cwd, cols, rows)
        except (SessionError, OSError) as e:
            self.error = str(e)
            self.refresh()
            return
        self._after_open(cols, rows)

    def attach_session(self, name: Optional[str] = None) -> None:
        cols, rows = self._term_size()
        try:
            self.session = self.backend.attach(name or self.session_name, cols, rows)
        except (SessionError, OSError) as e:
            self.error = str(e)
            self.refresh()
            return
        self._after_open(cols, rows)

    def _after_open(self, cols: int, rows: int) -> None:
        self.error = None
        self._emulator(cols, rows)
        self.post_message(self.Status("idle"))
        self.set_interval(0.05, self._pump)
        self.refresh()

    def existing(self) -> list[str]:
        try:
            return self.backend.list()
        except Exception:
            return []

    def _pump(self) -> None:
        if self.session is None:
            return
        data = self.session.read(0)
        if data:
            self._stream.feed(data)
            self.post_message(self.Status("working"))
            self.refresh()

    def paste(self, text: str) -> None:
        """Put text in Claude's input without submitting it (no trailing newline)."""
        if self.session is None:
            return
        self.session.write(text.rstrip("\r\n").encode("utf-8"))

    def on_resize(self, event: events.Resize) -> None:
        if self.session is not None and self._screen is not None:
            cols, rows = self._term_size()
            self._screen.resize(rows, cols)
            self.session.resize(cols, rows)

    def on_unmount(self) -> None:
        if self.session is not None:
            self.session.close()

    # ----- keys -----

    def on_key(self, event: events.Key) -> None:
        if event.key == self.escape_key:
            event.stop()
            event.prevent_default()
            self.post_message(self.Escape())
            return
        if self.session is None:
            if event.key in ("n", "a"):
                event.stop()
                event.prevent_default()
                self.start_session() if event.key == "n" else self.attach_session(
                    (self.existing() or [self.session_name])[0])
            return
        data = key_bytes(event)
        if data is not None:
            self.session.write(data)
        # Every key goes to Claude: nothing bubbles to the dashboard's bindings
        event.stop()
        event.prevent_default()

    # ----- drawing -----

    def _title(self) -> str:
        if self.session is None:
            return "Claude" + " " * 10 + "○ no session"
        kind = f"session {self.session.name}" if self.session.persistent else "plain PTY"
        return f"Claude · {kind}"

    def render(self) -> Text:
        out = Text(self._title() + "\n", style="bold")
        if self.session is None:
            found = self.existing()
            msg = (f"\n  No Claude session for this project.\n\n  n  new session in {self.cwd}\n"
                   f"  a  attach an existing one ({len(found)} found)\n")
            if self.error:
                msg += f"\n  ⚠ {self.error}\n"
            out.append(msg)
            return out
        if not self.session.persistent:
            reason = f" ({self.fallback_reason})" if self.fallback_reason else ""
            out.append(f"⚠ no persistent backend{reason}: this session ends when the TUI quits\n", style="yellow")
        if self._screen is None:
            return out
        buf = self._screen.buffer
        for y in range(self._screen.lines):
            row = buf[y]
            line = Text()
            for x in range(self._screen.columns):
                ch = row[x]
                fg = COLOURS.get(ch.fg, None) if ch.fg in COLOURS else (f"#{ch.fg}" if len(ch.fg) == 6 else None)
                bg = COLOURS.get(ch.bg, None) if ch.bg in COLOURS else (f"#{ch.bg}" if len(ch.bg) == 6 else None)
                line.append(ch.data or " ", Style(color=fg, bgcolor=bg, bold=ch.bold, reverse=ch.reverse,
                                                  underline=ch.underscore))
            if y != self._screen.cursor.y:
                line.rstrip()
            out.append_text(line)
            out.append("\n")
        return out

    def screen_text(self) -> str:
        """What the terminal shows, as plain text (tests)."""
        return "\n".join(self._screen.display) if self._screen else ""
