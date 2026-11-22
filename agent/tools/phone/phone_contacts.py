import re
from typing import Any, Dict

from agent.tools.base_tool import ToolResult
from agent.tools.phone.base import PhoneTool


class PhoneContacts(PhoneTool):
    name: str = "phone_contacts"
    description: str = (
        "Look someone up in the contacts on the user's phone by name, and get their phone numbers, "
        "email addresses and organization. Use it before calling, texting or emailing someone the user "
        "names. It searches by name only and cannot list the whole address book. Returns at most 10 "
        "matches. The first use asks the user for contacts permission."
    )
    params: dict = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "The name, or part of it, to look for."},
        },
        "required": ["query"],
    }
    platforms = ("android", "ios")

    def execute(self, args: Dict[str, Any]) -> ToolResult:
        query = str(args.get("query") or "").strip()
        if not re.search(r"\w", query):
            return ToolResult.fail("Error: query must be a name, or part of one, to search for.")
        return self.run_on_phone({"query": query[:100]})
