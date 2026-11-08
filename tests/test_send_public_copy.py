"""The send tool's public copy is reused for the same content.

Sending a file again must not leave another copy behind, an edited file must
get its own copy so earlier links keep what they pointed at, and a file that is
already published is linked where it is.
"""

import os
import sys
import types

import pytest


if "linkai" not in sys.modules:
    _stub = types.ModuleType("linkai")

    class _LinkAIClient:
        def __init__(self, *a, **k):
            pass

    class _PushMsg:
        pass

    _stub.LinkAIClient = _LinkAIClient
    _stub.PushMsg = _PushMsg
    sys.modules["linkai"] = _stub

from common import cloud_client  # noqa: E402

BASE = "https://example.test/dep"


@pytest.fixture
def publish_dir(tmp_path, monkeypatch):
    pub = tmp_path / "websites"
    pub.mkdir()
    monkeypatch.setattr(cloud_client, "get_website_base_url", lambda workspace_dir="": BASE)
    monkeypatch.setattr(cloud_client, "get_publish_dir", lambda workspace_dir="", ensure=False: str(pub))
    return pub


def _copies(pub):
    send_dir = pub / cloud_client.COW_SEND_WEB_SUBDIR
    return sorted(p.name for p in send_dir.iterdir()) if send_dir.exists() else []


def test_sending_the_same_file_again_reuses_its_copy(tmp_path, publish_dir):
    src = tmp_path / "report.PDF"
    src.write_bytes(b"v1")

    first = cloud_client.copy_send_file(str(src), str(tmp_path))
    second = cloud_client.copy_send_file(str(src), str(tmp_path))

    assert first == second
    assert first.startswith(f"{BASE}/{cloud_client.COW_SEND_WEB_SUBDIR}/")
    assert first.endswith(".pdf")
    assert len(_copies(publish_dir)) == 1


def test_an_edited_file_gets_a_new_copy_and_the_old_one_stays(tmp_path, publish_dir):
    src = tmp_path / "report.pdf"
    src.write_bytes(b"v1")
    first = cloud_client.copy_send_file(str(src), str(tmp_path))
    src.write_bytes(b"v2")
    second = cloud_client.copy_send_file(str(src), str(tmp_path))

    assert first != second
    old = publish_dir / cloud_client.COW_SEND_WEB_SUBDIR / first.rsplit("/", 1)[1]
    assert old.read_bytes() == b"v1"
    assert len(_copies(publish_dir)) == 2


def test_a_published_file_is_linked_in_place(tmp_path, publish_dir):
    page = publish_dir / "game" / "a b.html"
    page.parent.mkdir()
    page.write_text("x")

    assert cloud_client.copy_send_file(str(page), str(tmp_path)) == f"{BASE}/game/a%20b.html"
    assert _copies(publish_dir) == []


def test_nothing_is_copied_without_a_public_route(tmp_path, monkeypatch):
    monkeypatch.setattr(cloud_client, "get_website_base_url", lambda workspace_dir="": "")
    src = tmp_path / "report.pdf"
    src.write_bytes(b"v1")

    assert cloud_client.copy_send_file(str(src), str(tmp_path)) == ""
    assert os.listdir(tmp_path) == ["report.pdf"]
