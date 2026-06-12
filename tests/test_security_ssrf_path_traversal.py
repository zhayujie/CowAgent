# encoding:utf-8
"""
Unit tests for security fixes:
  1. Vision tool SSRF protection (issue #2878, #2872)
  2. Skill service path traversal protection (issue #2873)
"""
import os
import sys
import tempfile
import types
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Stub 'requests' if not installed so vision.py can be imported for testing.
if "requests" not in sys.modules:
    _requests_stub = types.ModuleType("requests")
    _requests_stub.get = lambda *a, **k: None
    sys.modules["requests"] = _requests_stub


# =============================================================================
# Vision SSRF tests
# =============================================================================

class TestVisionSSRFValidation(unittest.TestCase):
    """Test that _validate_url_safe blocks internal/private URLs."""

    def setUp(self):
        from agent.tools.vision.vision import Vision
        self.validate = Vision._validate_url_safe

    def test_loopback_ipv4_blocked(self):
        """127.0.0.1 must be rejected."""
        with self.assertRaises(ValueError) as ctx:
            self.validate("http://127.0.0.1/canary.png")
        self.assertIn("non-public", str(ctx.exception))

    def test_loopback_localhost_blocked(self):
        """localhost must be rejected."""
        with self.assertRaises(ValueError) as ctx:
            self.validate("http://localhost/canary.png")
        self.assertIn("non-public", str(ctx.exception))

    def test_private_10_network_blocked(self):
        """10.x.x.x RFC1918 must be rejected."""
        with patch("socket.getaddrinfo") as mock_gai:
            mock_gai.return_value = [
                (2, 1, 6, "", ("10.0.0.1", 0)),
            ]
            with self.assertRaises(ValueError) as ctx:
                self.validate("http://internal.corp/image.png")
            self.assertIn("non-public", str(ctx.exception))

    def test_private_172_network_blocked(self):
        """172.16.x.x RFC1918 must be rejected."""
        with patch("socket.getaddrinfo") as mock_gai:
            mock_gai.return_value = [
                (2, 1, 6, "", ("172.16.0.1", 0)),
            ]
            with self.assertRaises(ValueError) as ctx:
                self.validate("http://internal.corp/image.png")
            self.assertIn("non-public", str(ctx.exception))

    def test_private_192_168_blocked(self):
        """192.168.x.x RFC1918 must be rejected."""
        with patch("socket.getaddrinfo") as mock_gai:
            mock_gai.return_value = [
                (2, 1, 6, "", ("192.168.1.1", 0)),
            ]
            with self.assertRaises(ValueError) as ctx:
                self.validate("http://router.local/image.png")
            self.assertIn("non-public", str(ctx.exception))

    def test_link_local_blocked(self):
        """169.254.x.x (link-local / cloud metadata) must be rejected."""
        with patch("socket.getaddrinfo") as mock_gai:
            mock_gai.return_value = [
                (2, 1, 6, "", ("169.254.169.254", 0)),
            ]
            with self.assertRaises(ValueError) as ctx:
                self.validate("http://metadata.google.internal/image.png")
            self.assertIn("non-public", str(ctx.exception))

    def test_ipv6_loopback_blocked(self):
        """::1 (IPv6 loopback) must be rejected."""
        with patch("socket.getaddrinfo") as mock_gai:
            mock_gai.return_value = [
                (10, 1, 6, "", ("::1", 0, 0, 0)),
            ]
            with self.assertRaises(ValueError) as ctx:
                self.validate("http://[::1]/image.png")
            self.assertIn("non-public", str(ctx.exception))

    def test_public_url_allowed(self):
        """A URL resolving to a public IP should pass validation."""
        with patch("socket.getaddrinfo") as mock_gai:
            mock_gai.return_value = [
                (2, 1, 6, "", ("151.101.1.140", 0)),
            ]
            # Should not raise
            self.validate("https://cdn.example.com/image.png")

    def test_no_hostname_rejected(self):
        """A URL with no host must be rejected."""
        with self.assertRaises(ValueError) as ctx:
            self.validate("http:///path/to/image.png")
        self.assertIn("no hostname", str(ctx.exception))

    def test_non_http_scheme_rejected(self):
        """file:// and ftp:// schemes must be rejected."""
        with self.assertRaises(ValueError) as ctx:
            self.validate("file:///etc/passwd")
        self.assertIn("scheme", str(ctx.exception))

    def test_dns_failure_rejected(self):
        """Unresolvable hostname must be rejected."""
        import socket as sock_mod
        with patch("socket.getaddrinfo", side_effect=sock_mod.gaierror("Name does not resolve")):
            with self.assertRaises(ValueError) as ctx:
                self.validate("http://nonexistent.invalid/img.png")
            self.assertIn("Cannot resolve", str(ctx.exception))


# =============================================================================
# Skill service path traversal tests
# =============================================================================

class TestSkillServicePathTraversal(unittest.TestCase):
    """Test that _safe_skill_dir blocks path traversal attempts."""

    def setUp(self):
        self.tmp_root = tempfile.mkdtemp()
        # Create a minimal SkillManager mock with custom_dir set.
        from agent.skills.service import SkillService
        mock_manager = MagicMock()
        mock_manager.custom_dir = self.tmp_root
        self.svc = SkillService(mock_manager)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp_root, ignore_errors=True)

    def test_normal_name_allowed(self):
        """A simple name like 'my-skill' should produce a valid path."""
        result = self.svc._safe_skill_dir("my-skill")
        expected = os.path.realpath(os.path.join(self.tmp_root, "my-skill"))
        self.assertEqual(result, expected)

    def test_dotdot_traversal_blocked(self):
        """'../escaped' must be rejected."""
        with self.assertRaises(ValueError) as ctx:
            self.svc._safe_skill_dir("../escaped")
        self.assertIn("path traversal", str(ctx.exception))

    def test_nested_dotdot_blocked(self):
        """'foo/../../escaped' must be rejected."""
        with self.assertRaises(ValueError) as ctx:
            self.svc._safe_skill_dir("foo/../../escaped")
        self.assertIn("path traversal", str(ctx.exception))

    def test_absolute_path_blocked(self):
        """'/tmp/evil' must be rejected."""
        with self.assertRaises(ValueError) as ctx:
            self.svc._safe_skill_dir("/tmp/evil")
        self.assertIn("path traversal", str(ctx.exception))

    def test_backslash_path_blocked(self):
        r"""'\\server\share' must be rejected."""
        with self.assertRaises(ValueError) as ctx:
            self.svc._safe_skill_dir("\\server\\share")
        self.assertIn("path traversal", str(ctx.exception))

    def test_empty_name_blocked(self):
        """Empty name must be rejected."""
        with self.assertRaises(ValueError):
            self.svc._safe_skill_dir("")

    def test_whitespace_only_blocked(self):
        """Whitespace-only name must be rejected."""
        with self.assertRaises(ValueError):
            self.svc._safe_skill_dir("   ")

    def test_subdir_name_allowed(self):
        """A name with a forward slash but no traversal is allowed if it stays in root."""
        # e.g. "category/skill-name" is a valid nested skill directory
        result = self.svc._safe_skill_dir("category/skill-name")
        expected = os.path.realpath(os.path.join(self.tmp_root, "category/skill-name"))
        self.assertEqual(result, expected)


if __name__ == "__main__":
    unittest.main()
