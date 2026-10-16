import json
from dataclasses import dataclass
from typing import Dict, Callable, Optional, List

from agent.tools.base_tool import BaseTool, ToolResult
from common.log import logger

STATUSES = ("pending", "in_progress", "completed")

_DESC_HEAD = (
    "记录和更新完整待办列表，用于安排多步骤任务并展示进度。"
    "任务包含两个或更多具体步骤时，在开始执行前调用，每个具体步骤对应一项；"
    "简单的单步任务可以跳过，不要为了使用工具而人为拆分步骤。"
    "每次必须传入完整列表，整体替换之前的列表，不做增量合并；"
    "传入空数组表示显式清空。"
)

_DESC_SINGLE = (
    "有任务正在执行时，将当前项标记为 in_progress；"
    "同一时刻最多允许一项处于进行中。"
)

_DESC_PARALLEL = (
    "将所有正在执行的项标记为 in_progress；"
    "只有工作确实并行执行时，才允许多项同时处于进行中。"
)

_DESC_TAIL = (
    "每完成一项就立即标记为 completed，步骤发生变化时及时更新完整列表。"
    "取消或失败的任务不得标记为 completed。"
    "写完待办后立即继续执行任务，不要只列待办就结束回复。"
)


def describe(allow_parallel: bool) -> str:
    """配置、工具 schema 与执行校验使用同一套并行策略。"""
    active_rule = _DESC_PARALLEL if allow_parallel else _DESC_SINGLE
    return _DESC_HEAD + active_rule + _DESC_TAIL


@dataclass(frozen=True)
class TodoContext:
    """由引擎按调用注入，绑定当前执行者所属的会话。

    commit 的契约：
    1. 只写入此 context 对应的 agent/session/run。
    2. 原子提交规范化后的完整列表及调用身份。
    3. 提交成功后返回该会话待办的单调递增版本号。
    4. 提交失败抛异常，不改变已提交状态。
    5. 同一调用重试必须幂等，不能重复生成版本。
    """

    agent_id: str
    session_id: str
    run_id: str
    tool_call_id: str
    commit: Callable[[list[Dict[str, str]], str], int]


