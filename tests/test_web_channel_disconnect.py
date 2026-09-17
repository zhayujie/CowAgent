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

import web

from channel.web import web_channel as wc
from channel.web.web_channel import ChannelsHandler


def _dispatch(monkeypatch, body, *, multi_agent):
    """Run ChannelsHandler.POST for ``body`` and record which handler it hit."""
    calls = []

    monkeypatch.setattr(wc, "_require_auth", lambda: None)
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

    monkeypatch.setattr(wc, "conf", lambda: cfg)
    monkeypatch.setattr(ci, "conf", lambda: cfg, raising=False)
    monkeypatch.setattr(wc, "get_data_root", lambda: str(tmp_path))
    monkeypatch.setattr(
        wc, "_read_config_file_for_write",
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
