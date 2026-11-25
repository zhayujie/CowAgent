"""The send tool's public copy is reused for the same content.

Sending a file again must not leave another copy behind, an edited file must
get its own copy so earlier links keep what they pointed at, and a file that is
already in websites/ is linked where it is.
"""

import os
import subprocess
import sys

import pytest

from common import publish

BASE = "https://example.test/dep"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture
def publish_dir(tmp_path, monkeypatch):
    pub = tmp_path / "websites"
    pub.mkdir()
    monkeypatch.setattr(publish, "get_publish_base_url", lambda workspace_dir="": BASE)
    monkeypatch.setattr(publish, "get_publish_dir", lambda workspace_dir="", ensure=False: str(pub))
    return pub


def _copies(pub):
    send_dir = pub / publish.COW_SEND_WEB_SUBDIR
    return sorted(p.name for p in send_dir.iterdir()) if send_dir.exists() else []


def test_sending_the_same_file_again_reuses_its_copy(tmp_path, publish_dir):
    src = tmp_path / "report.PDF"
    src.write_bytes(b"v1")

    first = publish.copy_send_file(str(src), str(tmp_path))
    second = publish.copy_send_file(str(src), str(tmp_path))

    assert first == second
    assert first.startswith(f"{BASE}/{publish.COW_SEND_WEB_SUBDIR}/")
    assert first.endswith(".pdf")
    assert len(_copies(publish_dir)) == 1


def test_an_edited_file_gets_a_new_copy_and_the_old_one_stays(tmp_path, publish_dir):
    src = tmp_path / "report.pdf"
    src.write_bytes(b"v1")
    first = publish.copy_send_file(str(src), str(tmp_path))
    src.write_bytes(b"v2")
    second = publish.copy_send_file(str(src), str(tmp_path))

    assert first != second
    old = publish_dir / publish.COW_SEND_WEB_SUBDIR / first.rsplit("/", 1)[1]
    assert old.read_bytes() == b"v1"
    assert len(_copies(publish_dir)) == 2


def test_a_file_in_websites_is_linked_in_place(tmp_path, publish_dir):
    page = publish_dir / "game" / "a b.html"
    page.parent.mkdir()
    page.write_text("x")

    assert publish.copy_send_file(str(page), str(tmp_path)) == f"{BASE}/game/a%20b.html"
    assert _copies(publish_dir) == []


def test_nothing_is_copied_without_a_public_route(tmp_path, monkeypatch):
    monkeypatch.setattr(publish, "get_publish_base_url", lambda workspace_dir="": "")
    src = tmp_path / "report.pdf"
    src.write_bytes(b"v1")

    assert publish.copy_send_file(str(src), str(tmp_path)) == ""
    assert os.listdir(tmp_path) == ["report.pdf"]


def test_a_configured_base_url_is_the_route(monkeypatch):
    from config import conf

    monkeypatch.setattr(publish, "_base_url_fallback", None)
    monkeypatch.setitem(conf(), "websites_base_url", "")
    assert publish._base_url() == ""

    monkeypatch.setitem(conf(), "websites_base_url", "https://files.example.com/")
    assert publish._base_url() == "https://files.example.com"

    monkeypatch.setitem(conf(), "websites_base_url", "files.example.com")
    assert publish._base_url() == ""


def test_the_fallback_answers_only_when_no_base_url_is_configured(monkeypatch):
    from config import conf

    monkeypatch.setattr(publish, "_base_url_fallback", lambda: "https://fallback.example.com/dep")
    monkeypatch.setitem(conf(), "websites_base_url", "")
    assert publish._base_url() == "https://fallback.example.com/dep"

    monkeypatch.setitem(conf(), "websites_base_url", "https://files.example.com")
    assert publish._base_url() == "https://files.example.com"


def _web_send_payloads(data):
    from types import SimpleNamespace

    from channel.web.web_channel import WebChannel

    sent = []
    channel = SimpleNamespace(
        sse_streams={"req": object()},
        _publish_sse_event=lambda request_id, item: sent.append(item),
    )
    WebChannel.__wrapped__._make_sse_callback(channel, "req")({"type": "file_to_send", "data": data})
    return sent


def test_the_web_console_keeps_the_card_for_a_local_file_with_a_public_link(tmp_path):
    page = tmp_path / "websites" / "page.html"
    page.parent.mkdir()
    page.write_text("x")
    link = f"{BASE}/page.html"

    [payload] = _web_send_payloads({
        "type": "file_to_send", "path": str(page), "file_name": "page.html", "file_type": "document",
        "url": link, "rel_path": "websites/page.html", "kind": "html", "previewable": True, "size": 1,
    })

    assert payload["content"].startswith("/api/file?path=")
    assert payload["abs_path"] == str(page)
    assert (payload["rel_path"], payload["kind"]) == ("websites/page.html", "html")
    assert payload["public_url"] == link


def test_the_web_console_passes_a_remote_file_through(tmp_path):
    remote = "https://files.example.com/report.pdf"

    [payload] = _web_send_payloads({
        "type": "file_to_send", "path": remote, "file_name": "report.pdf", "file_type": "document", "url": remote,
    })

    assert payload["content"] == remote
    assert "abs_path" not in payload and "public_url" not in payload


def test_the_prompt_rules_need_no_optional_packages(tmp_path):
    # Blocking the import makes it fail the way it does where the package is not installed.
    code = (
        "import sys; sys.modules['linkai'] = None\n"
        "from config import conf\n"
        "conf()['websites_base_url'] = 'https://files.example.com'\n"
        "from agent.prompt.builder import _build_publish_section\n"
        "lines = _build_publish_section(sys.argv[1])\n"
        "assert any('https://files.example.com' in line for line in lines), lines\n"
    )
    env = dict(os.environ, COW_DATA_DIR=str(tmp_path))
    result = subprocess.run(
        [sys.executable, "-c", code, str(tmp_path)],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stderr[-2000:]
