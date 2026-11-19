# encoding:utf-8
"""A dall-e config push must still be saved when the image plugin is not configured."""

import json
import os
import sys
import types
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

if "linkai" not in sys.modules:
    _stub = types.ModuleType("linkai")
    _stub.LinkAIClient = type("LinkAIClient", (), {"__init__": lambda self, *a, **k: None})
    _stub.PushMsg = type("PushMsg", (), {})
    sys.modules["linkai"] = _stub

import common.cloud_client as cloud_client  # noqa: E402
from common.cloud_client import CloudClient  # noqa: E402


def _push(root, remote_config, plugin_config):
    client = CloudClient.__new__(CloudClient)
    client.client_id = "test-client"
    client._peer_transport = None
    client.channel_mgr = None
    with patch.object(cloud_client, "get_data_root", return_value=str(root)), \
            patch.object(cloud_client, "conf", return_value={}), \
            patch.object(cloud_client, "pconf", return_value=plugin_config):
        client.on_config(remote_config)
    return json.loads((root / "config.json").read_text(encoding="utf-8-sig"))


def test_dall_e_push_without_plugin_config_is_saved(tmp_path):
    (tmp_path / "config.json").write_text('{"channel_type": "web"}', encoding="utf-8")
    saved = _push(tmp_path, {"enabled": "Y", "text_to_image": "dall-e-3", "model": "gpt-4o"}, None)
    assert saved["model"] == "gpt-4o"


def test_dall_e_push_still_turns_off_the_image_prefix(tmp_path):
    (tmp_path / "config.json").write_text('{"channel_type": "web"}', encoding="utf-8")
    plugin = {"midjourney": {"enabled": True, "use_image_create_prefix": True}}
    _push(tmp_path, {"enabled": "Y", "text_to_image": "dall-e-3"}, plugin)
    assert plugin["midjourney"]["use_image_create_prefix"] is False
