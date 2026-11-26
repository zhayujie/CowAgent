"""Synchronous SerpApi transport shared by web_search and web_fetch."""

import json
import os
from urllib.parse import quote_plus

import requests
from urllib3.exceptions import ReadTimeoutError

from common.media_download import MediaTooLargeError, read_response


class SerpApiError(Exception):
    """Safe to show to the caller; never includes a request URL or response body."""


def api_key(config: dict) -> str:
    tools = config.get("tools")
    search = tools.get("web_search") if isinstance(tools, dict) else None
    value = search.get("serpapi_api_key") if isinstance(search, dict) else None
    key = value.strip() if isinstance(value, str) else ""
    return key or os.environ.get("SERPAPI_API_KEY", "").strip()


def text(value, key: str) -> str:
    if not isinstance(value, str):
        return ""
    return value.replace(quote_plus(key), "[REDACTED]").replace(key, "[REDACTED]") if key else value


def _check_status(response, **kwargs):
    status = response.status_code
    if status == 200:
        return
    # Reject before Requests can read a redirect body to prepare Response.next.
    response.close()
    if status == 401:
        raise SerpApiError("Invalid SerpApi API key.")
    if status == 429:
        raise SerpApiError("SerpApi rate limit or quota reached.")
    raise SerpApiError(f"SerpApi returned HTTP {status}.")


def request_json(params: dict, key: str, *, connect_timeout: int, read_timeout: int,
                 max_bytes: int, read_seconds: int) -> dict:
    if not key:
        raise SerpApiError("Set tools.web_search.serpapi_api_key or SERPAPI_API_KEY.")
    try:
        response = requests.get(
            "https://serpapi.com/search.json", params={**params, "api_key": key},
            headers={"Accept-Encoding": "identity"}, timeout=(connect_timeout, read_timeout),
            stream=True, allow_redirects=False, hooks={"response": _check_status},
        )
        try:
            body = read_response(response, max_bytes, max_seconds=read_seconds)
        except requests.Timeout:
            raise SerpApiError(f"Reading the SerpApi response timed out after {read_seconds}s.") from None
        except requests.ConnectionError as exc:
            # Requests wraps socket read timeouts in ConnectionError while iterating the body.
            if isinstance(exc.__context__, ReadTimeoutError):
                raise SerpApiError(f"SerpApi request timed out after {read_timeout}s.") from None
            raise
        data = json.loads(body)
    except requests.ConnectTimeout:
        raise SerpApiError(f"SerpApi connection timed out after {connect_timeout}s.") from None
    except requests.Timeout:
        raise SerpApiError(f"SerpApi request timed out after {read_timeout}s.") from None
    except OSError:
        # Includes RequestException and invalid CA bundle paths. Don't echo the URL or key.
        raise SerpApiError("Failed to connect to or read from SerpApi.") from None
    except MediaTooLargeError:
        raise SerpApiError("SerpApi response exceeded the download limit.") from None
    except (ValueError, RecursionError):
        raise SerpApiError("Invalid SerpApi response.") from None
    if not isinstance(data, dict):
        raise SerpApiError("Invalid SerpApi response.")
    if "search_metadata" in data:
        metadata = data["search_metadata"]
        if not isinstance(metadata, dict) or metadata.get("status") != "Success":
            raise SerpApiError("SerpApi did not return a successful result.")
    if "error" in data:
        info = data.get("search_information")
        # Google reports a successful zero-hit search with a top-level error message.
        empty_google_search = (
            params.get("engine") == "google" and "search_metadata" in data
            and isinstance(info, dict) and info.get("organic_results_state") == "Fully empty"
            and data.get("organic_results", []) == []
        )
        if not empty_google_search:
            raise SerpApiError("SerpApi reported an error. Check the request and account quota.")
    return data
