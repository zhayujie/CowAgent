"""Owner and workspace-memory settings for a single Feishu application."""

import re


OWNER_IDS = "feishu_owner_open_ids"
LEGACY_OWNER_ID = "feishu_owner_open_id"
LEGACY_SHARE_MEMORY = "feishu_share_workspace_memory"
MEMORY_MODE = "feishu_private_memory_mode"
DEFAULT_MEMORY_MODE = "owner_workspace"
MEMORY_MODES = (DEFAULT_MEMORY_MODE, "per_user", "shared")


def _is_open_id(value):
    return isinstance(value, str) and re.fullmatch(r"ou_[A-Za-z0-9_-]+", value) is not None


def parse_owner_ids(value):
    """Accept a JSON list or comma/whitespace-delimited form input."""
    if isinstance(value, str):
        value = [item for item in re.split(r"[,，\s]+", value) if item]
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not _is_open_id(item.strip())
        for item in value
    ):
        raise ValueError("Feishu Owner IDs must be open_ids starting with ou_")
    return list(dict.fromkeys(item.strip() for item in value))


def owner_ids(settings):
    try:
        return parse_owner_ids(settings.get(OWNER_IDS, []))
    except ValueError:
        return []


def registration_owner_id(result):
    user_info = result.get("user_info")
    candidate = user_info.get("open_id") if isinstance(user_info, dict) else None
    if _is_open_id(candidate):
        return candidate
    return ""


def lookup_application_owner(app_id, app_secret):
    """Find an enterprise-member owner using the queried app's own identity."""
    import requests
    from channel.feishu.domain import FEISHU_DOMAIN, LARK_DOMAIN, WRONG_DOMAIN_CODE

    if not re.fullmatch(r"cli_[A-Za-z0-9_-]+", app_id) or not isinstance(app_secret, str) or not app_secret:
        return ""
    for domain in (FEISHU_DOMAIN, LARK_DOMAIN):
        try:
            token_response = requests.post(
                domain + "/open-apis/auth/v3/tenant_access_token/internal/",
                json={"app_id": app_id, "app_secret": app_secret}, timeout=(3, 5), allow_redirects=False,
            ).json()
            if token_response.get("code") != 0 or not token_response.get("tenant_access_token"):
                continue
            response = requests.get(
                f"{domain}/open-apis/application/v6/applications/{app_id}",
                params={"lang": "zh_cn", "user_id_type": "open_id"},
                headers={"Authorization": "Bearer " + token_response["tenant_access_token"]},
                timeout=(3, 5), allow_redirects=False,
            ).json()
            if response.get("code") == WRONG_DOMAIN_CODE:
                continue
            app = (response.get("data") or {}).get("app") or {}
            owner = app.get("owner") or {}
            candidate = owner.get("owner_id")
            if (response.get("code") == 0 and app.get("app_id") == app_id and
                    owner.get("type") == 2 and _is_open_id(candidate)):
                return candidate
            return ""
        except (requests.RequestException, ValueError, TypeError, AttributeError):
            return ""
    return ""


def memory_mode(settings):
    value = settings.get(MEMORY_MODE)
    return value if value in MEMORY_MODES else DEFAULT_MEMORY_MODE


def reset_replaced_app_settings(previous, updates):
    """Prevent an edited App ID from carrying over the old bot's trust."""
    if "feishu_app_id" not in updates or updates["feishu_app_id"] == previous.get("feishu_app_id"):
        return
    if OWNER_IDS not in updates or updates[OWNER_IDS] == owner_ids(previous):
        updates[OWNER_IDS] = []
    if MEMORY_MODE not in updates or updates[MEMORY_MODE] == "shared":
        updates[MEMORY_MODE] = DEFAULT_MEMORY_MODE
