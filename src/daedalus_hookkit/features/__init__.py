"""Every kit feature, in the order its lines are printed within an event."""

from ..core import Feature
from . import board, brief, capture, efficacy

FEATURES: list = [
    # first, so a nudge printed by this call isn't judged against the call that prompted it
    Feature("efficacy", frozenset({"PostToolUse", "UserPromptSubmit"}), "", efficacy.run),
    Feature("brief", frozenset({"SessionStart"}), "session_start", brief.run),
    Feature("board", frozenset({"UserPromptSubmit"}), "board", board.run),
    Feature("capture", frozenset({"SessionEnd", "PreCompact"}), "capture", capture.run),
]
