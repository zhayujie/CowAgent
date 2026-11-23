import {localizedLabel, tr, trf, type MessageKey} from '../i18n';
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

/**
 * Whether chat has a model to answer with: a provider and model picked, and
 * that provider's key set. A default config can name a model with no key.
 */
export function chatModelReady(state: ModelsState): boolean {
  const chat = state.capabilities?.chat;
  if (!chat?.current_provider || !chat.current_model) {
    return false;
  }
  // A server that doesn't list providers can't say; don't nag about it.
  if (!state.providers) {
    return true;
  }
  return !!state.providers.find(p => p.id === chat.current_provider)?.configured;
}

export const toOption = (o: ModelOption): Option => (typeof o === 'string' ? {value: o} : o);

export const toOptions = (list?: ModelOption[]): Option[] => (list ?? []).map(toOption);

export const isCustomProviderId = (id: string) => id === 'custom' || id.startsWith('custom:');

export const providerLabel = (data: ModelsState | null, id: string): string => {
  if (!id) {
    return '';
  }
  return localizedLabel(data?.providers.find(p => p.id === id)?.label, id);
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

/** Copy is looked up through getters so it follows the current language. */
function capabilityMeta(
  title: MessageKey,
  blurb: MessageKey,
  empty?: {label: MessageKey; desc: MessageKey},
  freeModel?: boolean,
): CapabilityMeta {
  return {
    get title() {
      return tr(title);
    },
    get blurb() {
      return tr(blurb);
    },
    get emptyLabel() {
      return empty ? tr(empty.label) : undefined;
    },
    get emptyDesc() {
      return empty ? tr(empty.desc) : undefined;
    },
    ...(freeModel ? {freeModel} : {}),
  };
}

export const CAPABILITY_META: Record<CapabilityKey, CapabilityMeta> = {
  vision: capabilityMeta('settings_cap_vision', 'settings_cap_vision_blurb', {
    label: 'settings_auto',
    desc: 'settings_cap_auto_desc',
  }),
  image: capabilityMeta('settings_cap_image', 'settings_cap_image_blurb', {
    label: 'settings_auto',
    desc: 'settings_cap_auto_desc',
  }),
  asr: capabilityMeta(
    'settings_cap_asr',
    'settings_cap_asr_blurb',
    {label: 'settings_auto', desc: 'settings_cap_asr_auto_desc'},
    true,
  ),
  tts: capabilityMeta('settings_cap_tts', 'settings_cap_tts_blurb'),
  embedding: capabilityMeta('settings_cap_embedding', 'settings_cap_embedding_blurb', {
    label: 'settings_cap_embedding_off',
    desc: 'settings_cap_embedding_off_desc',
  }),
};

export const REPLY_MODES: {value: VoiceReplyMode; label: string}[] = [
  {
    value: 'off',
    get label() {
      return tr('settings_reply_off');
    },
  },
  {
    value: 'voice_if_voice',
    get label() {
      return tr('settings_reply_if_voice');
    },
  },
  {
    value: 'always',
    get label() {
      return tr('settings_reply_always');
    },
  },
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

/** Voices are a flat list per vendor, or keyed by model first for some. */
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
    return tr('settings_reply_off');
  }
  if (!pick.current_provider) {
    return CAPABILITY_META[key].emptyLabel ?? tr('common_not_configured');
  }
  const vendor = providerLabel(data, pick.current_provider);
  return pick.current_model ? `${vendor} · ${pick.current_model}` : vendor;
}

export type SearchEditor = 'vendor' | 'deepseek' | 'url' | 'key';

/**
 * Some providers (Zhipu, Qianfan and the like) search with the model vendor's
 * key, so editing them means editing the vendor. DeepSeek shares its key and
 * base; SearXNG takes an instance URL; the rest have a dedicated key.
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

const SEARCH_HELP: Record<string, MessageKey> = {
  bocha: 'settings_search_help_bocha',
  anysearch: 'settings_search_help_anysearch',
  keenable: 'settings_search_help_keenable',
  searxng: 'settings_search_help_searxng',
  deepseek: 'settings_search_help_deepseek',
};

/** Vendors whose help just points at their console. */
const SEARCH_CONSOLES: Record<string, string> = {
  serply: 'serply.io',
  tavily: 'tavily.com',
  outcrawl: 'outcrawl.ai',
  firecrawl: 'firecrawl.dev',
  context: 'context.dev',
  specstream: 'specstream.ai',
  olostep: 'olostep.com',
  searchapi: 'searchapi.io',
};

export const searchHelp = (id: string): string => {
  const site = SEARCH_CONSOLES[id];
  if (site) {
    return trf('settings_search_help_console', {site});
  }
  const key = SEARCH_HELP[id];
  return key ? tr(key) : '';
};

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
