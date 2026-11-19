# encoding: utf-8
"""DingTalk upload_media() must cap remote downloads (cf. #3300, Feishu).

It used a bare requests.get + f.write, so an oversized URL filled memory/disk.
Pin it to the shared download_to_file helper -- and, a download being this
call's to make, to cleaning it up again on every way out, the way the
weixin / wecom_bot senders do. The voice send converts the TTS output to amr
beside it; that amr is transient too, including the half-written one a failed
conversion leaves behind.
"""
from bridge.reply import Reply, ReplyType
from tests.test_dingtalk_streaming_cards import _bare_channel, _context


class FakeResp:
    def __init__(self, content=b"", headers=None, json_data=None, status=200):
        self.content = content
        self.headers = headers or {}
        self._json = json_data or {}
        self.status_code = status
        self.closed = False

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError("HTTP %s" % self.status_code)

    def json(self):
        return self._json

    def iter_content(self, chunk_size):
        data = self.content
        step = chunk_size or 1
        for i in range(0, len(data), step):
            yield data[i:i + step]

    def close(self):
        self.closed = True


class _FakeReq:
    def __init__(self, get, post):
        self._get = get
        self._post = post

    def get(self, *a, **k):
        return self._get(*a, **k)

    def post(self, *a, **k):
        return self._post(*a, **k)


def _channel():
    ch = _bare_channel()
    ch.get_access_token = lambda: "tok"
    return ch


def _stub(monkeypatch, get_resp, post_resp, tmp_path):
    from channel.dingtalk import dingtalk_channel as mod
    from common import media_download as md

    fake = _FakeReq(lambda *a, **k: get_resp, lambda *a, **k: post_resp)
    monkeypatch.setattr(mod, "requests", fake)
    monkeypatch.setattr(md, "requests", fake)
    monkeypatch.setattr(
        "channel.dingtalk.dingtalk_channel.state_dir.tmp_dir",
        lambda *a, **k: str(tmp_path),
    )


def test_http_url_within_limit_returns_media_id(monkeypatch, tmp_path):
    get = FakeResp(content=b"<media data>", headers={"Content-Length": "20"})
    post = FakeResp(json_data={"errcode": 0, "media_id": "mid-1"})
    _stub(monkeypatch, get, post, tmp_path)
    assert _channel().upload_media("https://cdn.example/ok.mp4", "video") == "mid-1"


def test_http_url_over_size_limit_rejected(monkeypatch, tmp_path):
    from common.media_download import MAX_FILE_BYTES

    get = FakeResp(headers={"Content-Length": str(MAX_FILE_BYTES + 1)})
    post = FakeResp(json_data={"errcode": 0, "media_id": "mid-1"})
    _stub(monkeypatch, get, post, tmp_path)
    assert _channel().upload_media("https://evil.example/huge.bin", "file") is None


def test_http_url_query_string_stays_out_of_the_file_name(monkeypatch, tmp_path):
    from channel.dingtalk import dingtalk_channel as mod

    get = FakeResp(content=b"<media data>")
    post = FakeResp(json_data={"errcode": 0, "media_id": "mid-3"})
    _stub(monkeypatch, get, post, tmp_path)
    real_download = mod.download_to_file
    seen = {}

    def recording_download(url, path, *a, **k):
        seen["path"] = path
        return real_download(url, path, *a, **k)

    monkeypatch.setattr(mod, "download_to_file", recording_download)
    url = "https://cdn.example/dir/%E6%8A%A5%E5%91%8A.pdf?token=secret&x=a/b"
    assert _channel().upload_media(url, "file") == "mid-3"
    # The download target is a generated unique name, so nothing from the URL
    # -- query string included -- ever becomes part of a path.
    assert "?" not in seen["path"]
    assert "token" not in seen["path"]
    assert "secret" not in seen["path"]
    # A download belongs to this call: nothing is left in the tmp dir.
    assert [p.name for p in tmp_path.iterdir()] == []


def test_local_file_url_still_uploaded(monkeypatch, tmp_path):
    local = tmp_path / "clip.mp4"
    local.write_bytes(b"<media data>")
    post = FakeResp(json_data={"errcode": 0, "media_id": "mid-2"})
    _stub(monkeypatch, FakeResp(), post, tmp_path)
    assert _channel().upload_media("file://" + str(local), "video") == "mid-2"


def test_http_url_download_is_guarded(monkeypatch, tmp_path):
    from channel.dingtalk import dingtalk_channel as mod

    seen = {}

    def download_to_file(url, path, max_bytes, **kwargs):
        seen.update(kwargs)
        raise mod.MediaTooLargeError("stop")

    _stub(monkeypatch, FakeResp(), FakeResp(), tmp_path)
    monkeypatch.setattr(mod, "download_to_file", download_to_file)
    assert _channel().upload_media("https://cdn.example/a.pdf", "file") is None
    assert seen.get("guarded") is True


def test_http_url_download_is_cleaned_up_when_the_upload_fails(monkeypatch, tmp_path):
    get = FakeResp(content=b"<media data>")
    post = FakeResp(json_data={"errcode": 40001, "errmsg": "invalid token"})
    _stub(monkeypatch, get, post, tmp_path)
    assert _channel().upload_media("https://cdn.example/ok.mp4", "video") is None
    assert [p.name for p in tmp_path.iterdir()] == []


def test_voice_amr_is_cleaned_up_after_the_send(monkeypatch, tmp_path):
    from voice import audio_convert

    voice = tmp_path / "tts.mp3"
    voice.write_bytes(b"<mp3 data>")
    amr = tmp_path / "tts.amr"

    def fake_convert(src, dst):
        # pydub opens the target, then spawns ffmpeg into it.
        with open(dst, "wb") as f:
            f.write(b"#!AMR\n")
        return 1.5

    monkeypatch.setattr(audio_convert, "any_to_amr", fake_convert)
    _stub(monkeypatch, FakeResp(), FakeResp(json_data={"errcode": 0, "media_id": "mid-v"}), tmp_path)
    ch = _channel()
    ch._send_file_message = lambda *a, **k: True
    ch.reply_text = lambda *a, **k: None
    ch.send(Reply(ReplyType.VOICE, str(voice)), _context())

    assert not amr.exists()
    # The TTS source belongs to voice synthesis, not to this send.
    assert [p.name for p in tmp_path.iterdir()] == ["tts.mp3"]


def test_voice_amr_is_cleaned_up_when_the_conversion_fails(monkeypatch, tmp_path):
    from voice import audio_convert

    voice = tmp_path / "tts.mp3"
    voice.write_bytes(b"<mp3 data>")
    amr = tmp_path / "tts.amr"

    def failing_convert(src, dst):
        # pydub opens the target before it spawns ffmpeg: a conversion that
        # dies partway still leaves a half-written amr behind.
        with open(dst, "wb") as f:
            f.write(b"#!AMR\nhalf")
        raise RuntimeError("ffmpeg died")

    monkeypatch.setattr(audio_convert, "any_to_amr", failing_convert)
    _stub(monkeypatch, FakeResp(), FakeResp(), tmp_path)
    ch = _channel()
    ch._send_file_message = lambda *a, **k: True
    texts = []
    ch.reply_text = lambda content, incoming: texts.append(content)
    ch.send(Reply(ReplyType.VOICE, str(voice)), _context())

    assert not amr.exists()
    assert texts == ["抱歉，语音转码失败"]
    assert [p.name for p in tmp_path.iterdir()] == ["tts.mp3"]
