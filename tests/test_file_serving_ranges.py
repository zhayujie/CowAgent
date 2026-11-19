"""Media players seek with Range requests; file routes must answer them with 206."""

from urllib.parse import urlencode

import pytest
import web

from channel.web.api import files

BODY = bytes(range(256)) * 4


@pytest.fixture
def file_app(tmp_path, monkeypatch):
    media = tmp_path / "clip.mp4"
    media.write_bytes(BODY)
    monkeypatch.setattr(files, "_require_auth", lambda: None)
    monkeypatch.setattr(files, "_is_path_allowed", lambda path: path == str(media))
    app = web.application(("/api/file", "FileServeHandler"), vars(files))
    url = "/api/file?" + urlencode({"path": str(media)})
    return app, url


def get(app, url, range_header=None):
    env = {"HTTP_RANGE": range_header} if range_header else {}
    return app.request(url, env=env)


def test_plain_request_gets_whole_file_and_advertises_ranges(file_app):
    app, url = file_app
    response = get(app, url)
    assert response.status == "200 OK"
    assert response.data == BODY
    assert response.headers["Accept-Ranges"] == "bytes"


def test_bounded_range(file_app):
    app, url = file_app
    response = get(app, url, "bytes=10-19")
    assert response.status == "206 Partial Content"
    assert response.data == BODY[10:20]
    assert response.headers["Content-Range"] == f"bytes 10-19/{len(BODY)}"
    assert response.headers["Content-Length"] == "10"


def test_open_ended_range_runs_to_the_end(file_app):
    app, url = file_app
    response = get(app, url, "bytes=1000-")
    assert response.status == "206 Partial Content"
    assert response.data == BODY[1000:]


def test_suffix_range_reads_the_tail(file_app):
    app, url = file_app
    response = get(app, url, "bytes=-24")
    assert response.status == "206 Partial Content"
    assert response.data == BODY[-24:]
    assert response.headers["Content-Range"] == f"bytes {len(BODY) - 24}-{len(BODY) - 1}/{len(BODY)}"


def test_range_past_the_end_is_clamped(file_app):
    app, url = file_app
    response = get(app, url, "bytes=1020-5000")
    assert response.status == "206 Partial Content"
    assert response.data == BODY[1020:]


def test_unsatisfiable_range(file_app):
    app, url = file_app
    response = get(app, url, f"bytes={len(BODY)}-")
    assert response.status == "416 Range Not Satisfiable"
    assert response.headers["Content-Range"] == f"bytes */{len(BODY)}"


def test_multi_range_falls_back_to_whole_file(file_app):
    app, url = file_app
    response = get(app, url, "bytes=0-1,4-5")
    assert response.status == "200 OK"
    assert response.data == BODY
