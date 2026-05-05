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
from cli import __version__


# Known top-level subcommands that cow supports
KNOWN_COMMANDS = {
    "help", "version", "status", "logs",
    "start", "stop", "restart",
    "skill", "context", "config",
    "knowledge", "memory",
    "install-browser",
}

# Commands that can only run from the CLI (terminal), not in chat
CLI_ONLY_COMMANDS = {"start", "stop", "restart"}

# Commands that can only run from chat (need access to in-process memory)
CHAT_ONLY_COMMANDS = set()  # context is allowed in both, but behaves differently


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
        logger.debug("[CowCli] initialized")

    def on_handle_context(self, e_context: EventContext):
        if e_context["context"].type != ContextType.TEXT:
            return

        content = e_context["context"].content.strip()
        parsed = self._parse_command(content)
        if not parsed:
            return

        cmd, args = parsed
        logger.info(f"[CowCli] intercepted command: {cmd} {args}")

        result = self._dispatch(cmd, args, e_context)

        reply = Reply(ReplyType.TEXT, result)
        e_context["reply"] = reply
        e_context.action = EventAction.BREAK_PASS

    def _parse_command(self, content: str):
        """
        Parse cow command from message text.

        Supported formats:
          cow <command> [args...]   e.g. "cow skill list"
          /<command> [args...]      e.g. "/skill list"

        Returns (command, args_string) or None if not a cow command.
        """
        parts = None

        if content.startswith("/"):
            rest = content[1:].strip()
            if rest:
                parts = rest.split(None, 1)
        elif content.startswith("cow "):
            rest = content[4:].strip()
            if rest:
                parts = rest.split(None, 1)

        if not parts:
            return None

        cmd = parts[0].lower()
        if cmd not in KNOWN_COMMANDS:
            return None

        args = parts[1] if len(parts) > 1 else ""
        return cmd, args

    # ------------------------------------------------------------------
    # Command dispatch
    # ------------------------------------------------------------------

    def execute(self, query: str, session_id: str = "") -> str:
        """Execute a cow/slash command string without a channel context.

        Used by cloud on_chat to intercept commands before the agent runs.
        Returns None when *query* is not a recognised command.
        """
        parsed = self._parse_command(query.strip())
        if not parsed:
            return None
        cmd, args = parsed
        return self._dispatch(cmd, args, e_context=None, session_id=session_id)

    def _dispatch(self, cmd: str, args: str, e_context: EventContext, session_id: str = "") -> str:
        if cmd in CLI_ONLY_COMMANDS:
            return f"⚠️ `cow {cmd}` 只能在命令行终端中执行。\n请在终端运行: cow {cmd}"

        handler_attr = "_cmd_" + cmd.replace("-", "_")
        handler = getattr(self, handler_attr, None)
        if handler:
            try:
                return handler(args, e_context, session_id=session_id)
            except Exception as e:
                logger.error(f"[CowCli] command '{cmd}' failed: {e}")
                return f"命令执行失败: {e}"

        return f"未知命令: {cmd}"

    # ------------------------------------------------------------------
    # help / version
    # ------------------------------------------------------------------

    def _cmd_help(self, args: str, e_context, **_) -> str:
        lines = [
            "📋 CowAgent 命令列表",
            "",
            "  /help          显示此帮助",
            "  /version       查看版本",
            "  /status        查看运行状态",
            "  /logs [N]      查看最近N条日志 (默认20)",
            "  /context       查看当前对话上下文信息",
            "  /context clear 清除当前对话上下文",
            "  /skill list    查看已安装的技能",
            "  /skill list --remote  浏览技能广场",
            "  /skill search <关键词>  搜索技能",
            "  /skill install <名称>  安装技能",
            "  /skill info <名称>  查看技能详情",
            "  /config              查看当前配置",
            "  /config <key>        查看某项配置",
            "  /config <key> <val>  修改配置",
            "  /memory dream [N]    手动触发记忆蒸馏 (整理近N天, 默认3, 最多30)",
            "  /knowledge           查看知识库统计",
            "  /knowledge list      查看知识库文件树",
            "  /knowledge on|off    开启/关闭知识库",
            "",
            "💡 也可以用 cow <command> 代替 /<command>",
        ]
        return "\n".join(lines)

    def _cmd_version(self, args: str, e_context, **_) -> str:
        return f"CowAgent v{__version__}"

    # ------------------------------------------------------------------
    # status
    # ------------------------------------------------------------------

    def _cmd_status(self, args: str, e_context: EventContext, session_id: str = "", **_) -> str:
        from config import conf

        cfg = conf()
        lines = ["📊 CowAgent 运行状态", ""]

        lines.append(f"  版本: v{__version__}")
        lines.append(f"  进程: PID {os.getpid()}")

        channel = cfg.get("channel_type", "unknown")
        if isinstance(channel, list):
            channel = ", ".join(channel)
        lines.append(f"  通道: {channel}")

        model_name = cfg.get("model", "unknown")
        lines.append(f"  模型: {model_name}")

        mode = "Agent" if cfg.get("agent") else "Chat"
        lines.append(f"  模式: {mode}")

        session_id = self._get_session_id(e_context, fallback=session_id)
        agent = self._get_agent(session_id)
        if agent:
            lines.append("")
            with agent.messages_lock:
                msg_count = len(agent.messages)
            lines.append(f"  会话消息数: {msg_count}")

            if agent.skill_manager:
                total = len(agent.skill_manager.skills)
                enabled = sum(
                    1 for v in agent.skill_manager.skills_config.values()
                    if v.get("enabled", True)
                )
                lines.append(f"  已加载技能: {enabled}/{total}")
        else:
            lines.append("")
            lines.append(f"  Agent: 未初始化 (首次对话后自动创建)")

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
            return "未找到日志文件"

        try:
            with open(log_file, "r", encoding="utf-8", errors="replace") as f:
                all_lines = f.readlines()
            tail = all_lines[-num_lines:]
            content = "".join(tail).strip()
            if not content:
                return "日志为空"
            return f"📄 最近 {len(tail)} 条日志:\n\n{content}"
        except Exception as e:
            return f"读取日志失败: {e}"

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
            return "⚠️ Agent 未初始化，暂无上下文信息"

        with agent.messages_lock:
            messages = agent.messages.copy()

        if not messages:
            return "当前对话上下文为空"

        user_msgs = sum(1 for m in messages if m.get("role") == "user")
        assistant_msgs = sum(1 for m in messages if m.get("role") == "assistant")
        tool_msgs = sum(1 for m in messages if m.get("role") == "tool")

        total_chars = sum(len(str(m.get("content", ""))) for m in messages)

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
            return "⚠️ Agent 未初始化"

        with agent.messages_lock:
            count = len(agent.messages)
            agent.messages.clear()

        return f"✅ 已清除当前对话上下文 ({count} 条消息)"

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
        lines = ["⚙️ 当前配置", ""]
        for key in sorted(self._CONFIG_READABLE):
            val = cfg.get(key, "")
            lines.append(f"  {key}: {val}")
        lines.append("")
        lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━")
        lines.append("💡 /config <key>        查看配置")
        lines.append("💡 /config <key> <val>  修改配置")
        return "\n".join(lines)

    def _config_get(self, key: str) -> str:
        from config import conf
        if key not in self._CONFIG_READABLE:
            available = ", ".join(sorted(self._CONFIG_READABLE))
            return f"不支持查看 '{key}'\n\n可查看的配置项: {available}"
        val = conf().get(key, "")
        return f"⚙️ {key}: {val}"

    def _config_set(self, key: str, value_str: str) -> str:
        from config import conf, load_config, available_setting
        import json as _json

        if key not in self._CONFIG_WRITABLE:
            if key in self._CONFIG_READABLE:
                return f"⚠️ '{key}' 为只读配置，不支持修改"
            available = ", ".join(sorted(self._CONFIG_WRITABLE))
            return f"不支持修改 '{key}'\n\n可修改的配置项: {available}"

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
            return f"写入 config.json 失败: {e}"

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

        result = f"✅ 配置已更新\n\n  {key}: {old_val} → {new_val}"
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
            return (
                "用法: /install-browser\n\n"
                "无需参数，等同于终端执行 `cow install-browser`。\n"
                "安装过程可能持续数分钟；进度会以多条消息推送，pip 详细输出见服务日志。"
            )

        # Suppress detailed stream in chat; phases go through channel.send
        def _noop_stream(msg: str, fg=None):
            pass

        code = run_install_browser(
            stream=_noop_stream,
            on_phase=lambda m: self._send_install_progress(e_context, m),
        )
        if code != 0:
            return (
                "❌ 安装未成功结束，请查看上方分段提示或服务器日志；"
                "也可在终端执行 `cow install-browser`。"
            )
        return "✅ 安装流程已结束。请重启 CowAgent 后使用 browser 工具（进度见上方消息）。"

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
            return (
                "用法: /skill <子命令>\n\n"
                "子命令:\n"
                "  list [--remote]  查看技能列表\n"
                "  search <关键词>  搜索技能\n"
                "  install <名称>   安装技能\n"
                "  uninstall <名称> 卸载技能\n"
                "  info <名称>      查看技能详情\n"
                "  enable <名称>    启用技能\n"
                "  disable <名称>   禁用技能"
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
                return "暂无已安装的技能\n\n💡 /skill list --remote 浏览技能广场"
            config = {e["name"]: e for e in entries}

        sorted_entries = sorted(config.values(), key=lambda e: e.get("name", ""))
        enabled_count = sum(1 for e in sorted_entries if e.get("enabled", True))

        lines = [f"📦 已安装的技能 ({enabled_count}/{len(sorted_entries)})", ""]
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
                line += f"\n   来源: {source}"
            lines.append(line)
            lines.append("")

        lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━")
        lines.append("💡 /skill list --remote  浏览技能广场")
        lines.append("💡 /skill info <名称>     查看详情")
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
            return f"获取技能广场失败: {e}"

        if not skills and page == 1:
            return "技能广场暂无可用技能"

        total_pages = max(1, (total + page_size - 1) // page_size)
        page = min(page, total_pages)
        installed = set(load_skills_config().keys())

        lines = ["🌐 技能广场", ""]
        for s in skills:
            name = s.get("name", "")
            display = s.get("display_name", "") or name
            desc = s.get("description", "")
            if len(desc) > 50:
                desc = desc[:47] + "…"
            badge = " [已安装]" if name in installed else ""
            lines.append(f"📌 {display}{badge}")
            lines.append(f"   名称: {name}")
            if desc:
                lines.append(f"   {desc}")
            lines.append("")

        lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━")
        lines.append(f"📄 第 {page}/{total_pages} 页")
        if page < total_pages:
            lines.append(f"💡 /skill list --remote --page {page + 1}  下一页")
        if page > 1:
            lines.append(f"💡 /skill list --remote --page {page - 1}  上一页")
        lines.append("💡 /skill install <名称>  安装技能")
        lines.append("💡 /skill search <关键词>  搜索技能")
        lines.append("🌐 https://skills.cowagent.ai  在线浏览全部技能")
        return "\n".join(lines)

    def _skill_search(self, query: str) -> str:
        if not query:
            return "请指定搜索关键词: /skill search <关键词>"

        import requests
        from cli.utils import SKILL_HUB_API, load_skills_config
        try:
            resp = requests.get(f"{SKILL_HUB_API}/skills/search", params={"q": query}, timeout=10)
            resp.raise_for_status()
            skills = resp.json().get("skills", [])
        except Exception as e:
            return f"搜索失败: {e}"

        if not skills:
            return f"未找到与「{query}」相关的技能"

        installed = set(load_skills_config().keys())
        lines = [f"🔍 搜索「{query}」({len(skills)} 个结果)", ""]
        for s in skills:
            name = s.get("name", "")
            display = s.get("display_name", "") or name
            desc = s.get("description", "")
            if len(desc) > 50:
                desc = desc[:47] + "…"
            badge = " [已安装]" if name in installed else ""
            lines.append(f"📌 {display}{badge}")
            lines.append(f"   名称: {name}")
            if desc:
                lines.append(f"   {desc}")
            lines.append("")

        lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━")
        lines.append("💡 /skill install <名称>  安装技能")
        return "\n".join(lines)

    _INSTALL_TIMEOUT = 60

    def _skill_install(self, name: str, e_context: EventContext) -> str:
        if not name:
            return "请指定要安装的技能: /skill install <名称>"

        from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
        from cli.commands.skill import install_skill

        try:
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(install_skill, name)
                result = future.result(timeout=self._INSTALL_TIMEOUT)

            if result.error:
                return f"安装失败: {result.error}"

            if not result.installed:
                return "\n".join(result.messages) if result.messages else "未找到可安装的技能"

            return self._format_install_result(result)
        except FuturesTimeout:
            return "安装超时，请稍后重试或检查网络连接"
        except Exception as e:
            return f"安装失败: {e}"

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
            lines.append(f"✅ 技能安装成功：{skill_name}")
            if display and display != skill_name:
                lines.append(f"   名称：{display}")
            if desc:
                lines.append(f"   描述：{desc}")

        if len(result.installed) > 1:
            lines.append(f"\n共安装 {len(result.installed)} 个技能")

        return "\n".join(lines)

    def _skill_uninstall(self, name: str) -> str:
        if not name:
            return "请指定要卸载的技能: /skill uninstall <名称>"

        import shutil
        import json
        from cli.utils import get_skills_dir

        skills_dir = get_skills_dir()
        skill_dir = os.path.join(skills_dir, name)

        if not os.path.exists(skill_dir):
            skill_dir = self._resolve_skill_dir(name, skills_dir)

        if not skill_dir:
            return f"技能 '{name}' 未安装"

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

        return f"✅ 技能 '{name}' 已卸载"

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
            return "请指定技能名称: /skill info <名称>"

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
            return f"技能 '{name}' 未找到"

        skill_md = os.path.join(skill_dir, "SKILL.md")
        if not os.path.exists(skill_md):
            return f"技能 '{name}' 没有 SKILL.md 文件"

        with open(skill_md, "r", encoding="utf-8") as f:
            content = f.read()

        meta, body = self._strip_frontmatter(content)

        header_lines = [f"📖 技能: {name} [{source}]", ""]
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
            action = "启用" if enabled else "禁用"
            return f"请指定技能名称: /skill {'enable' if enabled else 'disable'} <名称>"

        import json
        from cli.utils import get_skills_dir

        skills_dir = get_skills_dir()
        config_path = os.path.join(skills_dir, "skills_config.json")

        if not os.path.exists(config_path):
            return "技能配置文件不存在"

        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
        except Exception as e:
            return f"读取配置失败: {e}"

        if name not in config:
            return f"技能 '{name}' 未在配置中找到"

        config[name]["enabled"] = enabled
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=4, ensure_ascii=False)

        action = "启用" if enabled else "禁用"
        icon = "✅" if enabled else "⬚"
        return f"{icon} 技能 '{name}' 已{action}"

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
        else:
            return (
                "用法: /memory <子命令>\n\n"
                "子命令:\n"
                "  dream [N]  手动触发记忆蒸馏 (整理近N天, 默认3, 最多30)"
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
                return f"⚠️ 无法初始化记忆蒸馏: {e}"

        if not flush_mgr.llm_model:
            return "⚠️ 未配置 LLM 模型，无法执行记忆蒸馏"

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
                    self._notify(e_context, "💤 记忆蒸馏跳过 — 没有新的记忆内容需要整理")
            except Exception as e:
                logger.warning(f"[CowCli] /memory dream failed: {e}")
                self._notify(e_context, f"❌ 记忆蒸馏失败: {e}")

        threading.Thread(target=_run, daemon=True).start()
        return f"🌙 记忆蒸馏已启动 (整理近 {days} 天的记忆)\n\n整理在后台执行，完成后会通知你。"

    def _memory_dream_sync(self, flush_mgr, days: int) -> str:
        """Run deep dream synchronously and return the full result."""
        try:
            result = flush_mgr.deep_dream(lookback_days=days, force=True)
            if result:
                return self._build_dream_result(flush_mgr, is_web=True)
            return "💤 记忆蒸馏跳过 — 没有新的记忆内容需要整理"
        except Exception as e:
            logger.warning(f"[CowCli] /memory dream sync failed: {e}")
            return f"❌ 记忆蒸馏失败: {e}"

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
    def _build_dream_result(flush_mgr, is_web: bool) -> str:
        """Build dream completion message with diary content."""
        from datetime import datetime
        lines = ["✅ 记忆蒸馏完成"]

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
            lines.append("\n[MEMORY.md](/memory/MEMORY.md) | [梦境日记](/memory/dreams)")
        else:
            lines.append("\nMEMORY.md 已更新")

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
            return f"⚠️ 内存中已切换，但写入 config.json 失败: {e}"

        status = "开启 ✅" if enabled else "关闭 ❌"
        note = "知识库将在下次对话中生效" if enabled else "知识库系统已停用，不再注入提示词和索引知识文件"
        return f"📚 知识库已{status}\n\n{note}"

    def _knowledge_stats(self) -> str:
        from config import conf
        from common.utils import expand_path
        knowledge_dir = os.path.join(
            expand_path(conf().get("agent_workspace", "~/cow")),
            "knowledge"
        )
        if not os.path.isdir(knowledge_dir):
            return "📚 知识库目录不存在\n\n💡 开启知识库: /knowledge on"

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

        status = "✅ 已开启" if enabled else "❌ 已关闭"
        lines = [
            "📚 知识库统计",
            "",
            f"状态: {status}",
            f"页面: {total_files} 篇",
            f"大小: {total_bytes / 1024:.1f} KB",
            "",
        ]
        if cat_count:
            for cat in sorted(cat_count.keys()):
                lines.append(f"- {cat}/ ({cat_count[cat]} pages)")
            lines.append("")

        lines.append(f"路径: {knowledge_dir}")
        lines.extend([
            "",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━",
            "💡 /knowledge list    查看文件树",
            "💡 /knowledge on|off  开关知识库",
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
            return "📚 知识库目录不存在\n\n💡 开启知识库: /knowledge on"

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
            tree.append("(空)")

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
        return "在对话中使用 /help 或 cow help 查看可用命令"
