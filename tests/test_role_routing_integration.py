"""角色绑定后 AgentRouter 路由集成测试。"""

from bridge.context import Context, ContextType

from agent.registry import AgentProfile, AgentRegistry
from agent.routing import AgentRouter
from channel.role_switch import (
    RoleBindingStore,
    _sync_bindings_to_config,
    load_role_bindings_on_startup,
)


def _registry(tmp_path):
    return AgentRegistry(
        [
            AgentProfile("primary", "主助手", str(tmp_path / "primary")),
            AgentProfile("coach", "职业教练", str(tmp_path / "coach")),
        ],
        default_agent_id="primary",
    )


def test_binding_routes_conversation_to_coach(tmp_path):
    registry = _registry(tmp_path)
    store = RoleBindingStore(str(tmp_path / "bindings.json"))
    store.set_binding("weixin", "u1", "coach")
    bindings = store.get_bindings()

    router = AgentRouter.from_config({"agent_bindings": bindings}, registry)
    assert router.resolve("weixin", ("u1",)) == "coach"
    assert router.resolve("weixin", ("u2",)) == "primary"


def test_unbound_conversation_uses_default(tmp_path):
    registry = _registry(tmp_path)
    router = AgentRouter.from_config({"agent_bindings": []}, registry)
    assert router.resolve("weixin", ("u9",)) == "primary"


def test_removed_binding_returns_to_default(tmp_path):
    registry = _registry(tmp_path)
    store = RoleBindingStore(str(tmp_path / "bindings.json"))
    store.set_binding("weixin", "u1", "coach")
    store.remove_binding("weixin", "u1")

    router = AgentRouter.from_config({"agent_bindings": store.get_bindings()}, registry)
    assert router.resolve("weixin", ("u1",)) == "primary"


def test_context_routing_respects_binding(tmp_path):
    registry = _registry(tmp_path)
    store = RoleBindingStore(str(tmp_path / "bindings.json"))
    store.set_binding("weixin", "u1", "coach")

    router = AgentRouter.from_config({"agent_bindings": store.get_bindings()}, registry)
    context = Context(ContextType.TEXT, "你好", kwargs={})
    context["channel_type"] = "weixin"
    context["session_id"] = "u1"
    context["receiver"] = ""

    assert router.resolve_context(context) == "coach"
    assert context["agent_id"] == "coach"


def test_sync_bindings_to_config_merges_without_overwriting(monkeypatch, tmp_path):
    """同步到 config 时：保留已有配置、追加角色绑定、重复键以角色绑定优先。"""
    store = RoleBindingStore(str(tmp_path / "bindings.json"))
    store.set_binding("weixin", "u1", "coach")

    config = {
        "agent_bindings": [
            {"channel_type": "weixin", "conversation_id": "u9", "agent_id": "primary"},
        ]
    }
    monkeypatch.setattr("config.conf", lambda: config)

    _sync_bindings_to_config(store)

    keys = {(b["channel_type"], b["conversation_id"]) for b in config["agent_bindings"]}
    assert ("weixin", "u1") in keys
    assert ("weixin", "u9") in keys
    assert len(config["agent_bindings"]) == 2


def test_load_role_bindings_on_startup_merges(monkeypatch, tmp_path):
    """启动加载时，持久化的角色绑定合并到 conf()["agent_bindings"]。"""
    path = str(tmp_path / "bindings.json")
    RoleBindingStore(path).set_binding("weixin", "u1", "coach")

    config = {"agent_bindings": []}
    monkeypatch.setattr("config.conf", lambda: config)

    from channel import role_switch

    monkeypatch.setattr(role_switch, "_default_bindings_path", lambda: path)

    load_role_bindings_on_startup()

    assert config["agent_bindings"] == [
        {"channel_type": "weixin", "conversation_id": "u1", "agent_id": "coach"}
    ]


def test_store_bindings_are_compatible_with_router_format(tmp_path):
    """持久化格式与 agent_bindings 配置格式兼容。"""
    registry = _registry(tmp_path)
    store = RoleBindingStore(str(tmp_path / "bindings.json"))
    store.set_binding("weixin", "u1", "coach")

    router = AgentRouter.from_config({"agent_bindings": store.get_bindings()}, registry)
    assert router.resolve("weixin", ("u1",)) == "coach"


def test_sync_exclude_cleans_removed_binding_from_config(monkeypatch, tmp_path):
    """切回默认后，此前合并进 conf 的旧绑定必须被剔除，路由切回默认。"""
    store = RoleBindingStore(str(tmp_path / "bindings.json"))
    store.set_binding("weixin", "u1", "coach")
    config = {"agent_bindings": []}
    monkeypatch.setattr("config.conf", lambda: config)

    # 模拟切换动作：先同步（conf 获得 coach 绑定），再移除并同步（exclude 剔除）
    _sync_bindings_to_config(store)
    assert config["agent_bindings"] == [
        {"channel_type": "weixin", "conversation_id": "u1", "agent_id": "coach"}
    ]

    store.remove_binding("weixin", "u1")
    _sync_bindings_to_config(store, exclude={("weixin", "u1")})
    assert config["agent_bindings"] == []


def test_sync_exclude_keeps_other_config_bindings(monkeypatch, tmp_path):
    """exclude 只剔除指定键，不影响配置文件中的其他绑定。"""
    store = RoleBindingStore(str(tmp_path / "bindings.json"))
    store.set_binding("weixin", "u1", "coach")
    config = {
        "agent_bindings": [
            {"channel_type": "weixin", "conversation_id": "u9", "agent_id": "primary"},
        ]
    }
    monkeypatch.setattr("config.conf", lambda: config)

    _sync_bindings_to_config(store)
    store.remove_binding("weixin", "u1")
    _sync_bindings_to_config(store, exclude={("weixin", "u1")})

    assert config["agent_bindings"] == [
        {"channel_type": "weixin", "conversation_id": "u9", "agent_id": "primary"}
    ]


def test_switch_to_default_leaves_no_residue(monkeypatch, tmp_path):
    """端到端：切到 coach 再切回默认，conf 与 store 均为空，路由回默认。"""
    import bridge.bridge as bridge_module
    from types import SimpleNamespace

    from channel import role_switch
    from channel.role_switch import handle_role_command

    registry = _registry(tmp_path)
    store = RoleBindingStore(str(tmp_path / "bindings.json"))
    monkeypatch.setattr(role_switch, "get_role_binding_store", lambda: store)
    monkeypatch.setattr(role_switch, "_rebuild_router", lambda bridge: None)

    config = {"agent_bindings": []}
    monkeypatch.setattr("config.conf", lambda: config)
    bridge = SimpleNamespace(agent_registry=registry)

    handle_role_command("/角色 coach", "weixin", "u1", bridge, bot_name="")
    assert store.get_binding("weixin", "u1") == "coach"
    assert config["agent_bindings"] == [
        {"channel_type": "weixin", "conversation_id": "u1", "agent_id": "coach"}
    ]

    handle_role_command("/回到大海", "weixin", "u1", bridge, bot_name="")
    assert store.get_binding("weixin", "u1") is None
    assert config["agent_bindings"] == []

    router = AgentRouter.from_config(
        {"agent_bindings": config["agent_bindings"]}, registry
    )
    assert router.resolve("weixin", ("u1",)) == "primary"
