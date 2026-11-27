from unittest.mock import Mock
import pytest
from models.openai.open_ai_image import OpenAIImage
from models.openai.openai_http_client import OpenAIHTTPError
from models.openai.openai_compat import RateLimitError
from tests.sleep_stub import stub_sleep


@pytest.mark.parametrize("failure", [OpenAIHTTPError(429, "rate limited"), RateLimitError("rate limited")])
def test_image_retry_preserves_explicit_endpoint(monkeypatch, failure):
    bot = OpenAIImage.__new__(OpenAIImage)
    client = Mock()
    client.images_generate.side_effect = [failure, {"data": [{"url": "https://image.invalid/result"}]}]
    bot._image_client = client
    monkeypatch.setattr("models.openai.open_ai_image.conf", lambda: {})
    stub_sleep(monkeypatch)
    ok, url = bot.create_img("draw", api_key="test-override", api_base="https://provider.invalid/v1")
    assert ok
    assert url == "https://image.invalid/result"
    assert len(client.images_generate.call_args_list) == 2
    for call in client.images_generate.call_args_list:
        assert call.kwargs["api_key"] == "test-override"
        assert call.kwargs["api_base"] == "https://provider.invalid/v1"
