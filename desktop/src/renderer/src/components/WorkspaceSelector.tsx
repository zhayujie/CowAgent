import React, { useCallback, useEffect, useRef, useState } from 'react'
import { FolderOpen, Folder, House, ChevronDown, Check, Plus } from 'lucide-react'
import { t } from '../i18n'
import apiClient from '../api/client'
import type { ProjectState } from '../types'
import { Modal, Btn, TextInput } from '../pages/settings/primitives'
import { useWorkspaceStore } from '../store/workspaceStore'
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
  const [menuOpen, setMenuOpen] = useState(false)
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

  // Close the menu on outside click.
  useEffect(() => {
    if (!menuOpen) return
    const onDown = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setMenuOpen(false)
    }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [menuOpen])

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
  }

  const selectProject = async (projectDir: string | null) => {
    setMenuOpen(false)
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
    setMenuOpen(false)
    const picked = await window.electronAPI?.selectDirectory?.()
    if (picked) await selectProject(picked)
  }

  const openNewDialog = () => {
    setMenuOpen(false)
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
    <div ref={rootRef} className="relative">
      <Tooltip label={fullPath || t('ws_sel_tip')}>
        <button
          type="button"
          onClick={() => setMenuOpen((v) => !v)}
          disabled={busy}
          className="flex-shrink-0 inline-flex items-center gap-1.5 pl-2 pr-2 py-0.5 rounded-btn text-xs text-content-secondary hover:text-accent hover:bg-accent-soft cursor-pointer transition-colors max-w-[240px] disabled:opacity-50"
        >
          <FolderOpen size={13} className="shrink-0" />
          <span className="truncate max-w-[190px]">{label}</span>
          <ChevronDown size={11} className="opacity-60 shrink-0" />
        </button>
      </Tooltip>

      {menuOpen && (
        <div className="absolute bottom-full left-0 mb-1.5 w-80 max-h-[380px] overflow-y-auto rounded-xl border border-default bg-elevated shadow-xl z-30 p-1.5">
          <div className="px-2.5 pt-1 pb-1.5 text-[11px] font-semibold uppercase tracking-wider text-content-tertiary">
            {t('ws_sel_title')}
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

          {recents.length > 0 && (
            <>
              <div className="my-1 h-px bg-default" />
              <div className="px-2.5 pt-1 pb-1.5 text-[11px] font-semibold uppercase tracking-wider text-content-tertiary">
                {t('ws_sel_recents')}
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
            </>
          )}

          <div className="my-1 h-px bg-default" />
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
