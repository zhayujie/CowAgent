from typing import Any, Dict

from agent.tools.base_tool import ToolResult
from agent.tools.phone.base import PhoneTool

_ACTIONS = ("url", "navigate", "call", "sms", "email")


class PhoneOpen(PhoneTool):
    name: str = "phone_open"
    description: str = (
        "Hand something over to another app on the user's phone. Actions: "
        "url (open a web page, or an app through its link scheme such as weixin:// or alipays://), "
        "navigate (open the maps app with a destination), "
        "call (open the dialer with a number filled in), "
        "sms (open a new text message), "
        "email (open a new email). "
        "Nothing is sent or dialed by this tool: the user finishes it in the app that opens. "
        "It cannot see or operate the other app afterwards."
    )
    params: dict = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": list(_ACTIONS)},
            "target": {
                "type": "string",
                "description": "url: the link. navigate: a place name or address. "
                               "call/sms: the phone number. email: the address.",
            },
            "text": {"type": "string", "description": "sms/email: the message body, prefilled for the user to edit."},
            "subject": {"type": "string", "description": "email: the subject line."},
        },
        "required": ["action", "target"],
    }
    platforms = ("android", "ios")

    def execute(self, args: Dict[str, Any]) -> ToolResult:
        action = str(args.get("action") or "").strip().lower()
        target = str(args.get("target") or "").strip()
        if action not in _ACTIONS:
            return ToolResult.fail(f"Error: action must be one of {', '.join(_ACTIONS)}.")
        if not target:
            return ToolResult.fail("Error: target is required.")
        request = {"action": action, "target": target}
        for key in ("text", "subject"):
            value = str(args.get(key) or "").strip()
            if value:
                request[key] = value
        result = self.run_on_phone(request)
        if result.status == "success":
            result.result = "Opened on the phone; the user takes it from there."
            if action in ("call", "sms", "email"):
                result.result += " Nothing has been dialed or sent yet; the user does that."
        return result
