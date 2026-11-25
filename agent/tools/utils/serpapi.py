"""Synchronous SerpApi transport shared by web_search and web_fetch."""

import http.client
import json
import os
import socket
import time
from urllib.parse import quote_plus

import requests
from requests.adapters import HTTPAdapter
from urllib3.exceptions import HTTPError, ReadTimeoutError


class SerpApiError(Exception):
    """Safe to show to the caller; never includes a request URL or response body."""


class _SerpApiAdapter(HTTPAdapter):
    """Keep the query-string credential out of Requests' and urllib3's logged URLs."""

    def __init__(self, key):
        self._key_suffix = "&api_key=" + quote_plus(key)
        super().__init__(max_retries=0)

    def _configure_https_pool(self, manager):
        pool_class = manager.pool_classes_by_scheme["https"]
        suffix = self._key_suffix

        class Connection(pool_class.ConnectionCls):
            debuglevel = 0

            def putrequest(self, method, url, *args, **kwargs):
                if method == "GET" and url.startswith("/search.json?"):
                    url += suffix
                return super().putrequest(method, url, *args, **kwargs)

        class Pool(pool_class):
            ConnectionCls = Connection

        # urllib3 can share the default map between managers. Change only this
        # adapter's copy, retaining the proxy's own connection type if present.
        manager.pool_classes_by_scheme = dict(manager.pool_classes_by_scheme, https=Pool)

    def init_poolmanager(self, *args, **kwargs):
        super().init_poolmanager(*args, **kwargs)
        self._configure_https_pool(self.poolmanager)

    def proxy_manager_for(self, proxy, **kwargs):
        if proxy not in self.proxy_manager:
            self._configure_https_pool(super().proxy_manager_for(proxy, **kwargs))
        return self.proxy_manager[proxy]


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
        with requests.Session() as session:
            endpoint = "https://serpapi.com/search.json"
            session.mount(endpoint, _SerpApiAdapter(key))
            with session.get(endpoint, params=params, headers={"Accept-Encoding": "identity"},
                             timeout=(connect_timeout, read_timeout), stream=True, allow_redirects=False,
                             hooks={"response": _check_status}) as response:
                # Older urllib3 versions expose read1 only on the stdlib response.
                read1 = getattr(response.raw, "read1", None) or response.raw._original_response.read1
                deadline = time.monotonic() + read_seconds
                body = bytearray()
                while True:
                    chunk = read1(min(65536, max_bytes + 1 - len(body)))
                    if time.monotonic() > deadline:
                        raise SerpApiError(f"Reading the SerpApi response timed out after {read_seconds}s.")
                    if not chunk:
                        break
                    body.extend(chunk)
                    if len(body) > max_bytes:
                        raise SerpApiError("SerpApi response exceeded the download limit.")
        data = json.loads(body)
    except requests.ConnectTimeout:
        raise SerpApiError(f"SerpApi connection timed out after {connect_timeout}s.") from None
    except (requests.Timeout, ReadTimeoutError, socket.timeout):
        raise SerpApiError(f"SerpApi request timed out after {read_timeout}s.") from None
    except (requests.RequestException, HTTPError, OSError, http.client.HTTPException):
        raise SerpApiError("Failed to connect to or read from SerpApi.") from None
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
