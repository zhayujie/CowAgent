"""角色切换指令解析与处理测试。"""

from types import SimpleNamespace

import pytest

from agent.registry import AgentProfile, AgentRegistry
from channel import role_switch
from channel.role_switch import RoleBindingStore, handle_role_command


def _registry(tmp_path, coach_enabled=True):
    return AgentRegistry(
        [
            AgentProfile("primary", "主助手", str(tmp_path / "primary")),
            AgentProfile(
                "coach",
                "职业教练",
                str(tmp_path / "coach"),
                enabled=coach_enabled,
            ),
        ],
        default_agent_id="primary",
    )


@pytest.fixture
def agent_bridge(tmp_path, monkeypatch):
    store = RoleBindingStore(str(tmp_path / "bindings.json"))
    monkeypatch.setattr(role_switch, "get_role_binding_store", lambda: store)
    monkeypatch.setattr(
        role_switch, "_sync_bindings_to_config", lambda store, exclude=None: None
    )
    monkeypatch.setattr(role_switch, "_rebuild_router", lambda bridge: None)
    registry = _registry(tmp_path)
    return SimpleNamespace(agent_registry=registry), store


def test_show_brief_lists_roles(agent_bridge):
    bridge, _ = agent_bridge
    handled, reply = handle_role_command("/角色", "weixin", "u1", bridge, bot_name="")
    assert handled is True
    assert "可用角色" in reply
    assert "/角色 coach" in reply


def test_show_detail_lists_roles(agent_bridge):
    bridge, _ = agent_bridge
    for content in ("/角色列表", "/roles", "/role list"):
        handled, reply = handle_role_command(
            content, "weixin", "u1", bridge, bot_name=""
        )
        assert handled is True
        assert "职业教练" in reply


def test_switch_role_binds_and_confirms(agent_bridge):
    bridge, store = agent_bridge
    handled, reply = handle_role_command(
        "/角色 coach", "weixin", "u1", bridge, bot_name=""
    )
    assert handled is True
    assert "职业教练" in reply
    assert store.get_binding("weixin", "u1") == "coach"


def test_switch_role_english_alias(agent_bridge):
    bridge, store = agent_bridge
    handled, reply = handle_role_command(
        "/role coach", "weixin", "u1", bridge, bot_name=""
    )
    assert handled is True
    assert store.get_binding("weixin", "u1") == "coach"


def test_switch_unknown_role_returns_hint(agent_bridge):
    bridge, store = agent_bridge
    handled, reply = handle_role_command(
        "/角色 unknown", "weixin", "u1", bridge, bot_name=""
    )
    assert handled is True
    assert "不存在" in reply
    assert store.get_binding("weixin", "u1") is None


def test_switch_disabled_role_returns_hint(tmp_path, monkeypatch):
    store = RoleBindingStore(str(tmp_path / "bindings.json"))
    monkeypatch.setattr(role_switch, "get_role_binding_store", lambda: store)
    monkeypatch.setattr(role_switch, "_sync_bindings_to_config", lambda store, exclude=None: None)
    monkeypatch.setattr(role_switch, "_rebuild_router", lambda bridge: None)
    bridge = SimpleNamespace(agent_registry=_registry(tmp_path, coach_enabled=False))
    handled, reply = handle_role_command(
        "/角色 coach", "weixin", "u1", bridge, bot_name=""
    )
    assert handled is True
    assert "不存在" in reply or "禁用" in reply


def test_switch_to_default_removes_binding(agent_bridge):
    bridge, store = agent_bridge
    store.set_binding("weixin", "u1", "coach")
    for content in ("/回到大海", "/default", "/大海"):
        handled, reply = handle_role_command(
            content, "weixin", "u1", bridge, bot_name=""
        )
        assert handled is True
        assert "主助手" in reply
    assert store.get_binding("weixin", "u1") is None


def test_switch_same_role_does_not_rebind(agent_bridge):
    bridge, store = agent_bridge
    store.set_binding("weixin", "u1", "coach")
    handled, reply = handle_role_command(
        "/角色 coach", "weixin", "u1", bridge, bot_name=""
    )
    assert handled is True
    assert "无需重复切换" in reply


def test_normal_message_passes_through(agent_bridge):
    bridge, _ = agent_bridge
    handled, reply = handle_role_command(
        "今天天气如何", "weixin", "u1", bridge, bot_name=""
    )
    assert handled is False
    assert reply is None


def test_switch_role_case_insensitive(agent_bridge):
    """大小写不敏感的切换：输入大小写与配置不同也能命中。"""
    bridge, store = agent_bridge
    handled, reply = handle_role_command(
        "/角色 COACH", "weixin", "u1", bridge, bot_name=""
    )
    assert handled is True
    assert store.get_binding("weixin", "u1") == "coach"


def test_switch_role_preserves_case_sensitive_id(tmp_path, monkeypatch):
    """大写 agent id 精确匹配后不做小写化。"""
    from types import SimpleNamespace

    from agent.registry import AgentProfile, AgentRegistry

    registry = AgentRegistry(
        [
            AgentProfile("primary", "主助手", str(tmp_path / "primary")),
            AgentProfile("MyCoach", "我的教练", str(tmp_path / "coach")),
        ],
        default_agent_id="primary",
    )
    store = RoleBindingStore(str(tmp_path / "bindings.json"))
    monkeypatch.setattr(role_switch, "get_role_binding_store", lambda: store)
    monkeypatch.setattr(role_switch, "_sync_bindings_to_config", lambda store, exclude=None: None)
    monkeypatch.setattr(role_switch, "_rebuild_router", lambda bridge: None)
    bridge = SimpleNamespace(agent_registry=registry)

    handled, reply = handle_role_command(
        "/角色 MyCoach", "weixin", "u1", bridge, bot_name=""
    )
    assert handled is True
    assert store.get_binding("weixin", "u1") == "MyCoach"


def test_at_mention_bot_prefix_is_stripped(agent_bridge):
    bridge, store = agent_bridge
    handled, reply = handle_role_command(
        "@我的机器人 /角色 coach", "weixin", "u1", bridge, bot_name="我的机器人"
    )
    assert handled is True
    assert store.get_binding("weixin", "u1") == "coach"
