import {plainStore, type SecureStore} from './plainStore';

export type {SecureStore} from './plainStore';

/** Browsers have no OS key store; the preview is a development tool. */
export const secureStore: SecureStore = plainStore;
