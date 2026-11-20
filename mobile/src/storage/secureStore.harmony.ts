import {plainStore, type SecureStore} from './plainStore';

export type {SecureStore} from './plainStore';

/**
 * react-native-keychain has no RNOH port, so tokens are still in plain app storage here.
 * Release builds must move them to Asset Store Kit; plainStore is what the migration reads from.
 */
export const secureStore: SecureStore = plainStore;
