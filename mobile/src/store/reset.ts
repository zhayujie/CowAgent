import type {StoreApi} from 'zustand';

const resets: Array<() => void> = [];

/**
 * Puts `store` back to the state it was created with when the user signs out,
 * so the next server (or account) never sees the last one's sessions, agents
 * or drafts. Call right after `create`, before anything has changed it.
 */
export function resetOnSignOut<S>(store: StoreApi<S>, before?: (state: S) => void) {
  const initial = store.getState();
  resets.push(() => {
    before?.(store.getState());
    store.setState(initial, true);
  });
}

export function resetServerData() {
  resets.forEach(reset => reset());
}
