"""
Integration module for scheduler with AgentBridge
"""

import os
from typing import Optional
from config import conf
from common.log import logger
from common.utils import expand_path
from bridge.context import Context, ContextType
from bridge.reply import Reply, ReplyType

# Global scheduler service instance
_scheduler_service = None
_task_store = None


def init_scheduler(agent_bridge) -> bool:
    """
    Initialize scheduler service
    
    Args:
        agent_bridge: AgentBridge instance
        
    Returns:
        True if initialized successfully
    """
    global _scheduler_service, _task_store
    
    try:
        from agent.tools.scheduler.task_store import TaskStore
        from agent.tools.scheduler.scheduler_service import SchedulerService
        
        # Get workspace from config
        workspace_root = expand_path(conf().get("agent_workspace", "~/cow"))
        store_path = os.path.join(workspace_root, "scheduler", "tasks.json")
        
        # Create task store
        _task_store = TaskStore(store_path)
        logger.debug(f"[Scheduler] Task store initialized: {store_path}")
        
        # Create execute callback
        def execute_task_callback(task: dict):
            """Callback to execute a scheduled task"""
            try:
                action = task.get("action", {})
                action_type = action.get("type")
                
                if action_type == "agent_task":
                    _execute_agent_task(task, agent_bridge)
                elif action_type == "send_message":
                    # Legacy support for old tasks
                    _execute_send_message(task, agent_bridge)
                elif action_type == "tool_call":
                    # Legacy support for old tasks
                    _execute_tool_call(task, agent_bridge)
                elif action_type == "skill_call":
                    # Legacy support for old tasks
                    _execute_skill_call(task, agent_bridge)
                else:
                    logger.warning(f"[Scheduler] Unknown action type: {action_type}")
            except Exception as e:
                logger.error(f"[Scheduler] Error executing task {task.get('id')}: {e}")
        
        # Create scheduler service
        _scheduler_service = SchedulerService(_task_store, execute_task_callback)
        _scheduler_service.start()
        
        logger.debug("[Scheduler] Scheduler service initialized and started")
        return True
        
    except Exception as e:
        logger.error(f"[Scheduler] Failed to initialize scheduler: {e}")
        return False


def get_task_store():
    """Get the global task store instance"""
    return _task_store


def get_scheduler_service():
    """Get the global scheduler service instance"""
    return _scheduler_service


