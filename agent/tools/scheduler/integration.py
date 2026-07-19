"""
Integration module for scheduler with AgentBridge
"""

import os
import threading
from typing import Dict, Optional
from config import conf
from common.log import logger
from common.utils import expand_path
from bridge.context import Context, ContextType
from bridge.reply import Reply, ReplyType

# Backward-compatible aliases for the configured default agent.
_scheduler_service = None
_task_store = None
_scheduler_services: Dict[str, object] = {}
_task_stores: Dict[str, object] = {}
# Module-level lock to guard idempotent initialization across threads
_init_lock = threading.RLock()


def _resolve_workspace(workspace_root: str = None, agent_id: str = None):
    if workspace_root is not None:
        return os.path.realpath(expand_path(str(workspace_root)))
    try:
        from agent.registry import get_agent_registry
        return get_agent_registry().get(agent_id).workspace
    except Exception:
        return os.path.realpath(expand_path(conf().get("agent_workspace", "~/cow")))


def init_scheduler(agent_bridge, workspace_root: str = None, agent_id: str = None) -> bool:
    """
    Initialize scheduler service (idempotent).

    Safe to call multiple times and from multiple threads: only the first
    successful call creates the singleton ``SchedulerService`` + background
    scanning thread. Subsequent calls return immediately.

    Args:
        agent_bridge: AgentBridge instance

    Returns:
        True if scheduler is initialized (newly created or already running)
    """
    global _scheduler_service, _task_store
    workspace_root = _resolve_workspace(workspace_root, agent_id)
    agent_id = agent_bridge.agent_registry.get(agent_id).id

    # Fast path: already initialized and running
    service = _scheduler_services.get(workspace_root)
    if service is not None and getattr(service, "running", False):
        return True

    with _init_lock:
        # Re-check under the lock to avoid races where multiple threads
        # passed the fast-path check before any of them acquired the lock.
        service = _scheduler_services.get(workspace_root)
        if service is not None and getattr(service, "running", False):
            return True

        try:
            from agent.tools.scheduler.task_store import TaskStore
            from agent.tools.scheduler.scheduler_service import SchedulerService

            store_path = os.path.join(workspace_root, "scheduler", "tasks.json")

            # Create task store (reuse if already created)
            task_store = _task_stores.get(workspace_root)
            if task_store is None:
                task_store = TaskStore(store_path)
                _task_stores[workspace_root] = task_store
                logger.debug(f"[Scheduler] Task store initialized: {store_path}")

            # Create execute callback. Returns True on success, False to ask
            # the scheduler to retry on the next tick (e.g. channel not yet
            # ready right after process start).
            def execute_task_callback(task: dict):
                try:
                    action = task.get("action", {})
                    action_type = action.get("type")
                    channel_type = action.get("channel_type", "unknown")
                    receiver = action.get("receiver", "")

                    if not _is_channel_ready(channel_type, receiver, agent_id):
                        logger.warning(
                            f"[Scheduler] Task {task.get('id')}: channel "
                            f"'{channel_type}' not ready for receiver={receiver} "
                            f"(no inbound msg cached since restart?); deferring"
                        )
                        return False

                    if action_type == "agent_task":
                        return _execute_agent_task(task, agent_bridge, agent_id)
                    elif action_type == "send_message":
                        return _execute_send_message(task, agent_bridge, agent_id)
                    elif action_type == "tool_call":
                        return _execute_tool_call(task, agent_bridge, agent_id)
                    elif action_type == "skill_call":
                        return _execute_skill_call(task, agent_bridge, agent_id)
                    else:
                        logger.warning(f"[Scheduler] Unknown action type: {action_type}")
                        return True
                except Exception as e:
                    logger.error(f"[Scheduler] Error executing task {task.get('id')}: {e}")
                    return False

            # Create scheduler service
            service = SchedulerService(task_store, execute_task_callback)
            service.start()
            _scheduler_services[workspace_root] = service
            if agent_id == agent_bridge.agent_registry.default_agent_id:
                _scheduler_service = service
                _task_store = task_store

            logger.info(
                f"[Scheduler] Service initialized for agent={agent_id}, "
                f"workspace={workspace_root}"
            )
            return True

        except Exception as e:
            logger.error(f"[Scheduler] Failed to initialize scheduler: {e}")
            return False


