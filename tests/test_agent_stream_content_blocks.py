# encoding:utf-8
"""Thinking/reasoning content blocks must stay off the visible reply.

Some providers (Anthropic-shaped adapters, MiMo sync wrappers) stream
``content`` as a list of blocks. ``AgentStream._split_content_blocks`` routes
thinking/reasoning blocks to the reasoning channel and keeps only real text as
the visible content, which is what stops CoT from leaking into IM channels as
an "Agent Reply".
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.protocol.agent_stream import AgentStreamExecutor


def test_plain_string_content_passes_through():
    text, reasoning = AgentStreamExecutor._split_content_blocks("hello world")
    assert text == "hello world"
    assert reasoning == ""


def test_thinking_block_kept_out_of_visible_text():
    content = [
        {"type": "thinking", "thinking": "let me count", "signature": "sig"},
        {"type": "text", "text": "42"},
    ]
    text, reasoning = AgentStreamExecutor._split_content_blocks(content)
    assert text == "42"
    assert reasoning == "let me count"


def test_reasoning_block_and_text_delta_variants():
    content = [
        {"type": "reasoning", "reasoning": "step 1"},
        {"type": "text_delta", "text": "answer "},
        {"type": None, "text": "here"},
    ]
    text, reasoning = AgentStreamExecutor._split_content_blocks(content)
    assert text == "answer here"
    assert reasoning == "step 1"


def test_thinking_only_yields_no_visible_text():
    content = [{"type": "thinking", "thinking": "internal only"}]
    text, reasoning = AgentStreamExecutor._split_content_blocks(content)
    assert text == ""
    assert reasoning == "internal only"


def test_malformed_blocks_are_ignored():
    content = ["not a dict", {"type": "text", "text": "ok"}, 123]
    text, reasoning = AgentStreamExecutor._split_content_blocks(content)
    assert text == "ok"
    assert reasoning == ""
