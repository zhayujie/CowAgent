"""Ambient runtime identity: who the current work is being done for.

Everything downstream of message routing needs to know which Agent, which end
user, which session and which task it is running under. Threading that through
every call site is what makes multi-agent refactors expensive, so it lives in a
ContextVar instead: routing resolves it once at the entry point, leaf code
reads it and never re-derives it.

ContextVars do not cross thread boundaries on their own. Work handed to another
thread must go through ``submit`` or ``wrap`` below, which copy the calling
context into the worker.
"""

from __future__ import annotations

import contextvars
import functools
from concurrent.futures import Executor, Future
from contextlib import contextmanager
from dataclasses import dataclass, replace
from typing import Any, Callable, Iterator, Optional

_FIELDS = ("agent_id", "user_id", "session_id", "run_id")


@dataclass(frozen=True)
class RuntimeIdentity:
    """Every field is optional.

    ``agent_id`` is None on single-Agent installs and before routing has run.
    ``user_id`` is the chat sender when the channel has one, and stays None
    when it does not — a session id is not a user. ``run_id`` is set per task
    once sub agents exist. Consumers must treat None as "use the default".
    """

    agent_id: Optional[str] = None
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    run_id: Optional[str] = None

    def derive(self, **overrides: Optional[str]) -> "RuntimeIdentity":
        unknown = set(overrides) - set(_FIELDS)
        if unknown:
            raise TypeError(f"unknown identity fields: {sorted(unknown)}")
        return replace(self, **overrides)


EMPTY_IDENTITY = RuntimeIdentity()

_current: contextvars.ContextVar[RuntimeIdentity] = contextvars.ContextVar(
    "cow_runtime_identity", default=EMPTY_IDENTITY
)


def current_identity() -> RuntimeIdentity:
    return _current.get()


def current_agent_id() -> Optional[str]:
    return _current.get().agent_id


@contextmanager
def identity_scope(**overrides: Optional[str]) -> Iterator[RuntimeIdentity]:
    """Derive an identity from the ambient one for the duration of a block.

    Sub agents use this: they inherit agent_id/user_id/session_id from the
    parent and take a fresh run_id.
    """
    identity = _current.get().derive(**overrides)
    token = _current.set(identity)
    try:
        yield identity
    finally:
        _current.reset(token)


@contextmanager
def use_identity(identity: RuntimeIdentity) -> Iterator[RuntimeIdentity]:
    """Replace the ambient identity wholesale, for entry points that resolved
    it from scratch rather than deriving it."""
    token = _current.set(identity)
    try:
        yield identity
    finally:
        _current.reset(token)


def submit(executor: Executor, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Future:
    """``executor.submit`` that carries the caller's identity into the worker."""
    ctx = contextvars.copy_context()
    return executor.submit(ctx.run, functools.partial(fn, *args, **kwargs))


def wrap(fn: Callable[..., Any]) -> Callable[..., Any]:
    """Bind the current context to a callable, for ``threading.Thread(target=)``."""
    ctx = contextvars.copy_context()

    @functools.wraps(fn)
    def _run(*args: Any, **kwargs: Any) -> Any:
        return ctx.run(functools.partial(fn, *args, **kwargs))

    return _run
