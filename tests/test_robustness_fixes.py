# encoding:utf-8
"""
Unit tests for robustness fixes:
  1. ChatChannel.cancel_session / cancel_all_session must not raise KeyError
     when a session has been produced but no task has been dispatched yet
     (so self.futures[session_id] does not exist).
  2. common.utils.compress_imgfile must terminate (no infinite loop / invalid
     PIL quality) when an image cannot be compressed below max_size.
"""
import io
import os
import sys
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# =============================================================================
# 1. cancel_session / cancel_all_session KeyError regression
# =============================================================================

class TestCancelSessionMissingFutures(unittest.TestCase):
    """A session may exist in self.sessions before any future is recorded."""

    def _make_channel(self):
        # Import lazily and build a bare object without running __init__,
        # to avoid pulling the full channel setup / config.
        from channel.chat_channel import ChatChannel

        ch = ChatChannel.__new__(ChatChannel)
        import threading

        ch.lock = threading.RLock()
        # A produced session whose future has NOT been dispatched yet.
        queue = MagicMock()
        queue.qsize.return_value = 0
        semaphore = MagicMock()
        ch.sessions = {"sid": [queue, semaphore]}
        ch.futures = {}  # intentionally empty: consume() never ran
        return ch

    def test_cancel_session_no_futures_entry(self):
        ch = self._make_channel()
        # Should not raise KeyError.
        try:
            ch.cancel_session("sid")
        except KeyError:
            self.fail("cancel_session raised KeyError when futures entry missing")

    def test_cancel_all_session_no_futures_entry(self):
        ch = self._make_channel()
        try:
            ch.cancel_all_session()
        except KeyError:
            self.fail("cancel_all_session raised KeyError when futures entry missing")

    def test_cancel_session_cancels_existing_futures(self):
        ch = self._make_channel()
        fut = MagicMock()
        ch.futures["sid"] = [fut]
        ch.cancel_session("sid")
        fut.cancel.assert_called_once()


# =============================================================================
# 2. compress_imgfile termination
# =============================================================================

class TestCompressImgfileTermination(unittest.TestCase):
    """compress_imgfile must always return, even for incompressible input."""

    def setUp(self):
        # Skip if Pillow is not available in the test environment.
        try:
            import PIL  # noqa: F401
        except ImportError:
            self.skipTest("Pillow not installed")

    def _make_image_buf(self, size=(64, 64)):
        from PIL import Image
        import random

        img = Image.new("RGB", size)
        # Fill with random noise so JPEG cannot compress it well.
        pixels = [
            (random.randint(0, 255), random.randint(0, 255), random.randint(0, 255))
            for _ in range(size[0] * size[1])
        ]
        img.putdata(pixels)
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=95)
        buf.seek(0)
        return buf

    def test_returns_when_target_unreachable(self):
        from common.utils import compress_imgfile

        buf = self._make_image_buf()
        # An impossibly small target that even quality=10 won't reach.
        out = compress_imgfile(buf, max_size=10)
        self.assertIsInstance(out, io.BytesIO)
        # Verify the result is still a valid JPEG (PIL never got invalid quality).
        from PIL import Image

        out.seek(0)
        img = Image.open(out)
        img.verify()

    def test_no_compression_needed_returns_same_object(self):
        from common.utils import compress_imgfile

        buf = self._make_image_buf()
        size = buf.getbuffer().nbytes
        out = compress_imgfile(buf, max_size=size + 1)
        self.assertIs(out, buf)


if __name__ == "__main__":
    unittest.main()
