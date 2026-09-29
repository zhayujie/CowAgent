"""
channel factory
"""
from common import const
from .channel import Channel


def create_channel(channel_type, instance_id="", bound_agent_id="", credentials=None, members=None, peers=None) -> Channel:
    """
    create a channel instance

    :param channel_type: channel type code
    :param instance_id: unique id when running several instances of the same
        channel type. Empty -> legacy single-instance behavior (the channel's
        own @singleton cache is used, exactly as before).
    :param bound_agent_id: Agent this instance routes inbound messages to.
    :param credentials: per-instance credential overrides (app_id/secret/...).
        When provided, a fresh (non-singleton) instance is built so each
        instance can carry its own credentials.
    :param members: teammate Agent ids the owner may delegate to (team bot).
    :param peers: connection profiles for teammates in another process, so the
        owner can delegate to them through the transport.
    :return: channel instance
    """
    multi_instance = bool(instance_id or credentials or bound_agent_id or members or peers)
    ch = _build_channel(channel_type, multi_instance)
    ch.channel_type = _normalize_type(channel_type)
    if multi_instance:
        ch.apply_instance(
            instance_id=instance_id or ch.channel_type,
            bound_agent_id=bound_agent_id,
            credentials=credentials,
            members=members,
            peers=peers,
        )
    return ch


def _normalize_type(channel_type: str) -> str:
    if channel_type in (const.WEIXIN, "wx"):
        return const.WEIXIN
    return channel_type


def _fresh(factory):
    """Return a non-singleton instance when the class is @singleton-wrapped,
    else just call it. Lets several instances of one channel type coexist."""
    new_instance = getattr(factory, "new_instance", None)
    if new_instance is not None:
        return new_instance()
    return factory()


def _build_channel(channel_type, multi_instance) -> Channel:
    """
    create a channel instance
    :param channel_type: channel type code
    :return: channel instance
    """
    ch = Channel()
    if channel_type == "terminal":
        from channel.terminal.terminal_channel import TerminalChannel
        ch = TerminalChannel()
    elif channel_type == 'web':
        from channel.web.web_channel import WebChannel
        ch = WebChannel()
    elif channel_type == "wechatmp":
        from channel.wechatmp.wechatmp_channel import WechatMPChannel
        ch = WechatMPChannel(passive_reply=True)
    elif channel_type == "wechatmp_service":
        from channel.wechatmp.wechatmp_channel import WechatMPChannel
        ch = WechatMPChannel(passive_reply=False)
    elif channel_type == "wechatcom_app":
        from channel.wechatcom.wechatcomapp_channel import WechatComAppChannel
        ch = WechatComAppChannel()
    elif channel_type == const.WECHAT_KF:
        from channel.wechat_kf.wechat_kf_channel import WechatKfChannel
        ch = WechatKfChannel()
    elif channel_type == const.FEISHU:
        from channel.feishu.feishu_channel import FeiShuChanel
        ch = _fresh(FeiShuChanel) if multi_instance else FeiShuChanel()
    elif channel_type == const.DINGTALK:
        from channel.dingtalk.dingtalk_channel import DingTalkChanel
        ch = _fresh(DingTalkChanel) if multi_instance else DingTalkChanel()
    elif channel_type == const.WECOM_BOT:
        from channel.wecom_bot.wecom_bot_channel import WecomBotChannel
        ch = _fresh(WecomBotChannel) if multi_instance else WecomBotChannel()
    elif channel_type == const.QQ:
        from channel.qq.qq_channel import QQChannel
        ch = _fresh(QQChannel) if multi_instance else QQChannel()
    elif channel_type == const.TELEGRAM:
        from channel.telegram.telegram_channel import TelegramChannel
        ch = _fresh(TelegramChannel) if multi_instance else TelegramChannel()
    elif channel_type == const.SLACK:
        from channel.slack.slack_channel import SlackChannel
        ch = _fresh(SlackChannel) if multi_instance else SlackChannel()
    elif channel_type == const.DISCORD:
        from channel.discord.discord_channel import DiscordChannel
        ch = _fresh(DiscordChannel) if multi_instance else DiscordChannel()
    elif channel_type in (const.WEIXIN, "wx"):
        from channel.weixin.weixin_channel import WeixinChannel
        ch = _fresh(WeixinChannel) if multi_instance else WeixinChannel()
        channel_type = const.WEIXIN
    else:
        raise RuntimeError(f"unsupported channel_type: {channel_type!r}")
    ch.channel_type = channel_type
    return ch
