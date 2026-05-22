"""
Cloud management client for connecting to the LinkAI control console.

Handles remote configuration sync, message push, and skill management
via the LinkAI socket protocol.

NOTE: By default, no cloud-related config is enabled. The application runs
entirely locally without connecting to any remote service. The cloud client
is only activated when BOTH of the following conditions are met:

  1. ``use_linkai`` is set to True in config (checked in app.py before
     importing this module).
  2. ``cloud_deployment_id`` (or env CLOUD_DEPLOYMENT_ID) is non-empty
     (checked in app.py and again in the ``start()`` function below).

If either condition is missing, this module is never loaded and the
program continues as a purely local application.
"""

from bridge.context import Context, ContextType
from bridge.reply import Reply, ReplyType
from common.log import logger
from linkai import LinkAIClient, PushMsg
from config import conf, pconf, plugin_config, available_setting, write_plugin_config, get_root
from plugins import PluginManager
import threading
import time
import json
import os


chat_client: LinkAIClient


CHANNEL_ACTIONS = {"channel_create", "channel_update", "channel_delete"}

# channelType -> config key mapping for app credentials
CREDENTIAL_MAP = {
    "feishu":            ("feishu_app_id",          "feishu_app_secret"),
    "dingtalk":          ("dingtalk_client_id",      "dingtalk_client_secret"),
    "wecom_bot":         ("wecom_bot_id",            "wecom_bot_secret"),
    "qq":                ("qq_app_id",               "qq_app_secret"),
    "wechatmp":          ("wechatmp_app_id",         "wechatmp_app_secret"),
    "wechatmp_service":  ("wechatmp_app_id",         "wechatmp_app_secret"),
    "wechatcom_app":     ("wechatcomapp_agent_id",   "wechatcomapp_secret"),
}


