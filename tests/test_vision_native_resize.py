"""Exercise native sips through Vision's real configured HTTP payload path."""

import base64
import http.server
import io
import json
import os
import shutil
import threading

import pytest
from PIL import Image

from agent.tools.vision.vision import COMPRESS_THRESHOLD, Vision
from config import conf

pytestmark = pytest.mark.skipif(shutil.which("sips") is None, reason="Requires native macOS sips")


@pytest.mark.parametrize("size,expected", [
    ((1100, 1100), (1100, 1100)),
    ((4000, 300), (3072, 230)),
    ((3, 3), (3, 3)),
])
def test_public_vision_never_upscales_during_native_compression(tmp_path, monkeypatch, size, expected):
    path = tmp_path / "owned.png"
    Image.frombytes("RGB", size, os.urandom(size[0] * size[1] * 3)).save(path)
    original = path.read_bytes()
    if size != (3, 3):
        assert len(original) > COMPRESS_THRESHOLD
    captured = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            uri = request["messages"][0]["content"][1]["image_url"]["url"]
            captured.append(uri)
            body = json.dumps({"choices": [{"message": {"content": "owned image wire fixture"}}]}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    monkeypatch.setitem(conf(), "custom_providers", [{
        "id": "owned-resize-test", "name": "Owned image wire fixture", "api_key": "owned-unused-key",
        "api_base": f"http://127.0.0.1:{server.server_port}/v1", "model": "owned",
    }])
    monkeypatch.setitem(conf(), "tools", {"vision": {"provider": "custom:owned-resize-test", "model": "owned"}})
    try:
        result = Vision({"cwd": str(tmp_path)}).execute({"image": "owned.png", "question": "owned wire check"})
        assert result.status == "success", result.result
        assert len(captured) == 1
        header, encoded = captured[0].split(",", 1)
        decoded = base64.b64decode(encoded)
        with Image.open(io.BytesIO(decoded)) as sent:
            assert sent.size == expected
            assert header == f"data:{Image.MIME[sent.format]};base64"
        if size == (3, 3):
            assert decoded == original
        assert path.read_bytes() == original
    finally:
        server.shutdown()
        server.server_close()
        worker.join(2)
