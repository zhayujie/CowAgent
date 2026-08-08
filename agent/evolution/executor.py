"""Self-evolution executor.

Runs an isolated review agent over an idle conversation's transcript and, if a
clear signal is found, lets it edit memory / skills via a restricted toolset.
Conservative by design: most runs return ``[SILENT]`` and change nothing.

Flow:
    1. Build a transcript from the session's new (since last pass) messages.
    2. Snapshot MEMORY.md + daily file + editable skills (for undo) -> backup_id.
    3. Run an isolated agent (same model, restricted tools, evolution prompt).
    4. If output is [SILENT], or no workspace file actually changed -> done.
    5. Otherwise -> record to the evolution log, inject an [EVOLUTION] note into
       the user session (so the main agent can honor "undo"), and push the
       summary to the user's channel.

Reuses existing infrastructure (AgentBridge.create_agent, ToolManager,
remember_scheduled_output, channel_factory) rather than introducing a fork.
"""

from __future__ import annotations

import threading
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from common.log import logger

from agent.evolution.backup import create_backup
from agent.evolution.config import get_evolution_config
from agent.evolution.prompts import (
    EVOLUTION_MARKER,
    EVOLUTION_SYSTEM_PROMPT,
    SILENT_TOKEN,
    build_review_user_message,
)
from agent.evolution.record import append_session_evolution

# Tools the isolated evolution agent is allowed to use. Everything else is
# withheld so an unattended review can only read context and edit approved
# workspace artifacts. Skill files are created directly with the write tool.
_ALLOWED_TOOLS = {"read", "write", "edit", "ls", "memory_search", "memory_get"}

# Cap concurrent evolution passes so a burst of idle sessions can't spawn many
# background model runs at once. Extra sessions simply wait for the next scan.
_MAX_CONCURRENT = 2
_running_lock = threading.Lock()
_running_count = 0


def _builtin_skill_names() -> set:
    """Names of skills shipped with the product (project-root ``skills/``).

    These are protected: the evolution agent must never edit them, even though
    a same-named copy exists in the workspace at runtime. The project dir is the
    authoritative list of what counts as built-in.
    """
    try:
        # executor.py -> agent/evolution -> agent -> project root
        project_root = Path(__file__).resolve().parents[2]
        builtin_dir = project_root / "skills"
        if not builtin_dir.is_dir():
            return set()
        names = set()
        for entry in builtin_dir.iterdir():
            if entry.is_dir() and not entry.name.startswith("."):
                names.add(entry.name)
        return names
    except Exception:
        return set()


def _build_transcript(messages: List[dict], max_chars: int = 12000) -> str:
    """Render the session messages into a compact text transcript."""
    lines: List[str] = []
    for msg in messages:
        role = msg.get("role", "")
        if role not in ("user", "assistant"):
            continue
        content = msg.get("content", "")
        text = _extract_text(content)
        if not text.strip():
            continue
        speaker = "User" if role == "user" else "Assistant"
        lines.append(f"{speaker}: {text.strip()}")
    transcript = "\n".join(lines)
    # Keep the most RECENT context if oversized (tail is most relevant).
    if len(transcript) > max_chars:
        transcript = "...(earlier omitted)...\n" + transcript[-max_chars:]
    return transcript


def _extract_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
            elif isinstance(block, str):
                parts.append(block)
        return "\n".join(parts)
    return ""


def _select_tools(all_tools: list) -> list:
    return [t for t in all_tools if getattr(t, "name", None) in _ALLOWED_TOOLS]


# Tools whose writes must be confined to the workspace during evolution.
_WRITE_TOOLS = {"write", "edit"}


class _EvolutionWriteTransaction:
    """Make writes performed by one unattended evolution pass atomic."""

    _MISSING = object()

    def __init__(self, workspace: Path):
        self._workspace = workspace.resolve()
        self._before: dict[Path, object] = {}
        self._missing_parents: set[Path] = set()
        self._committed = False

    def record(self, path: Path) -> None:
        path = path.resolve()
        if path in self._before:
            return
        parent = path.parent
        while parent != self._workspace:
            try:
                parent.relative_to(self._workspace)
            except ValueError:
                break
            if parent.exists():
                break
            self._missing_parents.add(parent)
            parent = parent.parent
        try:
            self._before[path] = path.read_bytes() if path.is_file() else self._MISSING
        except OSError as e:
            raise PermissionError(f"cannot snapshot '{path}' before evolution write: {e}")

    def commit(self) -> None:
        self._committed = True

    def rollback(self) -> None:
        if self._committed:
            return
        for path, before in reversed(list(self._before.items())):
            try:
                if before is self._MISSING:
                    if path.is_file() or path.is_symlink():
                        path.unlink()
                else:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(before)
            except OSError as e:
                logger.error(f"[Evolution] Failed to roll back {path}: {e}")
        for directory in sorted(
            self._missing_parents, key=lambda p: len(p.parts), reverse=True
        ):
            try:
                directory.rmdir()
            except OSError:
                pass


