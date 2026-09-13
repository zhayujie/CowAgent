"""Web search domains discovery tool.

Queries the AnySearch domain discovery endpoints:
  - GET /v1/domains             -> list top-level domains
  - GET /v1/sub-domains?domain= -> list sub-domains for a given domain
Free endpoints, do not consume quota.
"""

import json
import os

import requests

from agent.tools.base_tool import BaseTool, ToolResult
from common.log import logger
from agent.tools.utils.truncate import truncate_head


DEFAULT_TIMEOUT = 30


# NOTE: keep this key resolution in sync with web_search.py's _get_api_key("anysearch").
def _get_anysearch_api_key() -> str:
    from config import conf
    tools_cfg = conf().get("tools") or {}
    if not isinstance(tools_cfg, dict):
        return ""
    block = tools_cfg.get("web_search") or {}
    if not isinstance(block, dict):
        return ""
    key = (block.get("anysearch_api_key") or "").strip()
    return key or os.environ.get("ANYSEARCH_API_KEY", "").strip()


def _anysearch_anonymous_enabled() -> bool:
    from config import conf
    tools_cfg = conf().get("tools") or {}
    if not isinstance(tools_cfg, dict):
        return False
    block = tools_cfg.get("web_search") or {}
    if not isinstance(block, dict):
        return False
    return bool(block.get("anysearch_anonymous"))


class WebSearchDomains(BaseTool):
    """Tool for discovering AnySearch vertical search domains."""

    name: str = "web_search_domains"
    description: str = (
        "Discover AnySearch vertical search domains. "
        "Without a domain argument, lists top-level domains. "
        "With a domain argument (e.g. 'finance'), lists its sub-domains "
        "like 'finance.quote' or 'finance.news'. "
        "Free endpoint, does not consume quota."
    )

    params: dict = {
        "type": "object",
        "properties": {
            "domain": {
                "type": "string",
                "description": "Optional. Top-level domain to inspect (e.g. 'finance', 'code'). "
                               "If omitted, lists all top-level domains."
            }
        },
        "required": [],
    }

    @staticmethod
    def is_available() -> bool:
        """Available when anysearch is usable: key configured OR anonymous enabled."""
        return bool(_get_anysearch_api_key()) or _anysearch_anonymous_enabled()

    def execute(self, args: dict = None) -> ToolResult:
        args = args or {}
        domain = (args.get("domain") or "").strip()
        api_key = _get_anysearch_api_key()
        headers = {"Accept": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        if domain:
            url = f"https://api.anysearch.com/v1/sub-domains?domain={domain}"
        else:
            url = "https://api.anysearch.com/v1/domains"

        try:
            resp = requests.get(url, headers=headers, timeout=DEFAULT_TIMEOUT)
        except requests.Timeout:
            return ToolResult.fail(f"Error: domains request timed out after {DEFAULT_TIMEOUT}s")
        except requests.ConnectionError:
            return ToolResult.fail("Error: Failed to connect to AnySearch API")
        except Exception as e:
            logger.error(f"[WebSearchDomains] Unexpected error: {e}", exc_info=True)
            return ToolResult.fail(f"Error: domains request failed - {str(e)}")

        if resp.status_code == 401:
            return ToolResult.fail("Error: Invalid AnySearch API key.")
        if resp.status_code == 429:
            return ToolResult.fail("Error: AnySearch API rate limit reached.")
        if resp.status_code != 200:
            return ToolResult.fail(f"Error: AnySearch API returned HTTP {resp.status_code}: {resp.text[:200]}")

        data = resp.json()
        api_code = data.get("code")
        if api_code not in (0, None):
            msg = data.get("message") or "Unknown error"
            return ToolResult.fail(f"Error: AnySearch API error (code={api_code}): {msg}")

        inner = data.get("data") or {}
        domains = inner.get("domains") or []
        text = json.dumps(domains, ensure_ascii=False, indent=2)
        truncation = truncate_head(text)
        return ToolResult.success({
            "backend": "anysearch",
            "domains": truncation.content,
        })