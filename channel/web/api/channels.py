"""The channels view's endpoints: /api/channels and the two login flows.

ChannelsHandler lists the IM channels, saves their credentials and asks the
running ChannelManager to start or stop them. The other two serve the
interactive sign-ins that cannot be reduced to a form: the WeChat QR code,
and Feishu's one-click app registration.
"""

from collections import OrderedDict
import json
import os
import threading
import time

import web

from channel.web.core._common import (
    _live_channel_manager,
    _read_config_file_for_write,
    _require_auth,
)
from common.log import logger
from config import conf, get_data_root, get_weixin_credentials_path


class ChannelsHandler:
    """API for managing external channel configurations (feishu, dingtalk, etc)."""

    CHANNEL_DEFS = OrderedDict([
        ("weixin", {
            "label": {"zh": "微信", "en": "WeChat"},
            "icon": "fa-comment",
            "color": "emerald",
            "fields": [],
        }),
        ("feishu", {
            "label": {"zh": "飞书", "en": "Feishu"},
            "icon": "fa-paper-plane",
            "color": "blue",
            "fields": [
                {"key": "feishu_app_id", "label": "App ID", "type": "text"},
                {"key": "feishu_app_secret", "label": "App Secret", "type": "secret"},
            ],
        }),
        ("dingtalk", {
            "label": {"zh": "钉钉", "en": "DingTalk"},
            "icon": "fa-comments",
            "color": "blue",
            "fields": [
                {"key": "dingtalk_client_id", "label": "Client ID", "type": "text"},
                {"key": "dingtalk_client_secret", "label": "Client Secret", "type": "secret"},
            ],
        }),
        ("wecom_bot", {
            "label": {"zh": "企微智能机器人", "en": "WeCom Bot"},
            "icon": "fa-robot",
            "color": "emerald",
            "fields": [
                {"key": "wecom_bot_id", "label": "Bot ID", "type": "text"},
                {"key": "wecom_bot_secret", "label": "Secret", "type": "secret"},
            ],
        }),
        ("qq", {
            "label": {"zh": "QQ 机器人", "en": "QQ Bot"},
            "icon": "fa-comment",
            "color": "blue",
            "fields": [
                {"key": "qq_app_id", "label": "App ID", "type": "text"},
                {"key": "qq_app_secret", "label": "App Secret", "type": "secret"},
            ],
        }),
        ("wechatcom_app", {
            "label": {"zh": "企微自建应用", "en": "WeCom App"},
            "icon": "fa-building",
            "color": "emerald",
            "fields": [
                {"key": "wechatcom_corp_id", "label": "Corp ID", "type": "text"},
                {"key": "wechatcomapp_agent_id", "label": "Agent ID", "type": "text"},
                {"key": "wechatcomapp_secret", "label": "Secret", "type": "secret"},
                {"key": "wechatcomapp_token", "label": "Token", "type": "secret"},
                {"key": "wechatcomapp_aes_key", "label": "AES Key", "type": "secret"},
                {"key": "wechatcomapp_port", "label": "Port", "type": "number", "default": 9898},
            ],
        }),
        ("wechat_kf", {
            "label": {"zh": "微信客服", "en": "WeChat Customer Service"},
            "icon": "fa-headset",
            "color": "emerald",
            "fields": [
                {"key": "wechat_kf_corp_id", "label": "Corp ID", "type": "text"},
                {"key": "wechat_kf_secret", "label": "Secret", "type": "secret"},
                {"key": "wechat_kf_token", "label": "Token", "type": "secret"},
                {"key": "wechat_kf_aes_key", "label": "AES Key", "type": "secret"},
                {"key": "wechat_kf_port", "label": "Port", "type": "number", "default": 9888},
            ],
        }),
        ("wechatmp", {
            "label": {"zh": "公众号", "en": "WeChat MP"},
            "icon": "fa-comment-dots",
            "color": "emerald",
            "fields": [
                {"key": "wechatmp_app_id", "label": "App ID", "type": "text"},
                {"key": "wechatmp_app_secret", "label": "App Secret", "type": "secret"},
                {"key": "wechatmp_token", "label": "Token", "type": "secret"},
                {"key": "wechatmp_aes_key", "label": "AES Key", "type": "secret"},
                {"key": "wechatmp_port", "label": "Port", "type": "number", "default": 8080},
            ],
        }),
        ("telegram", {
            "label": {"zh": "Telegram", "en": "Telegram"},
            "icon": "fa-paper-plane",
            "color": "sky",
            "fields": [
                {"key": "telegram_token", "label": "Bot Token", "type": "secret"},
            ],
        }),
        ("slack", {
            "label": {"zh": "Slack", "en": "Slack"},
            "icon": "fa-hashtag",
            "color": "purple",
            "fields": [
                {"key": "slack_bot_token", "label": "Bot Token (xoxb-)", "type": "secret"},
                {"key": "slack_app_token", "label": "App Token (xapp-)", "type": "secret"},
            ],
        }),
        ("discord", {
            "label": {"zh": "Discord", "en": "Discord"},
            "icon": "fa-discord",
            "color": "indigo",
            "fields": [
                {"key": "discord_token", "label": "Bot Token", "type": "secret"},
            ],
        }),
    ])

    # Channels that lead the list in English. Everything defined above them
    # needs a mainland-China account, so an English user scrolling past those
    # to reach Telegram is scrolling past options they cannot use.
    EN_FIRST_CHANNELS = ("telegram", "discord", "slack")

    @classmethod
    def _ordered_channel_defs(cls, lang=None):
        """
        Channel definitions ordered for `lang`, defaulting to the configured UI
        language. Callers pass the language of the interface they are drawing:
        the desktop client keeps its own language in localStorage, so the global
        setting is not always what the user is looking at.
        """
        from common import i18n
        if (lang or i18n.get_language()) != i18n.EN:
            return list(cls.CHANNEL_DEFS.items())
        lead = [(k, cls.CHANNEL_DEFS[k]) for k in cls.EN_FIRST_CHANNELS if k in cls.CHANNEL_DEFS]
        rest = [(k, v) for k, v in cls.CHANNEL_DEFS.items() if k not in cls.EN_FIRST_CHANNELS]
        return lead + rest

    @staticmethod
    def _get_weixin_login_status(instance_id: str = "weixin") -> str:
        """Login state of the running Weixin channel registered under *instance_id*.

        The bare type is the legacy single-instance key; multi-instance channels
        register under their own id. Returns "unknown" when nothing is running
        under that key so a card never claims a login it cannot see.
        """
        try:
            mgr = _live_channel_manager()
            if mgr:
                ch = mgr.get_channel(instance_id or "weixin")
                if ch and hasattr(ch, 'login_status'):
                    return ch.login_status
        except Exception:
            pass
        return "unknown"

    @staticmethod
    def _mask_secret(value: str) -> str:
        if not value or len(value) <= 8:
            return value
        return value[:4] + "*" * (len(value) - 8) + value[-4:]

    @staticmethod
    def _parse_channel_list(raw) -> list:
        if isinstance(raw, list):
            return [ch.strip() for ch in raw if ch.strip()]
        if isinstance(raw, str):
            return [ch.strip() for ch in raw.split(",") if ch.strip()]
        return []

    @classmethod
    def _active_channel_set(cls) -> set:
        return set(cls._parse_channel_list(conf().get("channel_type", "")))

    @staticmethod
    def _multi_agent_mode() -> bool:
        """True once the install has crossed into multi-Agent territory.

        The team.json file only exists after a second Agent (or channel
        instance) is created; until then everything lives in config.json and the
        channels view stays single-instance, exactly as a legacy install expects.
        """
        from agent import team
        return team.team_file(conf()).exists()

    @classmethod
    def _channel_instances_view(cls) -> list:
        """Per-instance channel cards for every multi-instance-ready type.

        Expands ``channel_instances`` into one card each, carrying instance_id,
        the bound agent_id and masked credentials, so the console can show and
        edit each bot independently. Covers all MULTI_INSTANCE_READY types
        (feishu, dingtalk, qq, telegram, slack, discord), not just feishu.
        """
        from channel.channel_instances import (
            resolve_channel_instances,
            MULTI_INSTANCE_READY,
        )
        from agent import team

        settings = team.resolve(conf())
        local_config = conf()
        out = []
        for inst in resolve_channel_instances(settings):
            if inst.channel_type not in MULTI_INSTANCE_READY:
                continue
            ch_def = cls.CHANNEL_DEFS.get(inst.channel_type)
            if not ch_def:
                continue
            fields_out = []
            for f in ch_def["fields"]:
                raw_val = (inst.credentials or {}).get(f["key"], "")
                # Mirror runtime credential resolution (channel.cfg): when an
                # instance record is missing a value, the channel falls back to
                # the global config.json. Show the same value so a credential
                # the bot actually uses never renders as a blank field (e.g. a
                # secret that lives only in the global config still shows masked).
                if raw_val in (None, ""):
                    raw_val = local_config.get(f["key"], f.get("default", ""))
                if f["type"] == "secret" and raw_val:
                    display_val = cls._mask_secret(str(raw_val))
                else:
                    display_val = raw_val
                label_val = f["label"]
                fields_out.append({
                    "key": f["key"],
                    "label": label_val,
                    "type": f["type"],
                    "value": display_val,
                    "default": f.get("default", ""),
                })
            label_val = ch_def["label"]
            card = {
                "name": inst.channel_type,
                "instance_id": inst.instance_id,
                "channel_type": inst.channel_type,
                "agent_id": inst.agent_id or "",
                # User-editable label; empty falls back client-side to the id.
                "instance_name": inst.name or "",
                "members": list(inst.members or []),
                "label": label_val,
                "icon": ch_def["icon"],
                "color": ch_def["color"],
                "active": True,
                "fields": fields_out,
            }
            # A Weixin instance is only "connected" once its scan login is
            # done; surface the live state so a card waiting for a scan says
            # so (and offers the QR) instead of claiming to be connected.
            if inst.channel_type == "weixin":
                status = cls._get_weixin_login_status(inst.instance_id)
                if status != "unknown":
                    card["login_status"] = status
            out.append(card)
        return out

    def GET(self):
        _require_auth()
        web.header('Content-Type', 'application/json; charset=utf-8')
        try:
            from common import i18n
            local_config = conf()
            active_channels = self._active_channel_set()
            channels = []
            # The caller may request a language; only English is supported now.
            req_lang = web.input().get("lang") or None
            if req_lang != i18n.EN:
                req_lang = None
            for ch_name, ch_def in self._ordered_channel_defs(req_lang):
                fields_out = []
                for f in ch_def["fields"]:
                    raw_val = local_config.get(f["key"], f.get("default", ""))
                    if f["type"] == "secret" and raw_val:
                        display_val = self._mask_secret(str(raw_val))
                    else:
                        display_val = raw_val
                    
                    label_val = f["label"]

                    fields_out.append({
                        "key": f["key"],
                        "label": label_val,
                        "type": f["type"],
                        "value": display_val,
                        "default": f.get("default", ""),
                    })
                
                label_val = ch_def["label"]

                ch_info = {
                    "name": ch_name,
                    "label": label_val,
                    "icon": ch_def["icon"],
                    "color": ch_def["color"],
                    "active": ch_name in active_channels,
                    "fields": fields_out,
                }
                if ch_name == "weixin" and ch_name in active_channels:
                    ch_info["login_status"] = self._get_weixin_login_status()
                channels.append(ch_info)

            from channel.channel_instances import MULTI_INSTANCE_READY
            multi_agent = self._multi_agent_mode()
            payload = {
                "status": "success",
                "channels": channels,
                "multi_agent": multi_agent,
                "multi_instance_types": sorted(MULTI_INSTANCE_READY),
            }
            # In multi-Agent mode the multi-instance-ready types (feishu) render
            # one card per channel_instances record instead of one per type.
            if multi_agent:
                payload["instances"] = self._channel_instances_view()
            return json.dumps(payload, ensure_ascii=False)
        except Exception as e:
            logger.error(f"[WebChannel] Channels API error: {e}")
            return json.dumps({"status": "error", "message": str(e)})

    def POST(self):
        _require_auth()
        web.header('Content-Type', 'application/json; charset=utf-8')
        try:
            body = json.loads(web.data())
            action = body.get("action")
            channel_name = body.get("channel")

            if not action or not channel_name:
                return json.dumps({"status": "error", "message": "action and channel required"})

            if channel_name not in self.CHANNEL_DEFS:
                return json.dumps({"status": "error", "message": f"unknown channel: {channel_name}"})

            # Multi-Agent + a multi-instance-ready type (feishu) manages each bot
            # as its own channel_instances record in team.json rather than the
            # legacy flat config.json path. instance_id empty on connect means
            # "create a new instance".
            from channel.channel_instances import MULTI_INSTANCE_READY
            instance_id = (body.get("instance_id") or "").strip()
            # A multi-instance-ready type (feishu) is only an *instance* when it
            # carries an instance_id (connect with an empty id creates one). But
            # the same type can still be active the legacy way — enabled in
            # config.json's channel_type before this install went multi-Agent —
            # in which case its card has no instance_id. Disconnect/rename on
            # such a card must fall through to the legacy per-type path, or it
            # would be rejected ("instance_id is required") and never removed.
            is_instance_op = action in ("save", "connect") or bool(instance_id)
            if self._multi_agent_mode() and channel_name in MULTI_INSTANCE_READY and is_instance_op:
                if action == "save":
                    return self._handle_instance_save(channel_name, instance_id, body.get("config", {}))
                elif action == "connect":
                    return self._handle_instance_connect(channel_name, instance_id, body.get("config", {}))
                elif action == "disconnect":
                    return self._handle_instance_disconnect(channel_name, instance_id)
                elif action == "rename":
                    return self._handle_instance_rename(channel_name, instance_id, body.get("name", ""))
                else:
                    return json.dumps({"status": "error", "message": f"unknown action: {action}"})

            if action == "save":
                return self._handle_save(channel_name, body.get("config", {}))
            elif action == "connect":
                return self._handle_connect(channel_name, body.get("config", {}))
            elif action == "disconnect":
                return self._handle_disconnect(channel_name)
            else:
                return json.dumps({"status": "error", "message": f"unknown action: {action}"})
        except Exception as e:
            logger.error(f"[WebChannel] Channels POST error: {e}")
            return json.dumps({"status": "error", "message": str(e)})

    def _handle_save(self, channel_name: str, updates: dict):
        ch_def = self.CHANNEL_DEFS[channel_name]
        valid_keys = {f["key"] for f in ch_def["fields"]}
        secret_keys = {f["key"] for f in ch_def["fields"] if f["type"] == "secret"}

        local_config = conf()
        applied = {}
        # Track which applied keys actually changed value, so a save that leaves
        # every credential untouched (e.g. the user re-saved the form, or only
        # an unrelated setting moved) does not needlessly tear down and
        # reconnect a live channel.
        changed = {}
        for key, value in updates.items():
            if key not in valid_keys:
                continue
            if key in secret_keys:
                if not value or (len(value) > 8 and "*" * 4 in value):
                    continue
            field_def = next((f for f in ch_def["fields"] if f["key"] == key), None)
            if field_def:
                if field_def["type"] == "number":
                    value = int(value)
                elif field_def["type"] == "bool":
                    value = bool(value)
            if local_config.get(key) != value:
                changed[key] = value
            local_config[key] = value
            applied[key] = value

        if not applied:
            return json.dumps({"status": "error", "message": "no valid fields to update"})

        config_path = os.path.join(get_data_root(), "config.json")
        file_cfg = _read_config_file_for_write()
        file_cfg.update(applied)
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(file_cfg, f, indent=4, ensure_ascii=False)

        logger.info(
            f"[WebChannel] Channel '{channel_name}' config saved: {list(applied.keys())}, "
            f"changed: {list(changed.keys())}"
        )

        # Only a real change to this channel's config warrants a restart. An
        # idempotent save must not interrupt a connected channel.
        should_restart = False
        active_channels = self._active_channel_set()
        if channel_name in active_channels and changed:
            should_restart = True
            try:
                mgr = _live_channel_manager()
                if mgr:
                    threading.Thread(
                        target=mgr.restart,
                        args=(channel_name,),
                        daemon=True,
                    ).start()
                    logger.info(f"[WebChannel] Channel '{channel_name}' restart triggered")
            except Exception as e:
                logger.warning(f"[WebChannel] Failed to restart channel '{channel_name}': {e}")

        return json.dumps({
            "status": "success",
            "applied": list(applied.keys()),
            "restarted": should_restart,
        }, ensure_ascii=False)

    def _handle_connect(self, channel_name: str, updates: dict):
        """Save config fields, add channel to channel_type, and start it."""
        ch_def = self.CHANNEL_DEFS[channel_name]
        valid_keys = {f["key"] for f in ch_def["fields"]}
        secret_keys = {f["key"] for f in ch_def["fields"] if f["type"] == "secret"}

        # Feishu connected via web console must use websocket (long connection) mode
        if channel_name == "feishu":
            updates.setdefault("feishu_event_mode", "websocket")
            valid_keys.add("feishu_event_mode")

        local_config = conf()
        applied = {}
        for key, value in updates.items():
            if key not in valid_keys:
                continue
            if key in secret_keys:
                if not value or (len(value) > 8 and "*" * 4 in value):
                    continue
            field_def = next((f for f in ch_def["fields"] if f["key"] == key), None)
            if field_def:
                if field_def["type"] == "number":
                    value = int(value)
                elif field_def["type"] == "bool":
                    value = bool(value)
            local_config[key] = value
            applied[key] = value

        existing = self._parse_channel_list(conf().get("channel_type", ""))
        if channel_name not in existing:
            existing.append(channel_name)
        new_channel_type = ",".join(existing)
        local_config["channel_type"] = new_channel_type

        config_path = os.path.join(get_data_root(), "config.json")
        file_cfg = _read_config_file_for_write()
        file_cfg.update(applied)
        file_cfg["channel_type"] = new_channel_type
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(file_cfg, f, indent=4, ensure_ascii=False)

        logger.info(f"[WebChannel] Channel '{channel_name}' connecting, channel_type={new_channel_type}")

        # Feishu pulls its SDK bundle on first use; tell the UI so it can warn
        # about the one-time wait rather than reporting an instant success.
        downloading = False
        if channel_name == "feishu":
            try:
                from channel.feishu import lark_install
                downloading = lark_install.needs_download()
            except Exception as e:
                logger.warning(f"[WebChannel] Could not check Feishu SDK state: {e}")

        def _do_start():
            try:
                import sys
                app_module = sys.modules.get('__main__') or sys.modules.get('app')
                clear_fn = getattr(app_module, '_clear_singleton_cache', None) if app_module else None
                mgr = _live_channel_manager()
                if mgr is None:
                    logger.warning(f"[WebChannel] ChannelManager not available, cannot start '{channel_name}'")
                    return
                # Stop existing instance first if still running (e.g. re-connect without disconnect)
                existing_ch = mgr.get_channel(channel_name)
                if existing_ch is not None:
                    logger.info(f"[WebChannel] Stopping existing '{channel_name}' before reconnect...")
                    mgr.stop(channel_name)
                # Always wait for the remote service to release the old connection before
                # establishing a new one (DingTalk drops callbacks on duplicate connections)
                logger.info(f"[WebChannel] Waiting for '{channel_name}' old connection to close...")
                time.sleep(5)
                if clear_fn:
                    clear_fn(channel_name)
                logger.info(f"[WebChannel] Starting channel '{channel_name}'...")
                mgr.start([channel_name], first_start=False)
                logger.info(f"[WebChannel] Channel '{channel_name}' start completed")
            except Exception as e:
                logger.error(f"[WebChannel] Failed to start channel '{channel_name}': {e}",
                             exc_info=True)

        threading.Thread(target=_do_start, daemon=True).start()

        return json.dumps({
            "status": "success",
            "channel_type": new_channel_type,
            "downloading": downloading,
        }, ensure_ascii=False)

    def _handle_disconnect(self, channel_name: str):
        existing = self._parse_channel_list(conf().get("channel_type", ""))
        existing = [ch for ch in existing if ch != channel_name]
        new_channel_type = ",".join(existing)

        local_config = conf()
        local_config["channel_type"] = new_channel_type

        config_path = os.path.join(get_data_root(), "config.json")
        file_cfg = _read_config_file_for_write()
        file_cfg["channel_type"] = new_channel_type
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(file_cfg, f, indent=4, ensure_ascii=False)

        def _do_stop():
            try:
                import sys
                app_module = sys.modules.get('__main__') or sys.modules.get('app')
                mgr = _live_channel_manager()
                clear_fn = getattr(app_module, '_clear_singleton_cache', None) if app_module else None
                if mgr:
                    mgr.stop(channel_name)
                else:
                    logger.warning(f"[WebChannel] ChannelManager not found, cannot stop '{channel_name}'")
                if clear_fn:
                    clear_fn(channel_name)
                logger.info(f"[WebChannel] Channel '{channel_name}' disconnected, "
                            f"channel_type={new_channel_type}")
            except Exception as e:
                logger.warning(f"[WebChannel] Failed to stop channel '{channel_name}': {e}",
                               exc_info=True)

        threading.Thread(target=_do_stop, daemon=True).start()

        return json.dumps({
            "status": "success",
            "channel_type": new_channel_type,
        }, ensure_ascii=False)

    # ------------------------------------------------------------------
    # Multi-instance channel management (team.json driven, e.g. feishu)
    # ------------------------------------------------------------------
    @staticmethod
    def _channel_mgr():
        return _live_channel_manager()

    def _clean_credentials(self, channel_name: str, updates: dict) -> dict:
        """Keep only real, unmasked credential values for this channel type."""
        ch_def = self.CHANNEL_DEFS[channel_name]
        valid_keys = {f["key"] for f in ch_def["fields"]}
        secret_keys = {f["key"] for f in ch_def["fields"] if f["type"] == "secret"}
        creds = {}
        for key, value in (updates or {}).items():
            if key not in valid_keys:
                continue
            if key in secret_keys:
                # Skip empty or still-masked secrets so a save that leaves the
                # secret untouched does not overwrite it with the mask.
                if not value or (len(str(value)) > 8 and "*" * 4 in str(value)):
                    continue
            creds[key] = value
        return creds

    def _handle_instance_connect(self, channel_name: str, instance_id: str, updates: dict):
        """Create (empty id) or reconnect a channel instance, stored in team.json."""
        from channel.channel_instances import upsert_instance

        creds = self._clean_credentials(channel_name, updates)
        # Weixin scans its token during the QR flow (before the instance exists),
        # which lands in the global config. Fold it into this instance's own
        # credentials so the instance is self-contained: it stays logged in
        # across restarts and never depends on the transient global value.
        if channel_name == "weixin" and not creds.get("weixin_token"):
            token = conf().get("weixin_token", "")
            if token:
                creds["weixin_token"] = token
                base_url = conf().get("weixin_base_url", "")
                if base_url:
                    creds["weixin_base_url"] = base_url
                # Consume the transient QR token so the *next* Weixin instance
                # created (a different account) does not inherit this one's
                # token from the global config.
                conf()["weixin_token"] = ""
        inst = upsert_instance(
            conf(),
            channel_type=channel_name,
            instance_id=instance_id,
            credentials=creds,
        )

        downloading = False
        if channel_name == "feishu":
            try:
                from channel.feishu import lark_install
                downloading = lark_install.needs_download()
            except Exception as e:
                logger.warning(f"[WebChannel] Could not check Feishu SDK state: {e}")

        def _do_start():
            try:
                mgr = self._channel_mgr()
                if mgr is None:
                    logger.warning(
                        f"[WebChannel] ChannelManager unavailable, cannot start '{inst.instance_id}'"
                    )
                    return
                mgr.add_channel(inst)
                logger.info(f"[WebChannel] Channel instance '{inst.instance_id}' start completed")
            except Exception as e:
                logger.error(
                    f"[WebChannel] Failed to start channel instance '{inst.instance_id}': {e}",
                    exc_info=True,
                )

        threading.Thread(target=_do_start, daemon=True).start()
        return json.dumps({
            "status": "success",
            "instance_id": inst.instance_id,
            "downloading": downloading,
        }, ensure_ascii=False)

    def _handle_instance_save(self, channel_name: str, instance_id: str, updates: dict):
        """Update one instance's credentials in team.json and restart it."""
        from channel.channel_instances import get_instance, upsert_instance

        if not instance_id:
            return json.dumps({"status": "error", "message": "instance_id is required"})
        before = get_instance(conf(), instance_id)
        creds = self._clean_credentials(channel_name, updates)
        inst = upsert_instance(
            conf(),
            channel_type=channel_name,
            instance_id=instance_id,
            credentials=creds,
        )
        # Only restart when a credential actually changed, so re-saving an
        # unchanged form does not tear down a live connection.
        changed = not before or (dict(before.credentials or {}) != dict(inst.credentials or {}))
        if changed:
            def _do_restart():
                try:
                    mgr = self._channel_mgr()
                    if mgr is None:
                        return
                    mgr.restart(inst)
                except Exception as e:
                    logger.error(
                        f"[WebChannel] Failed to restart instance '{inst.instance_id}': {e}",
                        exc_info=True,
                    )
            threading.Thread(target=_do_restart, daemon=True).start()
        logger.info(
            f"[WebChannel] Channel instance '{inst.instance_id}' saved, "
            f"restart={'yes' if changed else 'no'}"
        )
        return json.dumps({"status": "success", "instance_id": inst.instance_id}, ensure_ascii=False)

    def _handle_instance_rename(self, channel_name: str, instance_id: str, name):
        """Set an instance's friendly label. Does not touch credentials or the
        live connection, so renaming never interrupts a running channel."""
        from channel.channel_instances import upsert_instance

        if not instance_id:
            return json.dumps({"status": "error", "message": "instance_id is required"})
        inst = upsert_instance(
            conf(),
            channel_type=channel_name,
            instance_id=instance_id,
            name=str(name or ""),
        )
        logger.info(f"[WebChannel] Channel instance '{inst.instance_id}' renamed to '{inst.name}'")
        return json.dumps(
            {"status": "success", "instance_id": inst.instance_id, "name": inst.name},
            ensure_ascii=False,
        )

    def _handle_instance_disconnect(self, channel_name: str, instance_id: str):
        """Remove one instance record from team.json and stop its channel."""
        from channel.channel_instances import remove_instance, read_raw_instances

        if not instance_id:
            return json.dumps({"status": "error", "message": "instance_id is required"})

        # A legacy channel (enabled the old way via config.json's channel_type)
        # is folded into channel_instances on every team.json write by
        # bootstrap_legacy_instances. Just dropping the record isn't enough:
        # remove_instance itself writes team.json, whose bootstrap immediately
        # re-materializes the record straight from channel_type — so the card
        # comes right back. Prune the type from channel_type *first* (when this
        # is the last instance of it), so by the time remove_instance writes,
        # the bootstrap has nothing to recreate.
        remaining = [
            r for r in read_raw_instances(conf())
            if str(r.get("instance_id") or "").strip() != instance_id
        ]
        self._prune_legacy_channel_type(channel_name, remaining)

        remove_instance(conf(), instance_id)

        def _do_stop():
            try:
                mgr = self._channel_mgr()
                if mgr is None:
                    return
                remover = getattr(mgr, "remove_channel", None)
                if callable(remover):
                    remover(instance_id)
                else:
                    mgr.stop(instance_id)
                logger.info(f"[WebChannel] Channel instance '{instance_id}' disconnected")
            except Exception as e:
                logger.warning(
                    f"[WebChannel] Failed to stop instance '{instance_id}': {e}",
                    exc_info=True,
                )

        threading.Thread(target=_do_stop, daemon=True).start()
        return json.dumps({"status": "success", "instance_id": instance_id}, ensure_ascii=False)

    def _prune_legacy_channel_type(self, channel_name: str, remaining):
        """Drop *channel_name* from config.json's channel_type once no instance
        of that type is left (``remaining`` = the instance records that will
        survive this disconnect).

        Without this, bootstrap_legacy_instances (which runs on every team.json
        write and is keyed off channel_type) would recreate the instance we just
        removed, so the disconnect would never stick. Only prunes when the last
        instance of the type is gone, so removing one of several Feishu bots
        leaves the type — and the others — untouched.
        """
        from channel.channel_instances import _normalize_type

        target = _normalize_type(channel_name)
        if any(_normalize_type(str(r.get("channel_type") or "")) == target for r in remaining):
            return

        existing = self._parse_channel_list(conf().get("channel_type", ""))
        pruned = [ch for ch in existing if _normalize_type(ch) != target]
        if len(pruned) == len(existing):
            return
        new_channel_type = ",".join(pruned)

        conf()["channel_type"] = new_channel_type
        try:
            config_path = os.path.join(get_data_root(), "config.json")
            file_cfg = _read_config_file_for_write()
            file_cfg["channel_type"] = new_channel_type
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(file_cfg, f, indent=4, ensure_ascii=False)
            logger.info(
                f"[WebChannel] Pruned legacy channel_type '{channel_name}', "
                f"channel_type={new_channel_type}"
            )
        except Exception as e:
            logger.warning(
                f"[WebChannel] Failed to prune legacy channel_type '{channel_name}': {e}",
                exc_info=True,
            )


