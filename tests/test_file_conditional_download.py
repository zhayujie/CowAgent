"""A resumed download splices onto bytes already held, so the file has to prove it is
still the same file. Without an ETag a client cannot tell that, and both Chrome and the
mobile app go back to the first byte instead of finishing the transfer."""

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
    return app, url, media


def get(app, url, **headers):
    """Request with the given headers, named the way the server sees them."""
    env = {"HTTP_" + name.upper().replace("-", "_"): value for name, value in headers.items()}
    return app.request(url, env=env)


def test_etag_identifies_the_file_and_stays_the_same(file_app):
    app, url, _ = file_app
    first = get(app, url)
    second = get(app, url)
    etag = first.headers["ETag"]
    assert etag == second.headers["ETag"]
    # A weak tag may be compared by date rather than bytes, which is not enough to
    # splice a file together, so this one has to be strong.
    assert etag.startswith('"') and not etag.startswith("W/")
    assert first.headers["Accept-Ranges"] == "bytes"


def test_the_etag_follows_the_file_contents(file_app):
    app, url, media = file_app
    etag = get(app, url).headers["ETag"]
    media.write_bytes(BODY + b"tail")
    assert get(app, url).headers["ETag"] != etag


def test_unchanged_file_answers_304_without_a_body(file_app):
    app, url, _ = file_app
    etag = get(app, url).headers["ETag"]
    response = get(app, url, **{"If-None-Match": etag})
    assert response.status == "304 Not Modified"
    assert response.data == b""


def test_changed_file_is_sent_whole(file_app):
    app, url, media = file_app
    etag = get(app, url).headers["ETag"]
    media.write_bytes(BODY + b"tail")
    response = get(app, url, **{"If-None-Match": etag})
    assert response.status == "200 OK"
    assert response.data == BODY + b"tail"


def test_if_none_match_takes_a_list_and_ignores_weakness(file_app):
    app, url, _ = file_app
    etag = get(app, url).headers["ETag"]
    response = get(app, url, **{"If-None-Match": '"someone-else", W/' + etag})
    assert response.status == "304 Not Modified"


def test_a_matching_if_range_resumes(file_app):
    app, url, _ = file_app
    etag = get(app, url).headers["ETag"]
    response = get(app, url, **{"Range": "bytes=100-", "If-Range": etag})
    assert response.status == "206 Partial Content"
    assert response.data == BODY[100:]


def test_a_stale_if_range_gets_the_whole_file(file_app):
    app, url, _ = file_app
    response = get(app, url, **{"Range": "bytes=100-", "If-Range": '"from-an-older-version"'})
    # Sending only the tail here would splice two versions into one corrupted file.
    assert response.status == "200 OK"
    assert response.data == BODY


def test_a_weak_tag_never_matches_if_range(file_app):
    app, url, _ = file_app
    etag = get(app, url).headers["ETag"]
    response = get(app, url, **{"Range": "bytes=100-", "If-Range": "W/" + etag})
    assert response.status == "200 OK"


def test_if_range_accepts_the_last_modified_date(file_app):
    app, url, _ = file_app
    last_modified = get(app, url).headers["Last-Modified"]
    response = get(app, url, **{"Range": "bytes=100-", "If-Range": last_modified})
    assert response.status == "206 Partial Content"
    assert response.data == BODY[100:]


def test_if_modified_since_answers_304(file_app):
    app, url, _ = file_app
    last_modified = get(app, url).headers["Last-Modified"]
    response = get(app, url, **{"If-Modified-Since": last_modified})
    assert response.status == "304 Not Modified"


def test_a_range_without_condition_still_works(file_app):
    app, url, _ = file_app
    response = get(app, url, **{"Range": "bytes=100-"})
    assert response.status == "206 Partial Content"
    assert response.data == BODY[100:]
