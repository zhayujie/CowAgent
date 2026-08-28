"""
SessionService - Manages multi-session lifecycle for both web channel and cloud client.

Provides a unified interface for listing, deleting, renaming, clearing context,
and generating AI titles for conversation sessions. Backed by ConversationStore
(SQLite) and AgentBridge (in-memory agent instances).
"""

import json
import os
import re
from typing import Optional

from common.log import logger


def _truncate_fallback_title(user_message: str, max_len: int = 30) -> str:
    """Pick the first non-empty line of the user message and truncate it."""
    if not user_message:
        return "New Chat"
    first_line = ""
    for line in user_message.splitlines():
        line = line.strip()
        if line:
            first_line = line
            break
    if not first_line:
        return "New Chat"
    if len(first_line) > max_len:
        first_line = first_line[:max_len].rstrip() + "..."
    return first_line


def generate_session_title(user_message: str, assistant_reply: str = "",
                            session_id: str = "") -> str:
    """
    Generate a short session title by calling the current bot's reply_text.
    Falls back to the first line of the user message if the LLM call fails
    or returns an obvious error sentinel.
    """
    fallback = _truncate_fallback_title(user_message)
    try:
        from bridge.bridge import Bridge
        from models.session_manager import Session
        bot = Bridge().get_bot("chat")

        prompt_parts = [f"User: {user_message[:300]}"]
        if assistant_reply:
            prompt_parts.append(f"Assistant: {assistant_reply[:300]}")

        session = Session(session_id or "__title_gen__", system_prompt="")
        session.messages = [
            {"role": "user", "content": (
                "Generate a very short title (max 15 characters for Chinese, max 6 words for English) "
                "summarizing this conversation. Return ONLY the title text, nothing else.\n\n"
                + "\n".join(prompt_parts)
            )}
        ]

        result = bot.reply_text(session) or {}
        # When bots fail (network error, auth error, rate limit, etc.) they
        # typically return completion_tokens=0 with a sentinel content like
        # "请再问我一次吧" / "我现在有点累了". Treat that as failure.
        completion_tokens = result.get("completion_tokens", 0) or 0
        raw = (result.get("content") or "").strip()
        if completion_tokens <= 0:
            logger.warning(
                f"[SessionService] Title generation got empty completion "
                f"(completion_tokens={completion_tokens}, content='{raw[:50]}'), "
                f"using fallback")
            return fallback

        title = re.sub(r'<think>.*?</think>', '', raw, flags=re.DOTALL).strip().strip('"\'')
        logger.info(f"[SessionService] Title generation result: '{title}' (len={len(title)})")
        if title and len(title) <= 50:
            return title
    except Exception as e:
        logger.warning(f"[SessionService] Title generation failed: {e}")
    return fallback


# Built-in fallback config, used when prompts.json is missing or broken.
_DEFAULT_OPTIMIZE_CONFIG = {
    "role": "你是一个「提示词优化专家」。你的唯一任务是：把 <user_prompt> 标签里的用户原始指令，改写成一条更清晰、更具体、更容易让大模型准确执行的提示词。",
    "principles": [
        {"guideline": "你不需要、也不能回答或执行 <user_prompt> 里的内容，只能对它进行改写优化。"},
        {"guideline": "优化时补全缺失的关键信息维度，可用占位符或引导式提问的方式让指令更完整。"},
        {"guideline": "修正口语化表达、网络俚语、碎片化短句，语句通顺严谨。"},
        {"guideline": "保留原文全部核心信息、逻辑与关键观点，不增删原意。"},
        {"guideline": "句式规整、逻辑层次清晰，行文正式得体，适配和大模型沟通的严谨行文风格。"},
        {"guideline": "不使用夸张情绪化措辞，客观中立，段落排版整洁。"},
    ],
    "output_format": "只输出优化后的提示词本身，不要输出任何解释、说明、前后缀或对话。",
    "input_wrapper": "<user_prompt>\n{user_prompt}\n</user_prompt>\n\n优化后的提示词：",
}


