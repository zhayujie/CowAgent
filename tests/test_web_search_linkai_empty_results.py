"""LinkAI search: an empty page is empty, and `summary` must be requested.

Two things the provider table promises but this branch did not do:

* ``summary`` is documented on the tool schema as "Bocha/linkai/deepseek/keenable
  only", and it was dropped on the floor for linkai — the request never asked for
  summaries, so a caller that wanted them silently got none.
* a no-result query came back as ``total: 1, count: 1`` holding a stringified
  dict, because the empty-page case fell into the "not a search payload"
  fallback. `_search_bocha` documents the real shape: ``"webPages": null``.
"""
import json

from agent.tools.web_search import web_search


class _Response:
    status_code = 200

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


def _search(monkeypatch, payload, summary=False):
    """Run the tool as the agent does, capturing the request body it posts."""
    captured = {}

    def post(url, **kwargs):
        captured["body"] = kwargs["json"]
        return _Response(payload)

    monkeypatch.setattr(web_search, "configured_providers", lambda: ["linkai"])
    monkeypatch.setattr(web_search, "_get_api_key", lambda provider: "k")
    monkeypatch.setattr(web_search.requests, "post", post)
    result = web_search.WebSearch({}).execute(
        {"query": "qq", "provider": "linkai", "summary": summary}
    )
    return result, captured.get("body")


def _wrapped(data):
    return {"success": True, "data": json.dumps(data)}


def test_an_empty_value_list_is_zero_results(monkeypatch):
    result, _ = _search(monkeypatch, _wrapped({"webPages": {"value": [], "totalEstimatedMatches": 0}}))

    assert result.status == "success"
    assert result.result["count"] == 0
    assert result.result["results"] == []
    assert result.result["total"] == 0


def test_a_null_web_pages_is_zero_results(monkeypatch):
    """The shape bocha's comment says a no-result query comes back with."""
    result, _ = _search(monkeypatch, _wrapped({"webPages": None}))

    assert result.result["count"] == 0
    assert result.result["results"] == []


def test_a_dict_payload_with_no_results_is_zero_results(monkeypatch):
    result, _ = _search(monkeypatch, {"success": True, "data": {"webPages": {"value": []}}})

    assert result.result["count"] == 0
    assert result.result["total"] == 0


def test_summary_reaches_the_request(monkeypatch):
    _, body = _search(monkeypatch, _wrapped({"webPages": {"value": []}}), summary=True)

    assert body["args"]["summary"] is True


def test_summary_defaults_to_false_in_the_request(monkeypatch):
    """The field has to be there either way, so the server's default is explicit."""
    _, body = _search(monkeypatch, _wrapped({"webPages": {"value": []}}))

    assert body["args"]["summary"] is False


def test_pages_are_still_mapped(monkeypatch):
    """Control: a real result set is unchanged."""
    payload = _wrapped({"webPages": {
        "value": [
            {"name": "A", "url": "https://a.test", "snippet": "sa", "siteName": "a.test",
             "summary": "sum-a"},
            {"name": "B", "url": "https://b.test", "snippet": "sb"},
        ],
        "totalEstimatedMatches": 42,
    }})

    result, _ = _search(monkeypatch, payload)

    assert result.result["count"] == 2
    assert result.result["total"] == 42
    assert result.result["results"][0] == {
        "title": "A", "url": "https://a.test", "snippet": "sa", "siteName": "a.test",
        "datePublished": "", "summary": "sum-a",
    }
    assert "summary" not in result.result["results"][1]


def test_a_non_search_payload_still_reports_its_content(monkeypatch):
    """Control: the fallback is for answers, not for empty search pages."""
    result, _ = _search(monkeypatch, _wrapped({"answer": "42"}))

    assert result.result["count"] == 1
    assert "answer" in result.result["results"][0]["content"]
