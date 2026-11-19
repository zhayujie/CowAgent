"""The guest pages' side of a visitor turn.

``agent.guest.runtime`` runs the turn; this module makes it fit a browser: the
turn runs in a thread while its events are buffered for the page's event
stream (so a reload can pick the stream up again), files become signed links
under ``/share/<token>``, and the transcript is shaped the way the page
renders it.
"""

from __future__ import annotations

import json
import mimetypes
import os
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, Iterable, Iterator, List, Optional
from urllib.parse import quote

from agent.guest import store
from agent.guest.paths import MENTION_RE, PathGuard
from agent.guest.runtime import GuestTurn, get_service
from agent.guest.share import ShareState
from common.log import logger

MAX_RUN_EVENTS = 4000
RUN_RETENTION_SECONDS = 15 * 60
FILE_LINK_TTL = 24 * 3600


@dataclass
class GuestRun:
    request_id: str
    slug: str
    session_id: str
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


def file_url(share_token: str, slug: str, session_id: str, vpath: str) -> str:
    expires = int(time.time()) + FILE_LINK_TTL
    sig = store.sign_file(slug, session_id, vpath, expires)
    return (f"/share/{share_token}/api/file?sid={session_id}&path={quote(vpath)}"
            f"&exp={expires}&sig={sig}")


def links(state: ShareState, session_id: str, guard: PathGuard, texts: Iterable[str]) -> Dict[str, str]:
    """Signed URLs for the visitor-visible files a reply mentions, so an
    inline ``![chart](/work/chart.png)`` or a link to a file renders."""
    out: Dict[str, str] = {}
    for text in texts:
        for match in MENTION_RE.finditer(text or ""):
            vpath = match.group(0).rstrip(".,;:!?")
            if vpath in out or len(out) >= 50:
                continue
            try:
                real = guard.resolve(vpath)
            except Exception:
                continue
            if os.path.isfile(real):
                out[vpath] = file_url(state.share_token, state.slug, session_id, vpath)
    return out


def _reply_texts(content: str, steps: List[Dict[str, Any]]) -> List[str]:
    return [content] + [s.get("content") or "" for s in steps if s.get("type") == "content"]


class GuestPages:
    def __init__(self):
        self._lock = threading.Lock()
        self._runs: Dict[str, GuestRun] = {}
        self._ip_hits: Dict[str, Deque[float]] = {}

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

    def start(self, state: ShareState, visitor_id: str, session_id: str, text: str,
              attachments: List[str]) -> str:
        turn = get_service().begin(state, visitor_id, session_id, text, attachments)
        run = GuestRun(request_id=turn.id, slug=state.slug, session_id=session_id)
        now = time.time()
        with self._lock:
            for request_id, old in list(self._runs.items()):
                if old.finished and now - old.finished_at > RUN_RETENTION_SECONDS:
                    del self._runs[request_id]
            self._runs[run.request_id] = run
        threading.Thread(target=self._run, args=(state, turn, run),
                         name=f"guest-run-{state.slug}", daemon=True).start()
        return run.request_id

    def _run(self, state: ShareState, turn: GuestTurn, run: GuestRun) -> None:
        def publish(event: Dict[str, Any]) -> None:
            if event.get("type") == "file":
                event = dict(event, url=file_url(state.share_token, state.slug, turn.session_id, event["path"]))
            run.publish(event)

        try:
            result = get_service().execute(turn, publish)
            if result.status == "cancelled":
                run.publish({"type": "cancelled"})
            if result.failed:
                run.publish({"type": "error", "reason": "run_failed"})
            else:
                run.publish({
                    "type": "done", "content": result.content, "status": result.status,
                    "links": links(state, turn.session_id, turn.guard, _reply_texts(result.content, result.steps)),
                    "timestamp": time.time(),
                })
        except Exception as e:
            logger.warning(f"[GuestShare] Turn failed for {state.slug}/{turn.session_id}: {e}")
            run.publish({"type": "error", "reason": "run_failed"})
        finally:
            run.publish({"type": "stream_end"})

    def get_run(self, request_id: str, slug: str, session_id: str) -> Optional[GuestRun]:
        run = self._runs.get(request_id)
        if run is None or run.slug != slug or run.session_id != session_id:
            return None
        return run

    @staticmethod
    def stream(run: GuestRun, after: int = 0, idle_timeout: float = 600) -> Iterator[bytes]:
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

    @staticmethod
    def history(state: ShareState, session_id: str) -> Dict[str, Any]:
        """The transcript in the shape the page renders, with fresh file links."""
        service = get_service()
        guard = service.guard_for(state, session_id)

        def link(vpath: str) -> str:
            return file_url(state.share_token, state.slug, session_id, vpath)

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
                texts.extend(_reply_texts(item["content"], item["steps"]))
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
            "links": links(state, session_id, guard, texts),
            "active_request_id": service.active_turn(state.slug, session_id),
        }


_pages: Optional[GuestPages] = None
_pages_lock = threading.Lock()


def get_pages() -> GuestPages:
    global _pages
    with _pages_lock:
        if _pages is None:
            _pages = GuestPages()
        return _pages
