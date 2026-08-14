import { create } from 'zustand'
import apiClient from '../api/client'
import { t } from '../i18n'
import type { Artifact, WorkspaceEntry } from '../types'

const WIDTH_KEY = 'cow_workspace_width'
export const WS_MIN_WIDTH = 300
export const WS_DEFAULT_WIDTH = 440

function readWidth(): number {
  const raw = parseInt(localStorage.getItem(WIDTH_KEY) || '', 10)
  return Number.isFinite(raw) && raw >= WS_MIN_WIDTH ? raw : WS_DEFAULT_WIDTH
}

export type WorkspaceTab = 'preview' | 'files'

interface WorkspaceState {
  open: boolean
  tab: WorkspaceTab
  width: number
  /** File currently shown in the preview tab. */
  current: WorkspaceEntry | null
  previewError: string | null
  /**
   * Set once the user closes the panel by hand. While true we stop
   * auto-opening artifacts, so the panel never fights the user.
   */
  autoOpenSuppressed: boolean
  /** Artifacts produced by the turn that is currently streaming. */
  turnArtifacts: Artifact[]
  /** Directory the files tab should jump to, with a counter so repeated
   *  requests for the same folder still trigger a reload. */
  browseDir: string | null
  browseSeq: number
  /** Session whose working dir the panel is scoped to. Passed to workspace
   *  API calls so the tree/preview resolve against the session's project. */
  sessionId: string

  openPanel: (tab?: WorkspaceTab) => void
  closePanel: (byUser?: boolean) => void
  togglePanel: () => void
  setTab: (tab: WorkspaceTab) => void
  setWidth: (w: number) => void

  /** Switch the panel to a new session: drop stale file/preview state and, if
   *  open on the files tab, reload the new session's root. */
  onSessionSwitch: (sessionId: string) => void

  /** Force the files tab back to the root and reload it. Used after the project
   *  for the current session changes (select / open / new), where the session
   *  id is unchanged so onSessionSwitch would no-op. */
  reloadRoot: () => void

  preview: (target: WorkspaceEntry | Artifact | string) => Promise<void>
  openLink: (path: string) => Promise<void>
  addTurnArtifact: (a: Artifact) => void
  resetTurnArtifacts: () => void
  maybeAutoOpen: () => void
}

/** Artifact and WorkspaceEntry differ only in naming; normalize to an entry. */
function toEntry(a: Artifact): WorkspaceEntry {
  return {
    name: a.file_name,
    path: a.rel_path,
    is_dir: false,
    kind: a.kind,
    previewable: a.previewable,
    size: a.size,
    mtime: 0,
    abs_path: a.abs_path,
    raw_url: a.raw_url,
    preview_url: a.preview_url,
  }
}

