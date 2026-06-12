"""
Self-evolution subsystem for CowAgent.

Runs a lightweight, isolated review pass after a conversation goes idle to
decide whether anything is worth durably learning (memory / skill) or whether
an unfinished task can be pushed forward. Conservative by design: most
conversations should produce no change at all.

Public entry points:
    from agent.evolution import get_evolution_config
    from agent.evolution.trigger import start_evolution_trigger, note_user_turn
"""

from agent.evolution.config import EvolutionConfig, get_evolution_config

__all__ = [
    "EvolutionConfig",
    "get_evolution_config",
]
