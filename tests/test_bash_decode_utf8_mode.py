# encoding:utf-8
"""
Regression test for decoding Windows command output in Python's UTF-8 mode.

When a command's output is not valid UTF-8, decode_output() falls back to the
Windows code page (cp936/GBK on Chinese Windows). It used to look that code
page up with locale.getpreferredencoding(), but in UTF-8 mode (PYTHONUTF8=1,
-X utf8, and the default from Python 3.15) that function always returns
"utf-8". The fallback was then skipped and GBK output such as `dir` error
messages came back as mojibake.
"""
import locale
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.tools.bash import decode


def test_gbk_output_is_decoded_in_utf8_mode(monkeypatch):
    # What the locale module reports on Chinese Windows in UTF-8 mode.
    monkeypatch.setattr(decode.sys, "platform", "win32")
    monkeypatch.setattr(locale, "getpreferredencoding", lambda do_setlocale=True: "utf-8")
    monkeypatch.setattr(locale, "getencoding", lambda: "cp936", raising=False)

    text = "系统找不到指定的路径。"
    assert decode.decode_output(text.encode("gbk")) == text


def test_utf8_output_is_unchanged_in_utf8_mode(monkeypatch):
    monkeypatch.setattr(decode.sys, "platform", "win32")
    monkeypatch.setattr(locale, "getpreferredencoding", lambda do_setlocale=True: "utf-8")
    monkeypatch.setattr(locale, "getencoding", lambda: "cp936", raising=False)

    text = "系统找不到指定的路径。"
    assert decode.decode_output(text.encode("utf-8")) == text
