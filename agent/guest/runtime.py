"""Running visitor conversations, whatever front end the visitor came through.

Deliberately not routed through ``AgentBridge.agent_reply``. That path serves
the owner: it resolves the owner's Agent, restores the owner's transcript,
writes to the owner's conversation store, wires the scheduler, delegation and
self-evolution, and builds the prompt from the owner's workspace. A visitor
needs none of it, and every one of those is a way to leak or to poison. The
guest path builds its own Agent from explicit inputs, keeps its transcript in
the guest share store, and shares only the model adapter with the owner.

A front end authenticates its visitors and names the profile, the visitor and
the conversation; everything after that happens here, the same for every
front end. A turn is ``begin`` (checks and reserves, so a refusal comes back
before anything runs) then ``execute`` (runs to the end and returns the
reply). Progress is reported as plain events and files by their virtual path:
streaming them, linking files or sending them as messages is the front end's
job.
"""

from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import re
import shutil
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Deque, Dict, Iterable, List, Optional, Tuple

from agent.guest import policy, store
from agent.guest.paths import GuestPathError, PathGuard
from agent.guest.share import ShareState
from agent.guest.tools import build_guest_tools
from agent.protocol.agent import Agent
from agent.tools.base_tool import is_tool_available
from common.log import logger

AGENT_IDLE_SECONDS = 60 * 60
RESTORE_TURNS = 10
MAX_CONCURRENT_RUNS_PER_PROFILE = 4
# Same budget the console's stream gives a tool result.
MAX_TOOL_RESULT_CHARS = 2000
_CANCEL_MARKER_RE = re.compile(r"_\(Cancelled(?: by user)?\)_")
# Visitor and conversation ids become directory names and database keys.
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_SAFE_NAME_RE = re.compile(r"[^\w.\- ()\u4e00-\u9fff]+")

EventSink = Callable[[Dict[str, Any]], None]


class GuestError(Exception):
    """A request the guest runtime refuses. ``code`` follows HTTP statuses."""

    def __init__(self, code: int, message: str, reason: str = ""):
        super().__init__(message)
        self.code = code
        self.message = message
        self.reason = reason


class GuestAgent(Agent):
    """An Agent whose prompt and reach come only from the guest profile."""

    is_guest = True

    def __init__(self, model, tools, prompt_inputs: Dict[str, Any], work_dir: str, max_steps: int = 30):
        self._prompt_inputs = prompt_inputs
        super().__init__(
            system_prompt="",
            description="Guest share agent",
            model=model,
            tools=tools,
            output_mode="logger",
            max_steps=max_steps,
            workspace_dir=work_dir,
            enable_skills=False,
            skip_context_files=True,
        )
        self.system_prompt = self.get_full_system_prompt()

    def get_full_system_prompt(self, skill_filter=None) -> str:
        from agent.prompt.guest import build_guest_system_prompt

        return build_guest_system_prompt(
            tools=[t for t in self.tools if is_tool_available(t)],
            **self._prompt_inputs,
        )

    def effective_permission_mode(self) -> str:
        # Confinement is enforced by the guest tools themselves, against
        # virtual paths the owner's permission check cannot interpret.
        from agent.permission import FULL_ACCESS

        return FULL_ACCESS

    def write_roots(self) -> list:
        return [self.workspace_dir]

    def protected_paths(self) -> list:
        return []


@dataclass
class GuestTurn:
    """One visitor message, from ``begin`` until ``execute`` returns."""

    id: str
    state: ShareState
    visitor_id: str
    session_id: str
    message: str
    agent: GuestAgent
    guard: PathGuard
    timeout: int
    cancel_event: threading.Event = field(default_factory=threading.Event)
    finished: bool = False

    @property
    def slug(self) -> str:
        return self.state.slug


@dataclass
class TurnResult:
    """``status`` is done, cancelled or failed. ``files`` are the files the
    reply handed to the visitor, by virtual path."""

    content: str
    status: str
    files: List[Dict[str, Any]]
    steps: List[Dict[str, Any]]
    tokens: int
    error: str = ""

    @property
    def failed(self) -> bool:
        return self.status == "failed" or bool(self.error and not self.content.strip())


