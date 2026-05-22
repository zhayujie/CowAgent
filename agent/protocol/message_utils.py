"""
Message sanitizer — fix broken tool_use / tool_result pairs.

Provides two public helpers that can be reused across agent_stream.py
and any bot that converts messages to OpenAI format:

1. sanitize_claude_messages(messages)
   Operates on the internal Claude-format message list (in-place).

2. drop_orphaned_tool_results_openai(messages)
   Operates on an already-converted OpenAI-format message list,
   returning a cleaned copy.
"""

from __future__ import annotations

from typing import Dict, List, Set

from common.log import logger

_SYNTH_TOOL_ERR = (
    "Error: Missing tool_result adjacent to tool_use (session repair). "
    "The conversation history was inconsistent; continue from here."
)


def _repair_tool_use_adjacency(messages: List[Dict]) -> int:
    """
    Anthropic requires: after assistant content with tool_use, the next message
    must be user content listing tool_result for every tool_use id (same user msg).

    Valid histories satisfy this at every such assistant; the loop only mutates
    when that condition fails (broken persistence, bad trims, etc.).
    """

    def _synth_block(tid: str) -> Dict:
        return {
            "type": "tool_result",
            "tool_use_id": tid,
            "content": _SYNTH_TOOL_ERR,
            "is_error": True,
        }

    repairs = 0
    i = 0
    while i < len(messages):
        msg = messages[i]
        if msg.get("role") != "assistant":
            i += 1
            continue

        content = msg.get("content", [])
        if not isinstance(content, list):
            i += 1
            continue

        required = [
            b.get("id")
            for b in content
            if isinstance(b, dict) and b.get("type") == "tool_use" and b.get("id")
        ]
        if not required:
            i += 1
            continue

        req_set = set(required)
        if i + 1 >= len(messages):
            messages.append({
                "role": "user",
                "content": [_synth_block(tid) for tid in required],
            })
            logger.warning(
                "⚠️ Appended synthetic tool_result after trailing assistant tool_use"
            )
            repairs += 1
            break

        nxt = messages[i + 1]
        if nxt.get("role") != "user":
            messages.insert(
                i + 1,
                {"role": "user", "content": [_synth_block(tid) for tid in required]},
            )
            logger.warning(
                "⚠️ Inserted synthetic tool_result user after tool_use "
                f"(next role={nxt.get('role')!r})"
            )
            repairs += 1
            i += 2
            continue

        nc = nxt.get("content", [])
        if not isinstance(nc, list):
            messages.insert(
                i + 1,
                {"role": "user", "content": [_synth_block(tid) for tid in required]},
            )
            repairs += 1
            i += 2
            continue

        present = {
            b.get("tool_use_id")
            for b in nc
            if isinstance(b, dict) and b.get("type") == "tool_result" and b.get("tool_use_id")
        }
        if req_set <= present:
            i += 1
            continue

        missing = [tid for tid in required if tid not in present]
        nxt["content"] = [_synth_block(tid) for tid in missing] + nc
        logger.warning(
            "⚠️ Prepended synthetic tool_result for Anthropic adjacency "
            f"(missing_ids={missing})"
        )
        repairs += len(missing)
        i += 1

    return repairs


# ------------------------------------------------------------------ #
# Claude-format sanitizer (used by agent_stream)
# ------------------------------------------------------------------ #