class TodoWriteTool(BaseTool):
    """整体替换调用者所属会话的待办列表。"""

    name: str = "todo_write"
    description: str = describe(False)

    params: dict = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "todos": {
                "type": "array",
                "description": (
                    "完整待办列表，按执行顺序排列，整体替换之前的列表。"
                    "每次包含全部条目；空数组表示显式清空。"
                ),
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "content": {
                            "type": "string",
                            "minLength": 1,
                            "description": (
                                "具体待办内容，使用简短行动句。"
                                "去除首尾空白后不得为空或重复。"
                            ),
                        },
                        "status": {
                            "type": "string",
                            "enum": list(STATUSES),
                            "description": (
                                "pending: 未开始；"
                                "in_progress: 正在执行；"
                                "completed: 已完成。"
                            )
                        },
                    },
                    "required": ["content", "status"]
                }
            },
            "explanation": {
                "type": "string",
                "description": "可选，说明本次调整的原因。",
            }
        },
        "required": ["todos"],
    }

    def __init__(self, config: dict = None):
        super().__init__()
        if config is None:
            config = {}
        if not isinstance(config, dict):
            raise TypeError("todo_write 配置必须是对象")
        self.config = dict(config)
        allow_parallel = config.get("allow_parallel_in_progress", False)

        if not isinstance(allow_parallel, bool):
            raise ValueError(
                "todo_write.allow_parallel_in_progress 必须是布尔值"
            )

        self.allow_parallel = allow_parallel
        self.description = describe(allow_parallel)

        self.todo_context: Optional[TodoContext] = None

    def _validate(self, params: dict):
        """返回规范化列表与说明；失败抛 ValueError。"""
        if not isinstance(params, dict):
            raise ValueError("参数必须是对象")

        if any(key not in ("todos", "explanation") for key in params):
            raise ValueError("仅支持 todos、explanation 参数")

        if "todos" not in params:
            raise ValueError("缺少必填参数 todos")

        incoming = params["todos"]
        if not isinstance(incoming, list):
            raise ValueError("todos 必须是数组；清空请传入 []")

        explanation = params.get("explanation", "")
        if not isinstance(explanation, str):
            raise ValueError("explanation 必须是字符串")
        explanation = explanation.strip()

        cleaned = []
        seen = set()
        active_count = 0

        for index, item in enumerate(incoming):
            prefix = f"todos[{index}]"

            if not isinstance(item, dict):
                raise ValueError(f"{prefix} 必须是对象")

            if set(item) != {"content", "status"}:
                raise ValueError(
                    f"{prefix} 必须且只能包含 content、status"
                )

            content = item["content"]
            status = item["status"]

            if not isinstance(content, str):
                raise ValueError(f"{prefix}.content 必须是字符串")
            if not isinstance(status, str):
                raise ValueError(f"{prefix}.status 必须是字符串")

            content = content.strip()
            if not content:
                raise ValueError(f"{prefix}.content 不能为空")

            if status not in STATUSES:
                raise ValueError(f"{prefix}.status 非法：{status!r}")

            if content in seen:
                raise ValueError(
                    f"{prefix}.content 与前面的条目重复：{content!r}"
                )

            seen.add(content)
            cleaned.append({"content": content, "status": status})
            active_count += int(status == "in_progress")

        if not self.allow_parallel and active_count > 1:
            raise ValueError(
                "当前配置同一时刻最多允许一项处于 in_progress"
            )

        return cleaned, explanation

    @staticmethod
    def _counts(todos: List[Dict[str, str]]) -> Dict[str, int]:
        counts = {status: 0 for status in STATUSES}
        for item in todos:
            counts[item["status"]] += 1
        return counts

    @staticmethod
    def _display(todos, counts, explanation: str) -> str:
        if not todos:
            lines = ["待办列表已清空。"]
        else:
            marks = {
                "pending": "[ ]",
                "in_progress": "[~]",
                "completed": "[√]",
            }
            lines = [f"待办进度：已完成{counts['completed']}/{len(todos)}"]
            lines.extend(
                f"{marks[item['status']]} {item['content']}" for item in todos
            )

        if explanation:
            lines.extend(["", explanation])
        return "\n".join(lines)

    def execute(self, params: dict) -> ToolResult:
        # 完整校验
        try:
            todos, explanation = self._validate(params)
        except ValueError as e:
            return ToolResult.fail(str(e))

        # 必须具有所属会话及提交能。
        context = self.todo_context
        if not isinstance(context, TodoContext):
            return ToolResult.fail(
                "todo_write 尚未绑定会话提交接口，待办未更新"
            )

        identities = (
            context.agent_id,
            context.session_id,
            context.run_id,
            context.tool_call_id,
        )

        if any(
                not isinstance(value, str) or not value.strip()
                for value in identities
        ):
            return ToolResult.fail(
                "todo_write 的会话或调用身份不完整，待办未更新"
            )

        if not callable(context.commit):
            return ToolResult.fail("todo_write 的提交接口不可用")

        if self.is_cancelled():
            return ToolResult.fail("任务已取消，待办未更新")

        counts = self._counts(todos)

        try:
            version = context.commit(
                [dict(item) for item in todos],
                explanation,
            )
        except Exception:
            logger.exception(
                "[TodoWrite] 提交失败，session=%s call=%s",
                context.session_id,
                context.tool_call_id,
            )
            return ToolResult.fail("待办提交失败，请检查会话存储后重试")

        # commit 接口必须保证返回合法版本。
        if type(version) is not int or version < 1:
            logger.error("[TodoWrite] 提交接口返回了非法版本")
            return ToolResult.fail(
                "待办提交接口返回了非法版本，请重新加载会话核实状态"
            )

        self.emit_event(
            "todo_update",
            {
                "agent_id": context.agent_id,
                "session_id": context.session_id,
                "run_id": context.run_id,
                "tool_call_id": context.tool_call_id,
                "version": version,
                "todos": [dict(item) for item in todos],
                "counts": dict(counts),
                "explanation": explanation,
            },
        )

        return ToolResult.success(
            result=json.dumps(
                {
                    "todos": todos,
                    "counts":counts,
                    "version": version,
                },
                ensure_ascii=False,
            ),
            display=self._display(todos,counts,explanation),
        )
