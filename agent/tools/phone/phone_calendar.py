import re
from typing import Any, Dict

from agent.tools.base_tool import ToolResult, _as_int
from agent.tools.phone.base import PhoneTool

_ACTIONS = ("list", "create")

# Local wall-clock time on the phone, as the model is asked to write it.
_TIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}([T ]\d{2}:\d{2}(:\d{2})?)?$")
_DATE_ONLY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class PhoneCalendar(PhoneTool):
    name: str = "phone_calendar"
    description: str = (
        "Read and add events in the calendar on the user's phone. "
        "list: events between start and end (default: the next 7 days), optionally only those whose "
        "title, place or notes contain query. "
        "create: add an event to the phone's default calendar. "
        "Times are the phone's local time, written YYYY-MM-DDTHH:MM, or YYYY-MM-DD for a whole day; "
        "an end written as a date includes that day, so one day's events are start=end=that date. "
        "The first use asks the user for calendar permission."
    )
    params: dict = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": list(_ACTIONS)},
            "start": {
                "type": "string",
                "description": "list: start of the range. create: when the event starts. "
                               "A date alone makes create an all-day event.",
            },
            "end": {
                "type": "string",
                "description": "list: end of the range. create: when it ends "
                               "(default: one hour after start, or the same day for all-day events).",
            },
            "query": {"type": "string", "description": "list: only events containing this text."},
            "title": {"type": "string", "description": "create: the event title."},
            "location": {"type": "string", "description": "create: where it takes place."},
            "notes": {"type": "string", "description": "create: notes on the event."},
            "reminder_minutes": {
                "type": "integer",
                "description": "create: remind the user this many minutes before it starts.",
            },
        },
        "required": ["action"],
    }
    platforms = ("android", "ios")

    def execute(self, args: Dict[str, Any]) -> ToolResult:
        action = str(args.get("action") or "").strip().lower()
        if action not in _ACTIONS:
            return ToolResult.fail(f"Error: action must be one of {', '.join(_ACTIONS)}.")
        request: Dict[str, Any] = {"action": action}
        for key in ("start", "end"):
            value = str(args.get(key) or "").strip()
            if value:
                if not _TIME_RE.match(value):
                    return ToolResult.fail(
                        f"Error: {key} must be YYYY-MM-DDTHH:MM or YYYY-MM-DD in the phone's local time."
                    )
                request[key] = value.replace(" ", "T")

        if action == "list":
            query = str(args.get("query") or "").strip()
            if query:
                request["query"] = query
            return self.run_on_phone(request)

        title = str(args.get("title") or "").strip()
        if not title:
            return ToolResult.fail("Error: title is required to create an event.")
        if "start" not in request:
            return ToolResult.fail("Error: start is required to create an event.")
        if "end" in request and bool(_DATE_ONLY_RE.match(request["start"])) != bool(_DATE_ONLY_RE.match(request["end"])):
            return ToolResult.fail("Error: start and end must both be dates, or both be times.")
        request["title"] = title
        for key in ("location", "notes"):
            value = str(args.get(key) or "").strip()
            if value:
                request[key] = value
        if args.get("reminder_minutes") not in (None, ""):
            minutes = _as_int(args.get("reminder_minutes"))
            if minutes is None or not 0 <= minutes <= 40320:
                return ToolResult.fail("Error: reminder_minutes must be a whole number of minutes, 0 to 40320.")
            request["reminder_minutes"] = minutes
        return self.run_on_phone(request)
