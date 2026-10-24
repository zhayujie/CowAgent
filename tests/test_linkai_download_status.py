# encoding:utf-8
"""_download_file must not save an HTTP error page as the requested file."""

import os
import sys
from unittest.mock import patch

import pytest
import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from models.linkai import link_ai_bot

URL = "https://files.example.com/report.pdf"


def _download(tmp_path, status_code, content):
    response = requests.Response()
    response.status_code = status_code
    response._content = content
    # The download is streamed now, so the response has to hand its body out
    # in chunks; a Response whose content was already read can do that.
    response._content_consumed = True
    with patch.object(link_ai_bot.state_dir, "tmp_dir", return_value=tmp_path), \
            patch.object(link_ai_bot.requests, "get", return_value=response):
        return link_ai_bot._download_file(URL)


@pytest.mark.parametrize("status_code", [403, 404])
def test_error_status_is_not_written(tmp_path, status_code):
    assert _download(tmp_path, status_code, b"<html>expired</html>") is None
    assert list(tmp_path.iterdir()) == []


def test_successful_download_is_written(tmp_path):
    result = _download(tmp_path, 200, b"%PDF-1.7")
    assert result == str(tmp_path / "report.pdf")
    assert (tmp_path / "report.pdf").read_bytes() == b"%PDF-1.7"
