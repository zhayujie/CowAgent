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
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from common.utils import expand_path


_AGENT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")

# Id of the built-in single agent, and the reserved alias by which the default
# agent can always be addressed (see AgentRegistry.get_addressed).
DEFAULT_AGENT_ALIAS = "default"


class AgentRegistryError(ValueError):
    """Raised when agent configuration is invalid."""


@dataclass(frozen=True)
class AgentProfile:
    """Configuration for one complete CowAgent workspace."""

    id: str
    name: str
    workspace: str
    #: What this Agent is for, in one line. Read by teammates: a name alone is
    #: enough to address someone but not to decide whose work something is.
    description: Optional[str] = None
    enabled: bool = True
    model: Optional[str] = None
    bot_type: Optional[str] = None
    avatar: Optional[str] = None
    # Which shared assets this Agent draws on. ``None`` means "all of them",
    # which is what every existing config means and what a new Agent gets;
    # an empty tuple is a real answer that differs from it, so the two cannot
    # collapse into one falsy case.
    skills: Optional[Tuple[str, ...]] = None
    knowledge: Optional[Tuple[str, ...]] = None

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
        if self.description:
            data["description"] = self.description
        if self.model:
            data["model"] = self.model
        if self.bot_type:
            data["bot_type"] = self.bot_type
        if self.avatar:
            data["avatar"] = self.avatar
        if self.skills is not None:
            data["skills"] = list(self.skills)
        if self.knowledge is not None:
            data["knowledge"] = list(self.knowledge)
        return data


