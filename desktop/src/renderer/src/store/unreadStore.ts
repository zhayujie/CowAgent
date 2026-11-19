import { create } from 'zustand'
import { useSessionStore } from './sessionStore'

// Conversations whose run finished (or that received a message) while the user
// wasn't looking at them. Shown as a dot in the session list and as a badge on
// the taskbar / Dock icon. Persisted so an unseen result survives a restart.
const STORAGE_KEY = 'cow_unread_sessions'

function load(): Record<string, true> {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    const arr = raw ? (JSON.parse(raw) as string[]) : []
    return Object.fromEntries((Array.isArray(arr) ? arr : []).map((id) => [id, true as const]))
  } catch {
    return {}
  }
}

function save(unread: Record<string, true>): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(Object.keys(unread)))
  } catch {
    /* storage unavailable: keep in memory */
  }
}

// Counts only sessions still in the list: one deleted from another client
// stays in `unread` with no row left to open and clear it.
let badgeCount = -1

function syncBadge(unread: Record<string, true>): void {
  const count = useSessionStore.getState().sessions.filter((s) => unread[s.session_id]).length
  if (count === badgeCount) return
  badgeCount = count
  window.electronAPI?.setUnreadBadge?.(count)
}

/** The user is looking at this conversation right now. */
export function isViewing(sid: string): boolean {
  if (sid !== useSessionStore.getState().activeId) return false
  if (document.visibilityState !== 'visible' || !document.hasFocus()) return false
  // HashRouter: the chat page is the root route.
  const route = window.location.hash.replace(/^#/, '').split('?')[0]
  return route === '' || route === '/'
}

interface UnreadState {
  unread: Record<string, true>
  /** Flag `sid` as having something new, unless the user is viewing it. */
  mark: (sid: string) => void
  clear: (sid: string) => void
}

export const useUnreadStore = create<UnreadState>((set, get) => ({
  unread: load(),

  mark: (sid) => {
    if (!sid || get().unread[sid] || isViewing(sid)) return
    const unread = { ...get().unread, [sid]: true as const }
    set({ unread })
    save(unread)
    syncBadge(unread)
  },

  clear: (sid) => {
    if (!get().unread[sid]) return
    const unread = { ...get().unread }
    delete unread[sid]
    set({ unread })
    save(unread)
    syncBadge(unread)
  },
}))

// Opening a conversation (or coming back to the window / chat page while it is
// open) counts as reading it.
function clearIfViewing(): void {
  const sid = useSessionStore.getState().activeId
  if (isViewing(sid)) useUnreadStore.getState().clear(sid)
}

useSessionStore.subscribe((s, prev) => {
  if (s.activeId !== prev.activeId) clearIfViewing()
  if (s.sessions !== prev.sessions) syncBadge(useUnreadStore.getState().unread)
})
window.addEventListener('focus', clearIfViewing)
window.addEventListener('hashchange', clearIfViewing)
document.addEventListener('visibilitychange', clearIfViewing)

syncBadge(useUnreadStore.getState().unread)
clearIfViewing()
