import {create} from 'zustand';
import {
  deleteProject,
  deleteSession,
  getSessions,
  renameProject,
  setProjectOrder,
  updateSession,
} from '../api/cowApi';
import {ApiError} from '../api/http';
import type {SessionItem} from '../protocol/events';
import {readJSON, writeJSON} from '../storage/kv';
import {agentParam} from './agentStore';
import {resetOnSignOut} from './reset';
import {onServerEnvelope, useServerStore} from './serverStore';

const PAGE_SIZE = 50;
const COLLAPSED_KEY = 'collapsed_spaces';

interface SessionState {
  sessions: SessionItem[];
  total: number;
  page: number;
  hasMore: boolean;
  loading: boolean;
  loadingMore: boolean;
  error: string | null;
  /** `project` once chats work in more than one space, as the server decides. */
  groupMode: 'project' | 'time';
  projectOrder: string[];
  /** Space keys folded shut, kept on the phone. */
  collapsed: string[];
  refresh: () => Promise<void>;
  loadMore: () => Promise<void>;
  rename: (session: SessionItem, title: string) => Promise<void>;
  setPinned: (session: SessionItem, pinned: boolean) => Promise<void>;
  remove: (session: SessionItem) => Promise<void>;
  toggleCollapsed: (key: string) => void;
  /** Moves `key` by `delta` places among `keys`, the spaces as shown. */
  moveSpace: (key: string, delta: number, keys: string[]) => Promise<void>;
  renameSpace: (path: string, name: string) => Promise<void>;
  removeSpace: (path: string) => Promise<void>;
}

async function handleError(e: unknown): Promise<string> {
  if (e instanceof ApiError && e.kind === 'unauthorized') {
    await useServerStore.getState().expireIfSignedOut();
  }
  return e instanceof Error ? e.message : String(e);
}

// Read once per sign-in; a fold made before the read lands is kept.
let collapsedRead: Promise<void> | null = null;

export const useSessionStore = create<SessionState>((set, get) => {
  const patchLocal = (id: string, patch: Partial<SessionItem>) =>
    set(s => ({
      sessions: s.sessions.map(x => (x.session_id === id ? {...x, ...patch} : x)),
    }));

  const readCollapsed = () =>
    (collapsedRead ??= readJSON<string[]>(COLLAPSED_KEY, [])
      .then(collapsed => set(s => (s.collapsed.length ? {} : {collapsed})))
      .catch(() => undefined));

  return {
    sessions: [],
    total: 0,
    page: 0,
    hasMore: false,
    loading: false,
    loadingMore: false,
    error: null,
    groupMode: 'time',
    projectOrder: [],
    collapsed: [],

    refresh: async () => {
      set({loading: true, error: null});
      readCollapsed();
      try {
        const res = await getSessions(1, PAGE_SIZE);
        set({
          sessions: res.sessions,
          total: res.total,
          page: 1,
          hasMore: res.has_more,
          loading: false,
          groupMode: res.group_mode === 'project' ? 'project' : 'time',
          projectOrder: res.project_order ?? [],
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

    toggleCollapsed: key => {
      const {collapsed} = get();
      const next = collapsed.includes(key) ? collapsed.filter(k => k !== key) : [...collapsed, key];
      set({collapsed: next});
      writeJSON(COLLAPSED_KEY, next).catch(() => undefined);
    },

    moveSpace: async (key, delta, keys) => {
      const from = keys.indexOf(key);
      const to = from + delta;
      if (from < 0 || to < 0 || to >= keys.length) {
        return;
      }
      const shown = [...keys];
      shown.splice(to, 0, ...shown.splice(from, 1));
      const previous = get().projectOrder;
      // Spaces not listed (the drawer shows only recent chats) keep their saved places after these.
      const order = [...shown, ...previous.filter(k => !shown.includes(k))];
      set({projectOrder: order});
      try {
        await setProjectOrder(order);
      } catch (e) {
        set({projectOrder: previous});
        throw e;
      }
    },

    renameSpace: async (path, name) => {
      const res = await renameProject(path, name);
      set(s => ({
        sessions: s.sessions.map(x => (x.project?.path === path ? {...x, project: {path, name: res.name || name}} : x)),
      }));
    },

    removeSpace: async path => {
      await deleteProject(path);
      await get().refresh();
    },
  };
});

resetOnSignOut(useSessionStore, () => {
  collapsedRead = null;
});

onServerEnvelope(envelope => {
  if (envelope.type === 'push.message' || envelope.type === 'scheduler.run') {
    useSessionStore.getState().refresh();
  }
});
