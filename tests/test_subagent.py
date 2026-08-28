"""Sub agents: templates, guards, isolation, and the off-by-default switch.

No LLM is called. A stub Agent stands in for the child so these assert the
wiring — which template, which tools, which context, which guard — rather than
what a model happens to reply.
"""

import json
import shutil
import threading
import time
from pathlib import Path

ASSET_DIR = Path(__file__).resolve().parent.parent / "agent" / "subagent" / "assets"

import pytest

from agent.subagent import (
    BLOCKED_TOOLS,
    SubagentSettings,
    SubagentTask,
    current_depth,
    load_templates,
    parse_template,
    run_tasks,
)
from agent.tools.subagent import SubagentTool


class _Tool:
    def __init__(self, name):
        self.name = name


class _FakeParent:
    """Enough of an Agent for the runner to build a child from."""

    def __init__(self, tools, workspace_dir):
        self.tools = tools
        self.workspace_dir = workspace_dir
        # The runner copies both onto the child so a sub agent cannot widen
        # the session's reach. Unset here, as on a fresh Agent.
        self.project_dir = None
        self.permission_mode = None
        self.model = object()
        self.max_steps = 7
        self.max_context_tokens = 1234
        self.skill_manager = None
        self.enable_skills = False
        self.runtime_info = None
        self.messages = []


@pytest.fixture
def workspace(tmp_path):
    return tmp_path / "ws"


@pytest.fixture
def parent(workspace):
    workspace.mkdir(parents=True, exist_ok=True)
    tools = [
        _Tool(n)
        for n in ("read", "ls", "search_files", "write", "bash", "send", "subagent")
    ]
    return _FakeParent(tools, str(workspace))


@pytest.fixture
def enabled(monkeypatch):
    settings = SubagentSettings(enabled=True, max_depth=1, max_concurrent=3, timeout_seconds=30)
    monkeypatch.setattr(SubagentSettings, "from_config", classmethod(lambda cls: settings))
    return settings


@pytest.fixture
def spawn_tool(parent, workspace):
    tool = SubagentTool({"cwd": str(workspace)})
    tool.context = parent
    return tool


def _capture_children(monkeypatch, reply="done"):
    """Replace the child Agent with a recorder."""
    built = []

    class _StubChild:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.extra_system_suffix = None
            built.append(self)

        def run_stream(self, goal, clear_history=False, cancel_event=None, on_event=None):
            self.goal = goal
            self.clear_history = clear_history
            self.depth_seen = current_depth()
            return reply

    monkeypatch.setattr("agent.protocol.agent.Agent", _StubChild)
    return built


# --- templates ---------------------------------------------------------------


def test_builtin_templates_are_always_available(workspace):
    templates = load_templates(str(workspace))
    assert "general-purpose" in templates
    assert "explore" in templates


def test_user_template_is_loaded_from_the_workspace(workspace):
    directory = workspace / "subagents"
    directory.mkdir(parents=True)
    (directory / "翻译.md").write_text(
        "---\nname: translator\ndescription: Translate documents.\ntools: read, write\n---\n"
        "You translate text and preserve formatting.\n",
        encoding="utf-8",
    )

    template = load_templates(str(workspace))["translator"]
    assert template.description == "Translate documents."
    assert template.tools == ["read", "write"]
    assert "preserve formatting" in template.prompt


def test_user_template_can_replace_a_builtin(workspace):
    directory = workspace / "subagents"
    directory.mkdir(parents=True)
    (directory / "explore.md").write_text(
        "---\nname: explore\ndescription: Mine.\n---\nMy own instructions.\n", encoding="utf-8"
    )

    assert load_templates(str(workspace))["explore"].description == "Mine."


def test_the_shipped_guide_is_not_offered_as_a_type(workspace):
    """README.md sits in the same directory as real templates. Loading it would
    put a bogus type in front of the Agent on every turn."""
    directory = workspace / "subagents"
    directory.mkdir(parents=True)
    (directory / "README.md").write_text(
        "---\nname: readme\ndescription: How to write one.\n---\nFormat docs.\n",
        encoding="utf-8",
    )

    templates = load_templates(str(workspace))
    assert "readme" not in templates
    assert set(templates) == {"general-purpose", "explore"}