def _remember_delivered_output(
    agent_bridge,
    task: dict,
    channel_type: str,
    content: str,
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
            remember(session_id, str(content), channel_type=channel_type, task_description=task_desc)
    except Exception as e:
        logger.warning(
            f"[Scheduler] Failed to remember delivered output for {session_id}: {e}"
        )


def _execute_agent_task(task: dict, agent_bridge):
    """
    Execute an agent_task action - let Agent handle the task
    
    Args:
        task: Task dictionary
        agent_bridge: AgentBridge instance
    """
    try:
        action = task.get("action", {})
        task_description = action.get("task_description")
        receiver = action.get("receiver")
        is_group = action.get("is_group", False)
        channel_type = action.get("channel_type", "unknown")
        
        if not task_description:
            logger.error(f"[Scheduler] Task {task['id']}: No task_description specified")
            return
        
        if not receiver:
            logger.error(f"[Scheduler] Task {task['id']}: No receiver specified")
            return
        
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
            
            if reply and reply.content:
                # Send the reply via channel
                from channel.channel_factory import create_channel
                
                try:
                    channel = create_channel(channel_type)
                    if channel:
                        # For web channel, register request_id
                        if channel_type == "web" and hasattr(channel, 'request_to_session'):
                            request_id = context.get("request_id")
                            if request_id:
                                channel.request_to_session[request_id] = receiver
                                logger.debug(f"[Scheduler] Registered request_id {request_id} -> session {receiver}")
                        
                        # Send the reply
                        channel.send(reply, context)
                        _remember_delivered_output(agent_bridge, task, channel_type, reply.content)
                        logger.info(f"[Scheduler] Task {task['id']} executed successfully, result sent to {receiver}")
                    else:
                        logger.error(f"[Scheduler] Failed to create channel: {channel_type}")
                except Exception as e:
                    logger.error(f"[Scheduler] Failed to send result: {e}")
            else:
                logger.error(f"[Scheduler] Task {task['id']}: No result from agent execution")
                
        except Exception as e:
            logger.error(f"[Scheduler] Failed to execute task via Agent: {e}")
            import traceback
            logger.error(f"[Scheduler] Traceback: {traceback.format_exc()}")
            
    except Exception as e:
        logger.error(f"[Scheduler] Error in _execute_agent_task: {e}")
        import traceback
        logger.error(f"[Scheduler] Traceback: {traceback.format_exc()}")


def _execute_send_message(task: dict, agent_bridge):
    """
    Execute a send_message action
    
    Args:
        task: Task dictionary
        agent_bridge: AgentBridge instance
    """
    try:
        action = task.get("action", {})
        content = action.get("content", "")
        receiver = action.get("receiver")
        is_group = action.get("is_group", False)
        channel_type = action.get("channel_type", "unknown")
        
        if not receiver:
            logger.error(f"[Scheduler] Task {task['id']}: No receiver specified")
            return
        
        # Create context for sending message
        context = Context(ContextType.TEXT, content)
        context["receiver"] = receiver
        context["isgroup"] = is_group
        context["session_id"] = receiver
        
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
        
        try:
            channel = create_channel(channel_type)
            if channel:
                # For web channel, register the request_id to session mapping
                if channel_type == "web" and hasattr(channel, 'request_to_session'):
                    channel.request_to_session[request_id] = receiver
                    logger.debug(f"[Scheduler] Registered request_id {request_id} -> session {receiver}")
                
                channel.send(reply, context)
                _remember_delivered_output(agent_bridge, task, channel_type, content)
                logger.info(f"[Scheduler] Task {task['id']} executed: sent message to {receiver}")
            else:
                logger.error(f"[Scheduler] Failed to create channel: {channel_type}")
        except Exception as e:
            logger.error(f"[Scheduler] Failed to send message: {e}")
            import traceback
            logger.error(f"[Scheduler] Traceback: {traceback.format_exc()}")
            
    except Exception as e:
        logger.error(f"[Scheduler] Error in _execute_send_message: {e}")
        import traceback
        logger.error(f"[Scheduler] Traceback: {traceback.format_exc()}")


def _execute_tool_call(task: dict, agent_bridge):
    """
    Execute a tool_call action
    
    Args:
        task: Task dictionary
        agent_bridge: AgentBridge instance
    """
    try:
        action = task.get("action", {})
        # Support both old and new field names
        tool_name = action.get("call_name") or action.get("tool_name")
        tool_params = action.get("call_params") or action.get("tool_params", {})
        result_prefix = action.get("result_prefix", "")
        receiver = action.get("receiver")
        is_group = action.get("is_group", False)
        channel_type = action.get("channel_type", "unknown")
        
        if not tool_name:
            logger.error(f"[Scheduler] Task {task['id']}: No tool_name specified")
            return
        
        if not receiver:
            logger.error(f"[Scheduler] Task {task['id']}: No receiver specified")
            return
        
        # Get tool manager and create tool instance
        from agent.tools.tool_manager import ToolManager
        tool_manager = ToolManager()
        tool = tool_manager.create_tool(tool_name)
        
        if not tool:
            logger.error(f"[Scheduler] Task {task['id']}: Tool '{tool_name}' not found")
            return
        
        # Execute tool
        logger.info(f"[Scheduler] Task {task['id']}: Executing tool '{tool_name}' with params {tool_params}")
        result = tool.execute(tool_params)
        
        # Get result content
        if hasattr(result, 'result'):
            content = result.result
        else:
            content = str(result)
        
        # Add prefix if specified
        if result_prefix:
            content = f"{result_prefix}\n\n{content}"
        
        # Send result as message
        context = Context(ContextType.TEXT, content)
        context["receiver"] = receiver
        context["isgroup"] = is_group
        context["session_id"] = receiver
        
        # Channel-specific context setup
        if channel_type == "web":
            # Web channel needs request_id
            import uuid
            request_id = f"scheduler_{task['id']}_{uuid.uuid4().hex[:8]}"
            context["request_id"] = request_id
            logger.debug(f"[Scheduler] Generated request_id for web channel: {request_id}")
        elif channel_type == "feishu":
            context["receive_id_type"] = "chat_id" if is_group else "open_id"
            context["msg"] = None
            logger.debug(f"[Scheduler] Feishu: receive_id_type={context['receive_id_type']}, is_group={is_group}, receiver={receiver}")
        elif channel_type == "wecom_bot":
            context["msg"] = None

        reply = Reply(ReplyType.TEXT, content)

        # Get channel and send
        from channel.channel_factory import create_channel

        try:
            channel = create_channel(channel_type)
            if channel:
                if channel_type == "web" and hasattr(channel, 'request_to_session'):
                    channel.request_to_session[request_id] = receiver
                    logger.debug(f"[Scheduler] Registered request_id {request_id} -> session {receiver}")

                channel.send(reply, context)
                _remember_delivered_output(agent_bridge, task, channel_type, content)
                logger.info(f"[Scheduler] Task {task['id']} executed: sent tool result to {receiver}")
            else:
                logger.error(f"[Scheduler] Failed to create channel: {channel_type}")
        except Exception as e:
            logger.error(f"[Scheduler] Failed to send tool result: {e}")

    except Exception as e:
        logger.error(f"[Scheduler] Error in _execute_tool_call: {e}")


def _execute_skill_call(task: dict, agent_bridge):
    """
    Execute a skill_call action by asking Agent to run the skill
    
    Args:
        task: Task dictionary
        agent_bridge: AgentBridge instance
    """
    try:
        action = task.get("action", {})
        # Support both old and new field names
        skill_name = action.get("call_name") or action.get("skill_name")
        skill_params = action.get("call_params") or action.get("skill_params", {})
        result_prefix = action.get("result_prefix", "")
        receiver = action.get("receiver")
        is_group = action.get("isgroup", False)
        channel_type = action.get("channel_type", "unknown")
        
        if not skill_name:
            logger.error(f"[Scheduler] Task {task['id']}: No skill_name specified")
            return
        
        if not receiver:
            logger.error(f"[Scheduler] Task {task['id']}: No receiver specified")
            return
        
        logger.info(f"[Scheduler] Task {task['id']}: Executing skill '{skill_name}' with params {skill_params}")
        
        # Create a unique session_id for this scheduled task to avoid polluting user's conversation
        # Format: scheduler_<receiver>_<task_id> to ensure isolation
        scheduler_session_id = f"scheduler_{receiver}_{task['id']}"
        
        # Build a natural language query for the Agent to execute the skill
        # Format: "Use skill-name to do something with params"
        param_str = ", ".join([f"{k}={v}" for k, v in skill_params.items()])
        query = f"Use {skill_name} skill"
        if param_str:
            query += f" with {param_str}"
        
        # Create context for Agent
        context = Context(ContextType.TEXT, query)
        context["receiver"] = receiver
        context["isgroup"] = is_group
        context["session_id"] = scheduler_session_id
        
        # Channel-specific setup
        if channel_type == "web":
            import uuid
            request_id = f"scheduler_{task['id']}_{uuid.uuid4().hex[:8]}"
            context["request_id"] = request_id
        elif channel_type == "feishu":
            context["receive_id_type"] = "chat_id" if is_group else "open_id"
            context["msg"] = None
        elif channel_type == "wecom_bot":
            context["msg"] = None

        # Use Agent to execute the skill
        try:
            # Don't clear history - scheduler tasks use isolated session_id so they won't pollute user conversations
            reply = agent_bridge.agent_reply(query, context=context, on_event=None, clear_history=False)
            
            if reply and reply.content:
                content = reply.content
                
                # Add prefix if specified
                if result_prefix:
                    content = f"{result_prefix}\n\n{content}"
                
                # Send the result via channel
                from channel.channel_factory import create_channel
                
                try:
                    channel = create_channel(channel_type)
                    if channel:
                        # For web channel, register request_id
                        if channel_type == "web" and hasattr(channel, 'request_to_session'):
                            req_id = context.get("request_id")
                            if req_id:
                                channel.request_to_session[req_id] = receiver
                                logger.debug(f"[Scheduler] Registered request_id {req_id} -> session {receiver}")
                        
                        channel.send(Reply(ReplyType.TEXT, content), context)
                        _remember_delivered_output(agent_bridge, task, channel_type, content)
                except Exception as e:
                    logger.error(f"[Scheduler] Failed to send skill result: {e}")
                
                logger.info(f"[Scheduler] Task {task['id']} executed: skill result sent to {receiver}")
            else:
                logger.error(f"[Scheduler] Task {task['id']}: No result from skill execution")
                
        except Exception as e:
            logger.error(f"[Scheduler] Failed to execute skill via Agent: {e}")
            import traceback
            logger.error(f"[Scheduler] Traceback: {traceback.format_exc()}")
            
    except Exception as e:
        logger.error(f"[Scheduler] Error in _execute_skill_call: {e}")
        import traceback
        logger.error(f"[Scheduler] Traceback: {traceback.format_exc()}")


def attach_scheduler_to_tool(tool, context: Context = None):
    """
    Attach scheduler components to a SchedulerTool instance
    
    Args:
        tool: SchedulerTool instance
        context: Current context (optional)
    """
    if _task_store:
        tool.task_store = _task_store
    
    if context:
        tool.current_context = context
        
        channel_type = context.get("channel_type") or conf().get("channel_type", "unknown")
        if not tool.config:
            tool.config = {}
        tool.config["channel_type"] = channel_type
