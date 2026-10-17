"""Rejected reminders must reach the model and tool cards as failed calls."""
import pytest

from agent.protocol.agent_stream import AgentStreamExecutor
from agent.tools.scheduler.recipient_store import RecipientStore
from agent.tools.scheduler.scheduler_tool import SchedulerTool
from agent.tools.scheduler.task_store import TaskStore
from bridge.context import Context, ContextType


@pytest.fixture
def tool(tmp_path):
    scheduler = SchedulerTool({"channel_type": "web"})
    scheduler.task_store = TaskStore(str(tmp_path / "tasks.json"))
    scheduler.recipient_store = RecipientStore(str(tmp_path / "recipients.json"))
    scheduler.current_context = Context(ContextType.TEXT, "reminder")
    scheduler.current_context["channel_type"] = "web"
    scheduler.current_context["receiver"] = "local-fixture"
    scheduler.current_context["session_id"] = "local-fixture"
    return scheduler


def create(**overrides):
    return {"action": "create", "name": "Reminder", "message": "Stand up",
            "schedule_type": "once", "schedule_value": "+5m", **overrides}


@pytest.mark.parametrize("params", [
    create(name=""), create(message=""), create(ai_task="also run a task"),
    create(schedule_type=""), create(schedule_value=""),
    create(schedule_type="cron", schedule_value="invalid cron"),
    create(schedule_value="2000-01-01 00:00:00"),
    create(channel_type="weixin"),
    create(channel_type="weixin", receiver="unknown"),
    *[{"action": action, "task_id": task_id}
      for action in ("get", "delete", "enable", "disable")
      for task_id in ("", "does-not-exist")],
])
def test_rejected_operations_report_failure_without_mutating_store(tool, params):
    result = tool.execute(params)
    assert result.status == "error", result.result
    assert isinstance(result.result, str)
    assert tool.task_store.load_tasks() == {}


def test_missing_conversation_and_recipient_directory_report_failure(tool):
    tool.current_context = None
    assert tool.execute(create()).status == "error"
    assert tool.execute({"action": "list_recipients"}).status == "error"
    tool.current_context = {"channel_type": "web"}
    tool.recipient_store = None
    assert tool.execute({"action": "list_recipients"}).status == "error"
    assert tool.execute(create(channel_type="weixin", receiver="unknown")).status == "error"
    assert tool.task_store.load_tasks() == {}


def test_successful_lifecycle_and_error_like_user_text_remain_successful(tool):
    result = tool.execute(create(name="Error: 错误: ordinary reminder",
                                 message="Error: is the text to remember"))
    assert result.status == "success", result.result
    tasks = tool.task_store.load_tasks()
    assert len(tasks) == 1
    task_id = next(iter(tasks))
    for action in ("get", "list", "disable", "enable", "delete"):
        result = tool.execute({"action": action, "task_id": task_id})
        assert result.status == "success", (action, result.result)
    assert tool.task_store.load_tasks() == {}
    assert tool.execute({"action": "list_recipients"}).status == "success"


def test_rejected_operation_reaches_executor_card_and_retry_history(tool):
    events = []
    executor = AgentStreamExecutor(agent=None, model=None, system_prompt="",
                                   tools=[tool], on_event=events.append)
    result = executor._execute_tool({"id": "missing", "name": "scheduler",
                                     "arguments": {"action": "disable", "task_id": "gone"}})
    assert result["status"] == "error", result
    assert "gone" in result["result"]
    assert executor.tool_failure_history[-1][2] is False
    end = [event["data"] for event in events if event["type"] == "tool_execution_end"]
    assert len(end) == 1
    assert end[0]["status"] == "error"
    assert "gone" in end[0]["result"]
