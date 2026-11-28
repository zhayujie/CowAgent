"""Web console channel POST dispatch: instance path vs legacy path.

A multi-instance-ready type (feishu/dingtalk) can be active two ways at once:
as a per-instance record (carrying an instance_id) or the legacy way, enabled
in config.json's ``channel_type`` before the install went multi-Agent. Its
legacy card has no instance_id, so a disconnect/rename must fall through to the
legacy per-type handler; otherwise the instance path rejects it with
"instance_id is required" and the channel can never be removed. These tests pin
that routing decision so the disconnect bug does not regress.
"""

import json
from types import SimpleNamespace
from unittest.mock import Mock

import web

from channel.web.api import channels as channels_api
from channel.web.api.channels import ChannelsHandler


def _dispatch(monkeypatch, body, *, multi_agent):
    """Run ChannelsHandler.POST for ``body`` and record which handler it hit."""
    calls = []

    monkeypatch.setattr(channels_api, "_require_auth", lambda: None)
    monkeypatch.setattr(web, "header", lambda *a, **k: None)
    monkeypatch.setattr(web, "data", lambda: json.dumps(body).encode("utf-8"))

    handler = ChannelsHandler()
    monkeypatch.setattr(handler, "_multi_agent_mode", staticmethod(lambda: multi_agent))

    def record(name, ret=None):
        def _fn(*a, **k):
            calls.append(name)
            return json.dumps(ret or {"status": "success"})
        return _fn

    for name in (
        "_handle_save", "_handle_connect", "_handle_disconnect",
        "_handle_instance_save", "_handle_instance_connect",
        "_handle_instance_disconnect", "_handle_instance_rename",
    ):
        monkeypatch.setattr(handler, name, record(name))

    handler.POST()
    return calls


def test_disconnect_without_instance_id_uses_legacy_even_in_multi_agent(monkeypatch):
    # feishu enabled the legacy way (config.json channel_type) shows a card with
    # no instance_id. Its disconnect must remove the type, not be rejected.
    calls = _dispatch(
        monkeypatch,
        {"action": "disconnect", "channel": "feishu", "instance_id": ""},
        multi_agent=True,
    )
    assert calls == ["_handle_disconnect"]


def test_disconnect_with_instance_id_uses_instance_path(monkeypatch):
    calls = _dispatch(
        monkeypatch,
        {"action": "disconnect", "channel": "feishu", "instance_id": "feishu-abc"},
        multi_agent=True,
    )
    assert calls == ["_handle_instance_disconnect"]


def test_rename_without_instance_id_falls_back_to_unknown_legacy_action(monkeypatch):
    # Rename has no legacy equivalent; without an instance_id it must not hit the
    # instance path (which would demand an id). It falls through to the legacy
    # branch and is reported as an unknown action rather than a confusing
    # "instance_id is required".
    calls = _dispatch(
        monkeypatch,
        {"action": "rename", "channel": "feishu", "instance_id": "", "name": "x"},
        multi_agent=True,
    )
    assert calls == []


def test_connect_without_instance_id_still_creates_instance(monkeypatch):
    # connect with an empty id means "create a new instance" and must stay on
    # the instance path in multi-Agent mode.
    calls = _dispatch(
        monkeypatch,
        {"action": "connect", "channel": "feishu", "instance_id": "", "config": {}},
        multi_agent=True,
    )
    assert calls == ["_handle_instance_connect"]


def test_single_agent_always_uses_legacy_path(monkeypatch):
    calls = _dispatch(
        monkeypatch,
        {"action": "disconnect", "channel": "feishu", "instance_id": ""},
        multi_agent=False,
    )
    assert calls == ["_handle_disconnect"]


def test_feishu_instance_leaves_legacy_dingtalk_visible_and_editable(tmp_path, monkeypatch):
    from channel.channel_instances import read_raw_instances, upsert_instance
    from channel.web.core import _common

    cfg = {"agent_workspace": str(tmp_path), "channel_type": "web,dingtalk", "dingtalk_client_id": "old-ding"}
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(cfg), encoding="utf-8")
    upsert_instance(cfg, "feishu", "feishu-new", credentials={"feishu_app_id": "cli_new"})
    monkeypatch.setattr(channels_api, "conf", lambda: cfg)
    monkeypatch.setattr(channels_api, "get_data_root", lambda: str(tmp_path))
    monkeypatch.setattr(_common, "get_data_root", lambda: str(tmp_path))
    monkeypatch.setattr(channels_api, "_require_auth", lambda: None)
    monkeypatch.setattr(channels_api, "threading", SimpleNamespace(Thread=Mock()))
    monkeypatch.setattr(web, "header", lambda *args: None)
    monkeypatch.setattr(web, "input", lambda: {})
    handler = ChannelsHandler()

    def post(action, **fields):
        body = {"action": action, "channel": "dingtalk", **fields}
        monkeypatch.setattr(web, "data", lambda: json.dumps(body))
        result = json.loads(handler.POST())
        assert result["status"] == "success", result
        return result

    view = json.loads(handler.GET())
    assert view["multi_instance_types"] == ["feishu"]
    assert "dingtalk" in view["project_channel_types"]
    assert [card["instance_id"] for card in view["instances"]] == ["feishu-new"]
    assert next(card for card in view["channels"] if card["name"] == "dingtalk")["active"]

    post("save", config={"dingtalk_client_id": "saved-ding"})
    assert json.loads(config_path.read_text(encoding="utf-8"))["dingtalk_client_id"] == "saved-ding"
    post("disconnect")
    assert cfg["channel_type"] == "web"
    post("connect", config={"dingtalk_client_id": "reconnected-ding"})
    assert cfg["channel_type"] == "web,dingtalk"
    assert [r["channel_type"] for r in read_raw_instances(cfg)] == ["feishu"]

    post("set_project", project_dir=str(tmp_path))
    post("save", instance_id="dingtalk", config={"dingtalk_client_id": "instance-ding"})
    ding = next(r for r in read_raw_instances(cfg) if r["channel_type"] == "dingtalk")
    assert ding["credentials"]["dingtalk_client_id"] == "instance-ding"
    assert ding["project_dir"] == str(tmp_path.resolve())
    assert json.loads(config_path.read_text(encoding="utf-8"))["dingtalk_client_id"] == "reconnected-ding"