class WeixinQrHandler:
    """Handle WeChat QR code login from the web console.

    GET  /api/weixin/qrlogin          → fetch a new QR code
    POST /api/weixin/qrlogin          → poll QR status or start channel after login
    """

    _qr_state = {}

    @staticmethod
    def _qr_to_data_uri(data: str) -> str:
        """Generate a QR code as a PNG data URI."""
        try:
            import qrcode as qr_lib
            import io
            import base64
            qr = qr_lib.QRCode(error_correction=qr_lib.constants.ERROR_CORRECT_L, box_size=6, border=2)
            qr.add_data(data)
            qr.make(fit=True)
            img = qr.make_image(fill_color="black", back_color="white")
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            b64 = base64.b64encode(buf.getvalue()).decode("ascii")
            return f"data:image/png;base64,{b64}"
        except ImportError:
            return ""

    # instance_id -> monotonic time of the last restart this handler kicked off,
    # so a card polling while the channel comes back up cannot restart it again.
    _restart_kicked = {}
    _RESTART_COOLDOWN_S = 20

    @staticmethod
    def _get_running_channel(instance_id: str = ""):
        try:
            mgr = _live_channel_manager()
            if mgr:
                return mgr.get_channel(instance_id or "weixin")
        except Exception:
            pass
        return None

    def _instance_qr(self, instance_id: str) -> str:
        """QR for an existing instance: read it off the running channel.

        The channel owns the scan for a live instance (it persists the token to
        its own credentials file on confirm), so this never falls back to the
        standalone flow — that one saves to the id-less default file, which the
        instance would not pick up, and its follow-up "connect" would create a
        second instance. If the channel's login attempt has already given up
        (status idle, no QR), restart it once so a fresh code is issued.
        """
        ch = self._get_running_channel(instance_id)
        if ch is None:
            return json.dumps({"status": "error", "message": "channel instance is not running"})

        qr_url = getattr(ch, "_current_qr_url", "") or ""
        if qr_url:
            return json.dumps({
                "status": "success",
                "qrcode_url": qr_url,
                "qr_image": self._qr_to_data_uri(qr_url),
                "source": "channel",
                "instance_id": instance_id,
            })

        login_status = getattr(ch, "login_status", "")
        last = WeixinQrHandler._restart_kicked.get(instance_id, 0)
        if login_status == "idle" and time.monotonic() - last > self._RESTART_COOLDOWN_S:
            WeixinQrHandler._restart_kicked[instance_id] = time.monotonic()
            mgr = _live_channel_manager()
            if mgr:
                threading.Thread(target=mgr.restart, args=(instance_id,), daemon=True).start()
                logger.info(f"[WebChannel] Weixin instance '{instance_id}' idle without QR, restarting for a new code")
        # Either the channel is mid-login and has not fetched a code yet, or a
        # restart is under way; the client retries shortly.
        return json.dumps({"status": "pending", "instance_id": instance_id})

    def GET(self):
        _require_auth()
        web.header('Content-Type', 'application/json; charset=utf-8')
        try:
            instance_id = (web.input().get("instance_id") or "").strip()
            if instance_id and instance_id != "weixin":
                return self._instance_qr(instance_id)

            running_ch = self._get_running_channel()
            if running_ch and hasattr(running_ch, '_current_qr_url') and running_ch._current_qr_url:
                qr_image = self._qr_to_data_uri(running_ch._current_qr_url)
                return json.dumps({
                    "status": "success",
                    "qrcode_url": running_ch._current_qr_url,
                    "qr_image": qr_image,
                    "source": "channel",
                })

            from channel.weixin.weixin_api import WeixinApi, DEFAULT_BASE_URL
            base_url = conf().get("weixin_base_url", DEFAULT_BASE_URL)
            api = WeixinApi(base_url=base_url)
            qr_resp = api.fetch_qr_code()
            qrcode = qr_resp.get("qrcode", "")
            qrcode_url = qr_resp.get("qrcode_img_content", "")
            if not qrcode:
                return json.dumps({"status": "error", "message": "No QR code returned"})
            qr_image = self._qr_to_data_uri(qrcode_url)
            WeixinQrHandler._qr_state = {
                "qrcode": qrcode,
                "qrcode_url": qrcode_url,
                "base_url": base_url,
            }
            return json.dumps({"status": "success", "qrcode_url": qrcode_url, "qr_image": qr_image})
        except Exception as e:
            logger.error(f"[WebChannel] WeixinQr GET error: {e}")
            return json.dumps({"status": "error", "message": str(e)})

    def POST(self):
        _require_auth()
        web.header('Content-Type', 'application/json; charset=utf-8')
        try:
            body = json.loads(web.data())
            action = body.get("action", "poll")

            if action == "poll":
                return self._poll_status()
            elif action == "refresh":
                return self.GET()
            else:
                return json.dumps({"status": "error", "message": f"unknown action: {action}"})
        except Exception as e:
            logger.error(f"[WebChannel] WeixinQr POST error: {e}")
            return json.dumps({"status": "error", "message": str(e)})

    def _poll_status(self):
        state = WeixinQrHandler._qr_state
        qrcode = state.get("qrcode", "")
        base_url = state.get("base_url", "")
        if not qrcode:
            return json.dumps({"status": "error", "message": "No active QR session"})

        from channel.weixin.weixin_api import WeixinApi, DEFAULT_BASE_URL
        api = WeixinApi(base_url=base_url or DEFAULT_BASE_URL)
        try:
            status_resp = api.poll_qr_status(qrcode, timeout=10)
        except Exception as e:
            return json.dumps({"status": "error", "message": str(e)})

        qr_status = status_resp.get("status", "wait")

        if qr_status == "confirmed":
            bot_token = status_resp.get("bot_token", "")
            bot_id = status_resp.get("ilink_bot_id", "")
            result_base_url = status_resp.get("baseurl", base_url)
            user_id = status_resp.get("ilink_user_id", "")

            if not bot_token or not bot_id:
                return json.dumps({"status": "error", "message": "Login confirmed but missing token"})

            cred_path = get_weixin_credentials_path()
            from channel.weixin.weixin_channel import _save_credentials
            _save_credentials(cred_path, {
                "token": bot_token,
                "base_url": result_base_url,
                "bot_id": bot_id,
                "user_id": user_id,
            })
            conf()["weixin_token"] = bot_token
            conf()["weixin_base_url"] = result_base_url

            WeixinQrHandler._qr_state = {}
            logger.info(f"[WebChannel] WeChat QR login confirmed: bot_id={bot_id}")

            return json.dumps({
                "status": "success",
                "qr_status": "confirmed",
                "bot_id": bot_id,
            })

        if qr_status == "expired":
            new_resp = api.fetch_qr_code()
            new_qrcode = new_resp.get("qrcode", "")
            new_qrcode_url = new_resp.get("qrcode_img_content", "")
            new_qr_image = self._qr_to_data_uri(new_qrcode_url)
            WeixinQrHandler._qr_state["qrcode"] = new_qrcode
            WeixinQrHandler._qr_state["qrcode_url"] = new_qrcode_url
            return json.dumps({
                "status": "success",
                "qr_status": "expired",
                "qrcode_url": new_qrcode_url,
                "qr_image": new_qr_image,
            })

        return json.dumps({"status": "success", "qr_status": qr_status})


