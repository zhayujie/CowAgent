"""
CowCli plugin - Intercept cow/slash commands in chat messages.

Matches messages like:
  cow skill list
  cow install-browser
  /skill list
  /context clear
  /status
  /install-browser

Does NOT match:
  cow是什么
  cow真好用
  /开头但不是已知命令
"""

import os
import threading

import plugins
from plugins import Plugin, Event, EventContext, EventAction
from bridge.context import ContextType
from bridge.reply import Reply, ReplyType
from common.log import logger
from common.i18n import t as _t
from config import conf
from cli import __version__


# Known top-level subcommands that cow supports.
# "start" / "stop" / "restart" refer to daemon lifecycle on the host shell;
# in chat, "/cancel" aborts the in-flight agent run instead.
KNOWN_COMMANDS = {
    "help", "version", "status", "logs",
    "start", "stop", "restart",
    "cancel",
    "skill", "context", "config",
    "knowledge", "memory",
    "install-browser",
}

# Commands that can only run from the CLI (terminal), not in chat.
CLI_ONLY_COMMANDS = {"start", "stop", "restart"}

# Commands that can only run from chat (need access to in-process memory)
CHAT_ONLY_COMMANDS = set()  # context is allowed in both, but behaves differently

# Convenience shorthands for the slash form only. Values are *full command
# strings* so an alias can carry arguments (e.g. "cc" -> "context clear").
# These shorthands are deliberate and NOT derivable from prefix/typo rules:
#   - "c"  is a prefix of cancel/config/context (ambiguous) -> needs explicit map
#   - "cc" is a prefix of nothing and expands to a command + argument
#   - "s"  would otherwise be an ambiguous prefix (skill/start/status/stop)
# Users may override / extend these via config.json "command_aliases".
DEFAULT_ALIASES = {
    "c":   "cancel",
    "cc":  "context clear",
    "ctx": "context",
    "h":   "help",
    "s":   "status",
    "cfg": "config",
    "k":   "knowledge",
}


