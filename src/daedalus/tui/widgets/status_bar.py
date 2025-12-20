"""
Daedalus Status Bar - Bottom bar showing worker count, bus status, active work.

Updates periodically via timer to reflect current bus state.
"""

from textual.app import ComposeResult
from textual.widgets import Static
from textual.containers import Horizontal
from textual.reactive import reactive

from ...bus import IcarusBus


class StatusBar(Static):
    """
    Status bar widget showing bus status.

    Displays:
    - Bus status (initialized or not)
    - Worker count and status breakdown
    - Work packages (pending / in-progress / completed)
    - Pending requests needing attention
    """

    # Reactive properties for status values
    bus_initialized: reactive[bool] = reactive(False)
    worker_count: reactive[int] = reactive(0)
    workers_by_status: reactive[dict] = reactive({})
    work_pending: reactive[int] = reactive(0)
    work_claimed: reactive[int] = reactive(0)
    work_completed: reactive[int] = reactive(0)
    requests_pending: reactive[int] = reactive(0)

    # Update interval in seconds
    UPDATE_INTERVAL = 1.0

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.bus = IcarusBus()

    def compose(self) -> ComposeResult:
        """Compose the status bar content."""
        with Horizontal(id="status-bar-content"):
            yield Static(id="bus-status")
            yield Static(id="worker-status")
            yield Static(id="work-status")
            yield Static(id="request-status")

    def on_mount(self) -> None:
        """Start periodic status updates."""
        self._update_status()
        self.set_interval(self.UPDATE_INTERVAL, self._update_status)

    def _update_status(self) -> None:
        """Fetch and update status from bus."""
        if not self.bus.is_initialized():
            self.bus_initialized = False
            self._render_status()
            return

        self.bus_initialized = True
        summary = self.bus.status_summary()

        # Update reactive properties
        inst = summary.get("instances", {})
        self.worker_count = inst.get("total", 0)
        self.workers_by_status = inst.get("by_status", {})

        work = summary.get("work", {})
        self.work_pending = work.get("pending", 0)
        self.work_claimed = work.get("claimed", 0)
        self.work_completed = work.get("completed", 0)

        reqs = summary.get("requests", {})
        self.requests_pending = reqs.get("pending", 0)

        self._render_status()

    def _render_status(self) -> None:
        """Render status to child widgets."""
        # Bus status
        bus_widget = self.query_one("#bus-status", Static)
        if self.bus_initialized:
            bus_widget.update(" BUS: [green]ON[/] ")
        else:
            bus_widget.update(" BUS: [dim]OFF[/] ")

        # Worker status
        worker_widget = self.query_one("#worker-status", Static)
        if self.worker_count > 0:
            # Build status breakdown
            status_parts = []
            for status, count in self.workers_by_status.items():
                if count > 0:
                    if status == "working":
                        status_parts.append(f"[green]{count}w[/]")
                    elif status == "idle":
                        status_parts.append(f"[yellow]{count}i[/]")
                    elif status == "blocked":
                        status_parts.append(f"[red]{count}b[/]")
                    else:
                        status_parts.append(f"{count}{status[0]}")

            breakdown = "/".join(status_parts) if status_parts else ""
            worker_widget.update(f" Workers: {self.worker_count} ({breakdown}) ")
        else:
            worker_widget.update(" Workers: [dim]0[/] ")

        # Work status
        work_widget = self.query_one("#work-status", Static)
        work_parts = []
        if self.work_pending > 0:
            work_parts.append(f"[yellow]{self.work_pending}p[/]")
        if self.work_claimed > 0:
            work_parts.append(f"[cyan]{self.work_claimed}a[/]")
        if self.work_completed > 0:
            work_parts.append(f"[green]{self.work_completed}d[/]")

        if work_parts:
            work_widget.update(f" Work: {'/'.join(work_parts)} ")
        else:
            work_widget.update(" Work: [dim]none[/] ")

        # Request status
        request_widget = self.query_one("#request-status", Static)
        if self.requests_pending > 0:
            request_widget.update(f" [bold red]Requests: {self.requests_pending}[/] ")
        else:
            request_widget.update(" Requests: [dim]0[/] ")

    def refresh_now(self) -> None:
        """Force an immediate status refresh."""
        self._update_status()
