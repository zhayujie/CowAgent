"""Web Search tool. Supports nine backends with a unified response format:
  - bocha   (https://open.bochaai.com)
  - zhipu   (https://docs.bigmodel.cn/cn/guide/tools/web-search)
  - qianfan (https://cloud.baidu.com/doc/qianfan/s/2mh4su4uy)
  - linkai  (https://link-ai.tech, fallback)
  - anysearch (https://anysearch.com)
  - serply  (https://serply.io, Google/Bing SERP API)
  - tavily  (https://tavily.com, AI-optimized search API)
  - searxng (https://docs.searxng.org, self-hosted meta search engine)
  - keenable (https://keenable.ai, keyless tier behind an explicit opt-in)

Provider selection
  - strategy 'auto' (default): pick the first configured provider in the
    canonical order [bocha, qianfan, zhipu, linkai, anysearch, serply,
    tavily, searxng, keenable]. Keenable counts as configured with a key or with the explicit
    `keenable_anonymous` opt-in (same contract as `anysearch_anonymous`). When
    the caller passes an explicit `provider` it overrides the pick; an
    invalid/unconfigured one silently falls back to the auto order.
  - strategy 'fixed': use the configured provider; if its credential is
    missing at call time, silently fall back to auto order (no card hint).

Credentials
  - bocha   : tools.web_search.bocha_api_key  ->  env BOCHA_API_KEY
  - zhipu   : conf.zhipu_ai_api_key            ->  env ZHIPUAI_API_KEY
  - qianfan : conf.qianfan_api_key             ->  env QIANFAN_API_KEY
  - linkai  : conf.linkai_api_key              ->  env LINKAI_API_KEY
  - anysearch : tools.web_search.anysearch_api_key  -> env ANYSEARCH_API_KEY
  - serply  : tools.web_search.serply_api_key  ->  env SERPLY_API_KEY
  - tavily  : tools.web_search.tavily_api_key  ->  env TAVILY_API_KEY
  - searxng : tools.web_search.searxng_url     ->  env SEARXNG_URL
  - keenable: tools.web_search.keenable_api_key -> env KEENABLE_API_KEY (optional,
              only lifts the rate limits of the keyless public endpoint);
              keyless use is opt-in via tools.web_search.keenable_anonymous
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
# zhipu (strong on long-form articles), linkai (cloud aggregator),
# anysearch, serply (global Google/Bing SERP, last since it isn't
# benchmarked against the Chinese-market providers above), tavily, searxng,
# keenable (global index, keyless tier behind an explicit opt-in; placed last
# so any provider the user paid for wins).
PROVIDER_ORDER = ("bocha", "qianfan", "zhipu", "linkai", "anysearch", "serply", "tavily", "searxng", "keenable")

PROVIDER_LABELS = {
    "bocha":   "Bocha",
    "zhipu":   "Zhipu",
    "qianfan": "Baidu Qianfan",
    "linkai":  "LinkAI",
    "anysearch": "AnySearch",
    "serply":  "Serply",
    "tavily":  "Tavily",
    "searxng": "SearXNG",
    "keenable": "Keenable",
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
    if provider == "anysearch":
        key = (_tools_web_search_conf().get("anysearch_api_key") or "").strip()
        return key or os.environ.get("ANYSEARCH_API_KEY", "").strip()
    if provider == "serply":
        key = (_tools_web_search_conf().get("serply_api_key") or "").strip()
        return key or os.environ.get("SERPLY_API_KEY", "").strip()
    if provider == "tavily":
        key = (_tools_web_search_conf().get("tavily_api_key") or "").strip()
        return key or os.environ.get("TAVILY_API_KEY", "").strip()
    if provider == "keenable":
        key = (_tools_web_search_conf().get("keenable_api_key") or "").strip()
        return key or os.environ.get("KEENABLE_API_KEY", "").strip()
    return ""


def _anysearch_anonymous_enabled() -> bool:
    """Check if AnySearch anonymous mode is enabled via config."""
    return bool(_tools_web_search_conf().get("anysearch_anonymous"))


def _keenable_anonymous_enabled() -> bool:
    """Check if Keenable anonymous (keyless) mode is enabled via config."""
    return bool(_tools_web_search_conf().get("keenable_anonymous"))


def _get_searxng_url() -> str:
    """Resolve SearXNG instance URL from config or environment."""
    url = (_tools_web_search_conf().get("searxng_url") or "").strip()
    return url or os.environ.get("SEARXNG_URL", "").strip()


def configured_providers() -> List[str]:
    """Configured providers in canonical order. anysearch and keenable qualify
    with a real key OR an explicit anonymous opt-in (still last in fallback
    order); nothing goes keyless unless the user turned it on. searxng
    qualifies when an instance URL is configured."""
    result = []
    for p in PROVIDER_ORDER:
        if _get_api_key(p):
            result.append(p)
        elif p == "anysearch" and _anysearch_anonymous_enabled():
            result.append(p)
        elif p == "searxng" and _get_searxng_url():
            result.append(p)
        elif p == "keenable" and _keenable_anonymous_enabled():
            result.append(p)
    return result

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
                    "or date range like '2025-01-01..2025-02-01'. "
                    "Honored by bocha/zhipu/qianfan/linkai/keenable; ignored by anysearch."
                )
            },
            "summary": {
                "type": "boolean",
                "description": "Whether to include text summary for each result (default: false). "
                               "Bocha/linkai/keenable only; ignored by anysearch."
            }
        },
        "required": ["query"]
    }

    def __init__(self, config: dict = None):
        self.config = config or {}

    @staticmethod
    def is_available() -> bool:
        """Tool is offered to the agent when at least one provider has a key
        or an explicit anonymous opt-in (anysearch_anonymous / keenable_anonymous)."""
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
        # P2-1: expose vertical domain fields only when anysearch is guaranteed
        # to be the backend (fixed=anysearch or auto with only anysearch configured).
        expose_vertical = (
            (_configured_strategy() == "fixed" and _configured_provider() == "anysearch")
            or (_configured_strategy() == "auto" and configured_providers() == ["anysearch"])
        )
        if expose_vertical:
            schema["parameters"]["properties"]["tag"] = {
                "type": "string",
                "description": "Optional vertical domain, format '{domain}.{sub_domain}', "
                               "e.g. 'finance.quote', 'code.doc'. AnySearch backend only.",
            }
            schema["parameters"]["properties"]["params"] = {
                "type": "object",
                "description": "Optional per-sub-domain parameters (discoverable via GET /v1/sub-domains). "
                               "AnySearch backend only.",
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

        For anysearch: considered "available" even without a key (anonymous).
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

        # anysearch 始终在 available 中，所以会作为末位 fallback
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
        # This branch is technically unreachable because anysearch is always available
        # (anonymous tier). It's kept as a defensive guard for future modifications.
        if not provider:
            return ToolResult.fail(
                "Error: No search provider configured. "
                "Configure one of BOCHA_API_KEY / zhipu_ai_api_key / qianfan_api_key / linkai_api_key / "
                "anysearch_api_key / SERPLY_API_KEY / TAVILY_API_KEY / SEARXNG_URL."
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
            if provider == "anysearch":
                tag = args.get("tag") or (_tools_web_search_conf().get("anysearch_domain") or "").strip() or None
                search_params = args.get("params")
                if not isinstance(search_params, dict):
                    search_params = None
                zone = (_tools_web_search_conf().get("anysearch_zone") or "").strip().lower()
                language = (_tools_web_search_conf().get("anysearch_language") or "").strip()
                return self._search_anysearch(query, count, freshness, summary,
                                              tag=tag, search_params=search_params,
                                              zone=zone, language=language)
            if provider == "serply":
                return self._search_serply(query, count)
            if provider == "tavily":
                return self._search_tavily(query, count)
            if provider == "searxng":
                return self._search_searxng(query, count)
            if provider == "keenable":
                return self._search_keenable(query, count, freshness, summary)
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

    def _search_anysearch(self, query: str, count: int, freshness: str = "noLimit",
                              summary: bool = False, tag: str = None,
                              search_params: dict = None, zone: str = None,
                              language: str = None) -> ToolResult:
        if freshness and freshness != "noLimit":
            logger.warning(f"[WebSearch] anysearch does not support freshness ({freshness!r}); ignoring")
        if summary:
            logger.warning("[WebSearch] anysearch does not support summary; ignoring")
        api_key = _get_api_key("anysearch")
        url = "https://api.anysearch.com/v1/search"
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        # AnySearch also serves anonymous traffic with a daily free quota, so
        # the Authorization header is only sent when a key is configured.
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        # AnySearch accepts 1-10 results; the shared tool schema allows 1-10.
        max_results = max(1, min(int(count or 10), 10))
        payload = {"query": query, "max_results": max_results, "format": "json"}
        if tag:
            payload["tag"] = tag
        if search_params:
            payload["params"] = search_params
        if zone in ("cn", "intl"):
            payload["zone"] = zone
        if language in ("zh-CN", "en"):
            payload["language"] = language

        logger.debug(f"[WebSearch] anysearch: query='{query}', max_results={max_results}, has_key={bool(api_key)}")
        resp = requests.post(url, headers=headers, json=payload, timeout=DEFAULT_TIMEOUT)

        if resp.status_code == 401:
            if api_key:
                return ToolResult.fail("Error: Invalid AnySearch API key.")
            return ToolResult.fail(
                "Error: AnySearch authentication failed. Try configuring an API key at https://anysearch.com")
        if resp.status_code == 402:
            if api_key:
                return ToolResult.fail("Error: AnySearch quota exhausted. Check usage at https://anysearch.com")
            return ToolResult.fail(
                "Error: AnySearch anonymous quota exhausted. Configure an API key at https://anysearch.com for higher limits.")
        if resp.status_code == 429:
            return ToolResult.fail("Error: AnySearch API rate limit reached.")
        if resp.status_code != 200:
            return ToolResult.fail(f"Error: AnySearch API returned HTTP {resp.status_code}")

        data = resp.json()
        # AnySearch signals success with business code 0.
        api_code = data.get("code")
        if api_code not in (0, None):
            msg = data.get("message") or "Unknown error"
            return ToolResult.fail(f"Error: AnySearch API error (code={api_code}): {msg}")

        body = data.get("data") or {}
        results = []
        for it in body.get("results") or []:
            results.append({
                "title": it.get("title", ""),
                "url": it.get("url", ""),
                "snippet": it.get("snippet") or (it.get("content") or "")[:200],
            })
        total = (body.get("metadata") or {}).get("total_results", len(results))
        request_id = resp.headers.get("X-Request-ID") or data.get("request_id")
        meta = body.get("metadata") or {}

        result = {
            "query": query,
            "backend": "anysearch",
            "total": total,
            "count": len(results),
            "results": results,
        }

        if request_id:
            result["request_id"] = request_id
        if meta.get("search_time_ms") is not None:
            result["search_time_ms"] = meta["search_time_ms"]

        return ToolResult.success(result)

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

    # ------------------------------------------------------------------
    # Keenable
    # ------------------------------------------------------------------

    def _search_keenable(self, query: str, count: int, freshness: str, summary: bool) -> ToolResult:
        api_key = _get_api_key("keenable")
        # Keenable serves anonymous traffic on a public endpoint that wants an
        # app title instead of a key (rate limited per IP: 10 requests/s,
        # 1000/hour). Reaching this branch without a key means the user set
        # keenable_anonymous. A key switches to the authenticated endpoint,
        # which only lifts those limits.
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-Keenable-Title": "cowagent",
        }
        if api_key:
            url = "https://api.keenable.ai/v1/search"
            headers["X-API-Key"] = api_key
        else:
            url = "https://api.keenable.ai/v1/search/public"

        payload: Dict[str, Any] = {
            "query": query,
            "max_results": max(1, min(int(count or 10), 50)),
            # A hint, not a hard cap: the API rounds up to a word boundary.
            "snippet_max_length": 1000 if summary else 300,
        }
        payload.update(self._keenable_build_freshness_filter(freshness))

        logger.debug(
            f"[WebSearch] keenable: query='{query}', max_results={payload['max_results']}, keyed={bool(api_key)}"
        )
        resp = requests.post(url, headers=headers, json=payload, timeout=DEFAULT_TIMEOUT)

        if resp.status_code == 401:
            return ToolResult.fail("Error: Invalid Keenable API key.")
        if resp.status_code == 429:
            hint = "" if api_key else " Set keenable_api_key / KEENABLE_API_KEY to lift the keyless limit."
            return ToolResult.fail(f"Error: Keenable API rate limit reached.{hint}")
        if resp.status_code != 200:
            return ToolResult.fail(f"Error: Keenable API returned HTTP {resp.status_code}: {resp.text[:200]}")

        data = resp.json()
        results = []
        for it in data.get("results") or []:
            results.append({
                "title": it.get("title", ""),
                "url": it.get("url", ""),
                # `snippet` carries the page text; `description` is usually empty.
                "snippet": it.get("snippet") or it.get("description") or "",
                "datePublished": it.get("published_at") or "",
            })
        return ToolResult.success({
            "query": query, "backend": "keenable",
            "total": len(results), "count": len(results), "results": results,
        })

    @staticmethod
    def _keenable_build_freshness_filter(freshness: str) -> Dict[str, str]:
        """Translate the shared freshness vocabulary into Keenable's
        `published_after` / `published_before` (YYYY-MM-DD) request fields.
        Accepts the named tokens and the `2025-01-01..2025-02-01` range form."""
        if not freshness or freshness == "noLimit":
            return {}
        delta_days = {"oneDay": 1, "oneWeek": 7, "oneMonth": 30, "oneYear": 365}.get(freshness)
        if delta_days:
            from datetime import datetime, timedelta
            return {"published_after": (datetime.now() - timedelta(days=delta_days)).strftime("%Y-%m-%d")}
        start, sep, end = freshness.partition("..")
        if sep and start.strip() and end.strip():
            return {"published_after": start.strip(), "published_before": end.strip()}
        return {}

    # ------------------------------------------------------------------
    # Tavily
    # ------------------------------------------------------------------

    def _search_tavily(self, query: str, count: int) -> ToolResult:
        api_key = _get_api_key("tavily")
        url = "https://api.tavily.com/search"
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        max_results = max(1, min(int(count or 10), 20))
        search_depth = (_tools_web_search_conf().get("tavily_search_depth") or "basic").strip().lower()
        if search_depth not in ("basic", "advanced"):
            search_depth = "basic"

        payload: Dict[str, Any] = {
            "api_key": api_key,
            "query": query,
            "max_results": max_results,
            "search_depth": search_depth,
            "include_answer": False,
        }

        logger.debug(f"[WebSearch] tavily: query='{query}', max_results={max_results}, depth={search_depth}")
        resp = requests.post(url, headers=headers, json=payload, timeout=DEFAULT_TIMEOUT)

        if resp.status_code == 401:
            return ToolResult.fail("Error: Invalid Tavily API key.")
        if resp.status_code == 402:
            return ToolResult.fail("Error: Tavily API quota exhausted. Check usage at https://tavily.com")
        if resp.status_code == 429:
            return ToolResult.fail("Error: Tavily API rate limit reached.")
        if resp.status_code != 200:
            return ToolResult.fail(f"Error: Tavily API returned HTTP {resp.status_code}: {resp.text[:200]}")

        data = resp.json()
        items = data.get("results") or []
        results = []
        for it in items:
            results.append({
                "title": it.get("title", ""),
                "url": it.get("url", ""),
                "snippet": it.get("content") or it.get("snippet", ""),
                "siteName": it.get("source") or "",
                "score": it.get("score"),
            })
        return ToolResult.success({
            "query": query, "backend": "tavily",
            "total": len(results), "count": len(results), "results": results,
        })

    # ------------------------------------------------------------------
    # SearXNG (self-hosted meta search engine)
    # ------------------------------------------------------------------

    def _search_searxng(self, query: str, count: int) -> ToolResult:
        base_url = _get_searxng_url().rstrip("/")
        if not base_url:
            return ToolResult.fail("Error: SearXNG instance URL not configured. Set tools.web_search.searxng_url or SEARXNG_URL.")

        params = {
            "q": query,
            "format": "json",
            "pageno": 1,
        }
        language = (_tools_web_search_conf().get("searxng_language") or "").strip()
        if language:
            params["language"] = language
        categories = (_tools_web_search_conf().get("searxng_categories") or "general").strip()
        if categories:
            params["categories"] = categories

        url = f"{base_url}/search?{urlencode(params)}"
        headers = {
            "Accept": "application/json",
            "User-Agent": "CowAgent",
        }

        logger.debug(f"[WebSearch] searxng: query='{query}', instance={base_url}")
        resp = requests.get(url, headers=headers, timeout=DEFAULT_TIMEOUT)

        if resp.status_code == 401:
            return ToolResult.fail("Error: SearXNG instance requires authentication.")
        if resp.status_code == 403:
            return ToolResult.fail("Error: SearXNG instance access forbidden. Check instance CORS/API settings.")
        if resp.status_code == 429:
            return ToolResult.fail("Error: SearXNG rate limit reached.")
        if resp.status_code != 200:
            return ToolResult.fail(f"Error: SearXNG returned HTTP {resp.status_code}: {resp.text[:200]}")

        try:
            data = resp.json()
        except (ValueError, TypeError):
            return ToolResult.fail("Error: SearXNG returned non-JSON response. Ensure the instance supports format=json.")

        items = data.get("results") or []
        results = []
        for it in items[:max(1, min(int(count or 10), 50))]:
            results.append({
                "title": it.get("title", ""),
                "url": it.get("url", ""),
                "snippet": it.get("content") or it.get("snippet", ""),
                "siteName": it.get("engine") or it.get("source") or "",
                "score": it.get("score"),
            })
        return ToolResult.success({
            "query": query, "backend": "searxng",
            "total": len(results), "count": len(results), "results": results,
        })
