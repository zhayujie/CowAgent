import {StyleSheet, useColorScheme} from 'react-native';
import {create} from 'zustand';
import {readJSON, writeJSON} from '../storage/kv';
import {dark, light, type Palette} from './palette';

export type ThemeMode = 'system' | 'light' | 'dark';

interface PrefsState {
  hydrated: boolean;
  mode: ThemeMode;
  /** Set once the first message is sent; the first-run guide never returns. */
  onboarded: boolean;
  hydrate: () => Promise<void>;
  setMode: (mode: ThemeMode) => void;
  markOnboarded: () => void;
}

interface PersistedPrefs {
  mode: ThemeMode;
  onboarded: boolean;
}

const PREFS_KEY = 'prefs';

export const usePrefsStore = create<PrefsState>((set, get) => {
  const persist = () => {
    const {mode, onboarded} = get();
    writeJSON(PREFS_KEY, {mode, onboarded} satisfies PersistedPrefs).catch(() => undefined);
  };
  return {
    hydrated: false,
    mode: 'system',
    onboarded: false,
    hydrate: async () => {
      const saved = await readJSON<Partial<PersistedPrefs>>(PREFS_KEY, {});
      set({
        hydrated: true,
        mode: saved.mode ?? 'system',
        onboarded: saved.onboarded ?? false,
      });
    },
    setMode: mode => {
      set({mode});
      persist();
    },
    markOnboarded: () => {
      if (!get().onboarded) {
        set({onboarded: true});
        persist();
      }
    },
  };
});

export function useTheme(): Palette {
  const scheme = useColorScheme();
  const mode = usePrefsStore(s => s.mode);
  const isDark = mode === 'system' ? scheme === 'dark' : mode === 'dark';
  return isDark ? dark : light;
}

/** Build a style sheet per palette once and reuse it across renders. */
export function makeStyles<T extends StyleSheet.NamedStyles<T>>(
  factory: (t: Palette) => T,
): () => T {
  const cache = new Map<Palette, T>();
  return function useStyles() {
    const t = useTheme();
    let styles = cache.get(t);
    if (!styles) {
      styles = StyleSheet.create(factory(t));
      cache.set(t, styles);
    }
    return styles;
  };
}
