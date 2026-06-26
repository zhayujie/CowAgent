"""Skill purification subsystem for CowAgent.

Implements four purification capabilities:
1. Usage tracking + auto-cleanup of stale skills
2. Version history + regression detection + auto-rollback
3. Semantic conflict detection before creating new skills
4. Evolution quality scoring and reporting

All operations are safe and non-destructive: cleanup disables rather than
deletes, rollback uses existing backup infrastructure, and conflict detection
is advisory (logged + surfaced to the evolution agent).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from common.log import logger

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Default threshold for auto-disabling unused skills (days).
DEFAULT_UNUSED_DAYS = 90

# Maximum version history entries per skill.
MAX_VERSION_HISTORY = 10

# Regression count threshold for auto-rollback (can be overridden by config).
REGRESSION_ROLLBACK_THRESHOLD = 3

# LLM rate limit for regression detection (calls per minute, can be overridden by config).
LLM_RATE_LIMIT_PER_MINUTE = 10

# Cleanup retention defaults (can be overridden by config).
TRACKING_RETENTION_DAYS = 30
BACKUPS_TO_KEEP = 10

# Semantic similarity threshold for conflict detection (0-1).
CONFLICT_SIMILARITY_THRESHOLD = 0.80

# Quality report lookback window (days).
DEFAULT_REPORT_DAYS = 30

# Quick pre-filter keywords: if NONE of these appear, skip LLM call entirely.
# These are precise indicators of dissatisfaction — not used for final judgment.
REGRESSION_PREFILTER_KEYWORDS = [
    # Chinese indicators (precise phrases only)
    "不对", "错了", "搞错", "理解错", "答错", "回滚", "撤回", "撤销",
    "不行", "有问题", "不满意", "失望", "有误", "误解",
    # English indicators (precise phrases only)
    "wrong", "incorrect", "error", "mistake", "misunderstood",
    "rollback", "revert", "undo", "disappointed", "unsatisfied",
]

# Exclusion patterns: if these appear, skip LLM even if keywords match
REGRESSION_PREFILTER_EXCLUSIONS = [
    # Chinese exclusions
    "不错", "是不是", "对不对", "没错", "不是问题",
    # English exclusions
    "not bad", "is it", "right?", "no problem",
]

# Rate limiting for LLM calls
_LLM_CALL_HISTORY = []  # List of timestamps
_LLM_CALL_LOCK = threading.Lock()
_LLM_CALL_WINDOW = 60  # seconds

def _get_llm_rate_limit() -> int:
    """Get LLM rate limit from config, fallback to default."""
    try:
        from config import conf
        return conf().get("purification_llm_rate_limit", LLM_RATE_LIMIT_PER_MINUTE)
    except Exception:
        return LLM_RATE_LIMIT_PER_MINUTE

# LLM judgment prompt for regression detection
REGRESSION_JUDGMENT_PROMPT = """你是一个对话质量分析专家。请判断用户的最新消息是否**明确表达对 AI 助手回答的不满或纠正意图**。

**核心原则**：只有当用户**明确指出 AI 的回答有问题**时才返回 YES。模糊的请求、技术讨论、操作指令都返回 NO。

## 判断标准

### 返回 YES（退化信号）的情况：
1. **明确批评 AI 的回答**：
   - "你回答错了"、"你的理解有误"、"回答不对"
   - "wrong answer"、"your answer is incorrect"
   - "你搞错了"、"理解错了"

2. **明确要求 AI 重新回答**（带有批评语气）：
   - "重新回答这个问题"、"请重新解释"
   - "try again with a different approach"

3. **表达对 AI 回答质量的失望**：
   - "这不是我想要的回答"、"not what I asked for"
   - "你的回答没用"、"this doesn't help"

4. **要求撤销 AI 的操作**：
   - "撤销刚才的修改"、"rollback your changes"

### 返回 NO（不是退化信号）的情况：
1. **模糊的请求或询问**（即使包含"重新"、"再试"等词）：
   - "能不能再试一次" → NO（礼貌请求，不是批评）
   - "可以再解释一下吗" → NO（请求澄清）
   - "try again" → NO（可能是正常重试）

