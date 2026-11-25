"""An uploaded avatar reaches the running registry without a runtime reload."""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

@pytest.fixture
def live_registry(tmp_path):
    from agent.registry import AgentRegistry, set_agent_registry

    registry = AgentRegistry.from_config(
        {
            "default_agent_id": "main",
            "agents": [
                {"id": "main", "name": "Main", "workspace": str(tmp_path / "main")},
                {"id": "writer", "name": "Writer", "workspace": str(tmp_path / "writer")},
            ],
        }
    )
    set_agent_registry(registry)
    yield registry
    set_agent_registry(None)


def test_the_live_profile_carries_the_uploaded_image(live_registry):
    from channel.web.api.agents import AVATAR_IMAGE_TOKEN, _refresh_live_avatar

    _refresh_live_avatar("writer")

    profile = live_registry.get("writer", require_enabled=False)
    assert profile.avatar == AVATAR_IMAGE_TOKEN
    assert profile.name == "Writer"
    assert live_registry.get("main").avatar is None


def test_an_unknown_agent_is_only_logged(live_registry):
    from channel.web.api.agents import _refresh_live_avatar

    _refresh_live_avatar("missing")

    assert [p.id for p in live_registry.list(include_disabled=True)] == ["main", "writer"]
