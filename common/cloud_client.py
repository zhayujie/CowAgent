"""
Cloud management client for connecting to a remote control console.

Handles remote configuration sync, message push, and skill management over
the console's socket protocol.

DEFAULT IS LOCAL-ONLY. Out of the box no cloud config is enabled: the
application runs entirely on this machine and uploads nothing to any remote
service. The cloud client is only activated when BOTH of these hold:

  1. ``use_linkai`` is True in config (checked in app.py before this module
     is imported).
  2. ``cloud_deployment_id`` (or env CLOUD_DEPLOYMENT_ID) is non-empty
     (checked in app.py and again in the ``start()`` function below).

If either is missing this module is never loaded and the program continues
as a purely local application.
"""

from bridge.context import Context, ContextType
from bridge.reply import Reply, ReplyType
from common.log import logger
from linkai import LinkAIClient, PushMsg
from config import conf, pconf, plugin_config, available_setting, write_plugin_config, get_root, get_weixin_credentials_path
from plugins import PluginManager
from contextlib import contextmanager
from contextvars import ContextVar
import threading
import time
import json
import os


chat_client: LinkAIClient


# ``channel_sync`` carries the control plane's complete desired instance list
# for this client and is reconciled against team.json (add / update / remove).
# Older kernels that predate it fall through on_config and ignore it.
CHANNEL_ACTIONS = {"channel_create", "channel_update", "channel_delete", "channel_sync"}


AGENT_ACTIONS = {"agent_create", "agent_update", "agent_delete"}


# Message type for hand-offs between Agents hosted by different deployments
# of the same console. Sent outbound with the invoke; the console answers over
# the CONFIG channel with the actions CloudPeerTransport reads.
PEER_MSG_TYPE = "AGENT"

# The CHAT action under which a hand-off addressed to an Agent here arrives.
PEER_INVOKE_ACTION = "agent_invoke"
PEER_EVENT_ACTION = "agent_invoke_event"
PEER_RESULT_ACTION = "agent_invoke_result"

# How much longer than the teammate's own budget to wait, so its timeout
# report normally arrives before we give up on our side.
_PEER_GRACE_SECONDS = 15.0


class _PendingHandoff:
    __slots__ = ("done", "result", "on_event")

    def __init__(self, on_event):
        self.done = threading.Event()
        self.result = None
        self.on_event = on_event

    def emit(self, event) -> None:
        if self.on_event is None or not isinstance(event, dict):
            return
        try:
            self.on_event(event)
        except Exception as exc:
            logger.debug(f"[CloudClient] hand-off event callback failed: {exc}")

    def complete(self, result) -> None:
        if self.result is None:
            self.result = result
        self.done.set()


def _make_peer_transport(send):
    """Build the console-backed PeerTransport, or None when the kernel's
    multi-agent contract is unavailable. Defined lazily so this module still
    imports on kernels without ``agent.multiagent``."""
    try:
        from agent.multiagent import InvokeResult, PeerTransport
    except Exception as e:
        logger.warning(f"[CloudClient] peer transport unavailable: {e}")
        return None

    class CloudPeerTransport(PeerTransport):
        """Hand-offs to teammates in other deployments, via the console.

        Outbound ``agent_invoke`` rides this connection with request_id,
        source_agent_id, source_name, target_agent_id, task, root_session_id,
        trace, depth, members, peers, timeout, mode, history. The console
        answers with ``agent_invoke_event`` (request_id, event) per event and
        one ``agent_invoke_result`` (request_id, status, content, error,
        agent_id, agent_name, duration).
        """

        def __init__(self, send_fn):
            super().__init__()
            self._send = send_fn
            self._pending = {}
            self._lock = threading.Lock()

        def invoke(self, request, on_event=None):
            pending = _PendingHandoff(on_event)
            with self._lock:
                self._pending[request.request_id] = pending
            body = {
                "action": PEER_INVOKE_ACTION,
                "request_id": request.request_id,
                "source_agent_id": request.source_id,
                "source_name": request.source_name,
                "target_agent_id": request.target_id,
                "task": request.task,
                "root_session_id": request.root_session_id,
                "trace": list(request.trace),
                "depth": request.depth,
                "members": list(request.members),
                "peers": [p.as_dict() for p in request.peers],
                "timeout": request.timeout_seconds,
                "mode": request.mode,
            }
            if request.history:
                body["history"] = list(request.history)
            try:
                self._send(body)
            except Exception as exc:
                self._forget(request.request_id)
                return InvokeResult.failed(f"console unreachable: {exc}", agent_id=request.target_id)
            logger.info(
                f"[CloudClient] hand-off {request.request_id} sent: "
                f"{request.source_id} -> {request.target_id}, depth={request.depth}"
            )
            if not pending.done.wait(request.timeout_seconds + _PEER_GRACE_SECONDS):
                self._forget(request.request_id)
                return InvokeResult.failed(
                    "timed out waiting for the teammate's answer", agent_id=request.target_id
                )
            self._forget(request.request_id)
            return pending.result or InvokeResult.failed("no result received", agent_id=request.target_id)

        def handle_message(self, message) -> bool:
            """Consume a console message if it answers one of our hand-offs.
            Returns False for anything else so on_config keeps dispatching."""
            if not isinstance(message, dict):
                return False
            action = message.get("action")
            if action not in (PEER_EVENT_ACTION, PEER_RESULT_ACTION):
                return False
            body = message.get("data") if isinstance(message.get("data"), dict) else message
            request_id = str(body.get("request_id") or "")
            with self._lock:
                pending = self._pending.get(request_id)
            if pending is None:
                logger.debug(f"[CloudClient] {action} for unknown hand-off {request_id or '?'}, ignored")
                return True
            if action == PEER_EVENT_ACTION:
                pending.emit(body.get("event"))
                return True
            try:
                duration = float(body.get("duration") or 0)
            except (TypeError, ValueError):
                duration = 0.0
            pending.complete(InvokeResult(
                status=str(body.get("status") or "failed"),
                content=str(body.get("content") or ""),
                error=str(body.get("error") or ""),
                agent_id=str(body.get("agent_id") or ""),
                agent_name=str(body.get("agent_name") or ""),
                duration_seconds=duration,
            ))
            return True

        def _forget(self, request_id: str) -> None:
            with self._lock:
                self._pending.pop(request_id, None)

    return CloudPeerTransport(send)


# channelType -> config key mapping for app credentials.
# secret_key may be "" for single-token channels (e.g. telegram/discord).
# For slack, appId carries bot_token and appSecret carries app_token.
CREDENTIAL_MAP = {
    "feishu":            ("feishu_app_id",          "feishu_app_secret"),
    "dingtalk":          ("dingtalk_client_id",      "dingtalk_client_secret"),
    "wecom_bot":         ("wecom_bot_id",            "wecom_bot_secret"),
    "qq":                ("qq_app_id",               "qq_app_secret"),
    "wechatmp":          ("wechatmp_app_id",         "wechatmp_app_secret"),
    "wechatmp_service":  ("wechatmp_app_id",         "wechatmp_app_secret"),
    "wechatcom_app":     ("wechatcomapp_agent_id",   "wechatcomapp_secret"),
    "telegram":          ("telegram_token",          ""),
    "slack":             ("slack_bot_token",         "slack_app_token"),
    "discord":           ("discord_token",           ""),
}


