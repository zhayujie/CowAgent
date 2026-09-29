"""Resolve which channel instances to run, bridging legacy and multi-instance.

A legacy install configures channels through ``channel_type`` (a list of type
names) plus flat credentials in ``config.json``; every type maps to exactly one
running channel bound to the default Agent. This is the "shared by default"
world and must keep working untouched.

A multi-Agent install opts in by adding ``channel_instances`` to ``team.json``:
a list of records, each with its own ``instance_id``, ``channel_type``, the
``agent_id`` it routes to, and its own ``credentials``. Several records may
share a ``channel_type`` (e.g. two Feishu bots), which is exactly what a team of
independent AI employees needs.

``resolve_channel_instances`` returns a uniform list of :class:`ChannelInstance`
for both worlds, so the launcher never branch on which config style is in play. When ``channel_instances`` is absent it synthesizes one
instance per legacy ``channel_type`` with no credential override, i.e. the old
behavior byte-for-byte.
"""

from __future__ import annotations

import json
import os
import re
import secrets
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional

from common import const
from common.log import logger

# Length of the random suffix in a generated instance id. 10 hex chars gives
# ~40 bits of entropy, plenty to avoid collisions across a user's own bots while
# staying short enough to read and type.
_INSTANCE_ID_RANDOM_LEN = 10


def new_instance_id(channel_type: str, taken: Iterable[str] = ()) -> str:
    """Return a stable, unique id for a freshly created channel instance.

    Shape is ``{channel_type}-{random}`` (e.g. ``feishu-a3f9c2e1b7``): the
    prefix keeps the type recognizable at a glance, the random suffix makes it
    unique and stable across restarts. Ids provided elsewhere (e.g. handed down
    by a remote controller) are honored as-is and never regenerated; this helper
    is only for the local "create a new instance" path.
    """
    ctype = _normalize_type((channel_type or "").strip()) or "channel"
    existing = set(taken)
    while True:
        candidate = f"{ctype}-{secrets.token_hex(_INSTANCE_ID_RANDOM_LEN // 2 + 1)[:_INSTANCE_ID_RANDOM_LEN]}"
        if candidate not in existing:
            return candidate


def is_local_instance_id(instance_id: str, channel_type: str) -> bool:
    """True if *instance_id* was minted on this machine for *channel_type*.

    Local ids have exactly two shapes: the bare channel type (a legacy flat
    config folded into ``channel_instances``) and ``{channel_type}-{random}``
    from :func:`new_instance_id`. Any other id was provided from outside and
    stands for a distinct, separately provisioned bot. Callers use this to
    decide whether an instance may adopt machine-local state that was written
    without an id (e.g. a credentials file) or must be treated as brand new.
    """
    iid = (instance_id or "").strip()
    raw = (channel_type or "").strip()
    ctype = _normalize_type(raw)
    if not iid or not ctype:
        return False
    if iid in (ctype, raw):
        return True
    return re.fullmatch(rf"{re.escape(ctype)}-[0-9a-f]{{{_INSTANCE_ID_RANDOM_LEN}}}", iid) is not None


# Per channel type, the config keys that make up its credentials. Only these
# keys are copied into a per-instance override; everything else (ports, feature
# flags) stays global in conf(). Keep in sync with the channel classes' cfg()
# reads. Extend as more channel types gain multi-instance support.
CREDENTIAL_KEYS: Dict[str, tuple] = {
    const.FEISHU: (
        "feishu_app_id",
        "feishu_app_secret",
        "feishu_token",
        "feishu_bot_name",
    ),
    const.DINGTALK: (
        "dingtalk_client_id",
        "dingtalk_client_secret",
        "dingtalk_robot_code",
    ),
    const.WECOM_BOT: (
        "wecom_bot_id",
        "wecom_bot_secret",
        "wecom_bot_token",
        "wecom_bot_encoding_aes_key",
    ),
    const.WEIXIN: (
        "weixin_token",
        "weixin_base_url",
    ),
    const.QQ: (
        "qq_app_id",
        "qq_app_secret",
    ),
    const.TELEGRAM: (
        "telegram_token",
    ),
    const.SLACK: (
        "slack_bot_token",
        "slack_app_token",
    ),
    const.DISCORD: (
        "discord_token",
    ),
}

