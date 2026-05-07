"""
OpenAI-compatible exception layer.

This module used to bridge between openai SDK 0.x and 1.x exception types.
Since we no longer depend on the `openai` SDK at all (we call HTTP directly
via :mod:`models.openai.openai_http_client`), this file now provides:

1. Pure Python exception classes that match the *names* the rest of the
   codebase already imports (RateLimitError / Timeout / APIError /
   APIConnectionError / AuthenticationError / InvalidRequestError ...).
2. A :func:`map_http_error` helper that converts an
   :class:`OpenAIHTTPError` (or any HTTP status code + message) into the
   appropriate exception subclass, so existing ``except RateLimitError``
   ``except Timeout`` etc. blocks keep working unchanged.

This keeps the behavior of all existing bots (rate-limit backoff, timeout
retry, auth-error fast-fail) identical to the openai-SDK-based version, while
removing the hard dependency on the `openai` package.
"""

from typing import Optional


# --------------------------------------------------------------------------- #
# Exception hierarchy (mirrors openai SDK names so call sites don't change)
# --------------------------------------------------------------------------- #

class OpenAIError(Exception):
    """Base exception for all OpenAI-compatible API errors."""

    def __init__(self, message: str = "", status_code: Optional[int] = None,
                 body=None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.body = body


class APIError(OpenAIError):
    """Generic API error (5xx and unclassified errors)."""


class APIConnectionError(OpenAIError):
    """Network / connection failure (DNS, refused, reset...)."""


class Timeout(OpenAIError):
    """Request timeout. Aliased as APITimeoutError for new-SDK style imports."""


class AuthenticationError(OpenAIError):
    """401 Unauthorized."""


class PermissionDeniedError(OpenAIError):
    """403 Forbidden."""


class NotFoundError(OpenAIError):
    """404 Not Found."""


class InvalidRequestError(OpenAIError):
    """400 Bad Request. Aliased as BadRequestError."""


class RateLimitError(OpenAIError):
    """429 Too Many Requests."""


# Aliases used by some new-SDK-style code paths in the project.
APITimeoutError = Timeout
BadRequestError = InvalidRequestError


# --------------------------------------------------------------------------- #
# Backward-compat ``error`` module-style accessor
# --------------------------------------------------------------------------- #
# Some legacy code in the codebase (and possibly user plugins) does
#   from models.openai.openai_compat import error
#   except error.RateLimitError: ...
# Keep that path working by exposing an attribute namespace.
class _ErrorModule:
    OpenAIError = OpenAIError
    APIError = APIError
    APIConnectionError = APIConnectionError
    Timeout = Timeout
    AuthenticationError = AuthenticationError
    PermissionDeniedError = PermissionDeniedError
    NotFoundError = NotFoundError
    InvalidRequestError = InvalidRequestError
    RateLimitError = RateLimitError


error = _ErrorModule()


# --------------------------------------------------------------------------- #
# HTTP -> exception mapping
# --------------------------------------------------------------------------- #

def map_http_error(status_code: Optional[int], message: str = "",
                   body=None) -> OpenAIError:
    """Convert an HTTP status (+ optional message/body) to the right subclass.

    Used by HTTP-based bot wrappers so that downstream ``except RateLimitError``
    blocks behave identically to when the openai SDK was raising them.
    """
    sc = status_code or 0
    msg = message or ""
    msg_lower = msg.lower()

    # Connection-level (no status / non-HTTP failure)
    if sc == 0:
        if "timeout" in msg_lower or "timed out" in msg_lower:
            return Timeout(msg, sc, body)
        return APIConnectionError(msg, sc, body)

    if sc == 408:
        return Timeout(msg, sc, body)
    if sc == 401:
        return AuthenticationError(msg, sc, body)
    if sc == 403:
        return PermissionDeniedError(msg, sc, body)
    if sc == 404:
        return NotFoundError(msg, sc, body)
    if sc == 429:
        return RateLimitError(msg, sc, body)
    if 400 <= sc < 500:
        return InvalidRequestError(msg, sc, body)
    if sc >= 500:
        return APIError(msg, sc, body)

    return APIError(msg, sc, body)


def wrap_http_error(http_err) -> OpenAIError:
    """Adapter for :class:`OpenAIHTTPError` -> compat exception subclass.

    Accepts any object with ``status_code`` / ``message`` / ``body`` attrs.
    """
    sc = getattr(http_err, "status_code", None)
    msg = getattr(http_err, "message", "") or str(http_err)
    body = getattr(http_err, "body", None)
    return map_http_error(sc, msg, body)


__all__ = [
    "error",
    "OpenAIError",
    "APIError",
    "APIConnectionError",
    "Timeout",
    "APITimeoutError",
    "AuthenticationError",
    "PermissionDeniedError",
    "NotFoundError",
    "InvalidRequestError",
    "BadRequestError",
    "RateLimitError",
    "map_http_error",
    "wrap_http_error",
]
