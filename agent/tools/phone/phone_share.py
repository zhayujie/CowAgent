import mimetypes
import os
from typing import Any, Dict

from agent.tools.base_tool import ToolResult
from agent.tools.phone.base import PhoneTool
from agent.tools.utils.credentials import DENIED_MESSAGE, is_credential_path
from common.utils import expand_path

_MAX_BYTES = 200 * 1_048_576


class PhoneShare(PhoneTool):
    name: str = "phone_share"
    description: str = (
        "Open the phone's share sheet with a file, so the user can send it to a chat app, mail it, "
        "or save it to their files or photos. The user picks where it goes and sends it themselves. "
        "Use it when the user wants a file you made or found passed on, e.g. \"send the report to "
        "my colleague on WeChat\"."
    )
    params: dict = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "The file to share: an absolute path, or relative to the workspace.",
            },
        },
        "required": ["path"],
    }
    platforms = ("android", "ios")
    # The share sheet stays open while the user chooses.
    timeout: float = 300.0

    def execute(self, args: Dict[str, Any]) -> ToolResult:
        path = str(args.get("path") or "").strip()
        if not path:
            return ToolResult.fail("Error: path is required.")
        if path.lower().startswith(("http://", "https://")):
            return ToolResult.fail("Error: only a file on the phone can be shared; put a link in your reply instead.")
        absolute = self._resolve(path)
        if is_credential_path(absolute):
            return ToolResult.fail(DENIED_MESSAGE)
        if not os.path.isfile(absolute):
            return ToolResult.fail(f"Error: File not found: {path}")
        if os.path.getsize(absolute) > _MAX_BYTES:
            return ToolResult.fail("Error: the file is too large to share from the phone.")
        name = os.path.basename(absolute)
        mime = mimetypes.guess_type(name)[0] or "application/octet-stream"
        return self.run_on_phone({"path": absolute, "name": name, "mime": mime})

    def _resolve(self, path: str) -> str:
        path = expand_path(path)
        if os.path.isabs(path):
            return os.path.realpath(path)
        # Relative to the conversation's working directory, as read and write take them.
        return os.path.realpath(os.path.join(os.path.expanduser(self.cwd or os.getcwd()), path))