@plugins.register(
    name="cow_cli",
    desc="Handle cow/slash commands in chat messages",
    version="0.1.0",
    author="CowAgent",
    desire_priority=1000,
)
class CowCliPlugin(Plugin):

    def __init__(self):
        super().__init__()
        self.handlers[Event.ON_HANDLE_CONTEXT] = self.on_handle_context
        self.aliases = self._build_aliases()
        logger.debug("[CowCli] initialized")

    def reload(self):
        """Rebuild the alias table (e.g. after config changes)."""
        self.aliases = self._build_aliases()

    @staticmethod
    def _build_aliases() -> dict:
        """Merge DEFAULT_ALIASES with optional config.json ``command_aliases``.

        User-supplied entries (keys lowercased / stripped) override defaults.
        An alias whose target's first token is not a known command is dropped
        with a warning, so a bad alias can never create a dead command. An
        alias key that shadows a real command is kept but warned about — the
        exact-command stage in ``_resolve`` runs first, so the command wins.
        """
        merged = dict(DEFAULT_ALIASES)
        try:
            overrides = conf().get("command_aliases", {}) or {}
        except Exception as e:
            logger.warning(f"[CowCli] could not read command_aliases from config: {e}")
            overrides = {}
        if not isinstance(overrides, dict):
            logger.warning(f"[CowCli] command_aliases must be an object, got {type(overrides).__name__}; ignoring")
            overrides = {}
        for key, value in overrides.items():
            if not isinstance(key, str) or not isinstance(value, str):
                logger.warning(f"[CowCli] ignoring non-string alias entry: {key!r} -> {value!r}")
                continue
            k = key.strip().lower()
            if k:
                merged[k] = value.strip()

        valid = {}
        for key, value in merged.items():
            head = value.split(None, 1)[0].lower() if value.strip() else ""
            if head not in KNOWN_COMMANDS:
                logger.warning(f"[CowCli] dropping alias '/{key}' -> '{value}': unknown command '{head}'")
                continue
            if key in KNOWN_COMMANDS:
                logger.warning(f"[CowCli] alias '/{key}' shadows a real command; the command takes precedence")
            valid[key] = value
        return valid

    def on_handle_context(self, e_context: EventContext):
        if e_context["context"].type != ContextType.TEXT:
            return

        content = e_context["context"].content.strip()
        parsed = self._parse_command(content)
        if parsed is None:
            return

        token, user_args = parsed
        result = self._resolve(token, user_args)
        kind = result[0]

        if kind == "passthrough":
            # Not a command and not a near-typo: let the agent handle it.
            return

        if kind == "run":
            _, cmd, args = result
            logger.info(f"[CowCli] intercepted command: {cmd} {args}")
            reply_text = self._dispatch(cmd, args, e_context)
        elif kind == "ambiguous":
            reply_text = self._ambiguous_hint(token, result[1])
        else:  # "typo"
            reply_text = self._typo_hint(token, result[1])

        reply_text = self._harden_line_breaks(reply_text, e_context)
        e_context["reply"] = Reply(ReplyType.TEXT, reply_text)
        e_context.action = EventAction.BREAK_PASS

    def _parse_command(self, content: str):
        """
        Parse cow command from message text.

        Supported formats:
          cow <command> [args...]   e.g. "cow skill list"
          /<command> [args...]      e.g. "/skill list"

        Returns:
          - (command, args_string): when the message looks like a command.
            'command' may NOT be in KNOWN_COMMANDS; caller should validate.
          - None: when the message is not command-like at all.

        We deliberately return parsed-but-unknown for the slash form so the
        caller can offer a typo hint instead of silently passing the message
        through to the agent.
        """
        if content.startswith("/"):
            rest = content[1:].strip()
            if not rest:
                return None
            parts = rest.split(None, 1)
            cmd = parts[0].lower()
            args = parts[1] if len(parts) > 1 else ""
            return cmd, args

        if content.startswith("cow "):
            rest = content[4:].strip()
            if not rest:
                return None
            parts = rest.split(None, 1)
            cmd = parts[0].lower()
            if cmd not in KNOWN_COMMANDS:
                # 'cow xxx' that isn't a command — don't intercept (could be
                # natural language like "cow xxx 怎么样").
                return None
            args = parts[1] if len(parts) > 1 else ""
            return cmd, args

        return None

    @staticmethod
    def _suggest_command(cmd: str) -> str:
        """
        Return the closest known command if cmd is a likely typo, else "".
        Returns None to indicate "do not intercept" (when input is too far off).

        Heuristic: edit distance <= 1 (single insert/delete/substitute) when
        |cmd| >= 3, and the candidate shares the same first letter.
        """
        if not cmd:
            return ""
        if len(cmd) < 3:
            return None

        def edit_distance_le1(a: str, b: str) -> bool:
            if a == b:
                return True
            la, lb = len(a), len(b)
            if abs(la - lb) > 1:
                return False
            if la == lb:
                diffs = sum(1 for x, y in zip(a, b) if x != y)
                return diffs <= 1
            short, long_ = (a, b) if la < lb else (b, a)
            i = j = 0
            skipped = False
            while i < len(short) and j < len(long_):
                if short[i] != long_[j]:
                    if skipped:
                        return False
                    skipped = True
                    j += 1
                else:
                    i += 1
                    j += 1
            return True

        for known in KNOWN_COMMANDS:
            if known[0] == cmd[0] and edit_distance_le1(cmd, known):
                return known
        return None

    def _resolve(self, token: str, user_args: str):
        """Resolve a parsed slash token to an action.

        Precedence (first hit wins):
          1. exact command            -> ("run", cmd, args)
          2. alias (exact key)        -> expand to a full command string, merge args
          3. unique prefix            -> ("run", cmd, args)
          4. ambiguous prefix (>1)    -> ("ambiguous", sorted_candidates)
          5. typo (edit-distance <=1) -> ("typo", suggestion_or_None)
          6. no match                 -> ("passthrough",)

        Pure function of (token, user_args, KNOWN_COMMANDS, self.aliases) so it
        is trivially unit-testable. Note the `cow ` form never reaches stages
        2-5: `_parse_command` only returns known tokens for it, so it stays
        strict and alias/prefix matching applies to the `/` form only.
        """
        token = token.lower()

        # 1. exact command (a real command can never be shadowed by an alias)
        if token in KNOWN_COMMANDS:
            return ("run", token, user_args)

        # 2. alias -> full command string; merge alias args with user args.
        #    Alias expansion is applied at most once (no alias -> alias chains).
        if token in self.aliases:
            parts = self.aliases[token].split(None, 1)
            cmd = parts[0].lower()
            alias_args = parts[1] if len(parts) > 1 else ""
            merged = f"{alias_args} {user_args}".strip() if user_args else alias_args
            return ("run", cmd, merged)

        # 3 / 4. prefix match
        candidates = sorted(c for c in KNOWN_COMMANDS if c.startswith(token))
        if len(candidates) == 1:
            return ("run", candidates[0], user_args)
        if len(candidates) > 1:
            return ("ambiguous", candidates)

        # 5. typo (keeps its own len>=3 + edit-distance<=1 guards)
        suggestion = self._suggest_command(token)
        if suggestion is not None:
            return ("typo", suggestion)

        # 6. nothing matched
        return ("passthrough",)

    @staticmethod
    def _typo_hint(token: str, suggestion) -> str:
        hint = _t(f"未知命令: /{token}", f"Unknown command: /{token}")
        if suggestion:
            hint += _t(f"\n你是不是想输入 /{suggestion} ?", f"\nDid you mean /{suggestion} ?")
        hint += _t("\n发送 /help 查看全部命令。", "\nSend /help to see all commands.")
        return hint

    @staticmethod
    def _ambiguous_hint(token: str, candidates) -> str:
        options = " ".join(f"/{c}" for c in candidates)
        return _t(
            f"命令不明确: /{token}\n可能想输入: {options}\n发送 /help 查看全部命令。",
            f"Ambiguous command: /{token}\nDid you mean: {options}\nSend /help to see all commands.",
        )

    # ------------------------------------------------------------------
    # Command dispatch
    # ------------------------------------------------------------------

    def execute(self, query: str, session_id: str = "") -> str:
        """Execute a cow/slash command string without a channel context.

        Used by cloud on_chat to intercept commands before the agent runs.
        Returns None when *query* is not command-like at all (e.g. natural
        language). For slash-prefixed typos returns a hint string so the
        caller still short-circuits the agent round.
        """
        parsed = self._parse_command(query.strip())
        if parsed is None:
            return None
        token, user_args = parsed
        result = self._resolve(token, user_args)
        kind = result[0]
        if kind == "passthrough":
            return None
        if kind == "run":
            _, cmd, args = result
            return self._dispatch(cmd, args, e_context=None, session_id=session_id)
        if kind == "ambiguous":
            return self._ambiguous_hint(token, result[1])
        return self._typo_hint(token, result[1])  # "typo"

    def _dispatch(self, cmd: str, args: str, e_context: EventContext, session_id: str = "") -> str:
        if cmd in CLI_ONLY_COMMANDS:
            return _t(
                f"⚠️ `cow {cmd}` 只能在命令行终端中执行。\n请在终端运行: cow {cmd}",
                f"⚠️ `cow {cmd}` can only run in a terminal.\nRun it in your shell: cow {cmd}",
            )

        handler_attr = "_cmd_" + cmd.replace("-", "_")
        handler = getattr(self, handler_attr, None)
        if handler:
            try:
                return handler(args, e_context, session_id=session_id)
            except Exception as e:
                logger.error(f"[CowCli] command '{cmd}' failed: {e}")
                return _t(f"命令执行失败: {e}", f"Command failed: {e}")

        return _t(f"未知命令: {cmd}", f"Unknown command: {cmd}")

    # ------------------------------------------------------------------
    # help / version
    # ------------------------------------------------------------------

    def _cmd_help(self, args: str, e_context, **_) -> str:
        if _t("zh", "en") == "en":
            lines = [
                "📋 CowAgent Commands",
                "",
                "/help: Show this help",
                "/version: Show version",
                "/status: Show running status",
                "/cancel: Abort the running Agent task",
                "/logs [N]: Show the last N log lines (default 20)",
                "/context: Show current conversation context",
                "/context clear: Clear current conversation context",
                "/skill list: List installed skills",
                "/skill list --remote: Browse Skill Hub",
                "/skill search <keyword>: Search skills",
                "/skill install <name>: Install a skill",
                "/skill info <name>: Show skill details",
                "/config: Show current config",
                "/config <key>: Show a config item",
                "/config <key> <val>: Update a config item",
                "/memory status: Show memory index status",
                "/memory rebuild-index: Rebuild the vector index (required after switching embedding model)",
                "/memory dream [N]: Trigger memory distillation (last N days, default 3, max 30)",
                "/knowledge: Show knowledge base stats",
                "/knowledge list: Show knowledge base file tree",
                "/knowledge on|off: Enable/disable knowledge base",
                "",
                "💡 You can also use cow <command> instead of /<command>",
            ]
        else:
            lines = [
                "📋 CowAgent 命令列表",
                "",
                "/help: 显示此帮助",
                "/version: 查看版本",
                "/status: 查看运行状态",
                "/cancel: 中止当前正在运行的 Agent 任务",
                "/logs [N]: 查看最近N条日志 (默认20)",
                "/context: 查看当前对话上下文信息",
                "/context clear: 清除当前对话上下文",
                "/skill list: 查看已安装的技能",
                "/skill list --remote: 浏览技能广场",
                "/skill search <关键词>: 搜索技能",
                "/skill install <名称>: 安装技能",
                "/skill info <名称>: 查看技能详情",
                "/config: 查看当前配置",
                "/config <key>: 查看某项配置",
                "/config <key> <val>: 修改配置",
                "/memory status: 查看记忆索引状态",
                "/memory rebuild-index: 清空并重建向量索引 (切换 embedding 模型后必须执行)",
                "/memory dream [N]: 手动触发记忆蒸馏 (整理近N天, 默认3, 最多30)",
                "/knowledge: 查看知识库统计",
                "/knowledge list: 查看知识库文件树",
                "/knowledge on|off: 开启/关闭知识库",
                "",
                "💡 也可以用 cow <command> 代替 /<command>",
            ]
        return "\n".join(lines)

    def _cmd_version(self, args: str, e_context, **_) -> str:
        return f"CowAgent v{__version__}"

    # ------------------------------------------------------------------
    # cancel — abort the in-flight agent run for the current session.
    # Fallback handler; in practice chat_channel/web_channel intercept
    # /cancel earlier so it bypasses the per-session serial queue.
    # ------------------------------------------------------------------

    def _cmd_cancel(self, args: str, e_context: EventContext, session_id: str = "", **_) -> str:
        """Signal the running agent to halt at its next checkpoint."""
        from agent.protocol import get_cancel_registry

        target_session = self._get_session_id(e_context, fallback=session_id)
        registry = get_cancel_registry()

        # Prefer per-turn request_id (matches the key agent_bridge registered)
        cancelled = 0
        request_id = ""
        if e_context is not None:
            try:
                ctx = e_context["context"]
                request_id = ctx.kwargs.get("request_id") or ctx.get("request_id", "")
            except Exception:
                request_id = ""

        if request_id and registry.cancel_request(request_id):
            cancelled = 1

        # Fall back to session-wide cancel
        if cancelled == 0 and target_session:
            cancelled = registry.cancel_session(target_session)

        if cancelled <= 0:
            return _t("当前没有可中止的任务。", "Nothing to cancel.")

        return _t("🛑 已中止", "🛑 Cancelled")

    # ------------------------------------------------------------------
    # status
    # ------------------------------------------------------------------

    def _cmd_status(self, args: str, e_context: EventContext, session_id: str = "", **_) -> str:
        from config import conf

        cfg = conf()
        lines = [_t("📊 CowAgent 运行状态", "📊 CowAgent Status"), ""]

        lines.append(_t(f"  版本: v{__version__}", f"  Version: v{__version__}"))
        lines.append(_t(f"  进程: PID {os.getpid()}", f"  Process: PID {os.getpid()}"))

        channel = cfg.get("channel_type", "unknown")
        if isinstance(channel, list):
            channel = ", ".join(channel)
        lines.append(_t(f"  通道: {channel}", f"  Channel: {channel}"))

        model_name = cfg.get("model", "unknown")
        lines.append(_t(f"  模型: {model_name}", f"  Model: {model_name}"))

        mode = "Chat" if cfg.get("agent") is False else "Agent"
        lines.append(_t(f"  模式: {mode}", f"  Mode: {mode}"))

        from common import i18n
        lang_label = "中文" if i18n.get_language() == "zh" else "English"
        lines.append(_t(f"  语言: {lang_label}", f"  Language: {lang_label}"))

        session_id = self._get_session_id(e_context, fallback=session_id)
        agent = self._get_agent(session_id)
        if agent:
            lines.append("")
            with agent.messages_lock:
                msg_count = len(agent.messages)
            lines.append(_t(f"  会话消息数: {msg_count}", f"  Session messages: {msg_count}"))

            if agent.skill_manager:
                total = len(agent.skill_manager.skills)
                enabled = sum(
                    1 for v in agent.skill_manager.skills_config.values()
                    if v.get("enabled", True)
                )
                lines.append(_t(f"  已加载技能: {enabled}/{total}", f"  Loaded skills: {enabled}/{total}"))
        else:
            lines.append("")
            lines.append(_t("  Agent: 未初始化 (首次对话后自动创建)", "  Agent: not initialized (created on first chat)"))

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # logs
    # ------------------------------------------------------------------

    def _cmd_logs(self, args: str, e_context, **_) -> str:
        num_lines = 20
        if args.strip().isdigit():
            num_lines = min(int(args.strip()), 50)

        log_file = self._find_log_file()
        if not log_file:
            return _t("未找到日志文件", "No log file found")

        try:
            with open(log_file, "r", encoding="utf-8", errors="replace") as f:
                all_lines = f.readlines()
            tail = all_lines[-num_lines:]
            content = "".join(tail).strip()
            if not content:
                return _t("日志为空", "Log is empty")
            return _t(f"📄 最近 {len(tail)} 条日志:\n\n{content}", f"📄 Last {len(tail)} log lines:\n\n{content}")
        except Exception as e:
            return _t(f"读取日志失败: {e}", f"Failed to read log: {e}")

    def _find_log_file(self) -> str:
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        candidates = [
            os.path.join(project_root, "nohup.out"),
            os.path.join(project_root, "run.log"),
        ]
        import glob as glob_mod
        candidates.extend(sorted(glob_mod.glob(os.path.join(project_root, "logs", "*.log")), reverse=True))
        for f in candidates:
            if os.path.isfile(f) and os.path.getsize(f) > 0:
                return f
        return ""

    # ------------------------------------------------------------------
    # context
    # ------------------------------------------------------------------

    def _cmd_context(self, args: str, e_context: EventContext, session_id: str = "", **_) -> str:
        session_id = self._get_session_id(e_context, fallback=session_id)
        agent = self._get_agent(session_id)

        sub = args.strip().lower()
        if sub == "clear":
            return self._context_clear(agent, session_id)
        else:
            return self._context_info(agent, session_id)

    def _context_info(self, agent, session_id: str) -> str:
        if not agent:
            return _t("⚠️ Agent 未初始化，暂无上下文信息", "⚠️ Agent not initialized, no context yet")

        with agent.messages_lock:
            messages = agent.messages.copy()

        if not messages:
            return _t("当前对话上下文为空", "Current conversation context is empty")

        user_msgs = sum(1 for m in messages if m.get("role") == "user")
        assistant_msgs = sum(1 for m in messages if m.get("role") == "assistant")
        tool_msgs = sum(1 for m in messages if m.get("role") == "tool")

        total_chars = sum(len(str(m.get("content", ""))) for m in messages)

        if _t("zh", "en") == "en":
            lines = [
                "💬 Current Conversation Context",
                "",
                f"  Session: {session_id or 'default'}",
                f"  Total messages: {len(messages)}",
                f"  User messages: {user_msgs}",
                f"  Assistant replies: {assistant_msgs}",
                f"  Tool calls: {tool_msgs}",
                f"  Total content length: ~{total_chars} chars",
                "",
                "  Send /context clear to clear the conversation context",
            ]
        else:
            lines = [
                "💬 当前对话上下文",
                "",
                f"  会话: {session_id or 'default'}",
                f"  总消息数: {len(messages)}",
                f"  用户消息: {user_msgs}",
                f"  助手回复: {assistant_msgs}",
                f"  工具调用: {tool_msgs}",
                f"  内容总长度: ~{total_chars} 字符",
                "",
                "  发送 /context clear 可清除对话上下文",
            ]
        return "\n".join(lines)

    def _context_clear(self, agent, session_id: str) -> str:
        if not agent:
            return _t("⚠️ Agent 未初始化", "⚠️ Agent not initialized")

        with agent.messages_lock:
            count = len(agent.messages)
            agent.messages.clear()

        return _t(f"✅ 已清除当前对话上下文 ({count} 条消息)", f"✅ Conversation context cleared ({count} messages)")

    # ------------------------------------------------------------------
    # config
    # ------------------------------------------------------------------

    _CONFIG_WRITABLE = {
        "model",
        "agent_max_context_tokens",
        "agent_max_context_turns",
        "agent_max_steps",
        "knowledge",
        "enable_thinking",
    }

    _CONFIG_READABLE = _CONFIG_WRITABLE | {"channel_type"}

    def _cmd_config(self, args: str, e_context, **_) -> str:
        from config import conf, load_config
        import json as _json

        parts = args.strip().split(None, 1)
        if not parts:
            return self._config_show_all()

        key = parts[0].lower()
        if len(parts) == 1:
            return self._config_get(key)

        value_str = parts[1].strip()
        return self._config_set(key, value_str)

    def _config_show_all(self) -> str:
        from config import conf
        cfg = conf()
        lines = [_t("⚙️ 当前配置", "⚙️ Current Config"), ""]
        for key in sorted(self._CONFIG_READABLE):
            val = cfg.get(key, "")
            lines.append(f"  {key}: {val}")
        lines.append("")
        lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━")
        lines.append(_t("💡 /config <key>: 查看配置", "💡 /config <key>: Show a config item"))
        lines.append(_t("💡 /config <key> <val>: 修改配置", "💡 /config <key> <val>: Update a config item"))
        return "\n".join(lines)

    def _config_get(self, key: str) -> str:
        from config import conf
        if key not in self._CONFIG_READABLE:
            available = ", ".join(sorted(self._CONFIG_READABLE))
            return _t(
                f"不支持查看 '{key}'\n\n可查看的配置项: {available}",
                f"Cannot show '{key}'\n\nReadable config items: {available}",
            )
        val = conf().get(key, "")
        return f"⚙️ {key}: {val}"

    def _config_set(self, key: str, value_str: str) -> str:
        from config import conf, load_config, available_setting
        import json as _json

        if key not in self._CONFIG_WRITABLE:
            if key in self._CONFIG_READABLE:
                return _t(f"⚠️ '{key}' 为只读配置，不支持修改", f"⚠️ '{key}' is read-only and cannot be modified")
            available = ", ".join(sorted(self._CONFIG_WRITABLE))
            return _t(
                f"不支持修改 '{key}'\n\n可修改的配置项: {available}",
                f"Cannot modify '{key}'\n\nWritable config items: {available}",
            )

        old_val = conf().get(key, "")

        try:
            new_val = _json.loads(value_str)
        except (_json.JSONDecodeError, ValueError):
            if value_str.lower() == "true":
                new_val = True
            elif value_str.lower() == "false":
                new_val = False
            else:
                new_val = value_str

        updates = {key: new_val}
        old_bot_type = conf().get("bot_type", "")

        if key == "model" and old_bot_type:
            from common import const
            if old_bot_type not in (const.CUSTOM,):
                resolved = self._resolve_bot_type_for_model(str(new_val))
                if resolved:
                    updates["bot_type"] = resolved

        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        config_path = os.path.join(project_root, "config.json")
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                file_config = _json.load(f)
            file_config.update(updates)
            with open(config_path, "w", encoding="utf-8") as f:
                _json.dump(file_config, f, indent=4, ensure_ascii=False)
        except Exception as e:
            return _t(f"写入 config.json 失败: {e}", f"Failed to write config.json: {e}")

        # Sync updated values to environment variables so that load_config()
        # won't overwrite the new value with a stale env var (common in Docker).
        # Match env var keys case-insensitively (Docker compose typically uses
        # upper-case like MODEL, but lower-case is also possible).
        synced_envs = {}
        for k, v in updates.items():
            if k not in available_setting:
                continue
            str_val = str(v)
            k_lower = k.lower()
            for env_key in list(os.environ):
                if env_key.lower() == k_lower:
                    os.environ[env_key] = str_val
                    synced_envs[env_key] = str_val
        logger.info(f"[CowCli] config update: {updates}, synced envs: {synced_envs}")

        try:
            load_config()
        except Exception as e:
            logger.warning(f"[CowCli] config reload warning: {e}")

        result = _t(f"✅ 配置已更新\n\n  {key}: {old_val} → {new_val}", f"✅ Config updated\n\n  {key}: {old_val} → {new_val}")
        if "bot_type" in updates and updates["bot_type"] != old_bot_type:
            result += f"\n  bot_type: {old_bot_type} → {updates['bot_type']}"
        return result

    @staticmethod
    def _resolve_bot_type_for_model(model_name: str) -> str:
        """Resolve bot_type from model name, matching AgentBridge mapping."""
        from common import const
        _EXACT = {
            "wenxin": const.BAIDU, "wenxin-4": const.BAIDU,
            "xunfei": const.XUNFEI, const.QWEN: const.QWEN_DASHSCOPE,
            const.QIANFAN: const.QIANFAN,
            const.MODELSCOPE: const.MODELSCOPE,
            const.MOONSHOT: const.MOONSHOT,
            "moonshot-v1-8k": const.MOONSHOT, "moonshot-v1-32k": const.MOONSHOT,
            "moonshot-v1-128k": const.MOONSHOT,
        }
        _PREFIX = [
            ("qwen", const.QWEN_DASHSCOPE), ("qwq", const.QWEN_DASHSCOPE),
            ("qvq", const.QWEN_DASHSCOPE),
            ("gemini", const.GEMINI), ("glm", const.ZHIPU_AI),
            ("claude", const.CLAUDEAPI),
            ("moonshot", const.MOONSHOT), ("kimi", const.MOONSHOT),
            ("doubao", const.DOUBAO), ("deepseek", const.DEEPSEEK),
            ("ernie", const.QIANFAN),
        ]
        if not model_name:
            return const.OPENAI
        if model_name in _EXACT:
            return _EXACT[model_name]
        if model_name.lower().startswith("minimax") or model_name in ["abab6.5-chat"]:
            return const.MiniMax
        if model_name in [const.QWEN_TURBO, const.QWEN_PLUS, const.QWEN_MAX]:
            return const.QWEN_DASHSCOPE
        lowered_model = model_name.lower()
        for prefix, btype in _PREFIX:
            if lowered_model.startswith(prefix):
                return btype
        return const.OPENAI

    # ------------------------------------------------------------------
    # install-browser (shared logic with cow install-browser CLI)
    # ------------------------------------------------------------------

    @staticmethod
    def _send_install_progress(e_context, text: str) -> None:
        """Push a short status line to the chat channel (SSE: phase event, not done)."""
        if e_context is None:
            logger.info(f"[CowCli] install-browser: {text}")
            return
        try:
            channel = e_context["channel"]
            context = e_context["context"]
            if channel and context:
                r = Reply(ReplyType.TEXT, text)
                r.sse_phase = True
                channel.send(r, context)
        except Exception as e:
            logger.warning(f"[CowCli] install-browser progress send failed: {e}")

    def _cmd_install_browser(self, args: str, e_context, **_) -> str:
        from cli.commands.install import run_install_browser

        if args.strip():
            return _t(
                "用法: /install-browser\n\n"
                "无需参数，等同于终端执行 `cow install-browser`。\n"
                "安装过程可能持续数分钟；进度会以多条消息推送，pip 详细输出见服务日志。",
                "Usage: /install-browser\n\n"
                "No arguments needed; equivalent to running `cow install-browser` in a terminal.\n"
                "Installation may take a few minutes; progress is pushed as multiple messages, and detailed pip output goes to the service log.",
            )

        # Suppress detailed stream in chat; phases go through channel.send
        def _noop_stream(msg: str, fg=None):
            pass

        code = run_install_browser(
            stream=_noop_stream,
            on_phase=lambda m: self._send_install_progress(e_context, m),
        )
        if code != 0:
            return _t(
                "❌ 安装未成功结束，请查看上方分段提示或服务器日志；"
                "也可在终端执行 `cow install-browser`。",
                "❌ Installation did not finish successfully. Check the messages above or the server log; "
                "you can also run `cow install-browser` in a terminal.",
            )
        return _t(
            "✅ 安装流程已结束。请重启 CowAgent 后使用 browser 工具（进度见上方消息）。",
            "✅ Installation finished. Restart CowAgent to use the browser tool (see messages above for progress).",
        )

    # ------------------------------------------------------------------
    # skill
    # ------------------------------------------------------------------

    def _cmd_skill(self, args: str, e_context, **_) -> str:
        parts = args.strip().split(None, 1)
        sub = parts[0].lower() if parts else ""
        sub_args = parts[1].strip() if len(parts) > 1 else ""

        if sub == "list":
            return self._skill_list(sub_args)
        elif sub == "search":
            return self._skill_search(sub_args)
        elif sub == "install":
            return self._skill_install(sub_args, e_context)
        elif sub == "uninstall":
            return self._skill_uninstall(sub_args)
        elif sub == "info":
            return self._skill_info(sub_args)
        elif sub == "enable":
            return self._skill_set_enabled(sub_args, True)
        elif sub == "disable":
            return self._skill_set_enabled(sub_args, False)
        else:
            return _t(
                "用法: /skill <子命令>\n\n"
                "子命令:\n"
                "list [--remote]: 查看技能列表\n"
                "search <关键词>: 搜索技能\n"
                "install <名称>: 安装技能\n"
                "uninstall <名称>: 卸载技能\n"
                "info <名称>: 查看技能详情\n"
                "enable <名称>: 启用技能\n"
                "disable <名称>: 禁用技能",
                "Usage: /skill <subcommand>\n\n"
                "Subcommands:\n"
                "list [--remote]: List skills\n"
                "search <keyword>: Search skills\n"
                "install <name>: Install a skill\n"
                "uninstall <name>: Uninstall a skill\n"
                "info <name>: Show skill details\n"
                "enable <name>: Enable a skill\n"
                "disable <name>: Disable a skill",
            )

    def _refresh_skill_manager(self):
        """Re-scan skill directories so skills_config.json reflects disk state."""
        try:
            from bridge.bridge import Bridge
            bridge = Bridge()
            agent_bridge = bridge.get_agent_bridge()
            for agent in [agent_bridge.default_agent] + list(agent_bridge.agents.values()):
                if agent and hasattr(agent, 'skill_manager') and agent.skill_manager:
                    agent.skill_manager.refresh_skills()
                    break
        except Exception as e:
            logger.debug(f"[CowCli] skill refresh skipped: {e}")

    def _skill_list_local(self) -> str:
        from cli.utils import load_skills_config, get_skills_dir, get_builtin_skills_dir
        self._refresh_skill_manager()
        config = load_skills_config()

        if not config:
            skills_dir = get_skills_dir()
            builtin_dir = get_builtin_skills_dir()
            entries = []
            for d, source in [(builtin_dir, "builtin"), (skills_dir, "custom")]:
                if not os.path.isdir(d):
                    continue
                for name in sorted(os.listdir(d)):
                    skill_path = os.path.join(d, name)
                    if os.path.isdir(skill_path) and not name.startswith("."):
                        if os.path.exists(os.path.join(skill_path, "SKILL.md")):
                            entries.append({"name": name, "source": source, "enabled": True})
            if not entries:
                return _t(
                    "暂无已安装的技能\n\n💡 /skill list --remote: 浏览技能广场",
                    "No skills installed yet\n\n💡 /skill list --remote: Browse Skill Hub",
                )
            config = {e["name"]: e for e in entries}

        sorted_entries = sorted(config.values(), key=lambda e: e.get("name", ""))
        enabled_count = sum(1 for e in sorted_entries if e.get("enabled", True))

        lines = [_t(f"📦 已安装的技能 ({enabled_count}/{len(sorted_entries)})", f"📦 Installed Skills ({enabled_count}/{len(sorted_entries)})"), ""]
        for entry in sorted_entries:
            name = entry.get("name", "")
            enabled = entry.get("enabled", True)
            source = entry.get("source", "")
            icon = "✅" if enabled else "⏸️"
            display = entry.get("display_name", "") or name
            desc = entry.get("description", "")
            if len(desc) > 50:
                desc = desc[:47] + "…"
            line = f"{icon} {display}"
            if display != name:
                line += f" ({name})"
            if desc:
                line += f"\n   {desc}"
            if source:
                line += _t(f"\n   来源: {source}", f"\n   Source: {source}")
            lines.append(line)
            lines.append("")

        lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━")
        lines.append(_t("💡 /skill list --remote: 浏览技能广场", "💡 /skill list --remote: Browse Skill Hub"))
        lines.append(_t("💡 /skill info <名称>: 查看详情", "💡 /skill info <name>: Show details"))
        return "\n".join(lines)

    def _skill_list(self, args: str) -> str:
        parts = args.strip().split()
        if "--remote" in parts or "-r" in parts:
            page = 1
            for i, p in enumerate(parts):
                if p == "--page" and i + 1 < len(parts) and parts[i + 1].isdigit():
                    page = max(1, int(parts[i + 1]))
            return self._skill_list_remote(page=page)
        return self._skill_list_local()

    _REMOTE_PAGE_SIZE = 10

    def _skill_list_remote(self, page: int = 1) -> str:
        import requests
        from cli.utils import SKILL_HUB_API, load_skills_config
        page_size = self._REMOTE_PAGE_SIZE
        try:
            resp = requests.get(
                f"{SKILL_HUB_API}/skills",
                params={"page": page, "limit": page_size},
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
            skills = data.get("skills", [])
            total = data.get("total", len(skills))
        except Exception as e:
            return _t(f"获取技能广场失败: {e}", f"Failed to fetch Skill Hub: {e}")

        if not skills and page == 1:
            return _t("技能广场暂无可用技能", "No skills available on Skill Hub")

        total_pages = max(1, (total + page_size - 1) // page_size)
        page = min(page, total_pages)
        installed = set(load_skills_config().keys())

        lines = [_t("🌐 技能广场", "🌐 Skill Hub"), ""]
        for s in skills:
            name = s.get("name", "")
            display = s.get("display_name", "") or name
            desc = s.get("description", "")
            if len(desc) > 50:
                desc = desc[:47] + "…"
            badge = _t(" [已安装]", " [installed]") if name in installed else ""
            lines.append(f"📌 {display}{badge}")
            lines.append(_t(f"   名称: {name}", f"   Name: {name}"))
            if desc:
                lines.append(f"   {desc}")
            lines.append("")

        lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━")
        lines.append(_t(f"📄 第 {page}/{total_pages} 页", f"📄 Page {page}/{total_pages}"))
        if page < total_pages:
            lines.append(_t(f"💡 /skill list --remote --page {page + 1}: 下一页", f"💡 /skill list --remote --page {page + 1}: Next page"))
        if page > 1:
            lines.append(_t(f"💡 /skill list --remote --page {page - 1}: 上一页", f"💡 /skill list --remote --page {page - 1}: Previous page"))
        lines.append(_t("💡 /skill install <名称>: 安装技能", "💡 /skill install <name>: Install a skill"))
        lines.append(_t("💡 /skill search <关键词>: 搜索技能", "💡 /skill search <keyword>: Search skills"))
        lines.append(_t("🌐 https://skills.cowagent.ai  在线浏览全部技能", "🌐 https://skills.cowagent.ai  Browse all skills online"))
        return "\n".join(lines)

    def _skill_search(self, query: str) -> str:
        if not query:
            return _t("请指定搜索关键词: /skill search <关键词>", "Please specify a search keyword: /skill search <keyword>")

        import requests
        from cli.utils import SKILL_HUB_API, load_skills_config
        try:
            resp = requests.get(f"{SKILL_HUB_API}/skills/search", params={"q": query}, timeout=10)
            resp.raise_for_status()
            skills = resp.json().get("skills", [])
        except Exception as e:
            return _t(f"搜索失败: {e}", f"Search failed: {e}")

        if not skills:
            return _t(f"未找到与「{query}」相关的技能", f"No skills found for \"{query}\"")

        installed = set(load_skills_config().keys())
        lines = [_t(f"🔍 搜索「{query}」({len(skills)} 个结果)", f"🔍 Search \"{query}\" ({len(skills)} results)"), ""]
        for s in skills:
            name = s.get("name", "")
            display = s.get("display_name", "") or name
            desc = s.get("description", "")
            if len(desc) > 50:
                desc = desc[:47] + "…"
            badge = _t(" [已安装]", " [installed]") if name in installed else ""
            lines.append(f"📌 {display}{badge}")
            lines.append(_t(f"   名称: {name}", f"   Name: {name}"))
            if desc:
                lines.append(f"   {desc}")
            lines.append("")

        lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━")
        lines.append(_t("💡 /skill install <名称>: 安装技能", "💡 /skill install <name>: Install a skill"))
        return "\n".join(lines)

    _INSTALL_TIMEOUT = 60

    def _skill_install(self, name: str, e_context: EventContext) -> str:
        if not name:
            return _t("请指定要安装的技能: /skill install <名称>", "Please specify a skill to install: /skill install <name>")

        from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
        from cli.commands.skill import install_skill

        try:
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(install_skill, name)
                result = future.result(timeout=self._INSTALL_TIMEOUT)

            if result.error:
                return _t(f"安装失败: {result.error}", f"Install failed: {result.error}")

            if not result.installed:
                return "\n".join(result.messages) if result.messages else _t("未找到可安装的技能", "No installable skill found")

            return self._format_install_result(result)
        except FuturesTimeout:
            return _t("安装超时，请稍后重试或检查网络连接", "Install timed out. Please retry later or check your network connection.")
        except Exception as e:
            return _t(f"安装失败: {e}", f"Install failed: {e}")

    @staticmethod
    def _format_install_result(result) -> str:
        """Format InstallResult into a chat-friendly message."""
        from cli.commands.skill import _read_skill_description
        from cli.utils import get_skills_dir, load_skills_config
        skills_dir = get_skills_dir()
        config = load_skills_config()

        lines = []
        for skill_name in result.installed:
            desc = _read_skill_description(os.path.join(skills_dir, skill_name))
            display = config.get(skill_name, {}).get("display_name", "")
            lines.append(_t(f"✅ 技能安装成功：{skill_name}", f"✅ Skill installed: {skill_name}"))
            if display and display != skill_name:
                lines.append(_t(f"   名称：{display}", f"   Name: {display}"))
            if desc:
                lines.append(_t(f"   描述：{desc}", f"   Description: {desc}"))

        if len(result.installed) > 1:
            lines.append(_t(f"\n共安装 {len(result.installed)} 个技能", f"\nInstalled {len(result.installed)} skills"))

        return "\n".join(lines)

    def _skill_uninstall(self, name: str) -> str:
        if not name:
            return _t("请指定要卸载的技能: /skill uninstall <名称>", "Please specify a skill to uninstall: /skill uninstall <name>")

        import shutil
        import json
        from cli.utils import get_skills_dir

        skills_dir = get_skills_dir()
        skill_dir = os.path.join(skills_dir, name)

        if not os.path.exists(skill_dir):
            skill_dir = self._resolve_skill_dir(name, skills_dir)

        if not skill_dir:
            return _t(f"技能 '{name}' 未安装", f"Skill '{name}' is not installed")

        shutil.rmtree(skill_dir)

        config_path = os.path.join(skills_dir, "skills_config.json")
        if os.path.exists(config_path):
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    config = json.load(f)
                config.pop(name, None)
                with open(config_path, "w", encoding="utf-8") as f:
                    json.dump(config, f, indent=4, ensure_ascii=False)
            except Exception:
                pass

        return _t(f"✅ 技能 '{name}' 已卸载", f"✅ Skill '{name}' uninstalled")

    @staticmethod
    def _resolve_skill_dir(name: str, skills_dir: str):
        """Find actual directory for a skill whose folder name may differ from its config name."""
        if not os.path.isdir(skills_dir):
            return None
        for entry in os.listdir(skills_dir):
            entry_path = os.path.join(skills_dir, entry)
            if not os.path.isdir(entry_path) or entry.startswith("."):
                continue
            if entry == name or entry.startswith(name + "-") or entry.endswith("-" + name):
                skill_md = os.path.join(entry_path, "SKILL.md")
                if os.path.exists(skill_md):
                    return entry_path
        return None

    @staticmethod
    def _strip_frontmatter(content: str):
        """Strip YAML frontmatter and return (metadata_dict, body)."""
        if not content.startswith("---"):
            return {}, content
        end = content.find("\n---", 3)
        if end == -1:
            return {}, content
        fm_text = content[3:end].strip()
        body = content[end + 4:].lstrip("\n")
        meta = {}
        for line in fm_text.split("\n"):
            if ":" in line:
                key, _, val = line.partition(":")
                meta[key.strip()] = val.strip().strip('"').strip("'")
        return meta, body

    def _skill_info(self, name: str) -> str:
        if not name:
            return _t("请指定技能名称: /skill info <名称>", "Please specify a skill name: /skill info <name>")

        from cli.utils import get_skills_dir, get_builtin_skills_dir

        skills_dir = get_skills_dir()
        builtin_dir = get_builtin_skills_dir()

        skill_dir = None
        source = None
        for d, src in [(skills_dir, "custom"), (builtin_dir, "builtin")]:
            candidate = os.path.join(d, name)
            if os.path.isdir(candidate):
                skill_dir = candidate
                source = src
                break

        if not skill_dir:
            resolved = self._resolve_skill_dir(name, skills_dir)
            if resolved:
                skill_dir = resolved
                source = "custom"

        if not skill_dir:
            return _t(f"技能 '{name}' 未找到", f"Skill '{name}' not found")

        skill_md = os.path.join(skill_dir, "SKILL.md")
        if not os.path.exists(skill_md):
            return _t(f"技能 '{name}' 没有 SKILL.md 文件", f"Skill '{name}' has no SKILL.md file")

        with open(skill_md, "r", encoding="utf-8") as f:
            content = f.read()

        meta, body = self._strip_frontmatter(content)

        header_lines = [_t(f"📖 技能: {name} [{source}]", f"📖 Skill: {name} [{source}]"), ""]
        desc = meta.get("description", "")
        if desc:
            header_lines.append(f"  {desc}")
            header_lines.append("")

        lines = body.split("\n")
        preview = "\n".join(lines[:30])
        result = "\n".join(header_lines) + preview
        if len(lines) > 30:
            result += f"\n\n... ({len(lines) - 30} more lines)"
        return result

    def _skill_set_enabled(self, name: str, enabled: bool) -> str:
        if not name:
            return _t(
                f"请指定技能名称: /skill {'enable' if enabled else 'disable'} <名称>",
                f"Please specify a skill name: /skill {'enable' if enabled else 'disable'} <name>",
            )

        import json
        from cli.utils import get_skills_dir

        skills_dir = get_skills_dir()
        config_path = os.path.join(skills_dir, "skills_config.json")

        if not os.path.exists(config_path):
            return _t("技能配置文件不存在", "Skills config file not found")

        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
        except Exception as e:
            return _t(f"读取配置失败: {e}", f"Failed to read config: {e}")

        if name not in config:
            return _t(f"技能 '{name}' 未在配置中找到", f"Skill '{name}' not found in config")

        config[name]["enabled"] = enabled
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=4, ensure_ascii=False)

        icon = "✅" if enabled else "⬚"
        if enabled:
            return _t(f"{icon} 技能 '{name}' 已启用", f"{icon} Skill '{name}' enabled")
        return _t(f"{icon} 技能 '{name}' 已禁用", f"{icon} Skill '{name}' disabled")

    # ------------------------------------------------------------------
    # memory
    # ------------------------------------------------------------------

    def _cmd_memory(self, args: str, e_context, session_id: str = "", **_) -> str:
        parts = args.strip().split()
        sub = parts[0].lower() if parts else ""

        if sub == "dream":
            days = 3
            if len(parts) > 1 and parts[1].isdigit():
                days = max(1, min(int(parts[1]), 30))
            return self._memory_dream(days, e_context, session_id)
        elif sub in ("rebuild-index", "rebuild_index", "rebuild"):
            return self._memory_rebuild_index(e_context, session_id)
        elif sub in ("status", "info", ""):
            if sub == "":
                return self._memory_help()
            return self._memory_status()
        else:
            return self._memory_help()

    @staticmethod
    def _memory_help() -> str:
        return _t(
            "🧠 记忆管理\n\n"
            "用法: /memory <子命令>\n\n"
            "子命令:\n"
            "status: 查看索引状态 (provider / model / dim / chunks)\n"
            "rebuild-index: 清空并重建向量索引 (切换 embedding 模型后必须执行)\n"
            "dream [N]: 手动触发记忆蒸馏 (整理近N天, 默认3, 最多30)",
            "🧠 Memory Management\n\n"
            "Usage: /memory <subcommand>\n\n"
            "Subcommands:\n"
            "status: Show index status (provider / model / dim / chunks)\n"
            "rebuild-index: Rebuild the vector index (required after switching embedding model)\n"
            "dream [N]: Trigger memory distillation (last N days, default 3, max 30)",
        )

    def _memory_dream(self, days: int, e_context, session_id: str) -> str:
        session_id = self._get_session_id(e_context, fallback=session_id)
        agent = self._get_agent(session_id)

        flush_mgr = None
        if agent and agent.memory_manager:
            flush_mgr = agent.memory_manager.flush_manager

        if not flush_mgr:
            try:
                flush_mgr = self._create_standalone_flush_manager()
            except Exception as e:
                return _t(f"⚠️ 无法初始化记忆蒸馏: {e}", f"⚠️ Failed to initialize memory distillation: {e}")

        if not flush_mgr.llm_model:
            return _t("⚠️ 未配置 LLM 模型，无法执行记忆蒸馏", "⚠️ No LLM model configured, cannot run memory distillation")

        # SaaS (e_context is None): run synchronously, return full result
        if e_context is None:
            return self._memory_dream_sync(flush_mgr, days)

        # Local channels: run in background, notify via channel.send()
        is_web = self._is_web_channel(e_context)

        def _run():
            try:
                result = flush_mgr.deep_dream(lookback_days=days, force=True)
                if result:
                    self._notify(e_context, self._build_dream_result(flush_mgr, is_web))
                else:
                    self._notify(e_context, _t("💤 记忆蒸馏跳过 — 没有新的记忆内容需要整理", "💤 Memory distillation skipped — no new memories to process"))
            except Exception as e:
                logger.warning(f"[CowCli] /memory dream failed: {e}")
                self._notify(e_context, _t(f"❌ 记忆蒸馏失败: {e}", f"❌ Memory distillation failed: {e}"))

        threading.Thread(target=_run, daemon=True).start()
        return _t(
            f"🌙 记忆蒸馏已启动 (整理近 {days} 天的记忆)\n\n整理在后台执行，完成后会通知你。",
            f"🌙 Memory distillation started (processing the last {days} days)\n\nRunning in the background; you'll be notified when it's done.",
        )

    def _memory_dream_sync(self, flush_mgr, days: int) -> str:
        """Run deep dream synchronously and return the full result."""
        try:
            result = flush_mgr.deep_dream(lookback_days=days, force=True)
            if result:
                return self._build_dream_result(flush_mgr, is_web=True)
            return _t("💤 记忆蒸馏跳过 — 没有新的记忆内容需要整理", "💤 Memory distillation skipped — no new memories to process")
        except Exception as e:
            logger.warning(f"[CowCli] /memory dream sync failed: {e}")
            return _t(f"❌ 记忆蒸馏失败: {e}", f"❌ Memory distillation failed: {e}")

    @staticmethod
    def _resolve_active_embedding():
        """
        Resolve (provider_label, model, dim) from the LATEST config, not the
        possibly-stale provider instance cached on a running agent. Used by
        /memory status and rebuild-index hints so they reflect what a rebuild
        will actually run as after the user changes embedding_provider.
        Returns (label, model, dim) where any field may be None when unknown.
        """
        from agent.memory.embedding import EMBEDDING_VENDORS
        from config import conf

        provider_key = (conf().get("embedding_provider") or "").strip().lower()
        cfg_model = (conf().get("embedding_model") or "").strip()
        try:
            cfg_dim = int(conf().get("embedding_dimensions") or 0)
        except (TypeError, ValueError):
            cfg_dim = 0

        if not provider_key:
            # Legacy auto path: openai -> linkai, both default to text-embedding-3-small (1536).
            if (conf().get("open_ai_api_key") or "").strip():
                return "openai (legacy)", "text-embedding-3-small", 1536
            if (conf().get("linkai_api_key") or "").strip():
                return "linkai (legacy)", "text-embedding-3-small", 1536
            return "(legacy)", None, None

        meta = EMBEDDING_VENDORS.get(provider_key) or {}
        model = cfg_model or meta.get("default_model")
        dim = cfg_dim if cfg_dim > 0 else meta.get("default_dimensions")
        return provider_key, model, dim

    def _memory_status(self) -> str:
        """Show current memory index status."""
        from agent.memory.embedding import detect_index_dim
        from config import conf

        agent = self._get_agent("")
        memory_manager = agent.memory_manager if agent else None

        lines = [_t("🧠 记忆索引状态", "🧠 Memory Index Status"), ""]
        if not memory_manager:
            lines.append(_t("  ⚠️ Agent 尚未初始化，先发一条普通消息再试", "  ⚠️ Agent not initialized yet, send a normal message first"))
            return "\n".join(lines)

        stats = memory_manager.storage.get_stats()
        db_path = memory_manager.config.get_db_path()
        embedded = stats.get('embedded', 0)
        chunks = stats.get('chunks', 0)
        lines.append(f"  索引DB  : {db_path}")
        lines.append(f"  Files   : {stats.get('files', 0)}")
        lines.append(f"  Chunks  : {chunks} (embedded: {embedded})")
        lines.append("")

        # Resolve from the latest config so users see what /memory rebuild-index
        # will actually run as — not what the cached agent was initialized with.
        cfg_provider, cfg_model, cfg_dim = self._resolve_active_embedding()
        provider_obj = memory_manager.embedding_provider
        if cfg_model:
            lines.append(f"  Provider : {cfg_provider}")
            lines.append(f"  Model    : {cfg_model}")
            lines.append(f"  Dim      : {cfg_dim if cfg_dim else '?'}")
        else:
            lines.append(_t("  Provider : (未初始化, keyword-only)", "  Provider : (not initialized, keyword-only)"))

        # Health hints — only shown when the user has explicitly opted into
        # vector search via `embedding_provider`. Legacy users (no explicit
        # provider) are running in a "best-effort vectors" mode by design;
        # nagging them about missing/mismatched vectors would be noise.
        warnings = []
        explicitly_opted_in = (conf().get("embedding_provider") or "").strip() != ""
        if explicitly_opted_in and provider_obj is not None:
            if chunks > 0 and embedded < chunks:
                missing = chunks - embedded
                warnings.append(_t(
                    f"  ⚠️ {missing}/{chunks} 个 chunk 没有向量；运行 /memory rebuild-index 后所有记忆才会被向量化检索",
                    f"  ⚠️ {missing}/{chunks} chunks have no vectors; run /memory rebuild-index to enable vector search for all memories",
                ))

            index_dim = detect_index_dim(memory_manager.storage)
            if index_dim is not None and cfg_dim and index_dim != cfg_dim:
                warnings.append(_t(
                    f"  ⚠️ 索引中存量向量为 {index_dim} 维，与当前配置 {cfg_dim} 维不一致；运行 /memory rebuild-index 重建后向量检索才会生效",
                    f"  ⚠️ Existing vectors are {index_dim}-dim, mismatching the current {cfg_dim}-dim config; run /memory rebuild-index to make vector search work",
                ))

        if warnings:
            lines.append("")
            lines.extend(warnings)

        return "\n".join(lines)

    def _memory_rebuild_index(self, e_context, session_id: str) -> str:
        """Rebuild the vector index using the current agent's memory_manager."""
        session_id = self._get_session_id(e_context, fallback=session_id)
        agent = self._get_agent(session_id)
        if not agent or not agent.memory_manager:
            return _t(
                "⚠️ Agent 尚未初始化，无法重建索引。\n"
                "请先发送一条普通消息触发 Agent 启动后再试。",
                "⚠️ Agent not initialized, cannot rebuild the index.\n"
                "Send a normal message first to start the Agent, then try again.",
            )

        memory_manager = agent.memory_manager

        # Rebuild against the LATEST config: build a fresh provider from
        # config.json and swap it onto memory_manager. The agent's
        # conversation_history and other state are untouched.
        try:
            from bridge.agent_initializer import AgentInitializer
            fresh_provider = AgentInitializer(bridge=None, agent_bridge=None) \
                ._init_embedding_provider(memory_manager.config, session_id=session_id)
        except Exception as e:
            logger.exception("[CowCli] /memory rebuild-index: build provider failed")
            return _t(f"⚠️ 无法根据当前配置构造 embedding provider: {e}", f"⚠️ Failed to build embedding provider from current config: {e}")

        if fresh_provider is None:
            return _t(
                "⚠️ 当前没有可用的 embedding provider。\n"
                "请检查 config.json 中的 embedding 相关配置 (provider / api key)。",
                "⚠️ No embedding provider available.\n"
                "Check the embedding settings in config.json (provider / api key).",
            )
        memory_manager.embedding_provider = fresh_provider

        model_label = getattr(fresh_provider, "model", "?")
        dim_label = getattr(fresh_provider, "dimensions", "?")

        # SaaS (e_context is None): run synchronously, return final result
        if e_context is None:
            return self._memory_rebuild_sync(memory_manager, model_label, dim_label)

        # Local channels: run in background, push progress + final result
        from agent.memory.embedding import rebuild_in_process

        def _run():
            try:
                result = rebuild_in_process(memory_manager)
                if result.ok:
                    self._notify(
                        e_context,
                        _t(
                            f"✅ 索引重建完成\n"
                            f"  cleared : {result.removed}\n"
                            f"  chunks  : {result.chunks}\n"
                            f"  files   : {result.files}",
                            f"✅ Index rebuild complete\n"
                            f"  cleared : {result.removed}\n"
                            f"  chunks  : {result.chunks}\n"
                            f"  files   : {result.files}",
                        ),
                    )
                else:
                    self._notify(e_context, _t(f"❌ 索引重建失败: {result.error}", f"❌ Index rebuild failed: {result.error}"))
            except Exception as e:
                logger.exception("[CowCli] /memory rebuild-index failed")
                self._notify(e_context, _t(f"❌ 索引重建失败: {e}", f"❌ Index rebuild failed: {e}"))

        threading.Thread(target=_run, daemon=True).start()
        return _t(
            f"🔧 索引重建已启动 (model={model_label}, dim={dim_label})\n\n"
            f"将重新向量化所有记忆和知识文件，完成后会通知你。",
            f"🔧 Index rebuild started (model={model_label}, dim={dim_label})\n\n"
            f"Re-vectorizing all memory and knowledge files; you'll be notified when done.",
        )

    @staticmethod
    def _memory_rebuild_sync(memory_manager, model_label, dim_label) -> str:
        from agent.memory.embedding import rebuild_in_process

        try:
            result = rebuild_in_process(memory_manager)
        except Exception as e:
            logger.exception("[CowCli] /memory rebuild-index sync failed")
            return _t(f"❌ 索引重建失败: {e}", f"❌ Index rebuild failed: {e}")

        if not result.ok:
            return _t(f"❌ 索引重建失败: {result.error}", f"❌ Index rebuild failed: {result.error}")
        return _t(
            f"✅ 索引重建完成 (model={model_label}, dim={dim_label})\n"
            f"  cleared : {result.removed}\n"
            f"  chunks  : {result.chunks}\n"
            f"  files   : {result.files}",
            f"✅ Index rebuild complete (model={model_label}, dim={dim_label})\n"
            f"  cleared : {result.removed}\n"
            f"  chunks  : {result.chunks}\n"
            f"  files   : {result.files}",
        )

    @staticmethod
    def _notify(e_context, text: str):
        """Push a notification message back to the chat channel."""
        if e_context is None:
            logger.info(f"[CowCli] {text}")
            return
        try:
            channel = e_context["channel"]
            context = e_context["context"]
            if channel and context:
                channel.send(Reply(ReplyType.TEXT, text), context)
        except Exception as e:
            logger.warning(f"[CowCli] notify failed: {e}")

    @staticmethod
    def _is_web_channel(e_context) -> bool:
        if e_context is None:
            return False
        try:
            return e_context["context"].kwargs.get("channel_type") == "web"
        except Exception:
            return False

    @staticmethod
    def _harden_line_breaks(text: str, e_context) -> str:
        """WeChat PC renders bot messages as Markdown, where a lone '\\n' is
        collapsed into a space, so plain-text CLI output gets squashed onto
        one line. Prefix consecutive text lines with '- ' so the Markdown
        list keeps each on its own line (the only form WeChat respects).
        WeChat-only; other channels are untouched. Blank lines, code fences,
        and lines that are already list items are left intact."""
        if e_context is None or not text or "\n" not in text:
            return text
        try:
            if e_context["context"].kwargs.get("channel_type") != "weixin":
                return text
        except Exception:
            return text

        out = []
        in_code = False
        lines = text.split("\n")
        for i, line in enumerate(lines):
            if line.lstrip().startswith("```"):
                in_code = not in_code
                out.append(line)
                continue
            stripped = line.lstrip()
            prev_packed = i > 0 and lines[i - 1].strip() != ""
            next_packed = i < len(lines) - 1 and lines[i + 1].strip() != ""
            # Only convert lines inside a multi-line block (a neighbour line is
            # non-blank); standalone paragraphs separated by blank lines, code
            # blocks, blank lines, and existing list items are left intact.
            if (in_code or not stripped or stripped.startswith(("- ", "* ", "+ "))
                    or not (prev_packed or next_packed)):
                out.append(line)
            else:
                out.append("- " + stripped)
        return "\n".join(out)

    @staticmethod
    def _build_dream_result(flush_mgr, is_web: bool) -> str:
        """Build dream completion message with diary content."""
        from datetime import datetime
        lines = [_t("✅ 记忆蒸馏完成", "✅ Memory distillation complete")]

        # Read today's dream diary
        today = datetime.now().strftime("%Y-%m-%d")
        diary_file = flush_mgr.memory_dir / "dreams" / f"{today}.md"
        if diary_file.exists():
            diary = diary_file.read_text(encoding="utf-8").strip()
            # Strip the "# Dream Diary: ..." header line
            diary_lines = diary.split("\n")
            if diary_lines and diary_lines[0].startswith("# "):
                diary = "\n".join(diary_lines[1:]).strip()
            if diary:
                lines.append(f"\n{diary}")

        if is_web:
            lines.append(_t("\n[MEMORY.md](/memory/MEMORY.md) | [梦境日记](/memory/dreams)", "\n[MEMORY.md](/memory/MEMORY.md) | [Dream Diary](/memory/dreams)"))
        else:
            lines.append(_t("\nMEMORY.md 已更新", "\nMEMORY.md updated"))

        return "\n".join(lines)

    @staticmethod
    def _create_standalone_flush_manager():
        """Create a MemoryFlushManager without a running agent (for pre-init dream)."""
        from pathlib import Path
        from config import conf
        from common.utils import expand_path
        from agent.memory.summarizer import MemoryFlushManager
        from bridge.bridge import Bridge
        from bridge.agent_bridge import AgentLLMModel

        workspace = Path(expand_path(conf().get("agent_workspace", "~/cow")))
        flush_mgr = MemoryFlushManager(workspace_dir=workspace)
        flush_mgr.llm_model = AgentLLMModel(Bridge())
        return flush_mgr

    # ------------------------------------------------------------------
    # knowledge
    # ------------------------------------------------------------------

    def _cmd_knowledge(self, args: str, e_context, **_) -> str:
        sub = args.strip().lower().split(None, 1)[0] if args.strip() else ""

        if sub == "on":
            return self._knowledge_toggle(True)
        elif sub == "off":
            return self._knowledge_toggle(False)
        elif sub in ("list", "tree"):
            return self._knowledge_tree()
        else:
            return self._knowledge_stats()

    def _knowledge_toggle(self, enabled: bool) -> str:
        from config import conf
        import json as _json

        conf()["knowledge"] = enabled

        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        config_path = os.path.join(project_root, "config.json")
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                file_config = _json.load(f)
            file_config["knowledge"] = enabled
            with open(config_path, "w", encoding="utf-8") as f:
                _json.dump(file_config, f, indent=4, ensure_ascii=False)
        except Exception as e:
            return _t(f"⚠️ 内存中已切换，但写入 config.json 失败: {e}", f"⚠️ Switched in memory, but failed to write config.json: {e}")

        if enabled:
            return _t(
                "📚 知识库已开启 ✅\n\n知识库将在下次对话中生效",
                "📚 Knowledge base enabled ✅\n\nIt will take effect in the next conversation",
            )
        return _t(
            "📚 知识库已关闭 ❌\n\n知识库系统已停用，不再注入提示词和索引知识文件",
            "📚 Knowledge base disabled ❌\n\nThe knowledge system is off; no prompt injection or file indexing",
        )

    def _knowledge_stats(self) -> str:
        from config import conf
        from common.utils import expand_path
        knowledge_dir = os.path.join(
            expand_path(conf().get("agent_workspace", "~/cow")),
            "knowledge"
        )
        if not os.path.isdir(knowledge_dir):
            return _t("📚 知识库目录不存在\n\n💡 开启知识库: /knowledge on", "📚 Knowledge base directory not found\n\n💡 Enable it: /knowledge on")

        enabled = conf().get("knowledge", True)
        total_files = 0
        total_bytes = 0
        cat_count = {}

        for root, dirs, files in os.walk(knowledge_dir):
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            rel_root = os.path.relpath(root, knowledge_dir)
            category = rel_root.split(os.sep)[0] if rel_root != "." else "root"
            for f in files:
                if f.endswith(".md") and f not in ("index.md", "log.md"):
                    total_files += 1
                    total_bytes += os.path.getsize(os.path.join(root, f))
                    cat_count[category] = cat_count.get(category, 0) + 1

        status = _t("✅ 已开启", "✅ Enabled") if enabled else _t("❌ 已关闭", "❌ Disabled")
        lines = [
            _t("📚 知识库统计", "📚 Knowledge Base Stats"),
            "",
            _t(f"状态: {status}", f"Status: {status}"),
            _t(f"页面: {total_files} 篇", f"Pages: {total_files}"),
            _t(f"大小: {total_bytes / 1024:.1f} KB", f"Size: {total_bytes / 1024:.1f} KB"),
            "",
        ]
        if cat_count:
            for cat in sorted(cat_count.keys()):
                lines.append(f"- {cat}/ ({cat_count[cat]} pages)")
            lines.append("")

        lines.append(_t(f"路径: {knowledge_dir}", f"Path: {knowledge_dir}"))
        lines.extend([
            "",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━",
            _t("💡 /knowledge list: 查看文件树", "💡 /knowledge list: Show file tree"),
            _t("💡 /knowledge on|off: 开关知识库", "💡 /knowledge on|off: Toggle knowledge base"),
        ])
        return "\n".join(lines)

    def _knowledge_tree(self) -> str:
        from config import conf
        from common.utils import expand_path
        knowledge_dir = os.path.join(
            expand_path(conf().get("agent_workspace", "~/cow")),
            "knowledge"
        )
        if not os.path.isdir(knowledge_dir):
            return _t("📚 知识库目录不存在\n\n💡 开启知识库: /knowledge on", "📚 Knowledge base directory not found\n\n💡 Enable it: /knowledge on")

        tree = ["knowledge/"]

        subdirs = sorted([
            d for d in os.listdir(knowledge_dir)
            if os.path.isdir(os.path.join(knowledge_dir, d)) and not d.startswith(".")
        ])

        for i, subdir in enumerate(subdirs):
            is_last_dir = (i == len(subdirs) - 1)
            branch = "└── " if is_last_dir else "├── "
            subdir_path = os.path.join(knowledge_dir, subdir)
            md_files = sorted([
                f for f in os.listdir(subdir_path)
                if f.endswith(".md") and not f.startswith(".")
            ])
            tree.append(f"{branch}{subdir}/ ({len(md_files)})")

            child_prefix = "    " if is_last_dir else "│   "
            max_show = 12
            for j, fname in enumerate(md_files[:max_show]):
                is_last_file = (j == len(md_files[:max_show]) - 1) and len(md_files) <= max_show
                fb = "└── " if is_last_file else "├── "
                name = fname.replace(".md", "")
                tree.append(f"{child_prefix}{fb}{name}")
            if len(md_files) > max_show:
                tree.append(f"{child_prefix}└── ... +{len(md_files) - max_show} more")

        if not subdirs:
            tree.append(_t("(空)", "(empty)"))

        return "```\n" + "\n".join(tree) + "\n```"

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_session_id(self, e_context, fallback: str = "") -> str:
        if e_context is None:
            return fallback
        context = e_context["context"]
        return context.kwargs.get("session_id") or context.get("session_id", "")

    def _get_agent(self, session_id: str):
        try:
            from bridge.bridge import Bridge
            bridge = Bridge()
            if not bridge._agent_bridge:
                return None
            return bridge._agent_bridge.get_agent(session_id=session_id or None)
        except Exception:
            return None

    def get_help_text(self, **kwargs):
        return _t("在对话中使用 /help 或 cow help 查看可用命令", "Use /help or cow help in chat to see available commands")
