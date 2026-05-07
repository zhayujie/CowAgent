"""
Memory flush manager with Deep Dream distillation

Handles memory persistence when conversation context is trimmed or overflows:
- Uses LLM to summarize discarded messages into concise daily records
- Writes to daily memory files (lazy creation)
- Deduplicates trim flushes to avoid repeated writes
- Runs summarization asynchronously to avoid blocking normal replies
- Deep Dream: periodically distills daily memories → refined MEMORY.md + dream diary
"""

import threading
from typing import Optional, Callable, Any, List, Dict
from pathlib import Path
from datetime import datetime
from common.log import logger


SUMMARIZE_SYSTEM_PROMPT = """你是一个对话记录助手。请将对话内容归纳为当天的日常记录。

## 要求

按「事件」维度归纳发生的事，不要按对话轮次逐条记录：
- 每条一行，用 "- " 开头
- 合并同一件事的多轮对话
- 只记录有意义的事件，忽略闲聊和问候
- 保留关键的决策、结论和待办事项

当对话没有任何记录价值（仅含问候或无意义内容），直接回复"无"。"""

SUMMARIZE_USER_PROMPT = """请归纳以下对话的日常记录：

{conversation}"""

# ---------------------------------------------------------------------------
# Deep Dream prompts — distill daily memories → MEMORY.md + dream diary
# ---------------------------------------------------------------------------

DREAM_SYSTEM_PROMPT = """你是一个记忆整理助手，负责定期整理用户的长期记忆。

你将收到两份材料：
1. **当前长期记忆** — MEMORY.md 的全部现有内容
2. **今日日记** — 当天的日常记录

MEMORY.md 会注入每次对话的系统提示词中，因此必须保持精炼，只存放有价值和值得记忆的内容。

**重要：只能基于提供的材料进行整理，严禁编造、推测或添加材料中不存在的信息。**

## 任务

### Part 1: 更新后的长期记忆（[MEMORY]）

在现有记忆基础上进行整理和提炼，输出完整的更新后内容：
- **合并提炼**：将含义相近的多条合并为一条高密度表述，而非简单罗列
- **新增萃取**：从今日日记中提取值得永久记住的新信息（偏好、决策、人物、规则、经验）
- **冲突更新**：当新信息与旧条目矛盾时，以新信息为准，替换旧条目
- **清理无效**：删除临时性记录、空白条目、格式残留、无意义、重复内容等
- **删除冗余**：已被更精炼表述涵盖的旧条目应删除，避免信息重复
- 每条一行，用 "- " 开头，不带日期前缀
- 可用 "## 标题" 对相关条目分组，使结构更清晰
- 目标：控制在 50 条以内，每条尽量一句话概括

### Part 2: 梦境日记（[DREAM]）

用简洁的叙事风格写一篇短日记，记录这次整理的发现，保持格式美观易读：
- 发现了哪些重复或矛盾
- 从日记中提取了什么新洞察
- 做了哪些清理和优化
- 整体感受和观察

## 输出格式（严格遵守）

```
[MEMORY]
- 记忆条目1
- 记忆条目2
...

[DREAM]
梦境日记内容...
```"""

DREAM_USER_PROMPT = """## 当前长期记忆（MEMORY.md）

{memory_content}

## 近期日记（最近 {days} 天）

{daily_content}"""



