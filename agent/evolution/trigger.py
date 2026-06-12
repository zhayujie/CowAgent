"""Idle-based evolution trigger.

A single background thread periodically scans live agent sessions and runs an
evolution pass for any session that is idle for >= idle_minutes AND has enough
accumulated signal, where "enough signal" is EITHER:
  - >= min_turns user turns since the last evolution, OR
  - the live context has grown past _CONTEXT_RATIO of the agent's token budget
    (mirrors how OpenClacky / Claude Code consolidate under context pressure).

Turn counting is per user turn (not per message), measured from the last
evolution (or session start). After a pass runs, the baseline resets so a long
session can evolve multiple times without re-judging old content.

Per-session evolution state is stored on the agent instance via lightweight
attributes set by AgentBridge.agent_reply (see _note_user_turn).
"""

from __future__ import annotations

import threading
import time

from common.log import logger

from agent.evolution.config import get_evolution_config
from agent.evolution.executor import run_evolution_for_session

_SCAN_INTERVAL_SECONDS = 60

# Context-pressure trigger: evolve once the live context exceeds this fraction
# of the agent's token budget, even if min_turns hasn't been reached. Kept as a
# module constant (not user config) for now. Fallback budget matches
# agent_initializer / config.py (agent_max_context_tokens default = 50000).
_CONTEXT_RATIO = 0.8
_FALLBACK_CONTEXT_BUDGET = 50000


def _context_pressure_reached(agent) -> bool:
    """True if the agent's live context exceeds _CONTEXT_RATIO of its budget.

    Uses the agent's own (estimated) token accounting so behavior matches the
    existing context-trimming path. Best-effort: any error -> False.
    """
    try:
        with agent.messages_lock:
            messages = list(agent.messages)
        if not messages:
            return False
        est = sum(agent._estimate_message_tokens(m) for m in messages)
        budget = getattr(agent, "max_context_tokens", None) or _FALLBACK_CONTEXT_BUDGET
        return est / budget > _CONTEXT_RATIO
    except Exception:
        return False


def note_user_turn(agent, channel_type: str = "", receiver: str = "") -> None:
    """Record activity for a session's agent. Called once per real user turn.

    Maintains, on the agent instance:
      _evo_last_active   : epoch seconds of the last user turn
      _evo_turns         : user turns since the last evolution
      _evo_channel_type  : originating channel (for later notify)
      _evo_receiver      : push target for notify
    """
    try:
        agent._evo_last_active = time.time()
        agent._evo_turns = int(getattr(agent, "_evo_turns", 0)) + 1
        if channel_type:
            agent._evo_channel_type = channel_type
        if receiver:
            agent._evo_receiver = receiver
    except Exception:
        pass


def start_evolution_trigger(agent_bridge) -> None:
    """Start the idle-scan thread once per process (idempotent)."""
    if getattr(agent_bridge, "_evolution_trigger_started", False):
        return
    agent_bridge._evolution_trigger_started = True

    t = threading.Thread(
        target=_scan_loop, args=(agent_bridge,), daemon=True, name="evolution-trigger"
    )
    t.start()
    logger.info("[Evolution] Idle trigger started")


def _scan_loop(agent_bridge) -> None:
    while True:
        try:
            time.sleep(_SCAN_INTERVAL_SECONDS)
            cfg = get_evolution_config()
            if not cfg.enabled:
                continue
            _scan_once(agent_bridge, cfg)
        except Exception as e:
            logger.warning(f"[Evolution] Scan loop error: {e}")
            time.sleep(_SCAN_INTERVAL_SECONDS)


def _scan_once(agent_bridge, cfg) -> None:
    now = time.time()
    # Snapshot to avoid holding the dict while running long evolutions.
    sessions = list(getattr(agent_bridge, "agents", {}).items())
    for session_id, agent in sessions:
        try:
            last_active = getattr(agent, "_evo_last_active", 0)
            turns = int(getattr(agent, "_evo_turns", 0))
            # Enough signal = enough turns OR enough context pressure.
            enough_signal = turns >= cfg.min_turns or _context_pressure_reached(agent)
            if not enough_signal:
                continue
            idle = now - last_active if last_active > 0 else -1
            if last_active <= 0 or idle < cfg.idle_seconds:
                continue

            channel_type = getattr(agent, "_evo_channel_type", "") or ""
            receiver = getattr(agent, "_evo_receiver", "") or ""

            # Reset baseline BEFORE running so a long pass / new messages during
            # it don't double-trigger; turns accrue fresh from here.
            agent._evo_turns = 0

            run_evolution_for_session(
                agent_bridge,
                session_id=session_id,
                channel_type=channel_type,
                receiver=receiver,
                idle_minutes=(now - last_active) / 60 if last_active > 0 else 0.0,
            )
        except Exception as e:
            logger.warning(f"[Evolution] Failed to evaluate session={session_id}: {e}")
