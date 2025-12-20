"""
Icarus Bus - File-based coordination for Daedalus/Icarus parallelization.

Provides work dispatch, status tracking, and result collection for
parallel Claude Code sessions.
"""

from .icarus_bus import (
    IcarusBus,
    IcarusInstance,
    WorkPackage,
    Request,
    Response,
    InstanceStatus,
    WorkStatus,
    RequestType,
    BUS_ROOT,
)

from .permissions import (
    PermissionType,
    PermissionRequest,
    ApprovalScope,
    classify_tool,
    check_auto_approve,
    create_permission_request,
)

__all__ = [
    # Core bus
    "IcarusBus",
    "IcarusInstance",
    "WorkPackage",
    "Request",
    "Response",
    "InstanceStatus",
    "WorkStatus",
    "RequestType",
    "BUS_ROOT",
    # Permissions
    "PermissionType",
    "PermissionRequest",
    "ApprovalScope",
    "classify_tool",
    "check_auto_approve",
    "create_permission_request",
]