class CloudClient(LinkAIClient):
    def __init__(self, api_key: str, channel, host: str = "", port=None):
        super().__init__(api_key, host, port=port)
        self.channel = channel
        self.client_type = channel.channel_type
        self.channel_mgr = None
        self._skill_service = None
        self._memory_service = None
        self._knowledge_service = None
        self._chat_service = None
        self._session_service = None

    @property
    def skill_service(self):
        """Lazy-init SkillService so it is available once SkillManager exists."""
        if self._skill_service is None:
            try:
                from agent.skills.manager import SkillManager
                from agent.skills.service import SkillService
                from config import conf
                from common.utils import expand_path
                workspace_root = expand_path(conf().get("agent_workspace", "~/cow"))
                manager = SkillManager(custom_dir=os.path.join(workspace_root, "skills"))
                self._skill_service = SkillService(manager)
                logger.debug("[CloudClient] SkillService initialised")
            except Exception as e:
                logger.error(f"[CloudClient] Failed to init SkillService: {e}")
        return self._skill_service

    @property
    def memory_service(self):
        """Lazy-init MemoryService."""
        if self._memory_service is None:
            try:
                from agent.memory.service import MemoryService
                from config import conf
                from common.utils import expand_path
                workspace_root = expand_path(conf().get("agent_workspace", "~/cow"))
                self._memory_service = MemoryService(workspace_root)
                logger.debug("[CloudClient] MemoryService initialised")
            except Exception as e:
                logger.error(f"[CloudClient] Failed to init MemoryService: {e}")
        return self._memory_service

    @property
    def knowledge_service(self):
        """Lazy-init KnowledgeService."""
        if self._knowledge_service is None:
            try:
                from agent.knowledge.service import KnowledgeService
                from config import conf
                from common.utils import expand_path
                workspace_root = expand_path(conf().get("agent_workspace", "~/cow"))
                self._knowledge_service = KnowledgeService(workspace_root)
                logger.debug("[CloudClient] KnowledgeService initialised")
            except Exception as e:
                logger.error(f"[CloudClient] Failed to init KnowledgeService: {e}")
        return self._knowledge_service

    @property
    def chat_service(self):
        """Lazy-init ChatService (requires AgentBridge via Bridge singleton)."""
        if self._chat_service is None:
            try:
                from agent.chat.service import ChatService
                from bridge.bridge import Bridge
                agent_bridge = Bridge().get_agent_bridge()
                self._chat_service = ChatService(agent_bridge)
                logger.debug("[CloudClient] ChatService initialised")
            except Exception as e:
                logger.error(f"[CloudClient] Failed to init ChatService: {e}")
        return self._chat_service

    @property
    def session_service(self):
        """Lazy-init SessionService."""
        if self._session_service is None:
            try:
                from agent.chat.session_service import SessionService
                self._session_service = SessionService()
                logger.debug("[CloudClient] SessionService initialised")
            except Exception as e:
                logger.error(f"[CloudClient] Failed to init SessionService: {e}")
        return self._session_service

    # ------------------------------------------------------------------
    # message push callback
    # ------------------------------------------------------------------
    def on_message(self, push_msg: PushMsg):
        session_id = push_msg.session_id
        msg_content = push_msg.msg_content
        logger.info(f"receive msg push, session_id={session_id}, msg_content={msg_content}")
        context = Context()
        context.type = ContextType.TEXT
        context["receiver"] = session_id
        context["isgroup"] = push_msg.is_group
        self.channel.send(Reply(ReplyType.TEXT, content=msg_content), context)

    # ------------------------------------------------------------------
    # config callback
    # ------------------------------------------------------------------
    def on_config(self, config: dict):
        if not self.client_id:
            return
        logger.info(f"[CloudClient] Loading remote config: {config}")

        action = config.get("action")
        if action in CHANNEL_ACTIONS:
            self._dispatch_channel_action(action, config.get("data", {}))
            return

        if config.get("enabled") != "Y":
            return

        local_config = conf()
        need_restart_channel = False

        for key in config.keys():
            if key in available_setting and config.get(key) is not None:
                local_config[key] = config.get(key)

        # Voice settings
        reply_voice_mode = config.get("reply_voice_mode")
        if reply_voice_mode:
            if reply_voice_mode == "voice_reply_voice":
                local_config["voice_reply_voice"] = True
                local_config["always_reply_voice"] = False
            elif reply_voice_mode == "always_reply_voice":
                local_config["always_reply_voice"] = True
                local_config["voice_reply_voice"] = True
            elif reply_voice_mode == "no_reply_voice":
                local_config["always_reply_voice"] = False
                local_config["voice_reply_voice"] = False

        # Model configuration
        if config.get("model"):
            local_config["model"] = config.get("model")

        # Channel configuration (legacy single-channel path)
        if config.get("channelType"):
            if local_config.get("channel_type") != config.get("channelType"):
                local_config["channel_type"] = config.get("channelType")
                need_restart_channel = True

        # Channel-specific app credentials (legacy single-channel path)
        current_channel_type = local_config.get("channel_type", "")
        if self._set_channel_credentials(local_config, current_channel_type,
                                         config.get("app_id"), config.get("app_secret")):
            need_restart_channel = True

        if config.get("admin_password"):
            if not pconf("Godcmd"):
                write_plugin_config({"Godcmd": {"password": config.get("admin_password"), "admin_users": []}})
            else:
                pconf("Godcmd")["password"] = config.get("admin_password")
            PluginManager().instances["GODCMD"].reload()

        if config.get("group_app_map") and pconf("linkai"):
            local_group_map = {}
            for mapping in config.get("group_app_map"):
                local_group_map[mapping.get("group_name")] = mapping.get("app_code")
            pconf("linkai")["group_app_map"] = local_group_map
            PluginManager().instances["LINKAI"].reload()

        if config.get("text_to_image") and config.get("text_to_image") == "midjourney" and pconf("linkai"):
            if pconf("linkai")["midjourney"]:
                pconf("linkai")["midjourney"]["enabled"] = True
                pconf("linkai")["midjourney"]["use_image_create_prefix"] = True
        elif config.get("text_to_image") and config.get("text_to_image") in ["dall-e-2", "dall-e-3"]:
            if pconf("linkai")["midjourney"]:
                pconf("linkai")["midjourney"]["use_image_create_prefix"] = False

        self._save_config_to_file(local_config)

        if need_restart_channel:
            self._restart_channel(local_config.get("channel_type", ""))

    # ------------------------------------------------------------------
    # channel CRUD operations
    # ------------------------------------------------------------------
    def _dispatch_channel_action(self, action: str, data: dict):
        channel_type = data.get("channelType")
        if not channel_type:
            logger.warning(f"[CloudClient] Channel action '{action}' missing channelType, data={data}")
            return
        logger.info(f"[CloudClient] Channel action: {action}, channelType={channel_type}")

        if action == "channel_create":
            self._handle_channel_create(channel_type, data)
        elif action == "channel_update":
            self._handle_channel_update(channel_type, data)
        elif action == "channel_delete":
            self._handle_channel_delete(channel_type, data)

    def _handle_channel_create(self, channel_type: str, data: dict):
        local_config = conf()
        cred_changed = self._set_channel_credentials(
            local_config, channel_type, data.get("appId"), data.get("appSecret"))
        self._add_channel_type(local_config, channel_type)
        self._save_config_to_file(local_config)

        if not self.channel_mgr:
            return

        existing_ch = self.channel_mgr.get_channel(channel_type)
        skip_restart = existing_ch and not cred_changed
        if skip_restart and channel_type in ("weixin", "wx"):
            login_status = getattr(existing_ch, "login_status", "")
            if login_status != "logged_in":
                skip_restart = False
                logger.info(f"[CloudClient] Channel '{channel_type}' not logged in "
                            f"(status={login_status}), forcing restart")
        if skip_restart:
            logger.info(f"[CloudClient] Channel '{channel_type}' already running with same config, "
                        "skip restart, reporting status only")
            threading.Thread(
                target=self._report_channel_startup, args=(channel_type,), daemon=True
            ).start()
            return

        threading.Thread(
            target=self._do_add_channel, args=(channel_type,), daemon=True
        ).start()

    def _handle_channel_update(self, channel_type: str, data: dict):
        local_config = conf()
        enabled = data.get("enabled", "Y")

        cred_changed = self._set_channel_credentials(
            local_config, channel_type, data.get("appId"), data.get("appSecret"))
        if enabled == "N":
            self._remove_channel_type(local_config, channel_type)
        else:
            self._add_channel_type(local_config, channel_type)
        self._save_config_to_file(local_config)

        if not self.channel_mgr:
            return

        if enabled == "N":
            threading.Thread(
                target=self._do_remove_channel, args=(channel_type,), daemon=True
            ).start()
        else:
            existing_ch = self.channel_mgr.get_channel(channel_type)
            needs_restart = cred_changed or not existing_ch
            if not needs_restart and channel_type in ("weixin", "wx"):
                login_status = getattr(existing_ch, "login_status", "")
                if login_status != "logged_in":
                    needs_restart = True
                    logger.info(f"[CloudClient] Channel '{channel_type}' not logged in "
                                f"(status={login_status}), forcing restart")
            if existing_ch and not needs_restart:
                logger.info(f"[CloudClient] Channel '{channel_type}' already running with same config, "
                            "skip restart, reporting status only")
                threading.Thread(
                    target=self._report_channel_startup, args=(channel_type,), daemon=True
                ).start()
            else:
                threading.Thread(
                    target=self._do_restart_channel, args=(self.channel_mgr, channel_type), daemon=True
                ).start()

    def _handle_channel_delete(self, channel_type: str, data: dict):
        local_config = conf()
        self._clear_channel_credentials(local_config, channel_type)
        self._remove_channel_type(local_config, channel_type)
        self._save_config_to_file(local_config)

        if channel_type in ("weixin", "wx"):
            self._remove_weixin_credentials()

        if self.channel_mgr:
            threading.Thread(
                target=self._do_remove_channel, args=(channel_type,), daemon=True
            ).start()

    @staticmethod
    def _remove_weixin_credentials():
        """Remove the weixin token credentials file so next connect triggers QR login."""
        cred_path = os.path.expanduser(
            conf().get("weixin_credentials_path", "~/.weixin_cow_credentials.json")
        )
        try:
            if os.path.exists(cred_path):
                os.remove(cred_path)
                logger.info(f"[CloudClient] Removed weixin credentials: {cred_path}")
        except Exception as e:
            logger.warning(f"[CloudClient] Failed to remove weixin credentials: {e}")

    # ------------------------------------------------------------------
    # channel credentials helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _set_channel_credentials(local_config: dict, channel_type: str,
                                 app_id, app_secret) -> bool:
        """
        Write app_id / app_secret into the correct config keys for *channel_type*.
        Also syncs the values to environment variables (upper-cased key) so that
        skills that rely on env-based checks (e.g. has_env_var) work immediately.
        Returns True if any value actually changed.
        """
        cred = CREDENTIAL_MAP.get(channel_type)
        if not cred:
            return False
        id_key, secret_key = cred
        changed = False
        if app_id is not None and local_config.get(id_key) != app_id:
            local_config[id_key] = app_id
            os.environ[id_key.upper()] = str(app_id)
            changed = True
        if app_secret is not None and local_config.get(secret_key) != app_secret:
            local_config[secret_key] = app_secret
            os.environ[secret_key.upper()] = str(app_secret)
            changed = True
        if changed:
            logger.info(f"[CloudClient] Synced {channel_type} credentials to conf and env")
        return changed

    @staticmethod
    def _clear_channel_credentials(local_config: dict, channel_type: str):
        cred = CREDENTIAL_MAP.get(channel_type)
        if not cred:
            return
        id_key, secret_key = cred
        local_config.pop(id_key, None)
        local_config.pop(secret_key, None)
        os.environ.pop(id_key.upper(), None)
        os.environ.pop(secret_key.upper(), None)

    # ------------------------------------------------------------------
    # channel_type list helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _parse_channel_types(local_config: dict) -> list:
        raw = local_config.get("channel_type", "")
        if isinstance(raw, list):
            return [ch.strip() for ch in raw if ch.strip()]
        if isinstance(raw, str):
            return [ch.strip() for ch in raw.split(",") if ch.strip()]
        return []

    @staticmethod
    def _add_channel_type(local_config: dict, channel_type: str):
        types = CloudClient._parse_channel_types(local_config)
        if channel_type not in types:
            types.append(channel_type)
            local_config["channel_type"] = ", ".join(types)

    @staticmethod
    def _remove_channel_type(local_config: dict, channel_type: str):
        types = CloudClient._parse_channel_types(local_config)
        if channel_type in types:
            types.remove(channel_type)
            local_config["channel_type"] = ", ".join(types)

    # ------------------------------------------------------------------
    # channel manager thread helpers
    # ------------------------------------------------------------------
    def _do_add_channel(self, channel_type: str):
        try:
            self.channel_mgr.add_channel(channel_type)
            logger.info(f"[CloudClient] Channel '{channel_type}' added successfully")
        except Exception as e:
            logger.error(f"[CloudClient] Failed to add channel '{channel_type}': {e}", exc_info=True)
            self.send_channel_status(channel_type, "error", str(e))
            return
        self._report_channel_startup(channel_type)

    def _do_remove_channel(self, channel_type: str):
        try:
            self.channel_mgr.remove_channel(channel_type)
            logger.info(f"[CloudClient] Channel '{channel_type}' removed successfully")
        except Exception as e:
            logger.error(f"[CloudClient] Failed to remove channel '{channel_type}': {e}")

    def send_channel_qrcode(self, channel_type: str, qrcode_url: str):
        """Report QR code URL for a channel that requires scan-to-login."""
        if self.client_id:
            from linkai.api.client.client import ClientMsgType
            msg = self._build_package(ClientMsgType.CHANNEL_STATUS)
            msg["data"]["channelType"] = channel_type
            msg["data"]["status"] = "qrcode"
            msg["data"]["qrcodeUrl"] = qrcode_url
            self._send_package(msg)
            logger.info(f"[CloudClient] Sent QR code status for '{channel_type}'")

    def _report_channel_startup(self, channel_type: str):
        """Wait for channel startup result and report to cloud."""
        ch = self.channel_mgr.get_channel(channel_type)
        if not ch:
            self.send_channel_status(channel_type, "error", "channel instance not found")
            return

        if channel_type in ("weixin", "wx") and hasattr(ch, "login_status"):
            login_status = getattr(ch, "login_status", "")
            if login_status in ("waiting_scan", "scanned", "idle"):
                logger.info(f"[CloudClient] Channel '{channel_type}' is waiting for QR login, "
                            "skip reporting connected")
                return

        success, error = ch.wait_startup(timeout=3)
        if success:
            logger.info(f"[CloudClient] Channel '{channel_type}' connected, reporting status")
            self.send_channel_status(channel_type, "connected")
        else:
            logger.warning(f"[CloudClient] Channel '{channel_type}' startup failed: {error}")
            self.send_channel_status(channel_type, "error", error)

    # ------------------------------------------------------------------
    # skill callback
    # ------------------------------------------------------------------
    def on_skill(self, data: dict) -> dict:
        """
        Handle SKILL messages from the cloud console.
        Delegates to SkillService.dispatch for the actual operations.

        :param data: message data with 'action', 'clientId', 'payload'
        :return: response dict
        """
        action = data.get("action", "")
        payload = data.get("payload")
        logger.info(f"[CloudClient] on_skill: action={action}")

        svc = self.skill_service
        if svc is None:
            return {"action": action, "code": 500, "message": "SkillService not available", "payload": None}

        return svc.dispatch(action, payload)

    # ------------------------------------------------------------------
    # memory callback
    # ------------------------------------------------------------------
    def on_memory(self, data: dict) -> dict:
        """
        Handle MEMORY messages from the cloud console.
        Delegates to MemoryService.dispatch for the actual operations.

        :param data: message data with 'action', 'clientId', 'payload'
        :return: response dict
        """
        action = data.get("action", "")
        payload = data.get("payload")
        logger.info(f"[CloudClient] on_memory: action={action}")

        svc = self.memory_service
        if svc is None:
            return {"action": action, "code": 500, "message": "MemoryService not available", "payload": None}

        return svc.dispatch(action, payload)

    # ------------------------------------------------------------------
    # knowledge callback
    # ------------------------------------------------------------------
    def on_knowledge(self, data: dict) -> dict:
        """
        Handle KNOWLEDGE messages from the cloud console.
        Delegates to KnowledgeService.dispatch for the actual operations.

        :param data: message data with 'action', 'clientId', 'payload'
        :return: response dict
        """
        action = data.get("action", "")
        payload = data.get("payload")
        logger.info(f"[CloudClient] on_knowledge: action={action}")

        svc = self.knowledge_service
        if svc is None:
            return {"action": action, "code": 500, "message": "KnowledgeService not available", "payload": None}

        return svc.dispatch(action, payload)

    # ------------------------------------------------------------------
    # chat callback
    # ------------------------------------------------------------------
    def on_chat(self, data: dict, send_chunk_fn):
        """
        Handle CHAT messages from the cloud console.
        Runs the agent in streaming mode and sends chunks back via send_chunk_fn.

        :param data: message data with 'action' and 'payload' (query, session_id)
        :param send_chunk_fn: callable(chunk_data: dict) to send one streaming chunk
        """
        payload = data.get("payload", {})
        query = payload.get("query", "")
        session_id = payload.get("session_id", "cloud_console")
        channel_type = payload.get("channel_type", "")
        if not session_id.startswith("session_"):
            session_id = f"session_{session_id}"
        logger.info(f"[CloudClient] on_chat: session={session_id}, channel={channel_type}, query={query[:80]}")

        # Intercept cow/slash commands before the agent runs
        try:
            from plugins import PluginManager
            mgr = PluginManager()
            instance = mgr.instances.get("COW_CLI")
            if instance and hasattr(instance, "execute"):
                result = instance.execute(query, session_id=session_id)
                if result is not None:
                    send_chunk_fn({"chunk_type": "content", "delta": result, "segment_id": 0})
                    return
        except Exception as e:
            logger.warning(f"[CloudClient] cow_cli intercept failed: {e}")

        svc = self.chat_service
        if svc is None:
            raise RuntimeError("ChatService not available")

        svc.run(query=query, session_id=session_id, channel_type=channel_type, send_chunk_fn=send_chunk_fn)

    # ------------------------------------------------------------------
    # history callback
    # ------------------------------------------------------------------
    # Session-related actions handled via the HISTORY channel
    _SESSION_ACTIONS = {
        "list_sessions", "delete_session", "rename_session",
        "clear_context", "generate_title",
    }

    def on_history(self, data: dict) -> dict:
        """
        Handle HISTORY messages from the cloud console.

        Supports both history query and session management actions
        through a unified HISTORY message channel:
          - query: paginated conversation history
          - list_sessions / delete_session / rename_session /
            clear_context / generate_title: session lifecycle

        :param data: message data with 'action' and 'payload'
        :return: response dict
        """
        action = data.get("action", "query")
        payload = data.get("payload", {})
        logger.info(f"[CloudClient] on_history: action={action}")

        if action == "query":
            return self._query_history(payload)

        if action in self._SESSION_ACTIONS:
            return self._dispatch_session(action, payload)

        return {"action": action, "code": 404, "message": f"unknown action: {action}", "payload": None}

    def _dispatch_session(self, action: str, payload: dict) -> dict:
        """Delegate session actions to SessionService."""
        svc = self.session_service
        if svc is None:
            return {"action": action, "code": 500,
                    "message": "SessionService not available", "payload": None}
        return svc.dispatch(action, payload)

    def _query_history(self, payload: dict) -> dict:
        """Query paginated conversation history using ConversationStore."""
        session_id = payload.get("session_id", "")
        page = int(payload.get("page", 1))
        page_size = int(payload.get("page_size", 20))

        if not session_id:
            return {
                "action": "query",
                "payload": {"status": "error", "message": "session_id required"},
            }

        # Web channel stores sessions with a "session_" prefix
        if not session_id.startswith("session_"):
            session_id = f"session_{session_id}"
        logger.info(f"[CloudClient] history query: session={session_id}, page={page}, page_size={page_size}")

        try:
            from agent.memory.conversation_store import get_conversation_store
            store = get_conversation_store()
            result = store.load_history_page(
                session_id=session_id,
                page=page,
                page_size=page_size,
            )
            return {
                "action": "query",
                "payload": {"status": "success", **result},
            }
        except Exception as e:
            logger.error(f"[CloudClient] History query error: {e}")
            return {
                "action": "query",
                "payload": {"status": "error", "message": str(e)},
            }

    # ------------------------------------------------------------------
    # channel restart helpers
    # ------------------------------------------------------------------
    def _restart_channel(self, new_channel_type: str):
        """
        Restart the channel via ChannelManager when channel type changes.
        """
        if self.channel_mgr:
            logger.info(f"[CloudClient] Restarting channel to '{new_channel_type}'...")
            threading.Thread(target=self._do_restart_channel, args=(self.channel_mgr, new_channel_type), daemon=True).start()
        else:
            logger.warning("[CloudClient] ChannelManager not available, please restart the application manually")

    def _do_restart_channel(self, mgr, new_channel_type: str):
        """
        Perform the channel restart in a separate thread to avoid blocking the config callback.
        """
        try:
            mgr.restart(new_channel_type)
            if mgr.channel:
                self.channel = mgr.channel
                self.client_type = mgr.channel.channel_type
                logger.info(f"[CloudClient] Channel reference updated to '{new_channel_type}'")
        except Exception as e:
            logger.error(f"[CloudClient] Channel restart failed: {e}")
            self.send_channel_status(new_channel_type, "error", str(e))
            return
        self._report_channel_startup(new_channel_type)

    # ------------------------------------------------------------------
    # config persistence
    # ------------------------------------------------------------------
    def _save_config_to_file(self, local_config: dict):
        """
        Save configuration to config.json file.
        """
        try:
            config_path = os.path.join(get_root(), "config.json")
            if not os.path.exists(config_path):
                logger.warning(f"[CloudClient] config.json not found at {config_path}, skip saving")
                return

            with open(config_path, "r", encoding="utf-8") as f:
                file_config = json.load(f)

            file_config.update(dict(local_config))

            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(file_config, f, indent=4, ensure_ascii=False)

            logger.info("[CloudClient] Configuration saved to config.json successfully")
        except Exception as e:
            logger.error(f"[CloudClient] Failed to save configuration to config.json: {e}")