# Short human labels used only to seed a new instance's default name (e.g.
# "微信 2"). Purely cosmetic and easily overridden by the user, so an unknown
# type simply falls back to its raw channel_type string.
_CHANNEL_TYPE_LABELS: Dict[str, str] = {
    const.FEISHU: "飞书",
    const.DINGTALK: "钉钉",
    const.WECOM_BOT: "企微机器人",
    const.WEIXIN: "微信",
    const.QQ: "QQ",
    const.TELEGRAM: "Telegram",
    const.SLACK: "Slack",
    const.DISCORD: "Discord",
}

# Channel types that actually support running more than one instance today.
# Others may appear in channel_instances but will run as a single instance
# (their @singleton is not yet bypassed); we log and fall back gracefully.
MULTI_INSTANCE_READY = frozenset({
    const.FEISHU,
    const.DINGTALK,
    const.QQ,
    const.TELEGRAM,
    const.SLACK,
    const.DISCORD,
    const.WEIXIN,
    const.WECOM_BOT,
})


@dataclass(frozen=True)
class ChannelInstance:
    """One channel to bring up, with its identity, binding and credentials."""

    instance_id: str
    channel_type: str
    agent_id: str = ""
    #: Human-friendly label the user can edit (e.g. "运营微信"). Optional: when
    #: empty the UI falls back to a credential-derived name or the instance id, so
    #: an install that never sets one is unaffected.
    name: str = ""
    credentials: Dict[str, Any] = field(default_factory=dict)
    #: Other Agents sharing this channel's conversations. ``agent_id`` is the
    #: owner/leader that receives every inbound message; ``members`` are the
    #: teammates it may hand work to (via @mention or the agent_delegate tool),
    #: exactly like a Web team conversation. Empty means a solo bot. Owner is
    #: never listed here.
    members: List[str] = field(default_factory=list)
    #: Connection profiles for teammates that do not live in this process, as
    #: ``{id, name, description}``. A member id that also appears here is reached
    #: through the transport rather than the local registry, so the owner can
    #: delegate to it exactly like a local teammate. Empty when every member is
    #: local, which is the only shape a stand-alone install ever produces.
    peers: List[dict] = field(default_factory=list)
    #: True when synthesized from legacy channel_type rather than an explicit
    #: channel_instances record. Legacy instances carry no credential override.
    legacy: bool = True


def _normalize_type(channel_type: str) -> str:
    if channel_type in (const.WEIXIN, "wx"):
        return const.WEIXIN
    return channel_type


def _parse_channel_type(raw) -> List[str]:
    """Legacy channel_type -> list of type names (string / CSV / list)."""
    if isinstance(raw, list):
        return [str(ch).strip() for ch in raw if str(ch).strip()]
    if isinstance(raw, str):
        return [ch.strip() for ch in raw.split(",") if ch.strip()]
    return []


def _legacy_instances(settings: Mapping[str, Any]) -> List[ChannelInstance]:
    """One instance per legacy channel_type, no credential override.

    Byte-for-byte the pre-multi-instance behavior: instance_id == channel_type,
    credentials read from the global conf() at runtime, routing left to the
    existing config-based AgentRouter (agent_id empty here).
    """
    out: List[ChannelInstance] = []
    for name in _parse_channel_type(settings.get("channel_type", "")):
        ctype = _normalize_type(name)
        out.append(ChannelInstance(instance_id=ctype, channel_type=ctype))
    return out


