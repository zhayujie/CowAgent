import datetime
import os
import shutil
import uuid
from typing import Any, Dict, List
from urllib.parse import unquote

from agent.tools.base_tool import ToolResult, _as_int
from agent.tools.phone.base import PhoneTool
from common.log import logger

MAX_PHOTOS = 9
_MAX_BYTES = 30 * 1_048_576
_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic"}


class PhonePhotos(PhoneTool):
    name: str = "phone_photos"
    description: str = (
        "Ask the user to pick photos or screenshots from their phone's photo library, and save the "
        "ones they pick into the workspace. Only what the user picks is shared; the library itself "
        "cannot be browsed. Returns the saved file paths: look at them with the vision tool, or "
        "hand them to other tools. Use it when the user refers to a picture on their phone."
    )
    params: dict = {
        "type": "object",
        "properties": {
            "max_count": {
                "type": "integer",
                "description": f"How many photos the user may pick, 1 to {MAX_PHOTOS} (default 1).",
            },
        },
        "required": [],
    }
    platforms = ("android", "ios")
    # The user browses the library and picks, which takes a while.
    timeout: float = 300.0

    def execute(self, args: Dict[str, Any]) -> ToolResult:
        count = _as_int(args.get("max_count")) if args.get("max_count") not in (None, "") else 1
        count = min(max(count or 1, 1), MAX_PHOTOS)
        result = self.run_on_phone({"max_count": count})
        if result.status != "success":
            return result
        picked = (result.result or {}).get("photos") if isinstance(result.result, dict) else None
        if not picked:
            return ToolResult.success("The user did not pick any photo.")

        saved = self._save(picked[:count])
        if not saved:
            return ToolResult.fail("Error: the picked photos could not be read.")
        return ToolResult.success({
            "photos": saved,
            "note": "Saved in the workspace. Use the vision tool to look at them.",
        })

    def _save(self, picked: List[Any]) -> List[str]:
        workspace = getattr(getattr(self, "context", None), "workspace_dir", None) or self.cwd or os.getcwd()
        folder = os.path.join(os.path.expanduser(workspace), "tmp")
        os.makedirs(folder, exist_ok=True)
        # Unique per pick, so a second one in the same second leaves the first in place.
        stamp = f"{datetime.datetime.now():%Y%m%d%H%M%S}_{uuid.uuid4().hex[:6]}"
        saved = []
        for i, photo in enumerate(picked):
            source = str((photo or {}).get("path") or "") if isinstance(photo, dict) else ""
            if source.startswith("file://"):
                source = unquote(source[len("file://"):])
            ext = os.path.splitext(source)[1].lower()
            if ext not in _IMAGE_EXTENSIONS or not os.path.isfile(source):
                logger.warning(f"[phone_photos] skipped a picked file that is not a readable image: {source!r}")
                continue
            if os.path.getsize(source) > _MAX_BYTES:
                logger.warning(f"[phone_photos] skipped a picked file over {_MAX_BYTES} bytes")
                continue
            target = os.path.join(folder, f"phone_photo_{stamp}_{i + 1}{ext}")
            shutil.copyfile(source, target)
            saved.append(target)
        return saved
