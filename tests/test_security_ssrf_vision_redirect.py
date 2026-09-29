# encoding:utf-8
"""
Regression tests for the vision tool's SSRF protection across redirect hops.

Vision fetches a model-supplied image URL and base64-embeds whatever comes
back into the LLM request. The guard checked only the URL the model supplied,
while the download used a plain ``requests.get`` — which follows redirects
automatically. A public URL that 3xx-redirected into a loopback / link-local /
cloud-metadata address was therefore fetched unchecked, and the internal body
was handed to the model. web_fetch already re-validates every hop.

These tests drive the real redirect path against two real loopback HTTP
servers: an "entry" server (stand-in for a public CDN host) answering 302, and
an "internal" server that records every hit. No external network is used.
"""
import os
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.tools.utils import url_safety
from agent.tools.vision import vision as vision_mod

IMAGE_BYTES = b"\x89PNG\r\n\x1a\npublic-image"


def _serve(reply, hits):
    """Answer GETs on a loopback port with ``reply(handler)``; record paths."""

    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            hits.append(self.path)
            reply(self)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, server.server_address[1]


def _send_image(handler):
    handler.send_response(200)
    handler.send_header("Content-Type", "image/png")
    handler.send_header("Content-Length", str(len(IMAGE_BYTES)))
    handler.end_headers()
    handler.wfile.write(IMAGE_BYTES)


class TestVisionRedirectSSRF(unittest.TestCase):
    """A redirect into an internal address must be refused, as in web_fetch."""

    def setUp(self):
        self._prev_env = os.environ.get("WEB_SECURITY_SSRF_PROTECTION")
        os.environ["WEB_SECURITY_SSRF_PROTECTION"] = "true"

        self.internal_hits = []
        self.internal, self.internal_port = _serve(_send_image, self.internal_hits)
        self.internal_url = (
            "http://127.0.0.1:%d/latest/meta-data/iam/security-credentials/"
            % self.internal_port
        )

        self.entry_hits = []

        def _entry(handler):
            if handler.path == "/plain.png":
                _send_image(handler)
                return
            handler.send_response(302)
            handler.send_header("Location", self.internal_url)
            handler.send_header("Content-Length", "0")
            handler.end_headers()

        self.entry, self.entry_port = _serve(_entry, self.entry_hits)
        self.entry_origin = "http://127.0.0.1:%d/" % self.entry_port

    def tearDown(self):
        for server in (self.entry, self.internal):
            server.shutdown()
            server.server_close()
        if self._prev_env is None:
            os.environ.pop("WEB_SECURITY_SSRF_PROTECTION", None)
        else:
            os.environ["WEB_SECURITY_SSRF_PROTECTION"] = self._prev_env

    def _public_origin_guard(self, validated):
        """Stand in for the real guard: only the entry origin counts as public."""

        def _validate(url):
            validated.append(url)
            if not url.startswith(self.entry_origin):
                raise ValueError(
                    "URL resolves to a non-public address, request blocked for security"
                )

        return _validate

    def _guard(self, validated):
        guard = self._public_origin_guard(validated)
        return patch.object(vision_mod, "validate_url_safe", side_effect=guard), patch.object(
            url_safety, "validate_url_safe", side_effect=guard
        )

    def test_redirect_into_an_internal_address_is_refused(self):
        """A public URL that 302s to an internal target must not be fetched."""
        validated = []
        vision_guard, helper_guard = self._guard(validated)
        with vision_guard, helper_guard:
            with self.assertRaises(ValueError) as ctx:
                vision_mod.Vision()._build_image_content(self.entry_origin + "photo.png")

        self.assertIn("non-public", str(ctx.exception))
        # The redirect target was re-validated before it could be requested…
        self.assertIn(self.internal_url, validated)
        # …so the internal endpoint was never contacted.
        self.assertEqual(self.internal_hits, [])
        self.assertEqual(self.entry_hits, ["/photo.png"])

    def test_a_plain_image_url_is_still_downloaded(self):
        """Control: a URL that does not redirect keeps working."""
        validated = []
        vision_guard, helper_guard = self._guard(validated)
        with vision_guard, helper_guard:
            content = vision_mod.Vision()._build_image_content(self.entry_origin + "plain.png")

        self.assertTrue(content["image_url"]["url"].startswith("data:image/png;base64,"))
        self.assertEqual(self.internal_hits, [])

    def test_internal_literal_is_refused_before_any_request(self):
        """The pre-existing guard on the supplied URL still holds."""
        with self.assertRaises(ValueError):
            vision_mod.Vision()._build_image_content(
                "http://127.0.0.1:%d/photo.png" % self.internal_port
            )
        self.assertEqual(self.internal_hits, [])
        self.assertEqual(self.entry_hits, [])

    def test_redirect_is_still_followed_when_protection_is_disabled(self):
        """Opt-in guard off (the default): redirects keep working as before."""
        os.environ.pop("WEB_SECURITY_SSRF_PROTECTION", None)
        content = vision_mod.Vision()._build_image_content(self.entry_origin + "photo.png")

        self.assertTrue(content["image_url"]["url"].startswith("data:image/png;base64,"))
        self.assertEqual(self.internal_hits, ["/latest/meta-data/iam/security-credentials/"])


if __name__ == "__main__":
    unittest.main()
