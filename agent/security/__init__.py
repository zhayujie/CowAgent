"""
CowAgent security subsystem (issue #2998).

The agent runs on its owner's personal machine with shell and filesystem
access. Once the bot is invited into a Feishu or WeChat group, that machine is
reachable by everyone in the group, and content the agent merely *reads* can
steer it. Four layers address that, ordered from weakest to strongest:

1. ``prompt``     - security rules injected into every system prompt, on every
                    channel. Advisory: a model can be argued out of them.
2. ``injection``  - marks untrusted content as data and flags text that is
                    trying to behave like an instruction. Heuristic.
3. ``policy``     - the capability gate. Plain Python between the model's
                    decision and the tool's side effect, so it cannot be
                    argued with. **This is the actual boundary.**
4. ``redaction``  - strips secrets from outbound text, in case the layers
                    above all failed.

Plus ``audit``, which records every decision to a JSONL file in the workspace.

Design constraints worth knowing before changing anything here:

* **Fail-open when unscoped, fail-closed when scoped.** A run with no bound
  security context (desktop app, CLI, unit tests, the owner's own scheduled
  tasks) is treated as OWNER, so single-user setups see no behaviour change at
  all. Channel-driven runs always bind a context explicitly, and errors during
  resolution drop to GUEST rather than OWNER.
* **The prompt is not the boundary.** Anything that only works because the
  model cooperated is a mitigation, not a control. Enforcement belongs in
  ``policy.py``.

Typical use::

    from agent.security import resolve_security_context, security_scope

    with security_scope(resolve_security_context(context)):
        agent.run_stream(...)
"""

from agent.security.audit import (
    record,
    record_confirmation,
    record_denial,
    record_injection,
    record_redaction,
)
from agent.security.commands import CommandRisk, format_refusal, inspect_command
from agent.security.injection import (
    InjectionFinding,
    annotate_tool_result,
    detect,
    looks_like_injection,
    strip_invisible,
    wrap_untrusted,
)
from agent.security.paths import (
    is_sensitive_path,
    is_within_root,
    sensitive_path_kind,
)
from agent.security.policy import (
    Decision,
    describe_active_policy,
    evaluate_tool_call,
    workspace_root,
)
from agent.security.prompt import build_security_section
from agent.security.redaction import known_secret_values, redact, redact_text
from agent.security.trust import (
    SecurityContext,
    TrustLevel,
    current_security_context,
    resolve_security_context,
    security_scope,
)

__all__ = [
    # trust
    "TrustLevel",
    "SecurityContext",
    "current_security_context",
    "resolve_security_context",
    "security_scope",
    # policy
    "Decision",
    "evaluate_tool_call",
    "describe_active_policy",
    "workspace_root",
    # paths
    "is_sensitive_path",
    "sensitive_path_kind",
    "is_within_root",
    # commands
    "CommandRisk",
    "inspect_command",
    "format_refusal",
    # injection
    "InjectionFinding",
    "detect",
    "looks_like_injection",
    "strip_invisible",
    "wrap_untrusted",
    "annotate_tool_result",
    # redaction
    "redact",
    "redact_text",
    "known_secret_values",
    # prompt
    "build_security_section",
    # audit
    "record",
    "record_denial",
    "record_confirmation",
    "record_injection",
    "record_redaction",
]
