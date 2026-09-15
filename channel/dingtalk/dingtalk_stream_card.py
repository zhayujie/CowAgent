"""DingTalk AI-card streaming: markdown subset + incremental card updates.

Used by the DingTalk channel when dingtalk_card_enabled is true.
The SDK lifecycle is ai_start -> ai_streaming -> ai_finish/ai_fail so the
card leaves PROCESSING instead of sitting on a spinner after the turn ends.
"""
from __future__ import annotations

import logging
import queue
import re
import threading
import time
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

DINGTALK_AI_CARD_TITLE = "📌 内容由AI生成"
_STREAM_THROTTLE_S = 0.15
_FENCE_RE = re.compile(r"```[\w+-]*\n.*?```", re.DOTALL)
_HTML_TAG_RE = re.compile(r"</?([a-zA-Z][a-zA-Z0-9]*)\b[^>]*>")
_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_BR_RE = re.compile(r"<br\s*/?>", re.IGNORECASE)
_IMG_RE = re.compile(
    r'<img\b[^>]*\bsrc=["\']([^"\']+)["\'][^>]*>',
    re.IGNORECASE,
)
_TASK_ITEM_RE = re.compile(r"^(\s*[-*+])\s+\[[ xX]\]\s+", re.MULTILINE)
_BLANK_RE = re.compile(r"\n{3,}")


def sanitize_dingtalk_markdown(text: str) -> str:
    """Keep a DingTalk-safe markdown subset; degrade HTML to plain markdown.

    DingTalk AI cards render a subset of GFM: headings, emphasis, lists,
    links, images, fenced code, and simple tables. HTML and task-list
    checkboxes are not reliable, so they are converted or stripped. Fenced
    code is left untouched. If sanitising would drop all content, fall back
    to tag-stripped plain text instead of returning an empty card.
    """
    if text is None:
        return ""
    original = str(text)
    if not original:
        return ""

    normalised = original.replace("\r\n", "\n").replace("\r", "\n")

    fences: list[str] = []

    def _hold_fence(match: re.Match) -> str:
        fences.append(match.group(0))
        return f"\x00FENCE{len(fences) - 1}\x00"

    protected = _FENCE_RE.sub(_hold_fence, normalised)
    protected = _HTML_COMMENT_RE.sub("", protected)
    protected = _BR_RE.sub("\n", protected)
    protected = _IMG_RE.sub(lambda match: f"![]({match.group(1)})", protected)
    stripped = _HTML_TAG_RE.sub("", protected)
    stripped = _TASK_ITEM_RE.sub(r"\1 ", stripped)
    stripped = _BLANK_RE.sub("\n\n", stripped)

    for index, fence in enumerate(fences):
        stripped = stripped.replace(f"\x00FENCE{index}\x00", fence)

    result = stripped.strip()
    if result:
        return result
    fallback = _HTML_TAG_RE.sub("", normalised).strip()
    return fallback or original.strip()


def build_dingtalk_card_finish_payload(context, markdown: str):
    """Match generate_button_markdown_content for image replies."""
    image_url = context.get("image_url") if context is not None else None
    prompt_en = context.get("promptEn") if context is not None else None
    body = sanitize_dingtalk_markdown(markdown)
    buttons = []
    if image_url and prompt_en:
        buttons = [
            {
                "text": "查看原图",
                "url": image_url,
                "iosUrl": image_url,
                "color": "blue",
            }
        ]
        body = sanitize_dingtalk_markdown(
            f"{prompt_en}\n\n![]({image_url})\n\n{body}"
        )
    return body, buttons


