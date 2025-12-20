"""
Permission handling for headless Icarus workers.

This module extends the Icarus Bus with:
- PermissionType enum for specific tool permission categories
- PermissionRequest dataclass with tool details
- Auto-approve pattern matching
- Integration with Claude Agent SDK can_use_tool callback
"""

import fnmatch
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


class PermissionType(str, Enum):
    """Categories of permissions for tool usage."""
    FILE_READ = "file_read"
    FILE_WRITE = "file_write"
    FILE_EDIT = "file_edit"
    BASH_COMMAND = "bash_command"
    WEB_FETCH = "web_fetch"
    WEB_SEARCH = "web_search"
    MCP_TOOL = "mcp_tool"
    ASK_USER = "ask_user"
    OTHER = "other"


@dataclass
class PermissionRequest:
    """Detailed permission request from a tool use."""
    type: PermissionType
    tool_name: str
    input_params: Dict[str, Any]
    work_id: Optional[str] = None
    instance_id: Optional[str] = None

    # Extracted details for easier pattern matching
    file_path: Optional[str] = None
    bash_command: Optional[str] = None
    url: Optional[str] = None

    def __post_init__(self):
        """Extract details from input params."""
        if self.type == PermissionType.FILE_READ:
            self.file_path = self.input_params.get("file_path")
        elif self.type == PermissionType.FILE_WRITE:
            self.file_path = self.input_params.get("file_path")
        elif self.type == PermissionType.FILE_EDIT:
            self.file_path = self.input_params.get("file_path")
        elif self.type == PermissionType.BASH_COMMAND:
            self.bash_command = self.input_params.get("command")
        elif self.type in (PermissionType.WEB_FETCH, PermissionType.WEB_SEARCH):
            self.url = self.input_params.get("url")


@dataclass
class ApprovalScope:
    """
    Defines what a worker is allowed to do without explicit approval.

    Used by Daedalus when dispatching work, and by auto-approve logic.
    """
    # Paths worker can read (glob patterns)
    read_paths: List[str] = field(default_factory=list)

    # Paths worker can write/edit (glob patterns)
    write_paths: List[str] = field(default_factory=list)

    # Bash commands that are auto-approved (patterns or prefixes)
    bash_allow: List[str] = field(default_factory=list)

    # Bash commands that are explicitly denied (overrides allow)
    bash_deny: List[str] = field(default_factory=list)

    # URLs that can be fetched (patterns)
    url_allow: List[str] = field(default_factory=list)

    # Whether to allow all reads within project root
    allow_project_reads: bool = True

    # Project root for relative path resolution
    project_root: Optional[str] = None

    @classmethod
    def default(cls, project_root: str = None) -> "ApprovalScope":
        """Create a default scope with sensible safety defaults."""
        return cls(
            read_paths=["**/*"],  # Read anything
            write_paths=[],  # No writes by default
            bash_allow=[
                # Safe read-only commands
                "ls *",
                "cat *",
                "head *",
                "tail *",
                "grep *",
                "find *",
                "tree *",
                "wc *",
                # Git read operations
                "git status*",
                "git log*",
                "git diff*",
                "git show*",
                "git branch*",
                # Python checks
                "python -c *",
                "python3 -c *",
                "pip show *",
                "pip list*",
                # Node checks
                "npm list*",
                "npm info*",
                "node -e *",
            ],
            bash_deny=[
                # Dangerous commands
                "rm -rf *",
                "rm -r /*",
                "sudo *",
                "chmod 777 *",
                "> /dev/*",
                "dd if=*",
                "mkfs*",
                # Network exfiltration
                "curl * | *",
                "wget * | *",
                "nc *",
                "netcat *",
            ],
            allow_project_reads=True,
            project_root=project_root,
        )

    @classmethod
    def permissive(cls, project_root: str) -> "ApprovalScope":
        """Create a permissive scope for trusted work packages."""
        return cls(
            read_paths=["**/*"],
            write_paths=["**/*"],  # Allow all writes in project
            bash_allow=[
                "*",  # Allow all bash (use bash_deny for safety)
            ],
            bash_deny=[
                "rm -rf /",
                "rm -rf ~",
                "rm -rf /*",
                "sudo rm *",
                "> /dev/*",
                "dd if=*",
                "mkfs*",
            ],
            url_allow=["*"],
            allow_project_reads=True,
            project_root=project_root,
        )


