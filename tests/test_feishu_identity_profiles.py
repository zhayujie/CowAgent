"""Offline identity/profile regression coverage; no Feishu API or LLM needed."""
import re
from types import SimpleNamespace
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import PurePath
from threading import Lock

import pytest

from agent.memory.feishu_identity import (
    feishu_identity, profile_path, attributed_query, attach_identity, identity_prompt,
)
from agent.tools.memory.feishu_member_profile import FeishuMemberProfileTool
from common import i18n


def identity(sender="ou_a", group="oc_one", app="cli_app", owner="", shared=False, tenant=""):
    msg = SimpleNamespace(actual_user_id=sender, to_user_id=app,
                          is_group=bool(group), other_user_id=group,
                          actual_user_nickname="同名", msg_id="om_test", identity_tenant_key=tenant)
    return feishu_identity(msg, owner_open_ids=[owner] if owner else [],
                           private_memory_mode="shared" if shared else "owner_workspace")


def test_owner_is_explicit_and_private_only():
    assert not identity()["is_owner"]
    assert identity(owner="ou_a")["is_owner"]
    assert not identity(owner="ou_a")["legacy_private"]
    assert identity(group="", owner="ou_a")["legacy_private"]
    assert not identity(sender="", owner="ou_a")["valid"]


def test_profile_keys_split_people_apps_groups_and_private(tmp_path):
    variants = [identity(), identity(sender="ou_b"), identity(group="oc_two"),
                identity(group=""), identity(app="cli_other")]
    assert len({profile_path(tmp_path, x) for x in variants}) == len(variants)
    assert identity()["memory_scope"] == identity(sender="ou_b")["memory_scope"]
    assert identity()["memory_scope"] != identity(group="oc_two")["memory_scope"]


def test_cross_tenant_group_members_share_memory_but_keep_individual_profiles(tmp_path):
    from agent.tools.edit.edit import Edit
    from agent.tools.write.write import Write

    workspace = str(tmp_path)
    writer = Write({"cwd": workspace})
    editor = Edit({"cwd": workspace})
    agent = SimpleNamespace(tools=[writer, editor], workspace_dir=workspace)
    first = identity(tenant="tenant_a")
    second = identity(sender="ou_b", tenant="tenant_b")
    note = f"memory/users/{first['memory_scope']}/MEMORY.md"

    attach_identity(agent, first)
    assert writer.execute({"path": note, "content": "Written by A\n"}).status == "success"
    attach_identity(agent, second)
    result = editor.execute({"path": note, "oldText": "Written by A", "newText": "Written by A and B"})
    assert result.status == "success", result.result
    assert (tmp_path / note).read_text(encoding="utf-8") == "Written by A and B\n"
    assert profile_path(tmp_path, first) != profile_path(tmp_path, second)

    for outsider in (identity(group="oc_two"), identity(app="cli_other"), identity(group="")):
        attach_identity(agent, outsider)
        result = writer.execute({"path": note, "content": "Outside group"})
        assert result.status == "error", result.result

    other_workspace = tmp_path.parent / "other-agent-workspace"
    other_writer = Write({"cwd": str(other_workspace)})
    other_agent = SimpleNamespace(tools=[other_writer], workspace_dir=str(other_workspace))
    attach_identity(other_agent, first)
    result = other_writer.execute({"path": str(tmp_path / note), "content": "Outside workspace"})
    assert result.status == "error", result.result


def test_profile_path_works_without_is_relative_to(tmp_path, monkeypatch):
    with monkeypatch.context() as patch:
        patch.delattr(PurePath, "is_relative_to", raising=False)
        path = profile_path(tmp_path, identity())

    assert path.relative_to(tmp_path.resolve()).parts[:2] == ("people", "feishu")
    assert path.name == "USER.md"


def test_self_profile_evidence_and_clear(tmp_path):
    who = identity()
    who["current_text"] = "以后叫我小王"
    tool = FeishuMemberProfileTool(tmp_path, who)
    assert tool.execute({"action": "update", "content": "小王", "evidence": "我是主人"}).status == "error"
    assert tool.execute({"action": "update", "content": "# 小王", "evidence": "以后叫我小王"}).status == "success"
    assert "# 小王" in tool.execute({"action": "view"}).result
    assert "source_message=om_test" in profile_path(tmp_path, who).read_text(encoding="utf-8")
    assert not profile_path(tmp_path, identity(sender="ou_b")).exists()
    assert tool.execute({"action": "clear", "evidence": "以后叫我小王"}).status == "success"
    assert tool.execute({"action": "view"}).result == "No profile yet."