def test_the_repo_ships_a_guide_that_documents_the_real_format():
    """The guide is what a user copies from, so it has to stay in step with the
    loader rather than drift into describing fields that do not exist."""
    guide = ASSET_DIR / "README.md"
    assert guide.is_file(), "no sub agent guide shipped for users to copy"
    text = guide.read_text(encoding="utf-8")

    for name in sorted(BLOCKED_TOOLS):
        assert name in text, f"the guide omits {name} from the denied-tools list"


@pytest.mark.parametrize(
    "language, marker",
    [
        # Wording the tool listing does not also carry, or this would still
        # pass with the rule itself deleted.
        ("en", "needs research, search or information gathering"),
        ("zh", "信息采集的独立任务"),
    ],
)
def test_the_prompt_tells_the_agent_when_to_delegate(language, marker):
    """Left to the tool description alone the model competes it against ~30
    other tools and just searches directly, which is what happened in
    practice. The rule has to be in the prompt itself, in both languages."""
    from agent.prompt.builder import _build_tooling_section

    class FakeTool:
        def __init__(self, name):
            self.name = name

        def __str__(self):
            return self.name

    without = _build_tooling_section([FakeTool("read")], language)
    assert marker not in "\n".join(without), "delegation rule shown without the tool"

    with_tool = _build_tooling_section([FakeTool("read"), FakeTool("subagent")], language)
    assert marker in "\n".join(with_tool)

    # The prompt is paid for on every turn by every user, so the rule gets one
    # line — enough to make the model consider the tool. When and how to use it
    # live in the tool description, which it reads once it looks. Counted in
    # lines rather than characters, which would just track the language.
    added = len(with_tool) - len(without)
    assert added == 1, f"delegation guidance grew to {added} lines"


def test_the_tool_is_pitched_at_independent_work_not_at_a_step_count(workspace):
    """Two ways to get this wrong, and we have shipped both. Forbidding the
    handover of a whole task stopped research being delegated at all; a
    "more than N reads" trigger fires on ordinary work, and every firing costs
    a full model run the user waits through. The criterion is whether the work
    is self-contained and substantial enough to be worth handing over."""
    from agent.tools.subagent import SubagentTool

    description = SubagentTool(config={"cwd": str(workspace)}).description
    assert "whole task unchanged" not in description
    assert "three searches" not in description
    assert "self-contained" in description
    assert "substantial research" in description
    # Ordinary work stays with the caller; that has to be said, not implied.
    assert "finish yourself directly" in description


def test_the_shipped_example_is_inert_until_renamed(workspace):
    """The example is there to be copied, so it has to parse — but it must not
    quietly become a type of its own, or every install would carry a research
    agent nobody asked for."""
    directory = workspace / "subagents"
    directory.mkdir(parents=True)
    for asset in ASSET_DIR.iterdir():
        shutil.copyfile(asset, directory / asset.name)

    assert set(load_templates(str(workspace))) == {"general-purpose", "explore"}

    example = directory / "example.md.template"
    assert example.is_file(), "no example shipped for users to copy"
    example.rename(directory / "research-report.md")

    templates = load_templates(str(workspace))
    added = set(templates) - {"general-purpose", "explore"}
    assert len(added) == 1, "renaming the example did not produce exactly one type"

    template = templates[added.pop()]
    assert template.description.strip(), "the example has no description to pick it by"
    assert template.tools != ["*"], "the example's tools list was ignored"
    assert not BLOCKED_TOOLS & set(template.tools)
    assert template.prompt.strip(), "the example has no instructions in its body"


@pytest.mark.parametrize(
    "content",
    [
        "---\nname: x\n---\nBody but no description.",
        "---\nname: x\ndescription: Has one.\n---\n",
        "No frontmatter at all.",
    ],
)
def test_unusable_templates_are_rejected(content):
    assert parse_template(content, "fallback", source="t.md") is None


