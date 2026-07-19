from pathlib import Path

import pytest

from agent.memory import (
    MemoryConfig,
    clear_conversation_store_cache,
    get_default_memory_config,
    get_conversation_store,
    set_global_memory_config,
)
from agent.registry import AgentProfile, AgentRegistry, get_agent_registry, set_agent_registry
from agent.tools.scheduler.integration import (
    get_scheduler_service,
    get_task_store,
    init_scheduler,
    reset_scheduler_services,
)


@pytest.fixture
def isolated_registry(tmp_path, monkeypatch):
    from agent.tools.scheduler.scheduler_service import SchedulerService

    monkeypatch.setattr(
        SchedulerService, "start", lambda service: setattr(service, "running", True)
    )
    monkeypatch.setattr(
        SchedulerService, "stop", lambda service: setattr(service, "running", False)
    )
    previous = get_agent_registry()
    registry = AgentRegistry(
        [
            AgentProfile("primary", "Primary", str(tmp_path / "primary")),
            AgentProfile("research", "Research", str(tmp_path / "research")),
        ],
        default_agent_id="primary",
    )
    set_agent_registry(registry)
    clear_conversation_store_cache()
    reset_scheduler_services()
    try:
        yield registry
    finally:
        reset_scheduler_services()
        clear_conversation_store_cache()
        set_agent_registry(previous)


def _message(text):
    return {"role": "user", "content": [{"type": "text", "text": text}]}


def _task(task_id, name):
    return {
        "id": task_id,
        "name": name,
        "enabled": False,
        "schedule": {"type": "cron", "cron": "0 9 * * *"},
        "action": {"type": "send_message", "content": name},
    }


def test_conversations_with_same_session_id_use_different_databases(
    isolated_registry,
):
    primary = isolated_registry.get("primary")
    research = isolated_registry.get("research")
    primary_store = get_conversation_store(primary.workspace)
    research_store = get_conversation_store(research.workspace)

    primary_store.append_messages("same-session", [_message("primary")])
    research_store.append_messages("same-session", [_message("research")])

    assert primary_store is not research_store
    assert primary_store.load_messages("same-session")[0]["content"][0]["text"] == "primary"
    assert research_store.load_messages("same-session")[0]["content"][0]["text"] == "research"
    assert Path(primary_store._db_path) == Path(primary.workspace) / "memory/long-term/index.db"
    assert Path(research_store._db_path) == Path(research.workspace) / "memory/long-term/index.db"


def test_memory_config_keeps_each_agent_index_under_its_workspace(
    isolated_registry,
):
    primary = isolated_registry.get("primary")
    research = isolated_registry.get("research")

    primary_db = MemoryConfig(workspace_root=primary.workspace).get_db_path()
    research_db = MemoryConfig(workspace_root=research.workspace).get_db_path()

    assert primary_db != research_db
    assert primary_db == Path(primary.workspace) / "memory/long-term/index.db"
    assert research_db == Path(research.workspace) / "memory/long-term/index.db"


def test_scheduler_stores_allow_same_task_id_per_agent(isolated_registry):
    class Bridge:
        agent_registry = isolated_registry

    bridge = Bridge()
    for profile in isolated_registry.list(include_disabled=False):
        assert init_scheduler(bridge, profile.workspace, profile.id)

    primary_store = get_task_store(agent_id="primary")
    research_store = get_task_store(agent_id="research")
    primary_store.add_task(_task("daily", "Primary daily"))
    research_store.add_task(_task("daily", "Research daily"))

    assert primary_store is not research_store
    assert primary_store.get_task("daily")["name"] == "Primary daily"
    assert research_store.get_task("daily")["name"] == "Research daily"
    assert Path(primary_store.store_path) == Path(
        isolated_registry.get("primary").workspace
    ) / "scheduler/tasks.json"
    assert Path(research_store.store_path) == Path(
        isolated_registry.get("research").workspace
    ) / "scheduler/tasks.json"
    assert get_scheduler_service(agent_id="primary") is not get_scheduler_service(
        agent_id="research"
    )


def test_no_argument_conversation_store_preserves_single_agent_default(
    isolated_registry,
):
    previous = get_default_memory_config()
    default_workspace = isolated_registry.get("primary").workspace
    try:
        set_global_memory_config(MemoryConfig(workspace_root=default_workspace))
        clear_conversation_store_cache()
        default_store = get_conversation_store()
        explicit_store = get_conversation_store(default_workspace)
        assert default_store is explicit_store
    finally:
        set_global_memory_config(previous)
        clear_conversation_store_cache()
