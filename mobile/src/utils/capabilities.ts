import type {
  CapabilityKey,
  CapabilityPick,
  ModelOption,
  ModelsState,
  ProviderEntry,
  SearchProviderMeta,
  VoiceReplyMode,
} from '../protocol/resources';

export interface Option {
  value: string;
  hint?: string;
}

export const toOption = (o: ModelOption): Option => (typeof o === 'string' ? {value: o} : o);

export const toOptions = (list?: ModelOption[]): Option[] => (list ?? []).map(toOption);

export const isCustomProviderId = (id: string) => id === 'custom' || id.startsWith('custom:');

export const providerLabel = (data: ModelsState | null, id: string): string => {
  if (!id) {
    return '';
  }
  const label = data?.providers.find(p => p.id === id)?.label;
  if (!label) {
    return id;
  }
  return typeof label === 'string' ? label : label.zh || label.en || id;
};

interface CapabilityMeta {
  title: string;
  blurb: string;
  /** Label of the empty provider choice; absent when a provider is mandatory. */
  emptyLabel?: string;
  emptyDesc?: string;
  /** A model id may be typed when the catalog lacks it. */
  freeModel?: boolean;
}

export const CAPABILITY_META: Record<CapabilityKey, CapabilityMeta> = {
  vision: {
    title: '图像理解',
    blurb: '识别图片内容，用于图像识别工具',
    emptyLabel: '自动',
    emptyDesc: '按已配置的厂商自动选择',
  },
  image: {
    title: '图像生成',
    blurb: '生成图片，用于图像生成技能',
    emptyLabel: '自动',
    emptyDesc: '按已配置的厂商自动选择',
  },
  asr: {
    title: '语音识别',
    blurb: '语音转文字',
    emptyLabel: '自动',
    emptyDesc: '跟随主模型的厂商',
    freeModel: true,
  },
  tts: {title: '语音合成', blurb: '文字转语音'},
  embedding: {
    title: '向量',
    blurb: '用于记忆与知识的向量化检索',
    emptyLabel: '不启用',
    emptyDesc: '记忆与知识不做向量检索',
  },
};

export const REPLY_MODES: {value: VoiceReplyMode; label: string}[] = [
  {value: 'off', label: '关闭'},
  {value: 'voice_if_voice', label: '仅当用户发语音时'},
  {value: 'always', label: '始终语音回复'},
];

/**
 * Vendors worth offering for a capability: configured ones, named custom
 * vendors, and whatever is selected now (so a stale choice stays visible).
 */
export function capabilityProviders(data: ModelsState, pick: CapabilityPick, selected: string): string[] {
  const byId = new Map(data.providers.map(p => [p.id, p]));
  return (pick.providers ?? []).filter(id => {
    const p = byId.get(id);
    return id === selected || !!p?.configured || (isCustomProviderId(id) && !!p?.custom_name);
  });
}

/**
 * Model list for a capability and vendor, like the console: the capability's
 * own list, then the shared custom list for `custom:<id>`, then the vendor catalog.
 */
export function resolveModels(data: ModelsState | null, pick: CapabilityPick, providerId: string): Option[] {
  if (!providerId) {
    return [];
  }
  const scoped = pick.provider_models;
  if (scoped?.[providerId]) {
    return toOptions(scoped[providerId]);
  }
  if (isCustomProviderId(providerId) && scoped?.custom) {
    return toOptions(scoped.custom);
  }
  return toOptions(data?.providers.find(p => p.id === providerId)?.models);
}

/** Voices are a flat list per vendor, or keyed by model first (LinkAI). */
export function resolveVoices(pick: CapabilityPick, providerId: string, model: string): Option[] {
  const raw = pick.provider_voices?.[providerId];
  if (!raw) {
    return [];
  }
  if (Array.isArray(raw)) {
    return toOptions(raw);
  }
  return toOptions(raw[model]);
}

/** A custom vendor without a catalog can only be given a typed model id. */
export function needsTypedModel(provider: ProviderEntry | undefined, id: string): boolean {
  return isCustomProviderId(id) && !provider?.catalog?.length;
}

export function capabilitySummary(data: ModelsState, key: CapabilityKey): string {
  const pick = data.capabilities[key];
  if (!pick) {
    return '';
  }
  if (key === 'tts' && pick.reply_mode === 'off') {
    return '关闭';
  }
  if (!pick.current_provider) {
    return CAPABILITY_META[key].emptyLabel ?? '未配置';
  }
  const vendor = providerLabel(data, pick.current_provider);
  return pick.current_model ? `${vendor} · ${pick.current_model}` : vendor;
}

export type SearchEditor = 'vendor' | 'deepseek' | 'url' | 'key';

/**
 * Zhipu, Qianfan and LinkAI search with the model vendor's key, so editing them
 * means editing the vendor. DeepSeek shares its key and base; SearXNG takes an
 * instance URL; the rest have a dedicated key.
 */
export function searchEditor(p: SearchProviderMeta): SearchEditor {
  if (p.id === 'deepseek') {
    return 'deepseek';
  }
  if (p.needs_url) {
    return 'url';
  }
  return p.needs_dedicated_key ? 'key' : 'vendor';
}

/** AnySearch and Keenable work without a key. */
export const searchAllowsAnonymous = (id: string) => id === 'anysearch' || id === 'keenable';

const SEARCH_HELP: Record<string, string> = {
  bocha: '前往博查开放平台创建 API Key',
  anysearch: '前往 anysearch.com 控制台创建 API Key，留空则用匿名模式（每日有免费额度）',
  serply: '前往 serply.io 控制台创建 API Key',
  tavily: '前往 tavily.com 控制台创建 API Key',
  outcrawl: '前往 outcrawl.ai 控制台创建 API Key',
  firecrawl: '前往 firecrawl.dev 控制台创建 API Key',
  specstream: '前往 specstream.ai 控制台创建 API Key',
  olostep: '前往 olostep.com 控制台创建 API Key',
  searchapi: '前往 searchapi.io 控制台创建 API Key',
  keenable: '留空则用匿名模式；填入密钥可提升频率上限，前往 keenable.ai 获取',
  searxng: '自托管 SearXNG 实例的地址，无需 API Key',
  deepseek: '与 DeepSeek 模型共用同一组 API Key 和 API Base，修改后模型调用也会生效',
};

export const searchHelp = (id: string) => SEARCH_HELP[id] ?? '';

/** Order fallback links by moving one up or down; out-of-range moves are no-ops. */
export function moveItem<T>(list: T[], index: number, delta: -1 | 1): T[] {
  const target = index + delta;
  if (index < 0 || index >= list.length || target < 0 || target >= list.length) {
    return list;
  }
  const next = list.slice();
  [next[index], next[target]] = [next[target], next[index]];
  return next;
}