def test_template_tool_selection_subtracts_the_blocklist(parent):
    templates = load_templates(parent.workspace_dir)

    explore = [t.name for t in templates["explore"].select_tools(parent.tools)]
    assert explore == ["read", "ls", "search_files"]

    general = [t.name for t in templates["general-purpose"].select_tools(parent.tools)]
    assert "write" in general and "bash" in general
    # "*" must not mean "including the ones no sub agent may have".
    assert not BLOCKED_TOOLS & set(general)
    assert "subagent" not in general and "send" not in general


# --- the child's context -----------------------------------------------------


def test_child_gets_the_task_but_not_the_parents_persona_or_memory(
    parent, workspace, enabled, monkeypatch
):
    built = _capture_children(monkeypatch)
    templates = load_templates(str(workspace))

    run_tasks(
        parent,
        [SubagentTask(goal="Find the config", context="Look under /etc", subagent_type="explore")],
        templates,
        enabled,
    )

    child = built[0]
    assert child.kwargs["skip_context_files"] is True
    assert child.kwargs["memory_manager"] is None
    assert child.kwargs["workspace_dir"] == str(workspace)
    assert child.kwargs["model"] is parent.model
    assert child.clear_history is True

    brief = child.extra_system_suffix
    assert "Find the config" in brief
    assert "Look under /etc" in brief
    assert "read-only" in brief


def test_a_type_that_gives_up_tools_gives_up_skills_with_them(
    parent, workspace, enabled, monkeypatch
):
    """A skill is a workflow written end to end, and most end in a write. Show
    one to a read-only sub agent and it spends turns getting ready for a step
    it will never reach, then reports that it could not take it."""
    parent.skill_manager = object()
    parent.enable_skills = True
    built = _capture_children(monkeypatch)
    templates = load_templates(str(workspace))

    run_tasks(
        parent,
        [
            SubagentTask(goal="Find it", subagent_type="explore"),
            SubagentTask(goal="Fix it", subagent_type="general-purpose"),
        ],
        templates,
        enabled,
    )

    by_goal = {child.goal: child for child in built}
    assert by_goal["Find it"].kwargs["skill_manager"] is None
    assert by_goal["Find it"].kwargs["enable_skills"] is False
    # Full tool set, full skills: nothing it reads about is out of reach.
    assert by_goal["Fix it"].kwargs["skill_manager"] is parent.skill_manager
    assert by_goal["Fix it"].kwargs["enable_skills"] is True


def test_skip_context_files_actually_keeps_the_persona_out_of_the_prompt(workspace):
    """The flag being passed is not the same as the flag working. This builds a
    real Agent, so a regression in get_full_system_prompt is caught here."""
    from agent.protocol.agent import Agent

    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "AGENT.md").write_text(
        "You are PIRATE-BOT and you always say Arrr.", encoding="utf-8"
    )

    inheriting = Agent(system_prompt="base", workspace_dir=str(workspace), enable_skills=False)
    isolated = Agent(
        system_prompt="base",
        workspace_dir=str(workspace),
        enable_skills=False,
        skip_context_files=True,
    )

    assert "PIRATE-BOT" in inheriting.get_full_system_prompt()
    assert "PIRATE-BOT" not in isolated.get_full_system_prompt()


def test_the_prompt_does_not_claim_context_files_it_did_not_load(workspace):
    """Suppressing the files but keeping the "already loaded, no need to read
    them" notice leaves the sub agent both uninformed and told not to look."""
    from agent.protocol.agent import Agent

    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "RULE.md").write_text("Always write output as HTML.", encoding="utf-8")

    inheriting = Agent(system_prompt="base", workspace_dir=str(workspace), enable_skills=False)
    isolated = Agent(
        system_prompt="base",
        workspace_dir=str(workspace),
        enable_skills=False,
        skip_context_files=True,
    )

    assert "RULE.md" in inheriting.get_full_system_prompt()
    assert "RULE.md" not in isolated.get_full_system_prompt()


def test_child_runs_one_level_deeper_than_its_parent(parent, workspace, enabled, monkeypatch):
    built = _capture_children(monkeypatch)

    assert current_depth() == 0
    run_tasks(parent, [SubagentTask(goal="go")], load_templates(str(workspace)), enabled)

    assert built[0].depth_seen == 1
    # The counter lives in the worker's context copy, so the caller is untouched.
    assert current_depth() == 0


