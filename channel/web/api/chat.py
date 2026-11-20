"""Sending a message and following the reply: /api/message and the stream.

Thin by design. The work happens in WebChannel, which owns the queues and
the SSE state; these routes hand a request to it and stream back what it
produces.
"""

import web

from channel.web.core._common import _require_auth
from channel.web.core.channel import WebChannel


def _parse_sse_cursor(*values) -> int:
    cursors = []
    for value in values:
        try:
            cursors.append(max(0, int(value or 0)))
        except (TypeError, ValueError):
            cursors.append(0)
    return max(cursors, default=0)


class MessageHandler:
    def POST(self):
        _require_auth()
        return WebChannel().post_message()


class PollHandler:
    def POST(self):
        _require_auth()
        return WebChannel().poll_response()


class CancelHandler:
    def POST(self):
        _require_auth()
        return WebChannel().cancel_request()


class StreamHandler:
    def GET(self):
        _require_auth()
        params = web.input(request_id='', after_seq='')
        request_id = params.request_id
        if not request_id:
            raise web.badrequest()

        # Explicit query cursors are used by the frontend's manually-created
        # EventSource. Native EventSource reconnects remain compatible via the
        # standard Last-Event-ID request header.
        after_seq = _parse_sse_cursor(
            params.after_seq,
            web.ctx.env.get('HTTP_LAST_EVENT_ID', '0'),
        )

        web.header('Content-Type', 'text/event-stream; charset=utf-8')
        web.header('Cache-Control', 'no-cache')
        web.header('X-Accel-Buffering', 'no')

        return WebChannel().stream_response(request_id, after_seq)
