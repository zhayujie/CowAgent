import {readJSON, removeKey, writeJSON} from './kv';

/** Storage for credentials (device tokens). */
export interface SecureStore {
  get(key: string): Promise<string | null>;
  set(key: string, value: string): Promise<void>;
  remove(key: string): Promise<void>;
}

/** Plain app storage: what every platform used before the OS key stores, and still the web/HarmonyOS one. */
export const plainStore: SecureStore = {
  get: key => readJSON<string | null>(`secure:${key}`, null),
  set: (key, value) => writeJSON(`secure:${key}`, value),
  remove: key => removeKey(`secure:${key}`),
};

/**
 * `vault`, picking up values `legacy` still holds and deleting them once moved.
 *
 * If the vault itself fails (some Android Keystores are broken), values stay in
 * `legacy` rather than locking the user out: no worse than before the vault existed.
 */
export function migratingStore(vault: SecureStore, legacy: SecureStore): SecureStore {
  return {
    async get(key) {
      let value: string | null;
      try {
        value = await vault.get(key);
      } catch {
        return legacy.get(key);
      }
      if (value != null) {
        return value;
      }
      const old = await legacy.get(key);
      if (old != null) {
        await vault
          .set(key, old)
          .then(() => legacy.remove(key))
          .catch(() => undefined);
      }
      return old;
    },
    async set(key, value) {
      try {
        await vault.set(key, value);
      } catch {
        await legacy.set(key, value);
        return;
      }
      await legacy.remove(key);
    },
    async remove(key) {
      await Promise.all([vault.remove(key).catch(() => undefined), legacy.remove(key)]);
    },
  };
}
