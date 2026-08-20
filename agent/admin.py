"""Safe configuration and core-file management for agent workspaces."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import threading
from pathlib import Path
from typing import Dict, Mapping, Optional

from agent.registry import AgentProfile, AgentRegistry
from agent.routing import AgentRouter
from common.utils import expand_path


CORE_FILES = ("AGENT.md", "USER.md", "RULE.md", "MEMORY.md", "BOOTSTRAP.md")
MAX_CORE_FILE_BYTES = 1024 * 1024


class AgentAdminError(ValueError):
    pass


class StaleAgentFileError(AgentAdminError):
    pass


def _revision(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


class AgentAdminService:
    """Manage profiles without ever deleting an agent workspace implicitly."""

    def __init__(self, config_path: str, settings: Optional[Mapping] = None):
        self.config_path = Path(config_path)
        self._settings = dict(settings) if settings is not None else None
        self._lock = threading.RLock()

    def _load(self) -> Dict:
        if self._settings is not None:
            return dict(self._settings)
        if not self.config_path.exists():
            return {}
        with self.config_path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        if not isinstance(data, dict):
            raise AgentAdminError("config root must be an object")
        return data

    def _save(self, settings: Dict) -> None:
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(
            prefix=f".{self.config_path.name}.",
            suffix=".tmp",
            dir=str(self.config_path.parent),
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(settings, handle, indent=4, ensure_ascii=False)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, self.config_path)
        except Exception:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise
        self._settings = dict(settings)

    @staticmethod
    def _registry(settings: Mapping) -> AgentRegistry:
        return AgentRegistry.from_config(settings)

    @staticmethod
    def _explicit_profiles(settings: Dict, registry: AgentRegistry) -> list:
        raw_agents = settings.get("agents")
        if raw_agents:
            return [dict(item) for item in raw_agents]
        return [registry.get().to_dict()]

    @staticmethod
    def _serialise_registry(settings: Dict, profiles: list, default_agent_id: str):
        settings["agents"] = profiles
        settings["default_agent_id"] = default_agent_id
        return settings

    def snapshot(self) -> Dict:
        with self._lock:
            settings = self._load()
            registry = self._registry(settings)
            return {
                "default_agent_id": registry.default_agent_id,
                "agents": [profile.to_dict() for profile in registry.list()],
                "bindings": list(settings.get("agent_bindings") or []),
            }

    @staticmethod
    def _normalise_workspace(workspace: str) -> str:
        if not isinstance(workspace, str) or not workspace.strip():
            raise AgentAdminError("workspace is required")
        return str(Path(expand_path(workspace.strip())).resolve(strict=False))

    @staticmethod
    def _bootstrap_workspace(workspace: str) -> None:
        from agent.prompt import ensure_workspace

        ensure_workspace(workspace, create_templates=True)
        for name in ("memory", "skills", "knowledge", "output", "scheduler"):
            (Path(workspace) / name).mkdir(parents=True, exist_ok=True)

    def create_agent(
        self,
        agent_id: str,
        name: str,
        workspace: str,
        clone_from: str = None,
    ) -> Dict:
        with self._lock:
            settings = self._load()
            registry = self._registry(settings)
            workspace = self._normalise_workspace(workspace)
            try:
                registry.get(agent_id, require_enabled=False)
            except KeyError:
                pass
            else:
                raise AgentAdminError(f"agent '{agent_id}' already exists")

            destination = Path(workspace)
            created_destination = False
            if destination.exists() and any(destination.iterdir()):
                raise AgentAdminError("workspace must be empty for a new agent")

            try:
                if clone_from:
                    source = registry.get(clone_from).workspace_path
                    if not source.is_dir():
                        raise AgentAdminError(
                            f"source workspace for '{clone_from}' does not exist"
                        )
                    if destination.exists():
                        destination.rmdir()
                    shutil.copytree(source, destination)
                    created_destination = True
                else:
                    self._bootstrap_workspace(workspace)
                    created_destination = True

                profile = AgentProfile(agent_id, name, workspace)
                registry.upsert(profile)
                profiles = self._explicit_profiles(settings, self._registry(settings))
                profiles.append(profile.to_dict())
                candidate = self._serialise_registry(
                    dict(settings), profiles, registry.default_agent_id
                )
                self._registry(candidate)
                AgentRouter.from_config(candidate, self._registry(candidate))
                self._save(candidate)
            except Exception:
                if created_destination and destination.exists():
                    shutil.rmtree(destination)
                raise
            return profile.to_dict()

    def update_agent(
        self,
        agent_id: str,
        *,
        name: str = None,
        enabled: bool = None,
        make_default: bool = False,
    ) -> Dict:
        with self._lock:
            settings = self._load()
            registry = self._registry(settings)
            current = registry.get(agent_id, require_enabled=False)
            new_enabled = current.enabled if enabled is None else enabled
            if not isinstance(new_enabled, bool):
                raise AgentAdminError("enabled must be a boolean")
            new_name = current.name if name is None else name.strip()
            if not new_name:
                raise AgentAdminError("name must be a non-empty string")
            updated = AgentProfile(
                id=current.id,
                name=new_name,
                workspace=current.workspace,
                enabled=new_enabled,
                model=current.model,
                bot_type=current.bot_type,
            )
            registry.upsert(updated)
            if not new_enabled:
                registry.set_enabled(agent_id, False)
            if make_default:
                registry.set_default(agent_id)

            profiles = [
                updated.to_dict() if item.id == agent_id else item.to_dict()
                for item in registry.list()
            ]
            candidate = self._serialise_registry(
                dict(settings), profiles, registry.default_agent_id
            )
            AgentRouter.from_config(candidate, registry)
            self._save(candidate)
            return updated.to_dict()

    def archive_agent(self, agent_id: str) -> Dict:
        return self.update_agent(agent_id, enabled=False)

    def replace_bindings(self, bindings: list) -> list:
        with self._lock:
            settings = self._load()
            registry = self._registry(settings)
            candidate = dict(settings)
            candidate["agent_bindings"] = bindings
            AgentRouter.from_config(candidate, registry)
            self._save(candidate)
            return list(bindings)

    def _core_path(self, agent_id: str, filename: str) -> Path:
        if filename not in CORE_FILES:
            raise AgentAdminError(f"unsupported core file: {filename}")
        registry = self._registry(self._load())
        workspace = registry.get(agent_id, require_enabled=False).workspace_path.resolve()
        path = (workspace / filename).resolve()
        if path.parent != workspace:
            raise AgentAdminError("core file escapes the agent workspace")
        return path

    def read_core_file(self, agent_id: str, filename: str) -> Dict:
        with self._lock:
            path = self._core_path(agent_id, filename)
            raw = path.read_bytes() if path.exists() else b""
            return {
                "filename": filename,
                "content": raw.decode("utf-8"),
                "revision": _revision(raw),
                "exists": path.exists(),
            }

    def write_core_file(
        self, agent_id: str, filename: str, content: str, revision: str
    ) -> Dict:
        if not isinstance(content, str):
            raise AgentAdminError("content must be a string")
        raw = content.encode("utf-8")
        if len(raw) > MAX_CORE_FILE_BYTES:
            raise AgentAdminError("core file exceeds 1 MiB")
        with self._lock:
            path = self._core_path(agent_id, filename)
            current = path.read_bytes() if path.exists() else b""
            current_revision = _revision(current)
            if revision != current_revision:
                raise StaleAgentFileError(
                    "core file changed since it was loaded; refresh before saving"
                )
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp_name = tempfile.mkstemp(
                prefix=f".{filename}.", suffix=".tmp", dir=str(path.parent)
            )
            try:
                with os.fdopen(fd, "wb") as handle:
                    handle.write(raw)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(tmp_name, path)
            except Exception:
                try:
                    os.unlink(tmp_name)
                except OSError:
                    pass
                raise
            return {
                "filename": filename,
                "content": content,
                "revision": _revision(raw),
                "exists": True,
            }
