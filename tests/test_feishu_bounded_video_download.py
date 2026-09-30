# encoding:utf-8
"""
Regression test for channel/feishu/feishu_channel.py::_upload_video_url.

A remote video was fetched with a bare ``requests.get`` and written via
``file.write(response.content)`` (P4): no byte cap, so a huge or endless
response was buffered into memory and dropped on disk. The image and file
paths in the same file already use ``download_to_file``/``download_bytes``
from common/media_download, which stream and cap at MAX_FILE_BYTES. Pin the
video path to the same contract: an oversized remote video must be refused
(return None) rather than silently accepted.
"""
import io
import os
import sys
import unittest
from unittest.mock import patch

import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from common.media_download import MAX_FILE_BYTES
from channel.feishu import feishu_channel as mod


class _FakeResp:
    def __init__(self, content=b"", status=200, headers=None):
        self.content = content
        self.status_code = status
        self.headers = headers or {}
    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))
    def iter_content(self, chunk_size=8192):
        yield self.content
    def close(self):
        pass
    def json(self):
        return {"code": 0, "data": {"file_key": "k"}}


class _FakeFile:
    def __init__(self, data=b""):
        self._b = io.BytesIO(data)
    def write(self, b):
        return self._b.write(b)
    def read(self, *a, **k):
        return self._b.getvalue()
    def __enter__(self):
        return self
    def __exit__(self, *a, **k):
        return False


def _channel():
    cls = getattr(mod, "FeiShuChanel")
    cls = getattr(cls, "__wrapped__", cls)
    ch = cls.__new__(cls)
    ch._get_video_duration = lambda p: 0
    return ch


class TestFeishuBoundedVideoDownload(unittest.TestCase):
    def test_oversized_remote_video_is_refused(self):
        ch = _channel()
        big = b"x" * (MAX_FILE_BYTES + 1024)
        resp = _FakeResp(big, headers={"Content-Length": str(len(big))})
        with patch.object(requests, "get", lambda *a, **k: resp), \
             patch.object(mod, "open", lambda *a, **k: _FakeFile()), \
             patch.object(requests, "post", lambda *a, **k: _FakeResp()):
            result = ch._upload_video_url("https://example.com/v.mp4", "tok")
        self.assertIsNone(result)

    def test_normal_remote_video_uploads(self):
        ch = _channel()
        resp = _FakeResp(b"short-video-bytes")
        with patch.object(requests, "get", lambda *a, **k: resp), \
             patch.object(mod, "open", lambda *a, **k: _FakeFile(b"short-video-bytes")), \
             patch.object(requests, "post", lambda *a, **k: _FakeResp()):
            result = ch._upload_video_url("https://example.com/v.mp4", "tok")
        self.assertIsNotNone(result)
        self.assertEqual(result.get("file_key"), "k")
