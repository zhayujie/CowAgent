"""The MCP OAuth callback page must escape the error query params.

/mcp/oauth/callback is unauthenticated by design (the OAuth `state` param is
the single-use secret), so anyone can craft a link whose `error` /
`error_description` values land verbatim in the HTML response. Before the
escape, a console owner clicking such a link ran attacker script in the
console's origin — same-origin requests carry the victim's session cookie.
"""

import os
import sys
import types
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

if "web" not in sys.modules:
    web_stub = types.ModuleType("web")
    web_stub.HTTPError = type("HTTPError", (Exception,), {})
    web_stub.cookies = lambda: {}
    web_stub.header = lambda *args, **kwargs: None
    web_stub.data = lambda: b"{}"
    web_stub.input = lambda **kwargs: types.SimpleNamespace(**kwargs)
    web_stub.setcookie = lambda *args, **kwargs: None
    sys.modules["web"] = web_stub


class TestMcpOAuthCallbackEscapesErrorParams(unittest.TestCase):

    def _get(self, **params):
        import channel.web.api.auth as auth_api

        base = {"code": "", "state": "", "error": "", "error_description": ""}
        base.update(params)
        # Patch header too: when another test imported the real web.py first,
        # calling it outside a request context raises before the page renders.
        with patch.object(auth_api.web, "input", lambda **kwargs: types.SimpleNamespace(**base)), \
                patch.object(auth_api.web, "header", lambda *a, **k: None):
            return auth_api.McpOAuthCallbackHandler().GET()

    def test_error_param_is_escaped(self):
        page = self._get(error="<script>alert(1)</script>")
        self.assertNotIn("<script>", page, "raw script tag reached the response")
        self.assertIn("&lt;script&gt;", page)

    def test_error_description_is_escaped(self):
        page = self._get(
            error="oops",
            error_description='<img src=x onerror="fetch(\'/api/config\')">',
        )
        self.assertNotIn('<img src=x', page, "raw img tag reached the response")
        self.assertIn("&lt;img src=x", page)

    def test_markup_escaping_does_not_break_the_plain_error_page(self):
        page = self._get(error="invalid_scope", error_description="user denied")
        self.assertIn("invalid_scope", page)
        self.assertIn("user denied", page)


if __name__ == "__main__":
    unittest.main()