export const useWorkspaceStore = create<WorkspaceState>((set, get) => ({
  open: false,
  tab: 'preview',
  width: readWidth(),
  current: null,
  previewError: null,
  autoOpenSuppressed: false,
  turnArtifacts: [],
  browseDir: null,
  browseSeq: 0,
  sessionId: '',

  openPanel: (tab) => set((s) => ({ open: true, tab: tab ?? s.tab })),

  closePanel: (byUser) =>
    set((s) => ({ open: false, autoOpenSuppressed: byUser ? true : s.autoOpenSuppressed })),

  togglePanel: () => {
    const s = get()
    if (s.open) {
      s.closePanel(true)
      return
    }
    set({ open: true, autoOpenSuppressed: false, tab: s.current ? 'preview' : 'files' })
  },

  setTab: (tab) => set({ tab }),

  setWidth: (w) => {
    const next = Math.max(WS_MIN_WIDTH, Math.round(w))
    localStorage.setItem(WIDTH_KEY, String(next))
    set({ width: next })
  },

  onSessionSwitch: (sessionId) => {
    const s = get()
    if (s.sessionId === sessionId) return
    // The tree/preview belong to the previous session's working dir; drop them.
    set({
      sessionId,
      current: null,
      previewError: null,
      turnArtifacts: [],
      browseDir: null,
    })
    // If open on the files tab, reload the new session's root immediately.
    if (s.open && s.tab === 'files') {
      set({ browseDir: '', browseSeq: get().browseSeq + 1 })
    }
  },

  reloadRoot: () => {
    // Drop stale preview/artifacts and bump the browse counter so the files
    // tab re-fetches the (new) root even when path is unchanged ('').
    set({
      current: null,
      previewError: null,
      turnArtifacts: [],
      browseDir: '',
      browseSeq: get().browseSeq + 1,
    })
  },

  preview: async (target) => {
    let entry: WorkspaceEntry | null = null
    if (typeof target === 'string') {
      try {
        entry = (await apiClient.workspaceResolve(target, get().sessionId)).file
      } catch (e) {
        set({
          open: true,
          tab: 'preview',
          current: null,
          previewError: e instanceof Error ? e.message : String(e),
        })
        return
      }
    } else if ('rel_path' in target) {
      entry = toEntry(target)
    } else {
      entry = target
    }

    // Directories have nothing to render; browse into them instead.
    const browseIfDir = (e: WorkspaceEntry | null): boolean => {
      if (!e?.is_dir) return false
      set({
        open: true,
        tab: 'files',
        previewError: null,
        browseDir: e.path,
        browseSeq: get().browseSeq + 1,
      })
      return true
    }
    if (browseIfDir(entry)) return

    // Cards rebuilt from history carry only a path; fetch the signed URLs.
    if (entry && !entry.preview_url) {
      try {
        entry = (await apiClient.workspaceResolve(entry.abs_path || entry.path, get().sessionId)).file
      } catch (e) {
        set({
          open: true,
          tab: 'preview',
          current: null,
          previewError: e instanceof Error ? e.message : String(e),
        })
        return
      }
      if (browseIfDir(entry)) return
    }

    set({ open: true, tab: 'preview', current: entry, previewError: null })
  },

  /**
   * Open a workspace file referenced by a link in a rendered message. Agent
   * links are occasionally relative to the citing document rather than to the
   * workspace root, so fall back to a filename search before giving up.
   */
  openLink: async (path) => {
    try {
      await get().preview((await apiClient.workspaceResolve(path, get().sessionId)).file)
      return
    } catch {
      /* fall through to the name search */
    }

    const name = path.split('/').pop() || path
    try {
      const { results } = await apiClient.workspaceSearch(name, 10, get().sessionId)
      const hit = (results || []).find((r) => !r.is_dir && r.name === name)
      if (hit) {
        await get().preview(hit)
        return
      }
    } catch {
      /* fall through to the error state */
    }

    set({
      open: true,
      tab: 'preview',
      current: null,
      previewError: `${t('ws_link_not_found')}: ${path}`,
    })
  },

  addTurnArtifact: (a) =>
    set((s) =>
      s.turnArtifacts.some((x) => x.abs_path === a.abs_path)
        ? s
        : { turnArtifacts: [...s.turnArtifacts, a] }
    ),

  // Called when the user sends a new message. Clearing autoOpenSuppressed here
  // means "dismissing the panel only suppresses auto-open for the current turn";
  // a fresh request re-enables auto-preview of its products.
  resetTurnArtifacts: () => set({ turnArtifacts: [], autoOpenSuppressed: false }),

  /**
   * Auto-open policy: only when the turn produced exactly one previewable
   * artifact, and only while the user hasn't dismissed the panel by hand.
   */
  maybeAutoOpen: () => {
    const { turnArtifacts, autoOpenSuppressed, preview } = get()
    const previewable = turnArtifacts.filter((a) => a.previewable)
    set({ turnArtifacts: [] })
    if (autoOpenSuppressed || previewable.length !== 1) return
    preview(previewable[0])
  },
}))
