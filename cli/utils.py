"""Shared utilities for cow CLI."""

import hashlib
import os
import re
import sys
import json


def get_project_root() -> str:
    """Get the CowAgent project root directory."""
    # cli/ is directly under the project root
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _ensure_project_on_path() -> None:
    root = get_project_root()
    if root not in sys.path:
        sys.path.insert(0, root)


def get_workspace_dir(agent_id: str = None) -> str:
    """Workspace directory of an Agent, defaulting to the configured default.

    The CLI runs out of process and reads config.json itself, but resolves it
    through the same registry as the gateway so both agree on where an Agent's
    files live. The roster lives in its own team.json, not in config.json, so
    it has to be overlaid or every Agent but the default goes unresolved.
    """
    _ensure_project_on_path()
    from agent import team
    from agent.registry import AgentRegistry

    registry = AgentRegistry.from_config(team.resolve(load_config_json()))
    return registry.get(agent_id, require_enabled=False).workspace


def get_skills_dir(agent_id: str = None) -> str:
    """Get the custom skills directory."""
    _ensure_project_on_path()
    from common import state_dir

    return str(state_dir.skills_dir(base=get_workspace_dir(agent_id)))


def get_knowledge_dir(agent_id: str = None) -> str:
    """Get the knowledge base directory."""
    _ensure_project_on_path()
    from common import state_dir

    return str(state_dir.knowledge_dir(base=get_workspace_dir(agent_id)))


def get_builtin_skills_dir() -> str:
    """Get the builtin skills directory."""
    return os.path.join(get_project_root(), "skills")


def get_data_root() -> str:
    # Mirrors config.get_data_root(): the desktop build keeps its data in
    # COW_DATA_DIR, outside the read-only app bundle.
    data_dir = os.environ.get("COW_DATA_DIR")
    return os.path.expanduser(data_dir) if data_dir else get_project_root()


def get_device_dir() -> str:
    # Mirrors config.get_device_dir(), without creating it.
    data_dir = os.environ.get("COW_DATA_DIR")
    if data_dir:
        return os.path.join(os.path.expanduser(data_dir), "device")
    real = os.path.realpath(get_project_root())
    name = re.sub(r"[^A-Za-z0-9._-]", "", os.path.basename(real))[:40] or "cow"
    digest = hashlib.sha256(real.encode("utf-8", "surrogatepass")).hexdigest()[:8]
    return os.path.join(os.path.expanduser("~/.cow"), "device", f"{name}-{digest}")


def _config_json_path() -> str:
    return os.path.join(get_data_root(), "config.json")


def load_config_json() -> dict:
    """Load config.json from the data root (the project root outside the desktop build)."""
    config_path = _config_json_path()
    if not os.path.exists(config_path):
        return {}
    try:
        _ensure_project_on_path()
        from cli.config_json import merge_duplicate_keys

        with open(config_path, "r", encoding="utf-8-sig") as f:
            value = json.load(f, object_pairs_hook=merge_duplicate_keys)
            return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def get_cli_language() -> str:
    """Resolve the CLI UI language using the shared i18n detector.

    Reads the `cow_lang` field from config.json (defaults to "auto") and runs
    the same detection used by the running app, so CLI output matches.
    """
    ensure_sys_path()
    try:
        from common import i18n

        configured = load_config_json().get("cow_lang", "auto")
        return i18n.resolve_language(configured)
    except Exception:
        return "en"


def load_skills_config(agent_id: str = None) -> dict:
    """Load skills_config.json from an Agent's skills directory."""
    path = os.path.join(get_skills_dir(agent_id), "skills_config.json")
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    except Exception:
        return {}


def ensure_sys_path():
    """Add project root to sys.path so we can import agent modules."""
    root = get_project_root()
    if root not in sys.path:
        sys.path.insert(0, root)


SKILL_HUB_API = "https://skills.cowagent.ai/api"


def _skill_hub_setting(key: str) -> str:
    # In process the loaded config (env overrides included) is the truth; the
    # out-of-process CLI has not loaded it and reads config.json instead.
    value = ""
    try:
        ensure_sys_path()
        from config import conf

        value = conf().get(key) or ""
    except Exception:
        pass
    if not value:
        value = load_config_json().get(key) or ""
    return value.strip() if isinstance(value, str) else ""


def _usable_hub_url(url: str) -> bool:
    from urllib.parse import urlparse

    parsed = urlparse(url)
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def custom_skill_hub() -> bool:
    """Whether ``skill_hub_url`` points requests at a registry other than the default."""
    url = _skill_hub_setting("skill_hub_url")
    return bool(url) and _usable_hub_url(url)


def skill_hub(provider: str = None) -> tuple:
    """Base URL and request headers for a Skill Hub request.

    ``skill_hub_url`` replaces the default hub for requests that name no
    provider: installs by bare name, search and the remote listing. Requests
    for a provider (github:, clawhub:, ...) are what the default hub proxies,
    so they keep going there. ``skill_hub_api_key`` only ever goes to the
    configured registry.
    """
    if provider or not custom_skill_hub():
        return SKILL_HUB_API, {}
    headers = {}
    key = _skill_hub_setting("skill_hub_api_key")
    if key:
        headers["Authorization"] = f"Bearer {key}"
    return _skill_hub_setting("skill_hub_url").rstrip("/"), headers