# --- guards ------------------------------------------------------------------


def test_tool_is_refused_while_the_feature_is_off(spawn_tool, monkeypatch):
    off = SubagentSettings(enabled=False)
    monkeypatch.setattr(SubagentSettings, "from_config", classmethod(lambda cls: off))

    result = spawn_tool.execute({"goal": "anything"})
    assert result.status == "error"
    assert "disabled" in result.result


def test_depth_limit_stops_a_sub_agent_spawning_another(spawn_tool, enabled, monkeypatch):
    monkeypatch.setattr("agent.subagent.current_depth", lambda: 1)

    result = spawn_tool.execute({"goal": "recurse"})
    assert result.status == "error"
    assert "max_depth" in result.result


def test_batch_larger_than_the_concurrency_limit_is_refused(spawn_tool, enabled):
    result = spawn_tool.execute({"tasks": [{"goal": f"t{i}"} for i in range(enabled.max_concurrent + 1)]})
    assert result.status == "error"
    assert "max_concurrent" in result.result


def test_unknown_type_names_what_is_available(spawn_tool, enabled):
    result = spawn_tool.execute({"goal": "go", "subagent_type": "nope"})
    assert result.status == "error"
    assert "nope" in result.result and "general-purpose" in result.result


def test_missing_goal_is_refused(spawn_tool, enabled):
    assert spawn_tool.execute({}).status == "error"
    assert spawn_tool.execute({"tasks": []}).status == "error"


def test_a_task_that_overruns_its_budget_is_reported_not_dropped(parent, workspace, monkeypatch):
    settings = SubagentSettings(enabled=True, max_depth=1, max_concurrent=2, timeout_seconds=0.2)
    started = threading.Event()

    class _Hanging:
        def __init__(self, **kwargs):
            self.extra_system_suffix = None

        def run_stream(self, goal, clear_history=False, cancel_event=None, on_event=None):
            started.set()
            # Honour the cancel the runner sets on timeout, as a real run would.
            cancel_event.wait(timeout=5)
            return ""

    monkeypatch.setattr("agent.protocol.agent.Agent", _Hanging)

    results = run_tasks(parent, [SubagentTask(goal="hang")], load_templates(str(workspace)), settings)

    assert started.is_set()
    assert len(results) == 1
    assert results[0]["status"] == "timeout"
    assert "timeout_seconds" in results[0]["error"]


def test_a_timed_out_call_returns_without_waiting_for_the_worker(parent, workspace, monkeypatch):
    """Joining the abandoned thread would make the call overrun the very budget
    the timeout exists to enforce."""
    settings = SubagentSettings(enabled=True, max_depth=1, max_concurrent=2, timeout_seconds=0.2)
    release = threading.Event()

    class _Stuck:
        def __init__(self, **kwargs):
            self.extra_system_suffix = None

        def run_stream(self, goal, clear_history=False, cancel_event=None, on_event=None):
            release.wait(timeout=10)  # ignores the cancel, as a wedged run would
            return ""

    monkeypatch.setattr("agent.protocol.agent.Agent", _Stuck)

    started = time.time()
    results = run_tasks(parent, [SubagentTask(goal="stuck")], load_templates(str(workspace)), settings)
    elapsed = time.time() - started
    release.set()

    assert results[0]["status"] == "timeout"
    assert elapsed < 5, f"run_tasks blocked for {elapsed:.1f}s waiting on the abandoned worker"


def test_siblings_do_not_share_tool_instances(parent, workspace, enabled, monkeypatch):
    """The agent loop clears cancel_event on a tool after each call. Shared
    instances would let one sibling disarm another's timeout."""
    seen = []

    class _Recording:
        def __init__(self, **kwargs):
            self.tools = kwargs["tools"]
            self.extra_system_suffix = None

        def run_stream(self, goal, clear_history=False, cancel_event=None, on_event=None):
            # Keep the objects alive, not their ids: a freed copy's address can
            # be handed straight back to the next allocation.
            seen.append({t.name: t for t in self.tools})
            return "ok"

    monkeypatch.setattr("agent.protocol.agent.Agent", _Recording)

    run_tasks(
        parent,
        [SubagentTask(goal="a"), SubagentTask(goal="b")],
        load_templates(str(workspace)),
        enabled,
    )

    parent_tools = {t.name: t for t in parent.tools}
    assert len(seen) == 2
    for name in seen[0]:
        assert seen[0][name] is not seen[1][name], f"siblings share the same {name} instance"
        assert seen[0][name] is not parent_tools[name], f"child shares the parent's {name} instance"


