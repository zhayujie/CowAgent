"""Web Search tool. Supports five backends with a unified response format:
  - bocha   (https://open.bochaai.com)
  - zhipu   (https://docs.bigmodel.cn/cn/guide/tools/web-search)
  - qianfan (https://cloud.baidu.com/doc/qianfan/s/2mh4su4uy)
  - linkai  (https://link-ai.tech, fallback)
  - serply  (https://serply.io, Google/Bing SERP API)

Provider selection
  - strategy 'auto' (default): pick the first configured provider in the
    canonical order [bocha, zhipu, qianfan, linkai, serply]. When the caller
    passes an explicit `provider` it overrides the pick; an invalid/
    unconfigured one silently falls back to the auto order.
  - strategy 'fixed': use the configured provider; if its credential is
    missing at call time, silently fall back to auto order (no card hint).

Credentials
  - bocha   : tools.web_search.bocha_api_key  ->  env BOCHA_API_KEY
  - zhipu   : conf.zhipu_ai_api_key            ->  env ZHIPUAI_API_KEY
  - qianfan : conf.qianfan_api_key             ->  env QIANFAN_API_KEY
  - linkai  : conf.linkai_api_key              ->  env LINKAI_API_KEY
  - serply  : tools.web_search.serply_api_key  ->  env SERPLY_API_KEY
"""

import json
import os
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

import requests

from agent.tools.base_tool import BaseTool, ToolResult
from common.log import logger
from config import conf


DEFAULT_TIMEOUT = 30

# Canonical fallback order. Empirically ordered by Chinese real-time
# quality + relevance: bocha (best overall), qianfan (best for hot news),
# zhipu (strong on long-form articles), linkai (cloud aggregator), serply
# (global Google/Bing SERP, last since it isn't benchmarked against the
# Chinese-market providers above).
PROVIDER_ORDER = ("bocha", "qianfan", "zhipu", "linkai", "serply")

PROVIDER_LABELS = {
    "bocha":   "Bocha",
    "zhipu":   "Zhipu",
    "qianfan": "Baidu Qianfan",
    "linkai":  "LinkAI",
    "serply":  "Serply",
}


def _tools_web_search_conf() -> dict:
    """Return the tools.web_search config block (dict-like)."""
    tools_cfg = conf().get("tools") or {}
    if not isinstance(tools_cfg, dict):
        return {}
    block = tools_cfg.get("web_search") or {}
    return block if isinstance(block, dict) else {}


def _get_api_key(provider: str) -> str:
    """Resolve API key for a provider, with conf -> env fallback."""
    if provider == "bocha":
        key = (_tools_web_search_conf().get("bocha_api_key") or "").strip()
        return key or os.environ.get("BOCHA_API_KEY", "").strip()
    if provider == "zhipu":
        key = (conf().get("zhipu_ai_api_key") or "").strip()
        return key or os.environ.get("ZHIPUAI_API_KEY", "").strip()
    if provider == "qianfan":
        key = (conf().get("qianfan_api_key") or "").strip()
        return key or os.environ.get("QIANFAN_API_KEY", "").strip()
    if provider == "linkai":
        key = (conf().get("linkai_api_key") or "").strip()
        return key or os.environ.get("LINKAI_API_KEY", "").strip()
    if provider == "serply":
        key = (_tools_web_search_conf().get("serply_api_key") or "").strip()
        return key or os.environ.get("SERPLY_API_KEY", "").strip()
    return ""


def configured_providers() -> List[str]:
    """Return configured providers in canonical order."""
    return [p for p in PROVIDER_ORDER if _get_api_key(p)]


def _configured_strategy() -> str:
    return (_tools_web_search_conf().get("strategy") or "auto").strip().lower()


def _configured_provider() -> str:
    return (_tools_web_search_conf().get("provider") or "").strip().lower()