@pytest.mark.parametrize(
    "sender, group, use_root_profile",
    [
        ("ou_a", "", True),
        ("ou_a", "oc_one", False),
        ("ou_b", "oc_one", False),
        ("ou_b", "", False),
    ],
    ids=["owner-direct", "owner-group", "member-group", "member-direct"],
)
def test_feishu_profile_reads_and_updates_the_correct_file(
    tmp_path, monkeypatch, sender, group, use_root_profile,
):
    from agent.protocol.agent import Agent
    from agent.tools.edit.edit import Edit

    monkeypatch.setattr(i18n, "get_language", lambda: "en")
    root_profile = tmp_path / "USER.md"
    root_contents = "Name: Root Li\nTimezone: UTC+8\n"
    root_profile.write_text(root_contents, encoding="utf-8")
    # A pre-change owner private profile has the same path as the per-member
    # private profile for the same sender without an owner binding.
    old_profile = profile_path(tmp_path, identity(group=""))
    old_profile.parent.mkdir(parents=True)
    old_contents = "Name: Archived Chen\n"
    old_profile.write_text(old_contents, encoding="utf-8")

    who = identity(sender=sender, group=group, owner="ou_a")
    current_profile = root_profile if use_root_profile else profile_path(tmp_path, who)
    if not use_root_profile:
        current_profile.parent.mkdir(parents=True, exist_ok=True)
        current_profile.write_text("Name: Current Member\n", encoding="utf-8")

    project_dir = tmp_path / "project"
    project_dir.mkdir()
    project_profile = project_dir / "USER.md"
    project_profile.write_text("Name: Project Decoy\n", encoding="utf-8")
    edit = Edit()
    agent = Agent("base", tools=[edit], workspace_dir=str(tmp_path), enable_skills=False)
    agent.apply_project_dir(str(project_dir))
    attach_identity(agent, who)

    prompt = agent.get_full_system_prompt()
    assert "Archived Chen" not in prompt
    assert "Project Decoy" not in prompt
    member_tools = [tool for tool in agent.tools if tool.name == "member_profile"]
    if use_root_profile:
        assert prompt.count("Name: Root Li") == 1
        assert f"use edit to update the relevant details in the workspace profile at `{root_profile.resolve()}`" in prompt
        assert not member_tools
        result = edit.execute({
            "path": str(root_profile.resolve()),
            "oldText": "Name: Root Li",
            "newText": "Name: Updated Name",
        })
        assert result.status == "success", result.result
        assert root_profile.read_text(encoding="utf-8") == "Name: Updated Name\nTimezone: UTC+8\n"
    else:
        assert "Root Li" not in prompt
        assert "Current Member" in prompt
        [member_tool] = member_tools
        member_tool.identity["current_text"] = "Call me Updated Name"
        result = member_tool.execute({
            "action": "update", "content": "Name: Updated Name", "evidence": "Call me Updated Name",
        })
        assert result.status == "success", result.result
        assert root_profile.read_text(encoding="utf-8") == root_contents

    assert "Name: Updated Name" in current_profile.read_text(encoding="utf-8")
    assert "Name: Updated Name" in agent.get_full_system_prompt()
    assert old_profile.read_text(encoding="utf-8") == old_contents
    assert project_profile.read_text(encoding="utf-8") == "Name: Project Decoy\n"


def test_parallel_profile_writes_are_complete(tmp_path):
    who = identity()
    who["current_text"] = "记住我"
    tool = FeishuMemberProfileTool(tmp_path, who)
    with ThreadPoolExecutor(max_workers=5) as pool:
        results = list(pool.map(lambda i: tool.execute({"action": "update", "content": str(i) * 500,
                                                       "evidence": "记住我"}), range(20)))
    assert all(r.status == "success" for r in results)
    assert "source_message" in tool.execute({"action": "view"}).result


def test_bind_replaces_scope_each_turn(tmp_path):
    search = SimpleNamespace(name="memory_search")
    get = SimpleNamespace(name="memory_get")
    agent = SimpleNamespace(tools=[search, get], workspace_dir=str(tmp_path))
    attach_identity(agent, identity())
    assert not search.include_shared and search.include_knowledge
    assert search.user_id == identity()["memory_scope"]
    assert get.allowed_memory_scope == search.user_id
    attach_identity(agent, identity(sender="ou_b"))
    assert len([t for t in agent.tools if t.name == "member_profile"]) == 1
    attach_identity(agent, None)
    assert search.include_shared and not search.include_knowledge and search.user_id is None
    assert get.allowed_memory_scope is None
    assert not any(t.name == "member_profile" for t in agent.tools)


