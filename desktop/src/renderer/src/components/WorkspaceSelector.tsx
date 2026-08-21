import React, { useCallback, useEffect, useRef, useState } from 'react'
import { FolderOpen, Folder, House, ChevronDown, Check, Plus } from 'lucide-react'
import { t } from '../i18n'
import apiClient from '../api/client'
import type { ProjectState } from '../types'
import { Modal, Btn, TextInput } from '../pages/settings/primitives'
import { useWorkspaceStore } from '../store/workspaceStore'
import { useSessionStore } from '../store/sessionStore'
import { useSessionSettingsStore } from '../store/sessionSettingsStore'
import { useUIStore } from '../store/uiStore'
import Tooltip from './Tooltip'

interface WorkspaceSelectorProps {
  sessionId: string
}

/**
 * Per-session project workspace picker. Mirrors the web console: pick the
 * default workspace (~/cow), a recent project, create a new project, or open
 * an existing directory via the native OS folder dialog. Selecting a project
 * scopes the agent's cwd, previews and `@` picker to that directory.
 */
const WorkspaceSelector: React.FC<WorkspaceSelectorProps> = ({ sessionId }) => {
  const [state, setState] = useState<ProjectState | null>(null)
  const openMenu = useSessionSettingsStore((s) => s.openMenu)
  const setOpenMenu = useSessionSettingsStore((s) => s.setOpenMenu)
  const menuOpen = openMenu === 'workspace'
  const [newOpen, setNewOpen] = useState(false)
  const [newName, setNewName] = useState('')
  const [newError, setNewError] = useState('')
  const [busy, setBusy] = useState(false)
  const rootRef = useRef<HTMLDivElement>(null)

  const reloadRoot = useWorkspaceStore((s) => s.reloadRoot)
  const openPanel = useWorkspaceStore((s) => s.openPanel)

  const refresh = useCallback(async () => {
    if (!sessionId) return
    try {
      const data = await apiClient.getProjects(sessionId)
      if (data.status === 'success') setState(data)
    } catch {
      /* keep last state; selector is non-critical */
    }
  }, [sessionId])

  // Reload whenever the active session changes.
  useEffect(() => {
    refresh()
  }, [refresh])

  // Also reload when project records change elsewhere (e.g. a project is
  // renamed/deleted from the session sidebar), so recents stay in sync.
  const projectsRev = useSessionStore((s) => s.projectsRev)
  useEffect(() => {
    refresh()
  }, [projectsRev, refresh])

  // Close the menu on outside click.
  useEffect(() => {
    if (!menuOpen) return
    const onDown = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpenMenu(null)
    }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [menuOpen, setOpenMenu])

  const current = state?.current || null
  const label = current ? current.name : t('ws_default_workspace')
  const fullPath = current ? current.path : state?.default_workspace || ''

  // Apply a project selection and reveal the file panel scoped to it. The
  // session id is unchanged, so we force a root reload rather than relying on
  // the session-switch path (which would no-op).
  const applyState = (next: ProjectState) => {
    setState(next)
    openPanel('files')
    reloadRoot()
    // Reveal the history sidebar so the current session shows under the space
    // it was just bound to (mirrors the web console behavior).
    useUIStore.getState().setSessionsCollapsed(false)
    // Grouping in the session list depends on how many spaces are in play.
    const sessionStore = useSessionStore.getState()
    sessionStore.loadSessions(1).then(() => {
      // A brand-new session has no backend record yet, so the reload above
      // won't include it. Add it optimistically under the space it was just
      // bound to, so the user sees the current conversation inside the project.
      const inList = useSessionStore.getState().sessions.some((s) => s.session_id === sessionId)
      if (!inList) {
        useSessionStore
          .getState()
          .addOptimistic(sessionId, next.current ? { path: next.current.path, name: next.current.name } : null)
      }
    })
  }

  const selectProject = async (projectDir: string | null) => {
    setOpenMenu(null)
    setBusy(true)
    try {
      const res = await apiClient.selectProject(sessionId, projectDir)
      if (res.status === 'success') applyState(res)
    } catch {
      /* transient; leave current state untouched */
    } finally {
      setBusy(false)
    }
  }

  // Open project: native OS folder picker (Electron), then bind the directory.
  const openProject = async () => {
    setOpenMenu(null)
    const picked = await window.electronAPI?.selectDirectory?.()
    if (picked) await selectProject(picked)
  }

  const openNewDialog = () => {
    setOpenMenu(null)
    setNewName('')
    setNewError('')
    setNewOpen(true)
  }

  const createProject = async () => {
    const name = newName.trim()
    if (!name) {
      setNewError(t('ws_sel_name_required'))
      return
    }
    if (name.includes('/') || name.includes('\\')) {
      setNewError(t('ws_sel_name_no_slash'))
      return
    }
    setBusy(true)
    try {
      const res = await apiClient.createProject(sessionId, name)
      if (res.status === 'success') {
        setNewOpen(false)
        applyState(res)
      } else {
        setNewError(res.message || t('ws_sel_create_failed'))
      }
    } catch (e) {
      setNewError(e instanceof Error ? e.message : t('ws_sel_create_failed'))
    } finally {
      setBusy(false)
    }
  }

  const recents = state?.recents || []

  return (
    <div ref={rootRef} className="relative min-w-0">
      <Tooltip label={fullPath || t('ws_sel_tip')}>
        <button
          type="button"
          onClick={() => setOpenMenu(menuOpen ? null : 'workspace')}
          disabled={busy}
          className={`inline-flex items-center gap-1.5 h-8 px-2 rounded-btn text-xs cursor-pointer transition-colors max-w-full min-w-0 disabled:opacity-50 ${
            menuOpen
              ? 'text-accent bg-accent-soft'
              : 'text-content-secondary hover:text-accent hover:bg-accent-soft'
          }`}
        >
          <FolderOpen size={13} className="shrink-0" />
          <span className="composer-chip-label truncate">{label}</span>
          <ChevronDown size={11} className="opacity-60 shrink-0" />
        </button>
      </Tooltip>

      {menuOpen && (
        <div className="absolute bottom-full left-0 mb-1.5 w-80 max-h-[380px] overflow-y-auto rounded-xl border border-default bg-elevated shadow-xl z-30 p-1.5">
          <div className="px-2.5 pt-1 pb-1.5 text-[11px] font-semibold uppercase tracking-wider text-content-tertiary">
            {t('ws_sel_system_space')}
          </div>

          {/* Default workspace (~/cow) */}
          <button
            onClick={() => selectProject(null)}
            title={state?.default_workspace}
            className={`w-full flex items-center gap-2.5 px-2.5 py-2 rounded-lg text-left cursor-pointer transition-colors ${
              !current ? 'bg-accent-soft text-accent' : 'hover:bg-surface-2 text-content'
            }`}
          >
            <House size={14} className="shrink-0" />
            <span className="flex-1 min-w-0 text-[13px] truncate">{t('ws_default_workspace')}</span>
            {!current && <Check size={14} className="shrink-0" />}
          </button>

          {/* Project space: recent projects plus the open/new actions all live
              under one heading, separated from the system space by a divider. */}
          <div className="my-1 mx-1.5 border-t border-default" />
          <div className="px-2.5 pt-1 pb-1.5 text-[11px] font-semibold uppercase tracking-wider text-content-tertiary">
            {t('ws_sel_project_space')}
          </div>

          {recents.map((r) => {
            const active = current?.path === r.path
            return (
              <button
                key={r.path}
                onClick={() => selectProject(r.path)}
                title={r.path}
                className={`w-full flex items-center gap-2.5 px-2.5 py-2 rounded-lg text-left cursor-pointer transition-colors ${
                  active ? 'bg-accent-soft text-accent' : 'hover:bg-surface-2 text-content'
                }`}
              >
                <Folder size={14} className="shrink-0" />
                <span className="flex-1 min-w-0 text-[13px] truncate">{r.name}</span>
                {active && <Check size={14} className="shrink-0" />}
              </button>
            )
          })}

          {/* Divider between the project list and the open/new-project actions. */}
          <div className="my-1 mx-1.5 border-t border-default" />
          <button
            onClick={openProject}
            className="w-full flex items-center gap-2.5 px-2.5 py-2 rounded-lg text-left cursor-pointer transition-colors hover:bg-surface-2 text-content"
          >
            <FolderOpen size={14} className="shrink-0 text-content-tertiary" />
            <span className="flex-1 min-w-0 text-[13px] truncate">{t('ws_sel_open')}</span>
          </button>
          <button
            onClick={openNewDialog}
            className="w-full flex items-center gap-2.5 px-2.5 py-2 rounded-lg text-left cursor-pointer transition-colors hover:bg-surface-2 text-content"
          >
            <Plus size={14} className="shrink-0 text-content-tertiary" />
            <span className="flex-1 min-w-0 text-[13px] truncate">{t('ws_sel_new')}</span>
          </button>
        </div>
      )}

      <Modal
        open={newOpen}
        title={t('ws_sel_new_title')}
        onClose={() => setNewOpen(false)}
        footer={
          <>
            <Btn onClick={() => setNewOpen(false)}>{t('ws_sel_cancel')}</Btn>
            <Btn variant="primary" onClick={createProject} disabled={busy}>
              {t('ws_sel_create')}
            </Btn>
          </>
        }
      >
        <p className="text-xs text-content-tertiary">{t('ws_sel_new_subtitle')}</p>
        <TextInput
          autoFocus
          value={newName}
          onChange={(e) => {
            setNewName(e.target.value)
            setNewError('')
          }}
          onKeyDown={(e) => {
            if (e.key === 'Enter') createProject()
          }}
          placeholder={t('ws_sel_new_placeholder')}
        />
        {newError && <p className="text-xs text-danger">{newError}</p>}
      </Modal>
    </div>
  )
}

export default WorkspaceSelector
