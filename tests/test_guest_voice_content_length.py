"""The guest voice endpoint must reject oversized bodies before parsing.

GuestUploadHandler checks CONTENT_LENGTH before multipart parsing, so a
declared-too-large upload is refused without reading it. The voice handler
had no such pre-check: multipart.parse_form_data spills parts over its
in-memory cap into disk-backed temp files, so a guest token (free via
POST /share/<token>/api/session) could make every request spend a large
temp file and full parse time before _read_uploaded_file_bytes_limited
rejected the bytes. These tests pin the same pre-check on the voice route.
"""
import os
import sys
import types
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import channel.web.api.guest as guest_api
from channel.web.api.guest import GuestVoiceHandler

MAX_BYTES = GuestVoiceHandler.MAX_BYTES


def _parse_must_not_run(*args, **kwargs):
    raise AssertionError("multipart parsing ran before the size pre-check")


class _FailSignal(guest_api.web.HTTPError):
    """Stand-in for _fail's HTTPError: the real constructor needs a live
    request context. Subclassing keeps the handler's ``except web.HTTPError:
    raise`` path intact so the marker surfaces unchanged."""

    def __init__(self, code, message, reason=""):
        self.code, self.message = code, message
        Exception.__init__(self, f"fail:{code}:{message}")


def _fail_marker(code, message, reason=""):
    raise _FailSignal(code, message, reason)


class _Pages:
    def allow_ip(self, key, limit, window=60.0):
        return True


class TestGuestVoiceContentLengthPrecheck(unittest.TestCase):

    def _post(self, content_length, parse_result=None):
        ctx = types.SimpleNamespace(env={"CONTENT_LENGTH": content_length})
        parse = _parse_must_not_run if parse_result is None else (lambda *a, **k: parse_result)
        with patch.object(guest_api, "_load_share", lambda token: object()), \
                patch.object(guest_api, "_visitor", lambda state: "v"), \
                patch.object(guest_api, "_asr_available", lambda: True), \
                patch.object(guest_api, "get_pages", lambda: _Pages()), \
                patch.object(guest_api, "_client_ip", lambda: "1.2.3.4"), \
                patch.object(guest_api.web, "ctx", ctx), \
                patch.object(guest_api, "_fail", _fail_marker), \
                patch.object(guest_api, "_multipart_lists", parse), \
                patch.object(guest_api, "_first_value", lambda params, name: None):
            with self.assertRaises(_FailSignal) as caught:
                GuestVoiceHandler().POST("token")
        return str(caught.exception)

    def test_oversized_declared_body_is_refused_without_parsing(self):
        message = self._post(str(MAX_BYTES + 1024 * 1024))
        self.assertIn("fail:413", message)

    def test_oversized_by_a_little_is_also_refused(self):
        message = self._post(str(MAX_BYTES + 65 * 1024))
        self.assertIn("fail:413", message)

    def test_a_normal_declared_body_reaches_the_parser(self):
        # Below the ceiling the flow passes the pre-check and reaches the
        # parser, which returns no file — the handler's own "no audio" 400.
        message = self._post("1024", parse_result={})
        self.assertIn("fail:400", message)
        self.assertIn("No audio", message)


if __name__ == "__main__":
    unittest.main()
