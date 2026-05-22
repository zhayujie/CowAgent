"""Shared utilities for cow CLI."""

import os
import sys
import json


def get_project_root() -> str:
    """Get the CowAgent project root directory."""
    # cli/ is directly under the project root
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def get_workspace_dir() -> str:
    """Get the agent workspace directory from config, defaulting to ~/cow."""
    config = load_config_json()
    workspace = config.get("agent_workspace", "~/cow")
    return os.path.expanduser(workspace)


def get_skills_dir() -> str:
    """Get the custom skills directory."""
    return os.path.join(get_workspace_dir(), "skills")


def get_builtin_skills_dir() -> str:
    """Get the builtin skills directory."""
    return os.path.join(get_project_root(), "skills")


def load_config_json() -> dict:
    """Load config.json from project root."""
    config_path = os.path.join(get_project_root(), "config.json")
    if not os.path.exists(config_path):
        return {}
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def load_skills_config() -> dict:
    """Load skills_config.json from the custom skills directory."""
    path = os.path.join(get_skills_dir(), "skills_config.json")
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def ensure_sys_path():
    """Add project root to sys.path so we can import agent modules."""
    root = get_project_root()
    if root not in sys.path:
        sys.path.insert(0, root)


SKILL_HUB_API = "https://skills.cowagent.ai/api"
