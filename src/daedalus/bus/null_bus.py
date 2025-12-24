"""
Null implementation of Icarus bus for disabled state.

All read operations return empty results.
All write operations raise RuntimeError with helpful message.
"""

from typing import List, Dict, Any, Optional
from pathlib import Path

from .icarus_bus import (
    IcarusInstance,
    WorkPackage,
    Request,
    Response,
    InstanceStatus,
    WorkStatus,
)


class NullBus:
    """
    No-op bus implementation for when Icarus is disabled.

    This is used when the user hasn't enabled Icarus parallel workers.
    Read operations return empty results, write operations raise with
    a helpful message explaining how to enable Icarus.
    """

    def __init__(self, root: Path = None):
        self.root = root  # Ignored
        self._error_msg = (
            "Icarus bus is disabled. To enable parallel workers:\n"
            "  1. Run: daedalus config icarus.enabled true\n"
            "  2. Restart your Claude Code session"
        )

    def initialize(self) -> None:
        """No-op - don't create directories when disabled."""
        pass

    def is_initialized(self) -> bool:
        """Always returns False when disabled."""
        return False

    # ========== Instance Management ==========

    def register_instance(self, pid: int, metadata: Dict = None) -> str:
        """Raise error - can't register instances when disabled."""
        raise RuntimeError(self._error_msg)

    def unregister_instance(self, instance_id: str) -> None:
        """No-op."""
        pass

    def update_status(
        self,
        instance_id: str,
        status: InstanceStatus,
        work_id: Optional[str] = None
    ) -> None:
        """No-op."""
        pass

    def heartbeat(self, instance_id: str) -> None:
        """No-op."""
        pass

    def list_instances(self, status: Optional[InstanceStatus] = None) -> List[IcarusInstance]:
        """Return empty list when disabled."""
        return []

    def get_instance(self, instance_id: str) -> Optional[IcarusInstance]:
        """Return None when disabled."""
        return None

    # ========== Work Management ==========

    def post_work(self, work: WorkPackage) -> str:
        """Raise error - can't post work when disabled."""
        raise RuntimeError(self._error_msg)

    def claim_work(self, instance_id: str) -> Optional[WorkPackage]:
        """Return None when disabled."""
        return None

    def list_pending_work(self) -> List[WorkPackage]:
        """Return empty list when disabled."""
        return []

    def list_claimed_work(self) -> List[WorkPackage]:
        """Return empty list when disabled."""
        return []

    def get_work(self, work_id: str) -> Optional[WorkPackage]:
        """Return None when disabled."""
        return None

    # ========== Results ==========

    def submit_result(
        self,
        work_id: str,
        instance_id: str,
        result: Dict[str, Any]
    ) -> None:
        """No-op."""
        pass

    def collect_results(self) -> List[Dict[str, Any]]:
        """Return empty list when disabled."""
        return []

    # ========== Requests/Responses ==========

    def request_help(
        self,
        instance_id: str,
        work_id: Optional[str],
        request_type: str,
        message: str,
        context: Dict = None
    ) -> str:
        """Raise error - can't request help when disabled."""
        raise RuntimeError(self._error_msg)

    def list_pending_requests(self) -> List[Request]:
        """Return empty list when disabled."""
        return []

    def respond_to_request(self, request_id: str, response: Response) -> None:
        """No-op."""
        pass

    def wait_for_response(
        self,
        request_id: str,
        timeout: float = 300
    ) -> Optional[Response]:
        """Return None when disabled."""
        return None

    # ========== Streaming ==========

    def stream_output(self, instance_id: str, content: str) -> None:
        """No-op."""
        pass

    def read_stream(self, instance_id: str, offset: int = 0) -> str:
        """Return empty string when disabled."""
        return ""

    # ========== Status ==========

    def status_summary(self) -> Dict[str, Any]:
        """Return disabled status summary."""
        return {
            "initialized": False,
            "disabled": True,
            "message": "Icarus bus is disabled. Run 'daedalus config icarus.enabled true' to enable.",
            "instances": 0,
            "pending_work": 0,
            "claimed_work": 0,
            "pending_requests": 0,
        }
