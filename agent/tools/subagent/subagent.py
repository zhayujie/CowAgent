"""The tool the main Agent uses to hand work to a sub agent.

Deliberately not the tool for reaching a peer Agent. A sub agent is a way this
Agent gets work done; a peer has its own workspace, identity and permissions, so
handing work across that boundary is a different decision, needs a different
authorization, and belongs in its own tool.
"""

import json
import threading
import uuid
from typing import List

from agent.tools.base_tool import BaseTool, ToolResult
from common.log import logger


_STATIC_DESCRIPTION = (
    "Hand a self-contained task to a sub agent that works in its own context "
    "and reports back with only its conclusion."
)

# How much of a failed step's error travels out with it. Enough to say what
# went wrong, not enough for twenty of them to weigh on the stream.
_STEP_ERROR_CHARS = 300


def _format_duration(seconds: float) -> str:
    seconds = int(round(seconds or 0))
    if seconds < 60:
        return f"{seconds}s"
    return f"{seconds // 60}m {seconds % 60}s"


def _error_text(value) -> str:
    text = json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else str(value or "")
    return f"{text[:_STEP_ERROR_CHARS]}…" if len(text) > _STEP_ERROR_CHARS else text


def format_results(results: List[dict]) -> str:
    """The spawn's outcome, written for a person.

    The tool returns JSON because that is what the parent model parses. Nobody
    who just waited minutes for a report wants to read a JSON blob, so the
    same outcome goes out a second time as markdown for whoever is watching.
    """
    numbered = len(results) > 1
    blocks = []
    for position, item in enumerate(results, 1):
        heading = item.get("subagent_type") or "subagent"
        if numbered:
            heading = f"{position}. {heading}"
        if item.get("duration_seconds"):
            heading += f" · {_format_duration(item['duration_seconds'])}"

        status = item.get("status")
        body = item.get("summary") or item.get("error") or "(no output)"
        if status != "completed":
            body = f"**{status or 'unknown'}** — {body}"
        blocks.append(f"### {heading}\n\n{body}")
    return "\n\n---\n\n".join(blocks)


class _SpawnView:
    """What someone following the run gets to see of one spawn call.

    The parent's context is unaffected by any of this: it still receives only
    the returned summary, which is the whole point of spawning. This is the
    other audience — the person watching — for whom a sub agent that reports
    nothing until it finishes is indistinguishable from one that hung.
    """

    def __init__(self, tool, tasks: List):
        self.tool = tool
        self.tasks = tasks
        # Several sub agents need a card each; one spinner cannot say which of
        # them is still going. A lone sub agent already has the spawn call's
        # own card, and a second card for the same work is just noise.
        self.own_cards = len(tasks) > 1
        if self.own_cards:
            self.card_ids = [uuid.uuid4().hex[:12] for _ in tasks]
        else:
            self.card_ids = [getattr(tool, "tool_call_id", None) or uuid.uuid4().hex[:12]]
        self._closed = set()
        # Files each sub agent wrote, by task. Sub agents run on their own
        # threads, so this is written from several at once.
        self._files: dict = {}
        self._lock = threading.Lock()

    def files_for(self, index: int) -> List[str]:
        with self._lock:
            return list(self._files.get(index, ()))

    def on_state(self, index: int, state: dict) -> None:
        if not self.own_cards:
            return
        name = f"subagent:{state.get('subagent_type') or 'unknown'}"
        if state.get("status") == "running":
            self.tool.emit_event("tool_execution_start", {
                "tool_call_id": self.card_ids[index],
                "tool_name": name,
                "arguments": {"goal": self.tasks[index].goal},
            })
            return
        # A task cancelled on timeout settles twice: once when the timeout is
        # declared, once when the run it belongs to notices. The first is the
        # one that explains what happened. Those two arrive on different
        # threads, so claiming the task has to be one step.
        with self._lock:
            if index in self._closed:
                return
            self._closed.add(index)
        completed = state.get("status") == "completed"
        self.tool.emit_event("tool_execution_end", {
            "tool_call_id": self.card_ids[index],
            "tool_name": name,
            "status": "success" if completed else "error",
            "result": state.get("summary") or state.get("error") or "",
            "display": format_results([state]),
            "execution_time": state.get("duration_seconds", 0),
        })

    def on_event(self, index: int, event: dict) -> None:
        """Relay the parts of a sub agent's run that belong to this spawn.

        Its tool calls and the files it writes describe work the user asked
        for. Its prose and reasoning do not travel: those streams render as
        the assistant speaking, and a sub agent talking to itself in the main
        reply reads as the assistant losing the thread.
        """
        event_type = event.get("type")
        data = event.get("data") or {}

        if event_type == "artifact":
            path = data.get("path")
            if path:
                with self._lock:
                    self._files.setdefault(index, []).append(path)
            self.tool.emit_event("artifact", data)
        elif event_type == "tool_execution_start":
            self.tool.emit_event("subagent_step", {
                "card_id": self.card_ids[index],
                "step_id": self._step_id(index, data),
                "phase": "start",
                "tool_name": data.get("tool_name", "tool"),
                "arguments": data.get("arguments") or {},
            })
        elif event_type == "tool_execution_end":
            status = data.get("status", "success")
            step = {
                "card_id": self.card_ids[index],
                "step_id": self._step_id(index, data),
                "phase": "end",
                "tool_name": data.get("tool_name", "tool"),
                "status": status,
                "execution_time": round(data.get("execution_time") or 0, 2),
            }
            # What a step returned is already accounted for in the sub agent's
            # report, so carrying it here would be the same findings a second
            # time, in the one place too small to read them. An error is the
            # exception: nothing else says why that step came up empty.
            if status != "success":
                step["error"] = _error_text(data.get("result"))
            self.tool.emit_event("subagent_step", step)

    def _step_id(self, index: int, data: dict) -> str:
        # Sub agents pick tool call ids independently, so two of them running
        # at once can choose the same one. The card scopes it back to unique.
        return f"{self.card_ids[index]}:{data.get('tool_call_id') or uuid.uuid4().hex[:8]}"


