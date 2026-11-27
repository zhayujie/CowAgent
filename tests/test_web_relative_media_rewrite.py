import os
from urllib.parse import quote

import pytest

from channel.web.core._common import _rewrite_relative_media


@pytest.fixture
def workspace(tmp_path):
    images = tmp_path / "images"
    images.mkdir()
    for name in ("chart.png", "Function_(mathematics).png"):
        (images / name).write_bytes(b"png")
    return os.path.realpath(tmp_path)


def _api_url(workspace, rel):
    return f"/api/file?path={quote(os.path.join(workspace, rel))}"


@pytest.mark.parametrize(
    "markdown, expected_rel",
    [
        ("![chart](images/chart.png) done", "images/chart.png"),
        ("![chart](images/chart.png) (source) done", "images/chart.png"),
        (
            "![plot](images/Function_(mathematics).png) done",
            "images/Function_(mathematics).png",
        ),
        (
            '![plot](images/Function_(mathematics).png "Plot") done',
            "images/Function_(mathematics).png",
        ),
    ],
)
def test_relative_markdown_images_are_rewritten(workspace, markdown, expected_rel):
    result = _rewrite_relative_media(markdown, workspace)

    assert _api_url(workspace, expected_rel) in result
    assert result.endswith(" done")
    assert ".png)" not in result.replace(_api_url(workspace, expected_rel), "")
