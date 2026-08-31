"""P1-1 修复验证：绑定到已停用 agent 时，角色指令仍可执行（自救）。

当会话被绑定到一个随后被禁用/删除的 agent 时，route_context() 会抛
AgentUnavailableError。若角色指令拦截发生在 route_context 之后，该异常
会提前 return，用户将无法通过 /角色 /回到大海 自救。本测试锁定此行为：
produce() 必须先处理角色指令，再进入路由。
"""

from types import SimpleNamespace

import pytest

from agent.registry import AgentProfile, AgentRegistry
from agent.routing import AgentUnavailableError
from bridge.context import Context, ContextType
from channel.chat_channel import ChatChannel
from channel import role_switch
from channel.role_switch import RoleBindingStore


class _FakeBridge:
    def __init__(self, registry):
        self.agent_registry = registry
        self.agent_router = None

    def route_context(self, context):
        raise AgentUnavailableError("conversation binding selected agent 'coach'")


class _FakeBridgeHolder:
    """提供 get_agent_bridge() 的 Bridge 单例替身。"""

    def __init__(self, registry):
        self.agent_bridge = _FakeBridge(registry)

    def get_agent_bridge(self):
        return self.agent_bridge


class _RecorderChannel(ChatChannel):
    """最小 ChatChannel 子类：拦截 _send_reply 以捕获回复。"""

    def __init__(self, channel_type="weixin"):
        super().__init__()
        self.channel_type = channel_type
        self.name = "我的机器人"
        self.replies = []

    def _send_reply(self, context, reply, *args, **kwargs):
        self.replies.append(reply)
        return True


@pytest.fixture
def disabled_bridge(tmp_path, monkeypatch):
    """coach 被禁用的 registry + 绑定到 coach 的持久化 store。"""
    registry = AgentRegistry(
        [
            AgentProfile("primary", "主助手", str(tmp_path / "primary")),
            AgentProfile("coach", "职业教练", str(tmp_path / "coach"), enabled=False),
        ],
        default_agent_id="primary",
    )
    store = RoleBindingStore(str(tmp_path / "bindings.json"))
    store.set_binding("weixin", "u1", "coach")
    monkeypatch.setattr(role_switch, "get_role_binding_store", lambda: store)
    monkeypatch.setattr(role_switch, "_sync_bindings_to_config", lambda store, exclude=None: None)
    monkeypatch.setattr(role_switch, "_rebuild_router", lambda bridge: None)
    from bridge import bridge as bridge_module

    monkeypatch.setattr(
        bridge_module, "Bridge", lambda: _FakeBridgeHolder(registry), raising=False
    )
    return store


def test_recover_command_works_when_bound_agent_disabled(disabled_bridge):
    """绑定停用角色后，/回到大海 仍能切换回默认角色。"""
    channel = _RecorderChannel()
    context = Context(ContextType.TEXT, "/回到大海", kwargs={})
    context["session_id"] = "u1"
    context["channel_type"] = "weixin"

    channel.produce(context)

    assert len(channel.replies) == 1
    assert "主助手" in channel.replies[0].content
    assert disabled_bridge.get_binding("weixin", "u1") is None


def test_switch_command_works_when_bound_agent_disabled(disabled_bridge):
    """绑定停用角色后，/角色 <其他角色> 仍能切换。"""
    channel = _RecorderChannel()
    context = Context(ContextType.TEXT, "/角色 coach", kwargs={})
    context["session_id"] = "u1"
    context["channel_type"] = "weixin"

    channel.produce(context)

    assert len(channel.replies) == 1
    # 绑定已存在且禁用 → 走"已绑定停用角色"逻辑或切换提示，但绝不返回停用文案
    assert "已停用" not in channel.replies[0].content
