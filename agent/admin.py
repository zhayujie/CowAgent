"""Safe configuration and core-file management for agent workspaces."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import threading
import time
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional

from agent import team
from agent.registry import AgentProfile, AgentRegistry
from common.log import logger
from common.utils import expand_path


CORE_FILES = ("AGENT.md", "USER.md", "RULE.md", "MEMORY.md", "BOOTSTRAP.md")
MAX_CORE_FILE_BYTES = 1024 * 1024

# What a cloned Agent starts from: how it behaves, not what it knows.
# MEMORY.md is excluded because it is what the source Agent learned about its
# user, and .env, the session database and the shared asset directories are
# excluded because copying them would fork credentials, hand one Agent another's
# conversations, and put the skill library into N places that then drift.
CLONED_FILES = ("AGENT.md", "USER.md", "RULE.md", "BOOTSTRAP.md")

# The keys this service owns. Anything else in the settings it is handed
# belongs to another console page and is never written from here.
ROSTER_KEYS = team.TEAM_KEYS
_UNSET = object()


class AgentAdminError(ValueError):
    pass


class StaleAgentFileError(AgentAdminError):
    pass


class StaleRosterError(AgentAdminError):
    """Raised when the roster changed between the caller's read and its write."""


def _revision(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _roster_revision(settings: Mapping) -> str:
    """Revision over the Agent-owned slice of the config only.

    Scoped rather than whole-file so that saving an unrelated setting from
    another page does not invalidate an Agents page that is merely open, while
    two concurrent roster edits still conflict.
    """
    scoped = {key: settings.get(key) for key in ROSTER_KEYS}
    return _revision(
        json.dumps(scoped, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
    )


def _is_strictly_within(inner: Path, outer: Path) -> bool:
    if inner == outer:
        return False
    try:
        inner.relative_to(outer)
    except ValueError:
        return False
    return True


class AgentAdminService:
    """Manage profiles without ever deleting an agent workspace implicitly."""

    def __init__(self, config_path: str, settings: Optional[Mapping] = None):
        self.config_path = Path(config_path)
        self._settings = dict(settings) if settings is not None else None
        self._lock = threading.RLock()

    def _load(self) -> Dict:
        """Deployment settings with the roster overlaid on top.

        Callers want one mapping to hand to ``AgentRegistry.from_config``, and
        should not have to know that the two halves come from different files.
        """
        if self._settings is not None:
            return team.resolve(self._settings)
        if not self.config_path.exists():
            return {}
        # utf-8-sig tolerates a UTF-8 BOM (e.g. config.json edited with Windows
        # Notepad / PowerShell). Plain utf-8 raises "Unexpected UTF-8 BOM" here,
        # which surfaces as a failed /api/agents snapshot and an empty team page.
        with self.config_path.open("r", encoding="utf-8-sig") as handle:
            data = json.load(handle)
        if not isinstance(data, dict):
            raise AgentAdminError("config root must be an object")
        return team.resolve(data)

    def _write(self, settings: Dict) -> None:
        """Persist the roster. ``config.json`` is not touched beyond retiring it.

        Only the roster keys are ever ours to write (``_commit`` enforces it),
        so the rest of ``settings`` is here to say where the file goes.
        """
        stored = dict(settings)
        if stored.get("agents"):
            stored["agents"] = team.compact(
                stored["agents"], settings, stored.get("default_agent_id") or ""
            )
        team.write(settings, stored)
        team.retire_legacy(self.config_path if self._settings is None else None)
        if self._settings is not None:
            self._settings = {
                key: value
                for key, value in settings.items()
                if key not in team.TEAM_KEYS
            }

    def _commit(self, updates: Mapping, revision: Optional[str] = None) -> Dict:
        """Apply the roster keys onto whatever is stored right now.

        Writing back a whole snapshot taken before the edit would drop any
        change another page made in between, so only the owned keys are written,
        and they are applied to a fresh read rather than to that snapshot.
        """
        current = self._load()
        if revision is not None and _roster_revision(current) != revision:
            raise StaleRosterError(
                "the Agent list changed since it was loaded; refresh before saving"
            )
        for key in updates:
            if key not in ROSTER_KEYS:
                raise AgentAdminError(f"refusing to write unowned config key: {key}")
        merged = dict(current)
        merged.update(updates)
        self._write(merged)
        return merged

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
    def _instance_root(settings: Mapping) -> Path:
        return Path(
            AgentAdminService._normalise_workspace(
                settings.get("agent_workspace") or "~/cow"
            )
        )

    def snapshot(self) -> Dict:
        with self._lock:
            settings = self._load()
            registry = self._registry(settings)
            default_id = registry.default_agent_id
            agents = []
            for profile in registry.list():
                data = profile.to_dict()
                # Whether this Agent reads the shared knowledge base or its own,
                # derived from the workspace so the UI can show the toggle state.
                data["knowledge_mode"] = self._knowledge_mode_of(profile, default_id)
                agents.append(data)
            return {
                "default_agent_id": default_id,
                "agents": agents,
                "channel_instances": list(settings.get("channel_instances") or []),
                "revision": _roster_revision(settings),
            }

    @staticmethod
    def _knowledge_mode_of(profile: AgentProfile, default_id: str) -> str:
        if profile.id == default_id:
            return "shared"
        kdir = profile.workspace_path / "knowledge"
        if kdir.is_dir() and not kdir.is_symlink():
            return "own"
        return "shared"

    @staticmethod
    def _normalise_workspace(workspace: str) -> str:
        if not isinstance(workspace, str) or not workspace.strip():
            raise AgentAdminError("workspace is required")
        return str(Path(expand_path(workspace.strip())).resolve(strict=False))

    @staticmethod
    def _bootstrap_workspace(workspace: str) -> None:
        """Create only what belongs to this Agent alone.

        Deliberately does not create ``skills/`` or ``knowledge/``: an Agent opts
        out of the shared copy by *having* that directory, so creating them empty
        would cut every new Agent off from all installed skills and knowledge.
        ``ensure_workspace`` already scaffolds those through ``state_dir``, which
        lands them on the shared copy.
        """
        from agent.prompt import ensure_workspace
        from common import state_dir

        ensure_workspace(workspace, create_templates=True)
        state_dir.scheduler_file(base=workspace).parent.mkdir(
            parents=True, exist_ok=True
        )

    @staticmethod
    def _seed_name(workspace: str, name: str) -> None:
        """Write the given name into the Agent's own AGENT.md.

        The template leaves the name as an instruction to fill in later, which
        is right for the first Agent — it is named in conversation. But an Agent
        created from the console was named in the form, and an Agent that cannot
        read its own name does not recognise being addressed by it.

        Only the placeholder is replaced, so a cloned or hand-written persona
        that already states a name is left alone.
        """
        path = Path(workspace) / "AGENT.md"
        try:
            original = path.read_text(encoding="utf-8")
        except OSError:
            return
        updated = re.sub(
            r"^(- \*\*(?:名字|Name)\*\*:).*$",
            lambda m: f"{m.group(1)} {name}",
            original,
            count=1,
            flags=re.MULTILINE,
        )
        if updated == original:
            return
        try:
            path.write_text(updated, encoding="utf-8")
        except OSError as e:
            logger.warning(f"[AgentAdmin] Could not seed name into {path}: {e}")

    @staticmethod
    def _seed_user_profile(registry: AgentRegistry, destination: Path, *, cloned: bool) -> None:
        """Carry the operator profile (USER.md) into a new Agent.

        USER.md is a fact about the person running the instance, not about the
        persona, so a fresh Agent should start knowing it rather than blank. If a
        persona template was cloned it already brought its own USER.md, so this
        only fills the gap for an Agent created without a template.
        """
        target = destination / "USER.md"
        if cloned and target.is_file():
            return
        try:
            default_ws = registry.get(require_enabled=False).workspace_path
        except Exception:
            return
        src = default_ws / "USER.md"
        if src.is_file() and src.resolve() != target.resolve():
            try:
                shutil.copy2(src, target)
            except OSError as e:
                logger.warning(f"[AgentAdmin] Could not seed USER.md into {target}: {e}")

    @staticmethod
    def _make_own_knowledge(destination: Path) -> None:
        """Give a brand-new Agent its own knowledge base (opt out of shared)."""
        kdir = destination / "knowledge"
        try:
            kdir.mkdir(parents=True, exist_ok=True)
            index = kdir / "index.md"
            if not index.exists():
                index.write_text("# Knowledge Index\n", encoding="utf-8")
        except OSError as e:
            logger.warning(f"[AgentAdmin] Could not create own knowledge for {destination}: {e}")

    @staticmethod
    def _make_own_skills(destination: Path) -> None:
        """Give a brand-new Agent its own skill set (opt out of shared).

        Presence of the directory is what opts an Agent out of the shared copy,
        so an empty ``skills/`` is enough: the Agent then starts with no shared
        skills and installs its own.
        """
        sdir = destination / "skills"
        try:
            sdir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            logger.warning(f"[AgentAdmin] Could not create own skills for {destination}: {e}")

    @staticmethod
    def _clone_persona(source: Path, destination: Path) -> None:
        """Copy how an Agent behaves, and nothing else.

        A whole-tree copy is wrong in every direction here: the default Agent's
        workspace is the instance root, so it contains every other Agent's
        workspace and the shared asset library, and copying it into a directory
        beneath itself recurses until the filesystem refuses the path length.
        """
        for filename in CLONED_FILES:
            candidate = source / filename
            if candidate.is_file():
                shutil.copy2(candidate, destination / filename)

    def _reject_overlapping_workspace(
        self, workspace: Path, registry: AgentRegistry, sanctioned: Path
    ) -> None:
        """Refuse a workspace nested in another Agent's, or containing one.

        The one nesting that is fine is the layout the registry itself derives,
        ``<instance root>/agents/<id>``, which necessarily sits inside the
        default Agent's workspace. Anything else makes one Agent's files
        reachable from another's root, so recursive work such as backup, clone
        or a workspace file listing would treat two Agents as one.
        """
        if workspace == sanctioned:
            return
        for profile in registry.list():
            other = Path(profile.workspace)
            if _is_strictly_within(workspace, other):
                raise AgentAdminError(
                    f"workspace sits inside agent '{profile.id}' workspace; "
                    f"use {sanctioned} or a path outside it"
                )
            if _is_strictly_within(other, workspace):
                raise AgentAdminError(
                    f"workspace contains agent '{profile.id}' workspace; "
                    f"use {sanctioned} or a path outside it"
                )

    @staticmethod
    def _asset_list(value, field: str) -> Optional[List[str]]:
        if value is None:
            return None
        if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
            raise AgentAdminError(f"{field} must be a list of strings")
        return [x.strip() for x in value if x.strip()]

    def create_agent(
        self,
        agent_id: str,
        name: str,
        workspace: str = None,
        clone_from: str = None,
        description: str = None,
        avatar: str = None,
        skills: Optional[Iterable[str]] = None,
        knowledge: Optional[Iterable[str]] = None,
        knowledge_mode: str = None,
        skill_mode: str = None,
        revision: str = None,
    ) -> Dict:
        if knowledge_mode not in (None, "shared", "own"):
            raise AgentAdminError("knowledge mode must be 'shared' or 'own'")
        if skill_mode not in (None, "shared", "own"):
            raise AgentAdminError("skill mode must be 'shared' or 'own'")
        with self._lock:
            settings = self._load()
            registry = self._registry(settings)

            try:
                registry.get(agent_id, require_enabled=False)
            except KeyError:
                pass
            else:
                raise AgentAdminError(f"agent '{agent_id}' already exists")


            # An omitted workspace is the common case: what a new Agent needs is
            # a name and a persona, so the console does not ask for a path.
            sanctioned = self._instance_root(settings) / "agents" / agent_id
            workspace = (
                self._normalise_workspace(workspace)
                if workspace
                else str(sanctioned)
            )
            destination = Path(workspace)
            self._reject_overlapping_workspace(destination, registry, sanctioned)

            if destination.exists() and any(destination.iterdir()):
                raise AgentAdminError("workspace must be empty for a new agent")

            source: Optional[Path] = None
            if clone_from:
                source = registry.get(clone_from).workspace_path
                if not source.is_dir():
                    raise AgentAdminError(
                        f"source workspace for '{clone_from}' does not exist"
                    )

            created_destination = not destination.exists()
            try:
                self._bootstrap_workspace(workspace)
                if source is not None:
                    self._clone_persona(source, destination)
                # USER.md describes the operator, not the persona, so it belongs
                # to whoever runs the instance: seed every new Agent with the
                # default's copy (unless a chosen template already supplied one),
                # so the operator profile carries over rather than starting blank.
                self._seed_user_profile(registry, destination, cloned=source is not None)
                self._seed_name(workspace, name)
                if knowledge_mode == "own":
                    self._make_own_knowledge(destination)
                if skill_mode == "own":
                    self._make_own_skills(destination)

                profile = AgentProfile(
                    id=agent_id,
                    name=name,
                    workspace=workspace,
                    description=(description or "").strip() or None,
                    avatar=(avatar or None),
                    skills=(
                        None if skills is None else tuple(self._asset_list(list(skills), "skills"))
                    ),
                    knowledge=(
                        None
                        if knowledge is None
                        else tuple(self._asset_list(list(knowledge), "knowledge"))
                    ),
                )
                registry.upsert(profile)
                profiles = self._explicit_profiles(settings, self._registry(settings))
                profiles.append(profile.to_dict())
                candidate = dict(settings)
                candidate["agents"] = profiles
                candidate["default_agent_id"] = registry.default_agent_id
                self._registry(candidate)
                self._commit(
                    {
                        "agents": profiles,
                        "default_agent_id": registry.default_agent_id,
                    },
                    revision,
                )
            except Exception:
                if created_destination and destination.exists():
                    shutil.rmtree(destination, ignore_errors=True)
                raise
            return profile.to_dict()

    def update_agent(
        self,
        agent_id: str,
        *,
        name: str = None,
        enabled: bool = None,
        make_default: bool = False,
        description: str = None,
        avatar: str = None,
        model: str = None,
        bot_type: str = None,
        skills=_UNSET,
        knowledge=_UNSET,
        revision: str = None,
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
            # An empty string clears the field; None leaves it alone, so the
            # console can send a partial update without wiping what it omits.
            new_avatar = current.avatar if avatar is None else (avatar.strip() or None)
            new_description = (
                current.description if description is None else (description.strip() or None)
            )
            new_model = current.model if model is None else (model.strip() or None)
            # A model without its provider would be asked of whichever vendor is
            # globally configured, so the two move together.
            new_bot_type = current.bot_type if bot_type is None else (bot_type.strip() or None)
            if not new_model:
                new_bot_type = None
            # The default Agent is the one the console's model setting is for. A
            # second answer here would mean two places to change it and no way
            # to tell which is in force, so promotion drops the Agent's own.
            becomes_default = make_default or agent_id == registry.default_agent_id
            if new_model and becomes_default:
                if make_default:
                    new_model = new_bot_type = None
                else:
                    raise AgentAdminError(
                        "the default agent follows the configured model; "
                        "change it in settings instead"
                    )
            # ``None`` here is a real answer ("use every shared skill"), distinct
            # from omitting the field. The handler only passes the argument when
            # the request named it.
            new_skills = (
                current.skills
                if skills is _UNSET
                else (
                    None
                    if skills is None
                    else tuple(self._asset_list(list(skills), "skills"))
                )
            )
            new_knowledge = (
                current.knowledge
                if knowledge is _UNSET
                else (
                    None
                    if knowledge is None
                    else tuple(self._asset_list(list(knowledge), "knowledge"))
                )
            )
            updated = AgentProfile(
                id=current.id,
                name=new_name,
                workspace=current.workspace,
                description=new_description,
                enabled=new_enabled,
                model=new_model,
                bot_type=new_bot_type,
                avatar=new_avatar,
                skills=new_skills,
                knowledge=new_knowledge,
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
            candidate = dict(settings)
            candidate["agents"] = profiles
            candidate["default_agent_id"] = registry.default_agent_id
            self._commit(
                {"agents": profiles, "default_agent_id": registry.default_agent_id},
                revision,
            )
            return updated.to_dict()

    def archive_agent(self, agent_id: str, revision: str = None) -> Dict:
        return self.update_agent(agent_id, enabled=False, revision=revision)

    def delete_agent(self, agent_id: str, revision: str = None) -> Dict:
        """Remove an Agent from the roster for good, files and all.

        The default Agent is the instance itself — its workspace is the
        instance root, holding every other Agent and the shared library — so it
        can never be deleted. For anyone else we drop the roster entry, unbind
        any channel instances that pointed at them (so those channels fall back
        to the default Agent rather than routing into the void), and delete
        their own workspace, but only when it is the layout we created
        (``<instance root>/agents/<id>``): a hand-picked path could be anywhere,
        and we will not recursively erase a directory we did not make.
        """
        with self._lock:
            settings = self._load()
            registry = self._registry(settings)
            profile = registry.get(agent_id, require_enabled=False)
            if agent_id == registry.default_agent_id:
                raise AgentAdminError("the default agent cannot be deleted")

            profiles = [
                item.to_dict()
                for item in registry.list()
                if item.id != agent_id
            ]
            # A channel instance bound to a now-missing Agent would route
            # messages into the void, so clear those bindings (the channel keeps
            # running and falls back to the default Agent).
            instances = []
            for item in (settings.get("channel_instances") or []):
                inst = dict(item)
                if (inst.get("agent_id") or "") == agent_id:
                    inst["agent_id"] = ""
                instances.append(inst)
            candidate = dict(settings)
            candidate["agents"] = profiles
            candidate["channel_instances"] = instances
            candidate["default_agent_id"] = registry.default_agent_id
            # Validate the resulting roster before writing anything.
            self._registry(candidate)
            self._commit(
                {
                    "agents": profiles,
                    "channel_instances": instances,
                    "default_agent_id": registry.default_agent_id,
                },
                revision,
            )

            sanctioned = self._instance_root(settings) / "agents" / agent_id
            workspace = profile.workspace_path
            if workspace == sanctioned and workspace.is_dir():
                shutil.rmtree(workspace, ignore_errors=True)

            # Sweep the session-prefs store of anything still pointing at the
            # gone Agent: its own orphaned session overrides and its id lingering
            # in other conversations' team rosters. Best-effort — a hiccup here
            # must not undo a deletion that already committed.
            try:
                from agent.workspace import session_prefs

                session_prefs.forget_agent(agent_id)
            except Exception as e:
                logger.warning(f"[AgentAdmin] session prefs cleanup after delete failed: {e}")

            # The project store keys its bindings the same way and needs the same
            # sweep: an Agent's own sessions go away with its workspace, so their
            # ``{id}::*`` entries would linger forever and a new Agent reusing the
            # id would inherit them. Best-effort too, and separate so one store
            # failing cannot swallow the other's cleanup.
            try:
                from agent.workspace import project_store

                project_store.forget_agent(agent_id)
            except Exception as e:
                logger.warning(f"[AgentAdmin] project store cleanup after delete failed: {e}")

            return {"id": agent_id, "deleted": True}

    def knowledge_mode(self, agent_id: str) -> str:
        """Whether this Agent reads the shared knowledge base or its own.

        Derived from the filesystem, not a stored flag, so it can never drift
        from reality (the same "opt out by presence" rule the shared assets use):
        a real ``knowledge/`` directory in the Agent's workspace means "own"; a
        symlink to the shared copy, or nothing at all, means "shared".

        The default Agent owns the instance root, so its ``knowledge/`` *is* the
        shared one — it is always reported as shared and cannot be switched.
        """
        with self._lock:
            settings = self._load()
            registry = self._registry(settings)
            profile = registry.get(agent_id, require_enabled=False)
            return self._knowledge_mode_of(profile, registry.default_agent_id)

    def set_knowledge_mode(self, agent_id: str, mode: str) -> Dict:
        """Switch an Agent between the shared knowledge base and its own.

        ``own``   → give the Agent a real ``knowledge/`` directory so its reads
                    and writes stay private: the base it set aside earlier if
                    there is one, else a fresh one seeded with an empty index.
        ``shared``→ point ``knowledge/`` at the shared copy via a symlink so the
                    Agent both sees and contributes to the common base. Shared is
                    only a reference, so the switch is always allowed: an own
                    base that holds content is set aside (``knowledge.own``)
                    rather than deleted, and comes back on the next switch to
                    ``own``. We never delete a knowledge base implicitly.

        Returns ``{"id", "mode", "changed"}``.
        """
        if mode not in ("shared", "own"):
            raise AgentAdminError("knowledge mode must be 'shared' or 'own'")
        from common import state_dir

        with self._lock:
            settings = self._load()
            registry = self._registry(settings)
            profile = registry.get(agent_id, require_enabled=False)
            if agent_id == registry.default_agent_id:
                raise AgentAdminError(
                    "the default Agent owns the shared knowledge base"
                )
            workspace = profile.workspace_path
            kdir = workspace / "knowledge"
            # Where an own base waits while the Agent reads the shared one.
            stash = workspace / "knowledge.own"
            # The shared base is the default Agent's knowledge/. Resolve it
            # directly rather than through this Agent's own base, which in "own"
            # mode would point back at the directory we're about to remove.
            shared = state_dir.shared_root() / "knowledge"

            if mode == "own":
                if kdir.is_dir() and not kdir.is_symlink():
                    return {"id": agent_id, "mode": "own", "changed": False}
                if kdir.is_symlink():
                    kdir.unlink()
                if stash.is_dir():
                    # The base this Agent set aside when it went shared: bring it
                    # back exactly as it was instead of starting empty.
                    stash.rename(kdir)
                    return {"id": agent_id, "mode": "own", "changed": True}
                kdir.mkdir(parents=True, exist_ok=True)
                index = kdir / "index.md"
                if not index.exists():
                    index.write_text("# Knowledge Index\n", encoding="utf-8")
                return {"id": agent_id, "mode": "own", "changed": True}

            # mode == "shared"
            if kdir.is_symlink() or not kdir.exists():
                # Already shared (or nothing yet): (re)point the symlink to be safe.
                if kdir.is_symlink():
                    kdir.unlink()
                self._link_shared_knowledge(kdir, shared)
                return {"id": agent_id, "mode": "shared", "changed": bool(kdir.exists())}
            # A real directory holds the Agent's own base. Shared is just a
            # reference, so the flip is always allowed — but we never delete a
            # base implicitly. Drop it only when it holds nothing the user put
            # there (empty, or just the index we seeded on the way in);
            # otherwise set it aside so switching back to "own" restores it.
            if self._own_knowledge_is_discardable(kdir):
                shutil.rmtree(kdir)
            else:
                if stash.exists():
                    # A stash that was never restored (someone recreated
                    # knowledge/ by hand). Keep both: the older one moves to a
                    # timestamped name rather than being thrown away.
                    stash.rename(workspace / f"knowledge.own.{int(time.time())}")
                kdir.rename(stash)
            self._link_shared_knowledge(kdir, shared)
            return {"id": agent_id, "mode": "shared", "changed": True}

    @staticmethod
    def _own_knowledge_is_discardable(kdir: Path) -> bool:
        """True when the Agent's own knowledge dir holds nothing worth keeping:
        empty, or only the auto-seeded ``index.md`` left at its seed content."""
        entries = list(kdir.iterdir())
        if not entries:
            return True
        if entries == [kdir / "index.md"]:
            try:
                return kdir.joinpath("index.md").read_text(encoding="utf-8").strip() in (
                    "",
                    "# Knowledge Index",
                )
            except OSError:
                return False
        return False

    @staticmethod
    def _link_shared_knowledge(link_path: Path, shared: Path) -> None:
        """Point an Agent's ``knowledge/`` at the shared base via a symlink so
        cwd-relative reads/writes and the vector scan all land on the shared
        copy. Falls back to leaving nothing (pure fallback resolution) if the
        platform refuses symlinks."""
        try:
            shared.mkdir(parents=True, exist_ok=True)
            link_path.parent.mkdir(parents=True, exist_ok=True)
            link_path.symlink_to(shared, target_is_directory=True)
        except (OSError, NotImplementedError):
            # Without a link the Agent still reads shared via state_dir's
            # fallback in the web console; only cwd-relative runtime writes
            # would differ, which is acceptable on symlink-less platforms.
            pass

    def prune_skill(self, skill_name: str) -> bool:
        """Drop an uninstalled skill's name from every Agent's selection.

        A per-Agent ``skills`` list references shared skills by name. When a
        skill is uninstalled that name becomes dead weight in team.json; this
        removes it so the file self-heals. An Agent that used "all" (no list)
        is untouched, and one whose list empties out keeps an empty list
        (a deliberate "none"), never silently reverting to "all".

        :return: True if any Agent's selection changed.
        """
        if not skill_name:
            return False
        with self._lock:
            settings = self._load()
            raw_agents = settings.get("agents")
            if not raw_agents:
                return False
            changed = False
            new_agents = []
            for item in raw_agents:
                entry = dict(item)
                sel = entry.get("skills")
                if isinstance(sel, list) and skill_name in sel:
                    entry["skills"] = [s for s in sel if s != skill_name]
                    changed = True
                new_agents.append(entry)
            if changed:
                self._commit({"agents": new_agents})
            return changed

    # ------------------------------------------------------------------
    # Core persona files
    # ------------------------------------------------------------------
    def _core_path(self, agent_id: str, filename: str) -> Path:
        if filename not in CORE_FILES:
            raise AgentAdminError(f"unsupported core file: {filename}")
        from common import state_dir

        registry = self._registry(self._load())
        workspace = registry.get(agent_id, require_enabled=False).workspace_path.resolve()
        # Resolved through state_dir rather than joined, so the console edits the
        # same MEMORY.md the Agent reads even once that file moves under a
        # per-user root.
        if filename == "MEMORY.md":
            path = Path(state_dir.memory_file(base=workspace)).resolve()
        else:
            path = (workspace / filename).resolve()
        if path != workspace / filename and not _is_strictly_within(path, workspace):
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


def get_agent_admin_service() -> "AgentAdminService":
    """Build a service pointed at the instance's standard config location.

    A single helper so callers outside the web layer (the CLI plugin, cloud
    client, …) don't each re-derive the ``config.json`` path.
    """
    from config import get_data_root

    return AgentAdminService(os.path.join(get_data_root(), "config.json"))
