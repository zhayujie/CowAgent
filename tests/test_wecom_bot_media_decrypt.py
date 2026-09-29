"""Encrypted WeCom inbound media must stay bounded and reject corrupt padding."""

import base64

import pytest
from Crypto.Cipher import AES

from channel.wecom_bot import wecom_bot_message as media
from common import media_download


KEY = bytes(range(32))
ENCODING_KEY = base64.b64encode(KEY).decode().rstrip("=")


def _encrypt(plaintext):
    pad = 32 - len(plaintext) % 32
    padded = plaintext + bytes([pad]) * pad
    return AES.new(KEY, AES.MODE_CBC, KEY[:16]).encrypt(padded)


class Response:
    def __init__(self, body, headers=None, fail_after_first=False):
        self.body = body
        self.headers = headers or {}
        self.fail_after_first = fail_after_first
        self.closed = False

    def raise_for_status(self):
        pass

    def iter_content(self, chunk_size):
        for offset in range(0, len(self.body), chunk_size):
            yield self.body[offset:offset + chunk_size]
            if self.fail_after_first:
                raise OSError("connection lost")

    def close(self):
        self.closed = True


def test_valid_media_decrypts_and_closes_response(monkeypatch):
    response = Response(_encrypt(b"image bytes"))
    calls = []

    def get(*args, **kwargs):
        calls.append(kwargs)
        return response

    monkeypatch.setattr(media_download.requests, "get", get)

    assert media._decrypt_media("https://example.test/media", ENCODING_KEY) == b"image bytes"
    assert response.closed
    assert calls == [{"stream": True, "timeout": (5, 30)}]


def test_declared_oversize_rejected_before_streaming(monkeypatch):
    response = Response(b"", {"Content-Length": str(media.MAX_FILE_BYTES + 1)})
    monkeypatch.setattr(media_download.requests, "get", lambda *args, **kwargs: response)

    with pytest.raises(ValueError, match="too large"):
        media._decrypt_media("https://example.test/media", ENCODING_KEY)
    assert response.closed


def test_streamed_oversize_rejected_without_length_header(monkeypatch):
    monkeypatch.setattr(media, "MAX_FILE_BYTES", 8)
    response = Response(_encrypt(b"image bytes"))
    monkeypatch.setattr(media_download.requests, "get", lambda *args, **kwargs: response)

    with pytest.raises(ValueError, match="too large"):
        media._decrypt_media("https://example.test/media", ENCODING_KEY)
    assert response.closed


@pytest.mark.parametrize("plaintext", [b"content" + bytes([0]) * 25, b"content" + bytes(24) + b"\x02"])
def test_invalid_padding_is_rejected(monkeypatch, plaintext):
    # Encrypt an entire block without adding valid PKCS#7 padding.
    response = Response(AES.new(KEY, AES.MODE_CBC, KEY[:16]).encrypt(plaintext))
    monkeypatch.setattr(media_download.requests, "get", lambda *args, **kwargs: response)

    with pytest.raises(ValueError, match="Invalid PKCS7 padding"):
        media._decrypt_media("https://example.test/media", ENCODING_KEY)
    assert response.closed


def test_interrupted_stream_closes_response(monkeypatch):
    response = Response(_encrypt(b"image bytes"), fail_after_first=True)
    monkeypatch.setattr(media_download.requests, "get", lambda *args, **kwargs: response)

    with pytest.raises(OSError, match="connection lost"):
        media._decrypt_media("https://example.test/media", ENCODING_KEY)
    assert response.closed
