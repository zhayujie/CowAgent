import * as Keychain from 'react-native-keychain';
import {migratingStore, plainStore, type SecureStore} from './plainStore';

export type {SecureStore} from './plainStore';

const service = (key: string) => `ai.cowagent.secure.${key}`;

/**
 * iOS Keychain / Android Keystore. Items stay on this device: no iCloud sync,
 * no restore onto another phone, and readable only after the first unlock.
 */
const keychainStore: SecureStore = {
  async get(key) {
    const item = await Keychain.getGenericPassword({service: service(key)});
    return item ? item.password : null;
  },
  async set(key, value) {
    const saved = await Keychain.setGenericPassword(key, value, {
      service: service(key),
      accessible: Keychain.ACCESSIBLE.AFTER_FIRST_UNLOCK_THIS_DEVICE_ONLY,
      storage: Keychain.STORAGE_TYPE.AES_GCM_NO_AUTH,
    });
    if (!saved) {
      throw new Error('Keychain refused the item');
    }
  },
  async remove(key) {
    await Keychain.resetGenericPassword({service: service(key)});
  },
};

export const secureStore: SecureStore = migratingStore(keychainStore, plainStore);