def _is_channel_ready(
    channel_type: str, receiver: str, agent_id: str = None
) -> bool:
    """Best-effort readiness probe for outbound channels.

    Returns False when we know the send will drop (e.g. weixin not yet
    logged in, web session has no polling queue), so the scheduler can
    defer instead of consuming the task. Unknown channels return True
    to preserve previous behaviour.
    """
    if not channel_type or channel_type == "unknown":
        return True
    try:
        from channel.channel_factory import create_channel
        channel = create_channel(channel_type)
        if channel is None:
            return False

        if channel_type == "weixin":
            tokens = getattr(channel, "_context_tokens", None)
            if not tokens or receiver not in tokens:
                return False
            return True

        if channel_type == "web":
            if hasattr(channel, "has_session_queue"):
                return channel.has_session_queue(receiver, agent_id)
            queues = getattr(channel, "session_queues", None)
            if not queues or receiver not in queues:
                return False
            return True

        return True
    except Exception as e:
        logger.warning(f"[Scheduler] Channel readiness check failed for {channel_type}: {e}")
        return True


def get_task_store(workspace_root: str = None, agent_id: str = None):
    """Get the task store owned by one agent workspace."""
    workspace_root = _resolve_workspace(workspace_root, agent_id)
    return _task_stores.get(workspace_root)


def get_scheduler_service(workspace_root: str = None, agent_id: str = None):
    """Get the scheduler service owned by one agent workspace."""
    workspace_root = _resolve_workspace(workspace_root, agent_id)
    return _scheduler_services.get(workspace_root)


def reset_scheduler_services(stop: bool = True) -> None:
    """Stop and forget all scheduler services, primarily for reloads/tests."""
    global _scheduler_service, _task_store
    with _init_lock:
        if stop:
            for service in list(_scheduler_services.values()):
                try:
                    service.stop()
                except Exception:
                    pass
        _scheduler_services.clear()
        _task_stores.clear()
        _scheduler_service = None
        _task_store = None


def _remember_delivered_output(
    agent_bridge,
    task: dict,
    channel_type: str,
    content: str,
    agent_id: str = None,
) -> None:
    """Best-effort persistence of the message the scheduler sent to a user.

    Uses notify_session_id (the real chat session_id stored at task creation time)
    so that group chats correctly associate the output with the user's conversation.
    Falls back to receiver for backward compatibility with old tasks.

    Per-action-type behaviour:
        - agent_task / tool_call / skill_call: gated by ``scheduler_inject_to_session``
          (default True). These produce AI-generated content worth remembering.
        - send_message: additionally gated by ``scheduler_inject_send_message``
          (default False). Fixed reminder text rarely benefits follow-up Q&A and
          would just consume context tokens.
    """
    if not content:
        return
    action = task.get("action", {})
    action_type = action.get("type", "")

    # send_message defaults to NOT being injected; explicit opt-in via config.
    if action_type == "send_message":
        if not conf().get("scheduler_inject_send_message", False):
            return

    session_id = action.get("notify_session_id") or action.get("receiver")
    if not session_id:
        return
    try:
        remember = getattr(agent_bridge, "remember_scheduled_output", None)
        if remember:
            task_desc = action.get("task_description") or action.get("content", "")
            kwargs = {
                "channel_type": channel_type,
                "task_description": task_desc,
            }
            if hasattr(agent_bridge, "agent_registry"):
                kwargs["agent_id"] = agent_id
            remember(session_id, str(content), **kwargs)
    except Exception as e:
        logger.warning(
            f"[Scheduler] Failed to remember delivered output for {session_id}: {e}"
        )


