# Native Multi-Agent Workspaces

## Goal

Allow one CowAgent process to host multiple agents without changing the
behaviour of existing single-agent installations. Each agent is a complete
CowAgent workspace, not a lightweight persona overlay.

## Workspace model

An agent profile identifies one workspace root. The existing workspace layout
is reused unchanged:

```text
<workspace>/
├── AGENT.md
├── USER.md
├── RULE.md
├── MEMORY.md
├── memory/
├── skills/
├── knowledge/
├── output/
└── scheduler/
```

The workspace owns the agent's persona, user profile, rules, long-term memory,
daily memory, search index, conversation history, skills, knowledge, scheduler
tasks, evolution data, and generated output.

There is no second home directory abstraction. There is also no shared memory
database with an `agent_id` column. Each workspace keeps using its own
`memory/long-term/index.db`, matching the current single-agent layout.

## Configuration

The optional configuration is:

```json
{
  "default_agent_id": "default",
  "agents": [
    {
      "id": "default",
      "name": "Default",
      "workspace": "~/cow",
      "enabled": true
    }
  ],
  "agent_bindings": []
}
```

When `agents` is absent, CowAgent synthesizes one `default` profile from the
existing `agent_workspace` value. Existing configuration and data therefore
continue to work without a migration.

Agent IDs are stable, URL-safe identifiers. Workspace paths must be unique.
Agent deletion is represented as disabling or archiving the profile; workspace
data is never deleted implicitly.

## Runtime isolation

The runtime key becomes `(agent_id, session_id)`. Initializing an agent resolves
the profile first, then passes its workspace explicitly through prompt loading,
memory, tools, skills, scheduler, and persistence.

Process-wide state that currently binds to the first workspace is replaced by
workspace-keyed registries:

```text
workspace → MemoryManager
workspace → ConversationStore
workspace → SchedulerService / TaskStore
workspace → memory flush, Deep Dream, and evolution runtime
```

No agent may obtain a manager, store, or scheduler belonging to another
workspace, even when both sessions use the same external session identifier.

## Routing

Inbound contexts carry `agent_id`. Resolution follows a deterministic order:

1. exact channel and conversation binding;
2. channel-level default binding;
3. configured `default_agent_id`.

Bindings that reference a missing or disabled agent fall back to the default
agent and emit a warning. Existing channels require no binding and continue to
use the default agent.

## Web console

The console can list, create, clone, enable, disable, and select agents. It can
edit the four core files `AGENT.md`, `USER.md`, `RULE.md`, and `MEMORY.md`.

The editor is intentionally not a general filesystem browser. The backend uses
an allowlist, resolves paths beneath the selected workspace, writes atomically,
and rejects stale writes using a content revision. Updating a core file evicts
only that agent's live sessions so its next turn rebuilds the prompt.

New profiles use the existing workspace bootstrap and templates. A new agent
therefore has the same onboarding and capabilities as the original single
agent.

## Inter-agent delegation

Agents communicate through a guarded request-response tool:

```text
agent_delegate(target_agent, message, timeout_seconds)
```

The target runs in its own workspace and a dedicated relay session. Results
include source attribution and structured errors. The runtime enforces target
allowlists, timeouts, cancellation, message limits, maximum delegation depth,
and cycle detection. Delegated output is returned to the caller and is not sent
to a user channel automatically.

## Backup and restore

Backups include the registry, bindings, and selected agent workspaces. Restore
validates manifest versions, profile IDs, workspace destinations, and archive
paths before writing. Restores remain transactional and preserve the existing
rollback behaviour.

No import tooling is part of this design.

## Delivery

The work is split into seven ordered changes:

1. agent registry and compatibility configuration;
2. agent-aware runtime initialization;
3. workspace-scoped memory, sessions, and scheduler;
4. channel bindings and routing;
5. Web console management and core-file editor;
6. guarded inter-agent delegation;
7. multi-agent backup, documentation, and final hardening.

Later changes depend on earlier ones. Each change must include its own tests and
preserve the zero-configuration single-agent path.

## Acceptance criteria

- Existing configurations still use `~/cow` exactly as before.
- Two agents with the same session ID cannot share runtime state or data.
- Memory, conversation history, scheduled tasks, skills, and knowledge remain
  inside the selected workspace.
- Channel bindings resolve deterministically and fail safely.
- The console can create an agent and safely edit its four core Markdown files.
- Delegation cannot recurse forever or bypass disabled-target checks.
- Backup and restore preserve all configured agents without writing outside
  approved workspace paths.
