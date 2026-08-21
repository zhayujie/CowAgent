# encoding:utf-8
"""
Regression tests for fatal-error classification in the agent stream executor.

Both the context-overflow and message-format branches drop the entire
in-memory conversation, so a false positive costs the user their working
context. These cases pin the errors that must NOT be classified as fatal —
the previous keyword set matched generic words ("without", "each",
"must have", "not found") and read a bare "400" substring out of token
counts like 4000, which made an unrelated bad-model-name error wipe a
conversation.

They also pin that no code path deletes persisted history to recover, since
every load path already strips tool_use/tool_result blocks.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.protocol.agent_stream import (
    _is_context_overflow,
    _is_message_format_error,
)


class TestMessageFormatErrorDetection(unittest.TestCase):
    def _check(self, raw: str) -> bool:
        return _is_message_format_error(raw.lower())

    def test_real_pairing_errors_are_detected(self):
        for raw in [
            "Error code: 400 - messages.3: `tool_use` ids were found without "
            "`tool_result` blocks immediately after",
            "400 invalid_request_error: each `tool_use` block must have a "
            "corresponding `tool_result` block",
            "openai.BadRequestError: Error code: 400 - Invalid parameter: "
            "messages with role 'tool' must be a response to a preceeding "
            "message with 'tool_calls'",
            "MiniMax error 2013: tool result's tool id(call_x) not found, "
            "status: 400",
            "invalid_request: tool_call_id 'call_abc' not found",
        ]:
            self.assertTrue(self._check(raw), f"should be fatal: {raw}")

    def test_unrelated_400_errors_are_not_detected(self):
        """Each of these used to wipe the user's conversation."""
        for raw in [
            "Error code: 400 - model not found",
            "Error code: 400 - The model `gpt-5` does not exist",
            "400 invalid_request_error: 'max_tokens' must have a value",
            "HTTP 400: request rejected without a valid api key",
            "400 Bad Request: each field is required",
            "Error code: 400 - image exceeds the 5MB limit",
            "invalidparameter: temperature out of range",
        ]:
            self.assertFalse(self._check(raw), f"must not be fatal: {raw}")

    def test_token_count_is_not_read_as_http_400(self):
        """"4000" contains "400"; word boundaries must reject it."""
        for raw in [
            "500 upstream error: tool_result cache miss, max_tokens 4000",
            "503 unavailable while streaming tool_calls, budget 14000 tokens",
            "502 bad gateway: tool_use retry, limit 40096",
        ]:
            self.assertFalse(self._check(raw), f"must not be fatal: {raw}")

    def test_pairing_words_alone_are_not_enough(self):
        """A structural marker without any 400-class signal is not fatal."""
        self.assertFalse(self._check("429 rate limited on tool_use retry"))
        self.assertFalse(self._check("connection reset while sending tool_result"))


class TestContextOverflowDetection(unittest.TestCase):
    def _check(self, raw: str) -> bool:
        return _is_context_overflow(raw.lower())

    def test_real_overflow_errors_are_detected(self):
        for raw in [
            "This model's maximum context length is 128000 tokens",
            # The exact DeepSeek V4 error that started the retry loop.
            "This model's maximum context length is 1048576 tokens. However, "
            "you requested 1276733 tokens (892733 in the messages, 384000 in "
            "the completion). Please reduce the length of the messages or completion.",
            "400 invalid_request_error: prompt is too long: 250000 tokens",
            "[CONTEXT_OVERFLOW] stream aborted",
            "rate_limit_error: request_too_large",
            "context length exceeded",
            "429: too many tokens in request",
            "input tokens exceed the configured limit",
        ]:
            self.assertTrue(self._check(raw), f"should be overflow: {raw}")

    def test_oversized_upload_is_not_overflow(self):
        """A bare "too large" used to send an oversized upload down the
        overflow path, which ended in the history being cleared."""
        for raw in [
            "413 Request Entity Too Large",
            "400 Bad Request: file too large",
            "upload failed: image too large, max 5MB",
            "400 invalid_request_error: file too large, max size 20MB",
            "payload too large",
        ]:
            self.assertFalse(self._check(raw), f"must not be overflow: {raw}")


class TestNoAutomaticHistoryDeletion(unittest.TestCase):
    def test_stream_executor_has_no_session_purge_helper(self):
        import agent.protocol.agent_stream as agent_stream

        self.assertFalse(
            hasattr(agent_stream.AgentStreamExecutor, "_clear_session_db"),
            "recovery must not purge persisted history",
        )

    def test_no_module_clears_sessions_during_error_recovery(self):
        """clear_session may only be called for user-initiated actions."""
        import inspect

        import agent.protocol.agent_stream as agent_stream
        import bridge.agent_bridge as agent_bridge

        self.assertNotIn("clear_session", inspect.getsource(agent_stream))

        source = inspect.getsource(agent_bridge)
        # The one remaining call site is the explicit "new conversation" reset.
        self.assertEqual(source.count("store.clear_session("), 1)
        self.assertNotIn("get_conversation_store().clear_session(", source)


if __name__ == "__main__":
    unittest.main()