def _allowed_evolution_path(
    workspace: Path, resolved: Path, protected_skills: set
) -> bool:
    """Allow only the file types Self-Evolution is designed to maintain."""
    try:
        relative = resolved.relative_to(workspace)
    except ValueError:
        return False
    parts = relative.parts
    if not parts:
        return False
    if len(parts) == 1:
        return parts[0] in {"MEMORY.md", "AGENT.md"}
    top = parts[0]
    if top == "memory":
        return (
            resolved.suffix.lower() == ".md"
            and parts[1] not in _MEMORY_IGNORE
        )
    if top == "skills":
        protected = {name.casefold() for name in protected_skills}
        return (
            len(parts) >= 3
            and parts[1].casefold() not in protected
            and parts[-1].casefold() not in {
                name.casefold() for name in _WATCH_IGNORE_NAMES
            }
        )
    return top in {"knowledge", "output"} and len(parts) >= 2


class _WorkspaceWriteGuard:
    """Wraps a write/edit tool so it can ONLY write inside the workspace.

    Hard engineering guard (not prompt-based): any write resolving outside the
    workspace — e.g. the project's bundled ``skills/`` dir — is rejected. This
    protects built-in skills regardless of what the model attempts.
    """

    def __init__(
        self, inner, workspace_dir: str, protected_skills: set,
        transaction: _EvolutionWriteTransaction,
    ):
        self._inner = inner
        self._ws = Path(workspace_dir).resolve()
        self._protected_skills = protected_skills
        self._transaction = transaction
        # Mirror the attributes the agent runtime reads off a tool.
        self.name = inner.name
        self.description = inner.description
        self.params = inner.params

    def __getattr__(self, item):
        return getattr(self._inner, item)

    def execute_tool(self, params):
        # The agent runtime calls execute_tool (not execute); route it through
        # our guarded execute so the path checks always run.
        try:
            return self.execute(params)
        except Exception as e:
            logger.error(f"[Evolution] guarded tool error: {e}")
            from agent.tools.base_tool import ToolResult
            return ToolResult.fail(f"Error: {e}")

    def execute(self, args):
        from agent.tools.base_tool import ToolResult
        path = (args.get("path") or "").strip()
        if not path:
            return ToolResult.fail("Error: evolution write path is required.")
        try:
            resolved = Path(self._inner._resolve_path(path)).resolve()
        except Exception as e:
            return ToolResult.fail(f"Error: invalid evolution write path '{path}': {e}")
        if not _allowed_evolution_path(
            self._ws, resolved, self._protected_skills
        ):
            return ToolResult.fail(
                "Error: evolution may only write approved memory, persona, "
                "custom-skill, knowledge, or output files; "
                f"path '{path}' was blocked."
            )
        try:
            self._transaction.record(resolved)
        except Exception as e:
            return ToolResult.fail(f"Error: {e}")
        return self._inner.execute(args)


def _guard_tools(
    tools: list, workspace_dir: str, protected_skills: set,
    transaction: _EvolutionWriteTransaction,
) -> list:
    """Wrap evolution write tools with path and transaction guards."""
    guarded = []
    for t in tools:
        name = getattr(t, "name", None)
        if name in _WRITE_TOOLS:
            guarded.append(_WorkspaceWriteGuard(
                t, workspace_dir, protected_skills, transaction
            ))
        else:
            guarded.append(t)
    return guarded


# Workspace subtrees worth watching for evolution-induced changes. AGENT.md is
# watched too: evolution may rarely refine the assistant's persona/style there.
_WATCH_SUBDIRS = ("MEMORY.md", "AGENT.md", "skills", "knowledge", "output")
# Subpaths under memory/ to ignore: evolution's own bookkeeping + the nightly
# dream diary, none of which count as a user-facing change signal.
_MEMORY_IGNORE = (".evolution_backups", "dreams", "evolution")
# Files the skill subsystem maintains automatically (the enable/disable index).
# Not an evolution result, so a rewrite must not count as a change signal.
_WATCH_IGNORE_NAMES = ("skills_config.json",)