class DingTalkCardStreamer:
    """Consume agent on_event payloads and drive one AI markdown card."""

    def __init__(
        self,
        start_card: Callable[[], Any],
        context,
        immediate: bool = False,
        throttle_s: float = _STREAM_THROTTLE_S,
    ):
        self._start_card = start_card
        self.context = context
        self.immediate = immediate
        self.throttle_s = throttle_s
        self.card = None
        self.disabled = False
        self.cancelled = False
        self.committed = ""
        self.current = ""
        self._lock = threading.Lock()
        self._queue: queue.Queue = queue.Queue()
        self._worker: Optional[threading.Thread] = None
        self._last_push = 0.0
        self._last_streamed = ""

    def handle_event(self, event: dict) -> None:
        event = event or {}
        event_type = event.get("type")
        data = event.get("data") or {}

        with self._lock:
            if self.disabled:
                return

        if event_type == "message_update":
            delta = data.get("delta") or ""
            if not delta:
                return
            if self._ensure_card() is None:
                return
            with self._lock:
                self.current += str(delta)
            self._enqueue_stream(force=False)
            return

        if event_type == "message_end":
            tool_calls = data.get("tool_calls") or []
            if not tool_calls:
                return
            with self._lock:
                if self.current.strip():
                    self.committed += self.current.rstrip() + "\n\n---\n\n"
                    self.current = ""
            if self.card is not None:
                self._enqueue_stream(force=True)
            return

        if event_type == "agent_cancelled":
            with self._lock:
                self.cancelled = True
            return

        if event_type == "agent_end":
            self._on_agent_end(data)
            return

    def _on_agent_end(self, data: dict) -> None:
        with self._lock:
            cancelled = self.cancelled or bool(data.get("cancelled"))
            accumulated = self.committed + self.current
            has_card = self.card is not None

        final_response = data.get("final_response")
        if cancelled:
            markdown = accumulated
            if not markdown.strip() and not has_card:
                return
            if self._ensure_card() is None:
                return
            if not markdown.strip():
                self._submit("fail", wait=True)
            else:
                body, buttons = build_dingtalk_card_finish_payload(
                    self.context, markdown
                )
                self._submit("finish", (body, buttons), wait=True)
            self._mark_streamed()
            return

        markdown = str(final_response) if final_response else accumulated
        if not markdown and not has_card:
            return
        if self._ensure_card() is None:
            return
        body, buttons = build_dingtalk_card_finish_payload(self.context, markdown)
        self._submit("finish", (body, buttons), wait=True)
        self._mark_streamed()

    def _mark_streamed(self) -> None:
        if self.context is None:
            return
        if self.disabled or self.card is None:
            return
        self.context["dingtalk_streamed"] = True

    def _ensure_card(self):
        with self._lock:
            if self.disabled:
                return None
            if self.card is not None:
                return self.card
        try:
            card = self._start_card()
        except Exception as exc:
            logger.warning("[DingTalk] Stream: create AI card failed: %s", exc)
            with self._lock:
                self.disabled = True
            return None
        if card is None or not getattr(card, "card_instance_id", None):
            logger.warning(
                "[DingTalk] Stream: create AI card failed (empty card id). "
                "Falling back to a one-shot reply."
            )
            with self._lock:
                self.disabled = True
            return None
        with self._lock:
            self.card = card
        self._start_worker()
        return card

    def _start_worker(self) -> None:
        if self.immediate or self._worker is not None:
            return
        worker = threading.Thread(
            target=self._run_worker,
            name="dingtalk-card-stream",
            daemon=True,
        )
        self._worker = worker
        worker.start()

    def _run_worker(self) -> None:
        while True:
            item = self._queue.get()
            if item is None:
                return
            kind, payload = item
            self._apply(kind, payload)

    def _enqueue_stream(self, force: bool) -> None:
        with self._lock:
            markdown = sanitize_dingtalk_markdown(self.committed + self.current)
        now = time.monotonic()
        if not force:
            if markdown == self._last_streamed:
                return
            if now - self._last_push < self.throttle_s:
                return
        self._last_push = now
        self._last_streamed = markdown
        self._submit("stream", markdown, wait=False)

    def _submit(self, kind: str, payload=None, wait: bool = False) -> None:
        if self.immediate:
            self._apply(kind, payload)
            return
        if self._worker is None:
            self._start_worker()
        self._queue.put((kind, payload))
        if wait:
            self._queue.put(None)
            if self._worker is not None:
                self._worker.join(timeout=8)

    def _apply(self, kind: str, payload) -> None:
        card = self.card
        if card is None:
            return
        try:
            if kind == "stream":
                card.ai_streaming(payload, append=False)
            elif kind == "finish":
                markdown, buttons = payload
                card.ai_finish(markdown=markdown, button_list=buttons or [])
            elif kind == "fail":
                card.ai_fail()
        except Exception as exc:
            logger.warning("[DingTalk] Stream: card %s failed: %s", kind, exc)