def test_missing_identity_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setattr(i18n, "get_language", lambda: "en")
    with pytest.raises(ValueError):
        profile_path(tmp_path, identity(sender=""))
    assert "No profile is available." in identity_prompt(tmp_path, identity(sender=""))


def _listed_workspace_files(prompt):
    prefixes = ("- ✅ `", "**Files already auto-loaded**", "**已自动加载的文件**")
    notice_lines = [line for line in prompt.splitlines() if line.startswith(prefixes)]
    return re.findall(r"`([^`]+\.md)`", "\n".join(notice_lines))


@pytest.mark.parametrize("use_project_dir", [False, True], ids=["workspace", "project"])
@pytest.mark.parametrize("group", ["oc_one", ""], ids=["group", "non-owner-direct"])
@pytest.mark.parametrize(
    "language, identity_heading, scope_guidance, owner_guidance",
    [
        ("en", "Platform identity and profile boundaries", "For this turn, use only memory under",
         "In a direct chat with the configured owner"),
        ("zh", "身份与档案边界", "本轮覆盖默认记忆路径", "已绑定主人私聊"),
        ("zh-Hant", "檔案邊界", "本輪覆蓋預設記憶路徑", "可以使用根 USER.md 和 MEMORY.md"),
    ],
)
def test_scoped_prompt_does_not_load_owner_files(
    tmp_path, monkeypatch, language, identity_heading, scope_guidance, owner_guidance,
    use_project_dir, group,
):
    from agent.protocol.agent import Agent
    monkeypatch.setattr(i18n, "get_language", lambda: language)
    (tmp_path / "USER.md").write_text("owner-secret-user", encoding="utf-8")
    (tmp_path / "MEMORY.md").write_text("owner-secret-memory", encoding="utf-8")
    (tmp_path / "AGENT.md").write_text("Helpful group assistant", encoding="utf-8")
    (tmp_path / "RULE.md").write_text("Follow the workspace rules", encoding="utf-8")
    agent = Agent("cached-owner-secret", tools=[], workspace_dir=str(tmp_path), enable_skills=False)
    if use_project_dir:
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        agent.apply_project_dir(str(project_dir))
    sender = identity(group=group)
    attach_identity(agent, sender)
    prompt = agent.get_full_system_prompt()
    assert "owner-secret-user" not in prompt
    assert "owner-secret-memory" not in prompt
    assert '"sender_id": "ou_a"' in prompt
    assert identity_heading in prompt
    assert scope_guidance in prompt
    assert f"memory/users/{sender['memory_scope']}/MEMORY.md" in prompt
    assert owner_guidance not in prompt
    assert _listed_workspace_files(prompt) == ["AGENT.md", "RULE.md"]
    attach_identity(agent, identity(group="", owner="ou_a"))
    prompt = agent.get_full_system_prompt()
    assert "owner-secret-user" in prompt
    assert "owner-secret-memory" in prompt
    assert identity_heading in prompt
    assert owner_guidance in prompt
    assert scope_guidance not in prompt
    assert _listed_workspace_files(prompt) == ["AGENT.md", "USER.md", "RULE.md", "MEMORY.md"]
    attach_identity(agent, identity(sender="ou_b", group="", shared=True))
    prompt = agent.get_full_system_prompt()
    assert "owner-secret-user" in prompt
    assert "owner-secret-memory" in prompt
    assert scope_guidance not in prompt


def test_member_file_tools_report_why_access_was_denied(tmp_path):
    from agent.tools.ls.ls import Ls
    from agent.tools.read.read import Read
    from agent.tools.send.send import Send

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    config = {"cwd": str(workspace)}
    tools = [Ls(config), Read(config), Send(config)]
    agent = SimpleNamespace(tools=tools, workspace_dir=str(workspace))
    attach_identity(agent, identity(group=""))

    for tool in tools:
        for path, reason in (
            (tmp_path / "outside", "path outside Feishu workspace and project directory"),
            (workspace / "memory" / "long-term", "private memory path"),
        ):
            result = tool.execute_tool({"path": str(path)})
            assert result.status == "error"
            assert result.result == f"Error: Access denied: {reason}"


def test_memory_get_reports_protected_configuration_path(tmp_path):
    from agent.tools.memory.memory_get import MemoryGetTool

    manager = SimpleNamespace(config=SimpleNamespace(get_workspace=lambda: tmp_path))
    tool = MemoryGetTool(manager)
    attach_identity(SimpleNamespace(tools=[tool], workspace_dir=str(tmp_path)), identity(group="", shared=True))

    result = tool.execute_tool({"path": str(tmp_path / "config.json")})
    assert result.status == "error"
    assert result.result == "Error: Access denied: protected Feishu configuration path"