def _execute_agent_task(task: dict, agent_bridge, agent_id: str = None) -> bool:
    """
    Execute an agent_task action - let Agent handle the task.
    Returns True on successful delivery, False to retry next tick.
    """
    try:
        action = task.get("action", {})
        task_description = action.get("task_description")
        receiver = action.get("receiver")
        is_group = action.get("is_group", False)
        channel_type = action.get("channel_type", "unknown")
        
        if not task_description:
            logger.error(f"[Scheduler] Task {task['id']}: No task_description specified")
            return True  # malformed task, don't loop forever
        
        if not receiver:
            logger.error(f"[Scheduler] Task {task['id']}: No receiver specified")
            return True
        
        # Check for unsupported channels
        if channel_type == "dingtalk":
            logger.warning(f"[Scheduler] Task {task['id']}: DingTalk channel does not support scheduled messages (Stream mode limitation). Task will execute but message cannot be sent.")
        
        logger.info(f"[Scheduler] Task {task['id']}: Executing agent task '{task_description}'")
        
        # Create a unique session_id for this scheduled task to avoid polluting user's conversation
        # Format: scheduler_<receiver>_<task_id> to ensure isolation
        scheduler_session_id = f"scheduler_{receiver}_{task['id']}"
        
        # Create context for Agent
        context = Context(ContextType.TEXT, task_description)
        context["receiver"] = receiver
        context["isgroup"] = is_group
        context["session_id"] = scheduler_session_id
        context["agent_id"] = agent_id
        
        # Channel-specific setup
        if channel_type == "web":
            import uuid
            request_id = f"scheduler_{task['id']}_{uuid.uuid4().hex[:8]}"
            context["request_id"] = request_id
        elif channel_type == "feishu":
            context["receive_id_type"] = "chat_id" if is_group else "open_id"
            context["msg"] = None
        elif channel_type == "dingtalk":
            # DingTalk requires msg object, set to None for scheduled tasks
            context["msg"] = None
            if not is_group:
                sender_staff_id = action.get("dingtalk_sender_staff_id")
                if sender_staff_id:
                    context["dingtalk_sender_staff_id"] = sender_staff_id
        elif channel_type == "wecom_bot":
            context["msg"] = None

        # Use Agent to execute the task
        # Mark this as a scheduled task execution to prevent recursive task creation
        context["is_scheduled_task"] = True
        
        try:
            # Don't clear history - scheduler tasks use isolated session_id so they won't pollute user conversations
            reply = agent_bridge.agent_reply(task_description, context=context, on_event=None, clear_history=False)

            if not (reply and reply.content):
                logger.error(f"[Scheduler] Task {task['id']}: No result from agent execution")
                return True  # agent ran but produced nothing; don't loop

            if action.get("silent", False):
                logger.info(
                    f"[Scheduler] Task {task['id']} executed successfully in silent mode"
                )
                return True

            from channel.channel_factory import create_channel
            channel = create_channel(channel_type)
            if not channel:
                logger.error(f"[Scheduler] Failed to create channel: {channel_type}")
                return False

            if channel_type == "web" and hasattr(channel, 'request_to_session'):
                request_id = context.get("request_id")
                if request_id:
                    channel.request_to_session[request_id] = receiver

            try:
                channel.send(reply, context)
            except Exception as e:
                logger.error(f"[Scheduler] Failed to send result: {e}")
                return False

            _remember_delivered_output(
                agent_bridge, task, channel_type, reply.content, agent_id
            )
            logger.info(f"[Scheduler] Task {task['id']} executed successfully, result sent to {receiver}")
            return True

        except Exception as e:
            logger.error(f"[Scheduler] Failed to execute task via Agent: {e}")
            import traceback
            logger.error(f"[Scheduler] Traceback: {traceback.format_exc()}")
            return False

    except Exception as e:
        logger.error(f"[Scheduler] Error in _execute_agent_task: {e}")
        import traceback
        logger.error(f"[Scheduler] Traceback: {traceback.format_exc()}")
        return False


