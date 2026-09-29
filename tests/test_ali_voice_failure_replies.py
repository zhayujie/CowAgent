"""A failed Aliyun voice call has to answer the user, not disappear.

Every other provider in ``voice/`` turns a failure into ``Reply(ReplyType.ERROR,
...)`` -- azure, baidu, custom, dashscope, google, mimo, minimax, tencent,
xunfei and zhipuai all wrap their calls. Aliyun was the one that did not:
``textToVoice`` and ``voiceToText`` called straight through, so an exception
travelled to ``ChatChannel._fail_callback``, which only logs
(``channel/chat_channel.py:453``) and sends the user nothing at all. They even
already had the ERROR branch -- it was only reachable when the call returned
None, never when it raised.

The raise was easy to reach. ``get_valid_token`` parsed the token response with
a bare ``json.loads`` and indexed ``["Token"]["Id"]``, so a rejected key or an
exhausted quota -- which answer ``{"Message": ..., "Code": ...}`` with no Token
field -- raised KeyError, and a gateway error page raised JSONDecodeError. The
response body appeared nowhere, so a bad key was indistinguishable from an
outage.

``voice/ali/ali_api.py`` also left all three of its outbound calls unbounded
(two via requests, one HTTPSConnection); six of the nine files under ``voice/``
already pass a timeout.
"""
import ast
from pathlib import Path

from bridge.reply import ReplyType
from voice.ali import ali_voice

ALI_API = Path(ali_voice.__file__).resolve().parent / "ali_api.py"


def _voice():
    """Build an AliVoice without __init__: they only ship a
    config.json.template, so the real constructor disables itself."""
    voice = ali_voice.AliVoice.__new__(ali_voice.AliVoice)
    voice.token = None
    voice.token_expire_time = 0
    voice.api_url_voice_to_text = "https://example.invalid/asr"
    voice.api_url_text_to_voice = "https://example.invalid/tts"
    voice.app_key = "appkey"
    voice.access_key_id = "access-key-id"
    voice.access_key_secret = "access-key-secret"
    return voice


class _TokenStub:
    def __init__(self, payload):
        self.payload = payload

    def get_token(self):
        return self.payload


def _stub_token(monkeypatch, payload):
    monkeypatch.setattr(ali_voice, "AliyunTokenGenerator", lambda *a, **kw: _TokenStub(payload))


_GOOD_TOKEN = '{"Token": {"Id": "token-id", "ExpireTime": 9999999999}}'
_NO_TOKEN = '{"Message": "InvalidAccessKeyId.NotFound", "Code": "InvalidAccessKeyId.NotFound"}'


def test_a_token_response_without_a_token_field_becomes_an_error_reply(monkeypatch):
    """A rejected key answers with Message/Code and no Token -- KeyError before."""
    voice = _voice()
    _stub_token(monkeypatch, _NO_TOKEN)

    reply = voice.textToVoice("你好")

    assert reply.type == ReplyType.ERROR
    assert reply.content == "抱歉，语音合成失败"


def test_a_gateway_error_page_becomes_an_error_reply(monkeypatch):
    """Not JSON at all -- JSONDecodeError before."""
    voice = _voice()
    _stub_token(monkeypatch, "<html><body>502 Bad Gateway</body></html>")

    reply = voice.textToVoice("你好")

    assert reply.type == ReplyType.ERROR


def test_a_failing_synthesis_call_becomes_an_error_reply(monkeypatch):
    voice = _voice()
    _stub_token(monkeypatch, _GOOD_TOKEN)

    def boom(*args, **kwargs):
        raise ConnectionError("connection reset by peer")

    monkeypatch.setattr(ali_voice, "text_to_speech_aliyun", boom)

    reply = voice.textToVoice("你好")

    assert reply.type == ReplyType.ERROR


def test_a_bad_token_response_also_becomes_an_error_reply_when_recognising(monkeypatch):
    voice = _voice()
    _stub_token(monkeypatch, _NO_TOKEN)
    monkeypatch.setattr(ali_voice, "get_pcm_from_wav", lambda path: b"pcm", raising=False)

    reply = voice.voiceToText("voice.wav")

    assert reply.type == ReplyType.ERROR
    assert reply.content == "抱歉，语音识别失败"


def test_a_successful_synthesis_still_returns_a_voice_reply(monkeypatch):
    """The control: the guard must not swallow the working path."""
    voice = _voice()
    _stub_token(monkeypatch, _GOOD_TOKEN)
    monkeypatch.setattr(ali_voice, "text_to_speech_aliyun", lambda *a, **kw: "/tmp/reply.wav")

    reply = voice.textToVoice("你好")

    assert reply.type == ReplyType.VOICE
    assert reply.content == "/tmp/reply.wav"


def test_a_cached_token_is_reused_without_a_second_lookup(monkeypatch):
    """The control for the token guard: a live cached token must not be refetched
    -- and must not be invalidated by the new exception handling."""
    voice = _voice()
    _stub_token(monkeypatch, _GOOD_TOKEN)
    monkeypatch.setattr(ali_voice, "text_to_speech_aliyun", lambda *a, **kw: "/tmp/reply.wav")

    first = voice.textToVoice("你好")
    calls = []
    monkeypatch.setattr(
        ali_voice, "AliyunTokenGenerator",
        lambda *a, **kw: calls.append(1) or _TokenStub(_GOOD_TOKEN),
    )
    second = voice.textToVoice("你好")

    assert first.type == ReplyType.VOICE and second.type == ReplyType.VOICE
    assert calls == []


def _outbound_calls():
    """Every outbound call this module makes, as (node, label).

    ``requests.<verb>`` and ``http.client.HTTPSConnection`` are the two ways
    out. The connection carries the timeout, not the ``conn.request`` that
    follows it, so only the constructor is checked."""
    tree = ast.parse(ALI_API.read_text(encoding="utf-8"), filename=str(ALI_API))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        called = node.func
        if not isinstance(called, ast.Attribute):
            continue
        if called.attr == "HTTPSConnection":
            # http.client.HTTPSConnection(...) -- an attribute chain, so the
            # name check below cannot see it.
            label = "http.client.HTTPSConnection"
        elif (isinstance(called.value, ast.Name) and called.value.id == "requests"
                and called.attr in ("post", "get", "request")):
            label = "requests.{}".format(called.attr)
        else:
            continue
        yield node, label


def test_every_outbound_call_in_ali_api_is_bounded():
    """requests and http.client both default to waiting forever."""
    unbounded = [
        f"line {node.lineno}: {name}(...)"
        for node, name in _outbound_calls()
        if not any(keyword.arg == "timeout" for keyword in node.keywords)
    ]

    assert unbounded == []


def test_the_scan_actually_finds_the_calls():
    """Without this, a renamed import would make the test above pass vacuously."""
    found = list(_outbound_calls())

    assert len(found) == 3
