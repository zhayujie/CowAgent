import pytest

from agent.registry import AgentProfile, AgentRegistry
from agent.routing import AgentBindingError, AgentRouter
from bridge.context import Context, ContextType


@pytest.fixture
def registry(tmp_path):
    return AgentRegistry(
        [
            AgentProfile("primary", "Primary", str(tmp_path / "primary")),
            AgentProfile("research", "Research", str(tmp_path / "research")),
            AgentProfile(
                "disabled", "Disabled", str(tmp_path / "disabled"), enabled=False
            ),
        ],
        default_agent_id="primary",
    )


def _router(registry, bindings):
    return AgentRouter.from_config({"agent_bindings": bindings}, registry)


def test_exact_binding_precedes_channel_default(registry):
    router = _router(
        registry,
        [
            {"channel_type": "feishu", "agent_id": "primary"},
            {
                "channel_type": "feishu",
                "conversation_id": "chat-research",
                "agent_id": "research",
            },
        ],
    )

    assert router.resolve("feishu", ("chat-research",)) == "research"
    assert router.resolve("feishu", ("another-chat",)) == "primary"


def test_explicit_selection_precedes_bindings(registry):
    router = _router(
        registry,
        [{"channel_type": "web", "agent_id": "research"}],
    )

    assert router.resolve("web", ("session-1",), "primary") == "primary"


def test_context_checks_session_and_receiver_for_exact_binding(registry):
    router = _router(
        registry,
        [
            {
                "channel_type": "slack",
                "conversation_id": "channel-7",
                "agent_id": "research",
            }
        ],
    )
    context = Context(ContextType.TEXT, "hello", kwargs={})
    context["channel_type"] = "slack"
    context["session_id"] = "user:channel-7"
    context["receiver"] = "channel-7"

    assert router.resolve_context(context) == "research"
    assert context["agent_id"] == "research"


def test_unavailable_binding_falls_back_to_default(registry, monkeypatch):
    warnings = []
    monkeypatch.setattr("agent.routing.logger.warning", warnings.append)
    router = _router(
        registry,
        [{"channel_type": "telegram", "agent_id": "disabled"}],
    )

    assert router.resolve("telegram", ("chat",)) == "primary"
    assert any("using default='primary'" in message for message in warnings)


def test_unbound_channel_uses_configured_default(registry):
    assert _router(registry, []).resolve("discord", ("123",)) == "primary"


@pytest.mark.parametrize(
    "bindings",
    [
        "not-a-list",
        [{"channel_type": "web", "agent_id": ""}],
        [{"channel_type": "", "agent_id": "primary"}],
        [
            {"channel_type": "web", "agent_id": "primary"},
            {"channel_type": "web", "agent_id": "research"},
        ],
    ],
)
def test_invalid_or_duplicate_bindings_are_rejected(registry, bindings):
    with pytest.raises(AgentBindingError):
        _router(registry, bindings)