def _execute_send_message(task: dict, agent_bridge, agent_id: str = None) -> bool:
    """Execute a send_message action. Returns True/False for delivery."""
    try:
        action = task.get("action", {})
        content = action.get("content", "")
        receiver = action.get("receiver")
        is_group = action.get("is_group", False)
        channel_type = action.get("channel_type", "unknown")
        
        if not receiver:
            logger.error(f"[Scheduler] Task {task['id']}: No receiver specified")
            return True
        
        # Create context for sending message
        context = Context(ContextType.TEXT, content)
        context["receiver"] = receiver
        context["isgroup"] = is_group
        context["session_id"] = receiver
        context["agent_id"] = agent_id
        
        # Channel-specific context setup
        if channel_type == "web":
            # Web channel needs request_id
            import uuid
            request_id = f"scheduler_{task['id']}_{uuid.uuid4().hex[:8]}"
            context["request_id"] = request_id
            logger.debug(f"[Scheduler] Generated request_id for web channel: {request_id}")
        elif channel_type == "feishu":
            # Feishu channel: for scheduled tasks, send as new message (no msg_id to reply to)
            # Use chat_id for groups, open_id for private chats
            context["receive_id_type"] = "chat_id" if is_group else "open_id"
            # Keep isgroup as is, but set msg to None (no original message to reply to)
            # Feishu channel will detect this and send as new message instead of reply
            context["msg"] = None
            logger.debug(f"[Scheduler] Feishu: receive_id_type={context['receive_id_type']}, is_group={is_group}, receiver={receiver}")
        elif channel_type == "dingtalk":
            # DingTalk channel setup
            context["msg"] = None
            # 如果是单聊，需要传递 sender_staff_id
            if not is_group:
                sender_staff_id = action.get("dingtalk_sender_staff_id")
                if sender_staff_id:
                    context["dingtalk_sender_staff_id"] = sender_staff_id
                    logger.debug(f"[Scheduler] DingTalk single chat: sender_staff_id={sender_staff_id}")
                else:
                    logger.warning(f"[Scheduler] Task {task['id']}: DingTalk single chat message missing sender_staff_id")
        elif channel_type == "wecom_bot":
            context["msg"] = None
        elif channel_type == "qq":
            context["msg"] = None

        # Create reply
        reply = Reply(ReplyType.TEXT, content)
        
        # Get channel and send
        from channel.channel_factory import create_channel
        
        channel = create_channel(channel_type)
        if not channel:
            logger.error(f"[Scheduler] Failed to create channel: {channel_type}")
            return False

        if channel_type == "web" and hasattr(channel, 'request_to_session'):
            channel.request_to_session[request_id] = receiver

        try:
            channel.send(reply, context)
        except Exception as e:
            logger.error(f"[Scheduler] Failed to send message: {e}")
            return False

        _remember_delivered_output(
            agent_bridge, task, channel_type, content, agent_id
        )
        logger.info(f"[Scheduler] Task {task['id']} executed: sent message to {receiver}")
        return True

    except Exception as e:
        logger.error(f"[Scheduler] Error in _execute_send_message: {e}")
        import traceback
        logger.error(f"[Scheduler] Traceback: {traceback.format_exc()}")
        return False


def _execute_tool_call(task: dict, agent_bridge, agent_id: str = None) -> bool:
    """Execute a tool_call action. Returns True/False for delivery."""
    try:
        action = task.get("action", {})
        tool_name = action.get("call_name") or action.get("tool_name")
        tool_params = action.get("call_params") or action.get("tool_params", {})
        result_prefix = action.get("result_prefix", "")
        receiver = action.get("receiver")
        is_group = action.get("is_group", False)
        channel_type = action.get("channel_type", "unknown")

        if not tool_name:
            logger.error(f"[Scheduler] Task {task['id']}: No tool_name specified")
            return True
        if not receiver:
            logger.error(f"[Scheduler] Task {task['id']}: No receiver specified")
            return True

        from agent.tools.tool_manager import ToolManager
        tool = ToolManager().create_tool(tool_name)
        if not tool:
            logger.error(f"[Scheduler] Task {task['id']}: Tool '{tool_name}' not found")
            return True

        logger.info(f"[Scheduler] Task {task['id']}: Executing tool '{tool_name}' with params {tool_params}")
        result = tool.execute(tool_params)
        content = result.result if hasattr(result, 'result') else str(result)
        if result_prefix:
            content = f"{result_prefix}\n\n{content}"

        context = Context(ContextType.TEXT, content)
        context["receiver"] = receiver
        context["isgroup"] = is_group
        context["session_id"] = receiver
        context["agent_id"] = agent_id

        request_id = None
        if channel_type == "web":
            import uuid
            request_id = f"scheduler_{task['id']}_{uuid.uuid4().hex[:8]}"
            context["request_id"] = request_id
        elif channel_type == "feishu":
            context["receive_id_type"] = "chat_id" if is_group else "open_id"
            context["msg"] = None
        elif channel_type == "wecom_bot":
            context["msg"] = None

        reply = Reply(ReplyType.TEXT, content)

        from channel.channel_factory import create_channel
        channel = create_channel(channel_type)
        if not channel:
            logger.error(f"[Scheduler] Failed to create channel: {channel_type}")
            return False

        if channel_type == "web" and request_id and hasattr(channel, 'request_to_session'):
            channel.request_to_session[request_id] = receiver

        try:
            channel.send(reply, context)
        except Exception as e:
            logger.error(f"[Scheduler] Failed to send tool result: {e}")
            return False

        _remember_delivered_output(
            agent_bridge, task, channel_type, content, agent_id
        )
        logger.info(f"[Scheduler] Task {task['id']} executed: sent tool result to {receiver}")
        return True

    except Exception as e:
        logger.error(f"[Scheduler] Error in _execute_tool_call: {e}")
        return False