def get_root_domain(host: str = "") -> str:
    """Extract root domain from a hostname.

    If *host* is empty, reads CLOUD_HOST env var / cloud_host config.
    """
    if not host:
        host = os.environ.get("CLOUD_HOST") or conf().get("cloud_host", "")
    if not host:
        return ""
    host = host.strip().rstrip("/")
    if "://" in host:
        host = host.split("://", 1)[1]
    host = host.split("/", 1)[0].split(":")[0]
    parts = host.split(".")
    if len(parts) >= 2:
        return ".".join(parts[-2:])
    return host


def get_deployment_id() -> str:
    """Return cloud deployment id from env var or config."""
    return os.environ.get("CLOUD_DEPLOYMENT_ID") or conf().get("cloud_deployment_id", "")


def get_website_base_url() -> str:
    """Return the URL prefix that maps to the workspace websites/ dir.

    Do nothing when in local env.
    """
    deployment_id = get_deployment_id()
    if not deployment_id:
        return ""

    websites_domain = os.environ.get("CLOUD_WEBSITES_DOMAIN") or conf().get("cloud_websites_domain", "")
    if websites_domain:
        websites_domain = websites_domain.strip().rstrip("/")
        return f"https://{websites_domain}/{deployment_id}"

    domain = get_root_domain()
    if not domain:
        return ""
    return f"https://app.{domain}/{deployment_id}"