@dataclass
class _Trace:
    """What one reply did, kept for the transcript so a reload replays it."""

    text: str = ""
    steps: List[Dict[str, Any]] = field(default_factory=list)
    files: List[Dict[str, Any]] = field(default_factory=list)
    arguments: Dict[Any, Any] = field(default_factory=dict)


@dataclass
class GuestSession:
    slug: str
    session_id: str
    agent: Optional[GuestAgent] = None
    fingerprint: str = ""
    guard: Optional[PathGuard] = None
    turns: int = 0
    last_active: float = field(default_factory=time.time)
    turn: Optional[GuestTurn] = None
    requests: Deque[float] = field(default_factory=deque)

    @property
    def busy(self) -> bool:
        return self.turn is not None and not self.turn.finished


_SCRIPT_EXTS = frozenset({".py", ".sh", ".bash", ".zsh", ".js", ".mjs", ".cjs", ".ts", ".rb", ".pl", ".php",
                          ".go", ".ps1", ".bat", ".cmd"})


_SHELL_BLOCK_RE = re.compile(r"^\s*```(?:bash|sh|shell|zsh|console)\b", re.MULTILINE)


def _shared_skills() -> Dict[str, Any]:
    """Every installed skill (built-in and the owner's) as a SkillEntry, by name."""
    from agent.skills.loader import SkillLoader
    from common import state_dir

    builtin = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "skills")
    try:
        return SkillLoader().load_all_skills(builtin_dir=builtin, custom_dir=str(state_dir.skills_dir()),
                                             use_cache=True)
    except Exception as e:
        logger.warning(f"[GuestShare] Could not load shared skills: {e}")
        return {}


def _declares_commands(value: Any) -> bool:
    # Frontmatter from other agent ecosystems nests requirements under their
    # own key, so look for the keys at any depth.
    if isinstance(value, dict):
        return any((k in ("bins", "anyBins", "install") and v) or _declares_commands(v) for k, v in value.items())
    if isinstance(value, list):
        return any(_declares_commands(v) for v in value)
    if isinstance(value, str) and value.lstrip().startswith("{"):
        try:
            return _declares_commands(json.loads(value))
        except ValueError:
            return False
    return False


def _needs_shell(entry: Any) -> bool:
    """Whether a skill works by running commands or scripts, which a
    visitor's Agent cannot; it can still read the skill's files."""
    meta = entry.metadata
    if meta and (meta.install or any(meta.requires.get(k) for k in ("bins", "anyBins"))):
        return True
    if _declares_commands(entry.skill.frontmatter):
        return True
    if _SHELL_BLOCK_RE.search(entry.skill.content or ""):
        return True
    root_depth = entry.skill.base_dir.rstrip(os.sep).count(os.sep)
    for dirpath, dirnames, filenames in os.walk(entry.skill.base_dir):
        if any(os.path.splitext(name)[1].lower() in _SCRIPT_EXTS for name in filenames):
            return True
        if dirpath.count(os.sep) - root_depth >= 2:
            dirnames[:] = []
    return False


def available_skills() -> List[Dict[str, Any]]:
    """The installed skills an owner may offer on a page, for the console."""
    return [{
        "name": name,
        "description": " ".join((entry.skill.description or "").split())[:200],
        "needs_shell": _needs_shell(entry),
    } for name, entry in sorted(_shared_skills().items())]


def reference_suggestions() -> List[Dict[str, str]]:
    """Knowledge base folders the console offers as reference material: each
    knowledge base and its categories. ``agent`` is empty for the shared one."""
    from common.state_dir import shared_root

    roots = [("", os.path.join(str(shared_root()), "knowledge"))]
    try:
        from agent.registry import get_agent_registry

        roots += [(p.name or p.id, os.path.join(p.workspace, "knowledge"))
                  for p in get_agent_registry().list(include_disabled=False) if p.workspace]
    except Exception as e:
        logger.warning(f"[GuestShare] Could not list Agent knowledge bases: {e}")
    out: List[Dict[str, str]] = []
    seen = set()
    for agent, root in roots:
        key = policy.path_key(root)
        if key in seen or not os.path.isdir(root):
            continue
        seen.add(key)
        dirs = [root] + [os.path.join(root, name) for name in sorted(os.listdir(root))
                         if not name.startswith(".") and os.path.isdir(os.path.join(root, name))]
        out += [{"path": d, "agent": agent, "category": "" if d == root else os.path.basename(d)}
                for d in dirs if policy.reference_problem(d) is None]
    return out