def test_a_sub_agent_gets_half_the_parents_step_budget(parent, workspace, enabled, monkeypatch):
    """One self-contained task, started from an empty context, should not be
    allowed to run as long as the whole conversation that delegated it."""
    seen = []

    class _Recording:
        def __init__(self, **kwargs):
            seen.append(kwargs["max_steps"])
            self.extra_system_suffix = None

        def run_stream(self, goal, clear_history=False, cancel_event=None, on_event=None):
            return "ok"

    monkeypatch.setattr("agent.protocol.agent.Agent", _Recording)
    templates = load_templates(str(workspace))

    parent.max_steps = 40
    run_tasks(parent, [SubagentTask(goal="a")], templates, enabled)
    # A budget too small to halve still has to leave room for one step.
    parent.max_steps = 1
    run_tasks(parent, [SubagentTask(goal="b")], templates, enabled)

    assert seen == [20, 1]


def test_a_failing_task_is_reported_as_failed(parent, workspace, enabled, monkeypatch):
    class _Exploding:
        def __init__(self, **kwargs):
            self.extra_system_suffix = None

        def run_stream(self, goal, clear_history=False, cancel_event=None, on_event=None):
            raise RuntimeError("model unavailable")

    monkeypatch.setattr("agent.protocol.agent.Agent", _Exploding)

    results = run_tasks(parent, [SubagentTask(goal="boom")], load_templates(str(workspace)), enabled)
    assert results[0]["status"] == "failed"
    assert "model unavailable" in results[0]["error"]


def test_all_tasks_failing_surfaces_as_a_tool_error(spawn_tool, enabled, monkeypatch):
    """A parent that reads a success result will report findings to the user.
    There are none, so this must not come back as success."""

    class _Exploding:
        def __init__(self, **kwargs):
            self.extra_system_suffix = None

        def run_stream(self, goal, clear_history=False, cancel_event=None, on_event=None):
            raise RuntimeError("nope")

    monkeypatch.setattr("agent.protocol.agent.Agent", _Exploding)

    result = spawn_tool.execute({"goal": "go"})
    assert result.status == "error"


# --- results and the tool description ----------------------------------------


def test_results_come_back_one_per_task_in_order(spawn_tool, enabled, monkeypatch):
    _capture_children(monkeypatch, reply="the answer")

    result = spawn_tool.execute(
        {"tasks": [{"goal": "first"}, {"goal": "second", "subagent_type": "explore"}]}
    )

    assert result.status == "success"
    results = json.loads(result.result)["results"]
    assert [r["task_index"] for r in results] == [0, 1]
    assert [r["subagent_type"] for r in results] == ["general-purpose", "explore"]
    assert all(r["summary"] == "the answer" for r in results)


def test_description_lists_the_types_the_model_can_pick(spawn_tool, enabled, workspace):
    directory = workspace / "subagents"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "auditor.md").write_text(
        "---\nname: auditor\ndescription: Review changes for defects.\n---\nAudit carefully.\n",
        encoding="utf-8",
    )

    description = spawn_tool.description
    assert "auditor: Review changes for defects." in description
    assert "general-purpose:" in description and "explore:" in description
    # The listing is rebuilt per read, so a template added mid-session shows up.
    (directory / "auditor.md").unlink()
    assert "auditor:" not in spawn_tool.description


def test_description_reaches_the_model_through_get_json_schema(spawn_tool, enabled):
    """The agent loop reads `.description`; other callers read the schema.
    They must not disagree."""
    assert spawn_tool.get_json_schema()["description"] == spawn_tool.description


# --- what the client is told while they run ----------------------------------