# Subdir under websites/ used by the send tool
COW_SEND_WEB_SUBDIR = "cow-send"


def copy_send_file(src_path: str, workspace_root: str) -> str:
    """Copy *src_path* into ``websites/cow-send/`` and return its URL.

    Returns empty string in local env.
    """
    import shutil
    import uuid

    from common.utils import expand_path

    base = get_website_base_url()
    if not base or not src_path or not os.path.isfile(src_path):
        return ""
    ws = os.path.abspath(expand_path(workspace_root))
    send_dir = os.path.join(ws, "websites", COW_SEND_WEB_SUBDIR)
    try:
        os.makedirs(send_dir, exist_ok=True)
    except OSError:
        return ""
    ext = os.path.splitext(src_path)[1].lower()
    if len(ext) > 12 or not ext.replace(".", "").isalnum():
        ext = ""
    dest_name = f"{uuid.uuid4().hex}{ext}"
    dest_path = os.path.join(send_dir, dest_name)
    try:
        shutil.copy2(src_path, dest_path)
    except OSError as e:
        logger.warning(f"[cloud] copy_send_file: copy failed: {e}")
        return ""
    return f"{base}/{COW_SEND_WEB_SUBDIR}/{dest_name}"


def build_website_prompt(workspace_dir: str) -> list:
    """Build system prompt lines for cloud website/file sharing rules.

    Returns an empty list when cloud deployment is not configured,
    so callers can safely do ``lines.extend(build_website_prompt(...))``.
    """
    base_url = get_website_base_url()
    if not base_url:
        return []

    return [
        "**文件分享与网页生成规则** (非常重要 — 当前为云部署模式):",
        "",
        f"云端已为工作空间的 `websites/` 目录配置好公网路由映射，访问地址前缀为: `{base_url}`",
        "",
        "1. **网页/网站**: 编写网页、H5页面等前端代码时，**必须**将文件放到 `websites/` 目录中",
        f"   - 例如: `websites/index.html` → `{base_url}/index.html`",
        f"   - 例如: `websites/my-app/index.html` → `{base_url}/my-app/index.html`",
        "",
        "2. **生成文件分享** (PPT、PDF、图片、音视频等): 当你为用户生成了需要下载或查看的文件时，**可以**将文件保存到 `websites/` 目录中",
        f"  - 例如: 生成的PPT保存到 `websites/files/report.pptx` → 下载链接为 `{base_url}/files/report.pptx`",
        "   - 你仍然可以同时使用 `send` 工具发送文件（在微信、飞书、钉钉、web等渠道中有效），但**必须同时在回复文本中提供下载链接**作为兜底，因为部分渠道无法通过 send 接收本地文件",
        "",
        "3. **必须发送链接**: 无论是网页还是文件，生成后**必须将完整的访问/下载链接直接写在回复文本中发送给用户**",
        "",
        "4. **文件名和路径尽量使用英文/拼音/数字等**，不要使用中文，避免链接无法访问",
        "",
        "5. 建议为每个独立项目在 `websites/` 下创建子目录，保持结构清晰",
        "",
    ]

