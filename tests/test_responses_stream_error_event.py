"""A Responses ``error`` SSE event keeps its provider code and message."""
from models.openai.responses_adapter import responses_stream_to_chat_chunks


def _run(events):
    return list(responses_stream_to_chat_chunks(iter(events), model="test"))


def test_top_level_error_event_keeps_provider_message():
    chunks = _run([
        {"type": "response.output_text.delta", "delta": "hi"},
        {"type": "error", "code": "rate_limit_exceeded", "message": "Rate limit reached", "param": None},
    ])
    error = chunks[-1]
    assert error["message"] == "Rate limit reached"
    assert error["error"] == {"message": "Rate limit reached", "code": "rate_limit_exceeded", "type": ""}
    assert error["status_code"] == 500


def test_failed_event_still_reads_nested_response_error():
    chunks = _run([
        {"type": "response.failed",
         "response": {"status": "failed", "error": {"code": "server_error", "message": "Generation failed"}}},
    ])
    assert chunks[-1]["message"] == "Generation failed"
    assert chunks[-1]["error"]["code"] == "server_error"


def test_error_event_without_details_falls_back():
    chunks = _run([{"type": "error"}])
    assert chunks[-1]["message"] == "Responses stream error"
    assert chunks[-1]["error"]["code"] == ""