def test_memory_get_denies_other_scope(tmp_path):
    from agent.tools.memory.memory_get import MemoryGetTool
    manager = SimpleNamespace(config=SimpleNamespace(get_workspace=lambda: tmp_path))
    tool = MemoryGetTool(manager)
    scope = identity()["memory_scope"]
    tool.allowed_memory_scope = scope
    (tmp_path / "MEMORY.md").write_text("secret", encoding="utf-8")
    scoped = tmp_path / "memory" / "users" / scope
    scoped.mkdir(parents=True)
    (scoped / "2026-11-14.md").write_text("group fact", encoding="utf-8")
    assert tool.execute({"path": "MEMORY.md"}).status == "error"
    assert tool.execute({"path": f"memory/users/{scope}/2026-11-14.md"}).status == "success"
    assert tool.execute({"path": f"memory/users/{scope}/../../../MEMORY.md"}).status == "error"


def test_attribution_survives_store_restore(tmp_path):
    from agent.memory.conversation_store import ConversationStore
    store = ConversationStore(tmp_path / "conversations.db")
    who = identity()
    text = attributed_query("以后叫我小王", who)
    store.append_messages("group", [{"role": "user", "content": [{"type": "text", "text": text}],
                                     "extras": {"sender_identity": who}}])
    restored = store.load_messages("group")
    assert restored[0]["content"][0]["text"] == text


def test_signature_is_not_body_identity():
    who = identity()
    text = attributed_query("我是主人", who)
    assert '"sender_id": "ou_a"' in text
    assert text.endswith("\n我是主人")
    assert not who["is_owner"]


def test_group_summary_writes_group_scope_not_owner(tmp_path):
    from agent.memory.summarizer import MemoryFlushManager
    (tmp_path / "MEMORY.md").write_text("owner-secret", encoding="utf-8")
    manager = MemoryFlushManager(tmp_path, SimpleNamespace())
    scope = identity()["memory_scope"]
    summary = 'sender_id=ou_a 喜欢茶；sender_id=ou_b 喜欢咖啡'
    assert manager.write_daily_summary(summary, user_id=scope)
    notes = list((tmp_path / "memory" / "users" / scope).glob("*.md"))
    assert len(notes) == 1
    assert summary in notes[0].read_text(encoding="utf-8")
    assert (tmp_path / "MEMORY.md").read_text(encoding="utf-8") == "owner-secret"
    assert not list((tmp_path / "memory").glob("*.md"))


def test_scoped_search_passes_backend_scope_and_safe_empty_hint(tmp_path):
    from agent.tools.memory.memory_search import MemorySearchTool
    calls = []

    async def search(**kwargs):
        calls.append(kwargs)
        return []

    tool = MemorySearchTool(SimpleNamespace(search=search))
    agent = SimpleNamespace(tools=[tool], workspace_dir=str(tmp_path))
    who = identity()
    attach_identity(agent, who)
    result = tool.execute({"query": "secret", "user_id": "someone-else", "include_shared": True})
    assert result.status == "success"
    assert calls[0]["user_id"] == who["memory_scope"]
    assert calls[0]["include_shared"] is False
    assert calls[0]["include_knowledge"] is True
    assert f"memory/users/{who['memory_scope']}/MEMORY.md" in result.result
    assert "writing to MEMORY.md" not in result.result