def _execute_skill_call(task: dict, agent_bridge, agent_id: str = None) -> bool:
    """Execute a skill_call action by asking Agent to run the skill.
    Returns True/False for delivery."""
    try:
        action = task.get("action", {})
        skill_name = action.get("call_name") or action.get("skill_name")
        skill_params = action.get("call_params") or action.get("skill_params", {})
        result_prefix = action.get("result_prefix", "")
        receiver = action.get("receiver")
        is_group = action.get("isgroup", False)
        channel_type = action.get("channel_type", "unknown")

        if not skill_name:
            logger.error(f"[Scheduler] Task {task['id']}: No skill_name specified")
            return True
        if not receiver:
            logger.error(f"[Scheduler] Task {task['id']}: No receiver specified")
            return True

        logger.info(f"[Scheduler] Task {task['id']}: Executing skill '{skill_name}' with params {skill_params}")

        scheduler_session_id = f"scheduler_{receiver}_{task['id']}"
        param_str = ", ".join([f"{k}={v}" for k, v in skill_params.items()])
        query = f"Use {skill_name} skill"
        if param_str:
            query += f" with {param_str}"

        context = Context(ContextType.TEXT, query)
        context["receiver"] = receiver
        context["isgroup"] = is_group
        context["session_id"] = scheduler_session_id
        context["agent_id"] = agent_id

        if channel_type == "web":
            import uuid
            request_id = f"scheduler_{task['id']}_{uuid.uuid4().hex[:8]}"
            context["request_id"] = request_id
        elif channel_type == "feishu":
            context["receive_id_type"] = "chat_id" if is_group else "open_id"
            context["msg"] = None
        elif channel_type == "wecom_bot":
            context["msg"] = None

        try:
            reply = agent_bridge.agent_reply(query, context=context, on_event=None, clear_history=False)
        except Exception as e:
            logger.error(f"[Scheduler] Failed to execute skill via Agent: {e}")
            import traceback
            logger.error(f"[Scheduler] Traceback: {traceback.format_exc()}")
            return False

        if not (reply and reply.content):
            logger.error(f"[Scheduler] Task {task['id']}: No result from skill execution")
            return True

        content = reply.content
        if result_prefix:
            content = f"{result_prefix}\n\n{content}"

        from channel.channel_factory import create_channel
        channel = create_channel(channel_type)
        if not channel:
            logger.error(f"[Scheduler] Failed to create channel: {channel_type}")
            return False

        if channel_type == "web" and hasattr(channel, 'request_to_session'):
            req_id = context.get("request_id")
            if req_id:
                channel.request_to_session[req_id] = receiver

        try:
            channel.send(Reply(ReplyType.TEXT, content), context)
        except Exception as e:
            logger.error(f"[Scheduler] Failed to send skill result: {e}")
            return False

        _remember_delivered_output(
            agent_bridge, task, channel_type, content, agent_id
        )
        logger.info(f"[Scheduler] Task {task['id']} executed: skill result sent to {receiver}")
        return True

    except Exception as e:
        logger.error(f"[Scheduler] Error in _execute_skill_call: {e}")
        import traceback
        logger.error(f"[Scheduler] Traceback: {traceback.format_exc()}")
        return False


def attach_scheduler_to_tool(tool, context: Context = None):
    """
    Attach scheduler components to a SchedulerTool instance
    
    Args:
        tool: SchedulerTool instance
        context: Current context (optional)
    """
    if context:
        agent_id = context.get("agent_id")
        task_store = get_task_store(agent_id=agent_id)
        scheduler_service = get_scheduler_service(agent_id=agent_id)
        if task_store:
            tool.task_store = task_store
        if scheduler_service:
            tool.scheduler_service = scheduler_service
        tool.current_context = context
        
        channel_type = context.get("channel_type") or conf().get("channel_type", "unknown")
        if not tool.config:
            tool.config = {}
        tool.config["channel_type"] = channel_type