def _explicit_instances(raw_list: list) -> List[ChannelInstance]:
    out: List[ChannelInstance] = []
    seen_ids = set()
    for index, raw in enumerate(raw_list):
        if not isinstance(raw, Mapping):
            logger.warning(f"[ChannelInstances] entry #{index} is not an object, skipping")
            continue
        channel_type = _normalize_type(str(raw.get("channel_type") or "").strip())
        if not channel_type:
            logger.warning(f"[ChannelInstances] entry #{index} has no channel_type, skipping")
            continue
        instance_id = str(raw.get("instance_id") or "").strip() or channel_type
        if instance_id in seen_ids:
            logger.warning(
                f"[ChannelInstances] duplicate instance_id '{instance_id}', skipping"
            )
            continue
        seen_ids.add(instance_id)

        agent_id = str(raw.get("agent_id") or "").strip()
        name = str(raw.get("name") or "").strip()

        raw_members = raw.get("members")
        members: List[str] = []
        if isinstance(raw_members, list):
            for m in raw_members:
                mid = str(m or "").strip()
                # The owner is never a member of its own team, and ids appear
                # once: a duplicate here would show the same teammate twice.
                if mid and mid != agent_id and mid not in members:
                    members.append(mid)

        # Teammates reached through the transport rather than the local registry.
        # Absent on a solo bot and on any all-local team, so the old shape is
        # unchanged; present only when the control plane names off-process ones.
        raw_peers = raw.get("peers")
        peers = _clean_peers(raw_peers, agent_id) if isinstance(raw_peers, list) else []

        # Credentials may be given inline under "credentials", or as flat keys
        # on the record itself; only the known keys for this type are kept.
        raw_creds = raw.get("credentials")
        source = raw_creds if isinstance(raw_creds, Mapping) else raw
        creds: Dict[str, Any] = {}
        for key in CREDENTIAL_KEYS.get(channel_type, ()):
            if source.get(key) is not None:
                creds[key] = source.get(key)

        if channel_type not in MULTI_INSTANCE_READY:
            logger.info(
                f"[ChannelInstances] '{channel_type}' does not support multiple "
                f"instances yet; '{instance_id}' will run as a single instance"
            )

        out.append(
            ChannelInstance(
                instance_id=instance_id,
                channel_type=channel_type,
                agent_id=agent_id,
                name=name,
                credentials=creds,
                members=members,
                peers=peers,
                legacy=False,
            )
        )
    return out


def resolve_channel_instances(settings: Mapping[str, Any]) -> List[ChannelInstance]:
    """Channel instances to run for *settings*.

    Prefers explicit ``channel_instances`` (multi-Agent); otherwise synthesizes
    the legacy set from ``channel_type``. The ``web`` console is intentionally
    not represented here — it is managed separately by the launcher.
    """
    raw_list = settings.get("channel_instances")
    if isinstance(raw_list, list) and raw_list:
        instances = _explicit_instances(raw_list)
        if instances:
            return instances
        logger.warning(
            "[ChannelInstances] channel_instances present but yielded nothing; "
            "falling back to legacy channel_type"
        )
    return _legacy_instances(settings)


# ---------------------------------------------------------------------------
# Persistence helpers for the explicit multi-instance list.
#
# These edit the ``channel_instances`` array in the roster file (team.json) and
# leave the legacy ``channel_type`` + flat credentials path completely alone, so
# an install that never opts into multiple instances is never touched.
# ---------------------------------------------------------------------------

def _filtered_credentials(channel_type: str, source: Mapping[str, Any]) -> Dict[str, Any]:
    """Keep only the credential keys meaningful for *channel_type*."""
    ctype = _normalize_type((channel_type or "").strip())
    creds: Dict[str, Any] = {}
    for key in CREDENTIAL_KEYS.get(ctype, ()):
        value = source.get(key)
        if value is not None:
            creds[key] = value
    return creds


def bootstrap_legacy_instances(
    settings: Mapping[str, Any],
    roster: Mapping[str, Any],
    default_agent_id: str = "",
) -> List[Dict[str, Any]]:
    """Fold a legacy single-channel setup into ``channel_instances`` records.

    Called when an install first crosses into multi-Agent territory (team.json
    is being written for the first time). A legacy install keeps its channel
    credentials as flat keys in config.json and names the channel in
    ``channel_type``; multi-Agent mode routes entirely off ``channel_instances``,
    so those flat channels would silently go dark unless carried over.

    For every multi-instance-ready channel named in ``channel_type`` that has
    credentials in ``settings`` and no existing record, synthesize one record
    bound to the default Agent (``instance_id == channel_type``, matching the
    legacy id so nothing else has to change). The config.json flat keys are left
    in place untouched — multi-Agent startup simply ignores them.

    Returns the (possibly extended) channel_instances list.
    """
    records = [
        dict(item)
        for item in (roster.get("channel_instances") or [])
        if isinstance(item, Mapping)
    ]
    have_types = {
        _normalize_type(str(r.get("channel_type") or "").strip()) for r in records
    }
    default_id = (default_agent_id or roster.get("default_agent_id") or "").strip()

    for name in _parse_channel_type(settings.get("channel_type", "")):
        ctype = _normalize_type(name)
        if ctype not in MULTI_INSTANCE_READY or ctype in have_types:
            continue
        creds = _filtered_credentials(ctype, settings)
        if not creds and not (ctype == const.WEIXIN and _legacy_weixin_login()):
            continue
        records.append(
            {
                "instance_id": ctype,
                "channel_type": ctype,
                "agent_id": default_id,
                "name": _CHANNEL_TYPE_LABELS.get(ctype, ctype),
                "credentials": creds,
            }
        )
        have_types.add(ctype)
        # Weixin's scan-login token lives in a credentials file, not config.json.
        # The bootstrapped instance (instance_id == "weixin") reads a per-instance
        # file, so carry the legacy default file over to it — otherwise the user
        # would have to re-scan just because they added an Agent.
        if ctype == const.WEIXIN:
            _carry_weixin_credentials_file(ctype)
        logger.info(
            f"[ChannelInstances] bootstrapped legacy '{ctype}' credentials into a "
            f"channel_instances record bound to '{default_id or 'default'}'"
        )
    return records