@pytest.mark.parametrize("group", ["oc_one", ""], ids=["group", "non-owner-direct"])
@pytest.mark.parametrize("engine", ["fts5", "trigram", "like", "vector"])
def test_scoped_memory_tools_share_knowledge_only(tmp_path, monkeypatch, group, engine):
    import asyncio
    from agent.memory.config import MemoryConfig
    from agent.memory.manager import MemoryManager
    from agent.tools.memory.memory_get import MemoryGetTool
    from agent.tools.memory.memory_search import MemorySearchTool
    from config import conf

    monkeypatch.setitem(conf(), "knowledge", True)
    workspace = tmp_path / "agent"
    shared = tmp_path / "shared"
    knowledge = shared / "knowledge" / "guide.md"
    knowledge.parent.mkdir(parents=True)
    monkeypatch.setattr("common.state_dir.shared_root", lambda: shared)

    who = identity(group=group)
    own_note = f"memory/users/{who['memory_scope']}/MEMORY.md"
    other_scope = identity(sender="ou_b", group="oc_two" if group else "")["memory_scope"]
    private_notes = {
        "MEMORY.md": "root-secret",
        "memory/2026-11-14.md": "daily-secret",
        f"memory/users/{other_scope}/MEMORY.md": "other-secret",
    }
    query = "工作区指南" if engine == "trigram" else "workspaceguide"
    for relative, text in {**private_notes, own_note: "session-fact"}.items():
        path = workspace / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"{query} {text}\n", encoding="utf-8")
    knowledge.write_text(f"{query} shared-fact\n", encoding="utf-8")

    embedding = None
    if engine == "vector":
        embedding = SimpleNamespace(
            embed_query=lambda _: [1.0, 0.0],
            embed_batch=lambda texts: [[1.0, 0.0] for _ in texts],
        )
    manager = MemoryManager(MemoryConfig(workspace_root=str(workspace)), embedding_provider=embedding)
    try:
        asyncio.run(manager.sync())
        storage = manager.storage
        if engine == "vector":
            monkeypatch.setattr(storage, "search_keyword", lambda **_: [])
        elif engine == "like":
            monkeypatch.setattr(storage, "fts5_available", False)
            monkeypatch.setattr(storage, "trigram_fts5_available", False)
        else:
            available = storage.fts5_available if engine == "fts5" else storage.trigram_fts5_available
            if not available:
                pytest.skip(f"SQLite lacks {engine} support")
            if engine == "fts5":
                monkeypatch.setattr(storage, "trigram_fts5_available", False)
            monkeypatch.setattr(storage, "_search_like", lambda *_: pytest.fail(f"{engine} fell back to LIKE"))

        search = MemorySearchTool(manager)
        get = MemoryGetTool(manager)
        attach_identity(SimpleNamespace(tools=[search, get], workspace_dir=str(workspace)), who)

        result = search.execute({"query": query, "min_score": 0})
        assert result.status == "success", result.result
        assert "Found 2 relevant memories" in result.result
        assert "knowledge/guide.md" in result.result
        assert own_note in result.result
        for path, secret in private_notes.items():
            assert secret not in result.result
            assert get.execute({"path": path}).status == "error"

        for path, fact in [("knowledge/guide.md", "shared-fact"), (own_note, "session-fact")]:
            result = get.execute({"path": path})
            assert result.status == "success", result.result
            assert fact in result.result

        monkeypatch.setitem(conf(), "knowledge", False)
        result = search.execute({"query": query, "min_score": 0})
        assert result.status == "success", result.result
        assert "Found 1 relevant memories" in result.result
        assert own_note in result.result and "shared-fact" not in result.result
        assert get.execute({"path": "knowledge/guide.md"}).status == "error"
    finally:
        manager.close()


class _NightlyMemoryModel:
    def __init__(self):
        self.dreams = []

    def call(self, request):
        markers = sorted(set(re.findall(r"nightly-[a-z-]+", request.messages[0]["content"])))
        content = "\n".join(f"- {marker}" for marker in markers)
        if "[DREAM]" in request.system:
            self.dreams.append(markers)
            content = f"[MEMORY]\n{content}\n[DREAM]\n{content}"
        return {"choices": [{"message": {"content": content}}]}


def test_nightly_feishu_summaries_and_dreams_keep_their_scope(tmp_path, monkeypatch):
    import agent.memory
    from agent.memory.conversation_store import ConversationStore
    from agent.memory.summarizer import MemoryFlushManager
    from bridge.agent_initializer import AgentInitializer
    from config import conf

    monkeypatch.setitem(conf(), "deep_dream_enabled", True)
    monkeypatch.setitem(conf(), "conversation_persistence", True)
    store = ConversationStore(tmp_path / "conversations.db")
    monkeypatch.setattr(agent.memory, "get_conversation_store", lambda _: store)
    model = _NightlyMemoryModel()
    sessions = []
    initializer = AgentInitializer(None, SimpleNamespace(iter_agent_instances=lambda: iter(sessions)))
    group_sender = identity(owner="ou_a", tenant="tenant_a")
    private_sender = identity(sender="ou_b", group="", owner="ou_a")
    cases = [
        ("nightly-owner-direct", identity(group="", owner="ou_a")),
        ("nightly-shared-first", identity(group="", shared=True)),
        ("nightly-shared-second", identity(sender="ou_b", group="", shared=True)),
        ("nightly-owner-group", group_sender),
        ("nightly-member-group", identity(sender="ou_b", owner="ou_a", tenant="tenant_b")),
        ("nightly-member-direct", private_sender),
        ("nightly-restored-unbound", None),
    ]
    for marker, sender in cases:
        runtime = SimpleNamespace(
            agent_id="pony", workspace_dir=str(tmp_path), tools=[], messages_lock=Lock(), messages=[],
            memory_manager=SimpleNamespace(flush_manager=MemoryFlushManager(tmp_path, model)),
        )
        message = {"role": "user", "content": [{"type": "text", "text": marker}]}
        if sender:
            attach_identity(runtime, sender)
            runtime.messages = [message]
        else:
            store.append_messages(marker, [message], channel_type="feishu")
            initializer._restore_conversation_history(runtime, marker)
            assert runtime.messages
        sessions.append((runtime.agent_id, marker, runtime))

    initializer._flush_all_agents()

    today = datetime.now().strftime("%Y-%m-%d")
    group_dir = tmp_path / "memory" / "users" / group_sender["memory_scope"]
    private_dir = tmp_path / "memory" / "users" / private_sender["memory_scope"]
    outputs = {
        (tmp_path / "MEMORY.md", tmp_path / "memory"): [
            "nightly-owner-direct", "nightly-shared-first", "nightly-shared-second",
        ],
        (group_dir / "MEMORY.md", group_dir): ["nightly-member-group", "nightly-owner-group"],
        (private_dir / "MEMORY.md", private_dir): ["nightly-member-direct"],
    }
    for (main_file, daily_dir), expected in outputs.items():
        for path in (main_file, daily_dir / f"{today}.md", daily_dir / "dreams" / f"{today}.md"):
            markers = sorted(re.findall(r"nightly-[a-z-]+", path.read_text(encoding="utf-8")))
            assert markers == expected, path
    assert sorted(model.dreams) == sorted(outputs.values())


