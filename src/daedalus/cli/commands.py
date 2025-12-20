"""
Daedalus CLI Commands.

Contains the main Daedalus orchestrator class with all command implementations.
"""

import os
import time

from .config import (
    DaedalusConfig,
    get_config,
    tmux_session_exists,
    tmux_run,
    tmux_send_keys,
    tmux_pane_count,
)
from ..bus import IcarusBus, WorkPackage, Response


class Daedalus:
    """Main orchestrator class."""

    def __init__(self, config: DaedalusConfig = None):
        self.config = config or get_config()
        self.bus = IcarusBus()

    # -------------------------------------------------------------------------
    # Session Management
    # -------------------------------------------------------------------------

    def create_workspace(self) -> bool:
        """Create new Daedalus workspace with full layout."""
        cfg = self.config

        if tmux_session_exists(cfg.session_name):
            print(f"Session '{cfg.session_name}' already exists.")
            print(f"Use: daedalus attach")
            return False

        print(f"Creating Daedalus workspace...")

        # Initialize the bus
        self.bus.initialize()
        print(f"  Bus initialized at {self.bus.root}")

        # Create swarm session first
        self._create_swarm_session()

        # Create main session
        tmux_run([
            "new-session", "-d",
            "-s", cfg.session_name,
            "-c", cfg.project_dir,
            "-x", "200", "-y", "50"
        ])

        # Split for lazygit at bottom (25% height)
        tmux_run(["split-window", "-t", cfg.session_name, "-v", "-p", "25", "-c", cfg.project_dir])
        tmux_send_keys(f"{cfg.session_name}:0.1", "lazygit")

        # Select top pane and split for Icarus swarm (60% width on right)
        tmux_run(["select-pane", "-t", f"{cfg.session_name}:0.0"])
        tmux_run(["split-window", "-t", cfg.session_name, "-h", "-p", "60", "-c", cfg.project_dir])

        # Right pane - attach to swarm session
        tmux_send_keys(
            f"{cfg.session_name}:0.1",
            f"tmux attach -t {cfg.swarm_session}"
        )

        # Left pane - start Claude for Daedalus
        # Small delay to let shell initialize before sending command
        time.sleep(0.3)
        tmux_run(["select-pane", "-t", f"{cfg.session_name}:0.0"])
        tmux_send_keys(f"{cfg.session_name}:0.0", "claude")

        print(f"  Workspace created!")
        print(f"  Layout: Daedalus (left) | Icarus Swarm (right) | lazygit (bottom)")

        return True

    def _create_swarm_session(self) -> None:
        """Create the Icarus swarm session."""
        cfg = self.config

        if tmux_session_exists(cfg.swarm_session):
            print(f"  Swarm session already exists")
            return

        tmux_run([
            "new-session", "-d",
            "-s", cfg.swarm_session,
            "-c", cfg.project_dir
        ])
        tmux_send_keys(
            cfg.swarm_session,
            "echo 'Icarus Swarm ready. Workers will appear here.'"
        )
        print(f"  Swarm session created: {cfg.swarm_session}")

    def attach(self) -> None:
        """Attach to existing Daedalus session."""
        cfg = self.config

        if not tmux_session_exists(cfg.session_name):
            print(f"No session '{cfg.session_name}' found.")
            print("Run: daedalus new")
            return

        os.execvp("tmux", ["tmux", "attach", "-t", cfg.session_name])

    def status(self) -> None:
        """Show detailed workspace status."""
        cfg = self.config

        print("=" * 60)
        print("  DAEDALUS WORKSPACE STATUS")
        print("=" * 60)
        print()

        # Session status
        main_active = tmux_session_exists(cfg.session_name)
        swarm_active = tmux_session_exists(cfg.swarm_session)

        print("Sessions:")
        status_str = "\033[92mactive\033[0m" if main_active else "\033[93mnot running\033[0m"
        print(f"  Main ({cfg.session_name}): {status_str}")

        status_str = "\033[92mactive\033[0m" if swarm_active else "\033[93mnot running\033[0m"
        swarm_panes = tmux_pane_count(cfg.swarm_session) if swarm_active else 0
        print(f"  Swarm ({cfg.swarm_session}): {status_str} ({swarm_panes} panes)")

        print()

        # Bus status
        print("Icarus Bus:")
        if self.bus.is_initialized():
            summary = self.bus.status_summary()
            inst = summary["instances"]
            work = summary["work"]
            reqs = summary["requests"]

            print(f"  Instances: {inst['total']} total")
            if inst["total"] > 0:
                for status, count in inst["by_status"].items():
                    if count > 0:
                        print(f"    - {status}: {count}")

            print(f"  Work: {work['pending']} pending, {work['claimed']} in progress, {work['completed']} done")
            print(f"  Requests: {reqs['pending']} pending")
        else:
            print("  Not initialized")

        print()

        # Pending requests that need attention
        if self.bus.is_initialized():
            requests = self.bus.list_pending_requests()
            if requests:
                print("\033[93mPending Requests (need attention):\033[0m")
                for req in requests:
                    print(f"  [{req.type.value}] {req.message[:60]}")
                    print(f"    From: {req.instance_id} | ID: {req.id}")

    # -------------------------------------------------------------------------
    # Worker Management
    # -------------------------------------------------------------------------

    def spawn_workers(self, count: int = 1) -> None:
        """Spawn Icarus workers in the swarm."""
        cfg = self.config

        if not tmux_session_exists(cfg.swarm_session):
            print("Swarm session not found. Creating...")
            self._create_swarm_session()

        print(f"Spawning {count} Icarus worker(s)...")

        current_panes = tmux_pane_count(cfg.swarm_session)

        for i in range(count):
            if i == 0 and current_panes == 1:
                # First worker uses existing pane if it's the only one
                # Check if it's just the welcome message
                tmux_send_keys(f"{cfg.swarm_session}:0.0", "claude")
            else:
                # Create new pane
                tmux_run(["split-window", "-t", cfg.swarm_session, "-c", cfg.project_dir])
                tmux_send_keys(cfg.swarm_session, "claude")
                # Re-tile
                tmux_run(["select-layout", "-t", cfg.swarm_session, "tiled"])

        # Final tiling
        tmux_run(["select-layout", "-t", cfg.swarm_session, "tiled"])

        final_panes = tmux_pane_count(cfg.swarm_session)
        print(f"  Spawned {count} worker(s). Total panes: {final_panes}")

    def kill_swarm(self) -> None:
        """Kill all Icarus workers."""
        cfg = self.config

        if not tmux_session_exists(cfg.swarm_session):
            print("Swarm session not found.")
            return

        tmux_run(["kill-session", "-t", cfg.swarm_session], check=False)
        print("Swarm session terminated.")

    def detach(self) -> None:
        """Detach from the Daedalus session (leaves it running)."""
        cfg = self.config

        if not tmux_session_exists(cfg.session_name):
            print(f"No session '{cfg.session_name}' to detach from.")
            return

        # Send detach command to the session
        tmux_run(["detach-client", "-s", cfg.session_name], check=False)
        print(f"Detached from {cfg.session_name}. Session still running.")

    def exit_workspace(self) -> None:
        """Terminate the entire workspace (swarm + main session)."""
        cfg = self.config

        # Kill swarm first
        if tmux_session_exists(cfg.swarm_session):
            tmux_run(["kill-session", "-t", cfg.swarm_session], check=False)
            print(f"Terminated swarm session: {cfg.swarm_session}")

        # Kill main session
        if tmux_session_exists(cfg.session_name):
            tmux_run(["kill-session", "-t", cfg.session_name], check=False)
            print(f"Terminated main session: {cfg.session_name}")
        else:
            print(f"No session '{cfg.session_name}' found.")

        print("Workspace terminated.")

    # -------------------------------------------------------------------------
    # Work Management
    # -------------------------------------------------------------------------

    def dispatch_work(self, work_type: str, description: str, priority: int = 5) -> str:
        """Dispatch a work package to the queue."""
        if not self.bus.is_initialized():
            self.bus.initialize()

        work = WorkPackage(
            id="",
            type=work_type,
            description=description,
            inputs={},
            outputs={},
            priority=priority,
        )
        work_id = self.bus.post_work(work)
        print(f"Dispatched: {work_id}")
        print(f"  Type: {work_type}")
        print(f"  Priority: {priority}")
        print(f"  Description: {description[:80]}")
        return work_id

    def list_work(self) -> None:
        """List all work packages."""
        if not self.bus.is_initialized():
            print("Bus not initialized.")
            return

        pending = self.bus.list_pending_work()
        claimed = self.bus.list_claimed_work()
        results = self.bus.collect_results(clear=False)

        print("Pending Work:")
        if pending:
            for w in pending:
                print(f"  [{w.priority}] {w.id}: {w.description[:50]}")
        else:
            print("  (none)")

        print("\nIn Progress:")
        if claimed:
            for w in claimed:
                print(f"  {w.id}: {w.claimed_by} - {w.description[:50]}")
        else:
            print("  (none)")

        print("\nCompleted:")
        if results:
            for r in results:
                status = "OK" if r["result"].get("success") else "FAIL"
                print(f"  {r['work_id']}: [{status}] {r['instance_id']}")
        else:
            print("  (none)")

    def respond_to_request(self, request_id: str, decision: str, message: str) -> None:
        """Respond to a pending request."""
        response = Response(
            request_id=request_id,
            decision=decision,
            message=message,
        )
        self.bus.respond_to_request(request_id, response)
        print(f"Responded to {request_id}: {decision}")

    # -------------------------------------------------------------------------
    # Headless Worker Management
    # -------------------------------------------------------------------------

    def spawn_headless(self, count: int = 1, claim: bool = True) -> None:
        """
        Spawn headless Icarus workers (no interactive tmux).

        Workers run as background processes with permissions routed through bus.
        """
        import subprocess
        import sys

        if not self.bus.is_initialized():
            self.bus.initialize()

        print(f"Spawning {count} headless Icarus worker(s)...")

        pids = []
        for i in range(count):
            # Spawn worker as background process
            cmd = [
                sys.executable, "-m", "daedalus.worker",
                "--project", self.config.project_dir,
            ]
            if claim:
                cmd.append("--claim")

            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,  # Detach from terminal
            )
            pids.append(proc.pid)
            print(f"  Worker {i+1}: PID {proc.pid}")

        print(f"\nSpawned {count} headless workers.")
        print("Use 'daedalus monitor' to watch their progress and handle permission requests.")

    # -------------------------------------------------------------------------
    # Monitoring with Permission Handling
    # -------------------------------------------------------------------------

    def monitor(self, auto_approve: bool = False, interactive: bool = True) -> None:
        """
        Live monitoring view with permission request handling.

        Args:
            auto_approve: Auto-approve requests matching scope patterns
            interactive: Prompt for permission decisions interactively
        """
        from ..bus.permissions import (
            ApprovalScope,
            check_auto_approve,
            PermissionRequest,
            PermissionType,
        )

        print("Daedalus Monitor - press Ctrl+C to exit")
        print(f"Mode: {'auto-approve enabled' if auto_approve else 'manual approval'}")
        print()

        scope = ApprovalScope.default(self.config.project_dir)

        try:
            while True:
                # Check for pending permission requests
                requests = self.bus.list_pending_requests()

                for req in requests:
                    self._handle_request(req, scope, auto_approve, interactive)

                # Display status
                self._display_status()

                time.sleep(1)

        except KeyboardInterrupt:
            print("\nExiting monitor.")

    def _handle_request(self, req, scope, auto_approve: bool, interactive: bool) -> None:
        """Handle a single permission request."""
        from ..bus.permissions import (
            check_auto_approve,
            PermissionRequest,
            PermissionType,
        )

        context = req.context or {}
        perm_type = context.get("permission_type")
        tool_name = context.get("tool_name", "unknown")
        input_params = context.get("input_params", {})

        print()
        print("=" * 60)
        print(f"\033[93mPermission Request: {req.id}\033[0m")
        print(f"From: {req.instance_id}")
        print(f"Type: {perm_type}")
        print(f"Tool: {tool_name}")
        print(f"Message:\n{req.message}")
        print("=" * 60)

        # Try auto-approve if enabled
        if auto_approve and perm_type:
            perm_req = PermissionRequest(
                type=PermissionType(perm_type),
                tool_name=tool_name,
                input_params=input_params,
                work_id=req.work_id,
                instance_id=req.instance_id,
            )
            approved, deny_reason = check_auto_approve(perm_req, scope)

            if approved:
                print("\033[92m→ Auto-approved\033[0m")
                self._respond_approved(req.id)
                return

            if deny_reason:
                print(f"\033[91m→ Auto-denied: {deny_reason}\033[0m")
                self._respond_denied(req.id, deny_reason)
                return

        # Interactive handling
        if interactive:
            while True:
                choice = input("\n[A]pprove / [D]eny / [S]kip? ").strip().lower()
                if choice in ('a', 'approve'):
                    self._respond_approved(req.id)
                    print("\033[92m→ Approved\033[0m")
                    break
                elif choice in ('d', 'deny'):
                    reason = input("Reason: ").strip() or "Denied by Daedalus"
                    self._respond_denied(req.id, reason)
                    print(f"\033[91m→ Denied: {reason}\033[0m")
                    break
                elif choice in ('s', 'skip'):
                    print("→ Skipped (will ask again)")
                    break
                else:
                    print("Invalid choice. Enter A, D, or S.")
        else:
            print("→ Pending (non-interactive mode)")

    def _respond_approved(self, request_id: str) -> None:
        """Send approval response."""
        response = Response(
            request_id=request_id,
            decision="approved",
            message="Approved by Daedalus",
        )
        self.bus.respond_to_request(request_id, response)

    def _respond_denied(self, request_id: str, reason: str) -> None:
        """Send denial response."""
        response = Response(
            request_id=request_id,
            decision="denied",
            message=reason,
        )
        self.bus.respond_to_request(request_id, response)

    def _display_status(self) -> None:
        """Display compact status for monitor mode."""
        if not self.bus.is_initialized():
            return

        summary = self.bus.status_summary()
        inst = summary["instances"]
        work = summary["work"]
        reqs = summary["requests"]

        # Single line status
        status_line = (
            f"\r\033[K"  # Clear line
            f"Workers: {inst['total']} | "
            f"Work: {work['pending']}p/{work['claimed']}a/{work['completed']}d | "
            f"Requests: {reqs['pending']} pending"
        )
        print(status_line, end="", flush=True)
