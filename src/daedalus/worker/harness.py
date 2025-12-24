"""
Icarus Worker Harness

Headless Claude Agent execution with bus-based permission routing.

Uses PreToolUse hooks to intercept tool calls and route permission
decisions through the Icarus Bus for Daedalus approval.

Usage:
    # As a module
    from daedalus.worker import IcarusWorker, run_worker

    worker = IcarusWorker(work_id="work-123", project_root="/path/to/project")
    result = await worker.execute(prompt="Implement feature X")

    # As a CLI
    python -m daedalus.worker --work-id work-123 --project /path/to/project
"""

import asyncio
import importlib.resources
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, Optional


def load_icarus_identity() -> str:
    """Load the Icarus identity from package resources."""
    try:
        # Load from package
        files = importlib.resources.files("daedalus.identity.data.agents")
        identity_file = files.joinpath("icarus.md")
        return identity_file.read_text()
    except Exception as e:
        # Fallback to minimal identity
        return """# Icarus

You are Icarus - a worker executing a specific work package.

Execute the work directly without asking questions or entering plan mode.
You have the context you need in the work package description.

Focus on completing the task efficiently and correctly.
"""

import subprocess

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

# Try to import Ariadne for diff submission
try:
    from ..ariadne import AriadneBus, Diff, extract_causal_chain
    HAS_ARIADNE = True
except ImportError:
    HAS_ARIADNE = False
    AriadneBus = None
    Diff = None

# Try to import Claude Agent SDK
try:
    from claude_agent_sdk import query
    from claude_agent_sdk.types import (
        ClaudeAgentOptions,
        HookContext,
        HookMatcher,
        PreToolUseHookInput,
        SyncHookJSONOutput,
    )
    HAS_AGENT_SDK = True