def test_nightly_dedup_tracks_identical_content_in_each_scope(tmp_path, monkeypatch):
    from agent.memory.summarizer import MemoryFlushManager
    from config import conf

    monkeypatch.setitem(conf(), "deep_dream_enabled", True)
    manager = MemoryFlushManager(tmp_path, _NightlyMemoryModel())
    messages = [{"role": "user", "content": "nightly-identical-content"}]
    scopes = (None, identity()["memory_scope"], identity(group="")["memory_scope"])
    for scope in scopes:
        assert manager.create_daily_summary(messages, user_id=scope)
        manager._last_flush_thread.join(timeout=5)
        assert not manager._last_flush_thread.is_alive()
        assert manager.deep_dream(user_id=scope)
    for scope in scopes:
        assert not manager.create_daily_summary(messages, user_id=scope)
        assert not manager.deep_dream(user_id=scope)


def test_scoped_prompt_failure_never_returns_cached_owner_prompt(tmp_path, monkeypatch):
    from agent.protocol.agent import Agent
    agent = Agent("cached-owner-secret", tools=[], workspace_dir=str(tmp_path), enable_skills=False)
    attach_identity(agent, identity())

    def fail(*args, **kwargs):
        raise OSError("profile unreadable")

    monkeypatch.setattr("agent.memory.feishu_identity.read_profile", fail)
    with pytest.raises(RuntimeError, match="Cannot safely build platform identity prompt"):
        agent.get_full_system_prompt()


def _link_knowledge_directory(link, target):
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError as exc:
        if getattr(exc, "winerror", None) != 1314:
            raise
        from _winapi import CreateJunction
        try:
            CreateJunction(str(target), str(link))
        except PermissionError:
            pytest.skip("Creating a directory link requires privileges on this Windows runner")