# Console user driving the request handled by the current thread. Kept in a
# ContextVar so outbound calls can read it without passing it through every
# call signature; background threads start empty.
_console_user: ContextVar = ContextVar("console_user", default=None)


def current_user_id():
    """Console user for the request being handled, or None."""
    return _console_user.get()


@contextmanager
def _acting_user(user_id):
    value = str(user_id).strip() if user_id is not None and str(user_id).strip() else None
    token = _console_user.set(value)
    try:
        yield
    finally:
        _console_user.reset(token)


class CloudClient(LinkAIClient):
    def __init__(self, api_key: str, channel, host: str = "", port=None):
        # Older base client versions do not accept a ``port`` kwarg; fall back
        # to the positional signature so both old and new versions work.
        try:
            super().__init__(api_key, host, port=port)
        except TypeError:
            super().__init__(api_key, host)
        self.channel = channel
        self.client_type = channel.channel_type
        self.channel_mgr = None
        self._skill_service = None
        self._memory_service = None
        self._knowledge_service = None
        self._chat_service = None
        self._session_service = None
        self._workspace_service = None
        # Teammates in other deployments are reached through this same
        # connection. Installed only here, so a process without this client
        # never has a peer transport at all.
        self._peer_transport = _make_peer_transport(self._send_peer_message)
        if self._peer_transport is not None:
            try:
                from agent.multiagent import set_transport
                set_transport(self._peer_transport)
            except Exception as e:
                logger.warning(f"[CloudClient] peer transport not installed: {e}")
                self._peer_transport = None

    def _send_peer_message(self, body: dict) -> None:
        """Post one hand-off message to the console, in this connection's envelope."""
        if not self.client_id:
            raise RuntimeError("not connected")
        data = {
            "apiKey": self.api_key,
            "clientType": self.client_type,
            "clientId": self.client_id,
            **body,
        }
        # Whoever started the root turn is still the one acting on the far side.
        user_id = current_user_id()
        if user_id:
            data["user_id"] = user_id
        self._send_package({"type": PEER_MSG_TYPE, "data": data})

    @property
    def skill_service(self):
        """Lazy-init SkillService so it is available once SkillManager exists."""
        if self._skill_service is None:
            try:
                from agent.skills.manager import SkillManager
                from agent.skills.service import SkillService
                from common.state_dir import skills_dir
                manager = SkillManager(custom_dir=str(skills_dir()))
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
                from common.state_dir import state_root_str
                self._memory_service = MemoryService(state_root_str())
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
                from common.state_dir import state_root_str
                self._knowledge_service = KnowledgeService(state_root_str())
                logger.debug("[CloudClient] KnowledgeService initialised")
            except Exception as e:
                logger.error(f"[CloudClient] Failed to init KnowledgeService: {e}")
        return self._knowledge_service

    @property
    def workspace_service(self):
        """Lazy-init WorkspaceService."""
        if self._workspace_service is None:
            try:
                from agent.workspace.service import WorkspaceService
                from common.state_dir import state_root_str
                self._workspace_service = WorkspaceService(state_root_str())
                logger.debug("[CloudClient] WorkspaceService initialised")
            except Exception as e:
                logger.error(f"[CloudClient] Failed to init WorkspaceService: {e}")
        return self._workspace_service

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
        # A teammate's tool steps / final answer for a hand-off we sent; not
        # config, and potentially long, so it is not echoed to the log.
        if self._peer_transport is not None and self._peer_transport.handle_message(config):
            return
        logger.info(f"[CloudClient] Loading remote config: {config}")

        action = config.get("action")
        if action in CHANNEL_ACTIONS:
            self._dispatch_channel_action(action, config.get("data", {}))
            return

        if action in AGENT_ACTIONS:
            self._dispatch_agent_action(action, config.get("data", {}))
            return

        if config.get("enabled") != "Y":
            return

        local_config = conf()
        need_restart_channel = False

        for key in config.keys():
            if key in available_setting and config.get(key) is not None:
                local_config[key] = config.get(key)

        # Self-evolution switch: normalize remote value (bool / "Y"/"N" / "true")
        # to a real bool so the evolution config parser reads it correctly.
        if config.get("self_evolution_enabled") is not None:
            local_config["self_evolution_enabled"] = self._to_bool(config.get("self_evolution_enabled"))

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
        if action == "channel_sync":
            self._handle_channel_sync(data)
            return

        channel_type = data.get("channelType")
        if not channel_type:
            logger.warning(f"[CloudClient] Channel action '{action}' missing channelType, data={data}")
            return

        # A per-connection id opts this channel into the multi-instance path:
        # its identity, binding and credentials are stored per instance in the
        # roster file rather than as one flat set in config.json, so several
        # connections of one type can coexist. Absent, everything below is the
        # original single-connection path, byte-for-byte.
        instance_id = str(data.get("channelId") or "").strip()
        if instance_id:
            logger.info(
                f"[CloudClient] Channel action: {action}, "
                f"channelType={channel_type}, id={instance_id}"
            )
            if action == "channel_create":
                self._handle_instance_create(instance_id, channel_type, data)
            elif action == "channel_update":
                self._handle_instance_update(instance_id, channel_type, data)
            elif action == "channel_delete":
                self._handle_instance_delete(instance_id, channel_type, data)
            return

        logger.info(f"[CloudClient] Channel action: {action}, channelType={channel_type}")

        if action == "channel_create":
            self._handle_channel_create(channel_type, data)
        elif action == "channel_update":
            self._handle_channel_update(channel_type, data)
        elif action == "channel_delete":
            self._handle_channel_delete(channel_type, data)

    # ------------------------------------------------------------------
    # agent operations (add/remove an agent without a restart)
    # ------------------------------------------------------------------
    def _dispatch_agent_action(self, action: str, data: dict):
        agent_id = str(data.get("id") or data.get("agentId") or "").strip()
        if not agent_id:
            logger.warning(f"[CloudClient] Agent action '{action}' missing id, data={data}")
            return
        logger.info(f"[CloudClient] Agent action: {action}, id={agent_id}")
        if action == "agent_create":
            self._handle_agent_create(agent_id, data)
        elif action == "agent_update":
            self._handle_agent_update(agent_id, data)
        elif action == "agent_delete":
            self._handle_agent_delete(agent_id)

    def _handle_agent_update(self, agent_id: str, data: dict):
        """Apply a profile / model change to a live agent."""
        fields = {}
        if data.get("name"):
            fields["name"] = str(data.get("name")).strip()
        if data.get("description") is not None:
            fields["description"] = str(data.get("description")).strip()
        if data.get("model"):
            fields["model"] = data.get("model")
        if not fields:
            return
        try:
            from agent.admin import get_agent_admin_service
            from agent.registry import get_agent_registry
            current = get_agent_registry().get_addressed(agent_id, require_enabled=False)
            if all(getattr(current, k, None) == v for k, v in fields.items()):
                return
            service = get_agent_admin_service()
            service.update_agent(current.id, **fields)
            self._reload_agents(service, changed_agent_ids=[current.id])
            logger.info(f"[CloudClient] Agent '{current.id}' updated: {list(fields)}")
        except Exception as e:
            logger.error(f"[CloudClient] Failed to update agent '{agent_id}': {e}", exc_info=True)

    def _handle_agent_delete(self, agent_id: str):
        """Remove an agent, its workspace and roster entry, then re-point the
        live runtime. The default agent is the instance itself and is refused
        by the admin service."""
        try:
            from agent.admin import get_agent_admin_service
            service = get_agent_admin_service()
            service.delete_agent(agent_id)
            self._reload_agents(service, changed_agent_ids=[agent_id])
            logger.info(f"[CloudClient] Agent '{agent_id}' deleted")
        except Exception as e:
            logger.error(f"[CloudClient] Failed to delete agent '{agent_id}': {e}", exc_info=True)

    def _handle_agent_create(self, agent_id: str, data: dict):
        """Add a new agent and re-point the live runtime, so it can answer
        without a restart. A no-op when agent support is unavailable.

        The console may send the same registration again, e.g. after a
        reconnect to make sure an agent it created while this instance was
        offline exists; an agent that already exists takes it as an update,
        and its asset modes are left as they are."""
        if self._agent_exists(agent_id):
            logger.info(f"[CloudClient] Agent '{agent_id}' already exists, applying as update")
            self._handle_agent_update(agent_id, data)
            return
        name = str(data.get("name") or agent_id).strip()
        description = str(data.get("description") or "").strip()
        model = data.get("model")
        # Asset isolation for the new agent. Values are "own" (a private copy)
        # or "shared" (draw on the shared library); unset keeps the default
        # shared behaviour so existing callers are unaffected.
        knowledge_mode = data.get("knowledge_mode") or data.get("knowledgeMode")
        skill_mode = data.get("skill_mode") or data.get("skillMode")
        try:
            from agent.admin import get_agent_admin_service
        except Exception as e:
            logger.warning(f"[CloudClient] agent create unavailable: {e}")
            return
        try:
            service = get_agent_admin_service()
            service.create_agent(
                agent_id=agent_id,
                name=name,
                description=description or None,
                knowledge_mode=knowledge_mode,
                skill_mode=skill_mode,
            )
            if model:
                try:
                    service.update_agent(agent_id, model=model)
                except Exception as e:
                    logger.warning(f"[CloudClient] set agent model failed: {e}")
            self._reload_agents(service)
            logger.info(f"[CloudClient] Agent '{agent_id}' created")
        except Exception as e:
            logger.error(f"[CloudClient] Failed to create agent '{agent_id}': {e}", exc_info=True)

    @staticmethod
    def _agent_exists(agent_id: str) -> bool:
        # Addressed lookup, so the reserved default alias names the existing
        # default agent rather than a new agent to create.
        try:
            from agent.registry import get_agent_registry
            get_agent_registry().get_addressed(agent_id, require_enabled=False)
            return True
        except Exception:
            return False

    @staticmethod
    def _reload_agents(service, changed_agent_ids=None):
        """Re-point the running runtime at the updated roster.

        ``changed_agent_ids`` are the agents whose cached runtimes are dropped:
        a runtime keeps the model it was built with, so an edited agent would
        otherwise answer on its old model until the process restarts."""
        try:
            from channel.web.api.agents import _reload_agent_runtime
            _reload_agent_runtime(service, changed_agent_ids=changed_agent_ids)
        except Exception as e:
            logger.warning(f"[CloudClient] agent runtime reload skipped: {e}")

    # ------------------------------------------------------------------
    # per-instance channel operations (multi-instance path)
    # ------------------------------------------------------------------
    @staticmethod
    def _instance_credentials_from(channel_type: str, data: dict) -> dict:
        """Map the remote appId/appSecret onto this type's credential keys."""
        cred = CREDENTIAL_MAP.get(channel_type)
        if not cred:
            return {}
        id_key, secret_key = cred
        out = {}
        if data.get("appId") is not None:
            out[id_key] = data.get("appId")
        if secret_key and data.get("appSecret") is not None:
            out[secret_key] = data.get("appSecret")
        return out

    @staticmethod
    def _instance_agent_id(data: dict):
        """The bound Agent id if the remote supplied one, else None.

        Accepts a few plausible field names so the binding is honored whichever
        the control plane uses; None means "leave the current binding as-is".
        """
        for key in ("agentId", "agent_id", "boundAgentId"):
            value = data.get(key)
            if value is not None and str(value).strip():
                return str(value).strip()
        return None

    @staticmethod
    def _instance_members(data: dict):
        """Teammates for a channel instance, or None to leave the team as-is.

        A list (even an empty one) is authoritative: ``[]`` clears the team. A
        control plane that predates teams never sends the key, so its records
        keep whatever members they had.
        """
        for key in ("members", "memberAgentIds", "member_agent_ids"):
            value = data.get(key)
            if isinstance(value, list):
                return [str(m).strip() for m in value if str(m or "").strip()]
        return None

    @staticmethod
    def _instance_peers(data: dict):
        """How to reach members that are not in this process, or None to leave
        the directory as-is.

        Same authoritative-list rule as the members above: ``[]`` clears it, an
        absent key keeps whatever the record had. Entries are
        ``{id, name, description}``; anything without an id is dropped later.
        """
        for key in ("peers", "peerAgents", "peer_agents"):
            value = data.get(key)
            if isinstance(value, list):
                return [p for p in value if isinstance(p, dict)]
        return None

    def _instance_signature(self, inst):
        """What decides whether a running instance must restart.

        The owner id is normalised so the legacy empty binding and the
        ``"default"`` alias compare equal to the real default agent: a control
        plane that starts sending an explicit owner must not bounce every bot.
        """
        from agent import team
        from agent.registry import DEFAULT_AGENT_ALIAS

        owner = (inst.agent_id or "").strip()
        if not owner or owner == DEFAULT_AGENT_ALIAS:
            try:
                owner = team.resolve(conf()).get("default_agent_id") or ""
            except Exception:
                owner = ""
        return (
            inst.channel_type,
            owner,
            tuple(sorted((inst.credentials or {}).items())),
            tuple(sorted(inst.members or [])),
            # A teammate that moved to another process, or back, changes how it is
            # reached even when the roster itself reads the same.
            tuple(sorted(str(p.get("id") or "") for p in (inst.peers or []))),
        )

    @staticmethod
    def _is_platform_instance_id(instance_id: str, channel_type: str) -> bool:
        """True for an id the control plane issued, i.e. anything not minted locally.

        Only such instances may be reconciled away by a sync; local ones (the
        bare type bootstrapped from the flat config, or ``<type>-<hex>`` from
        the local console) are never ours to delete.
        """
        from channel.channel_instances import is_local_instance_id

        if not instance_id:
            return False
        return not is_local_instance_id(instance_id, channel_type)

    def _instance_running(self, instance_id: str) -> bool:
        if not self.channel_mgr:
            return False
        try:
            return self.channel_mgr.get_channel(instance_id) is not None
        except Exception:
            return False

    def _apply_instance(self, instance_id: str, channel_type: str, data: dict) -> bool:
        """Persist one instance record and start it only when that matters.

        Returns True when the instance was (re)started. An identical record whose
        channel is already up is left alone: the control plane replays every
        channel on each login, and a bot must not drop its connection just to be
        told what it already knows. A record that changed, or one whose channel
        is not running, is started (restarting if needed).
        """
        from channel.channel_instances import get_instance, upsert_instance

        before = get_instance(conf(), instance_id)
        inst = upsert_instance(
            conf(),
            channel_type=channel_type,
            instance_id=instance_id,
            agent_id=self._instance_agent_id(data),
            credentials=self._instance_credentials_from(channel_type, data),
            members=self._instance_members(data),
            peers=self._instance_peers(data),
            name=(str(data.get("channelName") or "").strip() or None),
        )
        if not self.channel_mgr:
            return False
        unchanged = (
            before is not None
            and self._instance_signature(before) == self._instance_signature(inst)
        )
        if unchanged and self._instance_running(instance_id):
            logger.info(
                f"[CloudClient] Channel instance '{instance_id}' unchanged and running, skip restart"
            )
            return False
        threading.Thread(
            target=self._do_add_instance, args=(inst,), daemon=True
        ).start()
        return True

    def _handle_instance_create(self, instance_id: str, channel_type: str, data: dict):
        self._apply_instance(instance_id, channel_type, data)

    def _handle_instance_update(self, instance_id: str, channel_type: str, data: dict):
        from channel.channel_instances import remove_instance
        enabled = data.get("enabled", "Y")
        if enabled == "N":
            remove_instance(conf(), instance_id)
            if self.channel_mgr:
                threading.Thread(
                    target=self._do_remove_channel, args=(instance_id,), daemon=True
                ).start()
            return
        self._apply_instance(instance_id, channel_type, data)

    def _handle_channel_sync(self, data: dict):
        """Reconcile team.json against the control plane's full desired list.

        ``data["channels"]`` is every instance this client should run, each in
        the same shape as a ``channel_create`` record. Records are upserted
        (starting only what changed or is down), then any explicit instance not
        in the list is removed: a channel deleted on the platform while this
        kernel was offline must not keep answering from a stale credential. A
        payload without a list is ignored rather than treated as "remove all".
        """
        from channel.channel_instances import read_raw_instances, remove_instance

        channels = data.get("channels")
        if not isinstance(channels, list):
            logger.warning("[CloudClient] channel_sync without a channels list, ignored")
            return

        desired_ids = set()
        started = 0
        for record in channels:
            if not isinstance(record, dict):
                continue
            instance_id = str(record.get("channelId") or "").strip()
            channel_type = str(record.get("channelType") or "").strip()
            if not instance_id or not channel_type:
                logger.warning(f"[CloudClient] channel_sync record missing id/type, skipped: {record}")
                continue
            if str(record.get("enabled") or "Y") == "N":
                continue
            desired_ids.add(instance_id)
            try:
                if self._apply_instance(instance_id, channel_type, record):
                    started += 1
            except Exception as e:
                logger.error(f"[CloudClient] channel_sync failed to apply '{instance_id}': {e}", exc_info=True)

        removed = 0
        for record in read_raw_instances(conf()):
            instance_id = str(record.get("instance_id") or "").strip()
            if not instance_id or instance_id in desired_ids:
                continue
            channel_type = str(record.get("channel_type") or "").strip()
            if not self._is_platform_instance_id(instance_id, channel_type):
                # Bootstrapped legacy records (id == type) and instances the user
                # created in the local console (``<type>-<hex>``) are not ours to
                # delete; leaving a stray bot running beats killing a live one.
                logger.info(
                    f"[CloudClient] channel_sync keeps non-platform instance '{instance_id}'"
                )
                continue
            remove_instance(conf(), instance_id)
            removed += 1
            if self.channel_mgr:
                threading.Thread(
                    target=self._do_remove_channel, args=(instance_id,), daemon=True
                ).start()

        logger.info(
            f"[CloudClient] channel_sync done: desired={len(desired_ids)}, "
            f"started={started}, removed={removed}"
        )

    def _handle_instance_delete(self, instance_id: str, channel_type: str, data: dict):
        from channel.channel_instances import remove_instance
        remove_instance(conf(), instance_id)
        if self.channel_mgr:
            threading.Thread(
                target=self._do_remove_channel, args=(instance_id,), daemon=True
            ).start()

    def _do_add_instance(self, inst):
        """Start (or restart) one instance and report its status.

        The report names both the channel type (what older control planes key
        on) and the instance id, so two instances of one type stay distinct.
        """
        try:
            self.channel_mgr.add_channel(inst)
            logger.info(f"[CloudClient] Channel instance '{inst.instance_id}' added successfully")
        except Exception as e:
            logger.error(
                f"[CloudClient] Failed to add channel instance '{inst.instance_id}': {e}",
                exc_info=True,
            )
            self.send_channel_status(inst.channel_type, "error", str(e), channel_id=inst.instance_id)
            return
        ch = self.channel_mgr.get_channel(inst.instance_id)
        if not ch:
            self.send_channel_status(
                inst.channel_type, "error", "channel instance not found", channel_id=inst.instance_id
            )
            return
        if inst.channel_type in ("weixin", "wx") and hasattr(ch, "login_status"):
            # Scan-to-login: the channel itself reports "qrcode" / "connected"
            # as the login progresses; a premature "connected" here would hide
            # the QR code the user still has to scan.
            if getattr(ch, "login_status", "") in ("waiting_scan", "scanned", "idle"):
                logger.info(
                    f"[CloudClient] Channel instance '{inst.instance_id}' awaits QR login, skip status"
                )
                return
        success, error = ch.wait_startup(timeout=3)
        if success:
            logger.info(
                f"[CloudClient] Channel instance '{inst.instance_id}' connected, reporting status"
            )
            self.send_channel_status(inst.channel_type, "connected", channel_id=inst.instance_id)
        else:
            logger.warning(
                f"[CloudClient] Channel instance '{inst.instance_id}' startup failed: {error}"
            )
            self.send_channel_status(inst.channel_type, "error", error, channel_id=inst.instance_id)

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
        cred_path = get_weixin_credentials_path()
        try:
            if os.path.exists(cred_path):
                os.remove(cred_path)
                logger.info(f"[CloudClient] Removed weixin credentials: {cred_path}")
        except Exception as e:
            logger.warning(f"[CloudClient] Failed to remove weixin credentials: {e}")

    # ------------------------------------------------------------------
    # value helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _to_bool(value) -> bool:
        """Normalize a remote config value to bool (bool / "Y"/"N" / "true"/"1")."""
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value != 0
        if isinstance(value, str):
            return value.strip().lower() in ("y", "yes", "true", "1", "on")
        return False

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
        # secret_key may be empty for single-token channels (e.g. telegram/discord)
        if secret_key and app_secret is not None and local_config.get(secret_key) != app_secret:
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
        os.environ.pop(id_key.upper(), None)
        if secret_key:
            local_config.pop(secret_key, None)
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

    def send_channel_status(self, channel_type: str, status: str, error: str = None, channel_id: str = ""):
        """Report a channel's connection state to the control plane.

        Overrides the SDK method so the report can name the instance
        (``channelId``): with several instances of one type on a runtime, a
        type-level status would overwrite its siblings. A control plane that
        predates the field simply ignores it.
        """
        if not self.client_id:
            return
        from linkai.api.client.client import ClientMsgType
        msg = self._build_package(ClientMsgType.CHANNEL_STATUS)
        msg["data"]["channelType"] = channel_type
        msg["data"]["status"] = status
        if error:
            msg["data"]["error"] = str(error)
        if channel_id:
            msg["data"]["channelId"] = channel_id
        self._send_package(msg)

    def send_channel_qrcode(self, channel_type: str, qrcode_url: str, channel_id: str = ""):
        """Report QR code URL for a channel that requires scan-to-login."""
        if self.client_id:
            from linkai.api.client.client import ClientMsgType
            msg = self._build_package(ClientMsgType.CHANNEL_STATUS)
            msg["data"]["channelType"] = channel_type
            msg["data"]["status"] = "qrcode"
            msg["data"]["qrcodeUrl"] = qrcode_url
            if channel_id:
                msg["data"]["channelId"] = channel_id
            self._send_package(msg)
            logger.info(f"[CloudClient] Sent QR code status for '{channel_type}'")

    def _report_channel_startup(self, name: str):
        """Wait for a channel's startup result and report it to the cloud.

        ``name`` is the key the manager registered the channel under: the bare
        channel type for a legacy single-instance channel, but the instance id
        for a multi-instance one. The report needs the real type (plus the id
        separately), so both are read off the channel and only fall back to the
        key — otherwise an instance would report its uuid as its channel type.
        """
        ch = self.channel_mgr.get_channel(name)
        if not ch:
            self.send_channel_status(name, "error", "channel instance not found")
            return

        channel_type = getattr(ch, "channel_type", "") or name
        instance_id = getattr(ch, "instance_id", "") or ""
        channel_id = instance_id if instance_id != channel_type else ""

        if channel_type in ("weixin", "wx") and hasattr(ch, "login_status"):
            login_status = getattr(ch, "login_status", "")
            if login_status in ("waiting_scan", "scanned", "idle"):
                logger.info(f"[CloudClient] Channel '{name}' is waiting for QR login, "
                            "skip reporting connected")
                return

        success, error = ch.wait_startup(timeout=3)
        if success:
            logger.info(f"[CloudClient] Channel '{name}' connected, reporting status")
            self.send_channel_status(channel_type, "connected", channel_id=channel_id)
        else:
            logger.warning(f"[CloudClient] Channel '{name}' startup failed: {error}")
            self.send_channel_status(channel_type, "error", error, channel_id=channel_id)

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
        payload = data.get("payload") or {}
        logger.info(f"[CloudClient] on_skill: action={action}")

        agent_id = payload.get("agent_id") or payload.get("agentId")
        try:
            svc = self._skill_service_for(agent_id)
        except KeyError:
            return self._agent_not_found(action, agent_id)
        if svc is None:
            return {"action": action, "code": 500, "message": "SkillService not available", "payload": None}

        return svc.dispatch(action, payload)

    def _skill_service_for(self, agent_id):
        """A SkillService over the requested agent's skills: its own set when it
        has one, else the shared set. Falls back to the process-wide service when
        no agent is requested, so single-agent installs are unaffected."""
        workspace = self._agent_workspace(agent_id)
        if workspace is None:
            return self.skill_service
        try:
            from agent.skills.manager import SkillManager
            from agent.skills.service import SkillService
            from common.state_dir import skills_dir
            return SkillService(SkillManager(custom_dir=str(skills_dir(base=workspace))))
        except Exception as e:
            logger.error(f"[CloudClient] Failed to build SkillService for agent: {e}")
            return None

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
        payload = data.get("payload") or {}
        logger.info(f"[CloudClient] on_memory: action={action}")

        agent_id = payload.get("agent_id") or payload.get("agentId")
        try:
            svc = self._memory_service_for(agent_id)
        except KeyError:
            return self._agent_not_found(action, agent_id)
        if svc is None:
            return {"action": action, "code": 500, "message": "MemoryService not available", "payload": None}

        return svc.dispatch(action, payload)

    def _memory_service_for(self, agent_id):
        """A MemoryService bound to the requested agent's workspace. Falls back
        to the process-wide default-agent service when no agent is requested,
        so single-agent installs are unaffected."""
        workspace = self._agent_workspace(agent_id)
        if workspace is None:
            return self.memory_service
        try:
            from agent.memory.service import MemoryService
            return MemoryService(workspace)
        except Exception as e:
            logger.error(f"[CloudClient] Failed to build MemoryService for agent: {e}")
            return self.memory_service

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
        payload = data.get("payload") or {}
        logger.info(f"[CloudClient] on_knowledge: action={action}")

        agent_id = payload.get("agent_id") or payload.get("agentId")
        try:
            svc = self._knowledge_service_for(agent_id)
        except KeyError:
            return self._agent_not_found(action, agent_id)
        if svc is None:
            return {"action": action, "code": 500, "message": "KnowledgeService not available", "payload": None}

        return svc.dispatch(action, payload)

    def _knowledge_service_for(self, agent_id):
        """A KnowledgeService bound to the requested agent's workspace. Falls
        back to the process-wide default-agent service when no agent is
        requested, so single-agent installs are unaffected. An agent with its
        own knowledge/ reads that; otherwise it transparently reads the shared one."""
        workspace = self._agent_workspace(agent_id)
        if workspace is None:
            return self.knowledge_service
        try:
            from agent.knowledge.service import KnowledgeService
            return KnowledgeService(str(workspace))
        except Exception as e:
            logger.error(f"[CloudClient] Failed to build KnowledgeService for agent: {e}")
            return self.knowledge_service

    # ------------------------------------------------------------------
    # workspace callback
    # ------------------------------------------------------------------
    def on_workspace(self, data: dict) -> dict:
        """
        Handle WORKSPACE messages from the cloud console.

        Read-only browsing of the agent workspace. WorkspaceService keeps every
        path inside the workspace root and caps response sizes.

        :param data: message data with 'action', 'clientId', 'payload'
        :return: response dict
        """
        action = data.get("action", "")
        payload = data.get("payload") or {}

        logger.info(f"[CloudClient] on_workspace: action={action}, path={payload.get('path', '')}")

        agent_id = payload.get("agent_id") or payload.get("agentId")
        try:
            svc = self._workspace_service_for(agent_id)
        except KeyError:
            return self._agent_not_found(action, agent_id)
        if svc is None:
            return {"action": action, "code": 500, "message": "WorkspaceService not available", "payload": None}

        return svc.dispatch(action, payload)

    def _workspace_service_for(self, agent_id):
        """A WorkspaceService rooted at the requested agent's workspace. Falls
        back to the process-wide default-agent service when no agent is
        requested, so single-agent installs are unaffected."""
        workspace = self._agent_workspace(agent_id)
        if workspace is None:
            return self.workspace_service
        try:
            from agent.workspace.service import WorkspaceService
            return WorkspaceService(str(workspace))
        except Exception as e:
            logger.error(f"[CloudClient] Failed to build WorkspaceService for agent: {e}")
            return self.workspace_service

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
        # A hand-off from a teammate in another deployment, addressed to an
        # Agent here. It runs as a delegated turn and answers in chunks.
        if data.get("action") == PEER_INVOKE_ACTION:
            from agent.multiagent.inbound import serve_invoke

            user_id = payload.get("user_id") or data.get("user_id")
            target_id = self._resolve_optional_agent_id(payload.get("target_agent_id"))
            with _acting_user(user_id), self._chat_identity(target_id, user_id, None):
                serve_invoke(payload, self._agent_bridge(), send_chunk_fn)
            return

        query = payload.get("query", "")
        session_id = payload.get("session_id", "cloud_console")
        channel_type = payload.get("channel_type", "")
        # Console user on whose behalf this runs; usage is attributed to them
        # instead of the account this deployment is registered under.
        user_id = payload.get("user_id") or data.get("user_id")
        # Which agent should answer. Absent means the default agent, so
        # single-agent installs keep working unchanged.
        agent_id = payload.get("agent_id") or payload.get("agentId")
        agent_id = self._resolve_chat_agent_id(agent_id)
        # Teammates hosted elsewhere come with profiles so they can be named on
        # the roster; their ids are kept as sent since only the console resolves them.
        peers = payload.get("peers")
        if isinstance(peers, list) and self._peer_transport is not None:
            self._peer_transport.register_peers(peers)
        # Shared conversation: the roster on it and the teammate addressed for
        # this turn. Both optional; absent keeps the single-agent behaviour.
        speaker_agent_id = self._resolve_member_id(
            payload.get("speaker_agent_id") or payload.get("speakerAgentId")
        )
        members = payload.get("members")
        if isinstance(members, list):
            members = [m for m in (self._resolve_member_id(x) for x in members) if m]
        else:
            members = None
        if not session_id.startswith("session_"):
            session_id = f"session_{session_id}"
        logger.info(f"[CloudClient] on_chat: session={session_id}, channel={channel_type}, "
                    f"user_id={user_id}, agent_id={agent_id}, speaker={speaker_agent_id}, "
                    f"members={members}, query={query[:80]}")

        # Cancel / steer fast-path. These are NOT new agent turns — they act on
        # the run already in flight for this session. The web channel intercepts
        # them in its HTTP handler; the cloud/socket path (this method) is what a
        # platform like linkai-admin drives, so it must honour them here too.
        # Both reach the same in-process registries the running turn is polling.
        stripped = (query or "").strip()
        steer_flag = bool(payload.get("steer"))
        if stripped == "/cancel":
            handled = self._handle_cancel(session_id, send_chunk_fn, agent_id)
            if handled:
                return
        elif steer_flag or stripped.startswith("/steer"):
            instruction = (
                stripped[len("/steer"):].strip()
                if stripped.startswith("/steer")
                else stripped
            )
            self._handle_steer(session_id, instruction, send_chunk_fn, agent_id)
            return

        with _acting_user(user_id), self._chat_identity(agent_id, user_id, session_id):
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

            svc.run(query=query, session_id=session_id, channel_type=channel_type,
                    send_chunk_fn=self._aliasing_sender(send_chunk_fn), agent_id=agent_id,
                    speaker_agent_id=speaker_agent_id, members=members)

    #: Chunks that name a speaker, so the caller can attribute what follows.
    _SPEAKER_CHUNKS = ("speaker", "peer_start", "peer_end")

    def _aliasing_sender(self, send_chunk_fn):
        """Report the default agent to remote callers by its reserved alias,
        matching how they address it (see AgentRegistry.get_addressed)."""
        def send(chunk):
            if isinstance(chunk, dict) and chunk.get("chunk_type") in self._SPEAKER_CHUNKS:
                chunk = {**chunk, "agent_id": self._alias_agent_id(chunk.get("agent_id"))}
            send_chunk_fn(chunk)
        return send

    @staticmethod
    def _alias_agent_id(agent_id):
        """The default agent's id as seen from outside: the reserved alias."""
        try:
            from agent.registry import DEFAULT_AGENT_ALIAS, get_agent_registry
            if agent_id and agent_id == get_agent_registry().default_agent_id:
                return DEFAULT_AGENT_ALIAS
        except Exception:
            pass
        return agent_id

    def _resolve_optional_agent_id(self, agent_id):
        """Map an addressed id (including the reserved ``"default"`` alias) to
        the configured agent id, or None when absent or unknown. Unknown
        teammates are dropped rather than failing the turn: the owner still
        answers, which is what ``_resolve_speaker`` does for them anyway."""
        agent_id = str(agent_id).strip() if agent_id is not None else ""
        if not agent_id:
            return None
        try:
            from agent.registry import get_agent_registry
            return get_agent_registry().get_addressed(agent_id, require_enabled=False).id
        except Exception:
            logger.warning(f"[CloudClient] unknown agent id ignored: {agent_id}")
            return None

    def _resolve_member_id(self, agent_id):
        """A roster member: a local agent (resolved like any addressed id) or
        a teammate the peer transport knows, kept under the id it was sent as.
        Anything else is dropped, as before."""
        raw = str(agent_id).strip() if agent_id is not None else ""
        if not raw:
            return None
        try:
            from agent.registry import get_agent_registry
            return get_agent_registry().get_addressed(raw, require_enabled=False).id
        except Exception:
            pass
        if self._peer_transport is not None and self._peer_transport.get_peer(raw) is not None:
            return raw
        logger.warning(f"[CloudClient] unknown agent id ignored: {raw}")
        return None

    def _resolve_chat_agent_id(self, agent_id):
        """Validate a requested agent id, or fall back to the default agent
        when none is requested.

        Returns None when no bridge is available yet so callers keep their
        existing default-agent behaviour. A requested agent that is unknown or
        disabled is an error: answering as the default agent instead would
        silently mix up two agents' sessions and memory.
        """
        agent_id = str(agent_id).strip() if agent_id is not None else ""
        bridge = self._agent_bridge()
        if bridge is None:
            return agent_id or None
        try:
            return bridge.agent_router.resolve(explicit_agent_id=agent_id or None)
        except Exception as e:
            if agent_id:
                raise RuntimeError(f"agent unavailable: {agent_id}") from e
            logger.warning(f"[CloudClient] agent route fallback to default: {e}")
            return None

    def _agent_workspace(self, agent_id):
        """Resolve a requested agent id to its workspace root, or None to keep
        the default-agent behaviour when no agent is requested. An agent that is
        requested but unknown raises KeyError rather than silently serving the
        default agent's data (see AgentRegistry.get_addressed for the ids that
        are tolerated)."""
        agent_id = str(agent_id).strip() if agent_id is not None else ""
        if not agent_id:
            return None
        try:
            from agent.registry import get_agent_registry
            registry = get_agent_registry()
        except Exception as e:
            logger.warning(f"[CloudClient] agent registry unavailable, using default: {e}")
            return None
        return registry.get_addressed(agent_id, require_enabled=False).workspace

    @staticmethod
    def _agent_not_found(action, agent_id):
        return {"action": action, "code": 404, "message": f"agent not found: {agent_id}", "payload": None}

    @contextmanager
    def _chat_identity(self, agent_id, user_id, session_id):
        """Bind the ambient identity so downstream code resolves the right
        agent workspace/memory. A no-op when identity support is absent."""
        try:
            from common.runtime_identity import identity_scope
        except Exception:
            yield
            return
        with identity_scope(agent_id=agent_id, user_id=(str(user_id) if user_id else None),
                            session_id=session_id):
            yield

    def _agent_bridge(self):
        try:
            from bridge.bridge import Bridge
            return Bridge().get_agent_bridge()
        except Exception as e:
            logger.warning(f"[CloudClient] agent_bridge unavailable: {e}")
            return None

    def _handle_cancel(self, session_id: str, send_chunk_fn, agent_id: str = None) -> bool:
        """Abort the in-flight run for this session. Returns True if it was our
        command to handle (always True once matched), regardless of whether a
        run was actually running."""
        bridge = self._agent_bridge()
        cancelled = 0
        if bridge is not None:
            try:
                from agent.protocol import get_cancel_registry
                key = bridge.scoped_session_key(session_id, agent_id)
                cancelled = get_cancel_registry().cancel_session(key)
            except Exception as e:
                logger.warning(f"[CloudClient] cancel failed: {e}")
        logger.info(f"[CloudClient] /cancel: session={session_id}, cancelled={cancelled}")
        msg = "已中止当前执行。" if cancelled > 0 else "当前没有正在执行的任务。"
        send_chunk_fn({"chunk_type": "content", "delta": msg, "segment_id": 0})
        return True

    def _handle_steer(self, session_id: str, instruction: str, send_chunk_fn,
                      agent_id: str = None) -> None:
        """Inject a mid-run instruction into this session's active run."""
        if not instruction:
            send_chunk_fn({"chunk_type": "content",
                           "delta": "用法：/steer <要补充的指令>", "segment_id": 0})
            return
        bridge = self._agent_bridge()
        status_val = None
        if bridge is not None:
            try:
                result = bridge.steer_session(session_id, instruction, agent_id)
                status_val = getattr(getattr(result, "status", None), "value", None) or str(result)
            except Exception as e:
                logger.warning(f"[CloudClient] steer failed: {e}")
        logger.info(f"[CloudClient] /steer: session={session_id}, status={status_val}")
        msg = ("已把补充要求插入当前执行，员工会在下一步纳入。"
               if status_val in ("accepted", "ACCEPTED", "queued")
               else "当前没有正在执行的任务可插话，请直接发送新的要求。")
        send_chunk_fn({"chunk_type": "content", "delta": msg, "segment_id": 0})

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
            # Some actions (e.g. generate_title) call the model, so attribute
            # them to the console user just like a chat request.
            with _acting_user(payload.get("user_id")):
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
            # Scope the lookup to the requested agent's workspace so each agent
            # only sees its own history; None keeps the default-agent behaviour.
            workspace = self._agent_workspace(payload.get("agent_id") or payload.get("agentId"))
            store = get_conversation_store(workspace)
            result = store.load_history_page(
                session_id=session_id,
                page=page,
                page_size=page_size,
            )
            for turn in result.get("messages") or []:
                extras = turn.get("extras") if isinstance(turn, dict) else None
                if isinstance(extras, dict) and extras.get("agent_id"):
                    turn["agent_id"] = self._alias_agent_id(extras["agent_id"])
            return {
                "action": "query",
                "payload": {"status": "success", **result},
            }
        except KeyError as e:
            return {
                "action": "query",
                "payload": {"status": "error", "message": f"agent not found: {e.args[0] if e.args else ''}"},
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

            # utf-8-sig tolerates a UTF-8 BOM (e.g. edited with Windows Notepad).
            with open(config_path, "r", encoding="utf-8-sig") as f:
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


def _deployment_base_url() -> str:
    """Return the URL prefix the deployment's websites/ dir is served at."""
    deployment_id = get_deployment_id()
    if not deployment_id:
        return ""

    websites_domain = os.environ.get("CLOUD_WEBSITES_DOMAIN") or conf().get("cloud_websites_domain", "")
    if websites_domain:
        websites_domain = websites_domain.strip().rstrip("/")
        if websites_domain.startswith(("http://", "https://")):
            return f"{websites_domain}/{deployment_id}"
        return f"https://{websites_domain}/{deployment_id}"

    domain = get_root_domain()
    if not domain:
        return ""
    return f"https://app.{domain}/{deployment_id}"


def _publish_profile(workspace_dir: str = ""):
    """The Agent whose published files are in play, as (registry, profile).

    Resolved from *workspace_dir* when it names a configured Agent, so callers
    that hold a workspace path do not need an identity. A path that is not one
    (a project directory, say) falls back to the Agent this work belongs to.
    """
    from agent.registry import get_agent_registry
    from common.runtime_identity import current_identity
    from common.utils import expand_path

    registry = get_agent_registry()
    if workspace_dir:
        target = os.path.realpath(expand_path(workspace_dir))
        for profile in registry.list():
            if os.path.realpath(expand_path(profile.workspace)) == target:
                return registry, profile
    return registry, registry.get_or_default(current_identity().agent_id)


def get_publish_dir(workspace_dir: str = "", ensure: bool = False) -> str:
    """Return the directory whose contents the public route serves."""
    from common import state_dir

    try:
        _, profile = _publish_profile(workspace_dir)
        return str(state_dir.websites_dir(base=profile.workspace, ensure=ensure))
    except Exception:
        return str(state_dir.websites_dir(base=workspace_dir or None, ensure=ensure))


def get_website_base_url(workspace_dir: str = "") -> str:
    """Return the URL prefix that maps to an Agent's websites/ dir.

    Do nothing when in local env.

    The route serves the default Agent's directory at the root, so every other
    Agent is addressed by where its own directory sits relative to the instance
    root. Deriving that from the resolved paths keeps the layout defined in one
    place (state_dir) rather than spelled out again here.
    """
    base = _deployment_base_url()
    if not base:
        return ""
    try:
        from common import state_dir

        registry, profile = _publish_profile(workspace_dir)
        if profile.id == registry.default_agent_id:
            return base
        relative = os.path.relpath(
            str(state_dir.websites_dir(base=profile.workspace)),
            str(state_dir.shared_root()),
        ).replace(os.sep, "/")
        if relative.startswith(".."):
            # A workspace placed outside the instance root is not under the
            # route, and answering with the default Agent's prefix would hand
            # out a link to someone else's files.
            return ""
        return f"{base}/{relative}"
    except Exception:
        return base


# Subdir under websites/ used by the send tool
COW_SEND_WEB_SUBDIR = "cow-send"


def copy_send_file(src_path: str, workspace_root: str) -> str:
    """Copy *src_path* into ``websites/cow-send/`` and return its URL.

    Returns empty string in local env.
    """
    import shutil
    import uuid

    base = get_website_base_url(workspace_root)
    if not base or not src_path or not os.path.isfile(src_path):
        return ""
    send_dir = os.path.join(get_publish_dir(workspace_root), COW_SEND_WEB_SUBDIR)
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


def _display_path(path: str) -> str:
    """Spell an absolute path the short way the Agent is used to seeing."""
    home = os.path.expanduser("~")
    if path == home or path.startswith(home + os.sep):
        path = "~" + path[len(home):]
    return path.replace(os.sep, "/")


def build_website_prompt(workspace_dir: str) -> list:
    """Build system prompt lines for cloud website/file sharing rules.

    Returns an empty list when cloud deployment is not configured,
    so callers can safely do ``lines.extend(build_website_prompt(...))``.

    The directory is named absolutely rather than as a bare ``websites/``: each
    Agent has its own, and a relative path would also resolve into the project
    directory in a project-mode session, where nothing is served.
    """
    base_url = get_website_base_url(workspace_dir)
    if not base_url:
        return []
    pub = _display_path(get_publish_dir(workspace_dir))

    return [
        "**文件分享与网页生成规则** (非常重要 — 当前为云部署模式):",
        "",
        f"云端已为工作空间的 `{pub}/` 目录配置好公网路由映射，访问地址前缀为: `{base_url}`",
        "",
        f"1. **网页/网站**: 编写网页、H5页面等前端代码时，**必须**将文件放到 `{pub}/` 目录中",
        f"   - 例如: `{pub}/index.html` → `{base_url}/index.html`",
        f"   - 例如: `{pub}/my-app/index.html` → `{base_url}/my-app/index.html`",
        "",
        f"2. **生成文件分享** (PPT、PDF、图片、音视频等): 当你为用户生成了需要下载或查看的文件时，**可以**将文件保存到 `{pub}/` 目录中",
        f"  - 例如: 生成的PPT保存到 `{pub}/files/report.pptx` → 下载链接为 `{base_url}/files/report.pptx`",
        "   - 你仍然可以同时使用 `send` 工具发送文件（在微信、飞书、钉钉、web等渠道中有效），但**必须同时在回复文本中提供下载链接**作为兜底，因为部分渠道无法通过 send 接收本地文件",
        "",
        "3. **必须发送链接**: 无论是网页还是文件，生成后**必须将完整的访问/下载链接直接写在回复文本中发送给用户**",
        "",
        "4. **文件名和路径尽量使用英文/拼音/数字等**，不要使用中文，避免链接无法访问",
        "",
        f"5. 建议为每个独立项目在 `{pub}/` 下创建子目录，保持结构清晰",
        "",
    ]

# Held open for the life of the process; the OS drops the lock when it exits.
_connection_lock_handle = None


def _claim_connection(deployment_id: str) -> bool:
    """Whether this process may open the console connection for *deployment_id*.

    The console keeps a single connection per client and gives it to whichever
    process logged in last. A second instance started on the same host (for
    example from a shell tool, inheriting the environment) would silently take
    over every request, so only the first process to take a per-deployment lock
    connects. Where file locking is unavailable the check is skipped rather than
    blocking the connection.
    """
    global _connection_lock_handle
    if _connection_lock_handle is not None:
        return True
    import re
    import tempfile
    safe_id = re.sub(r"[^A-Za-z0-9_.-]", "_", str(deployment_id))
    path = os.path.join(tempfile.gettempdir(), f"cow-console-{safe_id}.lock")
    try:
        handle = open(path, "a+")
    except OSError as e:
        logger.warning(f"[Console] Connection lock unavailable, continuing without it: {e}")
        return True
    try:
        if os.name == "nt":
            import msvcrt
            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                handle.close()
                logger.warning(
                    "[Console] Another process already holds the console connection "
                    "for this deployment; not connecting from this one"
                )
                return False
        else:
            import fcntl
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                handle.seek(0)
                holder = handle.read().strip()
                handle.close()
                logger.warning(
                    f"[Console] Another process{f' (pid {holder})' if holder else ''} already "
                    f"holds the console connection for this deployment; not connecting from this one"
                )
                return False
            handle.seek(0)
            handle.truncate()
            handle.write(str(os.getpid()))
            handle.flush()
    except Exception as e:
        handle.close()
        logger.warning(f"[Console] Connection lock unavailable, continuing without it: {e}")
        return True
    _connection_lock_handle = handle
    return True


def start(channel, channel_mgr=None):
    deployment_id = get_deployment_id()
    if not deployment_id:
        return
    if not _claim_connection(deployment_id):
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
        # Self-evolution switch reported so the console can reflect state
        "self_evolution_enabled": "Y" if local_conf.get("self_evolution_enabled") else "N",
        "self_evolution_idle_minutes": local_conf.get("self_evolution_idle_minutes"),
        "self_evolution_min_turns": local_conf.get("self_evolution_min_turns"),
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

    # Add channel-specific app credentials based on CREDENTIAL_MAP.
    # For multi-channel channel_type (comma-separated), the first matched type wins.
    current_channel_type = local_conf.get("channel_type", "")
    for ch_type in CloudClient._parse_channel_types({"channel_type": current_channel_type}):
        cred = CREDENTIAL_MAP.get(ch_type)
        if not cred:
            continue
        id_key, secret_key = cred
        config["app_id"] = local_conf.get(id_key)
        config["app_secret"] = local_conf.get(secret_key) if secret_key else ""
        break

    return config