def _assemble_optimize_prompt(config: dict) -> str:
    """
    Assemble a full prompt template string from a structured config dict.

    Recognized keys (with backward-compatible aliases):
      - role
      - principles / rules: list of dicts, each with guideline / instruction
      - output_format
      - input_wrapper / input_template: must contain the {user_prompt} placeholder
    """
    parts = []

    role = (config.get('role') or '').strip()
    if role:
        parts.append(role)
        parts.append('')

    # Accept both "principles" (current) and "rules" (legacy) as the list key.
    rules = config.get('principles')
    if not isinstance(rules, list):
        rules = config.get('rules')
    if isinstance(rules, list) and rules:
        parts.append('严格遵守以下规则：')
        idx = 1
        for rule in rules:
            if not isinstance(rule, dict):
                continue
            # Accept both "guideline" (current) and "instruction" (legacy).
            text = (rule.get('guideline') or rule.get('instruction') or '').strip()
            if text:
                parts.append(f'{idx}. {text}')
                idx += 1
        parts.append('')

    output_fmt = (config.get('output_format') or '').strip()
    if output_fmt:
        parts.append(output_fmt)
        parts.append('')

    # Accept both "input_wrapper" (current) and "input_template" (legacy).
    input_tpl = (config.get('input_wrapper') or config.get('input_template') or '').strip()
    # Ensure the wrapper contains the placeholder, otherwise the user input
    # would be dropped entirely.
    if '{user_prompt}' not in input_tpl:
        input_tpl = '<user_prompt>\n{user_prompt}\n</user_prompt>'
    parts.append(input_tpl)

    return '\n'.join(parts).strip()


