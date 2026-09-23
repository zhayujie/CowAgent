"""
ChatService - Wraps the Agent stream execution to produce CHAT protocol chunks.

Translates agent events (message_update, message_end, tool_execution_end, etc.)
into the CHAT socket protocol format (content chunks with segment_id, tool_calls chunks).
"""

import re
import uuid
from typing import Callable, Optional

from common.log import logger


class ChatService:
    """
    High-level service that runs an Agent for a given query and streams
    the results as CHAT protocol chunks via a callback.

    Usage:
        svc = ChatService(agent_bridge)
        svc.run(query, session_id, send_chunk_fn)
    """

    def __init__(self, agent_bridge):
        """
        :param agent_bridge: AgentBridge instance (manages agent lifecycle)
        """
        self.agent_bridge = agent_bridge

    def run(
        self,
        query: str,
        session_id: str,
        send_chunk_fn: Callable[[dict], None],
        channel_type: str = "",
        agent_id: str = None,
        request_id: str = None,  # noqa: RUF013
        speaker_agent_id: str = None,
        members: list = None,
        transcript: list = None,
    ):
        """
        Run the agent for *query* and stream results back via *send_chunk_fn*.

        The method blocks until the agent finishes. After it returns the SDK
        will automatically send the final (streaming=false) message.

        :param query: user query text
        :param session_id: session identifier for agent isolation
        :param send_chunk_fn: callable(chunk_data: dict) to send a streaming chunk
        :param channel_type: source channel (e.g. "web", "feishu") for persistence
        :param agent_id: agent that owns the conversation; defaults to the configured default
        :param request_id: per-request cancellation key; defaults to session scope
        :param speaker_agent_id: teammate addressed for this turn; it answers in
            the owner's conversation, so the transcript stays in one place
        :param members: roster of the conversation (teammate ids). When given it
            is authoritative and reconciled onto the session, like a team channel
        :param transcript: attributed messages to run against instead of the
            restored history (conversation kept elsewhere)
        """
        # The conversation belongs to ``resolved_agent_id`` (its owner); only the
        # voice answering this turn may differ. Same model as agent_reply.
        resolved_agent_id = self.agent_bridge._resolve_agent_id(agent_id)

        # Build a context so context-aware tools (e.g. scheduler) can resolve the
        # receiver/session. This streaming path bypasses agent_bridge.agent_reply,
        # so the attach step that normally happens there must be done here too.
        context = self._build_context(
            query, session_id, channel_type, resolved_agent_id
        )
        speaker_id = resolved_agent_id
        model_query = query
        is_team = False
        cached = False
        if speaker_agent_id or members is not None:
            if members is not None:
                context["members"] = list(members)
            if speaker_agent_id:
                context["speaker_agent_id"] = speaker_agent_id
            self.agent_bridge._seed_team_members(session_id, resolved_agent_id, context)
            peer_speaker = self._peer_speaker(speaker_agent_id, resolved_agent_id)
            if peer_speaker is not None:
                self._run_on_peer(
                    query, session_id, channel_type, resolved_agent_id,
                    peer_speaker, send_chunk_fn,
                )
                return
            speaker_id = self.agent_bridge._resolve_speaker(resolved_agent_id, context)
            is_team = speaker_id != resolved_agent_id or self._has_team(session_id, resolved_agent_id)
            if speaker_agent_id:
                # What the model is asked once the address has been acted on
                # (also when the owner itself was named); the transcript keeps
                # the verbatim query.
                model_query = self.agent_bridge._strip_address(query, speaker_id)
            cached = self.agent_bridge._has_runtime(speaker_id, session_id)
            agent = self.agent_bridge.get_agent(
                session_id=session_id,
                agent_id=speaker_id,
                host_agent_id=resolved_agent_id,
            )
        else:
            agent = self.agent_bridge.get_agent(
                session_id=session_id, agent_id=resolved_agent_id
            )
        if agent is None:
            raise RuntimeError("Failed to initialise agent for the session")
        if is_team:
            # One transcript per team conversation: reload it with author labels
            # so this speaker sees the turns others spoke since it last ran. A
            # runtime built for this turn has only just restored it.
            if cached:
                self.agent_bridge._sync_shared_transcript(agent, session_id, resolved_agent_id)
            self._send_speaker(send_chunk_fn, speaker_id)
        if transcript is not None:
            with agent.messages_lock:
                agent.messages = list(transcript)

        # Pass context metadata to model for downstream API requests
        if hasattr(agent, 'model'):
            agent.model.channel_type = channel_type or ""
            agent.model.session_id = session_id or ""
            agent.model.agent_id = speaker_id

        self._attach_context_aware_tools(agent, context)

        # Mark this session as mid-run so the self-evolution idle scan does not
        # fire concurrently when a single turn runs longer than idle_minutes.
        self._mark_run_active(agent, True)

        # State shared between the event callback and this method
        state = _StreamState()

        def flush_file_links():
            """Emit any buffered file links as content, then drop them."""
            if not state.pending_file_links:
                return
            links = state.pending_file_links
            state.pending_file_links = []
            send_chunk_fn({
                "chunk_type": "content",
                "delta": "\n\n" + "\n\n".join(links) + "\n\n",
                "segment_id": state.segment_id,
            })

        def on_event(event: dict):
            """Translate agent events into CHAT protocol chunks."""
            event_type = event.get("type")
            data = event.get("data", {})

            if event_type == "reasoning_update":
                delta = data.get("delta", "")
                if delta:
                    send_chunk_fn({
                        "chunk_type": "reasoning",
                        "delta": delta,
                        "segment_id": state.segment_id,
                    })

            elif event_type == "message_update":
                # Incremental text delta
                delta = data.get("delta", "")
                if delta:
                    send_chunk_fn({
                        "chunk_type": "content",
                        "delta": delta,
                        "segment_id": state.segment_id,
                    })

            elif event_type == "message_end":
                # A content segment finished.
                tool_calls = data.get("tool_calls", [])
                if tool_calls:
                    # After tool_calls are executed the next content will be
                    # a new segment; collect tool results until turn_end.
                    state.pending_tool_results = []

            elif event_type == "tool_retrieval":
                # Forward sanitized retrieval metadata for progress displays.
                send_chunk_fn({
                    "chunk_type": "tool_retrieval",
                    "data": data,
                })

            elif event_type == "file_to_send":
                url = data.get("url") or ""
                if url:
                    fname = data.get("file_name") or "file"
                    ft = data.get("file_type") or "file"
                    if ft == "image":
                        link = f"![{fname}]({url})"
                    else:
                        link = f"[{fname}]({url})"
                    state.pending_file_links.append(link)
                    # Remove url so the model won't repeat it in its reply
                    data.pop("url", None)

            elif event_type == "tool_execution_start":
                # Notify the client that a tool is about to run (with its input args)
                tool_name = data.get("tool_name", "")
                arguments = data.get("arguments", {})
                # Cache arguments keyed by tool_call_id so tool_execution_end can include them
                tool_call_id = data.get("tool_call_id", tool_name)
                state.pending_tool_arguments[tool_call_id] = arguments
                send_chunk_fn({
                    "chunk_type": "tool_start",
                    "tool": tool_name,
                    "arguments": arguments,
                    # Carry the call id so later subagent_step chunks can attach
                    # their inner steps to the right card via card_id.
                    "tool_id": tool_call_id,
                })

            elif event_type == "tool_execution_end":
                tool_name = data.get("tool_name", "")
                tool_call_id = data.get("tool_call_id", tool_name)
                # Retrieve cached arguments from the matching tool_execution_start event
                arguments = state.pending_tool_arguments.pop(tool_call_id, data.get("arguments", {}))
                result = data.get("result", "")
                status = data.get("status", "unknown")
                execution_time = data.get("execution_time", 0)
                elapsed_str = f"{execution_time:.2f}s"

                # Serialise result to string if needed
                if not isinstance(result, str):
                    import json
                    try:
                        result = json.dumps(result, ensure_ascii=False)
                    except Exception:
                        result = str(result)

                tool_info = {
                    "name": tool_name,
                    "arguments": arguments,
                    "result": result,
                    "status": status,
                    "elapsed": elapsed_str,
                    # Same id the matching tool_start carried, so the frontend can
                    # carry sub agent substeps over from the loading card to this
                    # resolved one (see collectLoadingSubsteps / carried.get).
                    "id": tool_call_id,
                }

                # A call settles when its own tool finishes, not when the round
                # does. A delegated turn holds the round open for as long as the
                # teammate works, so every call made inside one - the hand-off
                # included - would otherwise sit unfinished until it returns.
                send_chunk_fn({
                    "chunk_type": "tool_end",
                    "tool_id": tool_call_id,
                    "tool": tool_name,
                    "status": status,
                    "result": result,
                    "elapsed": elapsed_str,
                })

                # Still collected for the closing batch: a client that predates
                # the chunk above learns the outcome there, as it always did.
                if state.pending_tool_results is not None:
                    state.pending_tool_results.append(tool_info)

            elif event_type == "subagent_step":
                # A single step a sub agent ran inside a still-in-flight
                # `subagent` tool call. Forwarded immediately (NOT batched into
                # pending_tool_results) so the console can follow the sub
                # agent's progress live instead of waiting minutes for the whole
                # spawn to finish and flush at turn_end.
                send_chunk_fn({
                    "chunk_type": "subagent_step",
                    "card_id": data.get("card_id"),
                    "step_id": data.get("step_id"),
                    "phase": data.get("phase"),
                    # Frontend expects `tool`; the event carries `tool_name`.
                    "tool": data.get("tool_name") or data.get("tool") or "tool",
                    "arguments": data.get("arguments") or {},
                    "status": data.get("status"),
                    "execution_time": data.get("execution_time"),
                    "error": data.get("error"),
                })

            elif event_type == "peer_message_start":
                # A teammate takes over for a stretch of this turn. What follows
                # is its reply, in the same chunks as any other, until the
                # matching end marker hands the floor back.
                send_chunk_fn({
                    "chunk_type": "peer_start",
                    "card_id": data.get("card_id"),
                    "agent_id": data.get("agent_id"),
                    "agent_name": data.get("agent_name"),
                })

            elif event_type == "peer_message_end":
                send_chunk_fn({
                    "chunk_type": "peer_end",
                    "card_id": data.get("card_id"),
                    "agent_id": data.get("agent_id"),
                    "status": data.get("status", "done"),
                })

            elif event_type == "artifact":
                # A file a (sub) agent wrote. Forward live so it can be previewed
                # as soon as it exists rather than only after the turn settles.
                send_chunk_fn({
                    "chunk_type": "artifact",
                    "artifact": data,
                })

            elif event_type == "turn_end":
                has_tool_calls = data.get("has_tool_calls", False)
                if has_tool_calls and state.pending_tool_results:
                    # Flush collected tool results as a single tool_calls chunk
                    send_chunk_fn({
                        "chunk_type": "tool_calls",
                        "tool_calls": state.pending_tool_results,
                    })
                    state.pending_tool_results = None
                    # Next content belongs to a new segment
                    state.segment_id += 1
                # Now that the tool results are out, the links belong to the
                # content that follows them.
                flush_file_links()

        # Run the agent with our event callback ---------------------------
        logger.info(
            f"[ChatService] Starting agent run: agent={resolved_agent_id}, "
            f"session={session_id}, query={query[:80]}"
        )

        from config import conf
        max_context_turns = conf().get("agent_max_context_turns", 20)

        # Get full system prompt with skills
        full_system_prompt = agent.get_full_system_prompt()

        # Create a copy of messages for this execution
        with agent.messages_lock:
            messages_copy = agent.messages.copy()
            original_length = len(agent.messages)

        from agent.protocol.agent_stream import AgentStreamExecutor

        # Register a cancel token so /cancel can abort this in-flight run.
        # API calls can key by request; IM channels remain session scoped.
        from agent.protocol import get_cancel_registry, get_steer_registry
        registry = get_cancel_registry()
        steer_registry = get_steer_registry()
        scoped_session_key = (
            self.agent_bridge._cancel_key(
                resolved_agent_id,
                session_id,
                self.agent_bridge.agent_registry.default_agent_id,
            )
            if session_id
            else None
        )
        cancel_key = (
            self.agent_bridge._cancel_key(
                resolved_agent_id,
                request_id,
                self.agent_bridge.agent_registry.default_agent_id,
            )
            if request_id
            else scoped_session_key
        )
        # Both the token and its session grouping are namespaced: two Agents
        # serving the same session id must not cancel or steer each other.
        cancel_event = (
            registry.register(cancel_key, session_id=scoped_session_key)
            if cancel_key
            else None
        )
        steer_inbox = (
            steer_registry.register(scoped_session_key) if scoped_session_key else None
        )

        executor = AgentStreamExecutor(
            agent=agent,
            model=agent.model,
            system_prompt=full_system_prompt,
            tools=agent.tools,
            max_turns=agent.max_steps,
            on_event=on_event,
            messages=messages_copy,
            max_context_turns=max_context_turns,
            cancel_event=cancel_event,
            steer_inbox=steer_inbox,
        )

        try:
            if cancel_event is not None and cancel_event.is_set():
                logger.info(
                    f"[ChatService] Skipping pre-cancelled run: agent={resolved_agent_id}, "
                    f"session={session_id}"
                )
                return
            executor.run_stream(model_query)
        except Exception:
            # If executor cleared messages (context overflow), sync back
            if len(executor.messages) == 0:
                with agent.messages_lock:
                    agent.messages.clear()
                    logger.info("[ChatService] Cleared agent message history after executor recovery")
            raise
        finally:
            # Clear the mid-run flag so idle scans can review this session again.
            self._mark_run_active(agent, False)
            # Release cancel token to keep the registry bounded.
            if cancel_key:
                try:
                    registry.unregister(cancel_key)
                except Exception:
                    pass
            if scoped_session_key and steer_inbox is not None:
                steer_registry.unregister(scoped_session_key, steer_inbox)

        # A run that ends without a closing turn_end (e.g. the last turn had no
        # tool calls to flush) must still deliver whatever the send tool uploaded.
        flush_file_links()

        # Sync executor messages back to agent (thread-safe).
        # The executor may have trimmed context, making its list shorter than
        # original_length. In that case we must replace entirely — just
        # appending would leave stale pre-trim messages in agent.messages
        # and cause the same trim to fire on every subsequent request.
        with agent.messages_lock:
            run_start = executor.run_start_index()
            trimmed = len(executor.messages) < original_length
            if run_start is not None:
                new_messages = list(executor.messages[run_start:])
            elif trimmed:
                # Context was trimmed: the executor appended the new user
                # query *before* trimming, so the new messages (user +
                # assistant + tools) sit at the tail of the trimmed list.
                # We cannot simply slice at original_length (it exceeds the
                # list length).  Instead, count how many messages the
                # executor added on top of the post-trim baseline.
                #
                # Timeline inside executor.run_stream:
                #   1. messages had `original_length` items
                #   2. append user query  → original_length + 1
                #   3. _trim_messages()   → some smaller number (includes the
                #      user query because it belongs to the last turn)
                #   4. LLM replies / tool calls appended
                #
                # The user query message is always the first message of the
                # last turn (it cannot be trimmed away), so we locate it to
                # find where "new" messages begin.
                new_start = original_length  # fallback
                for idx in range(len(executor.messages) - 1, -1, -1):
                    msg = executor.messages[idx]
                    if msg.get("role") == "user":
                        content = msg.get("content", [])
                        is_user_query = False
                        if isinstance(content, list):
                            has_text = any(
                                isinstance(b, dict) and b.get("type") == "text"
                                for b in content
                            )
                            has_tool_result = any(
                                isinstance(b, dict) and b.get("type") == "tool_result"
                                for b in content
                            )
                            is_user_query = has_text and not has_tool_result
                        elif isinstance(content, str):
                            is_user_query = True
                        if is_user_query:
                            new_start = idx
                            break
                new_messages = list(executor.messages[new_start:])
            else:
                new_messages = list(executor.messages[original_length:])
            agent.messages = list(executor.messages)

        # Persist new messages to SQLite so they survive restarts and
        # can be queried via the HISTORY interface. The store is the owner's:
        # a guest speaker writes into the shared transcript, stamped as author.
        if new_messages:
            workspace_root = agent.workspace_dir
            if is_team:
                new_messages = self.agent_bridge._attribute_to_speaker(
                    new_messages, speaker_id
                )
                new_messages = self.agent_bridge._strip_speaker_prefix_from_messages(
                    new_messages
                )
                workspace_root = self._owner_workspace(resolved_agent_id, agent)
            if model_query != query:
                new_messages = self._restore_verbatim_query(
                    new_messages, model_query, query
                )
            self._persist_messages(
                session_id,
                list(new_messages),
                channel_type,
                workspace_root=workspace_root,
            )

        # Store executor reference for files_to_send access
        agent.stream_executor = executor

        # Execute post-process tools
        agent._execute_post_process_tools()

        # Record this user turn for the self-evolution idle trigger. This
        # streaming path bypasses agent_bridge.agent_reply, so the activity must
        # be noted here, otherwise idle scans never see any signal to evolve.
        self._note_evolution_turn(agent, context)

        logger.info(
            f"[ChatService] Agent run completed: agent={resolved_agent_id}, "
            f"session={session_id}"
        )



    @staticmethod
    def _build_context(
        query: str, session_id: str, channel_type: str, agent_id: str = "default"
    ):
        """Build a Context for tool resolution on the streaming chat path.

        receiver falls back to session_id; the scheduler's delivery keys on
        session_id as the receiver.
        """
        from bridge.context import Context, ContextType
        # Pass an explicit kwargs dict: Context's default kwargs is a shared
        # mutable default, so omitting it would leak fields across sessions.
        ctx = Context(ContextType.TEXT, query, kwargs={})
        ctx["session_id"] = session_id
        ctx["receiver"] = session_id
        ctx["isgroup"] = False
        ctx["channel_type"] = channel_type or ""
        ctx["agent_id"] = agent_id
        return ctx

    @staticmethod
    def _has_team(session_id: str, host_agent_id: str) -> bool:
        """Whether the session has teammates on it (a shared conversation)."""
        if not session_id:
            return False
        try:
            from agent.workspace import session_prefs
            return bool(session_prefs.get_prefs(session_id, host_agent_id).get("members"))
        except Exception:
            return False

    def _send_speaker(self, send_chunk_fn, speaker_id: str) -> None:
        """Tell the client who is answering this turn, so a shared conversation
        can attribute the reply to the right agent as it streams."""
        try:
            profile = self.agent_bridge.agent_registry.get(speaker_id, require_enabled=False)
            send_chunk_fn({
                "chunk_type": "speaker",
                "agent_id": profile.id,
                "name": profile.name,
                "avatar": profile.avatar or "",
            })
        except Exception as e:
            logger.debug(f"[ChatService] speaker chunk skipped: {e}")

    # ---- peer speaker --------------------------------------------------------

    def _peer_speaker(self, addressed_id: str, owner_agent_id: str):
        """The addressed peer, or None when the id is empty, the owner, a local
        agent, or unknown to the transport."""
        addressed_id = str(addressed_id or "").strip()
        if not addressed_id or addressed_id == owner_agent_id:
            return None
        try:
            self.agent_bridge.agent_registry.get_addressed(addressed_id, require_enabled=False)
            return None
        except Exception:
            pass
        try:
            from agent.multiagent import get_transport, peer as peer_of
        except Exception:
            return None
        if get_transport() is None:
            return None
        return peer_of(addressed_id)

    def _run_on_peer(
        self,
        query: str,
        session_id: str,
        channel_type: str,
        owner_agent_id: str,
        peer,
        send_chunk_fn: Callable[[dict], None],
    ) -> None:
        """The addressed peer answers this turn; its reply streams under its
        name and is stored in the owner's transcript, like a local guest."""
        from agent.multiagent import MODE_SPEAK, InvokeRequest, get_transport

        transport = get_transport()
        owner = self.agent_bridge.agent_registry.get(owner_agent_id, require_enabled=False)
        roster = self._roster(session_id, owner_agent_id)

        members = [owner.id, *(m for m in roster if m not in (owner.id, peer.id))]
        peers = []
        for member_id in members:
            profile = self._teammate_profile(member_id)
            if profile is not None:
                peers.append(profile)

        request = InvokeRequest(
            request_id=uuid.uuid4().hex,
            target_id=peer.id,
            task=self._strip_peer_address(query, peer),
            source_id=owner.id,
            source_name=owner.name,
            root_session_id=session_id,
            trace=(owner.id,),
            depth=0,
            members=tuple(members),
            peers=tuple(peers),
            timeout_seconds=self._speak_timeout(),
            mode=MODE_SPEAK,
            history=tuple(self._shared_history(session_id, owner)),
        )

        send_chunk_fn({
            "chunk_type": "speaker",
            "agent_id": peer.id,
            "name": peer.name,
            "avatar": "",
        })
        logger.info(
            f"[ChatService] Turn addressed to peer {peer.id}; "
            f"answering in {owner.id}'s conversation, session={session_id}"
        )

        spoken = []

        def forward(event) -> None:
            if not isinstance(event, dict) or event.get("type") != "chunk":
                return
            chunk = event.get("data")
            if not isinstance(chunk, dict):
                return
            kind = chunk.get("chunk_type")
            if kind == "speaker":
                return
            if kind == "content":
                spoken.append(str(chunk.get("delta") or ""))
            send_chunk_fn(chunk)

        result = transport.invoke(request, on_event=forward)
        if not result.ok:
            raise RuntimeError(f"{peer.name} could not answer: {result.error}")

        content = result.content or "".join(spoken)
        if content and not spoken:
            # nothing was streamed: deliver the reply in one piece
            send_chunk_fn({"chunk_type": "content", "delta": content, "segment_id": 0})
        turn = [
            {"role": "user", "content": [{"type": "text", "text": query}]},
            {"role": "assistant", "content": [{"type": "text", "text": content}]},
        ]
        self._persist_messages(
            session_id,
            self.agent_bridge._attribute_to_speaker(turn, peer.id),
            channel_type,
            workspace_root=owner.workspace,
        )

    def _roster(self, session_id: str, owner_agent_id: str) -> list:
        """Teammate ids on the session, as stored."""
        if not session_id:
            return []
        try:
            from agent.workspace import session_prefs
            return list(session_prefs.get_prefs(session_id, owner_agent_id).get("members") or [])
        except Exception:
            return []

    @staticmethod
    def _teammate_profile(agent_id: str):
        """A PeerAgent for anyone on the team, local or not; None if unknown."""
        from agent.multiagent import PeerAgent, resolve_teammate

        found = resolve_teammate(agent_id)
        return PeerAgent.from_any(found) if found else None

    @staticmethod
    def _strip_peer_address(query: str, peer) -> str:
        """Drop the leading "@name" aimed at ``peer``; see AgentBridge._strip_address."""
        if not query:
            return query
        labels = [label for label in (peer.name, peer.id) if label]
        pattern = (
            r"^\s*@(?:"
            + "|".join(re.escape(label) for label in sorted(labels, key=len, reverse=True))
            + r")[\s,，:：、]*"
        )
        stripped = re.sub(pattern, "", query, count=1, flags=re.IGNORECASE)
        return stripped if stripped.strip() else query

    @staticmethod
    def _restore_verbatim_query(messages: list, model_query: str, query: str) -> list:
        """Put the verbatim query back into the turn's user message.

        The model is asked ``model_query`` (the "@name" already acted on), but
        the transcript must keep what was typed, or replay loses the address.
        Copies are returned; the in-memory context keeps what the model saw.
        """
        restored = list(messages)
        for i, msg in enumerate(restored):
            if msg.get("role") != "user":
                continue
            content = msg.get("content")
            if isinstance(content, str) and model_query in content:
                restored[i] = {**msg, "content": content.replace(model_query, query, 1)}
                return restored
            if isinstance(content, list):
                for j, block in enumerate(content):
                    text = block.get("text") if isinstance(block, dict) and block.get("type") == "text" else None
                    if text and model_query in text:
                        blocks = list(content)
                        blocks[j] = {**block, "text": text.replace(model_query, query, 1)}
                        restored[i] = {**msg, "content": blocks}
                        return restored
        return restored

    @staticmethod
    def _speak_timeout() -> float:
        try:
            from config import conf
            return float((conf().get("agent_delegation") or {}).get("timeout_seconds") or 600)
        except Exception:
            return 600.0

    def _shared_history(self, session_id: str, owner) -> list:
        """Text-only history with authors, oldest first."""
        try:
            from config import conf
            if not conf().get("conversation_persistence", True):
                return []
            from agent.memory import get_conversation_store
            from bridge.agent_initializer import AgentInitializer

            max_turns = conf().get("agent_max_context_turns", 20)
            saved = get_conversation_store(owner.workspace).load_messages(
                session_id, max_turns=max(3, max_turns // 2), with_authors=True
            )
        except Exception as e:
            logger.warning(f"[ChatService] shared history unavailable for {session_id}: {e}")
            return []
        history = []
        for message in AgentInitializer._filter_text_only_messages(saved or []):
            blocks = message.get("content") or []
            text = blocks[0].get("text", "") if blocks and isinstance(blocks[0], dict) else ""
            if not text:
                continue
            entry = {"role": message["role"], "text": text}
            if message["role"] == "assistant":
                entry["agent_id"] = message.get("agent_id") or owner.id
            history.append(entry)
        return history

    def _owner_workspace(self, owner_agent_id: str, agent) -> str:
        """Workspace whose store holds the conversation: the owner's."""
        try:
            return self.agent_bridge.agent_registry.get(
                owner_agent_id, require_enabled=False
            ).workspace
        except Exception:
            return agent.workspace_dir

    def _attach_context_aware_tools(self, agent, context):
        """Attach the current context to tools that need turn metadata."""
        try:
            if not (context and getattr(agent, "tools", None)):
                return
            for tool in agent.tools:
                if tool.name == "scheduler":
                    from agent.tools.scheduler.integration import attach_scheduler_to_tool
                    attach_scheduler_to_tool(tool, context)
                elif tool.name == "agent_delegate":
                    from agent.tools.agent_delegate.agent_delegate import attach_agent_delegate_to_tool
                    attach_agent_delegate_to_tool(tool, self.agent_bridge, context)
                elif tool.name in ("team_send", "team_inbox", "team_task"):
                    from agent.tools.team_collab import attach_team_collab_tools
                    attach_team_collab_tools(tool, self.agent_bridge, context)
        except Exception as e:
            logger.warning(f"[ChatService] Failed to attach context to scheduler: {e}")

    @staticmethod
    def _mark_run_active(agent, active):
        """Toggle the self-evolution mid-run flag for this session's agent."""
        try:
            from agent.evolution.trigger import mark_run_active
            mark_run_active(agent, active)
        except Exception:
            pass

    @staticmethod
    def _note_evolution_turn(agent, context):
        """Record a user turn so the self-evolution idle trigger has signal."""
        try:
            from agent.evolution.trigger import note_user_turn
            ch = (context.get("channel_type") or "") if context else ""
            rcv = (context.get("receiver") or "") if context else ""
            is_group = bool(context.get("isgroup")) if context else False
            # Only single chats get a proactive push target; group push is noisy.
            note_user_turn(agent, channel_type=ch, receiver=(rcv if not is_group else ""))
        except Exception:
            pass

    @staticmethod
    def _persist_messages(
        session_id: str,
        new_messages: list,
        channel_type: str = "",
        workspace_root: str = None,
    ):
        try:
            from config import conf
            if not conf().get("conversation_persistence", True):
                return
        except Exception:
            pass
        try:
            from agent.memory import get_conversation_store
            get_conversation_store(workspace_root).append_messages(
                session_id, new_messages, channel_type=channel_type
            )
        except Exception as e:
            logger.warning(
                f"[ChatService] Failed to persist messages for session={session_id}: {e}"
            )


class _StreamState:
    """Mutable state shared between the event callback and the run method."""

    def __init__(self):
        self.segment_id: int = 0
        # None means we are not accumulating tool results right now.
        # A list means we are in the middle of a tool-execution phase.
        self.pending_tool_results: Optional[list] = None
        # Maps tool_call_id -> arguments captured from tool_execution_start,
        # so that tool_execution_end can attach the correct input args.
        self.pending_tool_arguments: dict = {}
        # Markdown links for files the send tool uploaded, held until the turn's
        # tool results have been flushed. Emitting one the moment the tool reports
        # it would place content between a tool's start and its result, which no
        # other event does and which leaves clients unable to pair the two.
        self.pending_file_links: list = []
