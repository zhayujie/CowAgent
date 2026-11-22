from typing import Any, Dict

from agent.tools.base_tool import ToolResult
from agent.tools.phone.base import PhoneTool


class PhoneDevice(PhoneTool):
    name: str = "phone_device"
    description: str = (
        "Read the phone's current status: battery level and whether it is charging, power saving "
        "mode, the network it is on (wifi, cellular or none, and whether it is metered), free "
        "storage, the ringer mode on Android, and the phone model and system version. Use it when "
        "the user asks about the phone itself, or before something that depends on it, such as a "
        "large download over cellular or a long task on a low battery."
    )
    params: dict = {
        "type": "object",
        "properties": {},
        "required": [],
    }
    platforms = ("android", "ios")
    timeout: float = 30.0

    def execute(self, args: Dict[str, Any]) -> ToolResult:
        return self.run_on_phone({})