# ---------------------------------------------------------------------------
# The real bug: a bootstrapped legacy instance must stay gone after disconnect.
#
# bootstrap_legacy_instances runs on every team.json write and recreates any
# multi-instance-ready channel named in config.json's channel_type. So removing
# the instance record alone is undone by the next write. Disconnecting must also
# prune the type from channel_type so the bootstrap has nothing to recreate.
# ---------------------------------------------------------------------------

def _disconnect_env(monkeypatch, tmp_path):
    """Wire ChannelsHandler's config/read/write helpers to a temp workspace with
    a legacy dingtalk enabled via config.json channel_type."""
    import json as _json
    from agent import team
    from channel import channel_instances as ci

    cfg = {
        "agent_workspace": str(tmp_path),
        "channel_type": "feishu,dingtalk",
        "feishu_app_id": "FA",
        "feishu_app_secret": "FS",
        "dingtalk_client_id": "DA",
        "dingtalk_client_secret": "DS",
        "default_agent_id": "default",
    }
    config_path = tmp_path / "config.json"
    config_path.write_text(_json.dumps(cfg), encoding="utf-8")

    monkeypatch.setattr(channels_api, "conf", lambda: cfg)
    monkeypatch.setattr(ci, "conf", lambda: cfg, raising=False)
    monkeypatch.setattr(channels_api, "get_data_root", lambda: str(tmp_path))
    monkeypatch.setattr(
        channels_api, "_read_config_file_for_write",
        lambda: _json.loads(config_path.read_text(encoding="utf-8")),
    )

    # Materialize the roster + bootstrapped instances the way startup would.
    team.write(cfg, {"default_agent_id": "default", "agents": []})
    return cfg, config_path


def test_disconnecting_bootstrapped_legacy_instance_stays_removed(monkeypatch, tmp_path):
    from agent import team
    from channel import channel_instances as ci

    cfg, config_path = _disconnect_env(monkeypatch, tmp_path)

    # sanity: the legacy dingtalk was bootstrapped into an instance
    before = {i.channel_type for i in ci.resolve_channel_instances(team.resolve(cfg))}
    assert "dingtalk" in before

    handler = ChannelsHandler()
    handler._handle_instance_disconnect("dingtalk", "dingtalk")

    # channel_type must have dingtalk pruned so the bootstrap can't recreate it
    import json as _json
    on_disk = _json.loads(config_path.read_text(encoding="utf-8"))
    assert on_disk["channel_type"] == "feishu"

    # and it must not reappear after another roster write (which re-bootstraps)
    team.write(cfg, team.read(cfg))
    after = {i.channel_type for i in ci.resolve_channel_instances(team.resolve(cfg))}
    assert "dingtalk" not in after
    assert "feishu" in after  # untouched


def test_disconnecting_one_of_several_keeps_the_type(monkeypatch, tmp_path):
    from channel import channel_instances as ci

    cfg, config_path = _disconnect_env(monkeypatch, tmp_path)

    # add a second feishu instance so the type has two records
    ci.upsert_instance(
        cfg, "feishu", "feishu-second", agent_id="cust",
        credentials={"feishu_app_id": "FA2", "feishu_app_secret": "FS2"},
    )

    handler = ChannelsHandler()
    handler._handle_instance_disconnect("feishu", "feishu-second")

    import json as _json
    on_disk = _json.loads(config_path.read_text(encoding="utf-8"))
    # feishu still has the bootstrapped instance, so its type stays
    assert "feishu" in on_disk["channel_type"]


def test_feishu_private_chat_setting_persists_per_bot(monkeypatch, tmp_path):
    from channel import channel_instances as ci

    cfg, config_path = _disconnect_env(monkeypatch, tmp_path)
    ci.upsert_instance(
        cfg, "feishu", "feishu-second", agent_id="cust",
        credentials={"feishu_app_id": "FA2", "feishu_app_secret": "FS2"},
    )

    key = "feishu_private_chat_enabled"
    monkeypatch.setitem(cfg, key, False)
    monkeypatch.setattr(channels_api, "_require_auth", lambda: None)
    monkeypatch.setattr(web, "header", lambda *args: None)
    monkeypatch.setattr(web, "input", lambda: {})
    handler = ChannelsHandler()
    monkeypatch.setattr(handler, "_channel_mgr", lambda: None)
    response = handler._handle_instance_save("feishu", "feishu-second", {key: False})

    assert json.loads(response)["status"] == "success"
    assert ci.get_instance(cfg, "feishu-second").credentials[key] is False
    assert key not in ci.get_instance(cfg, "feishu").credentials
    assert key not in json.loads(config_path.read_text(encoding="utf-8"))
    payload = json.loads(handler.GET())
    feishu = next(channel for channel in payload["channels"] if channel["name"] == "feishu")
    assert next(field for field in feishu["fields"] if field["key"] == key)["value"] is True
    cards = {card["instance_id"]: card for card in payload["instances"]}
    for instance_id, expected in (("feishu-second", False), ("feishu", True)):
        field = next(field for field in cards[instance_id]["fields"] if field["key"] == key)
        assert field["value"] is expected
