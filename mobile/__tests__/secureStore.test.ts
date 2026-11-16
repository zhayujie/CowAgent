import AsyncStorage from '@react-native-async-storage/async-storage';
import * as Keychain from 'react-native-keychain';
import {migratingStore, plainStore, type SecureStore} from '../src/storage/plainStore';
import {secureStore} from '../src/storage/secureStore';

jest.mock('@react-native-async-storage/async-storage', () =>
  require('@react-native-async-storage/async-storage/jest/async-storage-mock'),
);

const mockKeychainItems = new Map<string, string>();
jest.mock('react-native-keychain', () => ({
  ACCESSIBLE: {AFTER_FIRST_UNLOCK_THIS_DEVICE_ONLY: 'AccessibleAfterFirstUnlockThisDeviceOnly'},
  STORAGE_TYPE: {AES_GCM_NO_AUTH: 'KeystoreAESGCM_NoAuth'},
  getGenericPassword: jest.fn(async ({service}: {service: string}) => {
    const password = mockKeychainItems.get(service);
    return password == null ? false : {service, username: 'u', password, storage: 'keychain'};
  }),
  setGenericPassword: jest.fn(async (_user: string, password: string, {service}: {service: string}) => {
    mockKeychainItems.set(service, password);
    return {service, storage: 'keychain'};
  }),
  resetGenericPassword: jest.fn(async ({service}: {service: string}) => mockKeychainItems.delete(service)),
}));

function memoryStore(): SecureStore & {items: Map<string, string>} {
  const items = new Map<string, string>();
  return {
    items,
    get: async key => items.get(key) ?? null,
    set: async (key, value) => {
      items.set(key, value);
    },
    remove: async key => {
      items.delete(key);
    },
  };
}

const broken: SecureStore = {
  get: () => Promise.reject(new Error('keystore unavailable')),
  set: () => Promise.reject(new Error('keystore unavailable')),
  remove: () => Promise.reject(new Error('keystore unavailable')),
};

describe('migratingStore', () => {
  it('moves a legacy value into the vault on first read', async () => {
    const vault = memoryStore();
    const legacy = memoryStore();
    legacy.items.set('token:a', 't1');
    const store = migratingStore(vault, legacy);

    expect(await store.get('token:a')).toBe('t1');
    expect(vault.items.get('token:a')).toBe('t1');
    expect(legacy.items.has('token:a')).toBe(false);
  });

  it('prefers the vault and clears legacy copies on write', async () => {
    const vault = memoryStore();
    const legacy = memoryStore();
    legacy.items.set('token:a', 'stale');
    const store = migratingStore(vault, legacy);

    await store.set('token:a', 'fresh');
    expect(await store.get('token:a')).toBe('fresh');
    expect(legacy.items.size).toBe(0);
  });

  it('removes the value from both stores', async () => {
    const vault = memoryStore();
    const legacy = memoryStore();
    vault.items.set('token:a', 'v');
    legacy.items.set('token:a', 'l');
    await migratingStore(vault, legacy).remove('token:a');
    expect(vault.items.size + legacy.items.size).toBe(0);
  });

  it('keeps the user signed in when the vault is broken', async () => {
    const legacy = memoryStore();
    legacy.items.set('token:a', 't1');
    const store = migratingStore(broken, legacy);

    expect(await store.get('token:a')).toBe('t1');
    await store.set('token:b', 't2');
    expect(legacy.items.get('token:b')).toBe('t2');
    await store.remove('token:a');
    expect(legacy.items.has('token:a')).toBe(false);
  });
});

describe('secureStore on iOS/Android', () => {
  beforeEach(async () => {
    mockKeychainItems.clear();
    await AsyncStorage.clear();
    jest.clearAllMocks();
  });

  it('stores tokens in the keychain, device-only and without a biometric prompt', async () => {
    await secureStore.set('token:srv', 'abc');

    expect(Keychain.setGenericPassword).toHaveBeenCalledWith('token:srv', 'abc', {
      service: 'ai.cowagent.secure.token:srv',
      accessible: 'AccessibleAfterFirstUnlockThisDeviceOnly',
      storage: 'KeystoreAESGCM_NoAuth',
    });
    expect(await secureStore.get('token:srv')).toBe('abc');
    expect(await plainStore.get('token:srv')).toBeNull();
  });

  it('migrates a token saved by earlier versions out of AsyncStorage', async () => {
    await plainStore.set('token:srv', 'old');

    expect(await secureStore.get('token:srv')).toBe('old');
    expect(mockKeychainItems.get('ai.cowagent.secure.token:srv')).toBe('old');
    expect(await AsyncStorage.getItem('cow:secure:token:srv')).toBeNull();
  });

  it('signs out of the keychain and AsyncStorage', async () => {
    await secureStore.set('token:srv', 'abc');
    await secureStore.remove('token:srv');
    expect(await secureStore.get('token:srv')).toBeNull();
  });
});
