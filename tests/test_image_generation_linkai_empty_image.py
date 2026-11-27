"""A 200 from LinkAI with no usable image is a failure, not an empty success.

Every other provider in ``generate.py`` raises ``RuntimeError`` when the
response carries no image, and ``main`` depends on that: it treats "the
provider returned" as success and prints ``{"images": [...]}`` for the model to
render. ``LinkAIProvider`` was the one provider that returned an empty list
instead, so a content-filtered or text-only reply produced
``{"images": []}`` with exit code 0 — the model was told the image exists and
had nothing to show the user.
"""

import base64
import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT_PATH = (
    Path(__file__).parents[1]
    / "skills"
    / "image-generation"
    / "scripts"
    / "generate.py"
)
SPEC = importlib.util.spec_from_file_location("image_generation_script", SCRIPT_PATH)
image_generation = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(image_generation)

PNG_BYTES = b"\x89PNG\r\n\x1a\nfake-image-payload"
PNG_B64 = base64.b64encode(PNG_BYTES).decode()


class _FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.text = json.dumps(payload)
        self.reason = "OK"

    def json(self):
        return self._payload


def _patch_post(monkeypatch, payload):
    calls = []

    def fake_post(url, headers=None, json=None, timeout=None, **kwargs):
        calls.append({"url": url, "payload": json})
        return _FakeResponse(payload)

    monkeypatch.setitem(image_generation.__dict__, "_HAS_REQUESTS", True)
    monkeypatch.setattr(image_generation.requests, "post", fake_post)
    return calls


def _provider():
    return image_generation.LinkAIProvider(
        api_key="test-key",
        api_base="https://linkai.example.com",
        model="",
    )


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param({}, id="no-data-key"),
        pytest.param({"data": []}, id="empty-data"),
        pytest.param({"data": None}, id="null-data"),
        pytest.param({"data": [{"url": "", "b64_json": ""}]}, id="unusable-entry"),
    ],
)
def test_linkai_raises_instead_of_returning_no_images(tmp_path, monkeypatch, payload):
    _patch_post(monkeypatch, payload)

    with pytest.raises(RuntimeError, match="LinkAI returned no image"):
        _provider().generate("a red circle", output_dir=str(tmp_path))

    assert list(tmp_path.iterdir()) == []


def test_linkai_returns_paths_when_an_image_arrives(tmp_path, monkeypatch):
    calls = _patch_post(monkeypatch, {"data": [{"b64_json": PNG_B64}]})

    paths = _provider().generate("a red circle", output_dir=str(tmp_path))

    assert len(paths) == 1
    assert Path(paths[0]).read_bytes() == PNG_BYTES
    assert calls[0]["payload"]["prompt"] == "a red circle"


class _Collector:
    """Minimal stdout stand-in so `main`'s JSON line can be parsed."""

    def __init__(self, sink):
        self._sink = sink

    def write(self, text):
        self._sink.append(text)

    def flush(self):
        pass


def _run_main(monkeypatch, argv_args, output_dir):
    """Run ``generate.main`` with only the LinkAI key configured.

    Every other provider key is cleared so the routing table builds exactly one
    provider — otherwise a key inherited from the ambient environment would
    shift the provider order and make this test depend on the machine.
    """
    for name in (
        "OPENAI_API_KEY",
        "GEMINI_API_KEY",
        "ARK_API_KEY",
        "DASHSCOPE_API_KEY",
        "MINIMAX_API_KEY",
        "COWAGENT_API_KEY",
        "SKILL_IMAGE_GENERATION_MODEL",
        "SKILL_IMAGE_GENERATION_PROVIDER",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LINKAI_API_KEY", "test-key")
    monkeypatch.setenv("LINKAI_API_BASE", "https://linkai.example.com")
    monkeypatch.setenv("IMAGE_OUTPUT_DIR", str(output_dir))
    monkeypatch.setattr(image_generation.sys, "argv", ["generate.py", json.dumps(argv_args)])

    out = []
    monkeypatch.setattr(image_generation.sys, "stdout", _Collector(out))
    return out


def test_main_exits_nonzero_instead_of_printing_an_empty_image_list(tmp_path, monkeypatch):
    _patch_post(monkeypatch, {"data": []})
    out = _run_main(monkeypatch, {"prompt": "a red circle"}, tmp_path)

    with pytest.raises(SystemExit) as exc:
        image_generation.main()

    assert exc.value.code == 1
    body = json.loads("".join(out))
    assert "error" in body
    assert "images" not in body
    assert "LinkAI returned no image" in body["error"]


def test_main_reports_the_saved_image_on_success(tmp_path, monkeypatch):
    _patch_post(monkeypatch, {"data": [{"b64_json": PNG_B64}]})
    out = _run_main(monkeypatch, {"prompt": "a red circle"}, tmp_path)

    image_generation.main()

    body = json.loads("".join(out))
    assert "error" not in body
    assert len(body["images"]) == 1
    assert Path(body["images"][0]["url"]).read_bytes() == PNG_BYTES