class MemoryFlushManager:
    """
    Manages memory flush operations.
    
    Flush is triggered by agent_stream in two scenarios:
    1. Context trim: _trim_messages discards old turns → flush discarded content
    2. Context overflow: API rejects request → emergency flush before clearing
    
    Additionally, create_daily_summary() can be called by scheduler for end-of-day summaries.
    """
    
    def __init__(
        self,
        workspace_dir: Path,
        llm_model: Optional[Any] = None,
    ):
        self.workspace_dir = workspace_dir
        self.llm_model = llm_model
        
        self.memory_dir = workspace_dir / "memory"
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        
        self.last_flush_timestamp: Optional[datetime] = None
        self._trim_flushed_hashes: set = set()  # Content hashes of already-flushed messages
        self._last_flushed_content_hash: str = ""  # Content hash at last flush, for daily dedup
        self._last_dream_input_hash: str = ""  # "{date}:{daily_hash}" of last dream, for dedup
        self._last_flush_thread: Optional[threading.Thread] = None
    
    def get_today_memory_file(self, user_id: Optional[str] = None, ensure_exists: bool = False) -> Path:
        """Get today's memory file path: memory/YYYY-MM-DD.md"""
        today = datetime.now().strftime("%Y-%m-%d")
        
        if user_id:
            user_dir = self.memory_dir / "users" / user_id
            if ensure_exists:
                user_dir.mkdir(parents=True, exist_ok=True)
            today_file = user_dir / f"{today}.md"
        else:
            today_file = self.memory_dir / f"{today}.md"
        
        if ensure_exists and not today_file.exists():
            today_file.parent.mkdir(parents=True, exist_ok=True)
            today_file.write_text(f"# Daily Memory: {today}\n\n")
        
        return today_file
    
    def get_main_memory_file(self, user_id: Optional[str] = None) -> Path:
        """Get main memory file path: MEMORY.md (workspace root)"""
        if user_id:
            user_dir = self.memory_dir / "users" / user_id
            user_dir.mkdir(parents=True, exist_ok=True)
            return user_dir / "MEMORY.md"
        else:
            return Path(self.workspace_dir) / "MEMORY.md"
    
    def get_status(self) -> dict:
        return {
            'last_flush_time': self.last_flush_timestamp.isoformat() if self.last_flush_timestamp else None,
            'today_file': str(self.get_today_memory_file()),
            'main_file': str(self.get_main_memory_file())
        }

    # ---- Flush execution (called by agent_stream or scheduler) ----
    
    def flush_from_messages(
        self,
        messages: List[Dict],
        user_id: Optional[str] = None,
        reason: str = "trim",
        max_messages: int = 0,
        context_summary_callback: Optional[Callable[[str], None]] = None,
    ) -> bool:
        """
        Asynchronously summarize and flush messages to daily memory.

        Deduplication runs synchronously, then LLM summarization + file write
        run in a background thread so the main reply flow is never blocked.

        If *context_summary_callback* is provided, it is called with the
        [DAILY] portion of the LLM summary once available. The caller can use
        this to inject the summary into the live message list for context
        continuity — one LLM call serves both disk persistence and in-context
        injection.
        """
        try:
            # Strip scheduler-injected pairs before any further processing.
            # These messages already serve as short-term context inside the
            # receiver session; promoting them into long-term daily memory
            # produces low-value flat logs (e.g. "11:28 price=1013, normal /
            # 11:58 price=1013, normal / ...") and wastes summarisation tokens.
            messages = self._strip_scheduler_pairs(messages)
            if not messages:
                return False

            import hashlib
            deduped = []
            for m in messages:
                text = self._extract_text_from_content(m.get("content", ""))
                if not text or not text.strip():
                    continue
                h = hashlib.md5(text.encode("utf-8")).hexdigest()
                if h not in self._trim_flushed_hashes:
                    self._trim_flushed_hashes.add(h)
                    deduped.append(m)
            if not deduped:
                return False

            import copy
            snapshot = copy.deepcopy(deduped)
            thread = threading.Thread(
                target=self._flush_worker,
                args=(snapshot, user_id, reason, max_messages, context_summary_callback),
                daemon=True,
            )
            thread.start()
            logger.info(f"[MemoryFlush] Async flush dispatched (reason={reason}, msgs={len(snapshot)})")
            self._last_flush_thread = thread
            return True

        except Exception as e:
            logger.warning(f"[MemoryFlush] Failed to dispatch flush (reason={reason}): {e}")
            return False

    def _flush_worker(
        self,
        messages: List[Dict],
        user_id: Optional[str],
        reason: str,
        max_messages: int,
        context_summary_callback: Optional[Callable[[str], None]] = None,
    ):
        """Background worker: summarize with LLM, write daily memory file."""
        try:
            raw_summary = self._summarize_messages(messages, max_messages)
            if not raw_summary or not raw_summary.strip() or raw_summary.strip() == "无":
                logger.info(f"[MemoryFlush] No valuable content to flush (reason={reason})")
                return

            # Strip legacy [DAILY]/[MEMORY] markers if model still outputs them
            daily_part = self._clean_summary_output(raw_summary)
            if not daily_part:
                return

            # --- Write daily memory ---
            daily_file = ensure_daily_memory_file(self.workspace_dir, user_id)

            headers = {
                "overflow": f"## Context Overflow Recovery ({datetime.now().strftime('%H:%M')})",
                "trim": f"## Trimmed Context ({datetime.now().strftime('%H:%M')})",
                "daily_summary": f"## Daily Summary ({datetime.now().strftime('%H:%M')})",
            }
            header = headers.get(reason, f"## Session Notes ({datetime.now().strftime('%H:%M')})")

            with open(daily_file, "a", encoding="utf-8") as f:
                f.write(f"\n{header}\n\n{daily_part}\n")

            logger.info(f"[MemoryFlush] Wrote daily memory to {daily_file.name} (reason={reason}, chars={len(daily_part)})")

            # --- Inject context summary into live messages (if callback provided) ---
            if context_summary_callback:
                try:
                    context_summary_callback(daily_part)
                except Exception as e:
                    logger.warning(f"[MemoryFlush] Context summary callback failed: {e}")

            self.last_flush_timestamp = datetime.now()

        except Exception as e:
            logger.warning(f"[MemoryFlush] Async flush failed (reason={reason}): {e}")

    @staticmethod
    def _clean_summary_output(raw: str) -> str:
        """Strip legacy [DAILY]/[MEMORY] markers if present, return clean daily text."""
        raw = raw.strip()
        if not raw or raw == "无":
            return ""

        # Strip [DAILY] marker
        if "[DAILY]" in raw:
            start = raw.index("[DAILY]") + len("[DAILY]")
            end = raw.index("[MEMORY]") if "[MEMORY]" in raw else len(raw)
            raw = raw[start:end].strip()

        # Remove stray [MEMORY] section entirely
        if "[MEMORY]" in raw:
            raw = raw[:raw.index("[MEMORY]")].strip()

        # Remove markdown code fences
        raw = raw.replace("```", "").strip()

        return raw

    def create_daily_summary(
        self,
        messages: List[Dict],
        user_id: Optional[str] = None
    ) -> bool:
        """
        Generate end-of-day summary. Called by daily timer.
        Skips if messages haven't changed since last flush.
        """
        import hashlib
        content = "".join(
            self._extract_text_from_content(m.get("content", ""))
            for m in messages
        )
        content_hash = hashlib.md5(content.encode("utf-8")).hexdigest()
        if content_hash == self._last_flushed_content_hash:
            logger.debug("[MemoryFlush] Daily summary skipped: no new content since last flush")
            return False
        self._last_flushed_content_hash = content_hash
        return self.flush_from_messages(
            messages=messages,
            user_id=user_id,
            reason="daily_summary",
            max_messages=0,
        )

    # ---- Deep Dream (memory distillation) ----

    def deep_dream(self, user_id: Optional[str] = None, lookback_days: int = 1, force: bool = False) -> bool:
        """
        Distill recent daily memories into MEMORY.md and generate a dream diary.

        Args:
            lookback_days: How many days of daily files to read (default 1 for scheduled, 3 for manual)
            force: Skip input-hash dedup check (used by manual /memory dream trigger)
        """
        if not self.llm_model:
            logger.warning("[DeepDream] No LLM model available, skipping")
            return False

        logger.info(f"[DeepDream] Starting memory distillation (lookback={lookback_days} days)")

        # Collect materials
        memory_content = self._read_main_memory(user_id)
        daily_content, has_content = self._read_recent_dailies(user_id, lookback_days)

        if not has_content:
            logger.info("[DeepDream] No recent daily records, skipping to preserve existing MEMORY.md")
            return False

        # Dedup: skip if same daily content already dreamed today.
        # Note: only hash daily_content (not memory_content), because deep_dream
        # itself rewrites MEMORY.md as a side effect, which would otherwise
        # invalidate the hash on every subsequent call within the same window.
        import hashlib
        daily_hash = hashlib.md5(daily_content.encode("utf-8")).hexdigest()
        today_str = datetime.now().strftime("%Y-%m-%d")
        dedup_key = f"{today_str}:{daily_hash}"
        if not force and dedup_key == self._last_dream_input_hash:
            logger.info("[DeepDream] Already dreamed today with same daily content, skipping")
            return False
        self._last_dream_input_hash = dedup_key

        logger.info(
            f"[DeepDream] Materials collected: "
            f"MEMORY.md={len(memory_content)} chars, "
            f"daily={len(daily_content)} chars"
        )

        # Call LLM for distillation
        import time as _time
        t0 = _time.monotonic()
        try:
            user_msg = DREAM_USER_PROMPT.format(
                memory_content=memory_content or "(empty)",
                days=lookback_days,
                daily_content=daily_content or "(no recent daily records)",
            )
            from agent.protocol.models import LLMRequest
            # Scale max_tokens based on input size to avoid truncating large MEMORY.md
            input_chars = len(memory_content) + len(daily_content)
            dream_max_tokens = max(2000, min(input_chars, 8000))
            request = LLMRequest(
                messages=[{"role": "user", "content": user_msg}],
                temperature=0.3,
                max_tokens=dream_max_tokens,
                stream=False,
                system=DREAM_SYSTEM_PROMPT,
            )
            response = self.llm_model.call(request)
            raw = self._extract_response_text(response)
            elapsed = _time.monotonic() - t0
            if not raw or not raw.strip():
                logger.warning(f"[DeepDream] LLM returned empty response ({elapsed:.1f}s)")
                return False
            logger.info(f"[DeepDream] LLM distillation completed ({elapsed:.1f}s, {len(raw)} chars)")
        except Exception as e:
            elapsed = _time.monotonic() - t0
            logger.warning(f"[DeepDream] LLM call failed ({elapsed:.1f}s): {e}")
            return False

        # Parse [MEMORY] and [DREAM] sections
        new_memory, dream_diary = self._parse_dream_output(raw)

        if not new_memory:
            logger.warning("[DeepDream] No [MEMORY] section in LLM output, skipping overwrite")
            return False

        # Overwrite MEMORY.md
        try:
            main_file = self.get_main_memory_file(user_id)
            old_size = len(memory_content)
            main_file.write_text(new_memory + "\n", encoding="utf-8")
            logger.info(
                f"[DeepDream] Updated MEMORY.md "
                f"({old_size} → {len(new_memory)} chars)"
            )
        except Exception as e:
            logger.warning(f"[DeepDream] Failed to write MEMORY.md: {e}")
            return False

        # Write dream diary
        if dream_diary:
            try:
                self._write_dream_diary(dream_diary, user_id)
            except Exception as e:
                logger.warning(f"[DeepDream] Failed to write dream diary: {e}")

        logger.info("[DeepDream] ✅ Deep Dream completed successfully")
        return True

    def _read_main_memory(self, user_id: Optional[str] = None) -> str:
        """Read current MEMORY.md content."""
        main_file = self.get_main_memory_file(user_id)
        if main_file.exists():
            return main_file.read_text(encoding="utf-8").strip()
        return ""

    def _read_recent_dailies(
        self, user_id: Optional[str] = None, lookback_days: int = 1
    ) -> tuple:
        """
        Read recent daily memory files.

        Returns:
            (combined_text, has_content) tuple
        """
        from datetime import timedelta

        parts = []
        has_content = False
        today = datetime.now().date()

        for offset in range(lookback_days):
            day = today - timedelta(days=offset)
            date_str = day.strftime("%Y-%m-%d")
            if user_id:
                daily_file = self.memory_dir / "users" / user_id / f"{date_str}.md"
            else:
                daily_file = self.memory_dir / f"{date_str}.md"

            if daily_file.exists():
                content = daily_file.read_text(encoding="utf-8").strip()
                if content:
                    parts.append(f"### {date_str}\n\n{content}")
                    has_content = True
            else:
                parts.append(f"### {date_str}\n\n(no records)")

        return "\n\n".join(parts), has_content

    @staticmethod
    def _parse_dream_output(raw: str) -> tuple:
        """Parse LLM output into (new_memory, dream_diary)."""
        raw = raw.strip().replace("```", "")
        new_memory = ""
        dream_diary = ""

        if "[MEMORY]" in raw:
            start = raw.index("[MEMORY]") + len("[MEMORY]")
            end = raw.index("[DREAM]") if "[DREAM]" in raw else len(raw)
            new_memory = raw[start:end].strip()

        if "[DREAM]" in raw:
            start = raw.index("[DREAM]") + len("[DREAM]")
            dream_diary = raw[start:].strip()

        return new_memory, dream_diary

    def _write_dream_diary(self, content: str, user_id: Optional[str] = None):
        """Write dream diary to memory/dreams/YYYY-MM-DD.md."""
        dreams_dir = self.memory_dir / "dreams"
        if user_id:
            dreams_dir = self.memory_dir / "users" / user_id / "dreams"
        dreams_dir.mkdir(parents=True, exist_ok=True)

        today = datetime.now().strftime("%Y-%m-%d")
        diary_file = dreams_dir / f"{today}.md"
        diary_file.write_text(
            f"# Dream Diary: {today}\n\n{content}\n",
            encoding="utf-8",
        )
        logger.info(f"[DeepDream] Wrote dream diary to {diary_file}")

    # ---- Internal helpers ----
    
    def _summarize_messages(self, messages: List[Dict], max_messages: int = 0) -> str:
        """
        Summarize conversation messages using LLM.
        Returns empty string if LLM deems content not worth recording.
        Rule-based fallback only used when LLM call raises an exception.
        """
        conversation_text = self._format_conversation_for_summary(messages, max_messages)
        if not conversation_text.strip():
            return ""
        
        if self.llm_model:
            try:
                summary = self._call_llm_for_summary(conversation_text)
                if summary and summary.strip() and summary.strip() != "无":
                    return summary.strip()
                logger.info("[MemoryFlush] LLM returned empty or '无', skipping write")
                return ""
            except Exception as e:
                logger.warning(f"[MemoryFlush] LLM summarization failed, using fallback: {e}")
                return self._extract_summary_fallback(messages, max_messages)
        else:
            logger.info("[MemoryFlush] No LLM model available, using rule-based fallback")
            return self._extract_summary_fallback(messages, max_messages)

    def _format_conversation_for_summary(self, messages: List[Dict], max_messages: int = 0) -> str:
        """Format messages into readable conversation text for LLM summarization."""
        msgs = messages if max_messages == 0 else messages[-max_messages * 2:]
        lines = []
        for msg in msgs:
            role = msg.get("role", "")
            text = self._extract_text_from_content(msg.get("content", ""))
            if not text or not text.strip():
                continue
            text = text.strip()
            if role == "user":
                lines.append(f"用户: {text[:500]}")
            elif role == "assistant":
                lines.append(f"助手: {text[:500]}")
        return "\n".join(lines)

    @staticmethod
    def _extract_response_text(response) -> str:
        """
        Extract text from LLM response regardless of format.

        Handles:
        - Generator (MiniMax _handle_sync_response yields Claude-format dicts)
        - Claude format: {"role":"assistant","content":[{"type":"text","text":"..."}]}
        - OpenAI format: {"choices":[{"message":{"content":"..."}}]}
        - OpenAI SDK response object with .choices attribute
        """
        import types

        # Unwrap generator — consume first yielded item
        if isinstance(response, types.GeneratorType):
            try:
                response = next(response)
            except StopIteration:
                return ""

        if not response:
            return ""

        if isinstance(response, dict):
            # Check for error
            if response.get("error"):
                raise RuntimeError(response.get("message", "LLM call failed"))

            # Claude format: content is a list of blocks
            content = response.get("content")
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        return block.get("text", "")

            # OpenAI format
            choices = response.get("choices", [])
            if choices:
                return choices[0].get("message", {}).get("content", "")

        # OpenAI SDK response object
        if hasattr(response, "choices") and response.choices:
            return response.choices[0].message.content or ""

        return ""

    def _call_llm_for_summary(self, conversation_text: str) -> str:
        """Call LLM to generate a concise summary of the conversation."""
        from agent.protocol.models import LLMRequest
        
        request = LLMRequest(
            messages=[{"role": "user", "content": SUMMARIZE_USER_PROMPT.format(conversation=conversation_text)}],
            temperature=0,
            max_tokens=500,
            stream=False,
            system=SUMMARIZE_SYSTEM_PROMPT,
        )
        
        response = self.llm_model.call(request)
        return self._extract_response_text(response)

    @staticmethod
    def _extract_first_meaningful_line(text: str, max_len: int = 120) -> str:
        """Extract the first meaningful line from assistant reply, skipping markdown noise."""
        import re
        for line in text.split("\n"):
            line = line.strip()
            if not line:
                continue
            # Skip markdown headings, horizontal rules, code fences, pure emoji/symbols
            if re.match(r'^(#{1,4}\s|```|---|\*\*\*|[-*]\s*$|[^\w\u4e00-\u9fff]{1,5}$)', line):
                continue
            # Strip leading markdown bold/emoji decorations
            cleaned = re.sub(r'^[\*#>\-\s]+', '', line).strip()
            cleaned = re.sub(r'^[\U0001f300-\U0001f9ff\u2600-\u27bf\s]+', '', cleaned).strip()
            if len(cleaned) >= 5:
                return cleaned[:max_len]
        return text.split("\n")[0].strip()[:max_len]

    @staticmethod
    def _extract_summary_fallback(messages: List[Dict], max_messages: int = 0) -> str:
        """
        Rule-based summary of discarded messages.
        Format: "用户问了X; 助手回答了Y" per event, compact and readable.
        """
        msgs = messages if max_messages == 0 else messages[-max_messages * 2:]

        events: List[str] = []
        current_user_text = ""
        for msg in msgs:
            role = msg.get("role", "")
            text = MemoryFlushManager._extract_text_from_content(msg.get("content", ""))
            if not text or not text.strip():
                continue
            text = text.strip()

            if role == "user":
                if len(text) <= 3:
                    continue
                current_user_text = text[:120]
            elif role == "assistant" and current_user_text:
                reply_summary = MemoryFlushManager._extract_first_meaningful_line(text)
                if reply_summary:
                    events.append(f"- 用户: {current_user_text} → 回复: {reply_summary}")
                else:
                    events.append(f"- 用户: {current_user_text}")
                current_user_text = ""

        if current_user_text:
            events.append(f"- 用户: {current_user_text}")

        return "\n".join(events[:10])
    
    @staticmethod
    def _extract_text_from_content(content) -> str:
        """Extract plain text from message content (string or content blocks)."""
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    parts.append(block.get("text", ""))
                elif isinstance(block, str):
                    parts.append(block)
            return "\n".join(parts)
        return ""

    @classmethod
    def _strip_scheduler_pairs(cls, messages: List[Dict]) -> List[Dict]:
        """Drop scheduler-injected user/assistant pairs from a flush batch.

        A scheduler user message starts with the ``[SCHEDULED]`` marker
        (written by ``AgentBridge.remember_scheduled_output``); the message
        immediately following it (if it is an assistant turn) is its paired
        output and is dropped together. Regular user/assistant turns and
        any tool_use / tool_result blocks are preserved as-is.
        """
        if not messages:
            return messages

        SCHEDULED_PREFIX = "[SCHEDULED]"
        result = []
        skip_next_assistant = False
        for msg in messages:
            if not isinstance(msg, dict):
                result.append(msg)
                skip_next_assistant = False
                continue
            role = msg.get("role")
            if skip_next_assistant and role == "assistant":
                skip_next_assistant = False
                continue
            skip_next_assistant = False
            if role == "user":
                text = cls._extract_text_from_content(msg.get("content", ""))
                if text.lstrip().startswith(SCHEDULED_PREFIX):
                    skip_next_assistant = True
                    continue
            result.append(msg)
        return result


