import json
import os
import time
import threading

from common.log import logger
from agent.protocol.models import LLMRequest, LLMModel
from agent.protocol.agent_stream import AgentStreamExecutor
from agent.protocol.result import AgentAction, AgentActionType, ToolResult, AgentResult
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
                    from agent.skills import SkillManager
                    custom_dir = os.path.join(workspace_dir, "skills") if workspace_dir else None
                    self.skill_manager = SkillManager(custom_dir=custom_dir)
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

    def _get_model_context_window(self) -> int:
        """
        Get the model's *total* context window size in tokens (input + output).
        Auto-detect based on model name.

        This is the hard ceiling the provider enforces on prompt tokens plus
        the completion budget. Trimming must leave room for the completion (see
        `_get_output_reserve_tokens`), otherwise a full-window prompt plus the
        server-side default `max_tokens` overflows and the request 400s.

        :return: Context window size in tokens
        """
        if self.model and hasattr(self.model, 'model'):
            model_name = self.model.model.lower()

            # Claude models - 200K context
            if 'claude' in model_name:
                return 200000

            # GPT-4 models
            elif 'gpt-4' in model_name:
                if 'turbo' in model_name or '128k' in model_name:
                    return 128000
                elif '32k' in model_name:
                    return 32000
                else:
                    return 8000

            # GPT-3.5
            elif 'gpt-3.5' in model_name:
                if '16k' in model_name:
                    return 16000
                else:
                    return 4000

            # DeepSeek: V4 family ships a 1M window; legacy chat/reasoner is 64K.
            elif 'deepseek' in model_name:
                if 'v4' in model_name:
                    return 1000000
                return 64000

            # Gemini models
            elif 'gemini' in model_name:
                if '2.0' in model_name or 'exp' in model_name:
                    return 2000000  # Gemini 2.0: 2M tokens
                else:
                    return 1000000  # Gemini 1.5: 1M tokens

        # Default conservative value
        return 128000

    def _get_output_reserve_tokens(self) -> int:
        """
        Tokens to hold back from the input budget for the model's completion.

        A model's context window is shared by the prompt and the reply. Providers
        (and proxies such as LinkAI) attach a large default `max_tokens` for
        agent-mode models — DeepSeek V4, for example, can be asked for up to 384K
        output tokens. If we let the trimmed prompt fill the whole window, prompt +
        that completion budget exceeds the window and the request is rejected with
        "maximum context length ... you requested N tokens", which then loops.

        Scale the reserve with the window so small models keep a modest buffer and
        large ones (V4's 1M) reserve enough for their oversized completion default,
        while never eating more than ~40% of the window.
        """
        context_window = self._get_model_context_window()
        # ~40% of the window, clamped to a sane floor/ceiling. 400K covers the
        # 384K completion default that large-window agent models request.
        reserve = int(context_window * 0.4)
        return max(8000, min(400000, reserve))

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
