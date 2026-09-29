import { create } from 'zustand'
import apiClient from '../api/client'
import { t } from '../i18n'
import { useWorkspaceStore } from './workspaceStore'
import { useAgentStore, isMultiAgent, findAgent } from './agentStore'
import { ownerOf, setOwner, forgetOwner, rememberOwners } from './sessionOwners'
import type { AgentBadge, SessionItem, SessionTeam } from '../types'

const ACTIVE_KEY = 'cow_session_id'
export const DEFAULT_SPACE_KEY = '__default__'

/**
 * The Agent that owns a conversation, for scoping its requests.
 *
 * For the open conversation this is, by construction, the active Agent: opening
 * a session activates its owner, and switching Agents on an empty chat re-owns
 * it. For any other row, the recorded owner (fed by the backend list and by
 * chat creation); an unknown one is the default Agent, which is where every
 * pre-team conversation lives. Empty in single-Agent mode so legacy requests
 * stay unscoped.
 */
export function sessionOwner(sessionId: string): string {
  if (!isMultiAgent()) return ''
  const { activeAgentId, defaultAgentId } = useAgentStore.getState()
  if (sessionId === useSessionStore.getState().activeId) return activeAgentId || defaultAgentId
  return ownerOf(sessionId) || defaultAgentId
}

// Opening a conversation makes its owner the active Agent — that's who the
// composer talks to and whose side panels (skills, knowledge) are shown. In
// single-Agent mode there's nothing to switch.
function activateOwner(sessionId: string) {
  if (!isMultiAgent()) return
  const { defaultAgentId, setActive } = useAgentStore.getState()
  const owner = ownerOf(sessionId) || defaultAgentId
  if (owner) setActive(owner)
}

function badgeOf(agentId: string): SessionItem['agent'] {
  if (!agentId) return undefined
  const a = findAgent(agentId)
  return { id: agentId, name: a?.name || agentId, avatar: a?.avatar || '' }
}

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
  setActive: (id: string) => Promise<void>
  /** Start a fresh (client-side) session owned by `ownerId`, or by the active
   *  Agent when omitted. */
  newSession: (ownerId?: string) => string
  /** Re-own a not-yet-persisted conversation (the composer's Agent switch
   *  before the first message). */
  setOwner: (id: string, ownerId: string) => void
  /** The project the currently-active session is bound to, or null (default). */
  currentProject: () => { path: string; name: string } | null
  /**
   * Insert a not-yet-persisted session at the top of the list so it is visible
   * immediately (before its first message). `project` files it under the right
   * space group. No-op if the id is already present.
   */
  addOptimistic: (id: string, project?: { path: string; name: string } | null) => void
  /**
   * Record who is in a conversation, so the list can show their faces.
   *
   * A list item carries its roster once the conversation is persisted; until the
   * first message only the client knows a chat was opened as a group, and
   * without this it reads as an ordinary empty one.
   */
  setParticipants: (id: string, team: SessionTeam) => void
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

// One row per session id. Offset pagination can hand back a row twice when the
// list shifts between pages, and two rows for one conversation both light up as
// "selected". The first occurrence (already on screen) wins.
function dedupe(list: SessionItem[]): SessionItem[] {
  const seen = new Set<string>()
  return list.filter((s) => {
    if (seen.has(s.session_id)) return false
    seen.add(s.session_id)
    return true
  })
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
      // The backend knows every persisted conversation's owner; keep the local
      // map current so switching to any row scopes its requests correctly. If
      // it names a different owner for the open conversation than we assumed
      // (e.g. the local map was lost), follow it — the chat page reloads the
      // history from the right store when the active Agent changes.
      rememberOwners(res.sessions || [])
      if (isMultiAgent() && (res.sessions || []).some((x) => x.session_id === get().activeId)) {
        activateOwner(get().activeId)
      }
      set((s) => ({
        sessions: page === 1 ? dedupe(res.sessions) : dedupe([...s.sessions, ...res.sessions]),
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

  setActive: async (id) => {
    // The workspace panel is scoped to the session, so switching drops any
    // editor open on the old one. Ask before that throws work away.
    if (id !== get().activeId && !(await useWorkspaceStore.getState().guardUnsavedEdit())) return
    localStorage.setItem(ACTIVE_KEY, id)
    activateOwner(id)
    set({ activeId: id })
  },

  newSession: (ownerId) => {
    const id = genId()
    if (isMultiAgent()) {
      const owner = ownerId || useAgentStore.getState().activeAgentId
      if (owner) setOwner(id, owner)
      activateOwner(id)
    }
    localStorage.setItem(ACTIVE_KEY, id)
    set({ activeId: id })
    return id
  },

  setOwner: (id, ownerId) => {
    if (!isMultiAgent() || !ownerId) return
    setOwner(id, ownerId)
    set((s) => ({
      sessions: s.sessions.map((sess) => (sess.session_id === id ? { ...sess, agent: badgeOf(ownerId) } : sess)),
    }))
    if (get().activeId === id) activateOwner(id)
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
        agent: badgeOf(ownerOf(id)),
      }
      return { sessions: [item, ...s.sessions] }
    })
  },

  setParticipants: (id, team) => {
    // Same shape and order the API sends: owner first, deduped. Only a real
    // group gets faces; a conversation back down to its owner drops them again.
    const roster: AgentBadge[] = []
    for (const m of [team.owner, ...(team.members || [])]) {
      if (m?.id && !roster.some((a) => a.id === m.id)) {
        roster.push({ id: m.id, name: m.name, avatar: m.avatar })
      }
    }
    set((s) => ({
      sessions: s.sessions.map((sess) =>
        sess.session_id === id
          ? { ...sess, participants: roster.length > 1 ? roster : undefined }
          : sess
      ),
    }))
  },

  rename: async (id, title) => {
    await apiClient.renameSession(id, title, sessionOwner(id))
    set((s) => ({
      sessions: s.sessions.map((sess) => (sess.session_id === id ? { ...sess, title } : sess)),
    }))
  },

  remove: async (id) => {
    await apiClient.deleteSession(id, sessionOwner(id))
    forgetOwner(id)
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
      const res = await apiClient.setSessionPinned(id, pinned, sessionOwner(id))
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
