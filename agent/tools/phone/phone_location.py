from typing import Any, Dict

from agent.tools.base_tool import ToolResult
from agent.tools.phone.base import PhoneTool


class PhoneLocation(PhoneTool):
    name: str = "phone_location"
    description: str = (
        "Get the phone's current location: coordinates (WGS-84), accuracy in meters and, "
        "when the phone can resolve it, a street address. Use it when the answer depends on "
        "where the user is right now (nearby places, weather here, directions from here). "
        "The first use asks the user for location permission."
    )
    params: dict = {
        "type": "object",
        "properties": {},
        "required": [],
    }
    platforms = ("android", "ios")

    def execute(self, args: Dict[str, Any]) -> ToolResult:
        return self.run_on_phone({})
