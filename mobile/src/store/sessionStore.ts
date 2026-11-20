import {create} from 'zustand';
import {deleteSession, getSessions, updateSession} from '../api/cowApi';
import {ApiError} from '../api/http';
import type {SessionItem} from '../protocol/events';
import {agentParam} from './agentStore';
import {resetOnSignOut} from './reset';
import {onServerEnvelope, useServerStore} from './serverStore';

const PAGE_SIZE = 50;

interface SessionState {
  sessions: SessionItem[];
  total: number;
  page: number;
  hasMore: boolean;
  loading: boolean;
  loadingMore: boolean;
  error: string | null;
  refresh: () => Promise<void>;
  loadMore: () => Promise<void>;
  rename: (session: SessionItem, title: string) => Promise<void>;
  setPinned: (session: SessionItem, pinned: boolean) => Promise<void>;
  remove: (session: SessionItem) => Promise<void>;
}

async function handleError(e: unknown): Promise<string> {
  if (e instanceof ApiError && e.kind === 'unauthorized') {
    await useServerStore.getState().expireIfSignedOut();
  }
  return e instanceof Error ? e.message : String(e);
}

export const useSessionStore = create<SessionState>((set, get) => {
  const patchLocal = (id: string, patch: Partial<SessionItem>) =>
    set(s => ({
      sessions: s.sessions.map(x => (x.session_id === id ? {...x, ...patch} : x)),
    }));

  return {
    sessions: [],
    total: 0,
    page: 0,
    hasMore: false,
    loading: false,
    loadingMore: false,
    error: null,

    refresh: async () => {
      set({loading: true, error: null});
      try {
        const res = await getSessions(1, PAGE_SIZE);
        set({
          sessions: res.sessions,
          total: res.total,
          page: 1,
          hasMore: res.has_more,
          loading: false,
        });
      } catch (e) {
        set({loading: false, error: await handleError(e)});
      }
    },

    loadMore: async () => {
      const {hasMore, loading, loadingMore, page} = get();
      if (!hasMore || loading || loadingMore) {
        return;
      }
      set({loadingMore: true});
      try {
        const res = await getSessions(page + 1, PAGE_SIZE);
        const known = new Set(get().sessions.map(s => s.session_id));
        set(s => ({
          sessions: [...s.sessions, ...res.sessions.filter(x => !known.has(x.session_id))],
          page: page + 1,
          hasMore: res.has_more,
          loadingMore: false,
        }));
      } catch (e) {
        set({loadingMore: false, error: await handleError(e)});
      }
    },

    rename: async (session, title) => {
      const previous = session.title;
      patchLocal(session.session_id, {title});
      try {
        await updateSession(session.session_id, {title}, agentParam(session.agent?.id));
      } catch (e) {
        patchLocal(session.session_id, {title: previous});
        throw e;
      }
    },

    setPinned: async (session, pinned) => {
      patchLocal(session.session_id, {pinned});
      try {
        await updateSession(session.session_id, {pinned}, agentParam(session.agent?.id));
      } catch (e) {
        patchLocal(session.session_id, {pinned: !pinned});
        throw e;
      }
    },

    remove: async session => {
      await deleteSession(session.session_id, agentParam(session.agent?.id));
      set(s => ({
        sessions: s.sessions.filter(x => x.session_id !== session.session_id),
        total: Math.max(0, s.total - 1),
      }));
    },
  };
});

resetOnSignOut(useSessionStore);

onServerEnvelope(envelope => {
  if (envelope.type === 'push.message' || envelope.type === 'scheduler.run') {
    useSessionStore.getState().refresh();
  }
});