2. **讨论方案、代码、配置本身**（不是批评 AI）：
   - "这个方案不行" → NO（讨论方案，不是批评 AI 的回答）
   - "这个代码有 bug" → NO（讨论代码质量）
   - "这个配置不对" → NO（讨论配置本身）
   - "there's a bug in the code" → NO

3. **正常的技术操作请求**：
   - "帮我重新部署" → NO（操作请求）
   - "重新安装依赖" → NO（操作请求）
   - "undo git commit" → NO（Git 操作）
   - "rollback the database" → NO（数据库操作）

4. **询问问题**：
   - "这个对吗？" → NO（询问）
   - "is this correct?" → NO（询问）
   - "我不太理解" → NO（表达困惑，不是批评）

## 关键区别示例

| 用户消息 | 判断 | 原因 |
|---------|------|------|
| "你回答错了" | YES | 明确批评 AI 的回答 |
| "这个代码有 bug" | NO | 讨论代码本身，不是 AI 的回答 |
| "能不能再试一次" | NO | 礼貌请求，没有批评语气 |
| "重新回答这个问题" | YES | 明确要求重新回答（暗示之前回答不好） |
| "这个方案不行" | NO | 讨论方案本身，不是批评 AI |
| "你的理解有误" | YES | 明确批评 AI 的理解 |
| "帮我重新部署" | NO | 正常操作请求 |
| "撤销刚才的修改" | YES | 要求撤销 AI 的操作 |

## 判断流程
1. 用户是否在**直接批评 AI 的回答/理解/行为**？→ YES
2. 用户是否在**讨论技术方案、代码、配置本身**？→ NO
3. 用户是否在**提出操作请求**（即使包含"重新"、"undo"等词）？→ NO
4. 用户是否在**礼貌地询问或请求**？→ NO

请只返回 YES 或 NO，不要解释。

用户消息：{user_message}

最近对话上下文（可选）：
{context}