class FeishuRegisterHandler:
    """飞书智能体应用一键创建（OAuth 设备授权流，基于 lark.register_app SDK）。

    GET  /api/feishu/register   → 启动注册：调用 SDK 生成二维码 URL，立即返回；
                                   后台线程继续轮询飞书侧直到用户扫码授权。
    POST /api/feishu/register   → 轮询当前会话状态（downloading / pending / done /
                                   error / expired）。桌面版首次启用时要先下载飞书
                                   SDK 包，此时二维码尚不存在，改由轮询补发。
                                   注册成功后不直接写 config，由前端再调
                                   /api/channels {action:'connect'} 走标准启用流程。
    """

    # 进程内单例状态（{url, expire_in, status, app_id, app_secret, error, thread}）。
    # 简单的本地自部署场景下不需要 session 隔离。
    _state = {}
    _lock = threading.Lock()

    @staticmethod
    def _qr_to_data_uri(data: str) -> str:
        """复用 WeixinQrHandler 的二维码渲染。"""
        return WeixinQrHandler._qr_to_data_uri(data)

    @classmethod
    def _reset_state(cls):
        with cls._lock:
            cls._state = {}

    @classmethod
    def _start_register_thread(cls):
        """启动一次新的注册会话。如已有进行中的会话，先取消（通过 cancel_event）。"""
        # 先取消可能存在的上一次会话，避免两个 SDK 线程并发 poll 同一个端点
        with cls._lock:
            old_cancel = cls._state.get("cancel_event") if cls._state else None
            if old_cancel is not None:
                old_cancel.set()
            cancel_event = threading.Event()
            cls._state = {"status": "starting", "cancel_event": cancel_event}

        def _worker():
            try:
                # Desktop builds don't bundle lark_oapi; fetch it on demand the
                # first time the user enables Feishu (requires network). Flag it
                # so the modal explains the wait instead of just spinning.
                from channel.feishu import lark_install
                if lark_install.needs_download():
                    with cls._lock:
                        cls._state["status"] = "downloading"
                lark_install.ensure(allow_install=True)
                import lark_oapi as lark
            except ImportError as e:
                with cls._lock:
                    cls._state["status"] = "error"
                    cls._state["error"] = (
                        "飞书 SDK 不可用，请联网后重试，"
                        "或手动执行 pip install -U 'lark-oapi>=1.5.5'（%s）" % e
                    )
                return

            def _on_qr(info):
                # SDK 拿到二维码 URL 后立即回调；写入 state 让前端 GET 立刻能拿到
                with cls._lock:
                    cls._state["url"] = info.get("url", "")
                    cls._state["expire_in"] = info.get("expire_in", 600)
                    cls._state["qr_image"] = cls._qr_to_data_uri(info.get("url", ""))
                    cls._state["status"] = "pending"
                logger.info(f"[FeishuRegister] QR ready, expire_in={info.get('expire_in')}s")

            def _on_status(info):
                # 过滤掉 polling 心跳（每 5 秒一次，纯噪音）；
                # 保留 slow_down / domain_switched 等真正的状态切换事件
                status = info.get("status")
                if status == "polling":
                    return
                logger.info(f"[FeishuRegister] SDK status: {info}")

            try:
                result = lark.register_app(
                    on_qr_code=_on_qr,
                    on_status_change=_on_status,
                    source="cowagent",
                    cancel_event=cancel_event,
                )
                with cls._lock:
                    cls._state["status"] = "done"
                    cls._state["app_id"] = result.get("client_id", "")
                    cls._state["app_secret"] = result.get("client_secret", "")
                logger.info(f"[FeishuRegister] App created: app_id={result.get('client_id')}")
            except Exception as e:
                err_msg = str(e)
                err_cls = e.__class__.__name__
                # 飞书 SDK 抛出的 AppExpiredError / AppAccessDeniedError / RegisterAppError
                if "Expired" in err_cls:
                    status = "expired"
                elif "Denied" in err_cls:
                    status = "denied"
                elif "abort" in err_msg.lower() or "cancel" in err_msg.lower():
                    # 被新一轮注册抢占，保持安静
                    return
                else:
                    status = "error"
                with cls._lock:
                    # 仅当当前 state 仍属于本次 worker 时才写入，避免覆盖更新的会话
                    if cls._state.get("cancel_event") is cancel_event:
                        cls._state["status"] = status
                        cls._state["error"] = err_msg
                logger.warning(f"[FeishuRegister] Register failed ({err_cls}): {err_msg}")

        threading.Thread(target=_worker, daemon=True, name="feishu-register").start()

    def GET(self):
        """启动一次新的注册会话。如果已有 pending/done 会话则覆盖。"""
        _require_auth()
        web.header('Content-Type', 'application/json; charset=utf-8')
        try:
            self._start_register_thread()
            # 等待 SDK 拿到二维码 URL（最多 10s）。SDK 内部会马上回调 _on_qr。
            import time as _t
            for _ in range(100):
                with self._lock:
                    if self._state.get("url") or self._state.get("status") in (
                        "downloading", "error", "expired", "denied"
                    ):
                        break
                _t.sleep(0.1)
            with self._lock:
                if self._state.get("status") in ("error", "expired", "denied"):
                    return json.dumps({
                        "status": "error",
                        "message": self._state.get("error", "register failed"),
                    })
                if self._state.get("status") == "downloading":
                    # The SDK bundle is still coming down; the QR only exists
                    # once it lands, so hand the frontend over to polling.
                    return json.dumps({
                        "status": "success",
                        "register_status": "downloading",
                    })
                if not self._state.get("url"):
                    return json.dumps({
                        "status": "error",
                        "message": "等待飞书二维码超时，请重试",
                    })
                return json.dumps({
                    "status": "success",
                    "qrcode_url": self._state["url"],
                    "qr_image": self._state.get("qr_image", ""),
                    "expire_in": self._state.get("expire_in", 600),
                })
        except Exception as e:
            logger.error(f"[WebChannel] FeishuRegister GET error: {e}")
            return json.dumps({"status": "error", "message": str(e)})

    def POST(self):
        """轮询注册结果。"""
        _require_auth()
        web.header('Content-Type', 'application/json; charset=utf-8')
        try:
            body = json.loads(web.data() or b"{}")
            action = body.get("action", "poll")
            if action != "poll":
                return json.dumps({"status": "error", "message": f"unknown action: {action}"})

            with self._lock:
                status = self._state.get("status", "idle")
                if status == "done":
                    payload = {
                        "status": "success",
                        "register_status": "done",
                        "app_id": self._state.get("app_id", ""),
                        "app_secret": self._state.get("app_secret", ""),
                    }
                    # 一次性返回凭据后清掉，避免敏感信息长期驻留内存
                    self._state = {}
                    return json.dumps(payload)
                if status in ("error", "expired", "denied"):
                    return json.dumps({
                        "status": "success",
                        "register_status": status,
                        "message": self._state.get("error", ""),
                    })
                if status == "downloading":
                    return json.dumps({
                        "status": "success",
                        "register_status": "downloading",
                    })
                # pending / starting：还在等用户扫码。二维码可能是在 GET 返回
                # "downloading" 之后才生成的，带上让前端补渲染。
                payload = {"status": "success", "register_status": "pending"}
                if self._state.get("url"):
                    payload["qrcode_url"] = self._state["url"]
                    payload["qr_image"] = self._state.get("qr_image", "")
                return json.dumps(payload)
        except Exception as e:
            logger.error(f"[WebChannel] FeishuRegister POST error: {e}")
            return json.dumps({"status": "error", "message": str(e)})
