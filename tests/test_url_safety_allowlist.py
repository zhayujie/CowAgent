# encoding:utf-8
"""
Domain allowlist under the strict URL guard.

When the owner lists allowed hosts, the name is the trust boundary: the
request is allowed or refused before any local DNS lookup. Local resolvers
(including VPN / proxy fake-ip) must not decide whether a listed host is
reachable. Literal non-public IPs stay blocked.
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.tools.utils import url_safety
from agent.tools.utils.url_safety import strict_url_guard, validate_url_safe


def _gai(ip_str):
    return [(2, 1, 6, "", (ip_str, 0))]


class AllowlistGuardTest(unittest.TestCase):
    def test_allowlisted_host_does_not_resolve(self):
        with patch.object(url_safety.socket, "getaddrinfo") as gai:
            with strict_url_guard(["cowagent.ai"]):
                validate_url_safe("https://docs.cowagent.ai/zh/intro/index.md")
        gai.assert_not_called()

    def test_host_outside_the_allowlist_is_refused(self):
        with patch.object(url_safety.socket, "getaddrinfo") as gai:
            with strict_url_guard(["cowagent.ai"]):
                with self.assertRaises(ValueError):
                    validate_url_safe("https://intranet.example.com/")
        gai.assert_not_called()

    def test_private_ip_literal_is_blocked_even_with_an_allowlist(self):
        with strict_url_guard(["cowagent.ai"]):
            with self.assertRaises(ValueError):
                validate_url_safe("https://10.0.0.5/")

    def test_loopback_literal_is_blocked_even_if_listed(self):
        with strict_url_guard(["127.0.0.1"]):
            with self.assertRaises(ValueError):
                validate_url_safe("http://127.0.0.1/admin")

    def test_without_allowlist_a_private_resolution_is_still_blocked(self):
        with patch.object(url_safety.socket, "getaddrinfo", return_value=_gai("10.0.0.5")):
            with strict_url_guard():
                with self.assertRaises(ValueError):
                    validate_url_safe("https://nas.local/admin")


if __name__ == "__main__":
    unittest.main()