class WebSearch(BaseTool):
    """Tool for searching the web across multiple providers."""

    name: str = "web_search"
    description: str = "Search the web for real-time information. Returns titles, URLs, and snippets."

    params: dict = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search query string"
            },
            "count": {
                "type": "integer",
                "description": "Number of results to return (1-50, default: 10)"
            },
            "freshness": {
                "type": "string",
                "description": (
                    "Time range filter. Options: "
                    "'noLimit' (default), 'oneDay', 'oneWeek', 'oneMonth', 'oneYear', "
                    "or date range like '2025-01-01..2025-02-01'"
                )
            },
            "summary": {
                "type": "boolean",
                "description": "Whether to include text summary for each result (default: false)"
            }
        },
        "required": ["query"]
    }

    def __init__(self, config: dict = None):
        self.config = config or {}

    @staticmethod
    def is_available() -> bool:
        """Tool is offered to the agent when at least one provider has a key."""
        return bool(configured_providers())

    def get_json_schema(self) -> dict:
        """Augment the static schema with a `provider` field — only when the
        user has ≥2 providers configured AND strategy is 'auto'. Otherwise
        the backend picks silently and exposing the field would only waste
        the agent's tokens."""
        schema = {
            "name": self.name,
            "description": self.description,
            "parameters": json.loads(json.dumps(self.params)),  # deep copy
        }
        if _configured_strategy() != "auto":
            return schema
        available = configured_providers()
        if len(available) < 2:
            return schema

        schema["parameters"]["properties"]["provider"] = {
            "type": "string",
            "enum": available,
            "description": "Optional. Specifies the search backend. You may switch between providers when the user wants results from a particular source or from multiple sources.",
        }
        return schema

    # ------------------------------------------------------------------
    # Provider resolution
    # ------------------------------------------------------------------

    def _resolve_provider(self, requested: Optional[str]) -> Optional[str]:
        """Pick a provider for this call.

        Priority: caller-supplied (if configured) > fixed strategy (if
        configured) > first configured in PROVIDER_ORDER. Silent fallback
        when the desired one has no key.
        """
        available = configured_providers()
        if not available:
            return None

        if requested:
            req = requested.strip().lower()
            if req in available:
                return req
            logger.warning(f"[WebSearch] requested provider '{requested}' unavailable, falling back")

        if _configured_strategy() == "fixed":
            pinned = _configured_provider()
            if pinned in available:
                return pinned
            if pinned:
                logger.warning(f"[WebSearch] pinned provider '{pinned}' unavailable, falling back to auto")

        return available[0]

    @staticmethod
    def _resolution_reason(requested: Optional[str], chosen: str) -> str:
        """Human-readable explanation for why `chosen` won the resolver."""
        if requested and requested.strip().lower() == chosen:
            return "caller-requested"
        strategy = _configured_strategy()
        if strategy == "fixed" and _configured_provider() == chosen:
            return "fixed-strategy"
        return "auto-fallback"

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    def execute(self, args: Dict[str, Any]) -> ToolResult:
        query = (args.get("query") or "").strip()
        if not query:
            return ToolResult.fail("Error: 'query' parameter is required")

        count = args.get("count", 10)
        freshness = args.get("freshness", "noLimit")
        summary = args.get("summary", False)
        if not isinstance(count, int) or count < 1 or count > 50:
            count = 10

        requested = args.get("provider")
        provider = self._resolve_provider(requested)
        if not provider:
            return ToolResult.fail(
                "Error: No search provider configured. "
                "Configure one of BOCHA_API_KEY / zhipu_ai_api_key / qianfan_api_key / "
                "linkai_api_key / SERPLY_API_KEY."
            )

        # Always log the routing decision so multi-provider deployments can
        # tell at a glance which backend served any given query.
        available = configured_providers()
        reason = self._resolution_reason(requested, provider)
        q_preview = query if len(query) <= 60 else (query[:57] + "...")
        logger.info(
            f"[WebSearch] provider={provider} reason={reason} "
            f"available={list(available)} query={q_preview!r} count={count} freshness={freshness}"
        )

        try:
            if provider == "bocha":
                return self._search_bocha(query, count, freshness, summary)
            if provider == "zhipu":
                return self._search_zhipu(query, count, freshness)
            if provider == "qianfan":
                return self._search_qianfan(query, count, freshness)
            if provider == "linkai":
                return self._search_linkai(query, count, freshness)
            if provider == "serply":
                return self._search_serply(query, count)
            return ToolResult.fail(f"Error: Unknown provider '{provider}'")
        except requests.Timeout:
            return ToolResult.fail(f"Error: Search request timed out after {DEFAULT_TIMEOUT}s")
        except requests.ConnectionError:
            return ToolResult.fail("Error: Failed to connect to search API")
        except Exception as e:
            logger.error(f"[WebSearch] Unexpected error ({provider}): {e}", exc_info=True)
            return ToolResult.fail(f"Error: Search failed - {str(e)}")

    # ------------------------------------------------------------------
    # Bocha
    # ------------------------------------------------------------------

    def _search_bocha(self, query: str, count: int, freshness: str, summary: bool) -> ToolResult:
        api_key = _get_api_key("bocha")
        url = "https://api.bochaai.com/v1/web-search"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        payload = {"query": query, "count": count, "freshness": freshness, "summary": summary}

        logger.debug(f"[WebSearch] bocha: query='{query}', count={count}")
        resp = requests.post(url, headers=headers, json=payload, timeout=DEFAULT_TIMEOUT)

        if resp.status_code == 401:
            return ToolResult.fail("Error: Invalid bocha API key.")
        if resp.status_code == 403:
            return ToolResult.fail("Error: bocha API — insufficient balance. Top up at https://open.bochaai.com")
        if resp.status_code == 429:
            return ToolResult.fail("Error: bocha API rate limit reached.")
        if resp.status_code != 200:
            return ToolResult.fail(f"Error: bocha API returned HTTP {resp.status_code}")

        data = resp.json()
        api_code = data.get("code")
        if api_code is not None and api_code != 200:
            msg = data.get("msg") or "Unknown error"
            return ToolResult.fail(f"Error: bocha API error (code={api_code}): {msg}")

        pages = (data.get("data") or {}).get("webPages", {}).get("value", []) or []
        results = []
        for p in pages:
            item = {
                "title": p.get("name", ""),
                "url": p.get("url", ""),
                "snippet": p.get("snippet", ""),
                "siteName": p.get("siteName", ""),
                "datePublished": p.get("datePublished") or p.get("dateLastCrawled", ""),
            }
            if p.get("summary"):
                item["summary"] = p["summary"]
            results.append(item)
        total = (data.get("data") or {}).get("webPages", {}).get("totalEstimatedMatches", len(results))
        return ToolResult.success({
            "query": query, "backend": "bocha",
            "total": total, "count": len(results), "results": results,
        })

    # ------------------------------------------------------------------
    # Zhipu
    # ------------------------------------------------------------------

    def _search_zhipu(self, query: str, count: int, freshness: str) -> ToolResult:
        api_key = _get_api_key("zhipu")
        api_base = (conf().get("zhipu_ai_api_base") or "https://open.bigmodel.cn/api/paas/v4").rstrip("/")
        url = f"{api_base}/web_search"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        # Zhipu Web Search expects `search_query` <= 70 chars; truncate
        # gracefully so a long agent-supplied query doesn't get rejected.
        trimmed_query = (query or "")[:70]
        engine = (_tools_web_search_conf().get("zhipu_search_engine") or "search_pro").strip().lower()
        if engine not in ("search_std", "search_pro", "search_pro_sogou", "search_pro_quark"):
            engine = "search_pro"

        payload: Dict[str, Any] = {
            "search_engine": engine,
            "search_query": trimmed_query,
            "search_intent": False,
            "count": max(1, min(int(count or 10), 50)),
            "search_recency_filter": freshness if freshness in (
                "oneDay", "oneWeek", "oneMonth", "oneYear", "noLimit"
            ) else "noLimit",
        }
        content_size = (_tools_web_search_conf().get("zhipu_content_size") or "").strip().lower()
        if content_size in ("medium", "high"):
            payload["content_size"] = content_size

        logger.debug(f"[WebSearch] zhipu: query='{trimmed_query}', count={payload['count']}, engine={engine}")
        resp = requests.post(url, headers=headers, json=payload, timeout=DEFAULT_TIMEOUT)

        if resp.status_code == 401:
            return ToolResult.fail("Error: Invalid Zhipu API key.")
        if resp.status_code != 200:
            return ToolResult.fail(f"Error: Zhipu API returned HTTP {resp.status_code}: {resp.text[:200]}")

        data = resp.json()
        # Business-level errors (1701/1702/1703 etc.) come back as
        # {"error": {"code","message"}} even on HTTP 200.
        if isinstance(data, dict) and data.get("error"):
            err = data["error"] or {}
            return ToolResult.fail(f"Error: Zhipu returned {err.get('code')}: {err.get('message','')}")

        items = data.get("search_result") or (data.get("data") or {}).get("search_result") or []
        results = []
        for it in items:
            results.append({
                "title": it.get("title", ""),
                "url": it.get("link") or it.get("url", ""),
                "snippet": it.get("content") or it.get("snippet", ""),
                "siteName": it.get("media") or it.get("siteName", ""),
                "datePublished": it.get("publish_date") or it.get("datePublished", ""),
            })
        return ToolResult.success({
            "query": query, "backend": "zhipu",
            "total": len(results), "count": len(results), "results": results,
        })

    # ------------------------------------------------------------------
    # Qianfan (Baidu)
    # ------------------------------------------------------------------

    def _search_qianfan(self, query: str, count: int, freshness: str) -> ToolResult:
        api_key = _get_api_key("qianfan")
        api_base = (conf().get("qianfan_api_base") or "https://qianfan.baidubce.com/v2").rstrip("/")
        url = f"{api_base}/ai_search/web_search"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "X-Appbuilder-From": "cow",
        }

        count = max(1, min(int(count or 10), 50))
        payload: Dict[str, Any] = {
            "messages": [{"role": "user", "content": query}],
            "search_source": "baidu_search_v2",
            "resource_type_filter": [{"type": "web", "top_k": count}],
        }

        # Baidu AI Search expects freshness as a date-range filter, not a
        # named recency token. Translate our shared vocabulary into the
        # underlying page_time range expected by the API.
        search_filter = self._qianfan_build_freshness_filter(freshness)
        if search_filter:
            payload["search_filter"] = search_filter

        logger.debug(f"[WebSearch] qianfan: query='{query}', count={count}, freshness={freshness!r}")
        resp = requests.post(url, headers=headers, json=payload, timeout=DEFAULT_TIMEOUT)

        if resp.status_code == 401:
            return ToolResult.fail("Error: Invalid Qianfan API key.")
        if resp.status_code != 200:
            return ToolResult.fail(f"Error: Qianfan API returned HTTP {resp.status_code}: {resp.text[:200]}")

        data = resp.json()
        # Even on HTTP 200 Baidu surfaces business errors as {"code","message"}.
        if isinstance(data, dict) and data.get("code"):
            return ToolResult.fail(f"Error: Qianfan returned {data.get('code')}: {data.get('message','')}")

        refs = data.get("references") or []
        results = []
        for d in refs:
            results.append({
                "title": d.get("title", ""),
                "url": d.get("url", ""),
                "snippet": (d.get("content") or "")[:200],
                "siteName": d.get("web_anchor") or d.get("website") or "",
                "datePublished": d.get("date", ""),
            })
        return ToolResult.success({
            "query": query, "backend": "qianfan",
            "total": len(results), "count": len(results), "results": results,
        })

    @staticmethod
    def _qianfan_build_freshness_filter(freshness: str) -> Optional[Dict[str, Any]]:
        if not freshness or freshness == "noLimit":
            return None
        delta_days = {"oneDay": 1, "oneWeek": 7, "oneMonth": 30, "oneYear": 365}.get(freshness)
        if not delta_days:
            return None
        from datetime import datetime, timedelta
        now = datetime.now()
        end_date = (now + timedelta(days=1)).strftime("%Y-%m-%d")
        start_date = (now - timedelta(days=delta_days)).strftime("%Y-%m-%d")
        return {"range": {"page_time": {"gte": start_date, "lt": end_date}}}

    # ------------------------------------------------------------------
    # LinkAI (plugin)
    # ------------------------------------------------------------------

    def _search_linkai(self, query: str, count: int, freshness: str) -> ToolResult:
        api_key = _get_api_key("linkai")
        api_base = (conf().get("linkai_api_base") or "https://api.link-ai.tech").rstrip("/")
        url = f"{api_base}/v1/plugin/execute"

        from common.utils import get_cloud_headers
        headers = get_cloud_headers(api_key)

        payload = {"code": "web-search", "args": {"query": query, "count": count, "freshness": freshness}}
        logger.debug(f"[WebSearch] linkai: query='{query}', count={count}")
        resp = requests.post(url, headers=headers, json=payload, timeout=DEFAULT_TIMEOUT)

        if resp.status_code == 401:
            return ToolResult.fail("Error: Invalid LinkAI API key.")
        if resp.status_code != 200:
            return ToolResult.fail(f"Error: LinkAI API returned HTTP {resp.status_code}")

        data = resp.json()
        if not data.get("success"):
            msg = data.get("message") or "Unknown error"
            return ToolResult.fail(f"Error: LinkAI search failed: {msg}")

        raw = data.get("data", "")
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                return ToolResult.success({
                    "query": query, "backend": "linkai",
                    "total": 1, "count": 1, "results": [{"content": raw}],
                })

        if isinstance(raw, dict):
            pages = (raw.get("webPages") or {}).get("value", []) or []
            if pages:
                results = []
                for p in pages:
                    item = {
                        "title": p.get("name", ""),
                        "url": p.get("url", ""),
                        "snippet": p.get("snippet", ""),
                        "siteName": p.get("siteName", ""),
                        "datePublished": p.get("datePublished") or p.get("dateLastCrawled", ""),
                    }
                    if p.get("summary"):
                        item["summary"] = p["summary"]
                    results.append(item)
                total = (raw.get("webPages") or {}).get("totalEstimatedMatches", len(results))
                return ToolResult.success({
                    "query": query, "backend": "linkai",
                    "total": total, "count": len(results), "results": results,
                })

        return ToolResult.success({
            "query": query, "backend": "linkai",
            "total": 1, "count": 1, "results": [{"content": str(raw)}],
        })

    # ------------------------------------------------------------------
    # Serply
    # ------------------------------------------------------------------

    def _search_serply(self, query: str, count: int) -> ToolResult:
        api_key = _get_api_key("serply")
        path = urlencode({"q": query, "num": max(1, min(int(count or 10), 50))})
        headers = {
            "X-Api-Key": api_key,
            "Accept": "application/json",
            # Serply sits behind Cloudflare, which rejects the default
            # requests User-Agent, so send an explicit one.
            "User-Agent": "CowAgent",
        }

        logger.debug(f"[WebSearch] serply: query='{query}', count={count}")
        resp = requests.get(f"https://api.serply.io/v1/search/{path}", headers=headers, timeout=DEFAULT_TIMEOUT)

        if resp.status_code == 401:
            return ToolResult.fail("Error: Invalid Serply API key.")
        if resp.status_code == 429:
            return ToolResult.fail("Error: Serply API rate limit reached.")
        if resp.status_code != 200:
            return ToolResult.fail(f"Error: Serply API returned HTTP {resp.status_code}")

        data = resp.json()
        items = data.get("results") or []
        results = []
        for it in items:
            results.append({
                "title": it.get("title", ""),
                "url": it.get("link", ""),
                "snippet": it.get("description", ""),
            })
        return ToolResult.success({
            "query": query, "backend": "serply",
            "total": len(results), "count": len(results), "results": results,
        })
