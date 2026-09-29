"""Teammates that live in another process.

A team conversation may name Agents this process does not host. Handing work
to one of them goes through whatever :class:`PeerTransport` the running
integration installed; with none installed every such Agent is simply out of
reach and a team behaves exactly as a single-process team always has.

Nothing in this package opens a connection or contacts anything on its own.
It only holds the transport it was handed and the peer profiles that transport
learned about.
"""

from agent.multiagent.transport import (
    MODE_CLEAR,
    MODE_DELEGATE,
    MODE_SPEAK,
    InvokeRequest,
    InvokeResult,
    PeerAgent,
    PeerTransport,
    get_transport,
    peer,
    resolve_teammate,
    set_transport,
)

__all__ = [
    "MODE_CLEAR",
    "MODE_DELEGATE",
    "MODE_SPEAK",
    "InvokeRequest",
    "InvokeResult",
    "PeerAgent",
    "PeerTransport",
    "get_transport",
    "peer",
    "resolve_teammate",
    "set_transport",
]
