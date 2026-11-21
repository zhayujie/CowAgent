import {StyleSheet, useColorScheme} from 'react-native';
import {create} from 'zustand';
import {readJSON, writeJSON} from '../storage/kv';
import {dark, light, type Palette} from './palette';

export type ThemeMode = 'system' | 'light' | 'dark';

interface PrefsState {
  hydrated: boolean;
  mode: ThemeMode;
  hydrate: () => Promise<void>;
  setMode: (mode: ThemeMode) => void;
}

interface PersistedPrefs {
  mode: ThemeMode;
}

const PREFS_KEY = 'prefs';

export const usePrefsStore = create<PrefsState>(set => ({
  hydrated: false,
  mode: 'system',
  hydrate: async () => {
    const saved = await readJSON<Partial<PersistedPrefs>>(PREFS_KEY, {});
    set({hydrated: true, mode: saved.mode ?? 'system'});
  },
  setMode: mode => {
    set({mode});
    writeJSON(PREFS_KEY, {mode} satisfies PersistedPrefs).catch(() => undefined);
  },
}));

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
