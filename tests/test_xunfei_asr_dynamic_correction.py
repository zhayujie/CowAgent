"""Dynamic corrections must retain the incoming result's sequence number."""

import importlib.util
import json
from pathlib import Path
import sys
from types import ModuleType

import pytest


@pytest.fixture
def asr(monkeypatch):
    monkeypatch.setitem(sys.modules, "websocket", ModuleType("websocket"))
    path = Path(__file__).resolve().parents[1] / "voice" / "xunfei" / "xunfei_asr.py"
    spec = importlib.util.spec_from_file_location("xunfei_asr_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.whole_dict = {}
    return module


def test_successive_dynamic_corrections_replace_previous_text(asr):
    asr.whole_dict = {1: "old1", 2: "old2"}

    asr.on_message(None, json.dumps({
        "code": 0, "sid": "t", "data": {"result": {
            "sn": 3, "rg": [1, 2], "ws": [{"cw": [{"w": "draft"}]}],
        }},
    }))
    asr.on_message(None, json.dumps({
        "code": 0, "sid": "t", "data": {"result": {
            "sn": 4, "rg": [3, 3], "ws": [{"cw": [{"w": "final"}]}],
        }},
    }))

    assert "".join(asr.whole_dict[sn] for sn in sorted(asr.whole_dict)) == "final"
    assert asr.whole_dict == {4: "final"}


def test_result_without_correction_is_stored_under_its_sequence_number(asr):
    asr.on_message(None, json.dumps({
        "code": 0, "sid": "t", "data": {"result": {
            "sn": 7, "ws": [{"cw": [{"w": "hello"}]}],
        }},
    }))

    assert asr.whole_dict == {7: "hello"}
