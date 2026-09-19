"""
Scheduler tool for creating and managing scheduled tasks
"""

import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from croniter import croniter
from agent.tools.scheduler.time_utils import (
    display_local,
    next_cron_occurrence,
    parse_utc,
    resolve_timezone,
    task_timezone,
    utc_now,
)

from agent.tools.base_tool import BaseTool, ToolResult
from bridge.context import Context, ContextType
from bridge.reply import Reply, ReplyType
from common.log import logger


class SchedulerTool(BaseTool):
    """
    Tool for managing scheduled tasks (reminders, notifications, etc.)
    """
    
    name: str = "scheduler"
    description: str = (
        "创建、查询和管理定时任务（提醒、周期性任务等）。\n\n"
        "⚠️ 重要：仅当需要「定时/提醒/每天/每周/X分钟后/X点」等延迟或周期执行时才使用此工具。"
        "使用方法：\n"
        "- 创建：action='create', name='任务名', message/ai_task='内容', schedule_type='once/interval/cron', schedule_value='...'\n"
        "- 查询：action='list' / action='get', task_id='任务ID'\n"
        "- 管理：action='delete/enable/disable', task_id='任务ID'\n\n"
        "调度类型：\n"
        "- once: 一次性任务，支持相对时间(+5s,+10m,+1h,+1d)或ISO时间\n"
        "- interval: 固定间隔(秒)，如3600表示每小时\n"
        "- cron: cron表达式，如'0 8 * * *'表示每天8点\n\n"
        "注意：'X秒后'用once+相对时间，'每X秒'用interval\n"
        "For Web cross-channel delivery, call action='list_recipients' first, "
        "then create a task (fixed message or ai_task) using the returned channel_type and receiver."
    )
    params: dict = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["create", "list", "list_recipients", "get", "delete", "enable", "disable"],
                "description": "操作类型: create(创建), list(列表), get(查询), delete(删除), enable(启用), disable(禁用)"
            },
            "task_id": {
                "type": "string",
                "description": "任务ID (用于 get/delete/enable/disable 操作)"
            },
            "name": {
                "type": "string",
                "description": "任务名称 (用于 create 操作)"
            },
            "message": {
                "type": "string",
                "description": "固定消息内容 (与ai_task二选一)"
            },
            "ai_task": {
                "type": "string",
                "description": (
                    "任务描述 (与message二选一)，描述到点时需要 Agent 执行的任务，例如执行什么操作、交付什么内容，"
                    "无需重复声明调度时间（由 schedule 决定）。"
                )
            },
            "schedule_type": {
                "type": "string",
                "enum": ["cron", "interval", "once"],
                "description": "调度类型 (用于 create 操作): cron(cron表达式), interval(固定间隔秒数), once(一次性)"
            },
            "schedule_value": {
                "type": "string",
                "description": "调度值: cron表达式/间隔秒数/时间(+5s,+10m,+1h或ISO格式)"
            },
            "silent": {
                "type": "boolean",
                "default": False,
                "description": "Silent mode (default false): when true, the task runs normally but its result is not pushed. Set true only when the user explicitly says they don't need the result; reminder, notification and broadcast tasks must keep it false"
            },
            "channel_type": {
                "type": "string",
                "description": "Target channel type for a Web-created cross-channel task. Use list_recipients first."
            },
            "instance_id": {
                "type": "string",
                "description": "The specific channel instance the recipient belongs to, as returned by list_recipients. Required when a channel type runs more than one instance; the same receiver on two instances is two different targets. Omit for a single-instance channel."
            },
            "timezone": {
                "type": "string",
                "description": "Optional IANA timezone (e.g. Asia/Shanghai) used for cron wall-clock times and naive ISO timestamps"
            },
            "receiver": {
                "type": "string",
                "description": "Trusted target receiver returned by list_recipients. It cannot be an arbitrary user ID."
            },
        },
        "required": ["action"]
    }
    
    def __init__(self, config: dict = None):
        super().__init__()
        self.config = config or {}
        
        # Will be set by agent bridge
        self.task_store = None
        self.recipient_store = None
        self.current_context = None
    
    def execute(self, params: dict) -> ToolResult:
        """
        Execute scheduler operations
        
        Args:
            params: Dictionary containing:
                - action: Operation type (create/list/get/delete/enable/disable)
                - Other parameters depending on action
            
        Returns:
            ToolResult object
        """
        # Extract parameters
        action = params.get("action")
        kwargs = params
        
        if not self.task_store:
            return ToolResult.fail("错误: 定时任务系统未初始化")
        
        try:
            if action == "create":
                result = self._create_task(**kwargs)
                return ToolResult.success(result)
            elif action == "list":
                result = self._list_tasks(**kwargs)
                return ToolResult.success(result)
            elif action == "list_recipients":
                result = self._list_recipients(**kwargs)
                return ToolResult.success(result)
            elif action == "get":
                result = self._get_task(**kwargs)
                return ToolResult.success(result)
            elif action == "delete":
                result = self._delete_task(**kwargs)
                return ToolResult.success(result)
            elif action == "enable":
                result = self._enable_task(**kwargs)
                return ToolResult.success(result)
            elif action == "disable":
                result = self._disable_task(**kwargs)
                return ToolResult.success(result)
            else:
                return ToolResult.fail(f"未知操作: {action}")
        except Exception as e:
            logger.error(f"[SchedulerTool] Error: {e}")
            return ToolResult.fail(f"操作失败: {str(e)}")
    
    def _create_task(self, **kwargs) -> str:
        """Create a new scheduled task"""
        name = kwargs.get("name")
        message = kwargs.get("message")
        ai_task = kwargs.get("ai_task")
        schedule_type = kwargs.get("schedule_type")
        schedule_value = kwargs.get("schedule_value")
        timezone_name = kwargs.get("timezone")
        
        # Validate required fields
        if not name:
            return "错误: 缺少任务名称 (name)"
        
        # Check that exactly one of message/ai_task is provided
        if not message and not ai_task:
            return "错误: 必须提供 message（固定消息）或 ai_task（AI任务）之一"
        if message and ai_task:
            return "错误: message 和 ai_task 只能提供其中一个"
        
        if not schedule_type:
            return "错误: 缺少调度类型 (schedule_type)"
        if not schedule_value:
            return "错误: 缺少调度值 (schedule_value)"
        
        # Validate schedule
        schedule = self._parse_schedule(schedule_type, schedule_value, timezone_name)
        if not schedule:
            return f"错误: 无效的调度配置 - type: {schedule_type}, value: {schedule_value}"
        
        # Get context info for receiver
        if not self.current_context:
            return "错误: 无法获取当前对话上下文"
        
        context = self.current_context

        target_channel = kwargs.get("channel_type")
        target_receiver = kwargs.get("receiver")
        # A channel type can run several instances; delivery must go back through
        # the exact one that saw the contact. When the caller does not name an
        # instance (legacy single-instance channel), it equals the channel type.
        target_instance = kwargs.get("instance_id") or target_channel
        target = None
        if target_channel or target_receiver:
            if context.get("channel_type") != "web":
                return "Error: cross-channel recipients can only be selected from the Web console"
            if not target_channel or not target_receiver:
                return "Error: channel_type and receiver must be provided together"
            if not self.recipient_store:
                return "Error: trusted recipient directory is unavailable"
            target = self.recipient_store.get(target_instance, target_receiver)
            if not target:
                return "Error: target is not in the trusted recipient directory; use list_recipients"
        
        # Create task
        task_id = str(uuid.uuid4())[:8]
        
        # Capture the real chat session_id at task creation time so that scheduler
        # can later inject the delivered output into the user's actual conversation
        # (in group chats, session_id != receiver, e.g. "user_id:group_id" on feishu).
        notify_session_id = target["session_id"] if target else context.get("session_id")
        receiver = target["receiver"] if target else context.get("receiver")
        receiver_name = target["name"] if target else self._get_receiver_name(context)
        is_group = target["is_group"] if target else context.get("isgroup", False)
        channel_type = target["channel_type"] if target else self.config.get("channel_type", "unknown")
        # The instance to deliver back through: the target's own for a
        # cross-channel task, else this conversation's. Defaults to the channel
        # type so a legacy single-instance channel keeps resolving as before.
        instance_id = (
            target.get("instance_id") if target else context.get("instance_id")
        ) or channel_type

        # Build action based on message or ai_task
        if message:
            action = {
                "type": "send_message",
                "content": message,
                "receiver": receiver,
                "receiver_name": receiver_name,
                "is_group": is_group,
                "channel_type": channel_type,
                "instance_id": instance_id,
                "notify_session_id": notify_session_id,
            }
        else:  # ai_task
            action = {
                "type": "agent_task",
                "task_description": ai_task,
                "receiver": receiver,
                "receiver_name": receiver_name,
                "is_group": is_group,
                "channel_type": channel_type,
                "instance_id": instance_id,
                "notify_session_id": notify_session_id,
            }
            # silent only applies to ai_task; fixed messages always deliver
            if kwargs.get("silent", False):
                action["silent"] = True
        
        # 针对钉钉单聊，额外存储 sender_staff_id
        msg = context.kwargs.get("msg")
        if msg and hasattr(msg, 'sender_staff_id') and not context.get("isgroup", False):
            action["dingtalk_sender_staff_id"] = msg.sender_staff_id
        
        # The Agent this task runs as. Stored on the task (not implied by which
        # file it lives in) so the global scheduler can scope execution to it and
        # so re-binding a channel instance to a different Agent never moves data.
        owner_agent_id = self._resolve_owner_agent_id(context, target)

        task_data = {
            "id": task_id,
            "name": name,
            "agent_id": owner_agent_id,
            "enabled": True,
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "schedule": schedule,
            "action": action
        }
        
        # Calculate initial next_run_at
        next_run = self._calculate_next_run(task_data)
        if next_run:
            task_data["next_run_at"] = next_run.isoformat()
        
        # Save task
        self.task_store.add_task(task_data)
        
        # Format response
        schedule_desc = self._format_schedule_description(schedule)
        receiver_desc = task_data["action"]["receiver_name"] or task_data["action"]["receiver"]
        
        if message:
            content_desc = f"💬 固定消息: {message}"
        else:
            content_desc = f"🤖 AI任务: {ai_task}"

        # Warn the user at creation time so a mistaken silent flag is easy to spot
        silent_desc = "\n🔇 静默模式: 执行后不会推送结果" if action.get("silent") else ""

        return (
            f"✅ 定时任务创建成功\n\n"
            f"📋 任务ID: {task_id}\n"
            f"📝 名称: {name}\n"
            f"⏰ 调度: {schedule_desc}\n"
            f"👤 接收者: {receiver_desc}\n"
            f"{content_desc}{silent_desc}\n"
            f"🕐 下次执行: {next_run.astimezone().strftime('%Y-%m-%d %H:%M:%S') if next_run else '未知'}"
        )
    
    def _list_tasks(self, **kwargs) -> str:
        """List all tasks"""
        tasks = self.task_store.list_tasks()
        
        if not tasks:
            return "📋 暂无定时任务"
        
        lines = [f"📋 定时任务列表 (共 {len(tasks)} 个)\n"]
        
        for task in tasks:
            status = "✅" if task.get("enabled", True) else "❌"
            schedule_desc = self._format_schedule_description(task.get("schedule", {}))
            next_run = task.get("next_run_at")
            next_run_str = display_local(next_run, task_timezone(task)).strftime('%m-%d %H:%M') if next_run else "未知"
            
            lines.append(
                f"{status} [{task['id']}] {task['name']}\n"
                f"   ⏰ {schedule_desc} | 下次: {next_run_str}"
            )
        
        return "\n".join(lines)

    def _list_recipients(self, **kwargs) -> str:
        """List trusted targets available to the Web scheduler."""
        if not self.current_context or self.current_context.get("channel_type") != "web":
            return "Error: trusted recipients can only be listed from the Web console"
        if not self.recipient_store:
            return "Error: trusted recipient directory is unavailable"
        recipients = self.recipient_store.list()
        if not recipients:
            return "No trusted recipients yet. A recipient must contact CowAgent first."
        lines = ["Trusted scheduler recipients:"]
        for item in recipients:
            kind = "group" if item["is_group"] else "user"
            instance_id = item.get("instance_id") or item["channel_type"]
            lines.append(
                f"- {item['name']} ({kind}): channel_type={item['channel_type']}, "
                f"instance_id={instance_id}, receiver={item['receiver']}"
            )
        return "\n".join(lines)
    
    def _get_task(self, **kwargs) -> str:
        """Get task details"""
        task_id = kwargs.get("task_id")
        if not task_id:
            return "错误: 缺少任务ID (task_id)"
        
        task = self.task_store.get_task(task_id)
        if not task:
            return f"错误: 任务 '{task_id}' 不存在"
        
        status = "启用" if task.get("enabled", True) else "禁用"
        schedule_desc = self._format_schedule_description(task.get("schedule", {}))
        action = task.get("action", {})
        next_run = task.get("next_run_at")
        zone = task_timezone(task)
        next_run_str = display_local(next_run, zone).strftime('%Y-%m-%d %H:%M:%S') if next_run else "未知"
        last_run = task.get("last_run_at")
        last_run_str = display_local(last_run, zone).strftime('%Y-%m-%d %H:%M:%S') if last_run else "从未执行"
        
        return (
            f"📋 任务详情\n\n"
            f"ID: {task['id']}\n"
            f"名称: {task['name']}\n"
            f"状态: {status}\n"
            f"调度: {schedule_desc}\n"
            f"接收者: {action.get('receiver_name', action.get('receiver'))}\n"
            f"消息: {action.get('content')}\n"
            f"下次执行: {next_run_str}\n"
            f"上次执行: {last_run_str}\n"
            f"创建时间: {display_local(task['created_at']).strftime('%Y-%m-%d %H:%M:%S')}"
        )
    
    def _delete_task(self, **kwargs) -> str:
        """Delete a task"""
        task_id = kwargs.get("task_id")
        if not task_id:
            return "错误: 缺少任务ID (task_id)"
        
        task = self.task_store.get_task(task_id)
        if not task:
            return f"错误: 任务 '{task_id}' 不存在"
        
        self.task_store.delete_task(task_id)
        return f"✅ 任务 '{task['name']}' ({task_id}) 已删除"
    
    def _enable_task(self, **kwargs) -> str:
        """Enable a task"""
        task_id = kwargs.get("task_id")
        if not task_id:
            return "错误: 缺少任务ID (task_id)"
        
        task = self.task_store.get_task(task_id)
        if not task:
            return f"错误: 任务 '{task_id}' 不存在"
        
        self.task_store.enable_task(task_id, True)
        return f"✅ 任务 '{task['name']}' ({task_id}) 已启用"
    
    def _disable_task(self, **kwargs) -> str:
        """Disable a task"""
        task_id = kwargs.get("task_id")
        if not task_id:
            return "错误: 缺少任务ID (task_id)"
        
        task = self.task_store.get_task(task_id)
        if not task:
            return f"错误: 任务 '{task_id}' 不存在"
        
        self.task_store.enable_task(task_id, False)
        return f"✅ 任务 '{task['name']}' ({task_id}) 已禁用"
    
    def _parse_schedule(
        self, schedule_type: str, schedule_value: str, timezone_name: str = None
    ) -> Optional[dict]:
        """Parse and validate schedule configuration"""
        try:
            zone = resolve_timezone(timezone_name)
            if schedule_type == "cron":
                # Validate cron expression
                croniter(schedule_value)
                schedule = {"type": "cron", "expression": schedule_value}
                if timezone_name:
                    schedule["timezone"] = timezone_name.strip()
                return schedule
            
            elif schedule_type == "interval":
                # Parse interval in seconds
                seconds = int(schedule_value)
                if seconds <= 0:
                    return None
                return {"type": "interval", "seconds": seconds}
            
            elif schedule_type == "once":
                # Parse datetime - support both relative and absolute time
                
                # Check if it's relative time (e.g., "+5s", "+10m", "+1h", "+1d")
                if schedule_value.startswith("+"):
                    import re
                    match = re.match(r'\+(\d+)([smhd])', schedule_value)
                    if match:
                        amount = int(match.group(1))
                        unit = match.group(2)
                        
                        now = utc_now()
                        
                        if unit == 's':  # seconds
                            target_time = now + timedelta(seconds=amount)
                        elif unit == 'm':  # minutes
                            target_time = now + timedelta(minutes=amount)
                        elif unit == 'h':  # hours
                            target_time = now + timedelta(hours=amount)
                        elif unit == 'd':  # days
                            target_time = now + timedelta(days=amount)
                        else:
                            return None
                        
                        schedule = {"type": "once", "run_at": target_time.isoformat()}
                        if timezone_name:
                            schedule["timezone"] = timezone_name.strip()
                        return schedule
                    else:
                        logger.error(f"[SchedulerTool] Invalid relative time format: {schedule_value}")
                        return None
                else:
                    # Absolute ISO times are canonicalized to UTC. A naive
                    # value uses the task timezone, or server-local time for
                    # backward compatibility when no timezone was supplied.
                    parsed = parse_utc(schedule_value, zone)
                    schedule = {"type": "once", "run_at": parsed.isoformat()}
                    if timezone_name:
                        schedule["timezone"] = timezone_name.strip()
                    return schedule
            
        except Exception as e:
            logger.error(f"[SchedulerTool] Invalid schedule: {e}")
            return None
        
        return None
    
    def _calculate_next_run(self, task: dict) -> Optional[datetime]:
        """Calculate next run time for a task"""
        schedule = task.get("schedule", {})
        schedule_type = schedule.get("type")
        now = utc_now()
        
        if schedule_type == "cron":
            expression = schedule.get("expression")
            return next_cron_occurrence(expression, now, task_timezone(task))
        
        elif schedule_type == "interval":
            seconds = schedule.get("seconds", 0)
            return now + timedelta(seconds=seconds)
        
        elif schedule_type == "once":
            run_at_str = schedule.get("run_at")
            return parse_utc(run_at_str, task_timezone(task))
        
        return None
    
    def _format_schedule_description(self, schedule: dict) -> str:
        """Format schedule as human-readable description"""
        schedule_type = schedule.get("type")
        
        if schedule_type == "cron":
            expr = schedule.get("expression", "")
            zone_name = schedule.get("timezone")
            # Try to provide friendly description
            if expr == "0 9 * * *":
                return "每天 9:00"
            elif expr == "0 */1 * * *":
                return "每小时"
            elif expr == "*/30 * * * *":
                return "每30分钟"
            else:
                return f"Cron: {expr} ({zone_name})" if zone_name else f"Cron: {expr}"
        
        elif schedule_type == "interval":
            seconds = schedule.get("seconds", 0)
            if seconds >= 86400:
                days = seconds // 86400
                return f"每 {days} 天"
            elif seconds >= 3600:
                hours = seconds // 3600
                return f"每 {hours} 小时"
            elif seconds >= 60:
                minutes = seconds // 60
                return f"每 {minutes} 分钟"
            else:
                return f"每 {seconds} 秒"
        
        elif schedule_type == "once":
            run_at = schedule.get("run_at", "")
            try:
                dt = display_local(run_at, resolve_timezone(schedule.get("timezone")))
                return f"一次性 ({dt.strftime('%Y-%m-%d %H:%M')})"
            except Exception:
                return "一次性"
        
        return "未知"
    
    def _get_receiver_name(self, context: Context) -> str:
        """Get receiver name from context"""
        try:
            msg = context.get("msg")
            if msg:
                if context.get("isgroup"):
                    return msg.other_user_nickname or "群聊"
                else:
                    return msg.from_user_nickname or "用户"
        except Exception:
            pass
        return "未知"

    def _resolve_owner_agent_id(self, context: Context, target: Optional[dict]) -> str:
        """Which Agent the new task runs as.

        For a cross-channel task the owner is the Agent the target's channel
        instance is bound to (delivery and identity should match how an inbound
        message from that instance would route). For a normal conversation task
        it is simply the Agent handling this conversation. Falls back to the
        ambient runtime identity, then the default Agent.
        """
        # Cross-channel: derive from the target instance's binding.
        if target:
            iid = (target.get("instance_id") or "").strip()
            if iid:
                try:
                    from channel.channel_instances import get_instance
                    from config import conf as _conf

                    inst = get_instance(_conf(), iid)
                    if inst and getattr(inst, "agent_id", ""):
                        return inst.agent_id
                except Exception:
                    pass
        # Conversation task: the Agent on the context, else ambient identity.
        agent_id = (context.get("agent_id") if context else "") or ""
        if not agent_id:
            try:
                from common.runtime_identity import current_identity

                agent_id = current_identity().agent_id or ""
            except Exception:
                agent_id = ""
        if agent_id:
            return agent_id
        try:
            from agent.registry import get_agent_registry

            return get_agent_registry().default_agent_id
        except Exception:
            return ""
