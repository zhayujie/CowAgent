"""Inbound files with the same display name must retain independent bytes."""

from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import re
import threading
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

from Crypto.Cipher import AES
from Crypto.Util.Padding import pad
import pytest

from channel import file_cache
from channel.file_cache import FileCache
from channel.weixin import weixin_message as messages
from common.expired_dict import ExpiredDict


KEY = bytes(range(16))  # Synthetic fixture key, no account credentials.
PAYLOADS = {"first": b"first report contents", "second": b"second report contents"}


@pytest.fixture
def cdn(tmp_path, monkeypatch):
    monkeypatch.setattr(messages, "_get_tmp_dir", lambda: str(tmp_path))
    class Requests(list):
        barrier = None

    requests = Requests()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            token = parse_qs(urlparse(self.path).query)["encrypted_query_param"][0]
            requests.append(token)
            if requests.barrier:
                requests.barrier.wait(timeout=5)
            if token not in PAYLOADS:
                self.send_error(404)
                return
            body = AES.new(KEY, AES.MODE_ECB).encrypt(pad(PAYLOADS[token], AES.block_size))
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def raw_file(token, name="report.txt", msg_id=None, text=None):
    items = [{"type": messages.ITEM_FILE, "file_item": {
        "file_name": name,
        "media": {"encrypt_query_param": token, "aes_key": KEY.hex()},
    }}]
    if text is not None:
        items.insert(0, {"type": messages.ITEM_TEXT, "text_item": {"text": text}})
    return {"message_type": 1, "message_id": msg_id or token,
            "from_user_id": "fixture-user", "to_user_id": "fixture-bot", "item_list": items}


def downloaded(base, token, **kwargs):
    msg = messages.WeixinMessage(raw_file(token, **kwargs), cdn_base_url=base)
    msg.prepare()
    return msg


@pytest.mark.parametrize("parallel", [False, True])
def test_same_named_files_keep_their_bytes_and_both_cache_entries(cdn, parallel):
    base, requests = cdn
    if parallel:
        requests.barrier = threading.Barrier(2)
        with ThreadPoolExecutor(max_workers=2) as pool:
            msgs = list(pool.map(lambda token: downloaded(base, token), PAYLOADS))
    else:
        msgs = [downloaded(base, token) for token in PAYLOADS]
    cache = FileCache()
    for msg in msgs:
        cache.add("fixture-user", msg.content, "file")
    assert len(cache.get("fixture-user")) == 2
    assert len({msg.content for msg in msgs}) == 2
    for token, msg in zip(PAYLOADS, msgs):
        assert Path(msg.content).read_bytes() == PAYLOADS[token]
        assert Path(msg.content).name.endswith("report.txt")
    assert sorted(requests) == sorted(PAYLOADS)


def test_reused_message_id_still_allocates_separate_storage(cdn):
    base, _ = cdn
    first = downloaded(base, "first", msg_id="shared-id")
    second = downloaded(base, "second", msg_id="shared-id")
    assert first.content != second.content
    assert Path(first.content).read_bytes() == PAYLOADS["first"]
    assert Path(second.content).read_bytes() == PAYLOADS["second"]