def _skill_entries(state: ShareState) -> List[Dict[str, str]]:
    """Skills the profile may use: the listed shared ones plus its own."""
    from agent.skills.loader import SkillLoader

    cfg = state.effective or {}
    wanted = set(cfg.get("skills") or [])
    entries: Dict[str, Any] = {}
    if wanted:
        shared = _shared_skills()
        for name in wanted:
            if name in shared:
                entries[name] = shared[name].skill
    own = state.profile.skills_dir
    if os.path.isdir(own):
        for skill in SkillLoader().load_skills_from_dir(own, source="guest").skills:
            entries[skill.name] = skill
    out = []
    for name in sorted(entries):
        skill = entries[name]
        out.append({
            "name": skill.name,
            "description": (skill.description or "").replace("\n", " ")[:500],
            "dir": skill.base_dir,
            "file": os.path.basename(skill.file_path),
        })
    return out


def _prompt_language(cfg: Dict[str, Any]) -> str:
    """The prompt's language: the page's own, else the instance's."""
    language = (cfg or {}).get("language") or ""
    if not language:
        from common import i18n

        try:
            language = i18n.get_language()
        except Exception:
            language = "zh"
    return "en" if language == "en" else "zh"


def _fingerprint(state: ShareState, skills: List[Dict[str, str]]) -> str:
    payload = json.dumps({
        "cfg": state.effective,
        "md": state.profile.guest_md,
        "skills": skills,
    }, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()


def _text_blocks(text: str) -> List[Dict[str, str]]:
    return [{"type": "text", "text": text}]


def _since_clear(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The records the model still sees: those after the last context clear."""
    for i in range(len(records) - 1, -1, -1):
        record = records[i]
        if record.get("role") == "event" and record.get("event") == store.EVENT_CLEAR:
            return records[i + 1:]
    return records


def _apply_model(model, cfg: Dict[str, Any]) -> None:
    """The profile's own model, else the global default."""
    if cfg.get("model"):
        model.set_agent_default(cfg.get("provider") or None, cfg["model"])


def _check_id(value: str, what: str) -> None:
    if not isinstance(value, str) or not _ID_RE.match(value):
        raise GuestError(400, f"Invalid {what}.", f"invalid_{what.replace(' ', '_')}")


class GuestService:
    def __init__(self):
        self._lock = threading.RLock()
        self._sessions: Dict[Tuple[str, str], GuestSession] = {}
        self._turns: Dict[str, GuestTurn] = {}
        self._janitor_started = False

    # --- sessions ------------------------------------------------------------

    def work_dir(self, slug: str, session_id: str) -> str:
        _check_id(session_id, "session id")
        path = os.path.join(store.sessions_dir(slug), session_id)
        os.makedirs(os.path.join(path, "uploads"), exist_ok=True)
        return path

    def _session(self, slug: str, session_id: str) -> GuestSession:
        with self._lock:
            key = (slug, session_id)
            session = self._sessions.get(key)
            if session is None:
                session = GuestSession(slug=slug, session_id=session_id)
                session.turns = sum(1 for r in _since_clear(store.read_messages(slug, session_id, 5000))
                                    if r.get("role") == "user")
                self._sessions[key] = session
            session.last_active = time.time()
            return session

    def guard_for(self, state: ShareState, session_id: str) -> PathGuard:
        skills = _skill_entries(state)
        cfg = state.effective or {}
        return PathGuard.build(
            work_dir=self.work_dir(state.slug, session_id),
            references=cfg.get("references") or [],
            skill_dirs={s["name"]: s["dir"] for s in skills},
        )

    def _prepare_agent(self, state: ShareState, session: GuestSession) -> GuestAgent:
        skills = _skill_entries(state)
        fingerprint = _fingerprint(state, skills)
        if session.agent is not None and session.fingerprint == fingerprint:
            return session.agent

        from bridge.agent_bridge import AgentLLMModel
        from bridge.bridge import Bridge

        cfg = state.effective
        guard = self.guard_for(state, session.session_id)
        tools = build_guest_tools(cfg, guard)
        mounts = guard.describe()
        skill_list = [{
            "name": s["name"],
            "description": s["description"],
            "location": f"{guard.virtual_of(s['dir']) or '/skills/' + s['name']}/{s['file']}",
        } for s in skills]
        language = _prompt_language(cfg)
        is_en = language == "en"
        notices = [
            "You cannot run shell commands, scripts or code in this conversation."
            if is_en else "本对话中不能执行 shell 命令、脚本或代码。"
        ]
        model = AgentLLMModel(Bridge())
        _apply_model(model, cfg)
        model.channel_type = "guest"
        model.session_id = f"guest:{state.slug}:{session.session_id}"
        agent = GuestAgent(
            model=model,
            tools=tools,
            prompt_inputs={
                "name": cfg.get("name") or state.slug,
                "guest_md": state.profile.guest_md,
                "mounts": mounts,
                "skills": skill_list,
                "notices": notices,
                "language": language,
            },
            work_dir=guard.work_dir,
        )
        if session.agent is not None:
            agent.messages = list(session.agent.messages)
        else:
            agent.messages = self._restored_messages(state.slug, session.session_id)
        session.agent = agent
        session.guard = guard
        session.fingerprint = fingerprint
        return agent

    @staticmethod
    def _restored_messages(slug: str, session_id: str) -> List[Dict[str, Any]]:
        """The last few turns of a session from its transcript, text only, so
        a conversation survives a restart without replaying tool calls."""
        records = [r for r in _since_clear(store.read_messages(slug, session_id, 2000))
                   if r.get("role") in ("user", "assistant")]
        messages: List[Dict[str, Any]] = []
        for record in records:
            text = str(record.get("content") or "").strip()
            if not text:
                continue
            if messages and messages[-1]["role"] == record["role"]:
                messages[-1] = {"role": record["role"], "content": _text_blocks(text)}
            else:
                messages.append({"role": record["role"], "content": _text_blocks(text)})
        while messages and messages[0]["role"] != "user":
            messages.pop(0)
        if messages and messages[-1]["role"] == "user":
            messages.pop()
        return messages[-RESTORE_TURNS * 2:]

    # --- limits --------------------------------------------------------------

    def _check_limits(self, state: ShareState, session: GuestSession, visitor_id: str) -> None:
        limits = state.effective.get("limits") or {}
        now = time.time()
        while session.requests and now - session.requests[0] > 60:
            session.requests.popleft()
        if len(session.requests) >= int(limits.get("rpm") or 10):
            raise GuestError(429, "Too many messages, please wait a moment.", "rate_limited")
        if session.turns >= int(limits.get("max_turns") or 50):
            raise GuestError(429, "This conversation has reached its length limit. Start a new one.", "max_turns")
        daily = int(limits.get("daily_tokens") or 0)
        if daily and store.tokens_today(state.slug) >= daily:
            raise GuestError(429, "This page has reached today's usage limit. Please come back tomorrow.", "daily_quota")
        questions = int(limits.get("daily_messages") or 0)
        if questions and store.questions_today(state.slug, visitor_id) >= questions:
            raise GuestError(429, "You have reached today's question limit. Please come back tomorrow.",
                             "visitor_quota")
        running = sum(1 for t in self._turns.values() if t.slug == state.slug)
        if running >= MAX_CONCURRENT_RUNS_PER_PROFILE:
            raise GuestError(429, "The assistant is busy right now, please retry shortly.", "busy")

    # --- turns ---------------------------------------------------------------

    def begin(self, state: ShareState, visitor_id: str, session_id: str, text: str,
              attachments: Iterable[str] = ()) -> GuestTurn:
        """Check and reserve a turn, and record the visitor's message.
        ``attachments`` are virtual paths in the conversation's own files.
        Every turn begun must be passed to ``execute``."""
        if not state.active:
            raise GuestError(403, "This page is not available right now.", state.status)
        _check_id(visitor_id, "visitor id")
        _check_id(session_id, "session id")
        text = (text or "").strip()
        attachments = list(attachments or [])
        if not text and not attachments:
            raise GuestError(400, "Message is empty.")
        if len(text) > 20000:
            raise GuestError(400, "Message is too long.")
        self._ensure_janitor()
        with self._lock:
            session = self._session(state.slug, session_id)
            if session.busy:
                raise GuestError(409, "A reply is still in progress.", "busy")
            self._check_limits(state, session, visitor_id)
            agent = self._prepare_agent(state, session)
            guard = session.guard
            vpaths = []
            for path in attachments[:10]:
                try:
                    real = guard.resolve(path)
                except Exception:
                    continue
                if os.path.isfile(real):
                    vpaths.append(guard.virtual_of(real) or path)
            session.requests.append(time.time())
            session.turns += 1
            store.add_question(state.slug, visitor_id)
            message = text
            if vpaths:
                listing = "\n".join(f"- {p}" for p in vpaths)
                message = f"{text}\n\n[Uploaded files]\n{listing}".strip()
            turn = GuestTurn(
                id=uuid.uuid4().hex, state=state, visitor_id=visitor_id, session_id=session_id,
                message=message, agent=agent, guard=guard,
                timeout=int((state.effective.get("limits") or {}).get("run_timeout_seconds") or 300),
            )
            self._turns[turn.id] = turn
            session.turn = turn
        try:
            store.append_message(state.slug, session_id, {"role": "user", "content": text, "attachments": vpaths},
                                 visitor_id=visitor_id)
        except Exception:
            self._release(turn)
            raise
        return turn

    def execute(self, turn: GuestTurn, on_event: Optional[EventSink] = None) -> TurnResult:
        """Run a turn to the end, store the reply and return it. Blocks for
        as long as the Agent works; ``on_event`` sees its progress."""
        try:
            return self._execute(turn, on_event)
        finally:
            self._release(turn)

    def _release(self, turn: GuestTurn) -> None:
        with self._lock:
            turn.finished = True
            self._turns.pop(turn.id, None)
            session = self._sessions.get((turn.slug, turn.session_id))
            if session is not None:
                session.last_active = time.time()

    def run_turn(self, state: ShareState, visitor_id: str, session_id: str, text: str,
                 attachments: Iterable[str] = (), on_event: Optional[EventSink] = None) -> TurnResult:
        """``begin`` and ``execute`` in one call, for front ends that wait."""
        return self.execute(self.begin(state, visitor_id, session_id, text, attachments), on_event)

    def _execute(self, turn: GuestTurn, on_event: Optional[EventSink]) -> TurnResult:
        trace = _Trace()
        errors: List[str] = []
        timer = threading.Timer(turn.timeout, turn.cancel_event.set)
        timer.daemon = True
        timer.start()
        response = ""
        status = "done"
        try:
            response = turn.agent.run_stream(user_message=turn.message,
                                             on_event=self._tracker(turn, trace, errors, on_event),
                                             cancel_event=turn.cancel_event)
        except Exception as e:
            status = "failed"
            errors.append(str(e))
            logger.warning(f"[GuestShare] Run failed for {turn.slug}/{turn.session_id}: {e}")
        finally:
            timer.cancel()
        if turn.cancel_event.is_set() and status == "done":
            status = "cancelled"

        executor = getattr(turn.agent, "stream_executor", None)
        usage = getattr(executor, "run_usage", None) or {}
        tokens = int(usage.get("total_tokens") or 0)
        if not tokens:
            tokens = max(1, (len(turn.message) + len(response or "")) // 2)
        store.add_tokens(turn.slug, turn.visitor_id, tokens)

        reply = turn.guard.to_virtual(response or "")
        if status == "cancelled":
            # The stop marker is for the model's history; front ends show their own.
            reply = _CANCEL_MARKER_RE.sub("", reply).strip() or trace.text.strip()
        result = TurnResult(content=reply, status=status, files=trace.files, steps=trace.steps,
                            tokens=tokens, error=errors[0][:2000] if errors else "")
        record = {"role": "assistant", "content": reply, "steps": trace.steps, "files": trace.files,
                  "tokens": tokens, "status": status}
        if result.error:
            record["error"] = result.error
        store.append_message(turn.slug, turn.session_id, record, visitor_id=turn.visitor_id)
        return result

    def _tracker(self, turn: GuestTurn, trace: "_Trace", errors: List[str],
                 on_event: Optional[EventSink]) -> EventSink:
        """Agent events -> the turn's trace and plain progress events, the
        shape the console's stream uses. Reasoning is not passed on, and every
        path in tool arguments and results is turned into its virtual form."""
        guard = turn.guard

        def emit(event: Dict[str, Any]) -> None:
            if on_event is None:
                return
            try:
                on_event(event)
            except Exception as e:
                logger.warning(f"[GuestShare] Event handler failed: {e}")

        def virtual(value: Any) -> Any:
            if isinstance(value, str):
                return guard.to_virtual(value)
            if isinstance(value, dict):
                return {k: virtual(v) for k, v in value.items()}
            if isinstance(value, list):
                return [virtual(v) for v in value]
            return value

        def as_text(value: Any) -> str:
            if isinstance(value, (dict, list)):
                return json.dumps(value, ensure_ascii=False)
            return "" if value is None else str(value)

        def add_file(raw_path: str, file_type: str, file_name: Optional[str] = None) -> None:
            """A file the visitor may download: sent with ``send``, or written
            under /work this turn."""
            if not raw_path:
                return
            try:
                real = guard.resolve(raw_path)
            except Exception:
                return
            vpath = guard.virtual_of(real) or ""
            if not os.path.isfile(real) or not vpath.startswith("/"):
                return
            if any(f["path"] == vpath for f in trace.files):
                return
            if file_type == "file" and (mimetypes.guess_type(real)[0] or "").startswith("image/"):
                file_type = "image"
            item = {"file_name": file_name or os.path.basename(real), "path": vpath,
                    "file_type": file_type, "size": os.path.getsize(real)}
            trace.files.append(item)
            emit(dict(item, type="file"))

        def on_agent_event(event: Dict[str, Any]) -> None:
            kind = event.get("type")
            data = event.get("data") or {}
            if kind == "message_update":
                delta = data.get("delta") or ""
                if delta:
                    trace.text += delta
                    emit({"type": "delta", "content": delta})
            elif kind == "message_end":
                if data.get("tool_calls"):
                    text = virtual(trace.text.strip())
                    if text:
                        trace.steps.append({"type": "content", "content": text})
                    trace.text = ""
                    emit({"type": "message_end", "has_tool_calls": True})
            elif kind == "tool_execution_start":
                trace.text = ""
                arguments = virtual(data.get("arguments") or {})
                trace.arguments[data.get("tool_call_id")] = arguments
                emit({
                    "type": "tool_start",
                    "tool_call_id": data.get("tool_call_id"),
                    "tool": data.get("tool_name") or "tool",
                    "arguments": arguments,
                })
            elif kind == "tool_execution_end":
                name = data.get("tool_name") or "tool"
                arguments = trace.arguments.pop(data.get("tool_call_id"), {})
                result = virtual(as_text(data.get("result")))
                if len(result) > MAX_TOOL_RESULT_CHARS:
                    result = result[:MAX_TOOL_RESULT_CHARS] + "…"
                ok = data.get("status") == "success"
                exec_time = round(float(data.get("execution_time") or 0), 2)
                trace.steps.append({
                    "type": "tool",
                    "name": name,
                    "arguments": arguments,
                    "result": result,
                    "is_error": not ok,
                    "execution_time": exec_time,
                })
                emit({
                    "type": "tool_end",
                    "tool_call_id": data.get("tool_call_id"),
                    "tool": name,
                    "status": "success" if ok else "error",
                    "result": result,
                    "execution_time": exec_time,
                })
                if ok and name in ("write", "edit"):
                    add_file(str((arguments or {}).get("path") or ""), "file")
            elif kind == "file_to_send":
                add_file(str(data.get("path") or ""), data.get("file_type") or "file", data.get("file_name"))
            elif kind == "error":
                errors.append(str(data.get("error") or "error"))

        return on_agent_event

    def active_turn(self, slug: str, session_id: str) -> Optional[str]:
        with self._lock:
            session = self._sessions.get((slug, session_id))
            return session.turn.id if session is not None and session.busy else None

    def cancel(self, slug: str, session_id: str) -> bool:
        with self._lock:
            session = self._sessions.get((slug, session_id))
            if session is None or not session.busy:
                return False
            session.turn.cancel_event.set()
            return True

    def clear_context(self, state: ShareState, visitor_id: str, session_id: str) -> None:
        """Start the model afresh; the transcript keeps what came before."""
        _check_id(session_id, "session id")
        with self._lock:
            session = self._session(state.slug, session_id)
            if session.busy:
                raise GuestError(409, "A reply is still in progress.", "busy")
            store.append_message(state.slug, session_id, {"role": "event", "event": store.EVENT_CLEAR},
                                 visitor_id=visitor_id)
            session.turns = 0
            if session.agent is not None:
                session.agent.messages = []

    def delete_session(self, state: ShareState, session_id: str) -> None:
        """Hide a conversation from its visitor and drop its files. The
        transcript stays for the owner, marked as deleted."""
        _check_id(session_id, "session id")
        with self._lock:
            session = self._sessions.pop((state.slug, session_id), None)
            if session is not None and session.busy:
                session.turn.cancel_event.set()
        store.mark_deleted(state.slug, session_id)
        shutil.rmtree(os.path.join(store.sessions_dir(state.slug), session_id), ignore_errors=True)

    # --- files ---------------------------------------------------------------

    def save_upload(self, state: ShareState, session_id: str, name: str, content: bytes) -> str:
        """Keep a file the visitor sent under /work/uploads and return its
        virtual path, which ``begin`` then takes as an attachment."""
        limits = (state.effective or {}).get("limits") or {}
        if len(content) > int(limits.get("max_upload_mb") or 20) * 1024 * 1024:
            raise GuestError(413, "File is too large.", "too_large")
        guard = self.guard_for(state, session_id)
        if guard.work_usage_bytes() + len(content) > int(limits.get("max_work_mb") or 200) * 1024 * 1024:
            raise GuestError(413, "This conversation's storage is full.", "storage_full")
        name = _SAFE_NAME_RE.sub("_", os.path.basename(str(name or "").replace("\\", "/"))).strip(" .") or "file"
        name = name[-120:]
        uploads = os.path.join(guard.work_dir, "uploads")
        os.makedirs(uploads, exist_ok=True)
        stem, ext = os.path.splitext(name)
        target, n = os.path.join(uploads, name), 1
        while os.path.exists(target):
            target = os.path.join(uploads, f"{stem}_{n}{ext}")
            n += 1
        with open(target, "wb") as f:
            f.write(content)
        return guard.virtual_of(target)

    def local_file(self, state: ShareState, session_id: str, vpath: str) -> Optional[str]:
        """Where a file the conversation may see is on disk, or None."""
        try:
            real = self.guard_for(state, session_id).resolve(vpath)
        except GuestPathError:
            return None
        return real if os.path.isfile(real) else None

    # --- housekeeping --------------------------------------------------------

    def forget_profile(self, slug: str) -> None:
        """Drop live state for a profile whose link or password changed."""
        with self._lock:
            for key in [k for k in self._sessions if k[0] == slug]:
                session = self._sessions.pop(key)
                if session.busy:
                    session.turn.cancel_event.set()

    def _ensure_janitor(self) -> None:
        with self._lock:
            if self._janitor_started:
                return
            self._janitor_started = True
        threading.Thread(target=self._janitor, name="guest-janitor", daemon=True).start()

    def _janitor(self) -> None:
        while True:
            time.sleep(300)
            try:
                self.sweep()
            except Exception as e:
                logger.warning(f"[GuestShare] Sweep failed: {e}")

    def sweep(self, now: Optional[float] = None) -> None:
        now = now or time.time()
        with self._lock:
            for key, session in list(self._sessions.items()):
                if not session.busy and now - session.last_active > AGENT_IDLE_SECONDS:
                    del self._sessions[key]
        self._sweep_work_dirs(now)

    def _sweep_work_dirs(self, now: float) -> None:
        from agent.guest.share import resolve

        root = os.path.join(store.data_dir(), "sessions")
        try:
            slugs = os.listdir(root)
        except OSError:
            return
        for slug in slugs:
            state = resolve(slug)
            ttl = state.session_ttl() if state else 0
            base = os.path.join(root, slug)
            try:
                names = os.listdir(base)
            except OSError:
                continue
            for name in names:
                path = os.path.join(base, name)
                with self._lock:
                    live = (slug, name) in self._sessions
                if live:
                    continue
                # The directory's mtime only moves when an entry is added or
                # removed; the conversation's own activity covers the rest.
                stamps = [store.last_activity(slug, name) or 0]
                try:
                    stamps.append(os.stat(path).st_mtime)
                except OSError:
                    pass
                if now - max(stamps) > ttl:
                    shutil.rmtree(path, ignore_errors=True)


_service: Optional[GuestService] = None
_service_lock = threading.Lock()


def get_service() -> GuestService:
    global _service
    with _service_lock:
        if _service is None:
            _service = GuestService()
        return _service
