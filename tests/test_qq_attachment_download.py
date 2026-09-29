"""QQ attachment downloads must stream within a finite size limit."""

from pathlib import Path
from unittest.mock import patch

from channel.qq import qq_message
from common import media_download


class FakeResponse:
    def __init__(self, chunks, headers=None):
        self.chunks = chunks
        self.headers = headers or {}
        self.closed = False
        self.iterated = False

    def close(self):
        self.closed = True

    def raise_for_status(self):
        pass

    def iter_content(self, chunk_size):
        self.iterated = True
        yield from self.chunks


def _download(tmp_path, response):
    with patch.object(qq_message, "_get_tmp_dir", return_value=str(tmp_path)):
        with patch.object(media_download.requests, "get", return_value=response) as get:
            path = qq_message._download_attachment(
                {"url": "https://example.test/file", "filename": "file.bin"}, "m1", 0
            )
    return path, get


def test_small_attachment_streams_and_closes_response(tmp_path):
    response = FakeResponse([b"abc", b"de"])
    path, get = _download(tmp_path, response)

    assert Path(path).read_bytes() == b"abcde"
    assert get.call_args.kwargs["stream"] is True
    assert response.iterated
    assert response.closed


def test_oversized_stream_leaves_no_file(tmp_path, monkeypatch):
    monkeypatch.setattr(qq_message, "MAX_FILE_BYTES", 5)
    response = FakeResponse([b"abc", b"def"])
    path, _ = _download(tmp_path, response)

    assert path == ""
    assert list(tmp_path.iterdir()) == []
    assert response.closed


def test_oversized_content_length_is_rejected_before_streaming(tmp_path, monkeypatch):
    monkeypatch.setattr(qq_message, "MAX_FILE_BYTES", 5)
    response = FakeResponse([b"abcdef"], {"Content-Length": "6"})
    path, _ = _download(tmp_path, response)

    assert path == ""
    assert not response.iterated
    assert list(tmp_path.iterdir()) == []
    assert response.closed


def test_interrupted_download_leaves_no_partial_file(tmp_path):
    class InterruptedResponse(FakeResponse):
        def iter_content(self, chunk_size):
            yield b"abc"
            raise OSError("connection lost")

    response = InterruptedResponse([b"abc"])
    path, _ = _download(tmp_path, response)

    assert path == ""
    assert list(tmp_path.iterdir()) == []
    assert response.closed
