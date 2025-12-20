"""
Icarus Worker Harness

Headless Claude Agent execution with bus-based permission routing.

Usage:
    # As a module
    from daedalus.worker import IcarusWorker, run_worker

    worker = IcarusWorker(work_id="work-123", project_root="/path/to/project")
    result = await worker.execute(prompt="Implement feature X")

    # As a CLI
    python -m daedalus.worker --work-id work-123 --project /path/to/project
"""

import asyncio
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, Optional

from ..bus.icarus_bus import (
    IcarusBus,
    InstanceStatus,
    RequestType,
    Response,
    WorkPackage,
)
from ..bus.permissions import (
    ApprovalScope,
    PermissionRequest,
    check_auto_approve,
    create_permission_request,
)

# Try to import Claude Agent SDK
try:
    from claude_agent_sdk import query
    HAS_AGENT_SDK = True
except ImportError:
    HAS_AGENT_SDK = False


class IcarusWorker:
    """
    Headless Icarus worker using Claude Agent SDK.

    Routes permission requests through the Icarus Bus instead of
    interactive prompts.
    """

    def __init__(
        self,
        work_id: Optional[str] = None,
        project_root: Optional[str] = None,
        scope: Optional[ApprovalScope] = None,
        bus: Optional[IcarusBus] = None,
        permission_timeout: float = 300,
        stream_output: bool = True,
    ):
        """
        Initialize worker.

        Args:
            work_id: ID of the work package (for tracking)
            project_root: Root directory for the project
            scope: Approval scope for auto-approve patterns
            bus: Icarus bus instance (creates new if None)
            permission_timeout: Seconds to wait for permission responses
            stream_output: Whether to stream output to bus
        """
        self.work_id = work_id
        self.project_root = project_root or os.getcwd()
        self.scope = scope or ApprovalScope.default(self.project_root)
        self.bus = bus or IcarusBus()
        self.permission_timeout = permission_timeout
        self.stream_output = stream_output

        # Instance ID set on registration
        self.instance_id: Optional[str] = None

        # Track permission decisions
        self.permissions_granted = 0
        self.permissions_denied = 0
        self.permissions_escalated = 0

    async def register(self) -> str:
        """Register with the bus. Returns instance ID."""
        self.instance_id = self.bus.register_instance(
            pid=os.getpid(),
            metadata={
                "work_id": self.work_id,
                "project_root": self.project_root,
            }
        )
        self.bus.update_status(self.instance_id, InstanceStatus.IDLE, self.work_id)
        self._log(f"Registered as {self.instance_id}")
        return self.instance_id

    async def unregister(self):
        """Unregister from the bus."""
        if self.instance_id:
            self.bus.unregister_instance(self.instance_id)
            self._log("Unregistered")

    def _log(self, message: str):
        """Log message to bus stream."""
        if self.stream_output and self.instance_id:
            self.bus.stream_output(self.instance_id, message)
        print(f"[Icarus] {message}", file=sys.stderr)

    async def _handle_permission(
        self,
        tool_name: str,
        input_params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Handle a permission request.

        This is the can_use_tool callback for Claude Agent SDK.

        Returns:
            {"behavior": "allow", "updatedInput": input_params} or
            {"behavior": "deny", "message": reason}
        """
        # Create permission request
        perm_req = create_permission_request(
            tool_name=tool_name,
            input_params=input_params,
            work_id=self.work_id,
            instance_id=self.instance_id,
        )

        self._log(f"Permission request: {perm_req.type.value} - {tool_name}")

        # Check auto-approve first
        approved, deny_reason = check_auto_approve(perm_req, self.scope)

        if approved:
            self.permissions_granted += 1
            self._log(f"  -> Auto-approved")
            return {"behavior": "allow", "updatedInput": input_params}

        if deny_reason:
            self.permissions_denied += 1
            self._log(f"  -> Auto-denied: {deny_reason}")
            return {"behavior": "deny", "message": deny_reason}

        # Not auto-approved or denied - escalate to Daedalus via bus
        self.permissions_escalated += 1
        self._log(f"  -> Escalating to Daedalus...")

        # Create detailed message for Daedalus
        message = self._format_permission_message(perm_req)

        # Submit request to bus
        request_id = self.bus.request_help(
            instance_id=self.instance_id,
            work_id=self.work_id,
            request_type=RequestType.APPROVAL,
            message=message,
            context={
                "permission_type": perm_req.type.value,
                "tool_name": tool_name,
                "input_params": input_params,
            },
        )

        self._log(f"  -> Request ID: {request_id}")

        # Wait for Daedalus response
        response = self.bus.wait_for_response(
            request_id,
            timeout=self.permission_timeout,
        )

        if response is None:
            self._log(f"  -> Timeout waiting for response")
            return {
                "behavior": "deny",
                "message": "Timeout waiting for permission approval",
            }

        if response.decision == "approved":
            self._log(f"  -> Approved by Daedalus")
            # Check if Daedalus modified the input
            updated_input = response.data.get("updated_input", input_params)
            return {"behavior": "allow", "updatedInput": updated_input}
        else:
            self._log(f"  -> Denied by Daedalus: {response.message}")
            return {"behavior": "deny", "message": response.message}

    def _format_permission_message(self, req: PermissionRequest) -> str:
        """Format a human-readable permission message."""
        lines = [f"Permission needed: {req.type.value}"]
        lines.append(f"Tool: {req.tool_name}")

        if req.file_path:
            lines.append(f"File: {req.file_path}")
        if req.bash_command:
            cmd_preview = req.bash_command[:100]
            if len(req.bash_command) > 100:
                cmd_preview += "..."
            lines.append(f"Command: {cmd_preview}")
        if req.url:
            lines.append(f"URL: {req.url}")

        return "\n".join(lines)

    async def execute(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        permission_mode: str = "default",
    ) -> Dict[str, Any]:
        """
        Execute a prompt using Claude Agent SDK.

        Args:
            prompt: The prompt to execute
            system_prompt: Optional system prompt
            permission_mode: SDK permission mode (default, acceptEdits, bypassPermissions)

        Returns:
            Result dictionary with success, output, and metadata
        """
        if not HAS_AGENT_SDK:
            return {
                "success": False,
                "error": "claude-agent-sdk not installed. Run: pip install claude-agent-sdk",
            }

        if not self.instance_id:
            await self.register()

        self.bus.update_status(self.instance_id, InstanceStatus.WORKING, self.work_id)
        self._log(f"Executing prompt ({len(prompt)} chars)")

        try:
            # Build options
            options = {
                "permission_mode": permission_mode,
                "can_use_tool": self._handle_permission,
                "cwd": self.project_root,
            }

            if system_prompt:
                options["system_prompt"] = system_prompt

            # Execute query
            result = await query(
                prompt=prompt,
                options=options,
            )

            self.bus.update_status(self.instance_id, InstanceStatus.COMPLETE, self.work_id)

            return {
                "success": True,
                "output": result,
                "permissions": {
                    "granted": self.permissions_granted,
                    "denied": self.permissions_denied,
                    "escalated": self.permissions_escalated,
                },
            }

        except Exception as e:
            self.bus.update_status(self.instance_id, InstanceStatus.FAILED, self.work_id)
            self._log(f"Execution failed: {e}")

            return {
                "success": False,
                "error": str(e),
                "permissions": {
                    "granted": self.permissions_granted,
                    "denied": self.permissions_denied,
                    "escalated": self.permissions_escalated,
                },
            }

    async def execute_work_package(self, work: WorkPackage) -> Dict[str, Any]:
        """
        Execute a work package.

        Args:
            work: The work package to execute

        Returns:
            Result dictionary
        """
        self.work_id = work.id

        # Update scope from work package inputs if provided
        if "scope" in work.inputs:
            scope_data = work.inputs["scope"]
            self.scope = ApprovalScope(**scope_data)

        # Build prompt from work package
        prompt_parts = [work.description]

        if work.inputs.get("files"):
            prompt_parts.append(f"\nFiles to work with: {', '.join(work.inputs['files'])}")

        if work.inputs.get("context"):
            prompt_parts.append(f"\nContext: {work.inputs['context']}")

        if work.constraints:
            prompt_parts.append(f"\nConstraints:\n" + "\n".join(f"- {c}" for c in work.constraints))

        if work.outputs.get("expected"):
            prompt_parts.append(f"\nExpected output: {work.outputs['expected']}")

        prompt = "\n".join(prompt_parts)

        # Execute
        result = await self.execute(
            prompt=prompt,
            system_prompt=work.inputs.get("system_prompt"),
        )

        # Submit result to bus
        self.bus.submit_result(
            work_id=work.id,
            instance_id=self.instance_id,
            result=result,
        )

        return result


async def run_worker(
    work_id: Optional[str] = None,
    project_root: Optional[str] = None,
    prompt: Optional[str] = None,
    claim_from_queue: bool = False,
):
    """
    Run an Icarus worker.

    Args:
        work_id: Specific work ID to execute
        project_root: Project root directory
        prompt: Direct prompt to execute (if not using work package)
        claim_from_queue: Whether to claim work from the queue
    """
    bus = IcarusBus()

    if not bus.is_initialized():
        print("Error: Bus not initialized. Run: daedalus init", file=sys.stderr)
        return

    worker = IcarusWorker(
        work_id=work_id,
        project_root=project_root,
        bus=bus,
    )

    await worker.register()

    try:
        if prompt:
            # Direct prompt execution
            result = await worker.execute(prompt)
            print(json.dumps(result, indent=2))

        elif claim_from_queue:
            # Claim work from queue
            work = bus.claim_work(worker.instance_id)
            if work:
                print(f"Claimed work: {work.id}", file=sys.stderr)
                result = await worker.execute_work_package(work)
                print(json.dumps(result, indent=2))
            else:
                print("No work available in queue", file=sys.stderr)

        elif work_id:
            # Execute specific work package
            work = bus.get_work(work_id)
            if work:
                result = await worker.execute_work_package(work)
                print(json.dumps(result, indent=2))
            else:
                print(f"Work package not found: {work_id}", file=sys.stderr)

        else:
            print("No work specified. Use --prompt, --work-id, or --claim", file=sys.stderr)

    finally:
        await worker.unregister()


def main():
    """CLI entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Icarus Worker - Headless Claude Agent")
    parser.add_argument("--work-id", help="Work package ID to execute")
    parser.add_argument("--project", default=os.getcwd(), help="Project root directory")
    parser.add_argument("--prompt", help="Direct prompt to execute")
    parser.add_argument("--claim", action="store_true", help="Claim work from queue")

    args = parser.parse_args()

    asyncio.run(run_worker(
        work_id=args.work_id,
        project_root=args.project,
        prompt=args.prompt,
        claim_from_queue=args.claim,
    ))


if __name__ == "__main__":
    main()
