"""
Daedalus CLI Commands.

Contains the main Daedalus orchestrator class with all command implementations.
"""

import os
import sys
import time
from pathlib import Path

if sys.version_info >= (3, 9):
    from importlib.resources import files, as_file
else:
    from importlib_resources import files, as_file

from .config import (
    DaedalusConfig,
    get_config,
    tmux_session_exists,
    tmux_run,
    tmux_send_keys,
    tmux_pane_count,
)
from ..bus import IcarusBus, WorkPackage, Response


# Config directory for Daedalus identity
CONFIG_DIR = Path.home() / ".config" / "daedalus"

# Log directory for Icarus workers
LOG_DIR = Path("/tmp/icarus-logs")

# Package containing identity seed files
IDENTITY_PACKAGE = "daedalus.identity.data"

# Files to copy during init
SEED_FILES = [
    "identity.md",
    "identity.json",
    "icarus-seed.md",
    "GUESTBOOK.md",
]

# Package containing agent definitions
AGENTS_PACKAGE = "daedalus.identity.data.agents"

# Agents to hydrate to projects
AGENT_FILES = [
    "icarus.md",
    "memory.md",
    "cass-chat.md",
    "design-analyst.md",
    "docs.md",
    "roadmap.md",
    "scout.md",
    "test-runner.md",
]


