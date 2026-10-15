"""One widget per ◆component in docs/design/tui/*.oph, named after it, with its CSS beside it (edict 0012)."""

from .claude_pane import ClaudePane
from .explain_card import ExplainCard
from .gameplan import Gameplan
from .header import Header
from .health import Health
from .key_bar import KeyBar
from .last_session import LastSession
from .needs_you import NeedsYou
from .send_to_claude import SendToClaude
from .tabs import ActiveTab, TabBar
from .welcome import Welcome

__all__ = ["ActiveTab", "ClaudePane", "ExplainCard", "Gameplan", "Header", "Health", "KeyBar", "LastSession",
           "NeedsYou", "SendToClaude", "TabBar", "Welcome"]
