from typing import Any, Dict

from agent.tools.base_tool import BaseTool, ToolResult
from agent.tools.phone.bridge import bridge

# Why the app did not carry a request out, as the model should read it.
_ERRORS = {
    "app_inactive": "The app is not open on the phone, so this cannot run now. "
                    "Tell the user to open the app and ask again.",
    "timeout": "The phone did not answer in time. Nothing was done.",
    "cancelled": "Stopped by the user.",
    "declined": "The user declined this on the phone. Do not retry unless they ask again.",
    "permission_denied": "The user did not grant the permission this needs, so it did not run.",
    "permission_blocked": "The permission this needs is turned off in the phone's settings. "
                          "The app has offered the user a way to turn it on; ask them to retry after that.",
    "unsupported": "This phone cannot do that.",
    "no_app": "No app on the phone can open this.",
    "location_off": "Location is turned off on the phone. Ask the user to turn it on and retry.",
    "no_fix": "The phone could not determine its location right now. Suggest retrying outdoors or later.",
    "no_calendar": "The phone has no calendar that events can be added to.",
}


class PhoneTool(BaseTool):
    """A tool the app carries out on the phone it runs on.

    Offered only once the app has said it can run the tool, and only in the
    app's own conversations: a message arriving through a chat channel comes
    from someone who may not own this phone.
    """

    # Systems the app implements this tool on. Shown to the user; the app
    # still says for itself which tools it runs.
    platforms: tuple = ()
    # Long enough for the user to answer a permission dialog.
    timeout: float = 120.0

    def is_available(self) -> bool:
        if not bridge.supports(self.name):
            return False
        return getattr(getattr(self, "model", None), "channel_type", None) == "web"

    def run_on_phone(self, args: Dict[str, Any]) -> ToolResult:
        answer = bridge.call(
            self.name, args,
            timeout=self.timeout,
            cancel_event=getattr(self, "cancel_event", None),
        )
        if answer.get("ok"):
            return ToolResult.success(answer.get("result"))
        code = str(answer.get("error") or "failed")
        message = _ERRORS.get(code) or str(answer.get("message") or "The phone could not do this.")
        return ToolResult.fail(f"Error: {message}")
