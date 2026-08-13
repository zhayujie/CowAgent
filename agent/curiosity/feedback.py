"""Conservative feedback classification with a safe LLM fallback."""

from __future__ import annotations

import inspect
import json
import re
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Iterable, Optional, Union


@dataclass(frozen=True)
class Feedback:
    type: str
    weight: int


Analyzer = Callable[[str], Union[Any, Awaitable[Any]]]


class FeedbackEngine:
    """Classify explicit feedback and optionally defer to an LLM.

    Keyword matching is deliberately conservative for unsegmented CJK text:
    a term must end at punctuation, whitespace, the end of the message, or a
    contrast conjunction.  This avoids treating ``真好`` inside ``真好看`` as
    an exact feedback token without adding a mandatory tokenizer dependency.
    """

    DEFAULT_POSITIVE = ("真好", "喜欢", "满意", "有趣")
    DEFAULT_NEGATIVE = ("无聊", "讨厌", "失望", "不好")
    _CJK = re.compile(r"[\u3400-\u9fff]")
    _RIGHT_BOUNDARIES = frozenset("但却可而和也呢啊呀哦嘛吧，。！？；：,.!?;:\t\r\n ")

    def __init__(
        self,
        positive_keywords: Iterable[str] = DEFAULT_POSITIVE,
        negative_keywords: Iterable[str] = DEFAULT_NEGATIVE,
        llm_analyzer: Optional[Analyzer] = None,
    ) -> None:
        self.positive_keywords = tuple(filter(None, positive_keywords))
        self.negative_keywords = tuple(filter(None, negative_keywords))
        self.llm_analyzer = llm_analyzer

    @classmethod
    def _contains_exact(cls, message: str, keyword: str) -> bool:
        start = 0
        while True:
            index = message.find(keyword, start)
            if index < 0:
                return False
            end = index + len(keyword)
            if cls._CJK.search(keyword):
                right_ok = end == len(message) or message[end] in cls._RIGHT_BOUNDARIES
                if right_ok:
                    return True
            else:
                left_ok = index == 0 or not message[index - 1].isalnum()
                right_ok = end == len(message) or not message[end].isalnum()
                if left_ok and right_ok:
                    return True
            start = index + 1

    def _keyword_feedback(self, message: str) -> Optional[Feedback]:
        positive = sum(self._contains_exact(message, word) for word in self.positive_keywords)
        negative = sum(self._contains_exact(message, word) for word in self.negative_keywords)
        if not positive and not negative:
            return None
        weight = positive - negative
        if weight > 0:
            return Feedback("positive", weight)
        if weight < 0:
            return Feedback("negative", weight)
        return Feedback("neutral", 0)

    @staticmethod
    def _coerce_llm_result(value: Any) -> Feedback:
        if isinstance(value, str):
            value = json.loads(value)
        if not isinstance(value, dict):
            raise ValueError("sentiment result must be an object")
        feedback_type = value.get("type")
        weight = value.get("weight")
        if feedback_type not in {"positive", "negative", "neutral"}:
            raise ValueError("invalid feedback type")
        if not isinstance(weight, int) or isinstance(weight, bool):
            raise ValueError("invalid feedback weight")
        return Feedback(feedback_type, weight)

    async def _llm_analyze_sentiment(self, message: str) -> Feedback:
        if self.llm_analyzer is None:
            return Feedback("neutral", 0)
        try:
            value = self.llm_analyzer(message)
            if inspect.isawaitable(value):
                value = await value
            return self._coerce_llm_result(value)
        except Exception:
            return Feedback("neutral", 0)

    async def analyze(self, message: str) -> Feedback:
        keyword_result = self._keyword_feedback(message)
        if keyword_result is not None:
            return keyword_result
        return await self._llm_analyze_sentiment(message)
