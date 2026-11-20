import {localizedLabel, tr, trf} from '../i18n';
import type {ChannelField, ChannelInfo, ChannelsResponse} from '../protocol/resources';

export type ChannelPending = 'none' | 'scanning' | 'starting';

/** One line on the picker: how the channel connects, so the choice is informed before tapping. */
export const CHANNEL_BLURB: Record<string, string> = {
  get weixin() { return tr('channel_blurb_weixin'); },
  get feishu() { return tr('channel_blurb_feishu'); },
  get dingtalk() { return tr('channel_blurb_dingtalk'); },
  get wecom_bot() { return tr('channel_blurb_wecom_bot'); },
  get qq() { return tr('channel_blurb_qq'); },
  get wechatcom_app() { return tr('channel_blurb_wechatcom_app'); },
  get wechat_kf() { return tr('channel_blurb_wechat_kf'); },
  get wechatmp() { return tr('channel_blurb_wechatmp'); },
  get telegram() { return tr('channel_blurb_telegram'); },
  get slack() { return tr('channel_blurb_slack'); },
  get discord() { return tr('channel_blurb_discord'); },
};

/** Shown under the form where getting the credentials right is not obvious. */
export const CHANNEL_HELP: Record<string, string> = {
  get feishu() { return tr('channel_help_feishu'); },
  get dingtalk() { return tr('channel_help_dingtalk'); },
  get wechatcom_app() { return tr('channel_help_wechatcom_app'); },
  get wechat_kf() { return tr('channel_help_wechat_kf'); },
  get wechatmp() { return tr('channel_help_wechatmp'); },
  get telegram() { return tr('channel_help_telegram'); },
  get slack() { return tr('channel_help_slack'); },
  get discord() { return tr('channel_help_discord'); },
};

const MASK_RE = /\*{2,}/;

export const localized = (label: ChannelInfo['label'] | ChannelField['label'], fallback = '') =>
  localizedLabel(label, fallback);

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
    return c.login_status === 'scanned' ? tr('channel_status_scanned') : tr('channel_status_waiting_scan');
  }
  if (pending === 'starting') {
    return tr('channel_status_starting');
  }
  return c.active ? tr('channel_status_connected') : tr('channel_status_disconnected');
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
    return tr('channel_binding_default');
  }
  const owner = nameOf(c.agent_id) ?? c.agent_id;
  const n = (c.members ?? []).length;
  return n ? trf('channel_binding_team', {owner, count: n + 1}) : owner;
}