判断结果："""


# ---------------------------------------------------------------------------
# 1. Usage Tracking
# ---------------------------------------------------------------------------

def record_skill_usage(skills_config: Dict[str, dict], skill_name: str) -> Dict[str, dict]:
    """Record a skill usage event in skills_config. Returns updated config.

    Adds/updates ``usage_stats`` with ``last_used``, ``use_count``, ``first_used``.
    """
    if skill_name not in skills_config:
        return skills_config

    now_iso = datetime.now().isoformat(timespec="seconds")
    entry = skills_config[skill_name]

    if "usage_stats" not in entry:
        entry["usage_stats"] = {
            "first_used": now_iso,
            "use_count": 0,
            "last_used": now_iso,
        }

    stats = entry["usage_stats"]
    stats["last_used"] = now_iso
    stats["use_count"] = stats.get("use_count", 0) + 1
    if "first_used" not in stats:
        stats["first_used"] = now_iso

    return skills_config


def find_unused_skills(
    skills_config: Dict[str, dict],
    days_threshold: int = DEFAULT_UNUSED_DAYS,
) -> List[Tuple[str, dict]]:
    """Find enabled skills that haven't been used within ``days_threshold``.

    Returns list of (skill_name, usage_stats) tuples.
    Skills that have never been used (no usage_stats) are NOT included —
    they may be newly installed.
    """
    cutoff = datetime.now() - timedelta(days=days_threshold)
    unused = []

    for name, config in skills_config.items():
        if not config.get("enabled", True):
            continue  # already disabled

        stats = config.get("usage_stats")
        if not stats:
            continue  # never used — skip (don't auto-disable fresh installs)

        last_used_str = stats.get("last_used")
        if not last_used_str:
            continue

        try:
            last_used = datetime.fromisoformat(last_used_str)
        except (ValueError, TypeError):
            continue

        if last_used < cutoff:
            unused.append((name, stats))

    return unused


# ---------------------------------------------------------------------------
# 2. Version History + Regression Detection
# ---------------------------------------------------------------------------

def compute_content_hash(content: str) -> str:
    """Compute a short hash of skill content for version tracking."""
    return hashlib.md5(content.encode("utf-8")).hexdigest()[:12]


def record_skill_version(
    skills_config: Dict[str, dict],
    skill_name: str,
    backup_id: Optional[str],
    change_summary: str,
    content: str,
) -> Dict[str, dict]:
    """Record a new version entry for a skill after evolution modifies it.

    Returns updated skills_config.
    """
    if skill_name not in skills_config:
        return skills_config

    entry = skills_config[skill_name]
    if "version_history" not in entry:
        entry["version_history"] = []

    # Use last version number + 1 to ensure monotonically increasing versions
    # even after history truncation (len-based approach would stall at MAX+1).
    if entry["version_history"]:
        version = entry["version_history"][-1]["version"] + 1
    else:
        version = 1
    content_hash = compute_content_hash(content)

    entry["version_history"].append({
        "version": version,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "evolution_backup_id": backup_id,
        "change_summary": change_summary[:200],  # cap summary length
        "content_hash": content_hash,
        "regression_count": 0,
    })

    # Keep only the most recent MAX_VERSION_HISTORY entries.
    entry["version_history"] = entry["version_history"][-MAX_VERSION_HISTORY:]

    return skills_config


def mark_skill_regression(
    skills_config: Dict[str, dict],
    skill_name: str,
) -> Tuple[Dict[str, dict], int]:
    """Mark a regression on the latest version of a skill.

    This function only increments the regression counter. The caller is
    responsible for checking if the count reaches the threshold and deciding
    whether to rollback.

    Returns (updated_config, current_regression_count).
    """
    if skill_name not in skills_config:
        return skills_config, 0

    entry = skills_config[skill_name]
    version_history = entry.get("version_history", [])
    if not version_history:
        return skills_config, 0

    latest = version_history[-1]
    latest["regression_count"] = latest.get("regression_count", 0) + 1
    
    current_count = latest["regression_count"]
    logger.debug(
        f"[Purification] Skill '{skill_name}' v{latest['version']} "
        f"regression count: {current_count}"
    )

    return skills_config, current_count


def detect_regression_signal_prefilter(user_message: str) -> bool:
    """Fast keyword pre-filter. Returns True if the message MIGHT be a regression signal.
    
    This is a cheap check to avoid calling the LLM for every message.
    If this returns False, the message is definitely NOT a regression signal.
    If this returns True, call detect_regression_signal_llm() for final judgment.
    
    Logic: check keywords first. If a keyword matches, return True even if an
    exclusion also matches (the message is ambiguous — let LLM decide).
    Exclusions only suppress the result when NO keyword matches at all, which
    is already the default False return.
    """
    if not user_message:
        return False
    msg_lower = user_message.lower()
    
    # Check for keywords first — if any match, this MIGHT be a regression signal.
    # Even if an exclusion pattern also appears (e.g. "不错，但你搞错了" contains
    # both "不错" and "搞错"), we still pass to LLM for accurate judgment.
    has_keyword = any(kw in msg_lower for kw in REGRESSION_PREFILTER_KEYWORDS)
    if not has_keyword:
        return False
    
    # Keyword matched. Check if it's a pure false-positive from an exclusion
    # substring (e.g. "不错" alone shouldn't trigger, but our keywords are
    # precise phrases like "错了"/"搞错" which don't appear in "不错").
    # If BOTH keyword and exclusion match, it's ambiguous — let LLM decide.
    return True


def _check_rate_limit() -> bool:
    """Check if we can make an LLM call (rate limiting).
    
    Returns:
        True if allowed, False if rate limit exceeded.
    """
    global _LLM_CALL_HISTORY
    now = time.time()
    
    with _LLM_CALL_LOCK:
        # Remove old entries outside the window
        _LLM_CALL_HISTORY = [t for t in _LLM_CALL_HISTORY if now - t < _LLM_CALL_WINDOW]
        
        # Check if we're at the limit (use config value)
        llm_limit = _get_llm_rate_limit()
        if len(_LLM_CALL_HISTORY) >= llm_limit:
            return False
        
        # Record this call
        _LLM_CALL_HISTORY.append(now)
        return True


def _extract_text_from_content(content) -> str:
    """Extract text from message content, handling both string and multimodal list formats.
    
    Args:
        content: Either a string or a list of content blocks (for multimodal messages)
    
    Returns:
        Extracted text string
    """
    if isinstance(content, str):
        return content
    elif isinstance(content, list):
        # Multimodal format: list of content blocks
        text_parts = []
        for block in content:
            if isinstance(block, dict):
                if block.get("type") == "text" and "text" in block:
                    text_parts.append(block["text"])
                elif "text" in block:
                    text_parts.append(block["text"])
        return " ".join(text_parts)
    else:
        return str(content)


def detect_regression_signal_llm(
    user_message: str,
    context_messages: Optional[List[Dict]] = None,
) -> bool:
    """Use LLM to accurately judge if a user message is a regression signal.
    
    Args:
        user_message: The user's latest message
        context_messages: Recent conversation history (list of {role, content} dicts)
    
    Returns:
        True if the LLM judges this as a regression signal, False otherwise.
        Returns False on any error (conservative: don't trigger rollback on uncertainty).
    """
    if not user_message:
        return False
    
    # Check rate limit
    if not _check_rate_limit():
        logger.debug("[Purification] Rate limit exceeded, skipping LLM call")
        return False
    
    # Build context summary (last 3 turns max)
    context_str = ""
    if context_messages:
        recent = context_messages[-6:]  # last 3 turns (user+assistant pairs)
        for msg in recent:
            role = msg.get("role", "")
            content = msg.get("content", "")
            # Extract text from content (handles multimodal messages)
            text = _extract_text_from_content(content)
            if role == "user":
                context_str += f"用户: {text[:200]}\n"
            elif role == "assistant":
                context_str += f"助手: {text[:200]}\n"
    
    prompt = REGRESSION_JUDGMENT_PROMPT.format(
        user_message=user_message,
        context=context_str if context_str else "（无上下文）"
    )
    
    try:
        from dashscope import Generation
        from http import HTTPStatus
        from config import conf
        
        # Get API key (thread-safe: pass directly, don't modify os.environ)
        api_key = os.environ.get("DASHSCOPE_API_KEY") or conf().get("dashscope_api_key")
        if not api_key:
            logger.warning("[Purification] No dashscope API key available")
            return False  # Conservative: don't trigger rollback without verification
        
        # Use a lightweight model for fast judgment
        model = conf().get("purification_judgment_model", "qwen-turbo")
        
        messages = [{"role": "user", "content": prompt}]
        
        # Pass api_key directly (thread-safe, no os.environ modification)
        response = Generation.call(
            model=model,
            messages=messages,
            result_format="message",
            api_key=api_key,
        )
        
        # Check response status
        if response.status_code != HTTPStatus.OK:
            logger.warning(
                f"[Purification] LLM judgment failed (status={response.status_code})"
            )
            return False  # Conservative: don't trigger rollback on failure
        
        # Validate response structure with null checks
        if not hasattr(response, "output"):
            logger.warning("[Purification] LLM response missing 'output'")
            return False
        
        if not hasattr(response.output, "choices") or not response.output.choices:
            logger.warning("[Purification] LLM response missing 'choices'")
            return False
        
        choice = response.output.choices[0]
        if not hasattr(choice, "message") or not hasattr(choice.message, "content"):
            logger.warning("[Purification] LLM response missing 'message.content'")
            return False
        
        raw_content = choice.message.content
        if not raw_content:
            logger.warning("[Purification] LLM response content is empty")
            return False
        
        # Handle multimodal response (content might be a list of blocks)
        content_str = _extract_text_from_content(raw_content)
        if not content_str:
            logger.warning("[Purification] LLM response text is empty after extraction")
            return False
        
        # Parse the response
        result = content_str.strip().upper().startswith("YES")
        
        logger.debug(
            f"[Purification] LLM judgment: '{user_message[:50]}...' -> {content_str} -> {result}"
        )
        return result
            
    except Exception as e:
        logger.warning(f"[Purification] LLM judgment error: {e}")
        return False  # Conservative: don't trigger rollback on error


def detect_regression_signal(
    user_message: str,
    context_messages: Optional[List[Dict]] = None,
) -> bool:
    """Two-level regression signal detection.
    
    Level 1: Fast keyword pre-filter (no LLM call)
    Level 2: LLM-based accurate judgment (only if pre-filter matches)
    
    Args:
        user_message: The user's latest message
        context_messages: Recent conversation history for LLM context
    
    Returns:
        True if this is judged as a regression signal.
    """
    # Level 1: Fast pre-filter
    if not detect_regression_signal_prefilter(user_message):
        return False
    
    # Level 2: LLM judgment
    return detect_regression_signal_llm(user_message, context_messages)


# ---------------------------------------------------------------------------
# 3. Semantic Conflict Detection
# ---------------------------------------------------------------------------

def _simple_text_similarity(text_a: str, text_b: str) -> float:
    """Compute Jaccard similarity between two texts (word-level).

    A lightweight fallback when no embedding model is available.
    For short skill descriptions this is surprisingly effective.
    """
    if not text_a or not text_b:
        return 0.0

    # Tokenize: lowercase, split on non-alphanumeric (handles Chinese too).
    tokens_a = set(re.findall(r'[\w\u4e00-\u9fff]+', text_a.lower()))
    tokens_b = set(re.findall(r'[\w\u4e00-\u9fff]+', text_b.lower()))

    if not tokens_a or not tokens_b:
        return 0.0

    intersection = tokens_a & tokens_b
    union = tokens_a | tokens_b
    return len(intersection) / len(union) if union else 0.0


def detect_skill_conflicts(
    skills_config: Dict[str, dict],
    new_skill_name: str,
    new_skill_description: str,
    all_skills: Optional[Dict] = None,
) -> List[Dict]:
    """Detect potential semantic conflicts between a new skill and existing ones.

    Uses embedding similarity if available, falls back to Jaccard text similarity.

    Returns list of conflict dicts sorted by similarity (descending):
        [{"skill_name": ..., "similarity": ..., "description": ...}, ...]
    """
    conflicts = []

    # Try embedding-based similarity first.
    embedding_provider = _try_get_embedding_provider()

    if embedding_provider:
        try:
            new_emb = embedding_provider.embed_text(new_skill_description)
            for name, config in skills_config.items():
                if name == new_skill_name:
                    continue
                desc = config.get("description", "")
                if not desc:
                    continue
                existing_emb = embedding_provider.embed_text(desc)
                sim = embedding_provider.cosine_similarity(new_emb, existing_emb)
                if sim >= CONFLICT_SIMILARITY_THRESHOLD:
                    conflicts.append({
                        "skill_name": name,
                        "similarity": round(sim, 3),
                        "description": desc[:100],
                    })
        except Exception as e:
            logger.debug(f"[Purification] Embedding conflict detection failed: {e}")
            embedding_provider = None  # fall through to text-based

    # Fallback: Jaccard text similarity.
    if not embedding_provider:
        for name, config in skills_config.items():
            if name == new_skill_name:
                continue
            desc = config.get("description", "")
            if not desc:
                continue
            sim = _simple_text_similarity(new_skill_description, desc)
            if sim >= CONFLICT_SIMILARITY_THRESHOLD:
                conflicts.append({
                    "skill_name": name,
                    "similarity": round(sim, 3),
                    "description": desc[:100],
                })

    return sorted(conflicts, key=lambda x: x["similarity"], reverse=True)


def _try_get_embedding_provider():
    """Try to get an embedding provider for semantic similarity. Returns None if unavailable."""
    try:
        from agent.memory.embedding.provider import get_embedding_provider
        provider = get_embedding_provider()
        if provider and hasattr(provider, "embed_text") and hasattr(provider, "cosine_similarity"):
            return provider
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# 4. Evolution Quality Scoring
# ---------------------------------------------------------------------------

# File lock for tracking file operations to prevent concurrent write corruption
_TRACKING_FILE_LOCK = threading.Lock()

def record_evolution_quality(
    workspace_dir: Path,
    backup_id: Optional[str],
    skill_changes: Optional[List[Dict]] = None,
    user_id: Optional[str] = None,
) -> None:
    """Record quality tracking data for an evolution pass.

    Creates/appends to ``memory/evolution/YYYY-MM-DD.tracking.json``.
    Uses file lock to prevent concurrent write corruption.
    """
    try:
        evo_dir = workspace_dir / "memory"
        if user_id:
            evo_dir = evo_dir / "users" / user_id
        evo_dir = evo_dir / "evolution"
        evo_dir.mkdir(parents=True, exist_ok=True)

        today = datetime.now().strftime("%Y-%m-%d")
        tracking_file = evo_dir / f"{today}.tracking.json"

        # Use lock to prevent concurrent write corruption
        with _TRACKING_FILE_LOCK:
            # Load existing tracking data.
            data = []
            if tracking_file.exists():
                try:
                    data = json.loads(tracking_file.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    data = []

            entry = {
                "timestamp": datetime.now().isoformat(timespec="seconds"),
                "backup_id": backup_id,
                "skill_changes": skill_changes or [],
                "feedback": {
                    "undo_count": 0,
                    "retry_count": 0,
                    "user_rating": None,
                },
            }
            data.append(entry)

            tracking_file.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        logger.debug(f"[Purification] Recorded evolution quality to {tracking_file.name}")
    except Exception as e:
        logger.warning(f"[Purification] Failed to record evolution quality: {e}")


def update_evolution_feedback(
    workspace_dir: Path,
    backup_id: str,
    feedback_type: str = "retry",
    user_id: Optional[str] = None,
) -> bool:
    """Update feedback for a specific evolution (identified by backup_id).

    :param feedback_type: "undo" or "retry"
    :returns: True if the entry was found and updated.
    Uses file lock to prevent concurrent write corruption.
    """
    try:
        evo_dir = workspace_dir / "memory"
        if user_id:
            evo_dir = evo_dir / "users" / user_id
        evo_dir = evo_dir / "evolution"

        # Search all tracking files for the backup_id.
        for tracking_file in evo_dir.glob("*.tracking.json"):
            # Use lock to prevent concurrent write corruption
            with _TRACKING_FILE_LOCK:
                try:
                    data = json.loads(tracking_file.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    continue

                for entry in data:
                    if entry.get("backup_id") == backup_id:
                        fb = entry.get("feedback", {})
                        if feedback_type == "undo":
                            fb["undo_count"] = fb.get("undo_count", 0) + 1
                        elif feedback_type == "retry":
                            fb["retry_count"] = fb.get("retry_count", 0) + 1
                        entry["feedback"] = fb

                        tracking_file.write_text(
                            json.dumps(data, ensure_ascii=False, indent=2),
                            encoding="utf-8",
                        )
                        return True
    except Exception as e:
        logger.warning(f"[Purification] Failed to update evolution feedback: {e}")
    return False


def generate_quality_report(
    workspace_dir: Path,
    days: int = DEFAULT_REPORT_DAYS,
    user_id: Optional[str] = None,
) -> Dict:
    """Generate an evolution quality report for the past N days.

    Returns a dict with aggregate statistics.
    """
    evo_dir = workspace_dir / "memory"
    if user_id:
        evo_dir = evo_dir / "users" / user_id
    evo_dir = evo_dir / "evolution"

    cutoff = datetime.now() - timedelta(days=days)

    stats = {
        "period_days": days,
        "total_evolutions": 0,
        "skill_patches": 0,
        "skill_creates": 0,
        "memory_updates": 0,
        "undo_count": 0,
        "retry_count": 0,
        "success_rate": 0.0,
        "per_skill": {},
    }

    if not evo_dir.exists():
        return stats

    for tracking_file in sorted(evo_dir.glob("*.tracking.json")):
        try:
            with _TRACKING_FILE_LOCK:
                data = json.loads(tracking_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue

        for entry in data:
            ts_str = entry.get("timestamp", "")
            try:
                ts = datetime.fromisoformat(ts_str)
            except (ValueError, TypeError):
                continue

            if ts < cutoff:
                continue

            stats["total_evolutions"] += 1
            fb = entry.get("feedback", {})
            stats["undo_count"] += fb.get("undo_count", 0)
            stats["retry_count"] += fb.get("retry_count", 0)

            # Count skill changes
            skill_changes = entry.get("skill_changes", [])
            for change in skill_changes:
                change_type = change.get("type", "unknown")
                skill_name = change.get("skill_name", "unknown")

                if change_type == "patch":
                    stats["skill_patches"] += 1
                elif change_type == "create":
                    stats["skill_creates"] += 1
                elif change_type == "memory":
                    stats["memory_updates"] += 1

                # Per-skill stats.
                if skill_name not in stats["per_skill"]:
                    stats["per_skill"][skill_name] = {
                        "patches": 0, "creates": 0, "regressions": 0
                    }
                ps = stats["per_skill"][skill_name]
                if change_type == "patch":
                    ps["patches"] += 1
                elif change_type == "create":
                    ps["creates"] += 1

            # Distribute regressions evenly across all skills changed in this evolution
            # (This is an approximation since we don't track which specific skill caused the regression)
            if skill_changes and (fb.get("retry_count", 0) > 0 or fb.get("undo_count", 0) > 0):
                total_regressions = fb.get("retry_count", 0) + fb.get("undo_count", 0)
                regressions_per_skill = total_regressions / len(skill_changes)
                for change in skill_changes:
                    skill_name = change.get("skill_name", "unknown")
                    if skill_name in stats["per_skill"]:
                        stats["per_skill"][skill_name]["regressions"] += regressions_per_skill

    # Calculate success rate.
    if stats["total_evolutions"] > 0:
        failures = stats["undo_count"] + stats["retry_count"]
        stats["success_rate"] = round(
            max(0.0, 1.0 - (failures / stats["total_evolutions"])), 3
        )

    return stats


# ---------------------------------------------------------------------------
# 5. File Cleanup
# ---------------------------------------------------------------------------

def cleanup_old_tracking_files(workspace_dir: Path, days_to_keep: int = None) -> int:
    """Clean up old tracking.json files, keeping only recent ones.
    
    Args:
        workspace_dir: Workspace directory path
        days_to_keep: Number of days to keep (default: from config or 30)
        
    Returns:
        Number of files deleted
    """
    if days_to_keep is None:
        try:
            from config import conf
            days_to_keep = conf().get("purification_tracking_retention_days", TRACKING_RETENTION_DAYS)
        except Exception:
            days_to_keep = TRACKING_RETENTION_DAYS
    
    try:
        tracking_dir = workspace_dir / "memory" / "evolution"
        if not tracking_dir.exists():
            return 0
        
        cutoff_date = datetime.now() - timedelta(days=days_to_keep)
        deleted_count = 0
        
        # Find all tracking files
        for tracking_file in tracking_dir.glob("*.tracking.json"):
            try:
                # Extract date from filename (format: YYYY-MM-DD.tracking.json)
                filename = tracking_file.stem  # Remove .json
                if filename.endswith(".tracking"):
                    date_str = filename.replace(".tracking", "")
                    file_date = datetime.strptime(date_str, "%Y-%m-%d")
                    
                    # Delete if older than cutoff
                    if file_date < cutoff_date:
                        tracking_file.unlink()
                        deleted_count += 1
                        logger.debug(f"[Purification] Deleted old tracking file: {tracking_file.name}")
            except (ValueError, OSError) as e:
                logger.debug(f"[Purification] Failed to process tracking file {tracking_file}: {e}")
        
        if deleted_count > 0:
            logger.info(f"[Purification] Cleaned up {deleted_count} old tracking file(s)")
        
        return deleted_count
    except Exception as e:
        logger.warning(f"[Purification] Failed to cleanup tracking files: {e}")
        return 0


def cleanup_old_backups(
    workspace_dir: Path,
    backups_to_keep: int = None,
    skills_config: Optional[Dict[str, dict]] = None,
) -> int:
    """Clean up old evolution backups, keeping only recent ones.
    
    Preserves backups that are still referenced by any skill's version_history
    to avoid breaking evolution undo functionality.
    
    Args:
        workspace_dir: Workspace directory path
        backups_to_keep: Number of recent backups to keep (default: from config or 10)
        skills_config: Optional skills_config dict to check for referenced backups
        
    Returns:
        Number of backups deleted
    """
    if backups_to_keep is None:
        try:
            from config import conf
            backups_to_keep = conf().get("purification_backups_to_keep", BACKUPS_TO_KEEP)
        except Exception:
            backups_to_keep = BACKUPS_TO_KEEP
    
    # Collect backup_ids still referenced by version_history (for undo safety)
    referenced_backup_ids: set = set()
    if skills_config:
        for skill_entry in skills_config.values():
            for vh in skill_entry.get("version_history", []):
                bid = vh.get("evolution_backup_id")
                if bid:
                    referenced_backup_ids.add(bid)
    
    # Never keep fewer than evolution's own limit to avoid conflicts
    try:
        from agent.evolution.backup import _MAX_BACKUPS as EVO_MAX_BACKUPS
        effective_keep = max(backups_to_keep, EVO_MAX_BACKUPS)
    except ImportError:
        effective_keep = backups_to_keep
    
    try:
        backup_dir = workspace_dir / "memory" / ".evolution_backups"
        if not backup_dir.exists():
            return 0
        
        # Get all backup directories sorted by modification time (newest first)
        backup_dirs = []
        for item in backup_dir.iterdir():
            if item.is_dir():
                backup_dirs.append((item, item.stat().st_mtime))
        
        backup_dirs.sort(key=lambda x: x[1], reverse=True)
        
        # Delete old backups beyond the limit, but skip referenced ones
        deleted_count = 0
        for backup_path, _ in backup_dirs[effective_keep:]:
            # Skip backups still referenced by version_history (needed for undo)
            if backup_path.name in referenced_backup_ids:
                logger.debug(
                    f"[Purification] Skipping referenced backup: {backup_path.name}"
                )
                continue
            try:
                import shutil
                shutil.rmtree(backup_path)
                deleted_count += 1
                logger.debug(f"[Purification] Deleted old backup: {backup_path.name}")
            except Exception as e:
                logger.debug(f"[Purification] Failed to delete backup {backup_path}: {e}")
        
        if deleted_count > 0:
            logger.info(f"[Purification] Cleaned up {deleted_count} old backup(s)")
        
        return deleted_count
    except Exception as e:
        logger.warning(f"[Purification] Failed to cleanup backups: {e}")
        return 0


def run_periodic_cleanup(
    workspace_dir: Path,
    days_to_keep: int = None,
    backups_to_keep: int = None,
    skills_config: Optional[Dict[str, dict]] = None
) -> Dict[str, int]:
    """Run all cleanup tasks.
    
    Args:
        workspace_dir: Workspace directory path
        days_to_keep: Days to keep tracking files (default: from config or 30)
        backups_to_keep: Number of backups to keep (default: from config or 10)
        skills_config: Optional skills_config dict to protect referenced backups
        
    Returns:
        Dict with cleanup statistics
    """
    # Read from config if not provided
    if days_to_keep is None:
        try:
            from config import conf
            days_to_keep = conf().get("purification_tracking_retention_days", TRACKING_RETENTION_DAYS)
        except Exception:
            days_to_keep = TRACKING_RETENTION_DAYS
    
    if backups_to_keep is None:
        try:
            from config import conf
            backups_to_keep = conf().get("purification_backups_to_keep", BACKUPS_TO_KEEP)
        except Exception:
            backups_to_keep = BACKUPS_TO_KEEP
    
    try:
        logger.info(f"[Purification] Starting periodic cleanup (tracking: {days_to_keep} days, backups: {backups_to_keep})...")
        
        tracking_deleted = cleanup_old_tracking_files(workspace_dir, days_to_keep)
        # Pass skills_config to protect referenced backups
        backups_deleted = cleanup_old_backups(workspace_dir, backups_to_keep, skills_config)
        
        result = {
            "tracking_files_deleted": tracking_deleted,
            "backups_deleted": backups_deleted,
        }
        
        logger.info(
            f"[Purification] Cleanup completed: "
            f"{tracking_deleted} tracking file(s), {backups_deleted} backup(s) deleted"
        )
        
        return result
    except Exception as e:
        logger.warning(f"[Purification] Periodic cleanup failed: {e}")
        return {"tracking_files_deleted": 0, "backups_deleted": 0}