def sanitize_claude_messages(messages: List[Dict]) -> int:
    """
    Validate and fix a Claude-format message list **in-place**.

    Fixes handled:
    - Anthropic adjacency: assistant tool_use must be immediately followed by
      user message(s) containing matching tool_result blocks
    - Leading orphaned tool_result user messages
    - Mid-list tool_result blocks whose tool_use_id has no matching
      tool_use in any preceding assistant message

    Returns: number of removals plus adjacency repair operations (inserts/prepends).
    """
    if not messages:
        return 0

    removed = 0

    # 1. Adjacency repair (Anthropic: tool_result must be in the next user message)
    adj_repairs = _repair_tool_use_adjacency(messages)

    # 2. Remove leading orphaned tool_result user messages
    while messages:
        first = messages[0]
        if first.get("role") != "user":
            break
        content = first.get("content", [])
        if isinstance(content, list) and _has_block_type(content, "tool_result") \
                and not _has_block_type(content, "text"):
            logger.warning("⚠️ Removing leading orphaned tool_result user message")
            messages.pop(0)
            removed += 1
        else:
            break

    # 3. Iteratively remove unmatched tool_use / tool_result until stable.
    #    Removing one broken message can orphan others (e.g. an assistant msg
    #    with both matched and unmatched tool_use — deleting it orphans the
    #    previously-matched tool_result).  Loop until clean.
    for _ in range(5):
        use_ids: Set[str] = set()
        result_ids: Set[str] = set()
        for msg in messages:
            for block in (msg.get("content") or []):
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "tool_use" and block.get("id"):
                    use_ids.add(block["id"])
                elif block.get("type") == "tool_result" and block.get("tool_use_id"):
                    result_ids.add(block["tool_use_id"])

        bad_use = use_ids - result_ids
        bad_result = result_ids - use_ids
        if not bad_use and not bad_result:
            break

        pass_removed = 0
        i = 0
        while i < len(messages):
            msg = messages[i]
            role = msg.get("role")
            content = msg.get("content", [])
            if not isinstance(content, list):
                i += 1
                continue

            if role == "assistant" and bad_use and any(
                isinstance(b, dict) and b.get("type") == "tool_use"
                and b.get("id") in bad_use for b in content
            ):
                logger.warning(f"⚠️ Removing assistant msg with unmatched tool_use")
                messages.pop(i)
                pass_removed += 1
                continue

            if role == "user" and bad_result and _has_block_type(content, "tool_result"):
                has_bad = any(
                    isinstance(b, dict) and b.get("type") == "tool_result"
                    and b.get("tool_use_id") in bad_result for b in content
                )
                if has_bad:
                    if not _has_block_type(content, "text"):
                        logger.warning(f"⚠️ Removing user msg with unmatched tool_result")
                        messages.pop(i)
                        pass_removed += 1
                        continue
                    else:
                        before = len(content)
                        msg["content"] = [
                            b for b in content
                            if not (isinstance(b, dict) and b.get("type") == "tool_result"
                                    and b.get("tool_use_id") in bad_result)
                        ]
                        pass_removed += before - len(msg["content"])

            i += 1

        removed += pass_removed
        if pass_removed == 0:
            break

    # 4. Removals above can break adjacency; re-run repair only if something was removed.
    if removed:
        adj_repairs += _repair_tool_use_adjacency(messages)

    if removed:
        logger.info(f"🔧 Message validation: removed {removed} broken message(s)")
    if adj_repairs:
        logger.info(f"🔧 Message validation: adjacency repairs={adj_repairs}")
    return removed + adj_repairs


# ------------------------------------------------------------------ #
# OpenAI-format sanitizer (used by minimax_bot, openai_compatible_bot)
# ------------------------------------------------------------------ #

def drop_orphaned_tool_results_openai(messages: List[Dict]) -> List[Dict]:
    """
    Return a copy of *messages* (OpenAI format) with any ``role=tool``
    messages removed if their ``tool_call_id`` does not match a
    ``tool_calls[].id`` in a preceding assistant message.
    """
    known_ids: Set[str] = set()
    cleaned: List[Dict] = []
    for msg in messages:
        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            for tc in msg["tool_calls"]:
                tc_id = tc.get("id", "")
                if tc_id:
                    known_ids.add(tc_id)

        if msg.get("role") == "tool":
            ref_id = msg.get("tool_call_id", "")
            if ref_id and ref_id not in known_ids:
                logger.warning(
                    f"[MessageSanitizer] Dropping orphaned tool result "
                    f"(tool_call_id={ref_id} not in known ids)"
                )
                continue
        cleaned.append(msg)
    return cleaned


# ------------------------------------------------------------------ #
# Internal helpers
# ------------------------------------------------------------------ #

def _has_block_type(content: list, block_type: str) -> bool:
    return any(
        isinstance(b, dict) and b.get("type") == block_type
        for b in content
    )


def _extract_text_from_content(content) -> str:
    """Extract plain text from a message content field (str or list of blocks)."""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = [
            b.get("text", "")
            for b in content
            if isinstance(b, dict) and b.get("type") == "text"
        ]
        return "\n".join(p for p in parts if p).strip()
    return ""


def compress_turn_to_text_only(turn: Dict) -> Dict:
    """
    Compress a full turn (with tool_use/tool_result chains) into a lightweight
    text-only turn that keeps only the first user text and the last assistant text.

    This preserves the conversational context (what the user asked and what the
    agent concluded) while stripping out the bulky intermediate tool interactions.

    Returns a new turn dict with a ``messages`` list; the original is not mutated.
    """
    user_text = ""
    last_assistant_text = ""

    for msg in turn["messages"]:
        role = msg.get("role")
        content = msg.get("content", [])

        if role == "user":
            if isinstance(content, list) and _has_block_type(content, "tool_result"):
                continue
            if not user_text:
                user_text = _extract_text_from_content(content)

        elif role == "assistant":
            text = _extract_text_from_content(content)
            if text:
                last_assistant_text = text

    compressed_messages = []
    if user_text:
        compressed_messages.append({
            "role": "user",
            "content": [{"type": "text", "text": user_text}]
        })
    if last_assistant_text:
        compressed_messages.append({
            "role": "assistant",
            "content": [{"type": "text", "text": last_assistant_text}]
        })

    return {"messages": compressed_messages}