class Daedalus:
    """Main orchestrator class."""

    def __init__(self, config: DaedalusConfig = None):
        self.config = config or get_config()
        self.bus = IcarusBus()

    # -------------------------------------------------------------------------
    # Identity Initialization
    # -------------------------------------------------------------------------

    def init(self, force: bool = False) -> bool:
        """
        Initialize Daedalus identity by copying seed files to config directory.

        The seed files contain:
        - identity.md: Global Daedalus identity
        - identity.json: Structured identity data
        - icarus-seed.md: Icarus worker identity seed
        - GUESTBOOK.md: Lineage of past instances

        Args:
            force: Overwrite existing files if True

        Returns:
            True if initialization succeeded
        """
        # Create config directory
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        print(f"Config directory: {CONFIG_DIR}")

        copied = 0
        skipped = 0

        for filename in SEED_FILES:
            dst = CONFIG_DIR / filename

            if dst.exists() and not force:
                print(f"  Skip (exists): {filename}")
                skipped += 1
                continue

            try:
                # Read from package resources
                resource = files(IDENTITY_PACKAGE).joinpath(filename)
                content = resource.read_text(encoding="utf-8")

                # Write to config directory
                dst.write_text(content, encoding="utf-8")
                dst.chmod(0o600)
                print(f"  Copied: {filename}")
                copied += 1
            except Exception as e:
                print(f"  Error copying {filename}: {e}")

        print()
        print(f"Initialized: {copied} file(s) copied, {skipped} skipped")

        if skipped > 0 and not force:
            print("Use --force to overwrite existing files")

        return True

    def hydrate(self, force: bool = False) -> bool:
        """
        Hydrate project with Daedalus agents.

        Copies agent definitions from package to project's .claude/agents/ directory.
        This makes agents like memory, scout, test-runner, etc. available in the project.

        Args:
            force: Overwrite existing files if True

        Returns:
            True if hydration succeeded
        """
        cfg = self.config
        agents_dir = Path(cfg.project_dir) / ".claude" / "agents"

        # Create agents directory
        agents_dir.mkdir(parents=True, exist_ok=True)
        print(f"Agents directory: {agents_dir}")

        copied = 0
        skipped = 0

        for filename in AGENT_FILES:
            dst = agents_dir / filename

            if dst.exists() and not force:
                print(f"  Skip (exists): {filename}")
                skipped += 1
                continue

            try:
                # Read from package resources
                resource = files(AGENTS_PACKAGE).joinpath(filename)
                content = resource.read_text(encoding="utf-8")

                # Write to project agents directory
                dst.write_text(content, encoding="utf-8")
                print(f"  Copied: {filename}")
                copied += 1
            except Exception as e:
                print(f"  Error copying {filename}: {e}")

        print()
        print(f"Hydrated: {copied} agent(s) copied, {skipped} skipped")

        if skipped > 0 and not force:
            print("Use --force to overwrite existing files")

        return True

    # -------------------------------------------------------------------------
    # Session Management
    # -------------------------------------------------------------------------

    def tui(self) -> None:
        """Launch the Daedalus TUI application."""
        from ..tui.app import run_tui

        cfg = self.config

        # Initialize the bus before launching TUI
        self.bus.initialize()

        print(f"Launching Daedalus TUI...")
        print(f"  Project: {cfg.project_dir}")
        print(f"  Bus: {self.bus.root}")

        run_tui(working_dir=cfg.project_dir)

    def create_workspace(self, use_tmux: bool = False) -> bool:
        """
        Create new Daedalus workspace.

        By default, launches the Textual TUI. With use_tmux=True, falls back
        to the legacy tmux-based layout.

        Args:
            use_tmux: If True, use tmux layout instead of TUI

        Returns:
            True if workspace was created successfully
        """
        cfg = self.config

        # Initialize the bus
        self.bus.initialize()
        print(f"Bus initialized at {self.bus.root}")

        if not use_tmux:
            # Default: Launch the TUI
            self.tui()
            return True

        # Legacy tmux-based workspace
        if tmux_session_exists(cfg.session_name):
            print(f"Session '{cfg.session_name}' already exists.")
            print(f"Use: daedalus attach")
            return False

        print(f"Creating Daedalus workspace (tmux mode)...")

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
        """Spawn Icarus workers as separate tmux sessions."""
        cfg = self.config

        # Load Icarus identity
        icarus_identity = self._load_icarus_identity()

        # Build allowed tools for auto-approval
        allowed_tools = self._build_allowed_tools()

        print(f"Spawning {count} Icarus worker(s)...")

        spawned = 0

        for i in range(count):
            # Find next available worker number
            worker_num = self._next_worker_number()
            session_name = f"icarus-{worker_num}"

            # Try to claim work from the queue
            work = self.bus.claim_work(f"icarus-{worker_num}")

            if work:
                # Build prompt with identity + work package
                prompt = f"{icarus_identity}\n\n---\n\n# Work Package: {work.id}\n\n{work.description}"
            else:
                # No work available - just start claude with identity
                prompt = icarus_identity
                print(f"  Worker {worker_num}: No work in queue, starting with identity only")

            # Write prompt to temp file for later injection
            import tempfile
            prompt_file = tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False)
            prompt_file.write(prompt)
            prompt_file.close()

            # Build claude command with permissions
            claude_cmd = (
                f"claude "
                f"--permission-mode acceptEdits "
                f"--allowedTools '{allowed_tools}' "
                f"--add-dir ~/cass/cass-vessel"
            )

            # Create new tmux session for this worker
            tmux_run([
                "new-session", "-d",
                "-s", session_name,
                "-c", cfg.project_dir,
            ])

            # Start claude in the session
            tmux_send_keys(session_name, claude_cmd)

            # Wait for Claude to start, then send the prompt
            time.sleep(3)
            tmux_send_keys(session_name, f"Read {prompt_file.name} for your identity and work package, then execute the work.")
            time.sleep(0.5)
            tmux_send_keys(session_name, "", enter=True)

            spawned += 1
            if work:
                print(f"  Worker {worker_num}: Claimed {work.id} (session: {session_name})")
            else:
                print(f"  Worker {worker_num}: Started (session: {session_name})")

        print(f"  Spawned {spawned} worker(s) as separate sessions")

    def _next_worker_number(self) -> int:
        """Find the next available worker number."""
        import subprocess
        try:
            result = subprocess.run(
                ["tmux", "list-sessions", "-F", "#{session_name}"],
                capture_output=True,
                text=True,
            )
            sessions = result.stdout.strip().split('\n') if result.stdout.strip() else []

            # Find existing icarus-N sessions
            existing = set()
            for s in sessions:
                if s.startswith("icarus-"):
                    try:
                        num = int(s.split("-")[1])
                        existing.add(num)
                    except (ValueError, IndexError):
                        pass

            # Find first available number
            num = 0
            while num in existing:
                num += 1
            return num
        except Exception:
            return 0

    def _build_allowed_tools(self) -> str:
        """Build allowed tools string for Claude Code auto-approval."""
        # Match patterns from our ApprovalScope defaults
        allowed = [
            # Read tools - allow broad reading
            "Read",
            "Glob",
            "Grep",
            # Safe bash commands
            "Bash(mkdir:*)",
            "Bash(ls:*)",
            "Bash(cat:*)",
            "Bash(head:*)",
            "Bash(tail:*)",
            "Bash(find:*)",
            "Bash(tree:*)",
            "Bash(pwd)",
            "Bash(which:*)",
            "Bash(python -c:*)",
            "Bash(python3:*)",
            "Bash(pip:*)",
            # Git read operations
            "Bash(git status)",
            "Bash(git log:*)",
            "Bash(git diff:*)",
            "Bash(git branch:*)",
            "Bash(git show:*)",
        ]
        return ",".join(allowed)

    def _load_icarus_identity(self) -> str:
        """Load Icarus identity from package resources."""
        try:
            agent_files = files("daedalus.identity.data.agents")
            identity_file = agent_files.joinpath("icarus.md")
            return identity_file.read_text()
        except Exception:
            return """# Icarus

You are Icarus - a worker executing a specific work package.

Execute directly. Do not enter plan mode. Do not ask clarifying questions.
Your work package contains everything you need.
"""

    def kill_swarm(self) -> None:
        """Kill all Icarus worker sessions."""
        import subprocess

        # Find all icarus-* sessions
        try:
            result = subprocess.run(
                ["tmux", "list-sessions", "-F", "#{session_name}"],
                capture_output=True,
                text=True,
            )
            sessions = result.stdout.strip().split('\n') if result.stdout.strip() else []

            icarus_sessions = [s for s in sessions if s.startswith("icarus-")]

            if not icarus_sessions:
                print("No Icarus worker sessions found.")
                return

            for session in icarus_sessions:
                tmux_run(["kill-session", "-t", session], check=False)
                print(f"  Killed: {session}")

            print(f"Terminated {len(icarus_sessions)} Icarus session(s).")

        except Exception as e:
            print(f"Error killing swarm: {e}")

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
        Spawn headless Icarus workers with visual output in swarm grid.

        Workers run as background processes with output routed to log files.
        The icarus-swarm tmux session displays tail -f of each log in a grid.
        """
        import subprocess
        import sys
        from datetime import datetime

        cfg = self.config

        if not self.bus.is_initialized():
            self.bus.initialize()

        # Create log directory
        LOG_DIR.mkdir(parents=True, exist_ok=True)

        # Ensure swarm session exists
        if not tmux_session_exists(cfg.swarm_session):
            self._create_swarm_session()

        print(f"Spawning {count} headless Icarus worker(s)...")

        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        workers = []

        for i in range(count):
            worker_id = f"icarus-{timestamp}-{i+1}"
            log_file = LOG_DIR / f"{worker_id}.log"

            # Create log file with header
            with open(log_file, "w") as f:
                f.write(f"=== Icarus Worker {worker_id} ===\n")
                f.write(f"Started: {datetime.now().isoformat()}\n")
                f.write(f"Project: {cfg.project_dir}\n")
                f.write("=" * 40 + "\n\n")

            # Spawn worker with output redirected to log file
            cmd = [
                sys.executable, "-m", "daedalus.worker",
                "--project", cfg.project_dir,
            ]
            if claim:
                cmd.append("--claim")

            with open(log_file, "a") as log_f:
                proc = subprocess.Popen(
                    cmd,
                    stdout=log_f,
                    stderr=log_f,
                    start_new_session=True,
                )

            workers.append({
                "id": worker_id,
                "pid": proc.pid,
                "log": str(log_file),
            })

            print(f"  Worker {i+1}: {worker_id} (PID {proc.pid})")

        # Create tmux panes for each worker in swarm session
        self._create_swarm_panes(workers)

        print(f"\nSpawned {count} headless workers.")
        print(f"Logs: {LOG_DIR}/")
        print(f"View: tmux attach -t {cfg.swarm_session}")

    def _create_swarm_panes(self, workers: list) -> None:
        """Create tmux panes in swarm session to tail worker logs."""
        cfg = self.config

        for i, worker in enumerate(workers):
            log_file = worker["log"]
            tail_cmd = f"tail -f {log_file}"

            if i == 0:
                # First worker: use existing pane or first pane
                pane_count = tmux_pane_count(cfg.swarm_session)
                if pane_count <= 1:
                    # Send to existing pane
                    tmux_send_keys(f"{cfg.swarm_session}:0.0", tail_cmd)
                else:
                    # Create new pane
                    tmux_run(["split-window", "-t", cfg.swarm_session, "-h"])
                    tmux_send_keys(cfg.swarm_session, tail_cmd)
            else:
                # Create new pane for additional workers
                tmux_run(["split-window", "-t", cfg.swarm_session, "-h"])
                tmux_send_keys(cfg.swarm_session, tail_cmd)

            # Re-tile after each pane for even distribution
            tmux_run(["select-layout", "-t", cfg.swarm_session, "tiled"])

        # Final tiling
        tmux_run(["select-layout", "-t", cfg.swarm_session, "tiled"])

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