def _events_from(tool):
    events = []
    tool.event_callback = lambda event_type, data: events.append((event_type, data))
    return events


def test_each_sub_agent_is_announced_separately(spawn_tool, enabled, monkeypatch):
    """Several sub agents arrive as one tool call, so without this the client
    has one spinner standing in for all of them."""
    _capture_children(monkeypatch, reply="found it")
    events = _events_from(spawn_tool)

    spawn_tool.execute({"tasks": [{"goal": "first"}, {"goal": "second", "subagent_type": "explore"}]})

    starts = [d for kind, d in events if kind == "tool_execution_start"]
    ends = [d for kind, d in events if kind == "tool_execution_end"]
    assert len(starts) == 2 and len(ends) == 2
    assert {d["arguments"]["goal"] for d in starts} == {"first", "second"}
    assert {d["tool_name"] for d in starts} == {"subagent:general-purpose", "subagent:explore"}
    # Every announced unit is one the client can follow and close on its own.
    assert len({d["tool_call_id"] for d in starts}) == 2
    assert {d["tool_call_id"] for d in starts} == {d["tool_call_id"] for d in ends}
    assert [d["status"] for d in ends] == ["success", "success"]
    assert {d["result"] for d in ends} == {"found it"}


def test_a_lone_sub_agent_is_left_to_the_call_itself(spawn_tool, enabled, monkeypatch):
    """One sub agent is already one tool call; announcing it again would just
    show the same work twice."""
    _capture_children(monkeypatch)
    events = _events_from(spawn_tool)

    spawn_tool.execute({"goal": "just the one"})

    assert [kind for kind, _ in events if kind.startswith("tool_execution")] == []


def test_a_failed_sub_agent_closes_with_its_error(spawn_tool, enabled, monkeypatch):
    class _Exploding:
        def __init__(self, **kwargs):
            self.extra_system_suffix = None

        def run_stream(self, goal, clear_history=False, cancel_event=None, on_event=None):
            raise RuntimeError("model unavailable")

    monkeypatch.setattr("agent.protocol.agent.Agent", _Exploding)
    events = _events_from(spawn_tool)

    spawn_tool.execute({"tasks": [{"goal": "a"}, {"goal": "b"}]})

    ends = [d for kind, d in events if kind == "tool_execution_end"]
    assert [d["status"] for d in ends] == ["error", "error"]
    assert all("model unavailable" in d["result"] for d in ends)


def test_a_sub_agent_that_overruns_its_budget_is_still_closed(spawn_tool, workspace, monkeypatch):
    """The worker is abandoned mid-run and never reports back itself. Left
    alone, its entry would sit there spinning for the rest of the session."""
    settings = SubagentSettings(enabled=True, max_depth=1, max_concurrent=2, timeout_seconds=0.2)
    monkeypatch.setattr(SubagentSettings, "from_config", classmethod(lambda cls: settings))

    class _Stuck:
        def __init__(self, **kwargs):
            self.extra_system_suffix = None

        def run_stream(self, goal, clear_history=False, cancel_event=None, on_event=None):
            cancel_event.wait(timeout=5)
            return ""

    monkeypatch.setattr("agent.protocol.agent.Agent", _Stuck)
    events = _events_from(spawn_tool)

    spawn_tool.execute({"tasks": [{"goal": "hang"}, {"goal": "hang too"}]})

    starts = [d for kind, d in events if kind == "tool_execution_start"]
    ends = [d for kind, d in events if kind == "tool_execution_end"]
    assert len(ends) == len(starts) == 2
    assert all(d["status"] == "error" for d in ends)
    assert all("timeout_seconds" in d["result"] for d in ends)
    # The abandoned worker settles later and reports again; the entry has
    # already been closed with the reason that actually explains it.
    time.sleep(0.5)
    assert len([d for kind, d in events if kind == "tool_execution_end"]) == 2


# --- what the client is told about the work inside them ----------------------


def _child_emitting(monkeypatch, events_by_goal, reply="done"):
    """Replace the child Agent with one that reports the given stream events."""

    class _Emitter:
        def __init__(self, **kwargs):
            self.extra_system_suffix = None

        def run_stream(self, goal, clear_history=False, cancel_event=None, on_event=None):
            for event in events_by_goal.get(goal, []):
                if on_event:
                    on_event(event)
            return reply

    monkeypatch.setattr("agent.protocol.agent.Agent", _Emitter)


