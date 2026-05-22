"""
Configuration support for skills.
"""

import os
import platform
from typing import Dict, Optional, List
from agent.skills.types import SkillEntry


def resolve_runtime_platform() -> str:
    """Get the current runtime platform."""
    return platform.system().lower()


def has_binary(bin_name: str) -> bool:
    """
    Check if a binary is available in PATH.
    
    :param bin_name: Binary name to check
    :return: True if binary is available
    """
    import shutil
    return shutil.which(bin_name) is not None


def has_any_binary(bin_names: List[str]) -> bool:
    """
    Check if any of the given binaries is available.
    
    :param bin_names: List of binary names to check
    :return: True if at least one binary is available
    """
    return any(has_binary(bin_name) for bin_name in bin_names)


def has_env_var(env_name: str) -> bool:
    """
    Check if an environment variable is set.
    
    :param env_name: Environment variable name
    :return: True if environment variable is set
    """
    return env_name in os.environ and bool(os.environ[env_name].strip())


def get_skill_config(config: Optional[Dict], skill_name: str) -> Optional[Dict]:
    """
    Get skill-specific configuration.
    
    :param config: Global configuration dictionary
    :param skill_name: Name of the skill
    :return: Skill configuration or None
    """
    if not config:
        return None
    
    skills_config = config.get('skills', {})
    if not isinstance(skills_config, dict):
        return None
    
    entries = skills_config.get('entries', {})
    if not isinstance(entries, dict):
        return None
    
    return entries.get(skill_name)


def should_include_skill(
    entry: SkillEntry,
    config: Optional[Dict] = None,
    current_platform: Optional[str] = None,
) -> bool:
    """
    Determine if a skill should be included based on requirements.
    
    Simple rule: Skills are auto-enabled if their requirements are met.
    - Has required API keys → enabled
    - Missing API keys → disabled
    - Wrong keys → enabled but will fail at runtime (LLM will handle error)
    
    :param entry: SkillEntry to check
    :param config: Configuration dictionary (currently unused, reserved for future)
    :param current_platform: Current platform (default: auto-detect)
    :return: True if skill should be included
    """
    metadata = entry.metadata
    
    # No metadata = always include (no requirements)
    if not metadata:
        return True
    
    # Check platform requirements (can't work on wrong platform)
    if metadata.os:
        platform_name = current_platform or resolve_runtime_platform()
        # Map common platform names
        platform_map = {
            'darwin': 'darwin',
            'linux': 'linux',
            'windows': 'win32',
        }
        normalized_platform = platform_map.get(platform_name, platform_name)
        
        if normalized_platform not in metadata.os:
            return False
    
    # If skill has 'always: true', include it regardless of other requirements
    if metadata.always:
        return True
    
    # Check requirements
    if metadata.requires:
        # Check required binaries (all must be present)
        required_bins = metadata.requires.get('bins', [])
        if required_bins:
            if not all(has_binary(bin_name) for bin_name in required_bins):
                return False
        
        # Check anyBins (at least one must be present)
        any_bins = metadata.requires.get('anyBins', [])
        if any_bins:
            if not has_any_binary(any_bins):
                return False
        
        # Check environment variables (API keys)
        # All required env vars must be set
        required_env = metadata.requires.get('env', [])
        if required_env:
            for env_name in required_env:
                if not has_env_var(env_name):
                    return False

        # Check anyEnv (at least one must be present)
        any_env = metadata.requires.get('anyEnv', [])
        if any_env:
            if not any(has_env_var(e) for e in any_env):
                return False
    
    return True


def get_missing_requirements(
    entry: SkillEntry,
    current_platform: Optional[str] = None,
) -> Dict[str, List[str]]:
    """
    Return a dict of missing requirements for a skill.
    Empty dict means all requirements are met.

    :param entry: SkillEntry to check
    :param current_platform: Current platform (default: auto-detect)
    :return: Dict like {"bins": ["curl"], "env": ["API_KEY"]}
    """
    missing: Dict[str, List[str]] = {}
    metadata = entry.metadata

    if not metadata or not metadata.requires:
        return missing

    required_bins = metadata.requires.get('bins', [])
    if required_bins:
        missing_bins = [b for b in required_bins if not has_binary(b)]
        if missing_bins:
            missing['bins'] = missing_bins

    any_bins = metadata.requires.get('anyBins', [])
    if any_bins and not has_any_binary(any_bins):
        missing['anyBins'] = any_bins

    required_env = metadata.requires.get('env', [])
    if required_env:
        missing_env = [e for e in required_env if not has_env_var(e)]
        if missing_env:
            missing['env'] = missing_env

    any_env = metadata.requires.get('anyEnv', [])
    if any_env and not any(has_env_var(e) for e in any_env):
        missing['anyEnv'] = any_env

    return missing


def is_config_path_truthy(config: Dict, path: str) -> bool:
    """
    Check if a config path resolves to a truthy value.
    
    :param config: Configuration dictionary
    :param path: Dot-separated path (e.g., 'skills.enabled')
    :return: True if path resolves to truthy value
    """
    parts = path.split('.')
    current = config
    
    for part in parts:
        if not isinstance(current, dict):
            return False
        current = current.get(part)
        if current is None:
            return False
    
    # Check if value is truthy
    if isinstance(current, bool):
        return current
    if isinstance(current, (int, float)):
        return current != 0
    if isinstance(current, str):
        return bool(current.strip())
    
    return bool(current)


def resolve_config_path(config: Dict, path: str):
    """
    Resolve a dot-separated config path to its value.
    
    :param config: Configuration dictionary
    :param path: Dot-separated path
    :return: Value at path or None
    """
    parts = path.split('.')
    current = config
    
    for part in parts:
        if not isinstance(current, dict):
            return None
        current = current.get(part)
        if current is None:
            return None
    
    return current
