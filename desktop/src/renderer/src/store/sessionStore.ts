import { create } from 'zustand'
import apiClient from '../api/client'
import { t } from '../i18n'
import type { SessionItem } from '../types'

const ACTIVE_KEY = 'cow_session_id'
export const DEFAULT_SPACE_KEY = '__default__'

interface SessionState {
  sessions: SessionItem[]
  total: number
  page: number
  hasMore: boolean
  loading: boolean
  activeId: string
  groupMode: 'project' | 'time'
  projectOrder: string[]
  /** Bumped whenever project records change (rename/delete), so other views
   *  (e.g. the workspace selector's recents) can refresh in lockstep. */
  projectsRev: number
  bumpProjects: () => void

  loadSessions: (page?: number) => Promise<void>
  loadMore: () => Promise<void>
  setActive: (id: string) => void
  newSession: () => string
  /** The project the currently-active session is bound to, or null (default). */
  currentProject: () => { path: string; name: string } | null
  /**
   * Insert a not-yet-persisted session at the top of the list so it is visible
   * immediately (before its first message). `project` files it under the right
   * space group. No-op if the id is already present.
   */
  addOptimistic: (id: string, project?: { path: string; name: string } | null) => void
  rename: (id: string, title: string) => Promise<void>
  remove: (id: string) => Promise<void>
  togglePin: (id: string) => Promise<void>
  reorderSpaces: (fromKey: string, beforeKey: string, currentOrder?: string[]) => void
}

function genId(): string {
  return `session_${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`
}

function readActive(): string {
  return localStorage.getItem(ACTIVE_KEY) || genId()
}

function sortSessions(list: SessionItem[]): SessionItem[] {
  return [...list].sort((a, b) => {
    const pa = a.pinned ? 1 : 0
    const pb = b.pinned ? 1 : 0
    if (pa !== pb) return pb - pa
    return (b.last_active || 0) - (a.last_active || 0)
  })
}

export const useSessionStore = create<SessionState>((set, get) => ({
  sessions: [],
  total: 0,
  page: 1,
  hasMore: false,
  loading: false,
  activeId: readActive(),
  groupMode: 'time',
  projectOrder: [],
  projectsRev: 0,

  bumpProjects: () => set((s) => ({ projectsRev: s.projectsRev + 1 })),

  loadSessions: async (page = 1) => {
    set({ loading: true })
    try {
      const res = await apiClient.getSessions(page, 50)
      set((s) => ({
        sessions: page === 1 ? res.sessions : [...s.sessions, ...res.sessions],
        total: res.total,
        page: res.page,
        hasMore: res.has_more,
        groupMode: res.group_mode || 'time',
        projectOrder: res.project_order || s.projectOrder,
        loading: false,
      }))
    } catch {
      set({ loading: false })
    }
  },

  loadMore: async () => {
    const { hasMore, loading, page } = get()
    if (!hasMore || loading) return
    await get().loadSessions(page + 1)
  },

  setActive: (id) => {
    localStorage.setItem(ACTIVE_KEY, id)
    set({ activeId: id })
  },

  newSession: () => {
    const id = genId()
    localStorage.setItem(ACTIVE_KEY, id)
    set({ activeId: id })
    return id
  },

  currentProject: () => {
    const { activeId, sessions } = get()
    return sessions.find((s) => s.session_id === activeId)?.project ?? null
  },

  addOptimistic: (id, project) => {
    set((s) => {
      const existing = s.sessions.find((sess) => sess.session_id === id)
      // Already present: just re-file it under the given space (e.g. the user
      // bound a fresh chat to a project after creating it) and float it to top.
      if (existing) {
        const rest = s.sessions.filter((sess) => sess.session_id !== id)
        return { sessions: [{ ...existing, project: project ?? null }, ...rest] }
      }
      const now = Math.floor(Date.now() / 1000)
      const item: SessionItem = {
        session_id: id,
        title: t('session_new'),
        created_at: now,
        last_active: now,
        msg_count: 0,
        pinned: false,
        project: project ?? null,
      }
      return { sessions: [item, ...s.sessions] }
    })
  },

  rename: async (id, title) => {
    await apiClient.renameSession(id, title)
    set((s) => ({
      sessions: s.sessions.map((sess) => (sess.session_id === id ? { ...sess, title } : sess)),
    }))
  },

  remove: async (id) => {
    await apiClient.deleteSession(id)
    set((s) => ({ sessions: s.sessions.filter((sess) => sess.session_id !== id) }))
    if (get().activeId === id) get().newSession()
  },

  togglePin: async (id) => {
    const entry = get().sessions.find((s) => s.session_id === id)
    if (!entry) return
    const pinned = !entry.pinned
    set((s) => ({
      sessions: sortSessions(
        s.sessions.map((sess) => (sess.session_id === id ? { ...sess, pinned } : sess))
      ),
    }))
    try {
      const res = await apiClient.setSessionPinned(id, pinned)
      if (res.status !== 'success') throw new Error(res.message || 'pin failed')
    } catch {
      set((s) => ({
        sessions: sortSessions(
          s.sessions.map((sess) => (sess.session_id === id ? { ...sess, pinned: !pinned } : sess))
        ),
      }))
    }
  },

  reorderSpaces: (fromKey, beforeKey, currentOrder) => {
    const { projectOrder, sessions, groupMode } = get()
    // Prefer the caller's currently-displayed group order (already stable via
    // buildGroups) so dragging matches what the user sees, and is never skewed
    // by a freshly created session sitting at the top of the array. Fall back
    // to the saved order, then to a derived one.
    const current =
      currentOrder && currentOrder.length
        ? [...currentOrder]
        : projectOrder.length
          ? [...projectOrder]
          : Array.from(
              new Set(sessions.map((s) => s.project?.path || DEFAULT_SPACE_KEY))
            )
    // Include any visible keys the saved order does not yet know about.
    if (groupMode === 'project') {
      for (const s of sessions) {
        const k = s.project?.path || DEFAULT_SPACE_KEY
        if (!current.includes(k)) current.push(k)
      }
      if (!current.includes(DEFAULT_SPACE_KEY) && sessions.some((s) => !s.project?.path)) {
        current.unshift(DEFAULT_SPACE_KEY)
      }
    }
    const order = current.filter((k) => k !== fromKey)
    const idx = order.indexOf(beforeKey)
    if (idx < 0) order.push(fromKey)
    else order.splice(idx, 0, fromKey)
    set({ projectOrder: order })
    apiClient.setProjectsOrder(order).catch(() => {
      /* keep optimistic order; next loadSessions will reconcile */
    })
  },
}))
