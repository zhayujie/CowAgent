"""Running visitor conversations.

Deliberately not routed through ``AgentBridge.agent_reply``. That path serves
the owner: it resolves the owner's Agent, restores the owner's transcript,
writes to the owner's conversation store, wires the scheduler, delegation and
self-evolution, and builds the prompt from the owner's workspace. A visitor
needs none of it, and every one of those is a way to leak or to poison. The
guest path builds its own Agent from explicit inputs, keeps its transcript in
the guest share store, and shares only the model adapter with the owner.
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
from typing import Any, Callable, Deque, Dict, Iterator, List, Optional, Tuple
from urllib.parse import quote

from agent.guest import policy, store
from agent.guest.paths import PathGuard
from agent.guest.share import ShareState
from agent.guest.tools import build_guest_tools
from agent.protocol.agent import Agent
from agent.tools.base_tool import is_tool_available
from common.log import logger

MAX_RUN_EVENTS = 4000
RUN_RETENTION_SECONDS = 15 * 60
AGENT_IDLE_SECONDS = 60 * 60
RESTORE_TURNS = 10
MAX_CONCURRENT_RUNS_PER_PROFILE = 4
FILE_LINK_TTL = 24 * 3600
# Same budget the console's stream gives a tool result.
MAX_TOOL_RESULT_CHARS = 2000
_CANCEL_MARKER_RE = re.compile(r"_\(Cancelled(?: by user)?\)_")
_VPATH_RE = re.compile(r"/(?:work|data|skills)/[^\s)\"'<>\]`*]+")


class GuestError(Exception):
    """A request the guest endpoints refuse. ``code`` is the HTTP status."""

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
        from common import i18n

        try:
            language = i18n.get_language()
        except Exception:
            language = "zh"
        return build_guest_system_prompt(
            tools=[t for t in self.tools if is_tool_available(t)],
            language=language,
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
class GuestRun:
    request_id: str
    slug: str
    session_id: str
    cancel_event: threading.Event = field(default_factory=threading.Event)
    events: List[Dict[str, Any]] = field(default_factory=list)
    cond: threading.Condition = field(default_factory=threading.Condition)
    finished: bool = False
    finished_at: float = 0.0

    def publish(self, event: Dict[str, Any]) -> None:
        with self.cond:
            if len(self.events) >= MAX_RUN_EVENTS and event.get("type") == "delta":
                return
            event = dict(event, seq=len(self.events) + 1)
            self.events.append(event)
            if event.get("type") == "stream_end":
                self.finished = True
                self.finished_at = time.time()
            self.cond.notify_all()


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
    active_run: Optional[str] = None
    requests: Deque[float] = field(default_factory=deque)


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


class GuestService:
    def __init__(self):
        self._lock = threading.RLock()
        self._sessions: Dict[Tuple[str, str], GuestSession] = {}
        self._runs: Dict[str, GuestRun] = {}
        self._ip_hits: Dict[str, Deque[float]] = {}
        self._janitor_started = False

    # --- sessions ------------------------------------------------------------

    def work_dir(self, slug: str, session_id: str) -> str:
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
        from common import i18n

        cfg = state.effective
        guard = self.guard_for(state, session.session_id)
        tools = build_guest_tools(cfg, guard)
        mounts = guard.describe()
        skill_list = [{
            "name": s["name"],
            "description": s["description"],
            "location": f"{guard.virtual_of(s['dir']) or '/skills/' + s['name']}/{s['file']}",
        } for s in skills]
        is_en = i18n.get_language() == "en"
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

    def allow_ip(self, ip: str, limit: int, window: float = 60.0) -> bool:
        now = time.time()
        with self._lock:
            hits = self._ip_hits.setdefault(ip, deque())
            while hits and now - hits[0] > window:
                hits.popleft()
            if len(hits) >= limit:
                return False
            hits.append(now)
            return True

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
        running = sum(1 for r in self._runs.values() if r.slug == state.slug and not r.finished)
        if running >= MAX_CONCURRENT_RUNS_PER_PROFILE:
            raise GuestError(429, "The assistant is busy right now, please retry shortly.", "busy")

    # --- runs ----------------------------------------------------------------

    def start(self, state: ShareState, visitor_id: str, session_id: str, text: str,
              attachments: List[str]) -> str:
        text = (text or "").strip()
        if not text and not attachments:
            raise GuestError(400, "Message is empty.")
        if len(text) > 20000:
            raise GuestError(400, "Message is too long.")
        self._ensure_janitor()
        with self._lock:
            session = self._session(state.slug, session_id)
            current = self._runs.get(session.active_run or "")
            if current is not None and not current.finished:
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
            run = GuestRun(request_id=uuid.uuid4().hex, slug=state.slug, session_id=session_id)
            self._runs[run.request_id] = run
            session.active_run = run.request_id

        message = text
        if vpaths:
            listing = "\n".join(f"- {p}" for p in vpaths)
            message = f"{text}\n\n[Uploaded files]\n{listing}".strip()
        store.append_message(state.slug, session_id, {"role": "user", "content": text, "attachments": vpaths})
        timeout = int((state.effective.get("limits") or {}).get("run_timeout_seconds") or 300)
        thread = threading.Thread(
            target=self._run, args=(state, session, agent, run, message, timeout),
            name=f"guest-run-{state.slug}", daemon=True,
        )
        thread.start()
        return run.request_id

    def _run(self, state: ShareState, session: GuestSession, agent: GuestAgent,
             run: GuestRun, message: str, timeout: int) -> None:
        trace = _Trace()
        errors: List[str] = []
        on_event = self._translator(state, session, run, trace, errors)
        timer = threading.Timer(timeout, run.cancel_event.set)
        timer.daemon = True
        timer.start()
        response = ""
        status = "done"
        try:
            response = agent.run_stream(user_message=message, on_event=on_event, cancel_event=run.cancel_event)
        except Exception as e:
            status = "failed"
            errors.append(str(e))
            logger.warning(f"[GuestShare] Run failed for {state.slug}/{session.session_id}: {e}")
        finally:
            timer.cancel()
        if run.cancel_event.is_set() and status == "done":
            status = "cancelled"

        tokens = 0
        executor = getattr(agent, "stream_executor", None)
        usage = getattr(executor, "run_usage", None) or {}
        tokens = int(usage.get("total_tokens") or 0)
        if not tokens:
            tokens = max(1, (len(message) + len(response or "")) // 2)
        store.add_tokens(state.slug, store.visitor_of(session.session_id), tokens)

        guard = session.guard
        reply = guard.to_virtual(response or "") if guard else (response or "")
        if status == "cancelled":
            # The stop marker is for the model's history; the page has its own.
            reply = _CANCEL_MARKER_RE.sub("", reply).strip() or trace.text.strip()
        record = {"role": "assistant", "content": reply, "steps": trace.steps, "files": trace.files,
                  "tokens": tokens, "status": status}
        if errors:
            record["error"] = errors[0][:2000]
        store.append_message(state.slug, session.session_id, record)

        if status == "cancelled":
            run.publish({"type": "cancelled"})
        if status == "failed" or (errors and not reply.strip()):
            run.publish({"type": "error", "reason": "run_failed"})
        else:
            links = self._links(state, session.session_id, guard, [reply] + [
                s.get("content") or "" for s in trace.steps if s.get("type") == "content"
            ])
            run.publish({"type": "done", "content": reply, "status": status, "links": links,
                         "timestamp": time.time()})
        run.publish({"type": "stream_end"})
        session.last_active = time.time()

    def _links(self, state: ShareState, session_id: str, guard: Optional[PathGuard],
               texts: List[str]) -> Dict[str, str]:
        """Signed URLs for the visitor-visible files a reply mentions, so an
        inline ``![chart](/work/chart.png)`` or a link to a file renders."""
        if guard is None:
            return {}
        links: Dict[str, str] = {}
        for text in texts:
            for match in _VPATH_RE.finditer(text or ""):
                vpath = match.group(0).rstrip(".,;:!?")
                if vpath in links or len(links) >= 50:
                    continue
                try:
                    real = guard.resolve(vpath)
                except Exception:
                    continue
                if os.path.isfile(real):
                    links[vpath] = self.file_url(state.share_token, state.slug, session_id, vpath)
        return links

    def active_request(self, slug: str, session_id: str) -> Optional[str]:
        with self._lock:
            session = self._sessions.get((slug, session_id))
            run = self._runs.get(session.active_run or "") if session else None
            return run.request_id if run is not None and not run.finished else None

    def file_url(self, share_token: str, slug: str, session_id: str, vpath: str) -> str:
        expires = int(time.time()) + FILE_LINK_TTL
        sig = store.sign_file(slug, session_id, vpath, expires)
        return (f"/share/{share_token}/api/file?sid={session_id}&path={quote(vpath)}"
                f"&exp={expires}&sig={sig}")

    def _translator(self, state: ShareState, session: GuestSession, run: GuestRun,
                    trace: "_Trace", errors: List[str]) -> Callable[[Dict[str, Any]], None]:
        """Agent events -> the console's stream events, so the guest page renders
        a reply the way the console does. Reasoning is not forwarded, and every
        path in tool arguments and results is turned into its virtual form."""
        guard = session.guard

        def virtual(value: Any) -> Any:
            if isinstance(value, str):
                return guard.to_virtual(value) if guard else value
            if isinstance(value, dict):
                return {k: virtual(v) for k, v in value.items()}
            if isinstance(value, list):
                return [virtual(v) for v in value]
            return value

        def as_text(value: Any) -> str:
            if isinstance(value, (dict, list)):
                return json.dumps(value, ensure_ascii=False)
            return "" if value is None else str(value)

        def publish_file(raw_path: str, file_type: str, file_name: Optional[str] = None) -> None:
            """A file card for a file the visitor may download: sent with
            ``send``, or written under /work this turn."""
            if guard is None or not raw_path:
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
            run.publish(dict(item, type="file",
                             url=self.file_url(state.share_token, state.slug, session.session_id, vpath)))

        def on_event(event: Dict[str, Any]) -> None:
            kind = event.get("type")
            data = event.get("data") or {}
            if kind == "message_update":
                delta = data.get("delta") or ""
                if delta:
                    trace.text += delta
                    run.publish({"type": "delta", "content": delta})
            elif kind == "message_end":
                if data.get("tool_calls"):
                    text = virtual(trace.text.strip())
                    if text:
                        trace.steps.append({"type": "content", "content": text})
                    trace.text = ""
                    run.publish({"type": "message_end", "has_tool_calls": True})
            elif kind == "tool_execution_start":
                trace.text = ""
                arguments = virtual(data.get("arguments") or {})
                trace.arguments[data.get("tool_call_id")] = arguments
                run.publish({
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
                run.publish({
                    "type": "tool_end",
                    "tool_call_id": data.get("tool_call_id"),
                    "tool": name,
                    "status": "success" if ok else "error",
                    "result": result,
                    "execution_time": exec_time,
                })
                if ok and name in ("write", "edit"):
                    publish_file(str((arguments or {}).get("path") or ""), "file")
            elif kind == "file_to_send":
                publish_file(str(data.get("path") or ""), data.get("file_type") or "file",
                             data.get("file_name"))
            elif kind == "error":
                errors.append(str(data.get("error") or "error"))

        return on_event

    def get_run(self, request_id: str, slug: str, session_id: str) -> Optional[GuestRun]:
        run = self._runs.get(request_id)
        if run is None or run.slug != slug or run.session_id != session_id:
            return None
        return run

    def stream(self, run: GuestRun, after: int = 0, idle_timeout: float = 600) -> Iterator[bytes]:
        cursor = max(0, int(after or 0))
        deadline = time.time() + idle_timeout
        while time.time() < deadline:
            with run.cond:
                pending = run.events[cursor:]
                if not pending and not run.finished:
                    run.cond.wait(timeout=15)
                    pending = run.events[cursor:]
            if not pending:
                if run.finished:
                    return
                yield b": keepalive\n\n"
                continue
            for event in pending:
                cursor = event["seq"]
                deadline = time.time() + idle_timeout
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n".encode("utf-8")
                if event.get("type") == "stream_end":
                    return

    def cancel(self, slug: str, session_id: str) -> bool:
        with self._lock:
            session = self._sessions.get((slug, session_id))
            if not session or not session.active_run:
                return False
            run = self._runs.get(session.active_run)
        if run is None or run.finished:
            return False
        run.cancel_event.set()
        return True

    def clear_context(self, state: ShareState, session_id: str) -> None:
        """Start the model afresh; the page keeps showing what came before."""
        with self._lock:
            session = self._session(state.slug, session_id)
            current = self._runs.get(session.active_run or "")
            if current is not None and not current.finished:
                raise GuestError(409, "A reply is still in progress.", "busy")
            store.append_message(state.slug, session_id, {"role": "event", "event": store.EVENT_CLEAR})
            session.turns = 0
            if session.agent is not None:
                session.agent.messages = []

    def delete_session(self, state: ShareState, session_id: str) -> None:
        """Hide a conversation from its visitor and drop its files. The
        transcript stays for the owner, marked as deleted."""
        with self._lock:
            session = self._sessions.pop((state.slug, session_id), None)
            if session and session.active_run in self._runs:
                self._runs[session.active_run].cancel_event.set()
        store.mark_deleted(state.slug, session_id)
        shutil.rmtree(os.path.join(store.sessions_dir(state.slug), session_id), ignore_errors=True)

    def history(self, state: ShareState, session_id: str) -> Dict[str, Any]:
        """The transcript in the shape the page renders, with fresh file links."""
        guard = self.guard_for(state, session_id)

        def link(vpath: str) -> str:
            return self.file_url(state.share_token, state.slug, session_id, vpath)

        messages = []
        texts: List[str] = []
        for record in store.read_messages(state.slug, session_id):
            role = record.get("role")
            if role == "event" and record.get("event") == store.EVENT_CLEAR:
                messages.append({"role": "event", "event": store.EVENT_CLEAR, "ts": record.get("ts")})
                continue
            if role not in ("user", "assistant"):
                continue
            item = {"role": role, "content": record.get("content") or "", "ts": record.get("ts")}
            if role == "assistant":
                item["steps"] = record.get("steps") or []
                item["status"] = record.get("status") or "done"
                item["files"] = [
                    dict(f, file_name=f.get("file_name") or f.get("name") or os.path.basename(f["path"]),
                         url=link(f["path"]))
                    for f in record.get("files") or [] if str(f.get("path") or "").startswith("/")
                ]
                texts.append(item["content"])
                texts.extend(s.get("content") or "" for s in item["steps"] if s.get("type") == "content")
            else:
                attachments = []
                for vpath in record.get("attachments") or []:
                    is_image = (mimetypes.guess_type(vpath)[0] or "").startswith("image/")
                    attachments.append({"file_name": os.path.basename(vpath),
                                        "file_type": "image" if is_image else "file",
                                        "url": link(vpath)})
                item["attachments"] = attachments
            messages.append(item)
        return {
            "messages": messages,
            "links": self._links(state, session_id, guard, texts),
            "active_request_id": self.active_request(state.slug, session_id),
        }

    # --- housekeeping --------------------------------------------------------

    def forget_profile(self, slug: str) -> None:
        """Drop live state for a profile whose link or password changed."""
        with self._lock:
            for key in [k for k in self._sessions if k[0] == slug]:
                session = self._sessions.pop(key)
                if session.active_run and session.active_run in self._runs:
                    self._runs[session.active_run].cancel_event.set()

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
            for request_id, run in list(self._runs.items()):
                if run.finished and now - run.finished_at > RUN_RETENTION_SECONDS:
                    del self._runs[request_id]
            for key, session in list(self._sessions.items()):
                running = session.active_run in self._runs and not self._runs[session.active_run].finished
                if not running and now - session.last_active > AGENT_IDLE_SECONDS:
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
