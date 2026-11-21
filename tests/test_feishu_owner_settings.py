import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from agent import team
from agent.memory.identity import attach_identity, feishu_identity, identity_prompt, private_session_id
from channel.channel_instances import get_instance, save_feishu_registration, upsert_instance
from channel.feishu import feishu_channel
from channel.feishu.owner_config import DEFAULT_MEMORY_MODE, LEGACY_SHARE_MEMORY, MEMORY_MODE, OWNER_IDS, owner_ids
from channel.web.api import channels as channels_api


def _bot(instance_id, app_id, **settings):
    return {"instance_id": instance_id, "channel_type": "feishu",
            "credentials": {"feishu_app_id": app_id, **settings}}


def _seed_roster(settings, *bots):
    path = team.team_file(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"channel_instances": bots}), encoding="utf-8")
    return path


def _legacy_config(tmp_path, **settings):
    settings.setdefault("agent_workspace", str(tmp_path))
    path = tmp_path / "config.json"
    path.write_text(json.dumps(settings), encoding="utf-8")
    return settings, path


@pytest.mark.parametrize("existing", [None, [], ["ou_explicit"]])
def test_startup_migrates_global_owner_to_matching_app_once(tmp_path, existing):
    settings, config = _legacy_config(tmp_path, feishu_app_id="cli_old", feishu_owner_open_id="ou_old")
    chosen = _bot("bot-old", "cli_old", **({OWNER_IDS: existing} if existing is not None else {}))
    _seed_roster(settings, _bot("bot-other", "cli_other"), chosen)

    team.migrate_feishu_settings(settings, config)
    assert get_instance(settings, "bot-old").credentials[OWNER_IDS] == (existing if existing is not None else ["ou_old"])
    assert OWNER_IDS not in get_instance(settings, "bot-other").credentials
    assert "feishu_owner_open_id" not in json.loads(config.read_text(encoding="utf-8"))
    assert "feishu_owner_open_id" not in settings

    upsert_instance(settings, "feishu", "bot-old", credentials={OWNER_IDS: []})
    team.migrate_feishu_settings(settings, config)
    assert get_instance(settings, "bot-old").credentials[OWNER_IDS] == []


@pytest.mark.parametrize("apps", [("cli_other",), ("cli_old", "cli_old")])
def test_unresolved_app_id_preserves_legacy_source_without_binding(tmp_path, apps):
    settings, config = _legacy_config(tmp_path, feishu_app_id="cli_old", feishu_owner_open_id="ou_old")
    _seed_roster(settings, *(_bot(f"bot-{i}", app) for i, app in enumerate(apps)))

    team.migrate_feishu_settings(settings, config)
    assert "feishu_owner_open_id" in json.loads(config.read_text(encoding="utf-8"))
    assert all(OWNER_IDS not in get_instance(settings, f"bot-{i}").credentials for i in range(len(apps)))
    assert owner_ids(settings) == []


