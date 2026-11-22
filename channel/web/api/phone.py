"""The mobile app's side of the phone tools: /api/phone/*.

The app that hosts this kernel long-polls for the requests phone tools make
and answers each one once it has run. Only that app may: these routes exist
on the mobile build alone, and answer requests from this device only, so a
browser or another device paired with this phone can neither take a request
nor fake an answer.
"""

import json

import web

from agent.tools.phone.bridge import POLL_WAIT_MAX, bridge
from channel.web.core._common import _is_loopback_request, _require_auth
from common.deployment import is_mobile


def _json(payload: dict) -> str:
    web.header("Content-Type", "application/json; charset=utf-8")
    return json.dumps(payload, ensure_ascii=False)


def _guard() -> dict:
    if not is_mobile() or not _is_loopback_request():
        raise web.notfound()
    _require_auth()
    try:
        body = json.loads(web.data() or b"{}")
    except ValueError:
        raise web.badrequest()
    if not isinstance(body, dict):
        raise web.badrequest()
    return body


class PhonePollHandler:
    def POST(self):
        body = _guard()
        listed = body.get("capabilities")
        capabilities = [c for c in listed if isinstance(c, str)] if isinstance(listed, list) else []
        try:
            wait = float(body.get("wait", POLL_WAIT_MAX))
        except (TypeError, ValueError):
            wait = POLL_WAIT_MAX
        requests, cancelled = bridge.poll(capabilities, wait)
        return _json({"status": "success", "requests": requests, "cancelled": cancelled})


class PhoneAnswerHandler:
    def POST(self, rid):
        body = _guard()
        answer = {"ok": bool(body.get("ok"))}
        if answer["ok"]:
            answer["result"] = body.get("result")
        else:
            answer["error"] = str(body.get("error") or "failed")[:64]
            answer["message"] = str(body.get("message") or "")[:500]
        return _json({"status": "success", "delivered": bridge.answer(rid, answer)})


PHONE_URLS = (
    '/api/phone/poll', 'PhonePollHandler',
    '/api/phone/requests/(r_[0-9a-f]+)', 'PhoneAnswerHandler',
)
