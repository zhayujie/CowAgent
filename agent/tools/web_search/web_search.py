"""
Web Search tool - Search the web using Bocha or LinkAI search API.
Supports two backends with unified response format:
  1. Bocha Search (primary, requires BOCHA_API_KEY)
  2. LinkAI Search (fallback, requires LINKAI_API_KEY)
"""

import os
import json
from typing import Dict, Any, Optional

import requests

from agent.tools.base_tool import BaseTool, ToolResult
from common.log import logger
from config import conf


# Default timeout for API requests (seconds)
DEFAULT_TIMEOUT = 30


class WebSearch(BaseTool):
    """Tool for searching the web using Bocha or LinkAI search API"""

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
        self._backend = None  # Will be resolved on first execute

    @staticmethod
    def is_available() -> bool:
        """Check if web search is available (at least one API key is configured)"""
        return bool(os.environ.get("BOCHA_API_KEY") or os.environ.get("LINKAI_API_KEY"))

    def _resolve_backend(self) -> Optional[str]:
        """
        Determine which search backend to use.
        Priority: Bocha > LinkAI

        :return: 'bocha', 'linkai', or None
        """
        if os.environ.get("BOCHA_API_KEY"):
            return "bocha"
        if os.environ.get("LINKAI_API_KEY"):
            return "linkai"
        return None

    def execute(self, args: Dict[str, Any]) -> ToolResult:
        """
        Execute web search

        :param args: Search parameters (query, count, freshness, summary)
        :return: Search results
        """
        query = args.get("query", "").strip()
        if not query:
            return ToolResult.fail("Error: 'query' parameter is required")

        count = args.get("count", 10)
        freshness = args.get("freshness", "noLimit")
        summary = args.get("summary", False)

        # Validate count
        if not isinstance(count, int) or count < 1 or count > 50:
            count = 10

        # Resolve backend
        backend = self._resolve_backend()
        if not backend:
            return ToolResult.fail(
                "Error: No search API key configured. "
                "Please set BOCHA_API_KEY or LINKAI_API_KEY using env_config tool.\n"
                "  - Bocha Search: https://open.bocha.cn\n"
                "  - LinkAI Search: https://link-ai.tech"
            )

        try:
            if backend == "bocha":
                return self._search_bocha(query, count, freshness, summary)
            else:
                return self._search_linkai(query, count, freshness)
        except requests.Timeout:
            return ToolResult.fail(f"Error: Search request timed out after {DEFAULT_TIMEOUT}s")
        except requests.ConnectionError:
            return ToolResult.fail("Error: Failed to connect to search API")
        except Exception as e:
            logger.error(f"[WebSearch] Unexpected error: {e}", exc_info=True)
            return ToolResult.fail(f"Error: Search failed - {str(e)}")

    def _search_bocha(self, query: str, count: int, freshness: str, summary: bool) -> ToolResult:
        """
        Search using Bocha API

        :param query: Search query
        :param count: Number of results
        :param freshness: Time range filter
        :param summary: Whether to include summary
        :return: Formatted search results
        """
        api_key = os.environ.get("BOCHA_API_KEY", "")
        url = "https://api.bocha.cn/v1/web-search"

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }

        payload = {
            "query": query,
            "count": count,
            "freshness": freshness,
            "summary": summary
        }

        logger.debug(f"[WebSearch] Bocha search: query='{query}', count={count}")

        response = requests.post(url, headers=headers, json=payload, timeout=DEFAULT_TIMEOUT)

        if response.status_code == 401:
            return ToolResult.fail("Error: Invalid BOCHA_API_KEY. Please check your API key.")
        if response.status_code == 403:
            return ToolResult.fail("Error: Bocha API - insufficient balance. Please top up at https://open.bocha.cn")
        if response.status_code == 429:
            return ToolResult.fail("Error: Bocha API rate limit reached. Please try again later.")
        if response.status_code != 200:
            return ToolResult.fail(f"Error: Bocha API returned HTTP {response.status_code}")

        data = response.json()

        # Check API-level error code
        api_code = data.get("code")
        if api_code is not None and api_code != 200:
            msg = data.get("msg") or "Unknown error"
            return ToolResult.fail(f"Error: Bocha API error (code={api_code}): {msg}")

        # Extract and format results
        return self._format_bocha_results(data, query)

    def _format_bocha_results(self, data: dict, query: str) -> ToolResult:
        """
        Format Bocha API response into unified result structure

        :param data: Raw API response
        :param query: Original query
        :return: Formatted ToolResult
        """
        search_data = data.get("data", {})
        web_pages = search_data.get("webPages", {})
        pages = web_pages.get("value", [])

        if not pages:
            return ToolResult.success({
                "query": query,
                "backend": "bocha",
                "total": 0,
                "results": [],
                "message": "No results found"
            })

        results = []
        for page in pages:
            result = {
                "title": page.get("name", ""),
                "url": page.get("url", ""),
                "snippet": page.get("snippet", ""),
                "siteName": page.get("siteName", ""),
                "datePublished": page.get("datePublished") or page.get("dateLastCrawled", ""),
            }
            # Include summary only if present
            if page.get("summary"):
                result["summary"] = page["summary"]
            results.append(result)

        total = web_pages.get("totalEstimatedMatches", len(results))

        return ToolResult.success({
            "query": query,
            "backend": "bocha",
            "total": total,
            "count": len(results),
            "results": results
        })

    def _search_linkai(self, query: str, count: int, freshness: str) -> ToolResult:
        """
        Search using LinkAI plugin API

        :param query: Search query
        :param count: Number of results
        :param freshness: Time range filter
        :return: Formatted search results
        """
        api_key = os.environ.get("LINKAI_API_KEY", "")
        api_base = conf().get("linkai_api_base", "https://api.link-ai.tech")
        url = f"{api_base.rstrip('/')}/v1/plugin/execute"

        from common.utils import get_cloud_headers
        headers = get_cloud_headers(api_key)

        payload = {
            "code": "web-search",
            "args": {
                "query": query,
                "count": count,
                "freshness": freshness
            }
        }

        logger.debug(f"[WebSearch] LinkAI search: query='{query}', count={count}")

        response = requests.post(url, headers=headers, json=payload, timeout=DEFAULT_TIMEOUT)

        if response.status_code == 401:
            return ToolResult.fail("Error: Invalid LINKAI_API_KEY. Please check your API key.")
        if response.status_code != 200:
            return ToolResult.fail(f"Error: LinkAI API returned HTTP {response.status_code}")

        data = response.json()

        if not data.get("success"):
            msg = data.get("message") or "Unknown error"
            return ToolResult.fail(f"Error: LinkAI search failed: {msg}")

        return self._format_linkai_results(data, query)

    def _format_linkai_results(self, data: dict, query: str) -> ToolResult:
        """
        Format LinkAI API response into unified result structure.
        LinkAI returns the search data in data.data field, which follows
        the same Bing-compatible format as Bocha.

        :param data: Raw API response
        :param query: Original query
        :return: Formatted ToolResult
        """
        raw_data = data.get("data", "")

        # LinkAI may return data as a JSON string
        if isinstance(raw_data, str):
            try:
                raw_data = json.loads(raw_data)
            except (json.JSONDecodeError, TypeError):
                # If data is plain text, return it as a single result
                return ToolResult.success({
                    "query": query,
                    "backend": "linkai",
                    "total": 1,
                    "count": 1,
                    "results": [{"content": raw_data}]
                })

        # If the response follows Bing-compatible structure
        if isinstance(raw_data, dict):
            web_pages = raw_data.get("webPages", {})
            pages = web_pages.get("value", [])

            if pages:
                results = []
                for page in pages:
                    result = {
                        "title": page.get("name", ""),
                        "url": page.get("url", ""),
                        "snippet": page.get("snippet", ""),
                        "siteName": page.get("siteName", ""),
                        "datePublished": page.get("datePublished") or page.get("dateLastCrawled", ""),
                    }
                    if page.get("summary"):
                        result["summary"] = page["summary"]
                    results.append(result)

                total = web_pages.get("totalEstimatedMatches", len(results))
                return ToolResult.success({
                    "query": query,
                    "backend": "linkai",
                    "total": total,
                    "count": len(results),
                    "results": results
                })

        # Fallback: return raw data
        return ToolResult.success({
            "query": query,
            "backend": "linkai",
            "total": 1,
            "count": 1,
            "results": [{"content": str(raw_data)}]
        })
