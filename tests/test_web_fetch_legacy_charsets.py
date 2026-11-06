"""Legacy charset labels are decoded the way browsers decode them.

Browsers follow the WHATWG Encoding Standard, which reads gb2312 as GB18030,
Shift_JIS as Windows-31J, EUC-KR as UHC, Big5 as Big5-HKSCS, ISO-8859-1 as
windows-1252, ISO-8859-9 as windows-1254 and TIS-620 as windows-874. Pages
rely on those supersets, and the narrower codecs garble them.
"""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import pytest
import requests

from agent.tools.web_fetch.web_fetch import WebFetch

CHINESE = "张堃、李喆出席了会议。别啰嗦，囧。"  # 堃 喆 啰 囧 are GBK, not GB2312
JAPANESE = "会議は①午前と②午後の二回です。髙橋さん"  # ① ② 髙 are Windows-31J, not JIS X 0208
KOREAN = "오늘 점심은 똠얌꿍"  # 똠 is UHC, not KS X 1001
CANTONESE = "佢哋話呢度啲嘢好好食"  # 哋 啲 嘢 are HKSCS, not Big5
ENGLISH = "He said “yes” — it costs €5."
TURKISH = "Türkçe “alıntı” — 5€"
THAI = "ราคา “พิเศษ” 5€ …"
# Plain Shift_JIS and EUC-KR text, long enough for chardet to detect
JAPANESE_PARAGRAPH = "日本の首都は東京です。今日はとても良い天気ですね。私は毎朝コーヒーを飲みます。"
KOREAN_PARAGRAPH = "대한민국의 수도는 서울입니다. 오늘은 날씨가 아주 좋습니다. 저는 매일 아침 커피를 마십니다."


@pytest.fixture(scope="module")
def serve():
    """One local HTTP server; ``serve(path, content_type, body)`` returns the URL serving it."""
    responses = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            content_type, body = responses[self.path]
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def add(path, content_type, body):
        responses[path] = (content_type, body)
        return f"http://127.0.0.1:{server.server_port}{path}"

    yield add
    server.shutdown()
    server.server_close()
    thread.join()


@pytest.fixture
def fetch(tmp_path, monkeypatch, serve):
    # The documented optional guard permits owned local services; the HTTP
    # request, charset detection and decoding remain real.
    monkeypatch.setenv("WEB_SECURITY_SSRF_PROTECTION", "false")

    def run(path, content_type, body):
        return WebFetch({"cwd": str(tmp_path)}).execute({"url": serve(path, content_type, body)})

    return run


@pytest.mark.parametrize(
    "content_type, meta, text, codec",
    [
        pytest.param("text/html; charset=gb2312", "", CHINESE, "gb18030", id="gb2312-header"),
        pytest.param("text/html", '<meta charset="gb2312">', CHINESE, "gb18030", id="gb2312-meta"),
        pytest.param(
            "text/html",
            '<meta http-equiv="Content-Type" content="text/html; charset=Shift_JIS">',
            JAPANESE,
            "cp932",
            id="shift_jis-http-equiv",
        ),
        pytest.param("text/html; charset=euc-kr", "", KOREAN, "cp949", id="euc-kr"),
        pytest.param("text/html; charset=big5", "", CANTONESE, "big5hkscs", id="big5"),
        pytest.param("text/html; charset=ISO-8859-1", "", ENGLISH, "cp1252", id="iso-8859-1"),
        pytest.param("text/html; charset=iso-8859-9", "", TURKISH, "cp1254", id="iso-8859-9"),
        pytest.param("text/html; charset=windows-874", "", THAI, "cp874", id="windows-874"),
        pytest.param("text/html; charset=utf-8", "", CHINESE + JAPANESE + KOREAN, "utf-8", id="utf-8"),
    ],
)
def test_webpage_is_decoded_like_a_browser(fetch, content_type, meta, text, codec):
    body = f"<html><head>{meta}</head><body><p>{text}</p></body></html>".encode(codec)

    result = fetch("/news", content_type, body)

    assert result.status == "success", result.result
    assert text in result.result


def test_undeclared_webpage_uses_the_superset_of_the_detected_charset(fetch, monkeypatch):
    # chardet 5.x, which requirements.txt allows, reports GBK text as GB2312.
    monkeypatch.setattr(requests.Response, "apparent_encoding", property(lambda self: "GB2312"))
    body = f"<html><body><p>{CHINESE}</p></body></html>".encode("gb18030")

    result = fetch("/news", "text/html", body)

    assert result.status == "success", result.result
    assert CHINESE in result.result


@pytest.mark.parametrize(
    "detected, text, codec",
    [
        pytest.param("CP932", JAPANESE, "cp932", id="cp932"),
        pytest.param("CP949", KOREAN, "cp949", id="cp949"),
    ],
)
def test_undeclared_webpage_detected_as_cp932_or_cp949(fetch, monkeypatch, detected, text, codec):
    # chardet 7.x reports most Japanese and Korean pages as CP932 and CP949, and
    # chardet 5.x does for pages with characters such as ① or 똠.
    monkeypatch.setattr(requests.Response, "apparent_encoding", property(lambda self: detected))
    body = f"<html><body><p>{text}</p></body></html>".encode(codec)

    result = fetch("/news", "text/html", body)

    assert result.status == "success", result.result
    assert text in result.result


@pytest.mark.parametrize(
    "text, codec",
    [
        pytest.param(JAPANESE_PARAGRAPH, "shift_jis", id="shift_jis"),
        pytest.param(KOREAN_PARAGRAPH, "euc_kr", id="euc-kr"),
    ],
)
def test_undeclared_japanese_and_korean_webpages_are_decoded(fetch, text, codec):
    # Real detection: chardet 7.x reports these pages as CP932 and CP949.
    body = f"<html><body><p>{text}</p></body></html>".encode(codec)

    result = fetch("/news", "text/html", body)

    assert result.status == "success", result.result
    assert text in result.result


@pytest.mark.parametrize(
    "charset, text, codec",
    [
        pytest.param("Shift_JIS", JAPANESE, "cp932", id="shift_jis"),
        pytest.param("euc-kr", KOREAN, "cp949", id="euc-kr"),
        pytest.param("big5", CANTONESE, "big5hkscs", id="big5"),
        pytest.param("iso-8859-1", ENGLISH, "cp1252", id="iso-8859-1"),
    ],
)
def test_text_download_is_decoded_like_a_browser(fetch, charset, text, codec):
    result = fetch("/minutes.txt", f"text/plain; charset={charset}", text.encode(codec))

    assert result.status == "success", result.result
    assert text in result.result


@pytest.mark.parametrize(
    "path, content_type, text",
    [
        pytest.param("/notes.txt", "text/plain; charset=us-ascii", "Café crème — 5 €, naïve façade", id="us-ascii"),
        pytest.param("/cities.csv", "text/csv; charset=gb2312", "城市,人口\n北京,2189\n上海,2487", id="gb2312-csv"),
    ],
)
def test_utf8_text_download_with_a_legacy_label_stays_utf8(fetch, path, content_type, text):
    # Downloads are often UTF-8 whatever their label says, so UTF-8 is tried before the
    # browser codec, which would accept these bytes as mojibake.
    result = fetch(path, content_type, (text + "\n").encode("utf-8"))

    assert result.status == "success", result.result
    assert text in result.result