def _normalise_workspace(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AgentRegistryError("agent workspace must be a non-empty string")
    return str(Path(expand_path(value.strip())).resolve(strict=False))


def _asset_selection(
    raw: Mapping[str, Any], agent_id: str, key: str
) -> Optional[Tuple[str, ...]]:
    """Parse an "only these shared assets" list, keeping absent distinct from empty.

    Absent means this Agent draws on everything, which is what every config
    written before the field existed means. A list, including an empty one,
    means the selection is deliberate.
    """
    value = raw.get(key)
    if value is None:
        return None
    if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
        raise AgentRegistryError(
            f"agent '{agent_id}' {key} must be a list of strings when set"
        )
    seen = []
    for name in value:
        name = name.strip()
        if name and name not in seen:
            seen.append(name)
    return tuple(seen)


def _profile_from_mapping(
    raw: Mapping[str, Any], default_workspace: Optional[str] = None
) -> AgentProfile:
    """Build one profile. ``default_workspace`` fills in an omitted workspace.

    Omitting it is the common case: what a second Agent needs is a persona and
    a name, and the shared skills, knowledge and credentials it reads live at
    the instance root either way. Spelling out a path per Agent is only worth
    it when one of them has to sit somewhere else, such as another disk.

    An empty string stays an error. Absent means "put it wherever you'd put a
    new one"; empty means the caller tried to say something and failed.
    """
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

    description = raw.get("description")
    if description is not None and not isinstance(description, str):
        raise AgentRegistryError(f"agent '{agent_id}' description must be a string")

    model = raw.get("model")
    bot_type = raw.get("bot_type")
    for key, value in (("model", model), ("bot_type", bot_type)):
        if value is not None and (not isinstance(value, str) or not value.strip()):
            raise AgentRegistryError(
                f"agent '{agent_id}' {key} must be a non-empty string when set"
            )

    workspace = raw.get("workspace")
    if workspace is None:
        workspace = default_workspace

    avatar = raw.get("avatar")
    if avatar is not None and not isinstance(avatar, str):
        raise AgentRegistryError(f"agent '{agent_id}' avatar must be a string")

    return AgentProfile(
        id=agent_id,
        name=name.strip(),
        workspace=_normalise_workspace(workspace),
        description=(description.strip() or None) if description else None,
        enabled=enabled,
        model=model.strip() if isinstance(model, str) else None,
        bot_type=bot_type.strip() if isinstance(bot_type, str) else None,
        avatar=avatar.strip() if isinstance(avatar, str) and avatar.strip() else None,
        skills=_asset_selection(raw, agent_id, "skills"),
        knowledge=_asset_selection(raw, agent_id, "knowledge"),
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
        instance_root = _normalise_workspace(settings.get("agent_workspace") or "~/cow")

        raw_agents = settings.get("agents")
        if raw_agents is None or raw_agents == []:
            # Single-agent install: the sole agent owns the instance root. Its id
            # is normally the built-in "default", but a provisioner may inject one
            # so the id is stable and meaningful from first boot; an invalid or
            # absent value falls back to "default" and never breaks startup.
            builtin_id = settings.get("default_agent_id")
            # A value injected via env may arrive as a non-string (e.g. an
            # all-digit id parsed as int), so coerce before validating.
            builtin_id = str(builtin_id).strip() if builtin_id is not None else ""
            if not builtin_id or not _AGENT_ID_RE.match(builtin_id):
                builtin_id = DEFAULT_AGENT_ALIAS
            builtin_name = settings.get("default_agent_name")
            builtin_name = str(builtin_name).strip() if builtin_name is not None else ""
            builtin_desc = settings.get("default_agent_description")
            builtin_desc = str(builtin_desc).strip() if builtin_desc is not None else ""
            profile = AgentProfile(
                id=builtin_id,
                name=builtin_name or "CowAgent",
                description=builtin_desc,
                workspace=instance_root,
            )
            return cls([profile], builtin_id)

        if not isinstance(raw_agents, list):
            raise AgentRegistryError("agents must be a list")
        for index, raw in enumerate(raw_agents):
            if not isinstance(raw, Mapping):
                raise AgentRegistryError(f"agents[{index}] must be an object")

        # Which entry inherits the instance root has to be settled before the
        # profiles are built, so the default is read off the raw list. An
        # explicit default that does not resolve is a configuration error and
        # must fail loudly, in _validate_default. An absent one falls back to
        # the first agent so that adding a second workspace does not require a
        # second setting.
        default_agent_id = settings.get("default_agent_id") or ""
        if not isinstance(default_agent_id, str):
            raise AgentRegistryError("default_agent_id must be a string")
        default_agent_id = default_agent_id.strip()
        if not default_agent_id:
            default_agent_id = next(
                (
                    str(raw.get("id"))
                    for raw in raw_agents
                    if raw.get("enabled", True) is True
                ),
                str(raw_agents[0].get("id")),
            )

        # The default Agent inherits the instance root, which is where a
        # single-Agent install already keeps everything: hand-writing an
        # `agents` list around an existing workspace must not silently relocate
        # it. Every other Agent lands under `agents/<id>/`.
        root = Path(instance_root)
        profiles: List[AgentProfile] = [
            _profile_from_mapping(
                raw,
                default_workspace=(
                    instance_root
                    if raw.get("id") == default_agent_id
                    else str(root / "agents" / str(raw.get("id") or ""))
                ),
            )
            for raw in raw_agents
        ]
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

    def get_addressed(self, agent_id: Optional[str], require_enabled: bool = True) -> AgentProfile:
        """The agent an inbound request addresses by id.

        Like ``get``, except that the reserved id ``"default"`` always means
        the default agent, whatever id it was actually given. Remote callers
        can therefore address the default agent without knowing its real id.
        Any other unknown id still raises, so a request is never silently
        answered by a different agent.
        """
        requested = (agent_id or "").strip()
        if requested == DEFAULT_AGENT_ALIAS:
            requested = ""
        return self.get(requested or None, require_enabled=require_enabled)

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
_registry_signature: Optional[tuple] = None
_registry_pinned: bool = False
_registry_lock = threading.Lock()


def _config_signature(settings: Mapping[str, Any]) -> tuple:
    from agent import team

    return (team.stamp(settings), settings.get("agent_workspace") or "")


def get_agent_registry() -> AgentRegistry:
    """Return the process-wide registry for the current configuration.

    Keyed on the settings it was built from rather than cached outright:
    resolving a workspace happens on hot paths, but config can still change
    under us - the console edits it, tests mutate it, and anything that
    resolved a path before load_config() saw the pre-config value.
    """

    global _registry_instance, _registry_signature
    import os

    from agent import team
    from config import conf

    settings = conf()
    signature = _config_signature(settings)
    with _registry_lock:
        if _registry_pinned and _registry_instance is not None:
            return _registry_instance
        if _registry_instance is None or _registry_signature != signature:
            # The roster is its own file; config.json only still holds it on an
            # install that has not written one yet. `resolve` hides which.
            settings = team.resolve(settings)
            try:
                _registry_instance = AgentRegistry.from_config(settings)
            except AgentRegistryError:
                # An invalid `agents`/`default_agent_id` block would otherwise
                # bubble all the way up through load_config() and take the whole
                # process down before the web console can bind — leaving a
                # desktop user with no UI to fix the very config that is broken.
                # Fall back to the default single agent so the app still starts;
                # the console can then edit the bad block. Source deployments
                # keep failing loudly so the developer sees the error at once.
                if os.environ.get("COW_DESKTOP") != "1":
                    raise
                from common.log import logger

                logger.error(
                    "[AgentRegistry] invalid 'agents' config; ignoring it and "
                    "starting with the default agent. Fix it in the console.",
                    exc_info=True,
                )
                fallback = {
                    k: v
                    for k, v in dict(settings).items()
                    if k not in ("agents", "default_agent_id")
                }
                _registry_instance = AgentRegistry.from_config(fallback)
            _registry_signature = signature
        return _registry_instance


def set_agent_registry(registry: Optional[AgentRegistry]) -> None:
    """Pin a registry, or pass None to go back to following configuration.

    A pinned registry survives config changes, which is what admin mutations
    (upsert, set_enabled) and tests need.
    """

    global _registry_instance, _registry_signature, _registry_pinned
    with _registry_lock:
        _registry_instance = registry
        _registry_signature = None
        _registry_pinned = registry is not None
