"""Upgrade legacy Feishu owner and private-memory settings at startup."""

import hashlib
import json
from pathlib import Path

from common.atomic_write import write_text_atomic
from common.const import FEISHU
from common.log import logger


FEISHU_CONFIG_MIGRATION_KEY = "feishu_config_migration"


def migrate_feishu_settings(settings, config_path):
    """Persist instance settings before retiring their flat configuration."""
    from agent import team
    from channel.channel_instances import bootstrap_legacy_instances
    from channel.feishu.owner_config import (
        DEFAULT_MEMORY_MODE, LEGACY_OWNER_ID, LEGACY_SHARE_MEMORY, MEMORY_MODE,
        OWNER_IDS, parse_owner_ids,
    )

    path = Path(config_path)
    roster_path = team.team_file(settings)
    try:
        try:
            source = json.loads(path.read_text(encoding="utf-8-sig"))
        except FileNotFoundError:
            source = {}
        if not isinstance(source, dict):
            raise ValueError("Config root must be an object")
        try:
            roster = json.loads(roster_path.read_text(encoding="utf-8-sig"))
        except FileNotFoundError:
            roster = team._legacy(source)
        if not isinstance(roster, dict):
            raise ValueError("Team root must be an object")
        if "channel_instances" in roster and not isinstance(roster["channel_instances"], list):
            raise ValueError("Team channel_instances must be a list")

        team.limit_new_feishu_roster(settings, roster)
        records = bootstrap_legacy_instances(settings, roster, channel_types=(FEISHU,))
        feishu = [record for record in records if record.get("channel_type") == FEISHU]
        changed = bool(feishu) and records != roster.get("channel_instances")
        for record in feishu:
            credentials = record.get("credentials")
            if not isinstance(credentials, dict):
                credentials = record
            if LEGACY_SHARE_MEMORY in credentials:
                shared = credentials.pop(LEGACY_SHARE_MEMORY)
                credentials.setdefault(MEMORY_MODE, "shared" if shared is True else DEFAULT_MEMORY_MODE)
                changed = True

        keys = (LEGACY_OWNER_ID, OWNER_IDS, LEGACY_SHARE_MEMORY)
        legacy = {key: source[key] for key in keys if key in source}
        app_id = source.get("feishu_app_id")
        fingerprint = hashlib.sha256(json.dumps([app_id, legacy], sort_keys=True).encode()).hexdigest()
        retire = bool(legacy) and roster.get(FEISHU_CONFIG_MIGRATION_KEY) == fingerprint
        if legacy and not retire:
            matches = []
            for record in feishu:
                credentials = record.get("credentials")
                credentials = credentials if isinstance(credentials, dict) else record
                if app_id and credentials.get("feishu_app_id") == app_id:
                    matches.append(credentials)
            # A template's empty placeholders carry no app-specific state.
            has_binding = bool(legacy.get(LEGACY_OWNER_ID) or legacy.get(OWNER_IDS) or
                               legacy.get(LEGACY_SHARE_MEMORY) is True)
            if len(matches) == 1:
                credentials = matches[0]
                try:
                    if OWNER_IDS not in credentials:
                        if OWNER_IDS in legacy:
                            credentials[OWNER_IDS] = parse_owner_ids(legacy[OWNER_IDS])
                        elif legacy.get(LEGACY_OWNER_ID):
                            credentials[OWNER_IDS] = parse_owner_ids([legacy[LEGACY_OWNER_ID]])
                    if legacy.get(LEGACY_SHARE_MEMORY) is True:
                        credentials.setdefault(MEMORY_MODE, "shared")
                    retire = changed = True
                except ValueError:
                    logger.warning("[Feishu] Invalid legacy Owner ID; review the old configuration")
            elif has_binding:
                logger.warning("[Feishu] Legacy Owner or memory settings require a unique App ID match")
            else:
                retire = True

        if changed:
            roster["channel_instances"] = records
            if retire:
                roster[FEISHU_CONFIG_MIGRATION_KEY] = fingerprint
            team.write(settings, roster, strict=True)
        if retire:
            current = json.loads(path.read_text(encoding="utf-8-sig"))
            if current.get("feishu_app_id") == app_id and {k: current[k] for k in keys if k in current} == legacy:
                for key in legacy:
                    current.pop(key)
                write_text_atomic(path, json.dumps(current, indent=4, ensure_ascii=False) + "\n", allow_in_place=False)
                for key in legacy:
                    settings.pop(key, None)
    except (OSError, ValueError) as exc:
        logger.warning(f"[Feishu] Could not finish channel settings migration ({type(exc).__name__}); will retry at startup")
