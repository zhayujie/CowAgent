"""The expired-QR refresh must not wipe the live login session.

``WeixinQrHandler._poll_status`` (channel/web/api/channels.py:1012) reacts to an
``expired`` status by fetching a fresh QR code. The first fetch in ``GET``
(line 937) refuses an empty answer and keeps the session intact; the refresh in
the expired branch has no such guard, so an upstream answer without a
``qrcode`` field -- ``{}``, ``{"qrcode": ""}`` or ``{"qrcode": null}`` -- is
written straight into ``WeixinQrHandler._qr_state``. ``_qr_to_data_uri("")``
still renders a valid (blank) PNG, so the console answers ``success`` with a
blank QR image and the next poll finds no code at all: the login session is
silently destroyed and the user has to start over.
"""

import json
import unittest
from unittest.mock import patch

import web

from channel.web.api.channels import WeixinQrHandler

LIVE_STATE = {
    "qrcode": "live-code",
    "qrcode_url": "http://live/qr.png",
    "base_url": "http://base",
}

# Upstream answers the expired refresh can produce without a usable code.
EMPTY_REFRESHES = [
    ("no fields at all", {}),
    ("empty qrcode string", {"qrcode": "", "qrcode_img_content": "http://img/qr.png"}),
    ("null qrcode", {"qrcode": None, "qrcode_img_content": "http://img/qr.png"}),
]


class _FakeApi:
    """Stands in for WeixinApi; records nothing, answers from attributes."""

    def __init__(self, base_url=None):
        self.base_url = base_url
        self.poll_result = {"status": "expired"}
        self.fetch_result = {}

    def poll_qr_status(self, qrcode, timeout=10):
        return self.poll_result

    def fetch_qr_code(self, local_token_list=None):
        return self.fetch_result


class WeixinQrExpiredRefreshTest(unittest.TestCase):
    def setUp(self):
        # web.header() appends to ctx.headers, which needs a request context.
        web.ctx.headers = []
        self._saved_state = WeixinQrHandler._qr_state
        WeixinQrHandler._qr_state = dict(LIVE_STATE)
        self.addCleanup(setattr, WeixinQrHandler, "_qr_state", self._saved_state)

    def test_empty_refresh_keeps_the_session_and_answers_error(self):
        for label, refresh in EMPTY_REFRESHES:
            with self.subTest(refresh=label):
                WeixinQrHandler._qr_state = dict(LIVE_STATE)

                class _Api(_FakeApi):
                    def fetch_qr_code(self, local_token_list=None):
                        return refresh

                with patch.object(web, "data", lambda: b'{"action": "poll"}'), \
                        patch("channel.weixin.weixin_api.WeixinApi", _Api):
                    payload = json.loads(WeixinQrHandler().POST())

                self.assertEqual(payload["status"], "error")
                self.assertEqual(
                    WeixinQrHandler._qr_state.get("qrcode"), LIVE_STATE["qrcode"],
                    "an empty refresh must not overwrite the live qrcode",
                )

    def test_a_good_refresh_still_replaces_the_code(self):
        class _Api(_FakeApi):
            def fetch_qr_code(self, local_token_list=None):
                return {"qrcode": "fresh-code", "qrcode_img_content": "http://img/fresh.png"}

        with patch.object(web, "data", lambda: b'{"action": "poll"}'), \
                patch("channel.weixin.weixin_api.WeixinApi", _Api):
            payload = json.loads(WeixinQrHandler().POST())

        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["qr_status"], "expired")
        self.assertEqual(payload["qrcode_url"], "http://img/fresh.png")
        self.assertEqual(WeixinQrHandler._qr_state["qrcode"], "fresh-code")

    def test_a_failing_refresh_keeps_the_session_too(self):
        class _Api(_FakeApi):
            def fetch_qr_code(self, local_token_list=None):
                raise OSError("upstream unreachable")

        with patch.object(web, "data", lambda: b'{"action": "poll"}'), \
                patch("channel.weixin.weixin_api.WeixinApi", _Api):
            payload = json.loads(WeixinQrHandler().POST())

        self.assertEqual(payload["status"], "error")
        self.assertEqual(WeixinQrHandler._qr_state.get("qrcode"), LIVE_STATE["qrcode"])


if __name__ == "__main__":
    unittest.main()
