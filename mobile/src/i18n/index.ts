import {I18nManager, NativeModules, Platform} from 'react-native';
import {create} from 'zustand';
import {readJSON, writeJSON} from '../storage/kv';
import {en, zh, type MessageKey} from './messages';

export type {MessageKey};
export type Lang = 'zh' | 'en';

const DICTS: Record<Lang, Record<MessageKey, string>> = {zh, en};
const LANG_KEY = 'lang';

function systemLocale(): string {
  try {
    if (Platform.OS === 'web') {
      return navigator.language || '';
    }
    return (
      Intl.DateTimeFormat().resolvedOptions().locale ||
      NativeModules.SettingsManager?.settings?.AppleLocale ||
      I18nManager.getConstants?.().localeIdentifier ||
      ''
    );
  } catch {
    return '';
  }
}

/** First-run default, as on the desktop client: zh-* systems start in Chinese, everyone else in English. */
export function systemLang(): Lang {
  return systemLocale().toLowerCase().startsWith('zh') ? 'zh' : 'en';
}

let current: Lang = systemLang();

interface LangState {
  hydrated: boolean;
  lang: Lang;
  hydrate: () => Promise<void>;
  /** Local only; callers push `cow_lang` to the server themselves. */
  setLang: (lang: Lang) => void;
}

export const useLangStore = create<LangState>(set => ({
  hydrated: false,
  lang: current,
  hydrate: async () => {
    const saved = await readJSON<Lang | null>(LANG_KEY, null);
    if (saved === 'zh' || saved === 'en') {
      current = saved;
    }
    set({hydrated: true, lang: current});
  },
  setLang: lang => {
    current = lang;
    set({lang});
    writeJSON(LANG_KEY, lang).catch(() => undefined);
  },
}));

export function getLang(): Lang {
  return current;
}

/**
 * The desktop client's `t()`, renamed because `t` is the theme palette across
 * this app. Never call at module top level: modules load before the saved
 * language is read, so a top-level call would freeze the system default.
 */
export function tr(key: MessageKey): string {
  return DICTS[current][key] || DICTS.en[key] || key;
}

/** {@link tr} with `{placeholder}` interpolation. */
export function trf(key: MessageKey, vars: Record<string, string | number>): string {
  let out = tr(key);
  for (const [k, v] of Object.entries(vars)) {
    out = out.split(`{${k}}`).join(String(v));
  }
  return out;
}

/** Resolve a server label that is either a plain string or `{zh, en}`. */
export function localizedLabel(label: string | {zh?: string; en?: string} | null | undefined, fallback = ''): string {
  if (!label) {
    return fallback;
  }
  if (typeof label === 'string') {
    return label;
  }
  return label[current] || label.en || label.zh || fallback;
}
