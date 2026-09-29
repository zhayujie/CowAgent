import { create } from 'zustand'
import apiClient from '../api/client'
import { t } from '../i18n'
import { sessionOwner, useSessionStore } from './sessionStore'
import type { SessionSettingsState } from '../types'

/**
 * Per-session model + permission overrides, mirroring the web console's
 * `_sessCfg`. Both fall back to the global config when unset; the composer chips
 * read `cfg` to render the effective model/permission and their menus.
 */
export type ComposerMenu = 'workspace' | 'permission' | 'model' | null

interface SessionSettingsStore {
  /** Settings for the currently loaded session, or null before the first fetch. */
  cfg: SessionSettingsState | null
  /** Which session `cfg` describes, so a stale response for a switched-away
   *  session is ignored. */
  sessionId: string | null
  loading: boolean
  /** Last apply failure, shown inline in the open menu; cleared on the next
   *  attempt or when a menu opens. */
  error: string | null
  /** Which composer menu is open. Shared so the three chips exclude each other,
   *  and so a permission-denied hint can open the permission menu. */
  openMenu: ComposerMenu

  /** Fetch (and cache) settings for a session. Safe to call repeatedly. */
  refresh: (sessionId: string) => Promise<void>
  /** Apply a model / permission / team change, then repaint from the server echo. */
  apply: (
    sessionId: string,
    body: { provider?: string | null; model?: string | null; permission?: string | null; members?: string[] | null }
  ) => Promise<boolean>
  /** Invite a teammate into the conversation (group chat). */
  addMember: (sessionId: string, agentId: string) => Promise<boolean>
  /** Remove a teammate from the conversation. */
  removeMember: (sessionId: string, agentId: string) => Promise<boolean>
  /** Drop cached settings (e.g. on a brand-new chat) so chips fall back to global. */
  reset: () => void
  setOpenMenu: (menu: ComposerMenu) => void
}

// Monotonic token for the latest settings request. A response is only applied
// when its token is still the newest one, so a slow fetch for a session the user
// has switched away from can never overwrite the current session's chips.
let requestSeq = 0

export const useSessionSettingsStore = create<SessionSettingsStore>((set, get) => ({
  cfg: null,
  sessionId: null,
  loading: false,
  error: null,
  openMenu: null,

  // Opening or closing a menu clears any stale failure from a previous attempt.
  setOpenMenu: (menu) => set({ openMenu: menu, error: null }),

  refresh: async (sessionId) => {
    if (!sessionId) return
    const token = ++requestSeq
    set({ loading: true })
    try {
      const data = await apiClient.getSessionSettings(sessionId, sessionOwner(sessionId) || undefined)
      // A newer request has superseded this one: drop the response entirely.
      if (token !== requestSeq) return
      if (data.status !== 'success') {
        set({ loading: false })
        return
      }
      set({ cfg: { model: data.model, permission: data.permission, team: data.team }, sessionId, loading: false })
    } catch {
      if (token === requestSeq) set({ loading: false })
    }
  },

  apply: async (sessionId, body) => {
    // An explicit change is the latest intent for this session; claim the token
    // so an in-flight refresh cannot clobber the echo we are about to write.
    const token = ++requestSeq
    set({ error: null })
    try {
      const data = await apiClient.updateSessionSettings(sessionId, body, sessionOwner(sessionId) || undefined)
      if (data.status !== 'success' || !data.model || !data.permission) {
        set({ error: t('session_settings_failed') })
        return false
      }
      if (token !== requestSeq) return true
      set({ cfg: { model: data.model, permission: data.permission, team: data.team }, sessionId })
      // Keep the list's faces in step with the roster we just changed, which it
      // cannot read from the API until the conversation has a first message.
      if (data.team) useSessionStore.getState().setParticipants(sessionId, data.team)
      return true
    } catch {
      set({ error: t('session_settings_failed') })
      return false
    }
  },

  addMember: async (sessionId, agentId) => {
    const owner = sessionOwner(sessionId)
    if (!agentId || agentId === owner) return false
    const current = (cfgFor(sessionId)?.team?.members || []).map((m) => m.id)
    if (current.includes(agentId)) return true
    return get().apply(sessionId, { members: [...current, agentId] })
  },

  removeMember: async (sessionId, agentId) => {
    const current = (cfgFor(sessionId)?.team?.members || []).map((m) => m.id)
    const next = current.filter((id) => id !== agentId)
    // An empty list means "nobody invited": the backend takes null for that.
    return get().apply(sessionId, { members: next.length ? next : null })
  },

  reset: () => set({ cfg: null, sessionId: null, openMenu: null, error: null }),
}))

/** True when `cfg` is loaded and belongs to the given session. */
export function cfgFor(sessionId: string): SessionSettingsState | null {
  const { cfg, sessionId: loaded } = useSessionSettingsStore.getState()
  return cfg && loaded === sessionId ? cfg : null
}

/** Selector: the loaded conversation holds more than its owner (a group chat).
 *  Until then it's an ordinary chat and is drawn like one. */
export function selectSharedConversation(s: SessionSettingsStore): boolean {
  return (s.cfg?.team?.members?.length ?? 0) > 0
}
