"""Update only the backend-bound current speaker's Markdown profile."""
from datetime import datetime, timezone

from agent.tools.base_tool import BaseTool, ToolResult
from agent.memory.feishu_identity import _PROFILE_LOCK, profile_path, read_profile
from common.atomic_write import write_text_atomic


class FeishuMemberProfileTool(BaseTool):
    name = "member_profile"
    description = ("View, update or clear the CURRENT speaker's profile in this group/private chat. "
                   "Only record explicit self-disclosures or corrections; never third-party claims. "
                   "No sender ID/path can be chosen. Group profiles contain group-public facts only.")
    params = {"type": "object", "properties": {
        "action": {"type": "string", "enum": ["view", "update", "clear"]},
        "content": {"type": "string", "description": "Complete Markdown profile, preserving still-valid facts."},
        "evidence": {"type": "string", "description": "Quote the current speaker's explicit request/self-disclosure."},
    }, "required": ["action"]}

    def __init__(self, workspace, identity):
        super().__init__()
        self.workspace = workspace
        self.identity = dict(identity)

    def execute(self, args):
        with _PROFILE_LOCK:
            action = args.get("action")
            if action == "view":
                return ToolResult.success(read_profile(self.workspace, self.identity) or "No profile yet.")
            if action not in ("update", "clear"):
                return ToolResult.fail("Invalid action")
            evidence = args.get("evidence", "")
            # Backend verifies evidence against the current raw message, not old history.
            original = self.identity.get("current_text", "")
            if not isinstance(evidence, str) or not evidence.strip() or evidence not in original:
                return ToolResult.fail("Evidence must quote the current speaker's message exactly")
            content = args.get("content", "") if action == "update" else ""
            if not isinstance(content, str) or len(content) > 10000:
                return ToolResult.fail("Profile must be Markdown of at most 10000 characters")
            path = profile_path(self.workspace, self.identity)
            path.parent.mkdir(parents=True, exist_ok=True)
            source = self.identity.get("message_id", "")
            stamp = datetime.now(timezone.utc).isoformat()
            text = (content.strip() + f"\n\n<!-- source_message={source}; updated={stamp} -->\n") if content.strip() else ""
            write_text_atomic(path, text)
            return ToolResult.success("Current speaker profile updated for this context.")