@pytest.mark.parametrize(
    "layout, group, project, mode",
    [
        ("local", "oc_one", False, "full-access"),
        ("local", "", True, "workspace-write"),
        ("local", "oc_one", True, "read-only"),
        ("default", "oc_one", True, "workspace-write"),
        ("shared", "oc_one", False, "full-access"),
        ("shared", "", True, "workspace-write"),
        ("shared", "oc_one", True, "read-only"),
        ("linked", "", False, "full-access"),
        ("linked", "oc_one", True, "workspace-write"),
    ],
)
def test_feishu_knowledge_prompt_matches_tool_access(
    tmp_path, monkeypatch, layout, group, project, mode,
):
    from agent.protocol.agent import Agent
    from agent.protocol.agent_stream import AgentStreamExecutor
    from agent.tools.edit.edit import Edit
    from agent.tools.read.read import Read
    from agent.tools.write.write import Write
    from common import state_dir
    from config import conf

    monkeypatch.setattr(i18n, "get_language", lambda: "en")
    monkeypatch.setitem(conf(), "knowledge", True)
    shared = tmp_path / "cow"
    workspace = shared if layout == "default" else shared / "agents" / "test"
    workspace.mkdir(parents=True)
    monkeypatch.setattr(state_dir, "shared_root", lambda: shared)
    # The runtime also allows the system temp dir. Keep it disjoint so the
    # workspace-write cases actually exercise the shared-root allowance.
    monkeypatch.setattr("agent.permission.policy.tempfile.gettempdir", lambda: str(tmp_path / "scratch"))
    own_knowledge = workspace / "knowledge"
    knowledge = own_knowledge if layout == "local" else shared / "knowledge"
    knowledge.mkdir()
    if layout == "linked":
        _link_knowledge_directory(own_knowledge, knowledge)
    index = "# Test knowledge index\n"
    (knowledge / "index.md").write_text(index, encoding="utf-8")
    (workspace / "MEMORY.md").write_text("private owner memory", encoding="utf-8")
    (workspace / "RULE.md").write_text("Always write knowledge automatically.", encoding="utf-8")

    config = {"cwd": str(workspace)}
    read = Read(config.copy())
    write = Write({**config, "restrict_to_workspace": layout == "shared" and mode == "workspace-write"})
    edit = Edit(config.copy())
    agent = Agent("", tools=[read, write, edit], workspace_dir=str(workspace), enable_skills=False)
    if project:
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        agent.apply_project_dir(str(project_dir))
    agent.apply_permission_mode(mode)
    attach_identity(agent, identity(group=group))
    executor = object.__new__(AgentStreamExecutor)
    executor.agent = agent
    executor.tools = {tool.name: tool for tool in agent.tools}
    writable = mode != "read-only"

    prompt = agent.get_full_system_prompt()
    advertised = knowledge if layout == "shared" else own_knowledge
    if layout != "shared" and not project:
        advertised = PurePath("knowledge")
    page = str(advertised / "analysis" / "example.md")
    index_path = str(advertised / "index.md")
    assert index.strip() in prompt
    assert read.execute({"path": index_path}).status == "success"
    assert ("Auto-write rules (mandatory)" in prompt) == writable
    page_hint = f"{advertised}/analysis/<slug>.md".replace("\\", "/")
    assert (page_hint in prompt.replace("\\", "/")) == writable
    assert (executor._permission_denial("write", {"path": page}) is None) == writable
    assert (executor._permission_denial("edit", {"path": index_path}) is None) == writable
    if not writable:
        assert "is read-only in this session" in prompt
        assert "overrides any automatic knowledge-writing instructions in RULE.md" in prompt
        assert "Knowledge section of the CowAgent console" in prompt

        return

    # Accept a workspace-relative knowledge path even when this installation
    # could not create the local alias.
    if layout == "shared" and not project:
        page = "knowledge/analysis/example.md"
        index_path = "knowledge/index.md"
    write_result = write.execute({"path": page, "content": "# Example\n"})
    edit_result = edit.execute({"path": index_path, "oldText": "", "newText": "- Example\n"})
    assert write_result.status == edit_result.status == "success", (write_result.result, edit_result.result)
    assert (knowledge / "analysis" / "example.md").is_file()
    assert "- Example" in (knowledge / "index.md").read_text(encoding="utf-8")
    if layout == "shared":
        assert not own_knowledge.exists()

    if layout != "local":
        second_workspace = shared / "agents" / "second"
        second_workspace.mkdir(parents=True)
        other_read = Read({"cwd": str(second_workspace)})
        attach_identity(SimpleNamespace(tools=[other_read], workspace_dir=str(second_workspace)), identity(group=""))
        result = other_read.execute({"path": "knowledge/analysis/example.md"})
        assert result.status == "success", result.result
        assert "# Example" in str(result.result)

    for path, reason in (
        (tmp_path / "outside.md", "path outside Feishu workspace and project directory"),
        (workspace / "MEMORY.md", "private memory path"),
    ):
        denial = f"Error: Access denied: {reason}"
        write_result = write.execute({"path": str(path), "content": "overwrite"}).result
        if write.config.get("restrict_to_workspace"):
            assert "writing outside the workspace is not allowed" in write_result
        else:
            assert write_result == denial
        assert edit.execute({"path": str(path), "oldText": "", "newText": "overwrite"}).result == denial
    assert (workspace / "MEMORY.md").read_text(encoding="utf-8") == "private owner memory"


