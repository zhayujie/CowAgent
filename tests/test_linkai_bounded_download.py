# encoding:utf-8
"""LinkAI's file sender must cap its download.

``_download_file`` did a bare requests.get and wrote resp.content, so the
whole body was buffered before anything could object -- ``media_download``'s
docstring spells out why a socket timeout alone never fires on a server that
keeps trickling bytes. The LinkAI voice download already routes through the
shared helper; this file download was the one that did not.
"""

import pytest


class _Stream:
    """A minimal streamed response: chunks, headers, close."""

    def __init__(self, chunks, headers=None):
        self._chunks = list(chunks)
        self.headers = headers or {}
        # The pre-fix code path read the whole body instead of streaming.
        self.content = b"".join(self._chunks)

    def raise_for_status(self):
        return None

    def iter_content(self, chunk_size=1):
        for chunk in self._chunks:
            yield chunk

    def close(self):
        return None


def _oversized(chunks=8, size=512):
    return [b"x" * size] * chunks


def _cap(monkeypatch, module, size=1024):
    """Shrink the shared cap so an oversized body is a few chunks, not 100 MB.

    ``raising=False`` keeps this working on the unfixed code, where the
    module does not import the constant yet: there the real 100 MB cap
    applies and the small body sails through -- which is the bug.
    """
    monkeypatch.setattr(module, "MAX_FILE_BYTES", size, raising=False)


def test_linkai_file_download_refuses_an_oversized_body(tmp_path, monkeypatch):
    from models.linkai import link_ai_bot

    _cap(monkeypatch, link_ai_bot)
    monkeypatch.setattr(link_ai_bot.state_dir, "tmp_dir", lambda: tmp_path)
    monkeypatch.setattr(link_ai_bot.requests, "get",
                        lambda *a, **k: _Stream(_oversized()))

    assert link_ai_bot._download_file("https://files.example.com/report.pdf") is None
    # A refused download leaves no partial file behind.
    assert list(tmp_path.iterdir()) == []


def test_linkai_file_download_still_writes_ordinary_bodies(tmp_path, monkeypatch):
    from models.linkai import link_ai_bot

    monkeypatch.setattr(link_ai_bot.state_dir, "tmp_dir", lambda: tmp_path)
    monkeypatch.setattr(link_ai_bot.requests, "get",
                        lambda *a, **k: _Stream([b"%PDF-1.7"]))

    result = link_ai_bot._download_file("https://files.example.com/report.pdf")

    assert result == str(tmp_path / "report.pdf")
    assert (tmp_path / "report.pdf").read_bytes() == b"%PDF-1.7"


@pytest.mark.parametrize("status_code", [403, 404])
def test_linkai_file_download_refuses_an_error_page(tmp_path, monkeypatch, status_code):
    """An expired signed link answers with an HTML page, not the file."""
    from models.linkai import link_ai_bot

    class _Error(_Stream):
        def raise_for_status(self):
            raise link_ai_bot.requests.exceptions.HTTPError(
                f"{status_code} Client Error")

    monkeypatch.setattr(link_ai_bot.state_dir, "tmp_dir", lambda: tmp_path)
    monkeypatch.setattr(link_ai_bot.requests, "get",
                        lambda *a, **k: _Error([b"<html>expired</html>"]))

    assert link_ai_bot._download_file("https://files.example.com/report.pdf") is None
    assert list(tmp_path.iterdir()) == []
