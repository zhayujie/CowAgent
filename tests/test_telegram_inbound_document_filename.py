"""A sender-chosen document name must not turn a telegram message into a drop.

``TelegramChannel._download_file`` joined the ``file_name`` straight out of the
inbound document onto ``get_tmp_dir()``. A name that is not a single path
component — ``sub/dir/q1.pdf``, ``../../outside.txt``, an absolute path, which a
sender can produce through the Bot API's ``filename`` field — pointed the
download at a directory that does not exist, python-telegram-bot's plain
``open(custom_path, "wb")`` raised, and the bare ``except Exception`` swallowed
it: ``_parse_message`` returned ``(None, None, "")`` and the user's file message
was ignored with only a log line. slack and discord reduce the name with their
own guard and weixin goes through ``safe_filename`` since a371f371; telegram was
the remaining inbound-download site that joined it raw.
"""

import asyncio
from pathlib import Path

import pytest

from channel.telegram import telegram_channel as tc

HOSTILE_NAMES = ["../../outside.txt", "..\\..\\win.txt", "sub/dir/evil.pdf",
                 "reports/2024/q1.pdf", "/etc/passwd"]

FILE_ID = "BAACAgUAAxkBDDk"


class _FakeFile:
    def __init__(self, written):
        self._written = written

    async def download_to_drive(self, custom_path):
        # What python-telegram-bot does: a plain open() with no mkdir, so a
        # parent directory the name dragged in raises FileNotFoundError here.
        with open(custom_path, "wb") as f:
            f.write(b"payload")
        self._written.append(custom_path)


class _FakeBot:
    def __init__(self, written):
        self._written = written

    async def get_file(self, file_id):
        return _FakeFile(self._written)


def _channel(tmp_path, monkeypatch):
    channel = object.__new__(tc.TelegramChannel.__wrapped__)
    written = []
    channel._bot = _FakeBot(written)
    monkeypatch.setattr(tc.TelegramMessage, "get_tmp_dir", staticmethod(lambda: str(tmp_path)))
    return channel, written


@pytest.mark.parametrize("hostile", HOSTILE_NAMES)
def test_a_document_name_with_a_separator_still_downloads(tmp_path, monkeypatch, hostile):
    channel, written = _channel(tmp_path, monkeypatch)

    path = asyncio.run(
        channel._download_file(FILE_ID, suffix=".pdf", original_name=hostile)
    )

    assert written, "the download must still run"
    assert path is not None, "the message must not be dropped"
    assert Path(path).parent == tmp_path, f"{path} left the tmp dir"
    assert Path(path).read_bytes() == b"payload"


def test_an_ordinary_document_name_is_still_the_one_the_sender_picked(tmp_path, monkeypatch):
    channel, _ = _channel(tmp_path, monkeypatch)

    path = asyncio.run(
        channel._download_file(FILE_ID, suffix=".pdf", original_name="quarterly report.pdf")
    )

    assert Path(path).name == f"{FILE_ID}_quarterly report.pdf"


@pytest.mark.parametrize("raw", ["", "...", "  .  "])
def test_a_name_that_reduces_to_nothing_falls_back_to_the_generated_one(raw, tmp_path, monkeypatch):
    channel, _ = _channel(tmp_path, monkeypatch)

    path = asyncio.run(channel._download_file(FILE_ID, suffix=".mp4", original_name=raw))

    assert Path(path).parent == tmp_path
    assert Path(path).name == f"{FILE_ID}.mp4"
