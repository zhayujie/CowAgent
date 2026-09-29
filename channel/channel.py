"""
Message sending channel abstract class
"""

from bridge.bridge import Bridge
from bridge.context import Context
from bridge.reply import *
from common.log import logger
from config import conf


class Channel(object):
    channel_type = ""
    NOT_SUPPORT_REPLYTYPE = [ReplyType.VOICE, ReplyType.IMAGE]

    def __init__(self):
        import threading
        self._startup_event = threading.Event()
        self._startup_error = None
        self.cloud_mode = False  # set to True by ChannelManager when running with cloud client
        # Multi-instance support. All optional and empty by default, so a
        # legacy single-instance channel behaves exactly as before:
        #   - instance_id: unique id of this channel instance (== channel_type
        #     for legacy single-instance channels).
        #   - bound_agent_id: the Agent this instance routes inbound messages
        #     to; empty means "fall back to config-based routing".
        #   - _creds: per-instance credential overrides. When empty, cfg()
        #     reads straight from the global conf(), i.e. legacy behavior.
        self.instance_id = ""
        self.bound_agent_id = ""
        self._creds = {}
        # Teammates this instance's owner (bound_agent_id) may hand work to.
        # Empty for a solo bot. Injected into each inbound message's context so
        # the shared delegate/@mention machinery treats the conversation as a
        # team, exactly like a Web team conversation.
        self.members = []
        # Connection profiles for teammates that live in another process, so the
        # owner can hand work to them through the transport. Empty when every
        # member is local, which is the only shape a stand-alone install produces.
        self.peers = []

    def cfg(self, key, default=None):
        """Read a config value, preferring this instance's credential override.

        Channels must read their credentials through this instead of ``conf()``
        directly so that several instances of the same channel type can each
        carry their own app_id / secret / token. With no override present
        (the default), this is exactly ``conf().get(key, default)``.
        """
        if self._creds and key in self._creds:
            value = self._creds.get(key)
            if value is not None:
                return value
        return conf().get(key, default)

    def apply_instance(self, instance_id="", bound_agent_id="", credentials=None, members=None, peers=None):
        """Attach multi-instance identity, credentials and team to this channel.

        Called by the factory/manager only on the new multi-instance path;
        legacy startup never calls it, leaving the instance in its default
        single-instance state.
        """
        if instance_id:
            self.instance_id = instance_id
        if bound_agent_id:
            self.bound_agent_id = bound_agent_id
        if credentials:
            self._creds = dict(credentials)
        if members is not None:
            self.members = list(members)
        if peers is not None:
            self.peers = [dict(p) for p in peers]
        return self

    def stamp_instance_context(self, context):
        """Inject this instance's routing identity onto an inbound context.

        A channel bound to a specific Agent (multi-instance path) stamps every
        inbound message with its ``bound_agent_id`` so the router sends it there
        rather than falling through to config-based channel_type routing; its
        ``instance_id`` and team ``members`` ride along for logging and team
        handling. All empty on a legacy single-instance channel, so the old
        routing stays intact. Channels that subclass ChatChannel inherit this
        via the base ``_compose_context``; channels that override
        ``_compose_context`` (feishu, telegram, ...) call it explicitly.
        """
        if context is None:
            return context
        bound = getattr(self, "bound_agent_id", "")
        if bound and "bound_agent_id" not in context:
            context["bound_agent_id"] = bound
        if "instance_id" not in context and getattr(self, "instance_id", ""):
            context["instance_id"] = self.instance_id
        members = getattr(self, "members", None)
        if members and "members" not in context:
            context["members"] = list(members)
        peers = getattr(self, "peers", None)
        if peers and "peers" not in context:
            context["peers"] = [dict(p) for p in peers]
        return context

    def startup(self):
        """
        init channel
        """
        raise NotImplementedError

    def report_startup_success(self):
        self._startup_error = None
        self._startup_event.set()

    def report_startup_error(self, error: str):
        self._startup_error = error
        self._startup_event.set()

    def wait_startup(self, timeout: float = 3) -> (bool, str):
        """
        Wait for channel startup result.
        Returns (success: bool, error_msg: str).
        """
        ready = self._startup_event.wait(timeout=timeout)
        if not ready:
            return True, ""
        if self._startup_error:
            return False, self._startup_error
        return True, ""

    def stop(self):
        """
        stop channel gracefully, called before restart
        """
        pass

    def handle_text(self, msg):
        """
        process received msg
        :param msg: message object
        """
        raise NotImplementedError

    # 统一的发送函数，每个Channel自行实现，根据reply的type字段发送不同类型的消息
    def send(self, reply: Reply, context: Context):
        """
        send message to user
        :param msg: message content
        :param receiver: receiver channel account
        :return:
        """
        raise NotImplementedError

    def build_reply_content(self, query, context: Context = None) -> Reply:
        """
        Build reply content, using agent if enabled in config
        """
        # Check if agent mode is enabled
        use_agent = conf().get("agent", True)

        if use_agent:
            try:
                logger.info("[Channel] Using agent mode")

                # Add channel_type to context if not present
                if context and "channel_type" not in context:
                    context["channel_type"] = self.channel_type

                # Read on_event callback injected by the channel (e.g. web SSE)
                on_event = context.get("on_event") if context else None

                # Use agent bridge to handle the query
                return Bridge().fetch_agent_reply(
                    query=query,
                    context=context,
                    on_event=on_event,
                    clear_history=False
                )
            except Exception as e:
                logger.error(f"[Channel] Agent mode failed, fallback to normal mode: {e}")
                # Fallback to normal mode if agent fails
                return Bridge().fetch_reply_content(query, context)
        else:
            # Normal mode
            return Bridge().fetch_reply_content(query, context)

    def build_voice_to_text(self, voice_file) -> Reply:
        return Bridge().fetch_voice_to_text(voice_file)

    def build_text_to_voice(self, text) -> Reply:
        return Bridge().fetch_text_to_voice(text)
