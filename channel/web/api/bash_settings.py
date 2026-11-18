"""Instance-wide command execution settings for the capabilities view."""

import json
import os
import sys

import web

from channel.web.api.config import _settings_save_lock
from channel.web.core._common import (
    _read_config_file_for_write, _require_auth, _write_config_file_for_write,
)
from config import conf, get_data_root


def _shell_status():
    from agent.tools.bash.shell import get_shell_status
    return get_shell_status()


def _settings_payload():
    tools = conf().get("tools") or {}
    shell = (tools.get("bash") or {}).get("windows_shell", "cmd")
    is_windows = sys.platform == "win32"
    pwsh = (
        _shell_status()["pwsh"]
        if is_windows
        else {"available": False, "path": None, "version": None}
    )
    return {
        "status": "success",
        "platform": "windows" if is_windows else sys.platform,
        "windows_shell": shell,
        "effective_shell": shell if is_windows else "sh",
        "pwsh": pwsh,
        "scope": "instance",
    }


class BashSettingsHandler:
    def GET(self):
        _require_auth()
        web.header("Content-Type", "application/json; charset=utf-8")
        try:
            return json.dumps(_settings_payload(), ensure_ascii=False)
        except Exception:
            return json.dumps({"status": "error", "code": "settings_unavailable",
                               "message": "Unable to read command execution settings"})

    def POST(self):
        _require_auth()
        web.header("Content-Type", "application/json; charset=utf-8")
        try:
            data = json.loads(web.data())
            if not isinstance(data, dict) or data.get("windows_shell") not in ("cmd", "pwsh"):
                return json.dumps({"status": "error", "code": "invalid_shell",
                                   "message": "windows_shell must be cmd or pwsh"})
            shell = data["windows_shell"]
            if sys.platform != "win32":
                return json.dumps({"status": "error", "code": "unsupported_platform",
                                   "message": "Windows shell selection requires a Windows execution host"})
            if shell == "pwsh" and not _shell_status()["pwsh"]["available"]:
                return json.dumps({"status": "error", "code": "pwsh_unavailable",
                                   "message": "PowerShell 7 was not found on the execution host"})
            with _settings_save_lock:
                file_cfg = _read_config_file_for_write()
                tools = dict(file_cfg.get("tools") or {})
                bash = dict(tools.get("bash") or {})
                bash["windows_shell"] = shell
                tools["bash"] = bash
                file_cfg["tools"] = tools
                _write_config_file_for_write(os.path.join(get_data_root(), "config.json"), file_cfg)
                # Publish only after persistence succeeds; leave running jobs alone.
                conf()["tools"] = tools
            return json.dumps(_settings_payload(), ensure_ascii=False)
        except (ValueError, TypeError):
            return json.dumps({"status": "error", "code": "invalid_request",
                               "message": "Expected a JSON object with windows_shell"})
        except Exception:
            return json.dumps({"status": "error", "code": "save_failed",
                               "message": "Unable to save command execution settings"})
