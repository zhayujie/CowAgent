import type {ChannelField, ChannelInfo, ChannelsResponse} from '../protocol/resources';

export type ChannelPending = 'none' | 'scanning' | 'starting';

/** One line on the picker: how the channel connects, so the choice is informed before tapping. */
export const CHANNEL_BLURB: Record<string, string> = {
  weixin: '扫码登录个人微信',
  feishu: '扫码一键创建机器人，或填写应用凭证',
  dingtalk: '填写钉钉应用的 Client ID 和 Secret',
  wecom_bot: '企业微信智能机器人',
  qq: 'QQ 开放平台机器人',
  wechatcom_app: '企业微信自建应用，需要公网回调',
  wechat_kf: '微信客服，需要公网回调',
  wechatmp: '微信公众号，需要公网回调',
  telegram: '填写 BotFather 给的 Bot Token',
  slack: 'Socket Mode，需要 Bot 和 App 两个 Token',
  discord: '填写 Developer Portal 里的 Bot Token',
};

/** Shown under the form where getting the credentials right is not obvious. */
export const CHANNEL_HELP: Record<string, string> = {
  feishu: '在飞书开放平台创建企业自建应用，开启机器人能力后，到「凭证与基础信息」复制 App ID 和 App Secret。',
  dingtalk: '在钉钉开放平台创建应用并添加机器人，消息接收方式选 Stream 模式。',
  wechatcom_app: '企业微信回调需要服务器能从公网访问到这里填的端口。',
  wechat_kf: '微信客服回调需要服务器能从公网访问到这里填的端口。',
  wechatmp: '公众号回调需要服务器能从公网访问到这里填的端口。',
  telegram: '在 Telegram 里找 @BotFather，发送 /newbot 创建机器人后会拿到 Token。',
  slack: '应用需要开启 Socket Mode。Bot Token 以 xoxb- 开头，App Token 以 xapp- 开头。',
  discord: '记得在 Bot 设置里打开 Message Content Intent，否则收不到消息内容。',
};

const MASK_RE = /\*{2,}/;

export const localized = (label: ChannelInfo['label'] | ChannelField['label'], fallback = '') =>
  typeof label === 'string' ? label : label?.zh || label?.en || fallback;

export const channelLabel = (c: ChannelInfo) => localized(c.label, c.name);

/** An instance reads by the name the user gave it, a per-type card by its type. */
export const channelTitle = (c: ChannelInfo) => c.instance_name || channelLabel(c);

export const channelKey = (c: ChannelInfo) => c.instance_id || c.name;

export const isMaskedSecret = (f: ChannelField) => f.type === 'secret' && !!f.value && MASK_RE.test(String(f.value));

/**
 * Only WeChat logs in by scan, so only it can be connected but not yet usable.
 * `idle`/`unknown` mean the channel is still coming up, not that it wants a scan.
 */
export function channelPending(c: ChannelInfo): ChannelPending {
  const s = c.login_status;
  if (c.name !== 'weixin' || !c.active || !s || s === 'logged_in') {
    return 'none';
  }
  return s === 'waiting_scan' || s === 'scanned' ? 'scanning' : 'starting';
}

export function channelStatusLabel(c: ChannelInfo): string {
  const pending = channelPending(c);
  if (pending === 'scanning') {
    return c.login_status === 'scanned' ? '已扫码，等待确认' : '等待扫码登录';
  }
  if (pending === 'starting') {
    return '正在启动';
  }
  return c.active ? '已连接' : '未连接';
}

export const isMultiInstance = (data: ChannelsResponse, type: string) =>
  !!data.multi_agent && (data.multi_instance_types ?? []).includes(type);

/**
 * In multi-Agent mode a multi-instance type shows one card per bot, so its
 * per-type card drops out of "connected" and the type stays available for
 * another bot. WeChat leads, everything else keeps the server's order.
 */
export function splitChannels(data: ChannelsResponse): {connected: ChannelInfo[]; available: ChannelInfo[]} {
  const multi = (type: string) => isMultiInstance(data, type);
  const legacy = data.channels.filter(c => c.active && !multi(c.name));
  const connected = [...legacy, ...(data.multi_agent ? data.instances ?? [] : [])].sort(
    (a, b) => Number(b.name === 'weixin') - Number(a.name === 'weixin'),
  );
  const available = data.channels.filter(c => !c.active || multi(c.name));
  return {connected, available};
}

/** A new bot starts from a blank form, never from another bot's stored credentials. */
export function blankChannel(c: ChannelInfo): ChannelInfo {
  return {
    ...c,
    active: false,
    instance_id: undefined,
    instance_name: undefined,
    agent_id: '',
    members: [],
    login_status: undefined,
    fields: (c.fields ?? []).map(f => ({...f, value: f.type === 'bool' ? f.value : ''})),
  };
}

/** What the form starts from: masked secrets stay empty and show their mask as the placeholder. */
export function initialValues(fields: ChannelField[]): Record<string, string> {
  return Object.fromEntries(
    fields.map(f => [f.key, isMaskedSecret(f) || f.value == null ? '' : String(f.value)]),
  );
}

/** Only fields with a value go out; an untouched secret keeps what the server stored. */
export function buildChannelConfig(fields: ChannelField[], values: Record<string, string>): Record<string, unknown> {
  const config: Record<string, unknown> = {};
  for (const f of fields) {
    const v = (values[f.key] ?? '').trim();
    if (!v) {
      continue;
    }
    config[f.key] = f.type === 'number' ? Number(v) : f.type === 'bool' ? v === 'true' : v;
  }
  return config;
}

/** Every credential is needed to connect; a stored secret or a default counts as filled. */
export function missingFields(fields: ChannelField[], values: Record<string, string>): ChannelField[] {
  return fields.filter(
    f => f.type !== 'bool' && !(values[f.key] ?? '').trim() && !isMaskedSecret(f) && (f.default ?? '') === '',
  );
}

export function changedFields(fields: ChannelField[], values: Record<string, string>): boolean {
  const start = initialValues(fields);
  return fields.some(f => (values[f.key] ?? '').trim() !== (start[f.key] ?? '').trim());
}

/** Who answers on a channel, in words: the owner, plus how many teammates it can hand off to. */
export function bindingSummary(
  c: ChannelInfo,
  nameOf: (id: string) => string | undefined,
): string {
  if (!c.agent_id) {
    return '跟随默认';
  }
  const owner = nameOf(c.agent_id) ?? c.agent_id;
  const n = (c.members ?? []).length;
  return n ? `${owner} 等 ${n + 1} 个` : owner;
}