def _load_optimize_prompt_template() -> str:
    """
    Load optimization rules from agent/chat/prompts.json and assemble them
    into a complete prompt template.

    The prompts.json file defines a structured rule set:
      - role: the AI persona description
      - principles: list of optimization rules (each with a guideline)
      - output_format: constraint on how the AI should output
      - input_wrapper: wraps the user's input with the {user_prompt} placeholder

    Users can add, remove, or edit rules in prompts.json and the changes
    take effect immediately on the next call — no restart needed.

    Falls back to a built-in structured template if the file is missing,
    broken, or produces an empty result.
    """
    template_path = os.path.join(os.path.dirname(__file__), 'prompts.json')
    try:
        with open(template_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        config = data.get('optimize_prompt')
        if isinstance(config, dict):
            assembled = _assemble_optimize_prompt(config)
            if assembled:
                logger.info('[SessionService] Assembled optimize prompt from prompts.json')
                return assembled
        elif isinstance(config, str):
            # Backward-compatible: old flat string format.
            template = config.strip()
            if template:
                logger.info('[SessionService] Loaded optimize prompt (legacy flat format)')
                return template
    except Exception as e:
        logger.warning(f'[SessionService] Failed to load optimize prompt template: {e}')

    logger.info('[SessionService] Using built-in fallback optimize prompt')
    return _assemble_optimize_prompt(_DEFAULT_OPTIMIZE_CONFIG)


def optimize_prompt(user_input: str, context_messages: list = None) -> str:
    """
    Optimize a user's colloquial input into a structured AI-ready instruction.

    Calls the current chat model with a fixed optimization system prompt.
    Falls back to the original input if the model call fails or returns empty.

    :param user_input: the raw user message to optimize
    :param context_messages: optional list of recent conversation messages for context
    :return: optimized instruction text
    """
    fallback = user_input.strip()
    if not fallback:
        return ""

    try:
        from bridge.bridge import Bridge
        from models.session_manager import Session
        bot = Bridge().get_bot("chat")

        template = _load_optimize_prompt_template()

        # Build the content that replaces {user_prompt} in the template
        prompt_content = user_input
        if isinstance(context_messages, list) and context_messages:
            context_lines = []
            for m in context_messages[-6:]:  # keep last 6 messages for context
                if not isinstance(m, dict):
                    continue
                role = m.get("role", "user")
                content = str(m.get("content", ""))[:200]
                context_lines.append(f"[{role}]: {content}")
            if context_lines:
                prompt_content = (
                    "（以下是最近的对话上下文，仅供参考，优化时请以 <user_prompt> 内的原文为准）\n"
                    + "\n".join(context_lines)
                    + f"\n\n原文：\n{user_input}"
                )

        user_message = template.replace("{user_prompt}", prompt_content)

        session = Session("__optimize_prompt__", system_prompt="")
        session.messages = [{"role": "user", "content": user_message}]

        result = bot.reply_text(session) or {}
        completion_tokens = result.get("completion_tokens", 0) or 0
        raw = (result.get("content") or "").strip()

        if completion_tokens <= 0:
            logger.warning(
                f"[SessionService] Prompt optimization got empty completion "
                f"(completion_tokens={completion_tokens}, content='{raw[:50]}'), "
                f"returning original input")
            return fallback

        # Strip any <think>...</think> tags (thinking models)
        optimized = re.sub(r'<think>.*?</think>', '', raw, flags=re.DOTALL).strip()

        if not optimized:
            logger.warning("[SessionService] Prompt optimization result empty after stripping, "
                           "returning original input")
            return fallback

        logger.info(f"[SessionService] Prompt optimized: {len(user_input)} → {len(optimized)} chars")
        return optimized

    except Exception as e:
        logger.warning(f"[SessionService] Prompt optimization failed: {e}")
        return fallback


class SessionService:
    """
    High-level service for session lifecycle management.

    Usage:
        svc = SessionService()
        result = svc.dispatch("list", {"channel_type": "web", "page": 1})
    """

    def __init__(self, agent_id: str = None):
        self.agent_id = agent_id

    def _resolve_agent_id(self, agent_id: str = None) -> str:
        from agent.registry import get_agent_registry
        return get_agent_registry().get(agent_id or self.agent_id).id

    def _get_store(self, agent_id: str = None):
        from agent.registry import get_agent_registry
        from agent.memory import get_conversation_store
        profile = get_agent_registry().get(agent_id or self.agent_id)
        return get_conversation_store(profile.workspace)

    def _remove_agent(self, session_id: str, agent_id: str = None):
        """Remove the in-memory Agent instance for a session if it exists."""
        try:
            from bridge.bridge import Bridge
            ab = Bridge().get_agent_bridge()
            ab.clear_session(session_id, agent_id=self._resolve_agent_id(agent_id))
        except Exception:
            pass

    @staticmethod
    def _normalize_sid(session_id: str) -> str:
        if session_id and not session_id.startswith("session_"):
            return f"session_{session_id}"
        return session_id

    # ------------------------------------------------------------------
    # actions
    # ------------------------------------------------------------------
    def list_sessions(self, channel_type: Optional[str] = None,
                      page: int = 1, page_size: int = 50,
                      agent_id: str = None) -> dict:
        store = self._get_store(agent_id)
        return store.list_sessions(
            channel_type=channel_type,
            page=page,
            page_size=page_size,
        )

    def _cancel_running(self, session_id: str, agent_id: str = None) -> None:
        """Abort any in-flight run of a session before dropping its data."""
        try:
            from agent.protocol import get_cancel_registry
            from agent.registry import get_agent_registry
            from bridge.agent_bridge import AgentBridge
            # Runs are registered under the agent-scoped key, so an unscoped
            # lookup here would silently cancel nothing.
            registry = get_agent_registry()
            scoped = AgentBridge._cancel_key(
                self._resolve_agent_id(agent_id),
                session_id,
                registry.default_agent_id,
            )
            cancelled = get_cancel_registry().cancel_session(scoped)
            if cancelled:
                logger.info(f"[SessionService] Cancelled {cancelled} in-flight "
                            f"request(s) for session {session_id}")
        except Exception as e:
            logger.warning(f"[SessionService] Cancel on delete failed: {e}")

    def delete_session(self, session_id: str, agent_id: str = None) -> None:
        if not session_id:
            raise ValueError("session_id required")
        session_id = self._normalize_sid(session_id)

        self._cancel_running(session_id, agent_id)
        store = self._get_store(agent_id)
        store.clear_session(session_id)
        self._remove_agent(session_id, agent_id)
        logger.info(f"[SessionService] Session deleted: {session_id}")

    def rename_session(
        self, session_id: str, title: str, agent_id: str = None
    ) -> None:
        if not session_id:
            raise ValueError("session_id required")
        if not title:
            raise ValueError("title required")
        session_id = self._normalize_sid(session_id)

        store = self._get_store(agent_id)
        found = store.rename_session(session_id, title)
        if not found:
            raise ValueError("session not found")

    def clear_context(self, session_id: str, agent_id: str = None) -> int:
        """
        Set context boundary. Returns the new context_start_seq value.
        """
        if not session_id:
            raise ValueError("session_id required")
        session_id = self._normalize_sid(session_id)

        store = self._get_store(agent_id)
        new_seq = store.clear_context(session_id)
        self._remove_agent(session_id, agent_id)
        return new_seq

    def gen_title(self, session_id: str, user_message: str,
                  assistant_reply: str = "", agent_id: str = None) -> str:
        """
        Generate an AI title and persist it. Returns the generated title.
        """
        if not session_id:
            raise ValueError("session_id required")
        if not user_message:
            raise ValueError("user_message required")
        session_id = self._normalize_sid(session_id)

        title = generate_session_title(user_message, assistant_reply, session_id)

        store = self._get_store(agent_id)
        updated = store.rename_session(session_id, title)
        logger.info(f"[SessionService] Title set: sid={session_id}, "
                     f"title='{title}', db_updated={updated}")
        return title

    # ------------------------------------------------------------------
    # dispatch — single entry point for protocol messages
    # ------------------------------------------------------------------
    def dispatch(self, action: str, payload: Optional[dict] = None) -> dict:
        """
        Dispatch a session management action and return a protocol-compatible
        response dict.

        Action names use a ``*_session`` / session-prefixed convention so they
        can coexist with history actions (e.g. ``query``) on the same HISTORY
        message channel without ambiguity.

        Supported actions:
          - list_sessions: list sessions with pagination
          - delete_session: delete a session
          - rename_session: rename a session title
          - clear_context: set context boundary
          - generate_title: AI-generate a session title

        :param action: one of the above action names
        :param payload: action-specific payload
        :return: dict with action, code, message, payload
        """
        payload = payload or {}
        agent_id = payload.get("agent_id") or self.agent_id
        try:
            if action == "list_sessions":
                result = self.list_sessions(
                    channel_type=payload.get("channel_type"),
                    page=int(payload.get("page", 1)),
                    page_size=int(payload.get("page_size", 50)),
                    agent_id=agent_id,
                )
                return {"action": action, "code": 200, "message": "success", "payload": result}

            elif action == "delete_session":
                self.delete_session(payload.get("session_id", ""), agent_id=agent_id)
                return {"action": action, "code": 200, "message": "success", "payload": None}

            elif action == "rename_session":
                self.rename_session(
                    payload.get("session_id", ""),
                    payload.get("title", "").strip(),
                    agent_id=agent_id,
                )
                return {"action": action, "code": 200, "message": "success", "payload": None}

            elif action == "clear_context":
                new_seq = self.clear_context(
                    payload.get("session_id", ""), agent_id=agent_id
                )
                return {"action": action, "code": 200, "message": "success",
                        "payload": {"context_start_seq": new_seq}}

            elif action == "generate_title":
                title = self.gen_title(
                    payload.get("session_id", ""),
                    payload.get("user_message", ""),
                    payload.get("assistant_reply", ""),
                    agent_id=agent_id,
                )
                return {"action": action, "code": 200, "message": "success",
                        "payload": {"title": title}}

            else:
                return {"action": action, "code": 400,
                        "message": f"unknown action: {action}", "payload": None}

        except ValueError as e:
            return {"action": action, "code": 400, "message": str(e), "payload": None}
        except Exception as e:
            logger.error(f"[SessionService] dispatch error: action={action}, error={e}")
            return {"action": action, "code": 500, "message": str(e), "payload": None}