def classify_tool(tool_name: str, input_params: Dict[str, Any]) -> PermissionType:
    """Classify a tool use into a permission type."""
    tool_lower = tool_name.lower()

    if tool_lower == "read":
        return PermissionType.FILE_READ
    elif tool_lower == "write":
        return PermissionType.FILE_WRITE
    elif tool_lower == "edit":
        return PermissionType.FILE_EDIT
    elif tool_lower == "bash":
        return PermissionType.BASH_COMMAND
    elif tool_lower == "webfetch":
        return PermissionType.WEB_FETCH
    elif tool_lower == "websearch":
        return PermissionType.WEB_SEARCH
    elif tool_lower == "askuserquestion":
        return PermissionType.ASK_USER
    elif tool_lower.startswith("mcp__"):
        return PermissionType.MCP_TOOL
    else:
        return PermissionType.OTHER


def _match_pattern(value: str, pattern: str) -> bool:
    """Match a value against a glob-like pattern."""
    # Convert glob to regex
    regex = fnmatch.translate(pattern)
    return bool(re.match(regex, value, re.IGNORECASE))


def _match_any(value: str, patterns: List[str]) -> bool:
    """Check if value matches any pattern in list."""
    return any(_match_pattern(value, p) for p in patterns)


def _is_within_project(file_path: str, project_root: str) -> bool:
    """Check if file path is within project root."""
    try:
        path = Path(file_path).resolve()
        root = Path(project_root).resolve()
        return str(path).startswith(str(root))
    except Exception:
        return False


def check_auto_approve(
    request: PermissionRequest,
    scope: ApprovalScope
) -> Tuple[bool, Optional[str]]:
    """
    Check if a permission request should be auto-approved.

    Returns:
        (approved: bool, reason: Optional[str])
        - (True, None) if approved
        - (False, reason) if denied with reason
        - (False, None) if needs manual review
    """

    # FILE_READ
    if request.type == PermissionType.FILE_READ:
        if request.file_path:
            # Check explicit allow patterns
            if _match_any(request.file_path, scope.read_paths):
                return (True, None)

            # Check project root
            if scope.allow_project_reads and scope.project_root:
                if _is_within_project(request.file_path, scope.project_root):
                    return (True, None)

        return (False, None)  # Needs manual review

    # FILE_WRITE / FILE_EDIT
    if request.type in (PermissionType.FILE_WRITE, PermissionType.FILE_EDIT):
        if request.file_path:
            # Check explicit allow patterns
            if _match_any(request.file_path, scope.write_paths):
                # Also verify within project root for safety
                if scope.project_root:
                    if _is_within_project(request.file_path, scope.project_root):
                        return (True, None)
                else:
                    return (True, None)

        return (False, None)  # Needs manual review

    # BASH_COMMAND
    if request.type == PermissionType.BASH_COMMAND:
        cmd = request.bash_command
        if cmd:
            # Check deny list first (takes precedence)
            if _match_any(cmd, scope.bash_deny):
                return (False, f"Command matches deny pattern: {cmd[:50]}")

            # Check allow list
            if _match_any(cmd, scope.bash_allow):
                return (True, None)

        return (False, None)  # Needs manual review

    # WEB_FETCH / WEB_SEARCH
    if request.type in (PermissionType.WEB_FETCH, PermissionType.WEB_SEARCH):
        url = request.url
        if url and _match_any(url, scope.url_allow):
            return (True, None)

        return (False, None)  # Needs manual review

    # ASK_USER - always escalate
    if request.type == PermissionType.ASK_USER:
        return (False, None)

    # OTHER / MCP_TOOL - needs review
    return (False, None)


def create_permission_request(
    tool_name: str,
    input_params: Dict[str, Any],
    work_id: Optional[str] = None,
    instance_id: Optional[str] = None
) -> PermissionRequest:
    """Create a PermissionRequest from tool use details."""
    perm_type = classify_tool(tool_name, input_params)

    return PermissionRequest(
        type=perm_type,
        tool_name=tool_name,
        input_params=input_params,
        work_id=work_id,
        instance_id=instance_id,
    )
