"""The seam between a team conversation and Agents hosted in other processes.

Delegation only ever knows a teammate by id. When that id is not in the local
registry the delegating tool asks the installed transport instead, so the
whole team machinery — roster, prompt, delegation card, result shape — is the
same whether the teammate shares this process or not.

This module is deliberately inert: it defines the contract and keeps a
reference to the one transport an integration chose to install. The default
is no transport at all.
"""

from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Callable, Dict, Iterable, Optional, Tuple

from common.log import logger


@dataclass(frozen=True)
class PeerAgent:
    """What is known about an Agent outside this process: enough to list it
    on a roster and address it, nothing more."""

    id: str
    name: str
    description: str = ""

    @classmethod
    def from_any(cls, raw) -> Optional["PeerAgent"]:
        """Build from a dict or another peer; None when there is no usable id."""
        if isinstance(raw, PeerAgent):
            return raw
        if not isinstance(raw, dict):
            return None
        peer_id = str(raw.get("id") or raw.get("agent_id") or "").strip()
        if not peer_id:
            return None
        return cls(
            id=peer_id,
            name=str(raw.get("name") or peer_id).strip() or peer_id,
            description=str(raw.get("description") or "").strip(),
        )

    def as_dict(self) -> dict:
        out = {"id": self.id, "name": self.name}
        if self.description:
            out["description"] = self.description
        return out


MODE_DELEGATE = "delegate"
MODE_SPEAK = "speak"
MODE_CLEAR = "clear"


@dataclass(frozen=True)
class InvokeRequest:
    """One hand-off to a teammate in another process.

    Mirrors the context a local delegated turn runs with, so the far side can
    run the very same kind of turn: who asked, the task, the conversation it
    belongs to, the chain so far (for the cycle guard), how deep we are, and
    the team the teammate may in turn hand work to.

    ``mode``: :data:`MODE_DELEGATE` runs a private sub-task whose result the
    caller folds into its reply; :data:`MODE_SPEAK` answers a turn the user
    addressed to the teammate, as itself, given the conversation so far in
    ``history`` (``{"role", "text", "agent_id"}`` entries, oldest first);
    :data:`MODE_CLEAR` runs no turn and drops the teammate's context for
    ``root_session_id``.
    """

    request_id: str
    target_id: str
    task: str
    source_id: str
    source_name: str
    root_session_id: str
    trace: Tuple[str, ...]
    depth: int
    members: Tuple[str, ...] = ()
    peers: Tuple[PeerAgent, ...] = ()
    timeout_seconds: float = 600.0
    mode: str = MODE_DELEGATE
    history: Tuple[dict, ...] = ()


@dataclass
class InvokeResult:
    """The teammate's answer, in the shape the delegation tool already returns."""

    status: str  # "done" | "failed"
    content: str = ""
    error: str = ""
    agent_id: str = ""
    agent_name: str = ""
    duration_seconds: float = 0.0

    @property
    def ok(self) -> bool:
        return self.status == "done"

    @classmethod
    def failed(cls, error: str, agent_id: str = "", agent_name: str = "") -> "InvokeResult":
        return cls(status="failed", error=str(error or "unknown error"),
                   agent_id=agent_id, agent_name=agent_name)


class PeerTransport(ABC):
    """How this process reaches Agents it does not host.

    Concrete transports decide *how* a request travels; this base only keeps
    the directory of peers they have learned about, which the roster and the
    delegation tool consult to tell "unknown id" apart from "teammate over
    there".
    """

    def __init__(self):
        self._peers: Dict[str, PeerAgent] = {}
        self._peers_lock = threading.Lock()

    # ---- directory -------------------------------------------------------

    def register_peers(self, peers: Optional[Iterable]) -> None:
        """Remember profiles for Agents reachable through this transport.

        Called whenever a conversation arrives naming teammates from elsewhere;
        the directory is additive so a peer learned on one turn stays known.
        """
        if not peers:
            return
        with self._peers_lock:
            for raw in peers:
                peer = PeerAgent.from_any(raw)
                if peer is not None:
                    self._peers[peer.id] = peer

    def get_peer(self, agent_id: Optional[str]) -> Optional[PeerAgent]:
        if not agent_id:
            return None
        with self._peers_lock:
            return self._peers.get(str(agent_id).strip())

    def peers(self) -> Dict[str, PeerAgent]:
        with self._peers_lock:
            return dict(self._peers)

    # ---- the one thing a transport must do --------------------------------

    @abstractmethod
    def invoke(
        self,
        request: InvokeRequest,
        on_event: Optional[Callable[[dict], None]] = None,
    ) -> InvokeResult:
        """Run ``request`` on the teammate and wait for its answer.

        ``on_event`` receives ``{"type": ..., "data": ...}`` events as the
        teammate runs: tool steps for a delegated turn, ``{"type": "chunk",
        "data": <stream chunk>}`` for a speaking turn. Must not raise for a
        failed hand-off: return :meth:`InvokeResult.failed` instead.
        """


_transport: Optional[PeerTransport] = None
_transport_lock = threading.Lock()


def set_transport(transport: Optional[PeerTransport]) -> None:
    """Install (or, with None, remove) the process-wide transport."""
    global _transport
    with _transport_lock:
        _transport = transport
    if transport is not None:
        logger.info(f"[MultiAgent] peer transport installed: {type(transport).__name__}")


def get_transport() -> Optional[PeerTransport]:
    with _transport_lock:
        return _transport


def peer(agent_id: Optional[str]) -> Optional[PeerAgent]:
    """The peer profile for ``agent_id``, or None when no transport knows it."""
    transport = get_transport()
    return transport.get_peer(agent_id) if transport is not None else None


def resolve_teammate(agent_id: Optional[str], registry=None) -> Optional[dict]:
    """A roster entry ``{id, name, description}`` for a teammate wherever it
    lives: the local registry first, then the transport's directory. None for
    an id nobody knows, which callers treat as "no longer on the team".

    Ids arrive as the ids a caller may address an Agent by, so the reserved
    "default" alias resolves here like it does anywhere else a roster is built;
    an empty id is nobody, not the default agent."""
    if not agent_id:
        return None
    if registry is None:
        try:
            from agent.registry import get_agent_registry

            registry = get_agent_registry()
        except Exception:
            registry = None
    if registry is not None:
        try:
            profile = registry.get_addressed(agent_id)
            return {
                "id": profile.id,
                "name": profile.name,
                "description": profile.description or "",
            }
        except Exception:
            pass
    found = peer(agent_id)
    return found.as_dict() if found is not None else None
