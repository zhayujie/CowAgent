# Native Multi-Agent Implementation Plan

## Change 1: Agent registry

- Add immutable `AgentProfile` values and a thread-safe `AgentRegistry`.
- Parse `agents`, `default_agent_id`, and `agent_bindings` from configuration.
- Synthesize the default profile from `agent_workspace` when the new fields are
  absent.
- Validate IDs, duplicate workspaces, enabled defaults, and binding targets.
- Add unit tests for compatibility and invalid configurations.

Verification: registry tests, configuration tests, Python compilation.

## Change 2: Runtime isolation

- Thread `agent_id` through `AgentBridge`, `AgentInitializer`, and chat service.
- Key live agent instances by `(agent_id, session_id)`.
- Pass the resolved workspace explicitly to prompt, tools, skills, memory, and
  runtime metadata.
- Add eviction helpers for one agent and one agent session.
- Test same-session isolation and legacy callers.

Verification: bridge/initializer tests and existing agent tests.

## Change 3: Workspace-scoped state

- Replace memory and conversation process singletons with workspace registries.
- Replace scheduler singleton access with workspace-scoped services and stores.
- Scope flush, Deep Dream, evolution, session operations, and task execution to
  the owning workspace.
- Keep the existing database schema and file layout.
- Test independent databases, tasks, timers, and cleanup.

Verification: memory, conversation, scheduler, evolution, and regression tests.

## Change 4: Routing

- Add a binding resolver with exact, channel-default, and global-default
  precedence.
- Add `agent_id` to inbound contexts and preserve it through queues, replies,
  persistence, and cancellation.
- Add Web chat agent selection.
- Test private chats, groups, missing targets, disabled targets, and unchanged
  default routing.

Verification: routing and representative channel tests.

## Change 5: Web management

- Add authenticated APIs for agent CRUD, bindings, and allowed core files.
- Use atomic writes, path containment checks, and content revisions.
- Add an Agents page and selectors in chat, sessions, tasks, memory, skills, and
  knowledge views where relevant.
- Evict only the affected agent after core-file changes.
- Test API authorization, validation, traversal protection, conflicts, and UI
  production build.

Verification: API tests, TypeScript checks, and desktop production build.

## Change 6: Delegation

- Add a delegation service and `agent_delegate` tool.
- Create stable target relay sessions without user-channel delivery.
- Enforce target policy, timeout, cancellation, depth, cycle, size, and
  concurrency limits.
- Return structured provenance and errors.
- Test success, unavailable targets, timeout, cancellation, and cycles.

Verification: delegation tests and agent tool regressions.

## Change 7: Backup and hardening

- Extend the backup manifest with registry, bindings, and selected workspaces.
- Preserve archive traversal, destination, and rollback protections.
- Add single-agent and all-agent backup/restore tests.
- Update English, Chinese, and Japanese documentation.
- Run the complete Python suite and desktop build against the final stack.

Verification: backup tests, full Python suite, desktop build, and diff checks.

## Publication

- Preserve one branch pointer after each ordered change.
- Push all implementation branches only after the final stack passes.
- Open reviewable pull requests with explicit dependency notes and validation.
- Open one tracking issue describing the completed work and merge order.