def _step(tool_call_id, tool_name, phase, **extra):
    data = {"tool_call_id": tool_call_id, "tool_name": tool_name, **extra}
    return {"type": f"tool_execution_{phase}", "data": data}


def test_a_file_a_sub_agent_wrote_reaches_the_user(spawn_tool, enabled, monkeypatch):
    """The report is the thing the spawn was for. Produced a level down, it is
    still the file the user asked for."""
    artifact = {"path": "/ws/report.md", "rel_path": "report.md", "kind": "markdown"}
    _child_emitting(monkeypatch, {"write it up": [{"type": "artifact", "data": artifact}]})
    events = _events_from(spawn_tool)

    spawn_tool.execute({"goal": "write it up"})

    assert [d for kind, d in events if kind == "artifact"] == [artifact]


def test_the_work_inside_a_lone_sub_agent_lands_on_the_spawn_card(spawn_tool, enabled, monkeypatch):
    _child_emitting(monkeypatch, {"look it up": [
        _step("c1", "web_search", "start", arguments={"query": "x"}),
        _step("c1", "web_search", "end", status="success", result={"total": 3}, execution_time=0.94),
    ]})
    events = _events_from(spawn_tool)
    spawn_tool.tool_call_id = "spawn-call"

    spawn_tool.execute({"goal": "look it up"})

    steps = [d for kind, d in events if kind == "subagent_step"]
    assert [d["phase"] for d in steps] == ["start", "end"]
    assert {d["card_id"] for d in steps} == {"spawn-call"}
    assert len({d["step_id"] for d in steps}) == 1
    assert steps[0]["tool_name"] == "web_search"
    assert steps[0]["arguments"] == {"query": "x"}
    assert steps[1]["execution_time"] == 0.94


def test_what_a_step_found_is_left_to_the_report(spawn_tool, enabled, monkeypatch):
    """Its findings are already in the sub agent's summary. Repeating them per
    step puts the same text through the stream twice, in the one place too
    small to read it."""
    _child_emitting(monkeypatch, {"look it up": [
        _step("c1", "web_search", "end", status="success", result={"results": ["…"] * 10}),
    ]})
    events = _events_from(spawn_tool)

    spawn_tool.execute({"goal": "look it up"})

    step = [d for kind, d in events if kind == "subagent_step"][0]
    assert "error" not in step and "result" not in step


def test_a_step_that_failed_carries_the_reason(spawn_tool, enabled, monkeypatch):
    """Nothing else says why that step came up empty."""
    _child_emitting(monkeypatch, {"look it up": [
        _step("c1", "web_fetch", "end", status="error", result="HTTP 403 for URL: https://x"),
    ]})
    events = _events_from(spawn_tool)

    spawn_tool.execute({"goal": "look it up"})

    step = [d for kind, d in events if kind == "subagent_step"][0]
    assert step["status"] == "error"
    assert step["error"] == "HTTP 403 for URL: https://x"


def test_steps_are_attributed_to_the_sub_agent_that_ran_them(spawn_tool, enabled, monkeypatch):
    """Two sub agents run at once and their events interleave. A step shown
    under the wrong one is worse than not showing it."""
    _child_emitting(monkeypatch, {
        "first": [_step("shared-id", "read", "start", arguments={})],
        "second": [_step("shared-id", "bash", "start", arguments={})],
    })
    events = _events_from(spawn_tool)

    spawn_tool.execute({"tasks": [{"goal": "first"}, {"goal": "second"}]})

    cards = {d["tool_call_id"] for kind, d in events if kind == "tool_execution_start"}
    steps = [d for kind, d in events if kind == "subagent_step"]
    assert len(steps) == 2
    assert {d["card_id"] for d in steps} == cards
    # Sub agents number their calls independently, so the same id from two of
    # them must not collapse into one step.
    assert len({d["step_id"] for d in steps}) == 2


