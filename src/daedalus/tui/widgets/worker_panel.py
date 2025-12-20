"""
WorkerPanel - Displays output from a single Icarus worker.

Watches a log file and streams its content with status indication.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

from rich.text import Text

from textual.widget import Widget
from textual.widgets import Static, RichLog
from textual.containers import Vertical
from textual.reactive import reactive
from textual import on


class WorkerStatus:
    """Worker status constants."""
    IDLE = "idle"
    WORKING = "working"
    COMPLETE = "complete"
    FAILED = "failed"


STATUS_STYLES = {
    WorkerStatus.IDLE: ("⏸", "#6272a4"),      # Gray - waiting
    WorkerStatus.WORKING: ("▶", "#50fa7b"),   # Green - active
    WorkerStatus.COMPLETE: ("✓", "#8be9fd"),  # Cyan - done
    WorkerStatus.FAILED: ("✗", "#ff5555"),    # Red - error
}


class WorkerPanel(Widget):
    """
    A panel displaying output from a single Icarus worker.

    Watches a log file and streams content to a scrollable log view.
    """

    DEFAULT_CSS = """
    WorkerPanel {
        height: 100%;
        width: 1fr;
        border: solid #444;
        padding: 0;
    }

    WorkerPanel > .worker-header {
        height: 1;
        background: #282a36;
        padding: 0 1;
    }

    WorkerPanel > .worker-log {
        height: 1fr;
        background: #1e1e2e;
        padding: 0;
        scrollbar-gutter: stable;
    }

    WorkerPanel.-working {
        border: solid #50fa7b;
    }

    WorkerPanel.-complete {
        border: solid #8be9fd;
    }

    WorkerPanel.-failed {
        border: solid #ff5555;
    }
    """

    status: reactive[str] = reactive(WorkerStatus.IDLE)

    def __init__(
        self,
        worker_id: str,
        log_path: Path,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(name=name, id=id, classes=classes)
        self.worker_id = worker_id
        self.log_path = log_path
        self._file_position = 0
        self._watch_task: Optional[asyncio.Task] = None
        self._last_line = ""

    def compose(self):
        """Create the panel layout."""
        icon, color = STATUS_STYLES[self.status]
        header_text = Text()
        header_text.append(f"{icon} ", style=color)
        header_text.append(self.worker_id, style="bold")

        yield Static(header_text, classes="worker-header", id=f"header-{self.worker_id}")
        yield RichLog(
            highlight=True,
            markup=True,
            wrap=True,
            classes="worker-log",
            id=f"log-{self.worker_id}"
        )

    def on_mount(self) -> None:
        """Start watching the log file."""
        self._watch_task = asyncio.create_task(self._watch_log())

    def on_unmount(self) -> None:
        """Stop watching the log file."""
        if self._watch_task:
            self._watch_task.cancel()

    async def _watch_log(self) -> None:
        """Watch the log file for new content and stream it."""
        try:
            # Initial read of existing content
            if self.log_path.exists():
                await self._read_new_content()

            # Continue watching for updates
            while True:
                await asyncio.sleep(0.25)  # Poll every 250ms
                if self.log_path.exists():
                    await self._read_new_content()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            log_widget = self.query_one(f"#log-{self.worker_id}", RichLog)
            log_widget.write(f"[red]Error watching log: {e}[/red]")

    async def _read_new_content(self) -> None:
        """Read new content from the log file."""
        try:
            current_size = self.log_path.stat().st_size
            if current_size <= self._file_position:
                return

            with open(self.log_path, 'r', errors='replace') as f:
                f.seek(self._file_position)
                new_content = f.read()
                self._file_position = f.tell()

            if new_content:
                log_widget = self.query_one(f"#log-{self.worker_id}", RichLog)

                # Parse content for status updates
                for line in new_content.splitlines():
                    if line.strip():
                        # Detect status from content
                        self._detect_status(line)

                        # Style special lines
                        styled_line = self._style_line(line)
                        log_widget.write(styled_line)

        except Exception as e:
            pass  # Silently handle file access errors

    def _detect_status(self, line: str) -> None:
        """Detect worker status from log line content."""
        line_lower = line.lower()

        if "error" in line_lower or "failed" in line_lower or "exception" in line_lower:
            self.status = WorkerStatus.FAILED
        elif "complete" in line_lower or "finished" in line_lower or "success" in line_lower:
            self.status = WorkerStatus.COMPLETE
        elif "executing" in line_lower or "working" in line_lower or ">>> tool" in line_lower:
            self.status = WorkerStatus.WORKING

    def _style_line(self, line: str) -> Text:
        """Apply styling to a log line based on content."""
        text = Text()

        # Tool invocations
        if line.startswith(">>> Tool:"):
            text.append(line, style="bold cyan")
        # Tool results
        elif line.startswith("<<<"):
            text.append(line, style="dim")
        # Icarus system messages
        elif line.startswith("[Icarus]"):
            text.append(line, style="green")
        # Errors
        elif "error" in line.lower() or "Error" in line:
            text.append(line, style="red")
        # Permission requests
        elif "permission" in line.lower() or "Permission" in line:
            text.append(line, style="yellow bold")
        # Separator lines
        elif line.startswith("===") or line.startswith("---"):
            text.append(line, style="dim cyan")
        # Default
        else:
            text.append(line)

        return text

    def watch_status(self, old_status: str, new_status: str) -> None:
        """React to status changes."""
        # Update CSS classes
        self.remove_class(f"-{old_status}")
        self.add_class(f"-{new_status}")

        # Update header
        try:
            header = self.query_one(f"#header-{self.worker_id}", Static)
            icon, color = STATUS_STYLES[new_status]
            header_text = Text()
            header_text.append(f"{icon} ", style=color)
            header_text.append(self.worker_id, style="bold")
            header.update(header_text)
        except Exception:
            pass  # Widget may not be mounted yet
