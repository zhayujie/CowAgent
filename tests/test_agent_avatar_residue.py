# encoding:utf-8
"""Deleting an Agent removes its avatar files, and GET stops serving an id that left the roster."""

import json

import pytest

from agent import team
from agent.admin import AgentAdminService
from agent.registry import AgentRegistry, set_agent_registry


@pytest.fixture
def admin(tmp_path):
    primary = tmp_path / "primary"
    primary.mkdir()
    settings = {
        "agent_workspace": str(tmp_path),
        "default_agent_id": "primary",
        "agents": [{"id": "primary", "name": "Primary", "workspace": str(primary), "enabled": True}],
        "channel_instances": [],
    }
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(settings), encoding="utf-8")
    set_agent_registry(AgentRegistry.from_config(team.resolve(settings)))
    service = AgentAdminService(str(config_path))
    # delete_agent only erases workspaces under <root>/agents/<id>.
    (tmp_path / "agents").mkdir()
    service.create_agent("research", "Research", str(tmp_path / "agents" / "research"))
    try:
        yield service, tmp_path
    finally:
        set_agent_registry(None)


def _avatar_file(root, agent_id, suffix=".png"):
    from common.state_dir import shared_root

    # shared_root() follows the global registry, which create/delete replaced.
    set_agent_registry(AgentRegistry.from_config(team.resolve({"agent_workspace": str(root)})))
    base = shared_root() / "avatars"
    base.mkdir(parents=True, exist_ok=True)
    path = base / f"{agent_id}{suffix}"
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + agent_id.encode())
    return path


def _get_avatar(agent_id):
    from channel.web.api import agents as agents_module
    web = pytest.importorskip("web")
    headers = {}
    env = {"REQUEST_METHOD": "GET", "PATH_INFO": "/api/agents/%s/avatar" % agent_id}
    ctx = type("Ctx", (), {"status": "200 OK", "headers": {}, "env": env})()
    real_ctx, real_header = web.ctx, web.header
    web.ctx, web.header = ctx, headers.__setitem__
    try:
        body = agents_module.AgentAvatarHandler().GET(agent_id)
    finally:
        web.ctx, web.header = real_ctx, real_header
    return body, ctx.status, headers


def test_delete_agent_removes_every_avatar_extension_but_not_neighbours(admin):
    service, root = admin
    primary_avatar = _avatar_file(root, "primary")
    written = [_avatar_file(root, "research", s) for s in (".png", ".jpg")]

    service.delete_agent("research")

    assert not (root / "agents" / "research").exists()
    assert not any(p.exists() for p in written)
    assert primary_avatar.is_file()


def test_delete_agent_without_avatar_succeeds(admin):
    service, _ = admin
    assert service.delete_agent("research")["deleted"] is True


def test_reused_id_starts_without_picture(admin):
    from channel.web.api.agents import _avatar_path

    service, root = admin
    _avatar_file(root, "research")
    service.delete_agent("research")
    service.create_agent("research", "Research", str(root / "agents" / "research"))

    assert _avatar_path("research") is None


def test_avatar_endpoint_serves_live_agent(admin):
    _, root = admin
    avatar = _avatar_file(root, "research")

    body, status, headers = _get_avatar("research")

    assert status == "200 OK", f"{status}: {body!r}"
    assert body == avatar.read_bytes()
    assert headers["Content-Type"] == "image/png"


def test_avatar_endpoint_refuses_deleted_agent(admin):
    service, root = admin
    service.delete_agent("research")
    # A leftover file must not be served once the id is off the roster.
    _avatar_file(root, "research")

    body, status, _ = _get_avatar("research")

    assert status == "404 Not Found"
    assert b"PNG" not in (body if isinstance(body, bytes) else body.encode())
