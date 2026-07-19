from agent.registry import (
    AgentProfile,
    AgentRegistry,
    get_agent_registry,
    set_agent_registry,
)
from agent.routing import AgentRouter, get_agent_router, set_agent_router
from common.tmp_dir import get_agent_tmp_dir


def test_channel_attachment_tmp_follows_agent_binding(tmp_path):
    previous_registry = get_agent_registry()
    previous_router = get_agent_router(previous_registry)
    registry = AgentRegistry(
        [
            AgentProfile("primary", "Primary", str(tmp_path / "primary")),
            AgentProfile("research", "Research", str(tmp_path / "research")),
        ],
        default_agent_id="primary",
    )
    router = AgentRouter.from_config(
        {
            "agent_bindings": [
                {
                    "channel_type": "feishu",
                    "conversation_id": "chat-research",
                    "agent_id": "research",
                }
            ]
        },
        registry,
    )
    set_agent_registry(registry)
    set_agent_router(router)
    try:
        routed = get_agent_tmp_dir("feishu", ("chat-research", "user-1"))
        fallback = get_agent_tmp_dir("feishu", ("chat-primary", "user-1"))

        assert routed == str(tmp_path / "research" / "tmp")
        assert fallback == str(tmp_path / "primary" / "tmp")
        assert (tmp_path / "research" / "tmp").is_dir()
        assert (tmp_path / "primary" / "tmp").is_dir()
    finally:
        set_agent_registry(previous_registry)
        set_agent_router(previous_router)


def test_explicit_agent_tmp_selection(tmp_path):
    previous_registry = get_agent_registry()
    previous_router = get_agent_router(previous_registry)
    registry = AgentRegistry(
        [
            AgentProfile("primary", "Primary", str(tmp_path / "primary")),
            AgentProfile("research", "Research", str(tmp_path / "research")),
        ],
        default_agent_id="primary",
    )
    router = AgentRouter(registry)
    set_agent_registry(registry)
    set_agent_router(router)
    try:
        selected = get_agent_tmp_dir(agent_id="research")

        assert selected == str(tmp_path / "research" / "tmp")
    finally:
        set_agent_registry(previous_registry)
        set_agent_router(previous_router)