def start(channel, channel_mgr=None):
    if not get_deployment_id():
        return

    global chat_client
    chat_client = CloudClient(api_key=conf().get("linkai_api_key"), host=conf().get("cloud_host", ""), port=conf().get("cloud_port"), channel=channel)
    chat_client.channel_mgr = channel_mgr
    chat_client.config = _build_config()
    chat_client.start()
    time.sleep(1.5)
    if chat_client.client_id:
        logger.info("[CloudClient] Console: https://link-ai.tech/console/clients")
        if channel_mgr:
            channel_mgr.cloud_mode = True
            threading.Thread(target=_report_existing_channels, args=(chat_client, channel_mgr), daemon=True).start()


def _report_existing_channels(client: CloudClient, mgr):
    """Report status for all channels that were started before cloud client connected."""
    try:
        for name, ch in list(mgr._channels.items()):
            if name == "web":
                continue
            ch.cloud_mode = True
            client._report_channel_startup(name)
    except Exception as e:
        logger.warning(f"[CloudClient] Failed to report existing channel status: {e}")


def _build_config():
    local_conf = conf()
    config = {
        "linkai_app_code": local_conf.get("linkai_app_code"),
        "single_chat_prefix": local_conf.get("single_chat_prefix"),
        "single_chat_reply_prefix": local_conf.get("single_chat_reply_prefix"),
        "single_chat_reply_suffix": local_conf.get("single_chat_reply_suffix"),
        "group_chat_prefix": local_conf.get("group_chat_prefix"),
        "group_chat_reply_prefix": local_conf.get("group_chat_reply_prefix"),
        "group_chat_reply_suffix": local_conf.get("group_chat_reply_suffix"),
        "group_name_white_list": local_conf.get("group_name_white_list"),
        "nick_name_black_list": local_conf.get("nick_name_black_list"),
        "speech_recognition": "Y" if local_conf.get("speech_recognition") else "N",
        "text_to_image": local_conf.get("text_to_image"),
        "image_create_prefix": local_conf.get("image_create_prefix"),
        "model": local_conf.get("model"),
        "agent_max_context_turns": local_conf.get("agent_max_context_turns"),
        "agent_max_context_tokens": local_conf.get("agent_max_context_tokens"),
        "agent_max_steps": local_conf.get("agent_max_steps"),
        "channelType": local_conf.get("channel_type"),
    }

    if local_conf.get("always_reply_voice"):
        config["reply_voice_mode"] = "always_reply_voice"
    elif local_conf.get("voice_reply_voice"):
        config["reply_voice_mode"] = "voice_reply_voice"

    if pconf("linkai"):
        config["group_app_map"] = pconf("linkai").get("group_app_map")

    if plugin_config.get("Godcmd"):
        config["admin_password"] = plugin_config.get("Godcmd").get("password")

    # Add channel-specific app credentials
    current_channel_type = local_conf.get("channel_type", "")
    if current_channel_type == "feishu":
        config["app_id"] = local_conf.get("feishu_app_id")
        config["app_secret"] = local_conf.get("feishu_app_secret")
    elif current_channel_type == "dingtalk":
        config["app_id"] = local_conf.get("dingtalk_client_id")
        config["app_secret"] = local_conf.get("dingtalk_client_secret")
    elif current_channel_type in ("wechatmp", "wechatmp_service"):
        config["app_id"] = local_conf.get("wechatmp_app_id")
        config["app_secret"] = local_conf.get("wechatmp_app_secret")
    elif current_channel_type == "wecom_bot":
        config["app_id"] = local_conf.get("wecom_bot_id")
        config["app_secret"] = local_conf.get("wecom_bot_secret")
    elif current_channel_type == "qq":
        config["app_id"] = local_conf.get("qq_app_id")
        config["app_secret"] = local_conf.get("qq_app_secret")
    elif current_channel_type == "wechatcom_app":
        config["app_id"] = local_conf.get("wechatcomapp_agent_id")
        config["app_secret"] = local_conf.get("wechatcomapp_secret")

    return config
