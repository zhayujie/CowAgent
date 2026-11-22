import {create} from 'zustand';

/**
 * Conversations whose reply finished while the reader was elsewhere in the app. The left list
 * marks them until they are opened; a finished reply in the open conversation is not "unseen",
 * so nothing is stored for it.
 */
interface UnreadState {
  unread: Record<string, true>;
  mark: (sessionId: string) => void;
  clear: (sessionId: string) => void;
}

export const useUnreadStore = create<UnreadState>(set => ({
  unread: {},
  mark: sessionId =>
    set(s => (s.unread[sessionId] ? s : {unread: {...s.unread, [sessionId]: true}})),
  clear: sessionId =>
    set(s => {
      if (!s.unread[sessionId]) {
        return s;
      }
      const next = {...s.unread};
      delete next[sessionId];
      return {unread: next};
    }),
}));
