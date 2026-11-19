"""Guest share: let people outside the instance chat with a restricted Agent.

A guest profile is a directory under ``<workspace>/guests/<slug>/`` holding the
rules (GUEST.md), the access and capability settings (config.json, including
the read-only reference directories) and optional profile-only skills (skills/).
Each profile gets its own share link; visitors on it never see the owner's
workspace, memory, credentials or configuration.

Security does not rest on the prompt. What a visitor can reach is decided by
code: the guest tools resolve every path against a per-session allowlist, the
effective configuration only widens after the owner confirms it in the web
console, and the visitor's credentials are a separate token family that no
console endpoint accepts.
"""
