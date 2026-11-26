import socket

import pytest

from channel.feishu import feishu_static_card


class FakeResponse:
    def __init__(self, status_code=200, headers=None, chunks=None):
        self.status_code = status_code
        self.headers = headers or {}
        self._chunks = chunks or []
        self.closed = False

    def iter_content(self, chunk_size=8192):
        yield from self._chunks

    def close(self):
        self.closed = True

    def json(self):
        return getattr(self, "json_body", {})


def test_remote_markdown_images_are_uploaded_once_and_replaced_with_image_keys():
    calls = []

    def upload(url):
        calls.append(url)
        return "img_v2_chart"

    markdown = (
        "Before\n![chart](https://cdn.example.com/chart.png)\n"
        "Again ![same](https://cdn.example.com/chart.png)"
    )

    result = feishu_static_card.resolve_markdown_images(markdown, upload)

    assert result == (
        "Before\n![chart](img_v2_chart)\nAgain ![same](img_v2_chart)"
    )
    assert calls == ["https://cdn.example.com/chart.png"]


def test_existing_feishu_image_keys_and_regular_links_are_untouched():
    def unexpected(_url):
        raise AssertionError("uploader should not be called")

    markdown = "![ready](img_v2_existing) [docs](https://example.com/docs)"

    assert feishu_static_card.resolve_markdown_images(markdown, unexpected) == markdown


@pytest.mark.parametrize("markdown, url, expected", [
    (
        "![plot](https://upload.wikimedia.org/a/Function_(mathematics).png) done",
        "https://upload.wikimedia.org/a/Function_(mathematics).png",
        "![plot](img_v2_plot) done",
    ),
    (
        "![plot](https://cdn.example.com/plot.png) (source)",
        "https://cdn.example.com/plot.png",
        "![plot](img_v2_plot) (source)",
    ),
])
def test_remote_image_url_may_contain_parentheses(markdown, url, expected):
    calls = []

    def upload(target):
        calls.append(target)
        return "img_v2_plot"

    assert feishu_static_card.resolve_markdown_images(markdown, upload) == expected
    assert calls == [url]


def test_failed_remote_image_upload_degrades_to_readable_alt_text():
    markdown = "Result: ![latency chart](https://cdn.example.com/chart.png)"

    result = feishu_static_card.resolve_markdown_images(markdown, lambda _url: None)

    assert result == "Result: [Image unavailable: latency chart]"


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/image.png",
        "http://169.254.169.254/latest/meta-data",
        "http://[::1]/image.png",
    ],
)
def test_public_image_guard_rejects_non_public_literal_addresses(url):
    with pytest.raises(ValueError, match="non-public"):
        feishu_static_card.validate_public_image_url(url)


def test_image_download_revalidates_redirect_targets(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))
        ],
    )
    redirect = FakeResponse(
        status_code=302,
        headers={"Location": "http://127.0.0.1/private.png"},
    )

    with pytest.raises(ValueError, match="non-public"):
        feishu_static_card.download_public_image(
            "https://example.com/image.png", get=lambda *args, **kwargs: redirect
        )

    assert redirect.closed is True


def test_image_download_enforces_content_type_and_size(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))
        ],
    )
    not_image = FakeResponse(
        headers={"Content-Type": "text/html"},
        chunks=[b"not an image"],
    )
    too_large = FakeResponse(
        headers={"Content-Type": "image/png", "Content-Length": "11"},
        chunks=[b"01234567890"],
    )

    with pytest.raises(ValueError, match="not an image"):
        feishu_static_card.download_public_image(
            "https://example.com/image.png", get=lambda *args, **kwargs: not_image
        )
    with pytest.raises(ValueError, match="too large"):
        feishu_static_card.download_public_image(
            "https://example.com/image.png",
            get=lambda *args, **kwargs: too_large,
            max_bytes=10,
        )


def test_public_image_is_uploaded_to_feishu_without_a_temp_file(monkeypatch):
    monkeypatch.setattr(
        feishu_static_card,
        "download_public_image",
        lambda _url: (b"png-bytes", "image/png"),
    )
    response = FakeResponse()
    response.json_body = {
        "code": 0,
        "data": {"image_key": "img_v2_uploaded"},
    }
    calls = []

    def post(url, **kwargs):
        calls.append((url, kwargs))
        return response

    image_key = feishu_static_card.upload_public_image_to_feishu(
        "https://example.com/image.png", "tenant-token", post=post
    )

    assert image_key == "img_v2_uploaded"
    assert calls[0][1]["headers"] == {"Authorization": "Bearer tenant-token"}
    filename, payload, content_type = calls[0][1]["files"]["image"]
    assert filename == "markdown-image.png"
    assert payload == b"png-bytes"
    assert content_type == "image/png"


@pytest.mark.parametrize(
    "markdown",
    [
        pytest.param(
            "Embed it like this:\n```markdown\n![logo](https://cdn.example.com/logo.png)\n```",
            id="backtick-fence",
        ),
        pytest.param(
            "~~~md\n![logo](https://cdn.example.com/logo.png)\n~~~",
            id="tilde-fence",
        ),
        pytest.param(
            "````md\n```\n![logo](https://cdn.example.com/logo.png)\n```\n````",
            id="longer-fence-around-a-shorter-one",
        ),
        pytest.param(
            "Write `![logo](https://cdn.example.com/logo.png)` in the README.",
            id="inline-code",
        ),
        pytest.param(
            "Use ``![a](https://cdn.example.com/a.png) and `x` `` here.",
            id="double-backtick-inline-code",
        ),
    ],
)
def test_images_inside_code_are_left_as_written(markdown):
    """A reply showing Markdown syntax must not have its example fetched,
    uploaded and swapped for an image key or "[Image unavailable: ...]"."""

    def unexpected(_url):
        raise AssertionError("uploader should not be called for code")

    assert feishu_static_card.resolve_markdown_images(markdown, unexpected) == markdown


def test_images_around_code_are_still_uploaded():
    calls = []

    def upload(url):
        calls.append(url)
        return "img_v2_key"

    markdown = (
        "![before](https://cdn.example.com/a.png)\n"
        "```\n![sample](https://cdn.example.com/sample.png)\n```\n"
        "Inline `![x](https://cdn.example.com/x.png)` then ![after](https://cdn.example.com/b.png)"
    )

    result = feishu_static_card.resolve_markdown_images(markdown, upload)

    assert result == (
        "![before](img_v2_key)\n"
        "```\n![sample](https://cdn.example.com/sample.png)\n```\n"
        "Inline `![x](https://cdn.example.com/x.png)` then ![after](img_v2_key)"
    )
    assert calls == ["https://cdn.example.com/a.png", "https://cdn.example.com/b.png"]