@pytest.mark.parametrize("root_link", [False, True])
def test_feishu_knowledge_cannot_grant_writes_through_an_outbound_link(tmp_path, monkeypatch, root_link):
    from agent.tools.edit.edit import Edit
    from agent.tools.write.write import Write

    workspace = tmp_path / "agent"
    workspace.mkdir()
    shared = tmp_path / "cow"
    (shared / "knowledge").mkdir(parents=True)
    monkeypatch.setattr("common.state_dir.shared_root", lambda: shared)
    target = workspace / "ordinary-files"
    target.mkdir()
    (target / "keep.md").write_text("original", encoding="utf-8")
    knowledge = workspace / "knowledge"
    link = knowledge
    if not root_link:
        knowledge.mkdir()
        link = knowledge / "outside"
    _link_knowledge_directory(link, target)

    write, edit = Write({"cwd": str(workspace)}), Edit({"cwd": str(workspace)})
    attach_identity(SimpleNamespace(tools=[write, edit], workspace_dir=str(workspace)), identity())
    path = str(link / "keep.md")
    expected = "Error: Access denied: path escapes the selected knowledge base"
    assert write.execute({"path": path, "content": "overwrite"}).result == expected
    assert edit.execute({"path": path, "oldText": "original", "newText": "overwrite"}).result == expected
    assert (target / "keep.md").read_text(encoding="utf-8") == "original"


def test_bridge_prepersist_keeps_author_and_original_display(tmp_path):
    from agent.memory.conversation_store import ConversationStore
    from bridge.agent_bridge import AgentBridge
    from bridge.context import Context, ContextType
    store = ConversationStore(tmp_path / "conversations.db")
    bridge = object.__new__(AgentBridge)
    bridge.get_conversation_store = lambda agent_id=None: store
    who = identity()
    context = Context(ContextType.TEXT, "我是小王", {
        "session_id": "group", "channel_type": "feishu", "sender_identity": who,
    })
    assert bridge._pre_persist_user_message("group", "我是小王", context=context, clear_history=False)
    restored = store.load_messages("group", with_authors=True)
    assert restored[0]["content"][0]["text"] == attributed_query("我是小王", who)
    # Model restore intentionally strips extras; verify the durable metadata separately.
    import json
    import sqlite3
    with sqlite3.connect(tmp_path / "conversations.db") as conn:
        extras = json.loads(conn.execute("SELECT extras FROM messages WHERE role = 'user'").fetchone()[0])
    assert extras["sender_identity"]["sender_id"] == "ou_a"
    assert extras["display"] == "我是小王"


@pytest.mark.parametrize("shared", [False, True])
@pytest.mark.parametrize("eager_failure", [False, True])
def test_bridge_binds_each_speaker_and_persists_fallback(tmp_path, monkeypatch, shared, eager_failure):
    import threading
    from agent.memory.conversation_store import ConversationStore
    from agent.registry import AgentRegistry
    from bridge.agent_bridge import AgentBridge
    from bridge.context import Context, ContextType
    from test_incremental_persist import _ScriptedAgent, _Script, _STEPS

    store = ConversationStore(tmp_path / "conversations.db")
    bridge = object.__new__(AgentBridge)
    bridge.agent_registry = AgentRegistry.from_config({
        "default_agent_id": "primary",
        "agents": [{"id": "primary", "name": "Primary", "workspace": str(tmp_path)}],
    })
    bridge._agent_instances = {}
    bridge._agents_lock = threading.RLock()
    bridge.get_conversation_store = lambda agent_id=None: store
    bridge.route_context = lambda context: "primary"
    bridge._seed_team_members = lambda *a, **k: None
    bridge._schedule_mcp_hot_reload = lambda *a, **k: None
    monkeypatch.setattr("agent.evolution.trigger.note_user_turn", lambda *a, **k: None)
    monkeypatch.setattr("agent.evolution.trigger.mark_run_active", lambda *a, **k: None)
    agent = _ScriptedAgent(_Script(_STEPS))
    agent.workspace_dir = str(tmp_path)
    bridge.get_agent = lambda **kwargs: agent
    if eager_failure:
        bridge._pre_persist_user_message = lambda *a, **k: False

    for sender in ("ou_a", "ou_b"):
        session = "oc_one" if shared else f"{sender}:oc_one"
        msg = SimpleNamespace(actual_user_id=sender, identity_app_id="cli_app", is_group=True,
                              other_user_id="oc_one", actual_user_nickname="同名", msg_id=f"om_{sender}")
        context = Context(ContextType.TEXT, "记住我", {
            "session_id": session, "channel_type": "feishu", "msg": msg,
        })
        reply = bridge.agent_reply("记住我", context=context)
        assert reply.type.name == "TEXT"
        assert agent._sender_identity["sender_id"] == sender
        assert agent._current_user_id == identity()["memory_scope"]
        profile = next(t for t in agent.tools if t.name == "member_profile")
        assert profile.identity["current_text"] == "记住我"
        rows = store.load_messages(session, max_turns=100)
        user_rows = [m for m in rows if m["content"][0].get("type") == "text" and m["role"] == "user"]
        assert f'"sender_id": "{sender}"' in user_rows[-1]["content"][0]["text"]
