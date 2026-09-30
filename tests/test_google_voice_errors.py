# encoding:utf-8
"""
Unit tests for voice/google/google_voice.py error handling.

Both methods used to end in ``finally: return reply``. ``reply`` is only bound
inside the try/except body, so any exception the clauses did not catch reached
``return`` with the name still unbound: the caller saw
``UnboundLocalError: cannot access local variable 'reply'`` and the real cause
was gone. A ``return`` inside ``finally`` also discards a propagating
``BaseException``, so a cancelled or interrupted turn looked like an ordinary
error reply.

``speech_recognition`` and ``gtts`` are optional extras, so they are stubbed the
same way the other optional-dependency tests in this suite do.
"""
import os
import sys
import types
import unittest
import unittest.mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from bridge.reply import ReplyType


class UnknownValueError(Exception):
    pass


class RequestError(Exception):
    pass


class _AudioFile:
    def __init__(self, path):
        self.path = path

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


class _Recognizer:
    """A recognizer whose outcome is chosen by ``mode``."""

    def __init__(self, mode="ok"):
        self.mode = mode

    def record(self, source):
        return object()

    def recognize_google(self, audio, language=None):
        if self.mode == "unknown":
            raise UnknownValueError()
        if self.mode == "request":
            raise RequestError("no network")
        if self.mode == "boom":
            raise RuntimeError("audio backend exploded")
        if self.mode == "interrupt":
            raise KeyboardInterrupt()
        return "hello"


def _install_stubs():
    sr = types.ModuleType("speech_recognition")
    sr.UnknownValueError = UnknownValueError
    sr.RequestError = RequestError
    sr.AudioFile = _AudioFile
    sr.Recognizer = _Recognizer
    sys.modules.setdefault("speech_recognition", sr)

    gtts = types.ModuleType("gtts")

    class _TTS:
        def __init__(self, text=None, lang=None):
            self.fail = False

        def save(self, path):
            if self.fail:
                raise OSError("disk full")

    gtts.gTTS = _TTS
    sys.modules.setdefault("gtts", gtts)


_install_stubs()

from voice.google.google_voice import GoogleVoice  # noqa: E402


class TestGoogleVoiceToText(unittest.TestCase):
    def _voice(self, mode):
        voice = GoogleVoice()
        voice.recognizer = _Recognizer(mode)
        return voice

    def test_successful_recognition_returns_text(self):
        reply = self._voice("ok").voiceToText("f.wav")
        self.assertEqual(reply.type, ReplyType.TEXT)
        self.assertEqual(reply.content, "hello")

    def test_unrecognisable_speech_returns_error(self):
        reply = self._voice("unknown").voiceToText("f.wav")
        self.assertEqual(reply.type, ReplyType.ERROR)

    def test_request_failure_returns_error(self):
        reply = self._voice("request").voiceToText("f.wav")
        self.assertEqual(reply.type, ReplyType.ERROR)

    def test_unexpected_exception_returns_error_not_unboundlocal(self):
        """A RuntimeError must not surface as UnboundLocalError."""
        reply = self._voice("boom").voiceToText("f.wav")
        self.assertEqual(reply.type, ReplyType.ERROR)
        self.assertTrue(reply.content)

    def test_base_exception_is_not_swallowed(self):
        """KeyboardInterrupt must propagate, not become an error reply."""
        with self.assertRaises(KeyboardInterrupt):
            self._voice("interrupt").voiceToText("f.wav")


class TestGoogleTextToVoice(unittest.TestCase):
    def test_base_exception_is_not_swallowed(self):
        """textToVoice must not turn a cancellation into a normal error reply.

        Patched on the module under test, because google_voice.py did
        ``from gtts import gTTS`` and holds that name directly.
        """
        import voice.google.google_voice as google_voice

        def _interrupt(text=None, lang=None):
            raise KeyboardInterrupt()

        with unittest.mock.patch.object(google_voice, "gTTS", _interrupt):
            with self.assertRaises(KeyboardInterrupt):
                GoogleVoice().textToVoice("hello")


if __name__ == "__main__":
    unittest.main()
