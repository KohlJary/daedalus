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
    # Enter with a modifier is a newline in Claude Code's input, not a submit (sent as meta-enter)
    "shift+enter": b"\x1b\r", "alt+enter": b"\x1b\r", "ctrl+enter": b"\x1b\r",
    "ctrl+up": b"\x1b[1;5A", "ctrl+down": b"\x1b[1;5B", "ctrl+right": b"\x1b[1;5C", "ctrl+left": b"\x1b[1;5D",
    "shift+up": b"\x1b[1;2A", "shift+down": b"\x1b[1;2B", "shift+right": b"\x1b[1;2C", "shift+left": b"\x1b[1;2D",
    "alt+up": b"\x1b[1;3A", "alt+down": b"\x1b[1;3B", "alt+right": b"\x1b[1;3C", "alt+left": b"\x1b[1;3D",
    "f1": b"\x1bOP", "f2": b"\x1bOQ", "f3": b"\x1bOR", "f4": b"\x1bOS", "f5": b"\x1b[15~", "f6": b"\x1b[17~",
    "f7": b"\x1b[18~", "f8": b"\x1b[19~", "f9": b"\x1b[20~", "f10": b"\x1b[21~", "f11": b"\x1b[23~",
    "f12": b"\x1b[24~",
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
    if event.key.startswith("alt+"):  # meta: ESC, then the key
        rest = event.key[4:]
        if len(rest) == 1:
            return b"\x1b" + rest.encode("utf-8")
        if rest.startswith("ctrl+") and len(rest) == 6 and rest[-1].isalpha():
            return b"\x1b" + bytes([ord(rest[-1].lower()) - 96])
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
        """Sessions on the backend that belong to this project."""
        try:
            return [n for n in self.backend.list() if n == self.session_name]
        except Exception:
            return []

    def _pump(self) -> None:
        if self.session is None:
            return
        self._ticks = getattr(self, "_ticks", 0) + 1
        if self._ticks % 20 == 0 and not self.session.alive():
            # Claude exited (or the tmux session ended): back to "no session", so n and a work again (Momus F6)
            self.session.close()
            self.session = None
            self.error = "The Claude session ended. n starts a new one."
            self.post_message(self.Status("ended"))
            self.refresh()
            return
        data = self.session.read(0)
        if data:
            try:
                self._stream.feed(data)
            except Exception:  # pyte chokes on some sequences (e.g. CSI 1;5D); one odd chunk mustn't freeze the pane
                pass
            self.post_message(self.Status("working"))
            self.refresh()

    def paste(self, text: str) -> None:
        """Put text in Claude's input without submitting it (no trailing newline)."""
        if self.session is None:
            return
        self.session.write(text.rstrip("\r\n").encode("utf-8"))

    def on_paste(self, event: events.Paste) -> None:
        """A terminal paste goes to Claude as a bracketed paste, so newlines in it don't submit (Momus F4)."""
        if self.session is not None:
            self.session.write(b"\x1b[200~" + event.text.encode("utf-8") + b"\x1b[201~")
        event.stop()
        event.prevent_default()

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
                if event.key == "n":
                    self.start_session()
                elif self.session_name in self.existing():
                    self.attach_session(self.session_name)  # only this project's session, never another's (F5)
                else:
                    self.error = "There's no session for this project to attach to. n starts one."
                    self.refresh()
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
            from pathlib import Path

            where = str(Path(self.cwd).resolve()).replace(str(Path.home()), "~", 1)
            msg = (f"\n  No Claude session for this project.\n\n  n  new session in {where}\n"
                   + (f"  a  attach the existing one ({self.session_name})\n" if found else ""))
            if self.error:
                msg += f"\n  ⚠ {self.error}\n"
            out.append(msg)
            return out
        if not self.session.persistent:
            reason = f" ({self.fallback_reason})" if self.fallback_reason else ""
            out.append(f"⚠ no persistent backend{reason}: this session ends when the TUI quits\n", style="bold")
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