def _legacy_weixin_login() -> bool:
    """Whether the legacy single Weixin channel holds a scan login.

    Its token lives in the default credentials file, and config.json usually
    has no weixin keys at all, so the flat keys alone would leave a logged-in
    channel out of the roster. Not applied where channels are provisioned from
    outside: there the roster is the provisioner's to fill, and a leftover file
    must not bring back a channel it removed.
    """
    try:
        from common.utils import is_cloud_deployment
        from config import get_weixin_credentials_path

        if is_cloud_deployment():
            return False
        with open(get_weixin_credentials_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
        return isinstance(data, dict) and bool(data.get("token"))
    except Exception:
        return False


def _carry_weixin_credentials_file(instance_id: str) -> None:
    """Copy the legacy Weixin token file to the per-instance path, once.

    Best-effort and idempotent: if the legacy default file exists and the
    per-instance file does not yet, the token (and persisted context tokens) are
    copied so the bootstrapped instance stays logged in. Never overwrites an
    existing per-instance file, and never raises into the write path.
    """
    try:
        import shutil
        from config import get_weixin_credentials_path

        legacy = get_weixin_credentials_path()
        target = get_weixin_credentials_path(instance_id)
        if legacy == target:
            return
        if os.path.exists(legacy) and not os.path.exists(target):
            shutil.copy2(legacy, target)
            logger.info(
                f"[ChannelInstances] carried Weixin credentials '{legacy}' -> "
                f"'{target}' so the bootstrapped instance stays logged in"
            )
    except Exception as e:
        logger.warning(f"[ChannelInstances] Weixin credentials carry-over skipped: {e}")


def read_raw_instances(settings: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """The raw ``channel_instances`` records as stored, or an empty list."""
    from agent import team

    roster = team.read(settings)
    raw = roster.get("channel_instances")
    if isinstance(raw, list):
        return [dict(item) for item in raw if isinstance(item, Mapping)]
    return []


def _clean_members(members, owner_id: str) -> list:
    """Normalize a members list: strings, de-duped, no owner, order preserved."""
    out: list = []
    owner = (owner_id or "").strip()
    for m in members or []:
        mid = str(m or "").strip()
        if mid and mid != owner and mid not in out:
            out.append(mid)
    return out


def _clean_peers(peers, owner_id: str) -> list:
    """Normalize a peers list: ``{id, name, description}`` dicts, de-duped by id,
    no owner, order preserved. Anything without an id is dropped."""
    out: list = []
    seen = set()
    owner = (owner_id or "").strip()
    for p in peers or []:
        if not isinstance(p, Mapping):
            continue
        pid = str(p.get("id") or p.get("agent_id") or "").strip()
        if not pid or pid == owner or pid in seen:
            continue
        seen.add(pid)
        entry = {"id": pid, "name": str(p.get("name") or pid).strip() or pid}
        desc = str(p.get("description") or "").strip()
        if desc:
            entry["description"] = desc
        out.append(entry)
    return out


def default_instance_name(channel_type: str, records: Iterable[Mapping[str, Any]]) -> str:
    """A friendly default label for a freshly created instance of *channel_type*.

    Shape is "<type label>" for the first instance of a type and "<type label> N"
    for later ones, so a second WeChat bot reads as "微信 2" rather than a random
    id. Only used to seed the field; the user can rename it afterwards.
    """
    ctype = _normalize_type((channel_type or "").strip())
    label = _CHANNEL_TYPE_LABELS.get(ctype, ctype)
    same_type = sum(
        1
        for r in records
        if _normalize_type(str(r.get("channel_type") or "").strip()) == ctype
    )
    return label if same_type == 0 else f"{label} {same_type + 1}"


def upsert_instance(
    settings: Mapping[str, Any],
    channel_type: str,
    instance_id: str = "",
    agent_id: Optional[str] = None,
    credentials: Optional[Mapping[str, Any]] = None,
    members: Optional[list] = None,
    peers: Optional[list] = None,
    name: Optional[str] = None,
) -> ChannelInstance:
    """Create or update one channel instance record and persist it.

    Matching is by ``instance_id``. When it is empty a new stable id is
    generated. ``agent_id``, ``credentials``, ``members``, ``peers`` and ``name``
    are merged onto any existing record so a partial update (e.g. credentials
    only) does not drop the binding, the team or the label. Pass ``members=None``
    (``peers=None``) to leave the team (peer directory) untouched, or ``[]`` to
    clear it. Pass ``name=None`` to leave the label untouched; a brand-new record
    with no name is seeded with a friendly default. Returns the resulting
    :class:`ChannelInstance`.
    """
    from agent import team

    ctype = _normalize_type((channel_type or "").strip())
    records = read_raw_instances(settings)
    taken = {str(r.get("instance_id") or "").strip() for r in records}

    target_id = (instance_id or "").strip()
    if not target_id:
        target_id = new_instance_id(ctype, taken)

    incoming_creds = _filtered_credentials(ctype, credentials or {})

    updated = False
    for record in records:
        if str(record.get("instance_id") or "").strip() != target_id:
            continue
        record["channel_type"] = ctype
        if agent_id is not None:
            record["agent_id"] = str(agent_id).strip()
        if name is not None:
            new_name = str(name).strip()
            if new_name:
                record["name"] = new_name
            else:
                record.pop("name", None)
        if incoming_creds:
            merged = dict(record.get("credentials") or {})
            merged.update(incoming_creds)
            record["credentials"] = merged
        if members is not None:
            cleaned = _clean_members(members, record.get("agent_id") or "")
            if cleaned:
                record["members"] = cleaned
            else:
                record.pop("members", None)
        if peers is not None:
            cleaned_peers = _clean_peers(peers, record.get("agent_id") or "")
            if cleaned_peers:
                record["peers"] = cleaned_peers
            else:
                record.pop("peers", None)
        updated = True
        result_record = record
        break

    if not updated:
        # Seed a friendly default label for a new instance so the console has
        # something readable to show before the user renames it. Computed against
        # the records *before* this one is appended, so the first is unnumbered.
        seeded_name = str(name).strip() if name is not None else ""
        if not seeded_name:
            seeded_name = default_instance_name(ctype, records)
        result_record = {
            "instance_id": target_id,
            "channel_type": ctype,
            "agent_id": str(agent_id).strip() if agent_id is not None else "",
            "name": seeded_name,
            "credentials": incoming_creds,
        }
        cleaned = _clean_members(members, result_record["agent_id"])
        if cleaned:
            result_record["members"] = cleaned
        cleaned_peers = _clean_peers(peers, result_record["agent_id"])
        if cleaned_peers:
            result_record["peers"] = cleaned_peers
        records.append(result_record)

    roster = team.read(settings)
    roster["channel_instances"] = records
    team.write(settings, roster)

    return ChannelInstance(
        instance_id=target_id,
        channel_type=ctype,
        agent_id=str(result_record.get("agent_id") or ""),
        name=str(result_record.get("name") or ""),
        credentials=dict(result_record.get("credentials") or {}),
        members=list(result_record.get("members") or []),
        peers=[dict(p) for p in (result_record.get("peers") or [])],
        legacy=False,
    )


def remove_instance(settings: Mapping[str, Any], instance_id: str) -> bool:
    """Drop one instance record by id. Returns True if something was removed."""
    from agent import team

    target_id = (instance_id or "").strip()
    if not target_id:
        return False
    records = read_raw_instances(settings)
    kept = [r for r in records if str(r.get("instance_id") or "").strip() != target_id]
    if len(kept) == len(records):
        return False
    roster = team.read(settings)
    roster["channel_instances"] = kept
    team.write(settings, roster)
    return True


def get_instance(settings: Mapping[str, Any], instance_id: str) -> Optional[ChannelInstance]:
    """Resolve one instance by id, or None.

    Overlays the roster file first so the lookup works even when the caller
    passes bare ``conf()`` (channel_instances lives in team.json, not config).
    """
    from agent import team

    target_id = (instance_id or "").strip()
    resolved = team.resolve(settings)
    for inst in resolve_channel_instances(resolved):
        if inst.instance_id == target_id:
            return inst
    return None
