"""Where the team is kept: who exists, who leads, and which channels reach whom.

Beside the workspaces it names, at ``<instance root>/agents/team.json``, rather
than inside ``config.json``, which several unrelated callers rewrite wholesale
after editing one key. That is safe against itself but not against a writer
holding a snapshot from before an Agent was created, which would put the file
back without it. A file of its own removes the shared blast radius instead of
adding another lock, and puts the team where the rest of the instance's state
already lives.

Workspaces are stored only when they are unusual. A standard layout puts the
default Agent at the root and everyone else in ``agents/<id>``, both derivable,
so the file carries no absolute paths and survives being moved or restored
somewhere else. Anything genuinely elsewhere is written out in full.

Reading falls back to ``config.json`` for installs that predate this file; the
first write migrates them and clears the old keys.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from threading import RLock
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional

from channel.feishu.feishu_config_migration import FEISHU_CONFIG_MIGRATION_KEY
from common import const
from common.atomic_write import write_text_atomic
from common.log import logger
from common.utils import expand_path

#: The keys that make up the roster. They move as one: a profile list and the
#: choice of default are meaningless apart. ``channel_instances`` carries each
#: channel's identity, credentials and the Agent it is bound to — the single
#: source of truth for inbound routing. It is opt-in: absent, channel startup
#: falls back to ``channel_type`` + flat credentials in config.json, so a legacy
#: single-Agent install keeps working untouched.
LEGACY_CHANNEL_IMPORT_TYPES = "legacy_channel_import_types"
TEAM_KEYS = (
    "agents", "default_agent_id", "channel_instances", FEISHU_CONFIG_MIGRATION_KEY,
    LEGACY_CHANNEL_IMPORT_TYPES,
)
_roster_lock = RLock()


@contextmanager
def roster_transaction():
    with _roster_lock:
        yield

FILE_NAME = "team.json"


def instance_root(settings: Mapping[str, Any]) -> Path:
    return Path(expand_path((settings.get("agent_workspace") or "~/cow")))


def team_file(settings: Mapping[str, Any]) -> Path:
    return instance_root(settings) / "agents" / FILE_NAME


def limit_new_feishu_roster(settings: Mapping[str, Any], roster: Dict[str, Any]) -> None:
    """When Feishu creates the roster, keep other flat channels in config.json."""
    if not team_file(settings).exists() and not roster.get("agents") and not roster.get("channel_instances"):
        roster[LEGACY_CHANNEL_IMPORT_TYPES] = [const.FEISHU]


def _legacy(settings: Mapping[str, Any]) -> Dict[str, Any]:
    """The roster as an older install still has it, inside ``config.json``."""
    return {key: settings[key] for key in TEAM_KEYS if key in settings}


def read(settings: Mapping[str, Any], *, strict=False) -> Dict[str, Any]:
    """The roster keys, from the file if there is one.

    Falls back to ``config.json`` so an install that predates the file keeps
    working untouched, and so does a hand-written config. The file wins once
    it exists, which is what makes the move a one-way door.
    """
    path = team_file(settings)
    try:
        raw = path.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        return _legacy(settings)
    except OSError as e:
        if strict:
            raise
        logger.warning(f"[Roster] Cannot read {path}, using config.json: {e}")
        return _legacy(settings)

    try:
        data = json.loads(raw)
    except ValueError as e:
        if strict:
            raise
        # Better to fall back than to start with no Agents at all: the
        # registry would substitute a lone default and the console would
        # look like every Agent had been deleted.
        logger.error(f"[Roster] {path} is not valid JSON, using config.json: {e}")
        return _legacy(settings)
    if not isinstance(data, dict):
        if strict:
            raise ValueError("Team configuration must contain an object")
        logger.error(f"[Roster] {path} must contain an object, using config.json")
        return _legacy(settings)
    return {key: data[key] for key in TEAM_KEYS if key in data}


def resolve(settings: Mapping[str, Any]) -> Dict[str, Any]:
    """``settings`` with the roster overlaid, ready for ``from_config``."""
    return {**dict(settings), **read(settings)}


def stamp(settings: Mapping[str, Any]) -> tuple:
    """Cheap identity of the current roster, for caching the registry.

    The file's mtime and size rather than its content: this is checked on hot
    paths, and every write goes through ``os.replace``, so a change always
    shows up here.
    """
    path = team_file(settings)
    try:
        stat = path.stat()
        return (str(path), stat.st_mtime_ns, stat.st_size)
    except OSError:
        # No file yet: the roster is still whatever config.json says, so the
        # signature has to follow that instead.
        return (str(path), repr(_legacy(settings)))


def compact(
    profiles: Iterable[Mapping[str, Any]],
    settings: Mapping[str, Any],
    default_agent_id: str,
) -> list:
    """Drop workspaces that the standard layout already implies.

    What is left is free of absolute paths, so the roster can be copied,
    backed up or restored somewhere else without rewriting. An Agent parked
    outside the tree keeps its path, because nothing else can imply it.
    """
    root = instance_root(settings).resolve()
    stored = []
    for profile in profiles:
        item = dict(profile)
        agent_id = str(item.get("id") or "")
        workspace = item.get("workspace")
        if workspace:
            implied = root if agent_id == default_agent_id else root / "agents" / agent_id
            if Path(expand_path(str(workspace))).resolve() == implied:
                item.pop("workspace")
        stored.append(item)
    return stored


@roster_transaction()
def write(settings: Mapping[str, Any], roster: Mapping[str, Any], *, strict=False) -> Path:
    """Replace the roster file atomically. Returns where it was written.

    A roster created solely for Feishu keeps the other legacy channels in
    config.json. Once a second Agent is added, apply the usual team import.
    """
    path = team_file(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {key: roster[key] for key in TEAM_KEYS if key in roster}
    agents = payload.get("agents")
    if isinstance(agents, list) and len(agents) > 1:
        payload.pop(LEGACY_CHANNEL_IMPORT_TYPES, None)
    from channel.channel_instances import bootstrap_legacy_instances

    bootstrapped = bootstrap_legacy_instances(
        settings, payload, payload.get("default_agent_id") or ""
    )
    if bootstrapped:
        payload["channel_instances"] = bootstrapped
    contents = json.dumps(payload, indent=4, ensure_ascii=False) + "\n"
    if strict:
        write_text_atomic(path, contents, allow_in_place=False)
    else:
        write_text_atomic(path, contents)
    return path


def migrate(settings: Mapping[str, Any], config_path: Optional[Any] = None) -> Optional[Path]:
    """Move a roster still living in ``config.json`` into its own file.

    Once, at startup, rather than on the next edit: until it has moved, the
    roster is still exposed to whatever else rewrites ``config.json``, which is
    the thing the move is for. Waiting for an edit leaves that window open
    indefinitely and leaves two copies to wonder about in the meantime.

    An install without a roster or explicit channel instances gets no file.
    """
    path = team_file(settings)
    if path.exists():
        return None
    legacy = _legacy(settings)
    if not legacy.get("agents") and not legacy.get("channel_instances"):
        return None
    roster = dict(legacy)
    if roster.get("agents"):
        roster["agents"] = compact(
            roster["agents"], settings, roster.get("default_agent_id") or ""
        )
    try:
        written = write(settings, roster)
    except OSError as e:
        # Keep running off config.json: it is still readable, and read() falls
        # back to it, so a failure here costs tidiness rather than Agents.
        logger.warning(f"[Team] Could not move the roster to {path}: {e}")
        return None
    retire_legacy(config_path)
    logger.info(f"[Team] Roster moved out of config.json into {written}")
    return written


@roster_transaction()
def adopt_legacy_channels(settings: Mapping[str, Any]) -> Optional[Path]:
    """Fold legacy channels into a roster file that already exists.

    ``write`` carries them over, but only when something writes: a channel set
    up in ``config.json`` after the file appeared (an older build run against
    the same data) would otherwise run without a record, so the console cannot
    show or manage it. Leaves unreadable files alone.
    """
    path = team_file(settings)
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    roster = {key: data[key] for key in TEAM_KEYS if key in data}
    from channel.channel_instances import bootstrap_legacy_instances

    after = bootstrap_legacy_instances(settings, roster, roster.get("default_agent_id") or "")
    if not after or after == roster.get("channel_instances"):
        return None
    roster["channel_instances"] = after
    try:
        written = write(settings, roster)
    except OSError as e:
        logger.warning(f"[Team] Could not add legacy channels to {path}: {e}")
        return None
    logger.info(f"[Team] Applied legacy channel settings to {written}")
    return written


@roster_transaction()
def retire_legacy(config_path: Optional[Path]) -> None:
    """Take the roster keys out of ``config.json``, once the file has them.

    Leaving both copies invites someone to edit the one that is no longer
    read. Best effort on purpose: the file is authoritative from here on, so
    a failure to tidy up changes nothing about which Agents exist.
    """
    if config_path is None:
        return
    path = Path(config_path)
    try:
        settings = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(settings, dict):
            return
        if not any(key in settings for key in TEAM_KEYS):
            return
        for key in TEAM_KEYS:
            settings.pop(key, None)
        write_text_atomic(
            path, json.dumps(settings, indent=4, ensure_ascii=False) + "\n"
        )
    except (OSError, ValueError) as e:
        logger.warning(f"[Roster] Left the old roster in {config_path}: {e}")
