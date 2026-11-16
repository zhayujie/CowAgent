import {readJSON, removeKey, writeJSON} from './kv';

/**
 * Storage for credentials (device tokens).
 *
 * Release builds must back this with iOS Keychain, Android Keystore and
 * HarmonyOS Asset Store Kit. The AsyncStorage implementation below keeps
 * tokens in plain app storage and is only acceptable during development.
 */
export interface SecureStore {
  get(key: string): Promise<string | null>;
  set(key: string, value: string): Promise<void>;
  remove(key: string): Promise<void>;
}

const devStore: SecureStore = {
  get: key => readJSON<string | null>(`secure:${key}`, null),
  set: (key, value) => writeJSON(`secure:${key}`, value),
  remove: key => removeKey(`secure:${key}`),
};

export const secureStore: SecureStore = devStore;
