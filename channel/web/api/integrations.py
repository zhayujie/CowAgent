"""Settings shared by the console's Integrations tab.

``web_public_url`` is the address the console shows in API examples, share
links and embed snippets, for owners reached through a domain or a public IP.
It is only displayed; the server listens and answers as before.
"""

import json
import os
import re

import web

from common.log import logger
from channel.web.core._common import (
    _read_config_file_for_write,
    _require_auth,
    _write_config_file_for_write,
)

_PUBLIC_URL_RE = re.compile(r"^https?://[A-Za-z0-9.\-\[\]:]+(:\d{1,5})?(/[A-Za-z0-9._~\-/]*)?$")


def save_config_values(values: dict) -> None:
    """Write top-level keys to config.json and the live config together."""
    from channel.web.api.config import _settings_save_lock
    from config import conf, get_data_root

    with _settings_save_lock:
        file_cfg = _read_config_file_for_write()
        file_cfg.update(values)
        _write_config_file_for_write(os.path.join(get_data_root(), "config.json"), file_cfg)
        for key, value in values.items():
            conf()[key] = value


def public_url() -> str:
    from config import conf

    return (conf().get("web_public_url") or "").strip().rstrip("/")


class IntegrationsHandler:
    def GET(self):
        _require_auth()
        web.header("Content-Type", "application/json; charset=utf-8")
        return json.dumps({"status": "success", "public_url": public_url()})

    def PUT(self):
        _require_auth()
        web.header("Content-Type", "application/json; charset=utf-8")
        try:
            data = json.loads(web.data() or b"{}")
        except ValueError:
            data = {}
        value = str((data or {}).get("public_url") or "").strip().rstrip("/")
        if value and not _PUBLIC_URL_RE.match(value):
            return json.dumps({"status": "error", "message": "invalid_public_url"})
        save_config_values({"web_public_url": value})
        logger.info(f"[Integrations] Public URL set to {value or '(page origin)'}")
        return json.dumps({"status": "success", "public_url": value})
