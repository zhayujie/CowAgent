"""Files that can run scripts must not run them as the console's origin."""

from urllib.parse import urlencode

import pytest
import web

from channel.web.api import files


@pytest.fixture
def serve(tmp_path, monkeypatch):
    monkeypatch.setattr(files, "_require_auth", lambda: None)
    monkeypatch.setattr(files, "_is_path_allowed", lambda path: path.startswith(str(tmp_path)))
    app = web.application(("/api/file", "FileServeHandler"), vars(files))

    def get(name, body=b"x", **query):
        path = tmp_path / name
        path.write_bytes(body)
        return app.request("/api/file?" + urlencode({"path": str(path), **query}))

    return get


def test_svg_gets_a_scriptless_sandbox(serve):
    response = serve("chart.svg", b"<svg xmlns='http://www.w3.org/2000/svg'><script>1</script></svg>")
    assert response.headers.get("Content-Security-Policy") == "sandbox"
    assert response.headers.get("X-Content-Type-Options") == "nosniff"


def test_xhtml_gets_a_scriptless_sandbox(serve):
    response = serve("page.xhtml")
    assert response.headers.get("Content-Security-Policy") == "sandbox"


def test_html_keeps_scripts_in_an_opaque_origin(serve):
    response = serve("page.html")
    assert response.headers.get("Content-Security-Policy") == files._PAGE_SANDBOX


def test_html_opened_with_a_url_token_gets_no_scripts(serve):
    response = serve("page.html", token="abc")
    assert response.headers.get("Content-Security-Policy") == "sandbox"


def test_media_is_left_alone(serve):
    for name in ("photo.png", "clip.mp4", "doc.pdf", "notes.txt"):
        response = serve(name)
        assert "Content-Security-Policy" not in response.headers, name
