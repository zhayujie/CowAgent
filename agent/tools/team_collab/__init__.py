"""Team collaboration tools: shared mailbox, task board, and inbox.

``team_send`` leaves messages (and wakes the recipient), ``team_inbox``
reads and acknowledges them, ``team_task`` works the shared board. The
store they share lives in :mod:`agent.team_runtime`; turn identity and
wake delivery in ``._shared``.
"""

from ._shared import (
    TeamCollabContext,
    attach_team_collab_tools,
    deliver_wakes,
    wake_prompt,
    wake_session_id,
)
from .team_inbox import TeamInboxTool
from .team_send import TeamSendTool
from .team_task import TeamTaskTool

__all__ = [
    "TeamCollabContext",
    "TeamInboxTool",
    "TeamSendTool",
    "TeamTaskTool",
    "attach_team_collab_tools",
    "deliver_wakes",
    "wake_prompt",
    "wake_session_id",
]