except ImportError:
    HAS_AGENT_SDK = False
    # Define stubs for type hints
    ClaudeAgentOptions = None
    HookContext = None
    HookMatcher = None
    PreToolUseHookInput = None
    SyncHookJSONOutput = None


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
        use_ariadne: bool = False,
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
            use_ariadne: Submit diffs to Ariadne instead of committing
        """
        self.work_id = work_id
        self.project_root = project_root or os.getcwd()
        self.scope = scope or ApprovalScope.default(self.project_root)
        self.bus = bus or IcarusBus()
        self.permission_timeout = permission_timeout
        self.stream_output = stream_output
        self.use_ariadne = use_ariadne

        # Ariadne bus for diff submission
        self.ariadne_bus: Optional["AriadneBus"] = None
        if use_ariadne and HAS_ARIADNE:
            self.ariadne_bus = AriadneBus()

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

    def submit_diff_to_ariadne(self, description: str) -> Optional[str]:
        """
        Generate a diff of current changes and submit to Ariadne.

        Instead of committing, this captures the current git diff and submits
        it to Ariadne's bus for verification and eventual atomic commit.

        Args:
            description: Description of what this diff does

        Returns:
            Diff ID if submitted, None if no changes or Ariadne unavailable
        """
        if not self.use_ariadne or not self.ariadne_bus:
            self._log("Ariadne not enabled, skipping diff submission")
            return None

        if not HAS_ARIADNE:
            self._log("Ariadne module not available")
            return None

        try:
            # Generate diff
            result = subprocess.run(
                ["git", "diff", "HEAD"],
                cwd=self.project_root,
                capture_output=True,
                text=True,
            )

            diff_content = result.stdout
            if not diff_content.strip():
                self._log("No changes to submit")
                return None

            # Create Diff object
            diff = Diff.from_git_diff(
                work_id=self.work_id or "unknown",
                instance_id=self.instance_id or "unknown",
                diff_content=diff_content,
                description=description,
            )

            # Extract causal chain for verification
            causal_chain = extract_causal_chain(diff, Path(self.project_root))
            diff.causal_chain = {
                "diff_id": causal_chain.diff_id,
                "affected_files": causal_chain.affected_files,
                "affected_functions": causal_chain.affected_functions,
                "affected_modules": causal_chain.affected_modules,
                "test_files": causal_chain.test_files,
            }

            # Submit to Ariadne
            diff_id = self.ariadne_bus.submit_diff(diff)
            self._log(f"Submitted diff to Ariadne: {diff_id}")
            self._log(f"  Files: {len(diff.all_affected_files())}")
            self._log(f"  Causal chain: {len(causal_chain.affected_functions)} functions")

            # Reset working directory (Ariadne will apply the diff later)
            subprocess.run(
                ["git", "checkout", "."],
                cwd=self.project_root,
                capture_output=True,
            )

            return diff_id

        except Exception as e:
            self._log(f"Failed to submit diff to Ariadne: {e}")
            return None

    def _log(self, message: str):
        """Log message to bus stream."""
        if self.stream_output and self.instance_id:
            self.bus.stream_output(self.instance_id, message)
        print(f"[Icarus] {message}", file=sys.stderr)

    def _stream_message(self, message) -> None:
        """Stream a SDK message to output in readable format."""
        # Get class name to determine message type
        class_name = type(message).__name__

        if class_name == 'AssistantMessage':
            content = getattr(message, 'content', None)
            if content:
                for block in content:
                    block_class = type(block).__name__
                    if block_class == 'TextBlock':
                        text = getattr(block, 'text', str(block))
                        print(f"\n{text}", file=sys.stderr)
                    elif block_class == 'ToolUseBlock':
                        tool_name = getattr(block, 'name', 'unknown')
                        tool_input = getattr(block, 'input', {})
                        print(f"\n>>> Tool: {tool_name}", file=sys.stderr)
                        if isinstance(tool_input, dict):
                            for k, v in list(tool_input.items())[:3]:
                                v_str = str(v)[:200]
                                print(f"    {k}: {v_str}", file=sys.stderr)

        elif class_name == 'UserMessage':
            # Tool results come back as user messages
            content = getattr(message, 'content', None)
            if content and isinstance(content, list):
                for block in content:
                    block_class = type(block).__name__
                    if block_class == 'ToolResultBlock':
                        result = getattr(block, 'content', '')
                        if isinstance(result, str):
                            # Show first 300 chars of result
                            if len(result) > 300:
                                result = result[:300] + "... [truncated]"
                            print(f"<<< {result}", file=sys.stderr)

        elif class_name == 'ResultMessage':
            result_text = getattr(message, 'result', None)
            if result_text:
                print(f"\n{'='*60}", file=sys.stderr)
                print("FINAL RESULT:", file=sys.stderr)
                print(f"{'='*60}", file=sys.stderr)
                print(result_text, file=sys.stderr)
                print(f"{'='*60}\n", file=sys.stderr)

        elif class_name == 'SystemMessage':
            # Skip system init messages
            pass

        else:
            # Unknown message type - log it for debugging
            print(f"[MSG:{class_name}] {str(message)[:100]}", file=sys.stderr)

    async def _handle_pre_tool_use(
        self,
        hook_input: "PreToolUseHookInput",
        tool_use_id: Optional[str],
        context: "HookContext",
    ) -> "SyncHookJSONOutput":
        """
        PreToolUse hook callback for permission routing.

        This hook intercepts all tool calls and routes permission decisions
        through the Icarus Bus. Using hooks (vs can_use_tool) keeps stdin
        open for bidirectional communication.

        Args:
            hook_input: Tool call details (tool_name, tool_input, etc.)
            tool_use_id: Optional tool use identifier
            context: Hook context

        Returns:
            SyncHookJSONOutput with permission decision
        """
        tool_name = hook_input["tool_name"]
        input_params = hook_input["tool_input"]

        self._log(f">>> PreToolUse hook: {tool_name}")

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
            return {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "allow",
                }
            }

        if deny_reason:
            self.permissions_denied += 1
            self._log(f"  -> Auto-denied: {deny_reason}")
            return {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": deny_reason,
                }
            }

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

        # Wait for Daedalus response (async to not block event loop)
        response = await self.bus.wait_for_response_async(
            request_id,
            timeout=self.permission_timeout,
        )

        if response is None:
            self._log(f"  -> Timeout waiting for response")
            return {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": "Timeout waiting for permission approval",
                }
            }

        if response.decision == "approved":
            self._log(f"  -> Approved by Daedalus")
            # Check if Daedalus modified the input
            updated_input = response.data.get("updated_input")
            result: SyncHookJSONOutput = {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "allow",
                }
            }
            if updated_input:
                result["hookSpecificOutput"]["updatedInput"] = updated_input
            return result
        else:
            self._log(f"  -> Denied by Daedalus: {response.message}")
            return {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": response.message or "Denied by Daedalus",
                }
            }

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
            system_prompt: Optional system prompt (defaults to Icarus identity)
            permission_mode: SDK permission mode (default, acceptEdits, bypassPermissions)

        Returns:
            Result dictionary with success, output, and metadata
        """
        if not HAS_AGENT_SDK:
            return {
                "success": False,
                "error": "claude-agent-sdk not installed. Run: pip install claude-agent-sdk",
            }

        # Load Icarus identity as default system prompt
        if system_prompt is None:
            system_prompt = load_icarus_identity()

        if not self.instance_id:
            await self.register()

        self.bus.update_status(self.instance_id, InstanceStatus.WORKING, self.work_id)
        self._log(f"Executing prompt ({len(prompt)} chars)")

        try:
            # Build PreToolUse hook for permission routing
            # Using hooks (vs can_use_tool) keeps stdin open for bidirectional comms
            pre_tool_hook = HookMatcher(
                matcher=None,  # Match all tools
                hooks=[self._handle_pre_tool_use],
            )

            # Build options using SDK types
            options = ClaudeAgentOptions(
                permission_mode=permission_mode,
                cwd=self.project_root,
                system_prompt=system_prompt,
                hooks={
                    "PreToolUse": [pre_tool_hook],
                },
            )

            # Hooks require streaming mode - wrap prompt in async generator
            async def prompt_stream():
                yield {
                    "type": "user",
                    "message": {"role": "user", "content": prompt}
                }

            # Execute query - returns async generator for streaming
            messages = []
            async for message in query(prompt=prompt_stream(), options=options):
                messages.append(message)
                # Stream full output for visibility
                self._stream_message(message)

            self.bus.update_status(self.instance_id, InstanceStatus.COMPLETE, self.work_id)

            # Extract final result from messages
            result_text = ""
            for msg in messages:
                if hasattr(msg, 'type') and msg.type == 'result':
                    result_text = str(msg)
                    break

            return {
                "success": True,
                "output": result_text or str(messages[-1]) if messages else "No output",
                "messages": [str(m) for m in messages],
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
    use_ariadne: bool = False,
):
    """
    Run an Icarus worker.

    Args:
        work_id: Specific work ID to execute
        project_root: Project root directory
        prompt: Direct prompt to execute (if not using work package)
        claim_from_queue: Whether to claim work from the queue
        use_ariadne: Submit diffs to Ariadne instead of committing
    """
    bus = IcarusBus()

    if not bus.is_initialized():
        print("Error: Bus not initialized. Run: daedalus init", file=sys.stderr)
        return

    worker = IcarusWorker(
        work_id=work_id,
        project_root=project_root,
        bus=bus,
        use_ariadne=use_ariadne,
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
    parser.add_argument("--ariadne", action="store_true",
                       help="Submit diffs to Ariadne instead of committing")

    args = parser.parse_args()

    asyncio.run(run_worker(
        work_id=args.work_id,
        project_root=args.project,
        prompt=args.prompt,
        claim_from_queue=args.claim,
        use_ariadne=args.ariadne,
    ))


if __name__ == "__main__":
    main()
