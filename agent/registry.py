"""Agent profile registry.

The registry is deliberately small: an agent is identified by a stable ID and
one complete CowAgent workspace. Runtime, routing, and persistence layers build
on this module without changing the existing single-agent configuration path.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional

from common.utils import expand_path


_AGENT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


class AgentRegistryError(ValueError):
    """Raised when agent configuration is invalid."""


@dataclass(frozen=True)
class AgentProfile:
    """Configuration for one complete CowAgent workspace."""

    id: str
    name: str
    workspace: str
    enabled: bool = True
    model: Optional[str] = None
    bot_type: Optional[str] = None

    @property
    def workspace_path(self) -> Path:
        return Path(self.workspace)

    def to_dict(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "id": self.id,
            "name": self.name,
            "workspace": self.workspace,
            "enabled": self.enabled,
        }
        if self.model:
            data["model"] = self.model
        if self.bot_type:
            data["bot_type"] = self.bot_type
        return data


def _normalise_workspace(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AgentRegistryError("agent workspace must be a non-empty string")
    return str(Path(expand_path(value.strip())).resolve(strict=False))


def _profile_from_mapping(raw: Mapping[str, Any]) -> AgentProfile:
    agent_id = raw.get("id")
    if not isinstance(agent_id, str) or not _AGENT_ID_RE.fullmatch(agent_id):
        raise AgentRegistryError(
            "agent id must be 1-64 URL-safe characters: letters, numbers, _ or -"
        )

    name = raw.get("name", agent_id)
    if not isinstance(name, str) or not name.strip():
        raise AgentRegistryError(f"agent '{agent_id}' name must be a non-empty string")

    enabled = raw.get("enabled", True)
    if not isinstance(enabled, bool):
        raise AgentRegistryError(f"agent '{agent_id}' enabled must be a boolean")

    model = raw.get("model")
    bot_type = raw.get("bot_type")
    for key, value in (("model", model), ("bot_type", bot_type)):
        if value is not None and (not isinstance(value, str) or not value.strip()):
            raise AgentRegistryError(
                f"agent '{agent_id}' {key} must be a non-empty string when set"
            )

    return AgentProfile(
        id=agent_id,
        name=name.strip(),
        workspace=_normalise_workspace(raw.get("workspace")),
        enabled=enabled,
        model=model.strip() if isinstance(model, str) else None,
        bot_type=bot_type.strip() if isinstance(bot_type, str) else None,
    )


class AgentRegistry:
    """Thread-safe registry of configured agent workspaces."""

    def __init__(self, profiles: Iterable[AgentProfile], default_agent_id: str):
        self._lock = threading.RLock()
        self._profiles: Dict[str, AgentProfile] = {}
        self._default_agent_id = default_agent_id

        workspaces: Dict[str, str] = {}
        for profile in profiles:
            if profile.id in self._profiles:
                raise AgentRegistryError(f"duplicate agent id: {profile.id}")
            owner = workspaces.get(profile.workspace)
            if owner is not None:
                raise AgentRegistryError(
                    f"agents '{owner}' and '{profile.id}' share workspace "
                    f"'{profile.workspace}'"
                )
            self._profiles[profile.id] = profile
            workspaces[profile.workspace] = profile.id

        if not self._profiles:
            raise AgentRegistryError("at least one agent profile is required")
        self._validate_default(default_agent_id)

    @classmethod
    def from_config(cls, settings: Mapping[str, Any]) -> "AgentRegistry":
        raw_agents = settings.get("agents")
        if raw_agents is None or raw_agents == []:
            workspace = settings.get("agent_workspace", "~/cow")
            profile = AgentProfile(
                id="default",
                name="Default",
                workspace=_normalise_workspace(workspace),
            )
            return cls([profile], "default")

        if not isinstance(raw_agents, list):
            raise AgentRegistryError("agents must be a list")
        profiles: List[AgentProfile] = []
        for index, raw in enumerate(raw_agents):
            if not isinstance(raw, Mapping):
                raise AgentRegistryError(f"agents[{index}] must be an object")
            profiles.append(_profile_from_mapping(raw))

        default_agent_id = settings.get("default_agent_id", "default")
        if not isinstance(default_agent_id, str) or not default_agent_id:
            raise AgentRegistryError("default_agent_id must be a non-empty string")
        return cls(profiles, default_agent_id)

    @property
    def default_agent_id(self) -> str:
        with self._lock:
            return self._default_agent_id

    def _validate_default(self, agent_id: str) -> None:
        profile = self._profiles.get(agent_id)
        if profile is None:
            raise AgentRegistryError(f"default agent '{agent_id}' is not configured")
        if not profile.enabled:
            raise AgentRegistryError(f"default agent '{agent_id}' is disabled")

    def get(self, agent_id: Optional[str] = None, require_enabled: bool = True) -> AgentProfile:
        with self._lock:
            resolved_id = agent_id or self._default_agent_id
            profile = self._profiles.get(resolved_id)
            if profile is None:
                raise KeyError(resolved_id)
            if require_enabled and not profile.enabled:
                raise AgentRegistryError(f"agent '{resolved_id}' is disabled")
            return profile

    def get_or_default(self, agent_id: Optional[str]) -> AgentProfile:
        with self._lock:
            profile = self._profiles.get(agent_id) if agent_id else None
            if profile is not None and profile.enabled:
                return profile
            return self._profiles[self._default_agent_id]

    def list(self, include_disabled: bool = True) -> List[AgentProfile]:
        with self._lock:
            profiles = list(self._profiles.values())
            if not include_disabled:
                profiles = [profile for profile in profiles if profile.enabled]
            return sorted(profiles, key=lambda profile: profile.id)

    def upsert(self, profile: AgentProfile) -> None:
        with self._lock:
            for existing in self._profiles.values():
                if existing.id != profile.id and existing.workspace == profile.workspace:
                    raise AgentRegistryError(
                        f"agents '{existing.id}' and '{profile.id}' share workspace "
                        f"'{profile.workspace}'"
                    )
            self._profiles[profile.id] = profile
            self._validate_default(self._default_agent_id)

    def set_enabled(self, agent_id: str, enabled: bool) -> AgentProfile:
        with self._lock:
            current = self.get(agent_id, require_enabled=False)
            if agent_id == self._default_agent_id and not enabled:
                raise AgentRegistryError("the default agent cannot be disabled")
            updated = replace(current, enabled=enabled)
            self._profiles[agent_id] = updated
            return updated

    def set_default(self, agent_id: str) -> None:
        with self._lock:
            profile = self.get(agent_id, require_enabled=True)
            self._default_agent_id = profile.id

    def remove(self, agent_id: str) -> AgentProfile:
        with self._lock:
            if agent_id == self._default_agent_id:
                raise AgentRegistryError("the default agent cannot be removed")
            try:
                return self._profiles.pop(agent_id)
            except KeyError:
                raise KeyError(agent_id) from None


_registry_instance: Optional[AgentRegistry] = None
_registry_lock = threading.Lock()


def get_agent_registry() -> AgentRegistry:
    """Return the process-wide registry built from the current configuration."""

    global _registry_instance
    if _registry_instance is not None:
        return _registry_instance
    with _registry_lock:
        if _registry_instance is None:
            from config import conf

            _registry_instance = AgentRegistry.from_config(conf())
        return _registry_instance


def set_agent_registry(registry: Optional[AgentRegistry]) -> None:
    """Replace the process registry, primarily for config reloads and tests."""

    global _registry_instance
    with _registry_lock:
        _registry_instance = registry
