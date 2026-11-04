# encoding:utf-8
"""Following a task up: queue order, restarts, quoted replies and task links."""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from agent.task import store as st
from agent.task.commands import own_text, quoted_approval, try_handle


@pytest.fixture
def store(tmp_path):
    instance = st.TaskStore(str(tmp_path / "tasks.db"))
    with patch.object(st, "_store", instance):
        yield instance


def _on():
    return patch("config.conf", return_value={"task": {"enabled": True, "approval_rules": []}})


_FEISHU = {"channel_type": "feishu", "receiver": "u1"}


# --- queue order and restarts -----------------------------------------------------

def test_follow_ups_claim_before_new_tasks(store):
    fresh = store.create_task("new", "p")
    followed = store.create_task("old", "p")
    store.update_task(followed["id"], run_count=1)
    assert [t["id"] for t in store.claim_next(1)] == [followed["id"]]
    assert [t["id"] for t in store.claim_next(1)] == [fresh["id"]]


def test_restart_requeues_with_a_recovery_note(store):
    from agent.task import runner as runner_mod

    first = store.create_task("first", "write the report")
    later = store.create_task("later", "p")
    store.claim_next(2)
    store.update_task(later["id"], run_count=3)
    with patch.object(runner_mod.threading, "Thread", MagicMock()):
        runner_mod.TaskRunner().start()

    first, later = store.get_task(first["id"]), store.get_task(later["id"])
    assert first["status"] == later["status"] == st.QUEUED
    note = runner_mod._recovery_note(later)
    assert later["pending_input"] == note
    # A first round may have stored nothing yet, so its brief comes again.
    assert first["pending_input"].endswith(note) and "write the report" in first["pending_input"]
    assert first["pending_display"].startswith("↻")


# --- quote replies ------------------------------------------------------------------

def test_quoted_approval_cards_are_recognized():
    assert quoted_approval("【待审批 #3】任务 #12「周报」要执行：推送代码") == 3
    assert quoted_approval("[Review #4] Task #12 \"report\" is done") == 4
    assert quoted_approval("bot | 【待验收 #5】任务 #12「周报」已完成") == 5
    assert quoted_approval("【任务 #12 已完成】周报") is None
    assert quoted_approval("今天天气不错，待审批 #12 呢") is None


def test_own_text_drops_the_quote_block():
    quoted = "【任务 #12 已完成】周报"
    assert own_text(f"[引用: {quoted}]\n加个图表", quoted) == "加个图表"
    assert own_text(f"[Quoted message]\n{quoted}\n[/Quoted message]\n\n加个图表", quoted) == "加个图表"
    assert own_text("加个图表", "") == "加个图表"


def test_quoting_a_task_notice_goes_to_the_agent(store):
    task = store.create_task("周报", "p", source=st.SOURCE_CHAT, origin=dict(_FEISHU))
    store.update_task(task["id"], status=st.DONE, result="r")
    quoted = f"【任务 #{task['id']} 已完成】周报\n\nr"
    text = f"[Quoted message]\n{quoted}\n[/Quoted message]\n\n加个图表"
    with _on(), patch("agent.task.runner.reply_to_task") as reply:
        assert try_handle(text, "feishu", "u1", quoted=quoted) is None
        assert try_handle(f"[引用: {quoted}]\n这个结果什么意思", "feishu", "u1", quoted=quoted) is None
        reply.assert_not_called()


def test_quoting_an_approval_card_names_the_approval(store):
    first = store.create_approval(st.KIND_ACTION, session_id="s", tool_name="bash",
                                  tool_args={"command": "a"}, origin=dict(_FEISHU))
    second = store.create_approval(st.KIND_ACTION, session_id="s", tool_name="bash",
                                   tool_args={"command": "b"}, origin=dict(_FEISHU))
    quoted = f"【待审批 #{second['id']}】需要执行：bash"
    with _on(), patch("agent.task.approval.decide") as decide:
        assert try_handle(f"[引用: {quoted}]\n通过", "weixin", "u1", quoted=quoted) is None
        assert try_handle(f"[引用: {quoted}]\n通过", "feishu", "u1", quoted=quoted)
        decide.assert_called_once()
        assert decide.call_args.args[0] == second["id"]
        # Free text under an approval card is not a decision; the agent reads it.
        assert try_handle(f"[引用: {quoted}]\n这是什么命令", "feishu", "u1", quoted=quoted) is None
    assert first["id"] != second["id"]


