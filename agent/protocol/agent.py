import json
import os
import re
import time
import threading

from common.log import logger


def _first_version(model_name: str):
    """Extract the leading numeric version from a model name for comparison.

    Returns a float so that e.g. gpt-5.6 / gpt-6 compare correctly against a
    threshold, and future bumps (gpt-7, gpt-10) keep matching instead of
    falling back to the conservative default. String comparison is avoided on
    purpose: lexically "gpt-10" < "gpt-5", which would misclassify new models.

    :return: the first version number as a float, or None when absent.
    """
    m = re.search(r'(\d+(?:\.\d+)?)', model_name or "")
    if not m:
        return None
    try:
        return float(m.group(1))
    except (TypeError, ValueError):
        return None


# Known model families: total context window (tokens) and, when the provider
# publishes a specific completion cap, its max output tokens. A None output
# means "no published cap" and the caller falls back to a window-proportional
# reserve. version_min gates a family by its leading version number so newer
# releases keep matching (e.g. any gpt >= 5 is 1M/128K) instead of regressing
# to the conservative default the moment a new model ships.
#
# (window, max_output) — max_output may be None.
_MODEL_SPECS = {
    # gpt-5.x / gpt-6 / future: 1M context, 128K max output.
    "gpt": {"version_min": 5.0, "window": 1000000, "max_output": 128000},
    # deepseek V4+: 1M context, 384K max output; legacy chat/reasoner: 64K.
    # full_cap_names lists version-less flagship names that should also get the
    # large window even though they carry no numeric version (e.g. deepseek-flash).
    "deepseek": {"version_min": 4.0, "window": 1000000, "max_output": 384000,
                 "fallback_window": 64000, "full_cap_names": ("deepseek-flash",)},
    # gemini: 1M context, 64K max output.
    "gemini": {"window": 1000000, "max_output": 64000},
    # claude: 200K context, 64K max output.
    "claude": {"window": 200000, "max_output": 64000},
    # GLM: only 5.3-flash ships a 1M window; older glm-5.x stays at 200K.
    "glm": {"prefix": "glm-5.3-flash", "window": 1000000, "max_output": None,
            "fallback_window": 200000},
    # Qwen: only 3.8-flash ships a 1M window; keep others conservative.
    "qwen": {"prefix": "qwen3.8-flash", "window": 1000000, "max_output": None,
             "fallback_window": 128000},
}


def resolve_family_spec(model_name: str):
    """Infer (context_window, max_output_tokens) for a model from the family
    table, or (None, None) when no family matches.

    Single source of truth for the built-in budgets: both the runtime budget
    resolver and the console's catalog editor (to show a model's inferred
    numbers) go through here, so a new family entry updates both at once.
    ``max_output`` may be None (no published cap)."""
    name = (model_name or "").lower()
    if not name:
        return None, None
    version = _first_version(name)
    for family, spec in _MODEL_SPECS.items():
        if family not in name:
            continue
        prefix = spec.get("prefix")
        version_min = spec.get("version_min")
        if prefix is not None:
            # Family where only a specific model gets the large window
            # (e.g. glm-5.3-flash); everything else uses the fallback.
            if name.startswith(prefix):
                return spec["window"], spec.get("max_output")
            return spec.get("fallback_window", 128000), None
        if name in spec.get("full_cap_names", ()):
            # Version-less flagship (e.g. deepseek-flash = V4.1): full window.
            return spec["window"], spec.get("max_output")
        if version_min is not None and (version is None or version < version_min):
            # Older release of a family that only bumped at version_min
            # (e.g. deepseek < v4): use its conservative fallback window.
            return spec.get("fallback_window", 128000), None
        return spec["window"], spec.get("max_output")
    return None, None
from agent.protocol.models import LLMModel
from agent.protocol.agent_stream import AgentStreamExecutor
from agent.protocol.result import AgentAction, AgentActionType, ToolResult
from agent.tools.base_tool import BaseTool, ToolStage, is_tool_available


