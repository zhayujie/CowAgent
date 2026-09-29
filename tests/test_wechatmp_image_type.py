"""The wechatmp channel must load on every interpreter the project supports.

``imghdr`` was removed from the standard library in Python 3.13 (PEP 594) while
this project keeps ``requires-python = ">=3.7"``, the v2.1.1 release notes
advertise "Python 3.13 support" and the CI matrix runs pytest on 3.13. It was
imported by ``channel/wechatmp/wechatmp_channel.py``, which
``channel/channel_factory.py`` imports to build ``WechatMPChannel`` -- so on
3.13 that channel could not be constructed at all. Nothing in the suite imported
it, so the breakage never showed up as a red run.
"""

import ast
from collections import defaultdict
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from bridge.reply import Reply, ReplyType
from channel.wechatmp.wechatmp_channel import WechatMPChannel

CHANNEL_CLS = WechatMPChannel.__wrapped__
REPO_ROOT = Path(__file__).resolve().parent.parent

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 8
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 8
GIF = b"GIF89a" + b"\x00" * 8
BMP = b"BM" + b"\x00" * 8
WEBP = b"RIFF" + b"\x0c\x00\x00\x00" + b"WEBP" + b"\x00" * 4

# PEP 594 removed these from the standard library in Python 3.13.
REMOVED_IN_313 = {
    "aifc", "asynchat", "asyncore", "audioop", "cgi", "cgitb", "chunk", "crypt",
    "imghdr", "imp", "mailcap", "msilib", "nis", "nntplib", "ossaudiodev",
    "pipes", "smtpd", "sndhdr", "spwd", "sunau", "telnetlib", "uu", "xdrlib",
}


@pytest.fixture
def channel():
    """The passive-reply send path, without the constructor's HTTP server."""
    ch = CHANNEL_CLS.__new__(CHANNEL_CLS)
    ch.passive_reply = True
    ch.cache_dict = defaultdict(list)
    ch.client = Mock()
    ch.client.material.add.return_value = {"media_id": "MEDIA-1"}
    return ch


def _send_local_image(channel, payload, tmp_path):
    image = tmp_path / "pic.bin"
    image.write_bytes(payload)
    channel.send(
        Reply(ReplyType.IMAGE_URL, str(image)),
        {"receiver": "u1", "msg": SimpleNamespace(msg_id="m1")},
    )
    _, payload_tuple = channel.client.material.add.call_args.args
    return payload_tuple


@pytest.mark.parametrize(
    "payload,expected", [(PNG, "png"), (JPEG, "jpeg"), (GIF, "gif"), (BMP, "bmp"), (WEBP, "webp")]
)
def test_an_image_is_uploaded_with_the_type_imghdr_used_to_report(channel, tmp_path, payload, expected):
    filename, stream, content_type = _send_local_image(channel, payload, tmp_path)

    assert filename == "u1-m1." + expected
    assert content_type == "image/" + expected
    assert stream.tell() == 0, "detection must leave the stream where the caller left it"
    assert stream.read() == payload, "the upload must still receive the whole file"


def test_an_unrecognised_payload_does_not_raise_before_the_upload(channel, tmp_path):
    """``imghdr.what`` returned None, and ``"." + None`` raised TypeError inside
    ``send`` before the upload was even attempted."""
    filename, _stream, content_type = _send_local_image(channel, b"definitely not an image", tmp_path)

    assert filename == "u1-m1.png"
    assert content_type == "image/png"


def test_no_repo_module_imports_a_stdlib_module_removed_in_313():
    """The project advertises 3.13 support, so keep those names out of the tree."""
    offenders = {}
    for source in REPO_ROOT.rglob("*.py"):
        if any(part in {".git", "venv", ".venv", "__pycache__", "node_modules"} for part in source.parts):
            continue
        tree = ast.parse(source.read_text(encoding="utf-8", errors="ignore"))
        found = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                found |= {alias.name.split(".")[0] for alias in node.names} & REMOVED_IN_313
            elif isinstance(node, ast.ImportFrom) and node.module:
                found |= {node.module.split(".")[0]} & REMOVED_IN_313
        if found:
            offenders[str(source.relative_to(REPO_ROOT))] = sorted(found)
    assert offenders == {}