def _workspace_snapshot(workspace_dir) -> dict:
    """Map relative path -> (mtime, size) for watched files. Cheap, no reads."""
    ws = Path(workspace_dir)
    snap: dict = {}
    for name in _WATCH_SUBDIRS:
        root = ws / name
        if root.is_file():
            try:
                st = root.stat()
                snap[name] = (st.st_mtime, st.st_size)
            except OSError:
                pass
            continue
        if not root.is_dir():
            continue
        for p in root.rglob("*"):
            if not p.is_file():
                continue
            if p.name in _WATCH_IGNORE_NAMES:
                continue
            try:
                st = p.stat()
                snap[str(p.relative_to(ws))] = (st.st_mtime, st.st_size)
            except OSError:
                pass

    # Watch the daily memory files (memory/*.md and per-user dailies) since
    # evolution now records learnings there. Skip backups/dreams bookkeeping.
    mem_dir = ws / "memory"
    if mem_dir.is_dir():
        for p in mem_dir.rglob("*.md"):
            rel_parts = p.relative_to(mem_dir).parts
            if rel_parts and rel_parts[0] in _MEMORY_IGNORE:
                continue
            try:
                st = p.stat()
                snap[str(p.relative_to(ws))] = (st.st_mtime, st.st_size)
            except OSError:
                pass
    return snap


def _workspace_changed(workspace_dir, pre: dict) -> bool:
    """True if any watched file was added, removed, or modified since ``pre``."""
    return _workspace_snapshot(workspace_dir) != pre


def _valid_evolution_result(result: str) -> bool:
    """Reject malformed/no-content summaries before committing file changes."""
    cleaned = (result or "").replace(SILENT_TOKEN, "").strip()
    if not cleaned or len(cleaned) > 4000:
        return False
    return any(ch.isalnum() for ch in cleaned)