class Agent:
    def __init__(self, system_prompt: str, description: str = "AI Agent", model: LLMModel = None,
                 tools=None, output_mode="print", max_steps=100, max_context_tokens=None,
                 context_reserve_tokens=None, memory_manager=None, name: str = None,
                 workspace_dir: str = None, skill_manager=None, enable_skills: bool = True,
                 runtime_info: dict = None, skip_context_files: bool = False):
        """
        Initialize the Agent with system prompt, model, description.

        :param system_prompt: The system prompt for the agent.
        :param description: A description of the agent.
        :param model: An instance of LLMModel to be used by the agent.
        :param tools: Optional list of tools for the agent to use.
        :param output_mode: Control how execution progress is displayed:
                           "print" for console output or "logger" for using logger
        :param max_steps: Maximum number of steps the agent can take (default: 100)
        :param max_context_tokens: Maximum tokens to keep in context (default: None, auto-calculated based on model)
        :param context_reserve_tokens: Reserve tokens for new requests (default: None, auto-calculated)
        :param memory_manager: Optional MemoryManager instance for memory operations
        :param name: [Deprecated] The name of the agent (no longer used in single-agent system)
        :param workspace_dir: Optional workspace directory for workspace-specific skills
        :param skill_manager: Optional SkillManager instance (will be created if None and enable_skills=True)
        :param enable_skills: Whether to enable skills support (default: True)
        :param runtime_info: Optional runtime info dict (with _get_current_time callable for dynamic time)
        :param skip_context_files: Skip AGENT.md / USER.md / RULE.md when building the
                           system prompt. Sub agents set this: they report to the
                           agent that spawned them rather than to the user, so the
                           persona is the parent's job, and inheriting it would
                           spend context on instructions about a conversation the
                           sub agent cannot see.
        """
        self.name = name or "Agent"
        self.system_prompt = system_prompt
        self.model: LLMModel = model  # Instance of LLMModel
        self.description = description
        self.tools: list = []
        self.max_steps = max_steps  # max tool-call steps, default 100
        self.max_context_tokens = max_context_tokens  # max tokens in context
        self.context_reserve_tokens = context_reserve_tokens  # reserve tokens for new requests
        self.captured_actions = []  # Initialize captured actions list
        self.output_mode = output_mode
        self.last_usage = None  # Store last API response usage info
        self.messages = []  # Unified message history for stream mode
        self.messages_lock = threading.Lock()  # Lock for thread-safe message operations
        self.memory_manager = memory_manager  # Memory manager for auto memory flush
        self.workspace_dir = workspace_dir  # Workspace directory (state root, e.g. ~/cow)
        # Optional per-session project directory that overrides the working
        # directory (bash cwd, relative file paths) while memory/skills stay
        # anchored to workspace_dir. None means "use workspace_dir".
        self.project_dir = None
        # How much this session may change (see agent.permission). None means
        # "follow the global setting", resolved at check time so a change to the
        # global default reaches sessions that never picked a mode themselves.
        self.permission_mode = None
        self.enable_skills = enable_skills  # Skills enabled flag
        self.runtime_info = runtime_info  # Runtime info for dynamic time update
        self.skip_context_files = skip_context_files
        # Optional extra instructions appended AFTER the rebuilt full system
        # prompt. Used by the self-evolution review agent to add its task brief
        # on top of the full context (tools, workspace, user preferences, time)
        # so it both follows the user's preferences and knows its evolution job.
        self.extra_system_suffix = None

        # Initialize skill manager
        self.skill_manager = None
        if enable_skills:
            if skill_manager:
                self.skill_manager = skill_manager
            else:
                # Auto-create skill manager
                try:
                    from agent.skills import build_skill_manager
                    self.skill_manager = build_skill_manager(workspace_dir=workspace_dir)
                    logger.debug(f"Initialized SkillManager with {len(self.skill_manager.skills)} skills")
                except Exception as e:
                    logger.warning(f"Failed to initialize SkillManager: {e}")

        if tools:
            for tool in tools:
                self.add_tool(tool)

    def add_tool(self, tool: BaseTool):
        """
        Add a tool to the agent.

        :param tool: The tool to add (either a tool instance or a tool name)
        """
        # If tool is already an instance, use it directly
        tool.model = self.model
        self.tools.append(tool)

    # Tools whose cwd defines the working directory. Memory and other tools
    # deliberately keep their own paths and are not retargeted here.
    _CWD_TOOLS = frozenset(
        {"read", "write", "edit", "bash", "search_files", "ls", "web_fetch", "send", "browser"}
    )

    def effective_cwd(self) -> str:
        """The working directory in force: the project override, else workspace."""
        return self.project_dir or self.workspace_dir or os.getcwd()

    def apply_project_dir(self, project_dir):
        """Point the working directory at ``project_dir`` (None resets to workspace).

        Retargets the cwd of file/shell tools so bash, read, write, etc. operate
        inside the project. Memory, skills and MCP keep pointing at the Agent's
        workspace because they resolve absolute paths of their own. The system
        prompt is rebuilt per turn via ``get_full_system_prompt`` and reads
        ``effective_cwd`` there, so no prompt refresh is needed here.
        """
        # Normalize: an empty or workspace-equal value means "no project".
        if project_dir:
            project_dir = os.path.realpath(os.path.expanduser(project_dir))
            if self.workspace_dir and project_dir == os.path.realpath(
                os.path.expanduser(self.workspace_dir)
            ):
                project_dir = None
        else:
            project_dir = None

        self.project_dir = project_dir
        cwd = self.effective_cwd()
        for tool in self.tools:
            name = getattr(tool, "name", None)
            if not (name in self._CWD_TOOLS or hasattr(tool, "cwd")):
                continue
            try:
                # Prefer set_cwd when a tool has one (bash re-renders its
                # description); otherwise just retarget the attribute.
                setter = getattr(tool, "set_cwd", None)
                if callable(setter):
                    setter(cwd)
                else:
                    tool.cwd = cwd
                if isinstance(getattr(tool, "config", None), dict):
                    tool.config["cwd"] = cwd
            except Exception:
                pass
        return self.project_dir

    def effective_permission_mode(self) -> str:
        """The permission mode in force: this session's, else the global default."""
        from agent.permission import global_mode, normalize_mode

        if self.permission_mode:
            return normalize_mode(self.permission_mode, global_mode())
        return global_mode()

    def apply_permission_mode(self, mode):
        """Set (or clear, with None) this session's permission mode.

        Takes effect on the next tool call: the executor resolves the mode per
        call, so a mid-conversation change applies without rebuilding the agent.
        The system prompt is rebuilt per turn and picks the new mode up there.
        """
        from agent.permission import normalize_mode

        self.permission_mode = normalize_mode(mode) if mode else None
        return self.permission_mode

    def write_roots(self) -> list:
        """Directories that stay writable under the workspace-write mode.

        The working directory is where the user's work belongs; the Agent's own
        state root has to stay writable regardless, or memory, skills and
        knowledge - which live there by design - would break in project mode.
        """
        roots = [self.effective_cwd()]
        if self.workspace_dir:
            roots.append(self.workspace_dir)
        return roots

    def get_skills_prompt(self, skill_filter=None) -> str:
        """
        Get the skills prompt to append to system prompt.

        :param skill_filter: Optional list of skill names to include
        :return: Formatted skills prompt or empty string
        """
        if not self.skill_manager:
            return ""

        try:
            return self.skill_manager.build_skills_prompt(skill_filter=skill_filter)
        except Exception as e:
            logger.warning(f"Failed to build skills prompt: {e}")
            return ""

    def get_full_system_prompt(self, skill_filter=None) -> str:
        """
        Build the complete system prompt from scratch every time.

        Re-reads AGENT.md / USER.md / RULE.md from disk, refreshes skills,
        tools, and runtime info so any change takes effect immediately.
        Falls back to the cached self.system_prompt on error.
        """
        try:
            from agent.prompt import load_context_files, PromptBuilder

            if self.skill_manager:
                self.skill_manager.refresh_skills()

            context_files = None
            if self.workspace_dir and not self.skip_context_files:
                context_files = load_context_files(self.workspace_dir)

            try:
                from common import i18n
                lang = i18n.get_language()
            except Exception:
                lang = "zh"
            builder = PromptBuilder(workspace_dir=self.workspace_dir or "", language=lang)
            full = builder.build(
                # Same list the model is offered this turn: describing a tool
                # in the prompt that is not in the schema invites it to call
                # something that is not there.
                tools=[tool for tool in self.tools if is_tool_available(tool)],
                context_files=context_files,
                skill_manager=self.skill_manager,
                memory_manager=self.memory_manager,
                runtime_info=self.runtime_info,
                project_dir=self.project_dir,
                permission_mode=self.effective_permission_mode(),
            )
            if self.extra_system_suffix:
                full = f"{full}\n\n{self.extra_system_suffix}"
            return full
        except Exception as e:
            logger.warning(f"Failed to rebuild system prompt, using cached version: {e}")
            if self.extra_system_suffix:
                return f"{self.system_prompt}\n\n{self.extra_system_suffix}"
            return self.system_prompt

    def refresh_skills(self):
        """Refresh the loaded skills."""
        if self.skill_manager:
            self.skill_manager.refresh_skills()
            logger.info(f"Refreshed skills: {len(self.skill_manager.skills)} skills loaded")

    def list_skills(self):
        """
        List all loaded skills.

        :return: List of skill entries or empty list
        """
        if not self.skill_manager:
            return []
        return self.skill_manager.list_skills()

    def _resolve_model_spec(self) -> tuple:
        """
        Resolve (context_window, max_output_tokens) for the current model.

        Order of precedence:
          1. the model's catalog entry (user-configured, always wins);
          2. the built-in family table (_MODEL_SPECS), gated by version so new
             releases keep matching instead of regressing to the default;
          3. a conservative default (128K window, no explicit output cap).

        max_output_tokens is None when no explicit cap is known — callers then
        fall back to a window-proportional reserve.

        :return: (context_window, max_output_tokens or None)
        """
        catalog_window = None
        catalog_output = None
        if self.model is not None and hasattr(self.model, 'catalog_model_meta'):
            try:
                meta = self.model.catalog_model_meta() or {}
                catalog_window = meta.get('context_window')
                catalog_output = meta.get('max_output_tokens')
            except Exception:
                pass

        window = None
        max_output = None
        if self.model and hasattr(self.model, 'model'):
            window, max_output = resolve_family_spec(self.model.model)

        # Catalog values override the family table (the user knows their model).
        if catalog_window:
            try:
                window = int(catalog_window)
            except (TypeError, ValueError):
                pass
        if catalog_output:
            try:
                max_output = int(catalog_output)
            except (TypeError, ValueError):
                pass

        if not window:
            window = 128000  # conservative default
        return window, max_output

    def _get_model_context_window(self) -> int:
        """
        Get the model's *total* context window size in tokens (input + output).

        This is the hard ceiling the provider enforces on prompt tokens plus
        the completion budget. Trimming must leave room for the completion (see
        `_get_output_reserve_tokens`), otherwise a full-window prompt plus the
        server-side default `max_tokens` overflows and the request 400s.

        :return: Context window size in tokens
        """
        window, _ = self._resolve_model_spec()
        return window

    def _get_output_reserve_tokens(self) -> int:
        """
        Tokens to hold back from the input budget so history is compacted before
        the prompt fills the whole window (compaction fires at ~80% of it).

        This is a compaction threshold, NOT the request's max_tokens: it is a
        fixed 20% of the window, giving an 80% input budget (in line with Claude
        Code / Cursor / Cline). It deliberately does NOT use the model's static
        max output tokens — coupling the two would drag the compaction line all
        over the place (e.g. DeepSeek V4's 384K cap would compact at ~62%, not
        80%). The actual completion cap sent to the provider is handled
        separately by the bot (see each bot's max_tokens default).
        """
        window = self._get_model_context_window()
        return int(window * 0.2)

    def _get_context_reserve_tokens(self) -> int:
        """
        Get the number of tokens to reserve for new requests.
        This prevents context overflow by keeping a buffer.

        :return: Number of tokens to reserve
        """
        if self.context_reserve_tokens is not None:
            return self.context_reserve_tokens

        # Reserve ~10% of context window, with min 10K and max 200K
        context_window = self._get_model_context_window()
        reserve = int(context_window * 0.1)
        return max(10000, min(200000, reserve))

    def _estimate_message_tokens(self, message: dict) -> int:
        """
        Estimate token count for a message.

        Uses chars/3 for Chinese-heavy content and chars/4 for ASCII-heavy content,
        plus per-block overhead for tool_use / tool_result structures.

        :param message: Message dict with 'role' and 'content'
        :return: Estimated token count
        """
        content = message.get('content', '')
        if isinstance(content, str):
            return max(1, self._estimate_text_tokens(content))
        elif isinstance(content, list):
            total_tokens = 0
            for part in content:
                if not isinstance(part, dict):
                    continue
                block_type = part.get('type', '')
                if block_type == 'text':
                    total_tokens += self._estimate_text_tokens(part.get('text', ''))
                elif block_type == 'image':
                    total_tokens += 1200
                elif block_type == 'tool_use':
                    # tool_use has id + name + input (JSON-encoded)
                    total_tokens += 50  # overhead for structure
                    input_data = part.get('input', {})
                    if isinstance(input_data, dict):
                        import json
                        input_str = json.dumps(input_data, ensure_ascii=False)
                        total_tokens += self._estimate_text_tokens(input_str)
                elif block_type == 'tool_result':
                    # tool_result has tool_use_id + content
                    total_tokens += 30  # overhead for structure
                    result_content = part.get('content', '')
                    if isinstance(result_content, str):
                        total_tokens += self._estimate_text_tokens(result_content)
                else:
                    # Unknown block type, estimate conservatively
                    total_tokens += 10
            return max(1, total_tokens)
        return 1

    @staticmethod
    def _estimate_text_tokens(text: str) -> int:
        """
        Estimate token count for a text string.

        Chinese / CJK characters typically use ~1.5 tokens each,
        while ASCII uses ~0.25 tokens per char (4 chars/token).
        We use a weighted average based on the character mix.

        :param text: Input text
        :return: Estimated token count
        """
        if not text:
            return 0
        # Count non-ASCII characters (CJK, emoji, etc.)
        non_ascii = sum(1 for c in text if ord(c) > 127)
        ascii_count = len(text) - non_ascii
        # CJK chars: ~1.5 tokens each; ASCII: ~0.25 tokens per char
        return int(non_ascii * 1.5 + ascii_count * 0.25) + 1

    def get_context_usage(self) -> dict:
        """Break the live context down into what is consuming it.

        Powers the context-usage chart on the UI's clear-context button, so it
        must stay cheap: it reads the already-assembled prompt and the in-memory
        message list, and never rebuilds either. Counts are the same heuristic
        estimates the trimmer budgets against (`_estimate_*`), not real
        tokenizer output — hence `estimated` in the payload.

        `used` may exceed `limit`: the trimmer budgets the system prompt and
        history but not the tool schemas, which still occupy the window.

        :return: Usage dict with a `breakdown` of system/tools/history/free.
        """
        # The cached prompt is what actually goes out (agent_stream passes
        # `self.system_prompt` straight to LLMRequest), so counting the cached
        # value is both correct and free. get_full_system_prompt() would re-read
        # AGENT.md and refresh skills — far too heavy for a hover.
        system_tokens = self._estimate_text_tokens(self.system_prompt or "")

        # The skills catalog is embedded in the system prompt (built by
        # _build_skills_section), but it is really a capability listing — the
        # menu of skills the agent can invoke — so the chart accounts for it
        # together with the tool schemas rather than under the persona/AGENT.md
        # "system" slice. Estimate it once and move it out of `system_tokens`
        # into `tools_tokens` below. With 50+ skills this is the dominant chunk,
        # so keeping it under "system" would badly misrepresent the breakdown.
        skills_tokens = 0
        try:
            skills_prompt = self.get_skills_prompt()
            if skills_prompt:
                skills_tokens = self._estimate_text_tokens(skills_prompt)
                # Don't let rounding/refresh drift drive the system slice
                # negative if the two prompt builds diverge slightly.
                system_tokens = max(0, system_tokens - skills_tokens)
        except Exception as e:
            logger.debug(f"[Agent] Skills token estimate skipped: {e}")

        # Approximates the executor's `_select_tools_for_injection()`, which is
        # only reachable mid-run; availability filtering matches the tool list
        # described in the prompt (see get_full_system_prompt).
        # NOTE: this counts every available tool's schema, so it is an UPPER
        # BOUND. When on-demand tool retrieval is on, `_select_tools_for_injection()`
        # may inject only a subset per turn, so the live tools slice can be
        # smaller than what the chart shows here.
        try:
            from agent.protocol.agent_stream import build_tools_schema

            schema = build_tools_schema([t for t in self.tools if is_tool_available(t)])
            # Guard the estimator's floor of 1 so "no tools" charts as nothing.
            tools_tokens = (
                self._estimate_text_tokens(json.dumps(schema, ensure_ascii=False))
                if schema else 0
            )
        except Exception as e:
            logger.debug(f"[Agent] Tool schema estimate skipped: {e}")
            tools_tokens = 0

        # Fold the skills catalog into the tools/skills slice.
        tools_tokens += skills_tokens

        history_tokens = sum(self._estimate_message_tokens(m) for m in self.messages)

        # Chart denominator = min(user budget, model window). This is a DISPLAY
        # ceiling only: it deliberately does NOT subtract the output reserve, so
        # the bar shows the real usable limit (like Cursor showing the full
        # window) rather than a reserve-adjusted number. Compaction still fires a
        # little earlier, at the reserve-adjusted budget in
        # AgentStreamExecutor._trim_messages — that logic is untouched, so "used"
        # naturally starts shrinking just before it reaches this line.
        context_window = self._get_model_context_window()
        limit = min(self.max_context_tokens, context_window) if self.max_context_tokens else context_window

        estimated_used = system_tokens + tools_tokens + history_tokens
        model_name = getattr(self.model, "model", None) if self.model else None

        # Prefer the provider's real prompt_tokens from the last turn when we
        # have it (populated by the stream executor via stream_options.
        # include_usage). It counts the exact input the model saw — system +
        # tools + history — so it is the accurate `used`. The per-slice
        # breakdown stays estimate-based (the API only reports a single total),
        # but we scale the slices so they sum to the real total, keeping the
        # chart both accurate overall and readable per slice.
        real_prompt_tokens = None
        last_usage = getattr(self, "last_usage", None)
        if isinstance(last_usage, dict):
            try:
                pt = int(last_usage.get("prompt_tokens") or 0)
                if pt > 0:
                    real_prompt_tokens = pt
            except (TypeError, ValueError):
                real_prompt_tokens = None

        # Staleness guard: last_usage describes the input of a PAST request. If
        # the history has since been trimmed/compacted (or grown with new
        # turns), that real prompt_tokens no longer matches what we'd send now,
        # so drop it and fall back to the live estimate. We compare the live
        # history estimate against the one captured alongside the usage; a
        # meaningful drift (>15%) means the history changed under it.
        if real_prompt_tokens is not None:
            captured_hist = last_usage.get("_est_history")
            if isinstance(captured_hist, (int, float)) and captured_hist > 0:
                drift = abs(history_tokens - captured_hist) / captured_hist
                if drift > 0.15:
                    real_prompt_tokens = None

        if real_prompt_tokens is not None:
            used = real_prompt_tokens
            estimated = False
            if estimated_used > 0:
                scale = real_prompt_tokens / estimated_used
                system_slice = round(system_tokens * scale)
                tools_slice = round(tools_tokens * scale)
                # Absorb rounding drift into history so slices sum to `used`.
                history_slice = max(0, used - system_slice - tools_slice)
            else:
                system_slice = tools_slice = 0
                history_slice = used
        else:
            used = estimated_used
            estimated = True
            system_slice, tools_slice, history_slice = (
                system_tokens, tools_tokens, history_tokens,
            )

        return {
            "available": True,
            "estimated": estimated,
            "model": model_name,
            "window": context_window,
            "limit": limit,
            "used": used,
            "messages": len(self.messages),
            "breakdown": {
                "system": system_slice,
                "tools": tools_slice,
                "history": history_slice,
                "free": max(0, limit - used),
            },
        }

    def _find_tool(self, tool_name: str):
        """Find and return a tool with the specified name"""
        for tool in self.tools:
            if tool.name == tool_name:
                # Only pre-process stage tools can be actively called
                if tool.stage == ToolStage.PRE_PROCESS:
                    tool.model = self.model
                    tool.context = self  # Set tool context
                    return tool
                else:
                    # If it's a post-process tool, return None to prevent direct calling
                    logger.warning(f"Tool {tool_name} is a post-process tool and cannot be called directly.")
                    return None
        return None

    # output function based on mode
    def output(self, message="", end="\n"):
        if self.output_mode == "print":
            print(message, end=end)
        elif message:
            logger.info(message)

    def _execute_post_process_tools(self):
        """Execute all post-process stage tools"""
        # Get all post-process stage tools
        post_process_tools = [tool for tool in self.tools if tool.stage == ToolStage.POST_PROCESS]

        # Execute each tool
        for tool in post_process_tools:
            # Set tool context
            tool.context = self

            # Record start time for execution timing
            start_time = time.time()

            # Execute tool (with empty parameters, tool will extract needed info from context)
            result = tool.execute({})

            # Calculate execution time
            execution_time = time.time() - start_time

            # Capture tool use for tracking
            self.capture_tool_use(
                tool_name=tool.name,
                input_params={},  # Post-process tools typically don't take parameters
                output=result.result,
                status=result.status,
                error_message=str(result.result) if result.status == "error" else None,
                execution_time=execution_time
            )

            # Log result
            if result.status == "success":
                # Print tool execution result in the desired format
                self.output(f"\n🛠️ {tool.name}: {json.dumps(result.result)}")
            else:
                # Print failure in print mode
                self.output(f"\n🛠️ {tool.name}: {json.dumps({'status': 'error', 'message': str(result.result)})}")

    def capture_tool_use(self, tool_name, input_params, output, status, thought=None, error_message=None,
                         execution_time=0.0):
        """
        Capture a tool use action.

        :param thought: thought content
        :param tool_name: Name of the tool used
        :param input_params: Parameters passed to the tool
        :param output: Output from the tool
        :param status: Status of the tool execution
        :param error_message: Error message if the tool execution failed
        :param execution_time: Time taken to execute the tool
        """
        tool_result = ToolResult(
            tool_name=tool_name,
            input_params=input_params,
            output=output,
            status=status,
            error_message=error_message,
            execution_time=execution_time
        )

        action = AgentAction(
            agent_id=self.id if hasattr(self, 'id') else str(id(self)),
            agent_name=self.name,
            action_type=AgentActionType.TOOL_USE,
            tool_result=tool_result,
            thought=thought
        )

        self.captured_actions.append(action)

        return action

    def run_stream(self, user_message: str, on_event=None, clear_history: bool = False,
                   skill_filter=None, cancel_event=None, steer_inbox=None,
                   allow_empty_response: bool = False) -> str:
        """
        Execute single agent task with streaming (based on tool-call)

        This method supports:
        - Streaming output
        - Multi-turn reasoning based on tool-call
        - Event callbacks
        - Persistent conversation history across calls
        - User-initiated cancellation via ``cancel_event``
        - Explicit active-turn guidance via ``steer_inbox``

        Args:
            user_message: User message
            on_event: Event callback function callback(event: dict)
                     event = {"type": str, "timestamp": float, "data": dict}
            clear_history: If True, clear conversation history before this call (default: False)
            skill_filter: Optional list of skill names to include in this run
            cancel_event: Optional threading.Event polled at agent checkpoints.
                When set, the loop exits at the next safe point, injects a
                "[Interrupted by user]" assistant note, and returns the
                partial response. ``messages`` stays in a valid state
                (tool_use/tool_result pairs preserved).
            steer_inbox: Optional SteerInbox drained at safe checkpoints. New
                instructions guide this run without entering the normal queue.
            allow_empty_response: If True, an empty answer is returned as-is
                instead of a fallback message. For runs nobody is waiting on
                (scheduled tasks), where sending nothing is a valid outcome.

        Returns:
            Final response text

        Example:
            # Multi-turn conversation with memory
            response1 = agent.run_stream("My name is Alice")
            response2 = agent.run_stream("What's my name?")  # Will remember Alice

            # Single-turn without memory
            response = agent.run_stream("Hello", clear_history=True)
        """
        # Clear history if requested
        if clear_history:
            with self.messages_lock:
                self.messages = []

        # Get model to use
        if not self.model:
            raise ValueError("No model available for agent")

        # Get full system prompt with skills
        full_system_prompt = self.get_full_system_prompt(skill_filter=skill_filter)

        # Create a copy of messages for this execution to avoid concurrent modification
        # Record the original length to track which messages are new
        with self.messages_lock:
            messages_copy = self.messages.copy()
            original_length = len(self.messages)

        # Get max_context_turns from config
        from config import conf
        max_context_turns = conf().get("agent_max_context_turns", 20)

        # Create stream executor with copied message history
        executor = AgentStreamExecutor(
            agent=self,
            model=self.model,
            system_prompt=full_system_prompt,
            tools=self.tools,
            max_turns=self.max_steps,
            on_event=on_event,
            messages=messages_copy,  # Pass copied message history
            max_context_turns=max_context_turns,
            cancel_event=cancel_event,
            steer_inbox=steer_inbox,
            allow_empty_response=allow_empty_response,
        )

        # Execute
        try:
            response = executor.run_stream(user_message)
        except Exception:
            # If executor cleared its messages (context overflow / message format error),
            # sync that back to the Agent's own message list so the next request
            # starts fresh instead of hitting the same overflow forever.
            if len(executor.messages) == 0:
                with self.messages_lock:
                    self.messages.clear()
                    logger.info("[Agent] Cleared Agent message history after executor recovery")
            raise

        # Sync executor's messages back to agent (thread-safe).
        # If the executor trimmed context, its message list is shorter than
        # original_length, so we must replace rather than append.
        with self.messages_lock:
            # Track messages added in this run (user query + all assistant/tool messages).
            # When context was trimmed, executor.messages is shorter than original_length,
            # so slicing at original_length yields an empty list and the assistant reply
            # would never be persisted. Instead, locate this run's user query (always the
            # first message of the last turn) by scanning from the tail.
            trimmed = len(executor.messages) < original_length
            if trimmed:
                new_start = original_length  # fallback
                for idx in range(len(executor.messages) - 1, -1, -1):
                    msg = executor.messages[idx]
                    if msg.get("role") != "user":
                        continue
                    content = msg.get("content", [])
                    is_user_query = False
                    if isinstance(content, list):
                        has_text = any(
                            isinstance(b, dict) and b.get("type") == "text"
                            for b in content
                        )
                        has_tool_result = any(
                            isinstance(b, dict) and b.get("type") == "tool_result"
                            for b in content
                        )
                        is_user_query = has_text and not has_tool_result
                    elif isinstance(content, str):
                        is_user_query = True
                    if is_user_query:
                        new_start = idx
                        break
                self._last_run_new_messages = list(executor.messages[new_start:])
            else:
                self._last_run_new_messages = list(executor.messages[original_length:])
            self.messages = list(executor.messages)

        # Store executor reference for agent_bridge to access files_to_send
        self.stream_executor = executor

        # Execute all post-process tools
        self._execute_post_process_tools()

        return response

    def clear_history(self):
        """Clear conversation history and captured actions"""
        self.messages = []
        self.captured_actions = []

    def compact_context(self, keep_recent_turns: int = 2) -> dict:
        """Manually compact the conversation history right now.

        Reuses the same turn-splitting and summary-injection logic as the
        automatic context trimming in AgentStreamExecutor (via shared helpers
        in message_utils), the only difference being that this summarizes
        synchronously and runs on demand regardless of token usage — so the
        /compact command frees context immediately and consistently.

        :param keep_recent_turns: How many most-recent turns to keep verbatim.
        :return: dict with keys: ok, reason, compacted_turns, before, after.
        """
        from agent.protocol.message_utils import (
            identify_complete_turns,
            build_compaction_summary_text,
            find_first_user_text_block,
            _extract_text_from_content,
        )

        with self.messages_lock:
            before = len(self.messages)
            turns = identify_complete_turns(self.messages)

            if len(turns) <= keep_recent_turns:
                return {
                    "ok": False,
                    "reason": "nothing_to_compact",
                    "compacted_turns": 0,
                    "before": before,
                    "after": before,
                }

            discarded_turns = turns[:-keep_recent_turns]
            kept_turns = turns[-keep_recent_turns:]
            discarded_messages = []
            for turn in discarded_turns:
                discarded_messages.extend(turn["messages"])

        # Summarize discarded turns synchronously so the injected note is ready
        # before we return. The SAME summary is reused for context injection and
        # daily-memory persistence — one LLM call serves both (mirrors the
        # context_summary_callback path used by automatic trimming, but sync).
        # Falls back to a plain-text digest when no LLM is available.
        summary = ""
        llm_summary = False
        flush_mgr = None
        if self.memory_manager:
            flush_mgr = getattr(self.memory_manager, "flush_manager", None)
        if flush_mgr:
            try:
                raw = flush_mgr._summarize_messages(discarded_messages, max_messages=0) or ""
                summary = flush_mgr._clean_summary_output(raw)
                llm_summary = bool(summary.strip())
            except Exception as e:
                logger.warning(f"[Agent] compact summarize failed: {e}")

        if not summary.strip():
            fragments = []
            for msg in discarded_messages:
                text = _extract_text_from_content(msg.get("content", ""))
                if text:
                    fragments.append(f"{msg.get('role', '?')}: {text[:200]}")
            summary = "\n".join(fragments[-20:])

        # Persist the same LLM summary to daily memory (no second LLM call).
        # Skip when we only have the plain-text fallback — it isn't worth
        # recording as long-term memory.
        if flush_mgr and llm_summary:
            try:
                user_id = getattr(self, "_current_user_id", None)
                flush_mgr.write_daily_summary(summary, user_id=user_id, reason="trim")
            except Exception as e:
                logger.debug(f"[Agent] compact write_daily_summary skipped: {e}")

        # Rebuild kept turns, injecting the summary into the first kept user
        # text block (same as auto-trim) to avoid two adjacent user messages
        # that would break strict user/assistant alternation on some providers.
        turn_count = len(discarded_turns)
        with self.messages_lock:
            new_messages = []
            for turn in kept_turns:
                new_messages.extend(turn["messages"])

            target_block = find_first_user_text_block(kept_turns)
            if target_block is not None:
                target_block["text"] = build_compaction_summary_text(
                    summary, turn_count, target_block.get("text", "")
                )
            else:
                # Fallback: no injectable target, prepend a standalone note.
                new_messages.insert(0, {
                    "role": "user",
                    "content": [{
                        "type": "text",
                        "text": build_compaction_summary_text(summary, turn_count, ""),
                    }],
                })

            self.messages = new_messages
            after = len(self.messages)

        # The last provider usage described the pre-compaction history, so it is
        # now stale. Clear it so the context-usage indicator estimates the
        # freshly compacted history until the next real turn reports usage.
        self.last_usage = None

        logger.info(
            f"[Agent] Manual compact: {turn_count} turns summarized, "
            f"{before} -> {after} messages"
        )
        return {
            "ok": True,
            "reason": "compacted",
            "compacted_turns": turn_count,
            "before": before,
            "after": after,
        }