def test_rejecting_a_quoted_review_card_is_rework(store):
    task = store.create_task("周报", "p", origin=dict(_FEISHU), require_accept=True)
    store.update_task(task["id"], status=st.WAITING, wait_type=st.WAIT_ACCEPT)
    review = store.create_approval(st.KIND_ACCEPT, task_id=task["id"], session_id=task["session_id"],
                                   origin=dict(_FEISHU))
    quoted = f"【待验收 #{review['id']}】任务 #{task['id']}「周报」已完成"
    with _on(), patch("agent.task.approval.decide") as decide:
        assert try_handle(f"[引用: {quoted}]\n驳回 第二段再短点", "feishu", "u1", quoted=quoted)
        decide.assert_called_once_with(review["id"], "reject", note="第二段再短点", via="feishu")
        # Feedback without "reject" is for the agent, which knows the task from the card.
        assert try_handle(f"[引用: {quoted}]\n第二段再短点", "feishu", "u1", quoted=quoted) is None


def test_quote_hint_only_where_quotes_reach_the_task():
    from agent.task.notify import can_quote_reply, done_text

    chat = {"id": 1, "title": "t", "source": st.SOURCE_CHAT, "origin": {"channel_type": "weixin"}}
    assert can_quote_reply(chat)
    assert not can_quote_reply({**chat, "origin": {"channel_type": "dingtalk"}})
    assert not can_quote_reply({**chat, "source": st.SOURCE_SCHEDULE})
    assert done_text(chat, "r", quote_hint=True) != done_text(chat, "r")


def test_feishu_card_quote_reads_its_markdown():
    from channel.feishu.feishu_message import FeishuMessage
    from channel.feishu.feishu_static_card import build_markdown_card

    card = build_markdown_card("【任务 #5 已完成】周报\n\n**要点**")
    item = {"msg_type": "interactive", "body": {"content": json.dumps(card, ensure_ascii=False)}}
    assert FeishuMessage._extract_quoted_text(item).startswith("【任务 #5 已完成】")
    assert FeishuMessage._extract_quoted_text({"msg_type": "interactive", "body": {"content": "{}"}}) == ""


def test_weixin_keeps_the_quote_apart():
    from channel.weixin.weixin_message import ITEM_TEXT, WeixinMessage

    msg = WeixinMessage({"from_user_id": "u1", "item_list": [{
        "type": ITEM_TEXT, "text_item": {"text": "加个图表"},
        "ref_msg": {"message_item": {"type": ITEM_TEXT, "text_item": {"text": "【任务 #7 已完成】周报"}}},
    }]})
    assert msg.quoted_content == "【任务 #7 已完成】周报"
    assert own_text(msg.content, msg.quoted_content) == "加个图表"


# --- links --------------------------------------------------------------------------

def test_task_create_links_the_new_task(store):
    from agent.tools.task.task import TaskTool

    tool = TaskTool()
    tool.context = SimpleNamespace(_current_context=None, messages=[], messages_lock=MagicMock(),
                                   _current_agent_id="")
    with _on(), patch("agent.task.runner.wake_runner"):
        result = tool.execute({"action": "create", "title": "周报", "prompt": "整理本周周报"})
    task_id = store.list_tasks()[0]["id"]
    assert f"(#task-{task_id})" in result.display
    assert f"#{task_id}" in result.result


def test_web_results_link_the_task_heading():
    from agent.task.notify import done_heading

    assert "(#task-3)" in done_heading(3, "t", link=True)
    assert "#task-" not in done_heading(3, "t")
