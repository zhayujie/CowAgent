"""Web extract tool - full readable text extraction via AnySearch API.

Use as a fallback when web_fetch fails (403/anti-bot/JS-rendered pages)
or the local network cannot reach the site. HTML pages only.
"""

import os

import requests

from agent.tools.base_tool import BaseTool, ToolResult
from common.log import logger
from agent.tools.utils.truncate import truncate_head


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


# NOTE: keep this in sync with web_search_domains.py's _anysearch_anonymous_enabled().
def _anysearch_anonymous_enabled() -> bool:
    from config import conf
    tools_cfg = conf().get("tools") or {}
    if not isinstance(tools_cfg, dict):
        return False
    block = tools_cfg.get("web_search") or {}
    if not isinstance(block, dict):
        return False
    return bool(block.get("anysearch_anonymous"))


def _error_body(resp) -> dict:
    """Best-effort parse of an error response body; {} when it is not a JSON object."""
    try:
        body = resp.json()
    except (ValueError, TypeError):
        return {}
    return body if isinstance(body, dict) else {}


def _api_detail(body: dict) -> str:
    """': <message>' suffix built from an AnySearch error body, '' when absent."""
    detail = (body.get("message") or "").strip()
    return f": {detail}" if detail else ""


DEFAULT_TIMEOUT = 30


class WebExtract(BaseTool):
    """Tool for extracting full readable text from a web page URL."""

    name: str = "web_extract"
    description: str = (
        "Extract full readable text from a web page URL via the AnySearch extraction API. "
        "Use as a fallback when web_fetch fails (403/anti-bot/JS-rendered pages) or the local "
        "network cannot reach the site. HTML pages only - PDF/DOCX and other binaries are not "
        "supported (use web_fetch for those)."
    )

    params: dict = {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "The HTTP/HTTPS URL to extract readable text from"
            }
        },
        "required": ["url"],
    }

    @staticmethod
    def is_available() -> bool:
        """Available when AnySearch is usable: key configured OR anonymous enabled.

        Mirrors web_search_domains.is_available() - registering the tool
        unconditionally would silently burn anonymous quota for users who
        never opted into AnySearch.
        """
        return bool(_get_anysearch_api_key()) or _anysearch_anonymous_enabled()

    def execute(self, args: dict) -> ToolResult:
        url = (args.get("url") or "").strip()
        if not url:
            return ToolResult.fail("Error: 'url' parameter is required")
        if not url.lower().startswith(("http://", "https://")):
            return ToolResult.fail("Error: URL must start with http:// or https://")

        api_key = _get_anysearch_api_key()
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        payload = {"url": url}
        endpoint = "https://api.anysearch.com/v1/extract"

        try:
            resp = requests.post(endpoint, headers=headers, json=payload, timeout=DEFAULT_TIMEOUT)
        except requests.Timeout:
            return ToolResult.fail(f"Error: extract request timed out after {DEFAULT_TIMEOUT}s")
        except requests.ConnectionError:
            return ToolResult.fail("Error: Failed to connect to AnySearch extraction API")
        except Exception as e:
            logger.error(f"[WebExtract] Unexpected error: {e}", exc_info=True)
            return ToolResult.fail(f"Error: extract failed - {str(e)}")

        # Error mapping per spec (8.5f). The AnySearch error envelope carries the
        # machine-readable reason in `error_code` (`code` is -1 on every failure),
        # so branch on `error_code`; on a mismatch surface the API `message`.
        if resp.status_code == 400:
            body = _error_body(resp)
            if body.get("error_code") == "invalid_extract_url":
                return ToolResult.fail("Error: invalid URL for extraction")
            return ToolResult.fail(f"Error: invalid URL for extraction{_api_detail(body)}")
        if resp.status_code == 401:
            return ToolResult.fail("Error: Invalid AnySearch API key.")
        if resp.status_code == 402:
            if api_key:
                return ToolResult.fail("Error: AnySearch quota exhausted. Check usage at https://anysearch.com")
            return ToolResult.fail(
                "Error: AnySearch anonymous quota exhausted. Configure an API key at https://anysearch.com for higher limits.")
        if resp.status_code == 422:
            body = _error_body(resp)
            if body.get("error_code") == "extract_failed":
                return ToolResult.fail("Error: extraction failed (page empty or blocked)")
            return ToolResult.fail(f"Error: extraction failed{_api_detail(body)}")
        if resp.status_code == 429:
            return ToolResult.fail("Error: AnySearch API rate limit reached.")
        if resp.status_code != 200:
            return ToolResult.fail(f"Error: AnySearch API returned HTTP {resp.status_code}")

        data = resp.json()
        api_code = data.get("code")
        if api_code not in (0, None):
            msg = data.get("message") or "Unknown error"
            return ToolResult.fail(f"Error: AnySearch API error (code={api_code}): {msg}")

        # Success path: same plain-text shape as web_fetch ("Title: ...\n\nContent: ..."),
        # so the agent can fall back from web_fetch to web_extract without any
        # output-format handling of its own.
        inner = data.get("data") or {}
        title = inner.get("title") or ""
        content = inner.get("content") or ""
        truncation = truncate_head(content)
        text = f"Title: {title}\n\nContent:\n{truncation.content}"
        if truncation.truncated:
            text += (f"\n\n[Content truncated: showing {truncation.output_lines} of "
                     f"{truncation.total_lines} lines]")
        return ToolResult.success(text)
