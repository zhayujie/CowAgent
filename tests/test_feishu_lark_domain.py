"""Platform discovery must use the WS endpoint: both token origins can succeed."""
from unittest.mock import MagicMock, Mock, patch

from channel.feishu.domain import FEISHU_DOMAIN, LARK_DOMAIN
from channel.feishu.feishu_channel import FeiShuChanel
from channel.feishu.feishu_message import _download_resource
from channel.feishu.feishu_static_card import upload_public_image_to_feishu


def _channel():
    channel = FeiShuChanel.__wrapped__.__new__(FeiShuChanel.__wrapped__)
    channel.feishu_app_id = "cli_test"
    channel.feishu_app_secret = "secret"
    channel.feishu_domain = FEISHU_DOMAIN
    return channel


def _response(payload):
    return Mock(status_code=200, json=Mock(return_value=payload))


def test_lark_discovery_even_when_domestic_token_succeeds():
    channel = _channel()
    with patch("channel.feishu.feishu_channel.requests.post", side_effect=[
        _response({"code": 0, "tenant_access_token": "shared-token"}),
        _response({"code": 1000040351}),
        _response({"code": 0}),
        _response({"code": 0, "tenant_access_token": "lark-token"}),
    ]) as post:
        assert channel.fetch_access_token() == "shared-token"
        channel._detect_platform()
        assert channel.feishu_domain == LARK_DOMAIN
        assert channel.fetch_access_token() == "lark-token"
    assert post.call_args.kwargs["url"].startswith(LARK_DOMAIN)


def test_domestic_discovery_does_not_probe_lark():
    channel = _channel()
    with patch("channel.feishu.feishu_channel.requests.post", return_value=_response({"code": 0})) as post:
        channel._detect_platform()
    assert channel.feishu_domain == FEISHU_DOMAIN
    assert post.call_count == 1


def test_permission_error_does_not_switch_platform():
    channel = _channel()
    with patch("channel.feishu.feishu_channel.requests.post", return_value=_response({"code": 99991663})) as post:
        channel._detect_platform()
    assert channel.feishu_domain == FEISHU_DOMAIN
    assert post.call_count == 1


def test_platform_is_per_instance():
    domestic, international = _channel(), _channel()
    with patch("channel.feishu.feishu_channel.requests.post", side_effect=[
        _response({"code": 1000040351}), _response({"code": 0}),
    ]):
        international._detect_platform()
    assert domestic.feishu_domain == FEISHU_DOMAIN
    assert international.feishu_domain == LARK_DOMAIN


def _run_ws(outcomes):
    channel = _channel()
    channel._ws_stop_event = Mock()
    channel._ws_stop_event.wait.return_value = True
    channel.report_startup_error = Mock()
    channel._fetch_bot_open_id = Mock()
    domains = []
    script = list(outcomes)

    class FakeClient:
        def __init__(self, *args, **kwargs):
            domains.append(kwargs["domain"])

        def start(self):
            outcome = script.pop(0)
            if outcome:
                raise outcome

    with patch("channel.feishu.feishu_channel._ensure_lark_imported"), patch(
        "channel.feishu.feishu_channel.lark", MagicMock()
    ), patch("channel.feishu.feishu_channel._new_lark_ws_client_module", return_value=Mock(Client=FakeClient)):
        channel._startup_websocket()
    return channel, domains


def test_websocket_domain_mismatch_retries_without_backoff():
    channel, domains = _run_ws([RuntimeError("1000040351: Incorrect domain name"), None])
    assert domains == [FEISHU_DOMAIN, LARK_DOMAIN]
    channel._ws_stop_event.wait.assert_not_called()
    channel.report_startup_error.assert_not_called()


def test_websocket_domain_mismatch_does_not_ping_pong():
    error = RuntimeError("1000040351: Incorrect domain name")
    channel, domains = _run_ws([error, error])
    assert domains == [FEISHU_DOMAIN, LARK_DOMAIN]
    channel._ws_stop_event.wait.assert_called_once_with(timeout=5)


def test_resource_download_uses_detected_lark_domain():
    with patch("channel.feishu.feishu_message.download_to_file") as download:
        assert _download_resource("m1", "key", "file", "token", "path", 100, domain=LARK_DOMAIN)
    assert download.call_args.args[0] == LARK_DOMAIN + "/open-apis/im/v1/messages/m1/resources/key"


def test_markdown_image_upload_uses_detected_lark_domain():
    post = Mock(return_value=_response({"code": 0, "data": {"image_key": "img_test"}}))
    with patch("channel.feishu.feishu_static_card.download_public_image", return_value=(b"image", "image/png")):
        assert upload_public_image_to_feishu("https://example.com/image", "token", post=post, domain=LARK_DOMAIN) == "img_test"
    assert post.call_args.args[0] == LARK_DOMAIN + "/open-apis/im/v1/images"