def run_evolution_for_session(
    agent_bridge,
    session_id: str,
    agent_id: str = "default",
    channel_type: str = "",
    receiver: str = "",
    user_id: Optional[str] = None,
    idle_minutes: float = 0.0,
) -> bool:
    """Run one evolution pass for a session. Returns True if it changed anything.

    Safe to call from a background thread. All failures are swallowed and
    logged — evolution must never disrupt the main pipeline.
    """
    cfg = get_evolution_config()
    if not cfg.enabled:
        return False

    # Concurrency gate: bound how many evolution passes run at once.
    global _running_count
    with _running_lock:
        if _running_count >= _MAX_CONCURRENT:
            logger.info(
                f"[Evolution] busy ({_running_count}/{_MAX_CONCURRENT} running); "
                f"skipping session={session_id} this scan"
            )
            return False
        _running_count += 1

    transaction: Optional[_EvolutionWriteTransaction] = None
    try:
        if hasattr(agent_bridge, "get_cached_agent"):
            agent = agent_bridge.get_cached_agent(session_id, agent_id=agent_id)
        else:
            agent = agent_bridge.agents.get(session_id) or agent_bridge.default_agent
        if not agent:
            return False

        # Consume the trigger only after this pass has secured a concurrency
        # slot and resolved its session. Sessions rejected by the gate keep
        # their accumulated turns and remain eligible for the next scan.
        agent._evo_turns = 0

        with agent.messages_lock:
            all_messages = list(agent.messages)
        total_msgs = len(all_messages)
        # In-memory evolution cursor: only review messages added since the last
        # pass so a long session doesn't re-judge (and re-write) old content.
        # Stored on the agent instance; lost on restart (acceptable — at worst
        # one redundant pass right after a restart, gated by the file-change
        # check downstream so it won't double-write identical memory).
        done = int(getattr(agent, "_evo_done_msg_count", 0))
        if done > total_msgs:
            done = 0  # history was trimmed/reset; start fresh
        new_messages = all_messages[done:]
        transcript = _build_transcript(new_messages)
        if not transcript.strip():
            # Routine no-op: the per-minute scan hits every idle session. Advance
            # the cursor so we don't re-scan the same tail; no log (pure noise).
            agent._evo_done_msg_count = total_msgs
            return False

        logger.info(
            f"[Evolution] ▶ Reviewing session={session_id} "
            f"(idle {idle_minutes:.1f}min, {len(new_messages)} new/{total_msgs} msgs, "
            f"~{len(transcript)} chars)"
        )

        # Resolve workspace + files to snapshot for undo.
        mem_cfg = getattr(getattr(agent, "memory_manager", None), "config", None)
        if mem_cfg is None:
            from agent.memory.config import get_default_memory_config
            mem_cfg = get_default_memory_config()
        workspace_dir = mem_cfg.get_workspace()
        if user_id:
            memory_file = Path(workspace_dir) / "memory" / "users" / user_id / "MEMORY.md"
        else:
            memory_file = Path(workspace_dir) / "MEMORY.md"
        skills_dir = mem_cfg.get_skills_dir()

        # Snapshot MEMORY.md + every NON-protected skill's SKILL.md. Protected
        # built-in skills are excluded from backup because they must never be
        # edited in the first place.
        protected_names = _builtin_skill_names()
        transaction = _EvolutionWriteTransaction(Path(workspace_dir))
        # Back up both MEMORY.md and today's daily file: evolution now writes to
        # the daily file, but MEMORY.md is cheap to snapshot and keeps undo safe
        # if the model ever edits it.
        today_daily = Path(workspace_dir) / "memory" / (
            datetime.now().strftime("%Y-%m-%d") + ".md"
        )
        if user_id:
            today_daily = Path(workspace_dir) / "memory" / "users" / user_id / (
                datetime.now().strftime("%Y-%m-%d") + ".md"
            )
        # AGENT.md (persona) is backed up too so a rare persona edit is undoable.
        # Persona is workspace-global (not per-user): it always lives at the
        # workspace root, regardless of user_id.
        agent_file = Path(workspace_dir) / "AGENT.md"
        backup_files = [Path(memory_file), today_daily, agent_file]
        if skills_dir.exists():
            for skill_md in skills_dir.rglob("SKILL.md"):
                # The skill dir is the SKILL.md's parent (or an ancestor for
                # collections); guard by checking the immediate top-level dir.
                try:
                    top = skill_md.relative_to(skills_dir).parts[0]
                except (ValueError, IndexError):
                    continue
                if top in protected_names:
                    continue
                backup_files.append(skill_md)
        backup_id = create_backup(workspace_dir, backup_files)
        _backup_n = sum(1 for f in backup_files if Path(f).exists())

        # Snapshot the whole workspace (path -> mtime/size) so we can reliably
        # detect ANY file change — including new output files written when
        # finishing an unfinished task, which are not in backup_files.
        pre_snapshot = _workspace_snapshot(workspace_dir)

        # Build the isolated review agent: same model, restricted tools, with a
        # hard guard that confines all writes to the workspace (protects the
        # project's bundled skills from ever being modified).
        review_tools = _guard_tools(
            _select_tools(list(getattr(agent, "tools", []) or [])),
            str(workspace_dir),
            protected_names,
            transaction,
        )
        review_agent = agent_bridge.create_agent(
            system_prompt="",
            tools=review_tools,
            description="Self-evolution review agent",
            max_steps=cfg.max_steps,
            workspace_dir=str(workspace_dir),
            skill_manager=getattr(agent, "skill_manager", None),
            memory_manager=getattr(agent, "memory_manager", None),
            enable_skills=True,
            runtime_info=getattr(agent, "runtime_info", None),
        )
        # Mark this as a restricted review agent so runtime MCP reconciliation
        # (ToolManager.sync_mcp_into_agent) will NOT silently re-inject MCP tools
        # that _select_tools()/_guard_tools() intentionally withheld. Without this
        # flag the review boundary would be re-opened on the first LLM turn.
        review_agent._evolution_restricted = True
        # Reuse the live model so it follows the user's configured model.
        review_agent.model = agent.model
        # Inject the evolution task brief AFTER the full system prompt: the agent
        # gets the full context (tools, workspace, user preferences, memory, time)
        # AND its evolution-specific instructions on top, instead of one
        # overwriting the other.
        review_agent.extra_system_suffix = EVOLUTION_SYSTEM_PROMPT

        logger.info(
            f"[Evolution] backup {backup_id} ({_backup_n} files) → running review agent"
        )
        user_msg = build_review_user_message(transcript, protected_skills=list(protected_names))
        result = review_agent.run_stream(user_msg, clear_history=True)
        result = (result or "").strip()

        # These messages are now reviewed; advance the cursor so the next pass
        # only looks at messages added after this point (silent or not).
        agent._evo_done_msg_count = total_msgs

        # Respect an explicit silent verdict: empty, exactly [SILENT], or text
        # that STARTS with [SILENT] means the model chose to stay quiet.
        if not result or result.startswith(SILENT_TOKEN):
            logger.info(f"[Evolution] ✗ No change for session={session_id} ([SILENT])")
            return False

        # Anti-nag backstop: if the model wrote a summary but actually changed no
        # watched file, stay silent — never notify about work that didn't happen.
        if not _workspace_changed(workspace_dir, pre_snapshot):
            logger.info(
                f"[Evolution] ✗ session={session_id}: text produced but no file "
                f"changed — staying silent"
            )
            return False

        # The model produced a real summary. Strip any stray [SILENT] tokens it
        # left mid-text, then notify.
        result = result.replace(SILENT_TOKEN, "").strip()
        if not _valid_evolution_result(result):
            logger.info(
                f"[Evolution] ✗ Invalid/no-content result for session={session_id}; "
                "rolling back"
            )
            return False

        logger.info(f"[Evolution] ✓ session={session_id} evolved:\n{result}")
        append_session_evolution(workspace_dir, result, backup_id=backup_id, user_id=user_id)
        # Inject an [EVOLUTION] note so the main agent can honor "undo".
        _inject_evolution_record(
            agent_bridge, session_id, channel_type, result, backup_id, agent_id
        )
        # The injection appended its own messages ([SCHEDULED]/[EVOLUTION]).
        # Advance the cursor past them so the next scan does not treat
        # evolution's own bookkeeping as new user content and re-trigger.
        try:
            with agent.messages_lock:
                agent._evo_done_msg_count = len(agent.messages)
        except Exception:
            pass

        # Push the summary to the user's channel. The "did a file actually
        # change" gate above is the only throttle we need: real evolutions are
        # rare, so no extra opt-in switch or daily-count limit is required.
        if channel_type and receiver:
            _notify_user(channel_type, receiver, result)

        transaction.commit()
        return True

    except Exception as e:
        logger.warning(f"[Evolution] Run failed for session={session_id}: {e}")
        return False
    finally:
        if transaction is not None:
            transaction.rollback()
        with _running_lock:
            _running_count -= 1