class SubagentTool(BaseTool):
    name = "subagent"
    # Sub agents share nothing but the workspace, so two of them running at
    # once is the same situation as two tasks inside one call. Models routinely
    # express independent work as several calls rather than one call with a
    # list; this lets that phrasing run just as fast.
    parallel_safe = True

    params = {
        "type": "object",
        "properties": {
            "goal": {
                "type": "string",
                "description": (
                    "What the sub agent should accomplish. Write it as a complete "
                    "instruction to someone who has never seen this conversation."
                ),
            },
            "context": {
                "type": "string",
                "description": (
                    "Everything the sub agent needs and cannot look up: file paths, "
                    "error text, decisions already made, what to leave alone. It "
                    "cannot see your conversation, so anything you omit is lost."
                ),
            },
            "subagent_type": {
                "type": "string",
                "description": "Which kind of sub agent to use. See the list in this tool's description.",
            },
            "tasks": {
                "type": "array",
                "description": (
                    "Run several tasks at once instead of one. Each entry takes "
                    "the same goal / context / subagent_type fields, and every "
                    "entry runs in parallel."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "goal": {"type": "string"},
                        "context": {"type": "string"},
                        "subagent_type": {"type": "string"},
                    },
                    "required": ["goal"],
                },
            },
        },
        "required": [],
    }

    def __init__(self, config: dict = None):
        self.config = config or {}
        self.cwd = self.config.get("cwd")

    def is_available(self) -> bool:
        """Follows the setting as it stands, not as it stood at startup, so
        switching sub agents off takes the tool away on the next turn rather
        than at the next restart."""
        from agent.subagent import SubagentSettings

        return SubagentSettings.from_config().enabled

    # --- what the model reads -------------------------------------------------

    @property
    def description(self) -> str:
        """Rebuilt on every read so a template added to the workspace is
        offered on the next turn, without a restart."""
        from agent.subagent import SubagentSettings, load_templates

        try:
            templates = load_templates(self.cwd)
            settings = SubagentSettings.from_config()
        except Exception as e:
            logger.debug(f"[SubagentTool] Falling back to static description: {e}")
            return _STATIC_DESCRIPTION

        listing = "\n".join(
            f"- {name}: {template.description}"
            for name, template in sorted(templates.items())
        )
        return (
            "Hand a self-contained task to a sub agent that runs in its own "
            "context and returns only its conclusion, keeping everything it "
            "reads or runs out of yours.\n\n"
            "Reach for it on substantial research, investigation or data "
            "gathering — one task, or several at once via `tasks` (up to "
            f"{settings.max_concurrent}) which run in parallel. Do simple work "
            "you can finish yourself directly instead.\n\n"
            "The sub agent starts with no history and cannot reach you or the "
            "user mid-task, so state the goal in full and put every path, "
            "identifier and constraint it needs into `context`; a vague goal "
            "comes back as a vague answer. Its reply is not shown to the user, "
            "so read it and say what matters in your own words.\n\n"
            "Available sub agent types:\n"
            f"{listing}"
        )

    # --- execution ------------------------------------------------------------

    def _collect_tasks(self, params: dict) -> List:
        from agent.subagent import SubagentTask

        raw_tasks = params.get("tasks")
        if isinstance(raw_tasks, list) and raw_tasks:
            tasks = []
            for entry in raw_tasks:
                if not isinstance(entry, dict):
                    continue
                goal = str(entry.get("goal") or "").strip()
                if not goal:
                    continue
                tasks.append(
                    SubagentTask(
                        goal=goal,
                        context=str(entry.get("context") or ""),
                        subagent_type=entry.get("subagent_type"),
                    )
                )
            return tasks

        goal = str(params.get("goal") or "").strip()
        if not goal:
            return []
        return [
            SubagentTask(
                goal=goal,
                context=str(params.get("context") or ""),
                subagent_type=params.get("subagent_type"),
            )
        ]

    def renders_own_cards(self, arguments: dict) -> bool:
        """True exactly when the tasks get cards of their own, which is the
        same condition `_SpawnView` uses. A lone sub agent keeps reporting
        under the spawn call's card, so that one has to stay."""
        return len(self._collect_tasks(arguments or {})) > 1

    def _spawn_view(self, tasks: List):
        """One spawn call, as the client sees it.

        A sub agent runs for minutes behind a single tool call. Left alone the
        client shows one spinner for the lot: no telling how many are running,
        which is still going, what any of them is doing, or what they found.
        This turns the spawn into entries the client already knows how to
        render, and relays the work happening inside each one.

        Several sub agents get a card each, since one spinner cannot stand for
        all of them. A lone sub agent reports under the spawn call itself,
        which already stands for exactly it.
        """
        return _SpawnView(self, tasks)

    def execute(self, params: dict) -> ToolResult:
        from agent.subagent import SubagentSettings, current_depth, load_templates, run_tasks

        settings = SubagentSettings.from_config()
        if not settings.enabled:
            return ToolResult.fail("Sub agents are disabled. Set subagent.enabled in config.json.")

        parent = getattr(self, "context", None)
        if parent is None:
            return ToolResult.fail("No parent agent available to spawn from.")

        depth = current_depth()
        if depth >= settings.max_depth:
            return ToolResult.fail(
                f"Already {depth} level(s) deep, and subagent.max_depth is "
                f"{settings.max_depth}. Do this task yourself instead of delegating it."
            )

        tasks = self._collect_tasks(params)
        if not tasks:
            return ToolResult.fail("Provide 'goal', or 'tasks' with at least one goal.")
        if len(tasks) > settings.max_concurrent:
            return ToolResult.fail(
                f"{len(tasks)} tasks requested but subagent.max_concurrent is "
                f"{settings.max_concurrent}. Send fewer, or split across turns."
            )

        templates = load_templates(parent.workspace_dir or self.cwd)
        unknown = sorted(
            {t.subagent_type for t in tasks if t.subagent_type and t.subagent_type not in templates}
        )
        if unknown:
            return ToolResult.fail(
                f"Unknown sub agent type(s): {', '.join(unknown)}. "
                f"Available: {', '.join(sorted(templates))}."
            )

        # Deliberately no progress message: the goal is already the call's
        # arguments, so restating it says nothing the client is not showing.
        # What it wants during those minutes is the steps below.
        logger.info(f"[SubagentTool] Running {len(tasks)} task(s) at depth {depth + 1}")

        view = self._spawn_view(tasks)
        results = run_tasks(
            parent, tasks, templates, settings,
            on_state=view.on_state, on_event=view.on_event,
            cancel_event=self.cancel_event,
        )
        for item in results:
            # A sub agent names its files in prose, if at all. Listing them
            # spares the parent from parsing them back out of the summary, and
            # is the only record once the run's events are gone.
            files = view.files_for(item.get("task_index"))
            if files:
                item["files"] = files

        payload = json.dumps({"results": results}, ensure_ascii=False)
        display = format_results(results)
        if all(r.get("status") not in ("completed", "cancelled") for r in results):
            # Every task failed or timed out: surfacing this as success would
            # let the parent report findings that do not exist.
            return ToolResult.fail(payload, display=display)
        return ToolResult.success(payload, display=display)
