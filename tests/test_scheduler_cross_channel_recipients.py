import json

from agent.tools.scheduler.recipient_store import RecipientStore
from agent.tools.scheduler.scheduler_tool import SchedulerTool
from bridge.context import Context, ContextType


class _TaskStore:
    def __init__(self):
        self.tasks = []

    def add_task(self, task):
        self.tasks.append(task)


def _context(channel_type, receiver):
    context = Context(ContextType.TEXT, "hello")
    context["channel_type"] = channel_type
    context["receiver"] = receiver
    context["session_id"] = receiver
    context["isgroup"] = False
    return context


def _create(tool, **overrides):
    values = {
        "name": "Reminder",
        "message": "Stand up",
        "schedule_type": "once",
        "schedule_value": "+5m",
    }
    values.update(overrides)
    return tool._create_task(**values)


def test_recipient_store_persists_only_delivery_identity(tmp_path):
    path = tmp_path / "recipients.json"
    store = RecipientStore(str(path))
    store.remember(
        "wecom_bot",
        "user-42",
        name="Ada",
        session_id="session-42",
    )

    reloaded = RecipientStore(str(path)).get("wecom_bot", "user-42")
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert reloaded["name"] == "Ada"
    assert reloaded["session_id"] == "session-42"
    assert "token" not in json.dumps(payload).lower()


def test_recipient_store_avoids_rewriting_an_unchanged_recent_entry(tmp_path):
    path = tmp_path / "recipients.json"
    store = RecipientStore(str(path))
    store.remember("wecom_bot", "user-42", name="Ada")
    original_mtime = path.stat().st_mtime_ns

    store.remember("wecom_bot", "user-42", name="Ada")

    assert path.stat().st_mtime_ns == original_mtime


def test_web_can_create_message_for_trusted_cross_channel_recipient(tmp_path):
    recipients = RecipientStore(str(tmp_path / "recipients.json"))
    recipients.remember("wecom_bot", "user-42", name="Ada")
    tasks = _TaskStore()
    tool = SchedulerTool({"channel_type": "web"})
    tool.current_context = _context("web", "web-session")
    tool.recipient_store = recipients
    tool.task_store = tasks

    result = _create(tool, channel_type="wecom_bot", receiver="user-42")

    assert "Error:" not in result
    assert tasks.tasks[0]["action"]["channel_type"] == "wecom_bot"
    assert tasks.tasks[0]["action"]["receiver"] == "user-42"
    assert tasks.tasks[0]["action"]["receiver_name"] == "Ada"


def test_cross_channel_target_must_be_trusted_and_selected_from_web(tmp_path):
    recipients = RecipientStore(str(tmp_path / "recipients.json"))
    tasks = _TaskStore()
    tool = SchedulerTool({"channel_type": "web"})
    tool.recipient_store = recipients
    tool.task_store = tasks

    tool.current_context = _context("web", "web-session")
    assert "not in the trusted recipient directory" in _create(
        tool, channel_type="wecom_bot", receiver="unknown"
    )

    recipients.remember("wecom_bot", "user-42")
    tool.current_context = _context("feishu", "feishu-user")
    assert "only be selected from the Web console" in _create(
        tool, channel_type="wecom_bot", receiver="user-42"
    )
    assert tasks.tasks == []


def test_cross_channel_phase_is_fixed_messages_only(tmp_path):
    recipients = RecipientStore(str(tmp_path / "recipients.json"))
    recipients.remember("wecom_bot", "user-42")
    tool = SchedulerTool({"channel_type": "web"})
    tool.current_context = _context("web", "web-session")
    tool.recipient_store = recipients
    tool.task_store = _TaskStore()

    result = _create(
        tool,
        message=None,
        ai_task="Prepare a report",
        channel_type="wecom_bot",
        receiver="user-42",
    )

    assert "fixed messages only" in result