def _inject_evolution_record(
    agent_bridge,
    session_id: str,
    channel_type: str,
    summary: str,
    backup_id: Optional[str],
    agent_id: str = None,
) -> None:
    """Add an [EVOLUTION] note to the user session so the main agent can undo."""
    try:
        note = f"{EVOLUTION_MARKER} {summary}"
        if backup_id:
            note += f"\n(backup_id: {backup_id}; to undo, restore this backup)"
        # Reuse the scheduler-output injection path: isolated execution, only a
        # compact record lands in the user session.
        remember_kwargs = {
            "session_id": session_id,
            "content": note,
            "channel_type": channel_type,
            "task_description": "self-evolution",
        }
        if hasattr(agent_bridge, "agent_registry"):
            remember_kwargs["agent_id"] = agent_id
        agent_bridge.remember_scheduled_output(**remember_kwargs)
    except Exception as e:
        logger.debug(f"[Evolution] Failed to inject evolution record: {e}")


def _notify_user(channel_type: str, receiver: str, summary: str) -> None:
    """Push the evolution summary to the user's channel as a new message."""
    try:
        from bridge.context import Context, ContextType
        from bridge.reply import Reply, ReplyType
        from channel.channel_factory import create_channel

        context = Context(ContextType.TEXT, summary)
        context["receiver"] = receiver
        context["isgroup"] = False
        context["session_id"] = receiver
        # Channels that reply to an original message need msg=None for a fresh push.
        if channel_type in ("feishu", "dingtalk", "wecom_bot", "qq"):
            context["msg"] = None
        if channel_type == "feishu":
            context["receive_id_type"] = "open_id"

        channel = create_channel(channel_type)
        if not channel:
            return

        # Web is request-response: a background push needs a synthetic request_id
        # plus a request->session mapping so the channel can route the message to
        # the user's polling queue (same approach the scheduler uses).
        if channel_type == "web":
            import uuid
            request_id = f"evolution_{uuid.uuid4().hex[:8]}"
            context["request_id"] = request_id
            if hasattr(channel, "request_to_session"):
                channel.request_to_session[request_id] = receiver

        channel.send(Reply(ReplyType.TEXT, summary), context)
        logger.info(f"[Evolution] Notified user via {channel_type}")
    except Exception as e:
        logger.warning(f"[Evolution] Failed to notify user: {e}")
