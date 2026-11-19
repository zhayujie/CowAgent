"""A remote image URL in a Gemini message block is downloaded and inlined.

The URL arrives in message content, and ``call_vision`` passes one the model
itself produced. Every other place that fetches media -- all the channels,
``vision``, ``web_fetch``, the skills service -- goes through
``common.media_download``, which streams the body, stops at ``MAX_IMAGE_BYTES``
and, with ``web_security_ssrf_protection`` on, validates the URL and every
redirect hop. Gemini inlined the body whole with a bare ``requests.get``, so
an endless or oversize response was buffered into memory (and then grown
another third by ``base64``) and a private URL was fetched unchecked.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

IMAGE_URL = "https://cdn.example.com/a.png"


class _Resp:
    """The parts of a ``requests.Response`` these code paths touch."""

    def __init__(self, *, status=200, headers=None, body=b""):
        self.status_code = status
        self.headers = dict(headers or {})
        self._body = body
        self.closed = False

    @property
    def content(self):
        return self._body

    @property
    def is_redirect(self):
        return self.status_code in (301, 302, 303, 307, 308)

    @property
    def is_permanent_redirect(self):
        return self.status_code in (301, 308)

    def iter_content(self, chunk_size=1):
        for start in range(0, len(self._body), 4096):
            yield self._body[start:start + 4096]

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def close(self):
        self.closed = True


def _patch_get(monkeypatch, build):
    """Install a fake ``requests.get`` and return the URLs it was asked for."""
    from models.gemini import google_gemini_bot

    calls = []

    def _get(url, **kwargs):
        calls.append(url)
        return build(url, kwargs)

    monkeypatch.setattr(google_gemini_bot.requests, "get", _get)
    return calls


def _inline(url):
    from models.gemini.google_gemini_bot import GoogleGeminiBot

    return GoogleGeminiBot._build_inline_part_from_image_url({"url": url})


def _cap(monkeypatch, limit):
    import common.media_download as media_download

    monkeypatch.setattr(media_download, "MAX_IMAGE_BYTES", limit)


def test_a_declared_oversize_image_is_refused(monkeypatch):
    """Content-Length over the cap is rejected before the body is read."""
    _cap(monkeypatch, 4096)
    _patch_get(monkeypatch, lambda url, kwargs: _Resp(
        headers={"Content-Length": "8192", "Content-Type": "image/png"},
        body=b"x" * 8192,
    ))

    assert _inline(IMAGE_URL) is None


def test_an_unbounded_body_is_stopped_at_the_cap(monkeypatch):
    """No Content-Length header: the stream itself has to stop at the cap."""
    _cap(monkeypatch, 4096)
    _patch_get(monkeypatch, lambda url, kwargs: _Resp(
        headers={"Content-Type": "image/png"},
        body=b"x" * 65536,
    ))

    assert _inline(IMAGE_URL) is None


def test_the_cap_holds_with_ssrf_protection_off(monkeypatch):
    """The size cap is unconditional; it does not depend on the SSRF switch."""
    _cap(monkeypatch, 4096)
    monkeypatch.delenv("WEB_SECURITY_SSRF_PROTECTION", raising=False)
    _patch_get(monkeypatch, lambda url, kwargs: _Resp(
        headers={"Content-Type": "image/png"},
        body=b"x" * 65536,
    ))

    assert _inline(IMAGE_URL) is None


def test_a_private_url_is_never_requested_when_the_guard_is_on(monkeypatch):
    """A loopback image URL must not be fetched at all with the guard on."""
    monkeypatch.setenv("WEB_SECURITY_SSRF_PROTECTION", "1")
    calls = _patch_get(monkeypatch, lambda url, kwargs: _Resp(
        headers={"Content-Type": "image/png"}, body=b"png",
    ))

    assert _inline("http://127.0.0.1:8080/secret.png") is None
    assert calls == [], f"the private URL was requested: {calls}"


def test_a_normal_image_still_becomes_an_inline_part(monkeypatch):
    """The guard must not break ordinary remote images."""
    monkeypatch.delenv("WEB_SECURITY_SSRF_PROTECTION", raising=False)
    _patch_get(monkeypatch, lambda url, kwargs: _Resp(
        headers={"Content-Type": "image/png"}, body=b"png-bytes",
    ))

    part = _inline(IMAGE_URL)

    assert part is not None
    assert part["inlineData"]["mimeType"] == "image/png"
    import base64
    assert base64.b64decode(part["inlineData"]["data"]) == b"png-bytes"


def test_an_oversize_local_image_is_not_inlined(monkeypatch, tmp_path):
    """A local file is checked on disk before it is read into a base64 part."""
    _cap(monkeypatch, 4096)
    path = tmp_path / "big.png"
    path.write_bytes(b"x" * 65536)

    from models.gemini.google_gemini_bot import GoogleGeminiBot

    assert GoogleGeminiBot._build_image_inline_part(str(path)) is None