def test_the_files_a_sub_agent_wrote_are_listed_in_its_result(spawn_tool, enabled, monkeypatch):
    """A sub agent names its files in prose, if at all. The parent should not
    have to parse them back out, and once the run's events are gone this is
    the only record that they exist."""
    _child_emitting(monkeypatch, {
        "first": [{"type": "artifact", "data": {"path": "/ws/a.md"}},
                  {"type": "artifact", "data": {"path": "/ws/b.md"}}],
        "second": [{"type": "artifact", "data": {"path": "/ws/c.md"}}],
    })

    result = spawn_tool.execute({"tasks": [{"goal": "first"}, {"goal": "second"}]})

    by_index = {r["task_index"]: r.get("files") for r in json.loads(result.result)["results"]}
    assert by_index == {0: ["/ws/a.md", "/ws/b.md"], 1: ["/ws/c.md"]}


def test_a_sub_agent_that_wrote_nothing_lists_nothing(spawn_tool, enabled, monkeypatch):
    _capture_children(monkeypatch)

    result = spawn_tool.execute({"goal": "go"})

    assert "files" not in json.loads(result.result)["results"][0]


def test_a_sub_agents_prose_never_reaches_the_reply(spawn_tool, enabled, monkeypatch):
    """Message and reasoning streams render as the assistant speaking. A sub
    agent talking to itself there reads as the assistant losing the thread."""
    _child_emitting(monkeypatch, {"go": [
        {"type": "message_update", "data": {"delta": "thinking out loud"}},
        {"type": "reasoning_update", "data": {"delta": "hmm"}},
        {"type": "turn_start", "data": {"turn": 2}},
    ]})
    events = _events_from(spawn_tool)

    spawn_tool.execute({"goal": "go"})

    assert events == []


def test_a_broken_watcher_does_not_take_the_sub_agent_down(spawn_tool, enabled, monkeypatch):
    _child_emitting(monkeypatch, {"go": [{"type": "artifact", "data": {"path": "/ws/a.md"}}]})

    def _broken(event_type, data):
        raise RuntimeError("client went away")

    spawn_tool.event_callback = _broken

    result = spawn_tool.execute({"goal": "go"})
    assert result.status == "success"


# --- the conclusion, written for a person ------------------------------------


def test_the_conclusion_is_offered_as_markdown(spawn_tool, enabled, monkeypatch):
    """The JSON is what the parent model parses. Nobody who waited minutes for
    a report wants to read a JSON blob."""
    _capture_children(monkeypatch, reply="Found three things.")

    result = spawn_tool.execute({"goal": "go"})

    assert result.display.startswith("### general-purpose")
    assert "Found three things." in result.display
    # The model still gets the machine-readable form.
    assert json.loads(result.result)["results"][0]["summary"] == "Found three things."


def test_several_conclusions_are_numbered_and_separated(spawn_tool, enabled, monkeypatch):
    _capture_children(monkeypatch, reply="the answer")

    result = spawn_tool.execute({"tasks": [{"goal": "a"}, {"goal": "b", "subagent_type": "explore"}]})

    assert "### 1. general-purpose" in result.display
    assert "### 2. explore" in result.display
    assert result.display.count("the answer") == 2


def test_a_conclusion_that_never_arrived_says_so(spawn_tool, enabled, monkeypatch):
    class _Exploding:
        def __init__(self, **kwargs):
            self.extra_system_suffix = None

        def run_stream(self, goal, clear_history=False, cancel_event=None, on_event=None):
            raise RuntimeError("model unavailable")

    monkeypatch.setattr("agent.protocol.agent.Agent", _Exploding)

    result = spawn_tool.execute({"goal": "go"})

    assert result.status == "error"
    assert "**failed**" in result.display
    assert "model unavailable" in result.display


def test_reporting_trouble_does_not_take_the_run_down(spawn_tool, enabled, monkeypatch):
    _capture_children(monkeypatch)

    def _broken(event_type, data):
        raise RuntimeError("client went away")

    spawn_tool.event_callback = _broken

    result = spawn_tool.execute({"tasks": [{"goal": "a"}, {"goal": "b"}]})

    assert result.status == "success"
    assert len(json.loads(result.result)["results"]) == 2