@pytest.mark.parametrize("which_write", ["roster", "config"])
def test_legacy_migration_recovers_from_each_write_failure(tmp_path, monkeypatch, which_write):
    settings, config = _legacy_config(tmp_path, feishu_app_id="cli_old", feishu_owner_open_id="ou_old")
    roster = _seed_roster(settings, _bot("bot-old", "cli_old"))
    write = team.write_text_atomic
    failed_path = roster if which_write == "roster" else config

    def fail_target(path, content, **kwargs):
        if path == failed_path:
            raise OSError("disk unavailable")
        write(path, content, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(team, "write_text_atomic", fail_target)
        team.migrate_feishu_settings(settings, config)

    assert "feishu_owner_open_id" in json.loads(config.read_text(encoding="utf-8"))
    before = get_instance(settings, "bot-old").credentials
    if which_write == "config":
        assert before[OWNER_IDS] == ["ou_old"]
        upsert_instance(settings, "feishu", "bot-old", credentials={OWNER_IDS: []})
    else:
        assert OWNER_IDS not in before
    team.migrate_feishu_settings(settings, config)
    assert get_instance(settings, "bot-old").credentials[OWNER_IDS] == ([] if which_write == "config" else ["ou_old"])
    assert "feishu_owner_open_id" not in json.loads(config.read_text(encoding="utf-8"))


@pytest.mark.parametrize("shared", [False, True])
def test_config_only_bot_keeps_identity_private_switch_and_explicit_sharing(tmp_path, shared):
    settings, config = _legacy_config(
        tmp_path, channel_type="web,feishu,dingtalk", feishu_app_id="cli_old",
        feishu_app_secret="secret", feishu_private_chat_enabled=False, dingtalk_client_id="ding",
        **{LEGACY_SHARE_MEMORY: shared},
    )
    team.migrate_feishu_settings(settings, config)
    instance = get_instance(settings, "feishu")
    assert instance.credentials.get(MEMORY_MODE, DEFAULT_MEMORY_MODE) == ("shared" if shared else DEFAULT_MEMORY_MODE)
    assert instance.credentials["feishu_private_chat_enabled"] is False
    assert instance.credentials["feishu_app_secret"] == "secret"
    assert get_instance(settings, "dingtalk").credentials["dingtalk_client_id"] == "ding"
    assert LEGACY_SHARE_MEMORY not in json.loads(config.read_text(encoding="utf-8"))


def test_replacing_app_does_not_reuse_its_owner_or_sharing(tmp_path):
    settings = {"agent_workspace": str(tmp_path)}
    _seed_roster(settings, _bot("bot", "cli_old", **{OWNER_IDS: ["ou_old"], MEMORY_MODE: "shared"}))
    instance = upsert_instance(settings, "feishu", "bot", credentials={"feishu_app_id": "cli_new"})
    assert instance.credentials[OWNER_IDS] == []
    assert instance.credentials[MEMORY_MODE] == DEFAULT_MEMORY_MODE


def test_rescan_checks_target_and_merges_only_for_the_same_app(tmp_path):
    settings = {"agent_workspace": str(tmp_path)}
    _seed_roster(settings, _bot("bot", "cli_old", **{OWNER_IDS: ["ou_old"], MEMORY_MODE: "shared"}),
                 _bot("other", "cli_other", **{OWNER_IDS: ["ou_other"]}))
    expected = get_instance(settings, "bot")
    with pytest.raises(ValueError, match="different App ID"):
        save_feishu_registration(settings, "bot", expected, "cli_new", "secret", "ou_scanner")
    with pytest.raises(ValueError, match="another instance"):
        save_feishu_registration(settings, "bot", expected, "cli_other", "secret", "ou_scanner", replace=True)
    updated = save_feishu_registration(settings, "bot", expected, "cli_old", "secret", "ou_scanner")
    assert updated.credentials[OWNER_IDS] == ["ou_old", "ou_scanner"]
    assert updated.credentials[MEMORY_MODE] == "shared"
    with pytest.raises(ValueError, match="instance changed"):
        save_feishu_registration(settings, "bot", expected, "cli_old", "secret", "ou_stale")
    replaced = save_feishu_registration(settings, "bot", updated, "cli_new", "secret", "ou_new", replace=True)
    assert replaced.credentials[OWNER_IDS] == ["ou_new"]
    assert replaced.credentials[MEMORY_MODE] == DEFAULT_MEMORY_MODE
    assert get_instance(settings, "other").credentials[OWNER_IDS] == ["ou_other"]


@pytest.mark.parametrize("sender, owners, mode, group, is_owner, uses_workspace", [
    ("ou_a", ["ou_a", "ou_b"], "owner_workspace", False, True, True),
    ("ou_b", ["ou_a", "ou_b"], "owner_workspace", False, True, True),
    ("ou_c", ["ou_a", "ou_b"], "owner_workspace", False, False, False),
    ("ou_a", [], "shared", False, False, True),
    ("ou_b", [], "shared", False, False, True),
    ("ou_a", ["ou_a"], "shared", True, True, False),
    ("ou_a", ["ou_a"], "per_user", False, True, False),
    ("ou_a", [], "owner_workspace", False, False, False),
    ("", [], "shared", False, False, False),
])
def test_workspace_rule_applies_to_profile_search_and_summary_scope(
    tmp_path, sender, owners, mode, group, is_owner, uses_workspace,
):
    msg = SimpleNamespace(actual_user_id=sender, to_user_id="cli_app", is_group=group, other_user_id="oc_group")
    who = feishu_identity(msg, owner_open_ids=owners, private_memory_mode=mode)
    assert who["is_owner"] is is_owner
    assert who["legacy_private"] is uses_workspace
    search = SimpleNamespace(name="memory_search")
    get = SimpleNamespace(name="memory_get")
    agent = SimpleNamespace(workspace_dir=str(tmp_path), tools=[search, get])
    attach_identity(agent, who)
    assert agent._current_user_id == (None if uses_workspace else who["memory_scope"])
    assert search.user_id == get.allowed_memory_scope == agent._current_user_id
    assert search.include_shared is uses_workspace
    if uses_workspace:
        assert "MEMORY.md" in identity_prompt(tmp_path, who)
        assert len(agent.tools) == 2


def test_webhook_uses_the_controller_instance(monkeypatch):
    event = {"sender": {}, "message": {}}
    request = {"header": {"token": "verified", "event_type": "im.message.receive_v1"}, "event": event}
    bot = SimpleNamespace(feishu_token="verified", _handle_message_event=Mock())
    monkeypatch.setattr(feishu_channel.web, "data", lambda: json.dumps(request).encode())
    result = feishu_channel.FeishuController(bot).POST()
    assert json.loads(result)["success"] is True
    bot._handle_message_event.assert_called_once_with(event)


def test_manual_owner_lookup_uses_matching_apps_credentials_and_leaves_list_for_adoption(tmp_path, monkeypatch):
    from channel.feishu import owner_config

    settings = {"agent_workspace": str(tmp_path)}
    _seed_roster(settings, _bot("bot", "cli_app", feishu_app_secret="private-secret", **{OWNER_IDS: ["ou_existing"]}))
    monkeypatch.setattr(channels_api, "conf", lambda: settings)
    lookup = Mock(return_value="ou_application_owner")
    monkeypatch.setattr(owner_config, "lookup_application_owner", lookup)
    handler = channels_api.ChannelsHandler()

    result = json.loads(handler._handle_feishu_owner_lookup("bot", {"feishu_app_id": "cli_app"}))
    assert result["owner_open_id"] == "ou_application_owner"
    lookup.assert_called_once_with("cli_app", "private-secret")
    assert get_instance(settings, "bot").credentials[OWNER_IDS] == ["ou_existing"]

    lookup.reset_mock()
    handler._handle_feishu_owner_lookup("bot", {"feishu_app_id": "cli_other"})
    lookup.assert_called_once_with("cli_other", None)


@pytest.mark.parametrize("code, app_id, owner, expected", [
    (0, "cli_app", {"type": 2, "owner_id": "ou_application_owner"}, "ou_application_owner"),
    (0, "cli_app", None, ""),
    (0, "cli_app", {"type": 0, "owner_id": "ou_service"}, ""),
    (0, "cli_other", {"type": 2, "owner_id": "ou_other"}, ""),
    (99991672, "cli_app", None, ""),
])
def test_rest_lookup_returns_only_this_apps_enterprise_member(code, app_id, owner, expected, monkeypatch):
    import requests
    from channel.feishu.owner_config import lookup_application_owner

    post = Mock(return_value=Mock(**{"json.return_value": {"code": 0, "tenant_access_token": "tenant-token"}}))
    response = {"code": code, "data": {"app": {"app_id": app_id, "owner": owner}}}
    get = Mock(return_value=Mock(**{"json.return_value": response}))
    monkeypatch.setattr(requests, "post", post)
    monkeypatch.setattr(requests, "get", get)
    assert lookup_application_owner("cli_app", "secret") == expected
    assert post.call_args.kwargs["json"] == {"app_id": "cli_app", "app_secret": "secret"}
    assert get.call_args.kwargs["params"] == {"lang": "zh_cn", "user_id_type": "open_id"}
    assert get.call_args.kwargs["headers"] == {"Authorization": "Bearer tenant-token"}
    assert get.call_args.kwargs["allow_redirects"] is False


def test_dm_history_changes_scope_without_reusing_workspace_transcript():
    msg = SimpleNamespace(actual_user_id="ou_a", identity_app_id="cli_app",
                          identity_sender_type="user", identity_tenant_key="tenant",
                          identity_owner_open_ids=["ou_a"])
    workspace = private_session_id(msg, "bot")
    msg.identity_owner_open_ids = []
    personal = private_session_id(msg, "bot")
    assert workspace != personal
    assert personal != private_session_id(msg, "another-bot")
    msg.identity_private_memory_mode = "per_user"
    assert personal == private_session_id(msg, "bot")
    msg.identity_private_memory_mode = "shared"
    assert workspace == private_session_id(msg, "bot")


def test_scoped_file_tools_cannot_read_or_change_workspace_memory(tmp_path):
    from agent.tools.read.read import Read
    from agent.tools.write.write import Write

    workspace_memory = tmp_path / "MEMORY.md"
    workspace_memory.write_text("workspace private", encoding="utf-8")
    identity = feishu_identity(SimpleNamespace(actual_user_id="ou_member", identity_app_id="cli_app"))
    reader, writer = Read({}), Write({})
    reader.cwd = writer.cwd = str(tmp_path)
    agent = SimpleNamespace(workspace_dir=str(tmp_path), tools=[reader, writer])
    attach_identity(agent, identity)

    scoped_path = f"memory/users/{identity['memory_scope']}/MEMORY.md"
    assert reader.execute({"path": "MEMORY.md"}).status == "error"
    assert writer.execute({"path": "MEMORY.md", "content": "overwritten"}).status == "error"
    assert writer.execute({"path": "agents/team.json", "content": "{}"}).status == "error"
    assert writer.execute({"path": scoped_path, "content": "personal note"}).status == "success"
    assert reader.execute({"path": scoped_path}).status == "success"
    assert workspace_memory.read_text(encoding="utf-8") == "workspace private"


def test_registration_binds_scanner_at_most_once_and_retries_disk_failures(monkeypatch, tmp_path):
    import sys

    handler = channels_api.FeishuRegisterHandler
    monkeypatch.setattr(handler, "_state", {})
    sdk = SimpleNamespace(register_app=lambda **_: {
        "client_id": "cli_new", "client_secret": "secret", "user_info": {"open_id": "ou_scanner"},
    })
    monkeypatch.setitem(sys.modules, "lark_oapi", sdk)
    monkeypatch.setattr(feishu_channel.lark_install, "ensure", lambda **_: None)
    monkeypatch.setattr(feishu_channel.lark_install, "needs_download", lambda: False)

    threads = []
    make_thread = channels_api.threading.Thread

    def tracked_thread(*args, **kwargs):
        thread = make_thread(*args, **kwargs)
        threads.append(thread)
        return thread

    monkeypatch.setattr(channels_api.threading, "Thread", tracked_thread)
    settings = {"agent_workspace": str(tmp_path)}
    monkeypatch.setattr(channels_api, "conf", lambda: settings)
    monkeypatch.setattr(channels_api, "_live_channel_manager", lambda: None)
    registration_id = handler._start_register_thread()
    threads[0].join(timeout=5)
    assert not threads[0].is_alive()
    monkeypatch.setattr(channels_api, "_require_auth", lambda: None)
    monkeypatch.setattr(channels_api.web, "header", lambda *args: None)

    def poll(token):
        monkeypatch.setattr(channels_api.web, "data", lambda: json.dumps({"registration_id": token}).encode())
        return json.loads(handler().POST())

    assert poll("old_scan")["status"] == "error"
    with monkeypatch.context() as patch:
        patch.setattr(team, "write_text_atomic", Mock(side_effect=OSError("disk full")))
        assert poll(registration_id)["register_status"] == "save_failed"
    result = poll(registration_id)
    assert result["owner_bound"] is True
    assert "app_secret" not in result
    assert "owner_open_id" not in result
    instance = get_instance(settings, result["instance_id"])
    assert instance.credentials[OWNER_IDS] == ["ou_scanner"]
    assert instance.credentials["feishu_app_id"] == "cli_new"
    assert poll(registration_id) == result
    assert len(team.read(settings)["channel_instances"]) == 1


def test_registration_save_conflict_clears_credentials_and_stops_retrying(monkeypatch, tmp_path):
    from channel import channel_instances

    handler = channels_api.FeishuRegisterHandler
    settings = {"agent_workspace": str(tmp_path)}
    _seed_roster(settings, _bot("bot", "cli_old", feishu_app_secret="old-secret"))
    monkeypatch.setattr(handler, "_state", {
        "status": "done",
        "registration_id": "scan",
        "expires_at": channels_api.time.monotonic() + 60,
        "cancel_event": channels_api.threading.Event(),
        "instance_id": "bot",
        "expected": get_instance(settings, "bot"),
        "replace": False,
        "app_id": "cli_other",
        "app_secret": "scan-secret",
        "owner_open_id": "ou_scanner",
    })
    save = Mock(wraps=save_feishu_registration)
    monkeypatch.setattr(channel_instances, "save_feishu_registration", save)
    monkeypatch.setattr(channels_api, "conf", lambda: settings)
    monkeypatch.setattr(channels_api, "_require_auth", lambda: None)
    monkeypatch.setattr(channels_api.web, "header", lambda *args: None)
    monkeypatch.setattr(channels_api.web, "data", lambda: b'{"registration_id":"scan"}')

    result = json.loads(handler().POST())
    assert result == {
        "status": "success",
        "register_status": "error",
        "message": "The scan returned a different App ID; use Replace app",
    }
    assert handler._state["status"] == "error"
    assert {"app_id", "app_secret", "owner_open_id", "expected"}.isdisjoint(handler._state)
    assert json.loads(handler().POST()) == result
    save.assert_called_once()