def create_memory_files_if_needed(workspace_dir: Path, user_id: Optional[str] = None):
    """
    Create essential memory files if they don't exist.
    Only creates MEMORY.md; daily files are created lazily on first write.
    
    Args:
        workspace_dir: Workspace directory
        user_id: Optional user ID for user-specific files
    """
    memory_dir = workspace_dir / "memory"
    memory_dir.mkdir(parents=True, exist_ok=True)
    
    # Create main MEMORY.md in workspace root (always needed for bootstrap)
    if user_id:
        user_dir = memory_dir / "users" / user_id
        user_dir.mkdir(parents=True, exist_ok=True)
        main_memory = user_dir / "MEMORY.md"
    else:
        main_memory = Path(workspace_dir) / "MEMORY.md"
    
    if not main_memory.exists():
        main_memory.write_text("")


def ensure_daily_memory_file(workspace_dir: Path, user_id: Optional[str] = None) -> Path:
    """
    Ensure today's daily memory file exists, creating it only when actually needed.
    Called lazily before first write to daily memory.
    
    Args:
        workspace_dir: Workspace directory
        user_id: Optional user ID for user-specific files
        
    Returns:
        Path to today's memory file
    """
    memory_dir = workspace_dir / "memory"
    memory_dir.mkdir(parents=True, exist_ok=True)
    
    today = datetime.now().strftime("%Y-%m-%d")
    if user_id:
        user_dir = memory_dir / "users" / user_id
        user_dir.mkdir(parents=True, exist_ok=True)
        today_memory = user_dir / f"{today}.md"
    else:
        today_memory = memory_dir / f"{today}.md"
    
    if not today_memory.exists():
        today_memory.write_text(
            f"# Daily Memory: {today}\n\n"
        )
    
    return today_memory