def test_actual_channel_followup_and_read_receive_both_reports(cdn, monkeypatch):
    from channel.weixin.weixin_channel import WeixinChannel
    from agent.tools.read.read import Read

    base, requests = cdn
    cls = WeixinChannel.__wrapped__
    channel = cls.__new__(cls)  # No login, poll thread, or model worker.
    channel.api = SimpleNamespace(cdn_base_url=base)
    channel._received_msgs = ExpiredDict(300)
    channel._pending_media = {}
    channel._pending_media_lock = threading.Lock()
    channel.channel_type = "weixin"
    produced = []
    channel.produce = produced.append  # Observe the real inbound queue boundary.
    monkeypatch.setattr(file_cache, "_file_cache", FileCache())
    channel._process_message(raw_file("first"))
    channel._process_message(raw_file("second"))
    channel._process_message({"message_type": 1, "message_id": "question",
        "from_user_id": "fixture-user", "to_user_id": "fixture-bot",
        "item_list": [{"type": messages.ITEM_TEXT, "text_item": {"text": "Compare reports"}}]})
    assert len(produced) == 1
    paths = re.findall(r"\[文件: (.*?)\]", produced[0].content)
    assert len(paths) == 2
    results = [Read().execute({"path": path}) for path in paths]
    assert all(result.status == "success" for result in results)
    assert "first report contents" in results[0].result["content"]
    assert "second report contents" in results[1].result["content"]
    assert file_cache.get_file_cache().get("fixture-user") == []
    assert sorted(requests) == sorted(PAYLOADS)


@pytest.mark.parametrize("name,ending", [("annual report.txt", "annual report.txt"),
    ("财务报告.txt", "财务报告.txt"), ("reports/report.txt", "report.txt"),
    ("..\\report.txt", "report.txt"), ("", ".bin")])
def test_display_basename_and_extension_survive(cdn, name, ending):
    base, _ = cdn
    msg = downloaded(base, "first", name=name)
    assert Path(msg.content).parent == Path(messages._get_tmp_dir())
    assert Path(msg.content).name.endswith(ending)
    assert Path(msg.content).read_bytes() == PAYLOADS["first"]


def test_inline_text_media_retains_both_files(cdn):
    base, _ = cdn
    msgs = [downloaded(base, token, text="Please read") for token in PAYLOADS]
    paths = [re.search(r"\[文件: (.*?)\]", msg.content).group(1) for msg in msgs]
    assert len(set(paths)) == 2
    for path, token in zip(paths, PAYLOADS):
        assert Path(path).read_bytes() == PAYLOADS[token]


def test_failed_second_download_keeps_first_file(cdn):
    base, _ = cdn
    first = downloaded(base, "first")
    failed = downloaded(base, "missing")
    assert failed.content == ""
    assert Path(first.content).read_bytes() == PAYLOADS["first"]
    assert list(Path(messages._get_tmp_dir()).iterdir()) == [Path(first.content)]


def test_prepare_is_idempotent(cdn):
    base, requests = cdn
    msg = downloaded(base, "first")
    path = msg.content
    msg.prepare()
    assert msg.content == path
    assert requests == ["first"]


def test_lazy_path_matches_successful_download_without_creating_an_empty_file(cdn):
    base, requests = cdn
    msg = messages.WeixinMessage(raw_file("first"), cdn_base_url=base)
    path = msg.content
    assert requests == []
    assert not Path(path).exists()
    msg.prepare()
    assert msg.content == path
    assert Path(path).read_bytes() == PAYLOADS["first"]


def test_names_that_sanitize_to_the_same_basename_keep_separate_bytes(cdn):
    base, _ = cdn
    first = downloaded(base, "first", name="reports/report.txt")
    second = downloaded(base, "second", name="..\\report.txt")
    assert first.content != second.content
    assert Path(first.content).read_bytes() == PAYLOADS["first"]
    assert Path(second.content).read_bytes() == PAYLOADS["second"]


@pytest.mark.parametrize("name", ["财" * 80 + ".txt", "界" * 82 + ".csv"])
def test_long_utf8_basename_downloads_and_remains_readable(cdn, name):
    from agent.tools.read.read import Read

    base, _ = cdn
    assert len(name.encode("utf-8")) <= 255
    msg = downloaded(base, "first", name=name)
    assert msg.content, "a valid original basename must remain downloadable"
    path = Path(msg.content)
    assert len(path.name.encode("utf-8")) <= 255
    assert path.suffix == Path(name).suffix
    assert path.read_bytes() == PAYLOADS["first"]
    result = Read().execute({"path": str(path)})
    assert result.status == "success"
    assert "first report contents" in result.result["content"]
