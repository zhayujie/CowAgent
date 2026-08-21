import React, { useEffect, useMemo, useRef, useState } from 'react'
import {
  Plus,
  MessageSquare,
  Pencil,
  Trash2,
  Check,
  X,
  History,
  Pin,
  ChevronDown,
  Folder,
  House,
  GripVertical,
} from 'lucide-react'
import { t, getLang } from '../i18n'
import { useSessionStore, DEFAULT_SPACE_KEY } from '../store/sessionStore'
import { useUIStore } from '../store/uiStore'
import { useWorkspaceStore } from '../store/workspaceStore'
import { usePlatform } from '../hooks/usePlatform'
import type { SessionItem } from '../types'
import apiClient from '../api/client'
import Tooltip from '../components/Tooltip'
import { Modal, Btn, TextInput } from '../pages/settings/primitives'

const COLLAPSED_KEY = 'cow_collapsed_projects'

function loadCollapsed(): Set<string> {
  try {
    const raw = localStorage.getItem(COLLAPSED_KEY)
    const arr = raw ? (JSON.parse(raw) as string[]) : []
    return new Set(Array.isArray(arr) ? arr : [])
  } catch {
    return new Set()
  }
}

function saveCollapsed(set: Set<string>) {
  localStorage.setItem(COLLAPSED_KEY, JSON.stringify([...set]))
}

function groupByTime(sessions: SessionItem[]): { key: string; label: string; items: SessionItem[] }[] {
  const now = new Date()
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime() / 1000
  const startOfYesterday = startOfToday - 86400

  const today: SessionItem[] = []
  const yesterday: SessionItem[] = []
  const earlier: SessionItem[] = []

  for (const s of sessions) {
    const ts = s.last_active || s.created_at
    if (ts >= startOfToday) today.push(s)
    else if (ts >= startOfYesterday) yesterday.push(s)
    else earlier.push(s)
  }

  return [
    { key: 'time:today', label: t('session_today'), items: today },
    { key: 'time:yesterday', label: t('session_yesterday'), items: yesterday },
    { key: 'time:earlier', label: t('session_earlier'), items: earlier },
  ].filter((g) => g.items.length > 0)
}

type SpaceGroup = {
  key: string
  label: string
  hint?: string
  isProject: boolean
  isDefault: boolean
  items: SessionItem[]
}

function buildGroups(
  sessions: SessionItem[],
  groupMode: 'project' | 'time',
  projectOrder: string[]
): SpaceGroup[] {
  if (groupMode === 'project') {
    const buckets = new Map<string, SpaceGroup>()
    for (const s of sessions) {
      const key = s.project?.path || DEFAULT_SPACE_KEY
      if (!buckets.has(key)) {
        buckets.set(key, {
          key,
          label: s.project?.name || t('ws_default_workspace'),
          hint: s.project?.path || '',
          isProject: true,
          isDefault: key === DEFAULT_SPACE_KEY,
          items: [],
        })
      }
      buckets.get(key)!.items.push(s)
    }
    const groups = Array.from(buckets.values())
    // Group order must be independent of the session array order: creating a
    // new chat unshifts a session to the top, which would otherwise float its
    // project group to the front. We rank by the user's saved projectOrder
    // first, then fall back to each group's "birth time" (its earliest session
    // created_at) — a stable key that an optimistic (now-timestamped) session
    // never changes. This preserves the manual drag order and keeps untouched
    // groups put.
    const rank = new Map(projectOrder.map((k, i) => [k, i]))
    const birth = new Map(
      groups.map((g) => [
        g.key,
        Math.min(...g.items.map((s) => s.created_at || s.last_active || 0)),
      ])
    )
    groups.sort((a, b) => {
      const ra = rank.has(a.key) ? rank.get(a.key)! : Infinity
      const rb = rank.has(b.key) ? rank.get(b.key)! : Infinity
      if (ra !== rb) return ra - rb
      // Neither (or both) in the saved order: oldest group first, stable.
      return (birth.get(a.key) ?? 0) - (birth.get(b.key) ?? 0)
    })
    return groups
  }

  const pinned = sessions.filter((s) => s.pinned)
  const rest = sessions.filter((s) => !s.pinned)
  const groups: SpaceGroup[] = []
  if (pinned.length) {
    groups.push({
      key: '__pinned__',
      label: t('session_pinned_group'),
      isProject: false,
      isDefault: false,
      items: pinned,
    })
  }
  for (const g of groupByTime(rest)) {
    groups.push({
      key: g.key,
      label: g.label,
      isProject: false,
      isDefault: false,
      items: g.items,
    })
  }
  return groups
}

const SessionList: React.FC = () => {
  const {
    sessions,
    activeId,
    loading,
    loadSessions,
    loadMore,
    hasMore,
    setActive,
    newSession,
    addOptimistic,
    rename,
    remove,
    togglePin,
    groupMode,
    projectOrder,
    reorderSpaces,
  } = useSessionStore()
  const toggleSessions = useUIStore((s) => s.toggleSessions)
  const setSessionsCollapsed = useUIStore((s) => s.setSessionsCollapsed)
  const navCollapsed = useUIStore((s) => s.navCollapsed)
  const reloadRoot = useWorkspaceStore((s) => s.reloadRoot)
  const openPanel = useWorkspaceStore((s) => s.openPanel)
  const { isMac } = usePlatform()
  const trafficOffset = isMac && navCollapsed ? 'ml-2' : ''
  const trafficDrop = isMac ? 'mt-1' : ''
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editValue, setEditValue] = useState('')
  const [collapsed, setCollapsed] = useState<Set<string>>(loadCollapsed)
  const [dragKey, setDragKey] = useState<string | null>(null)
  const [dropKey, setDropKey] = useState<string | null>(null)
  const [renameTarget, setRenameTarget] = useState<{ path: string; name: string } | null>(null)
  const [renameValue, setRenameValue] = useState('')
  const [deleteTarget, setDeleteTarget] = useState<{ path: string; name: string } | null>(null)
  const [deleteSessionTarget, setDeleteSessionTarget] = useState<SessionItem | null>(null)
  const [busy, setBusy] = useState(false)
  const activeRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    loadSessions(1)
  }, [loadSessions])

  // getLang() is included so group labels (e.g. the default-space name) rebuild
  // when the user switches language, since buildGroups resolves them via t().
  const groups = useMemo(
    () => buildGroups(sessions, groupMode, projectOrder),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [sessions, groupMode, projectOrder, getLang()]
  )

  // When several project groups are shown, indent their sessions so they read
  // as children of the project header (aligned with the folder icon above).
  const indentSessions = groupMode === 'project' && groups.length > 1

  const startEdit = (s: SessionItem) => {
    setEditingId(s.session_id)
    setEditValue(s.title || '')
  }

  const commitEdit = async () => {
    if (editingId && editValue.trim()) {
      await rename(editingId, editValue.trim())
    }
    setEditingId(null)
  }

  const toggleCollapse = (key: string) => {
    setCollapsed((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      saveCollapsed(next)
      return next
    })
  }

  const expandSpace = (key: string) => {
    setCollapsed((prev) => {
      if (!prev.has(key)) return prev
      const next = new Set(prev)
      next.delete(key)
      saveCollapsed(next)
      return next
    })
  }

  // Start a fresh conversation filed under a given space (a project path, or
  // null for the default workspace), triggered by the "+" on a group header.
  // Auto-expands the sidebar + group so the new session is immediately visible.
  const newChatInSpace = async (spaceKey: string) => {
    const id = newSession()
    setSessionsCollapsed(false)
    const isDefault = spaceKey === DEFAULT_SPACE_KEY
    const group = groups.find((g) => g.key === spaceKey)
    // Show the fresh (not-yet-persisted) session under its space right away.
    addOptimistic(
      id,
      isDefault ? null : { path: spaceKey, name: group?.label || spaceKey }
    )
    expandSpace(spaceKey)
    try {
      // Bind the new session to the space (default clears any binding) so it
      // stays under the right group once the list reloads.
      await apiClient.selectProject(id, isDefault ? null : spaceKey)
      openPanel('files')
      reloadRoot()
    } catch {
      /* transient; the optimistic item keeps the session visible locally */
    }
  }

  // Whenever the active session changes, make sure its group is expanded so the
  // user can see which conversation is selected (the row itself is highlighted
  // via isActive; scrolling into view is handled by the browser on focus).
  useEffect(() => {
    if (groupMode !== 'project') return
    const active = sessions.find((s) => s.session_id === activeId)
    if (!active) return
    const key = active.project?.path || DEFAULT_SPACE_KEY
    expandSpace(key)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeId, sessions, groupMode])

  // Scroll the active session into view after its group is expanded/rendered.
  // Depends on `sessions` too, so switching/creating a project (which inserts a
  // new group, often at the bottom) re-scrolls to the active session even
  // though activeId itself did not change. `center` makes a bottom group clearly
  // visible rather than just peeking above the fold.
  useEffect(() => {
    const el = activeRef.current
    if (!el) return
    const id = requestAnimationFrame(() => el.scrollIntoView({ block: 'center' }))
    return () => cancelAnimationFrame(id)
  }, [activeId, collapsed, sessions])

  const commitRename = async () => {
    if (!renameTarget) return
    const name = renameValue.trim()
    if (!name) return
    setBusy(true)
    try {
      const res = await apiClient.renameProject(renameTarget.path, name)
      if (res.status === 'success') {
        setRenameTarget(null)
        await loadSessions(1)
        useSessionStore.getState().bumpProjects()
      }
    } finally {
      setBusy(false)
    }
  }

  const commitDelete = async () => {
    if (!deleteTarget) return
    setBusy(true)
    try {
      const res = await apiClient.deleteProject(deleteTarget.path)
      if (res.status === 'success') {
        setDeleteTarget(null)
        await loadSessions(1)
        useSessionStore.getState().bumpProjects()
      }
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="w-[240px] flex-shrink-0 flex flex-col h-full bg-surface border-r border-default">
      <div className="flex items-center justify-between px-2 h-[44px] flex-shrink-0 titlebar-drag border-b border-default">
        <Tooltip label={t('session_history')}>
          <button
            onClick={toggleSessions}
            className={`titlebar-no-drag inline-flex items-center justify-center w-7 h-7 rounded-btn text-content-tertiary hover:text-content hover:bg-surface-2 cursor-pointer transition-colors ${trafficDrop} ${trafficOffset}`}
          >
            <History size={16} />
          </button>
        </Tooltip>
        <button
          onClick={() => {
            // Inherit the current session's project; fall back to default.
            const inherited = useSessionStore.getState().currentProject()
            const id = newSession()
            addOptimistic(id, inherited)
            expandSpace(inherited ? inherited.path : DEFAULT_SPACE_KEY)
            if (inherited) apiClient.selectProject(id, inherited.path).catch(() => {})
          }}
          className={`titlebar-no-drag inline-flex items-center gap-1.5 px-2.5 h-7 rounded-btn text-[12px] font-medium text-accent hover:bg-accent-soft cursor-pointer transition-colors ${trafficDrop}`}
        >
          <Plus size={15} />
          {t('session_new')}
        </button>
      </div>

      <div
        className="flex-1 overflow-y-auto px-2 pb-2 pt-1.5"
        onScroll={(e) => {
          const el = e.currentTarget
          if (el.scrollHeight - el.scrollTop - el.clientHeight < 80 && hasMore && !loading) loadMore()
        }}
      >
        {sessions.length === 0 && !loading && (
          <div className="flex flex-col items-center justify-center h-40 text-center px-4">
            <MessageSquare size={22} className="text-content-disabled mb-2" />
            <p className="text-xs text-content-tertiary">{t('session_empty')}</p>
          </div>
        )}

        {groups.map((group) => {
          const isCollapsed = group.isProject && collapsed.has(group.key)
          return (
            <div key={group.key} className="mb-1.5">
              {group.isProject ? (
                <div
                  draggable
                  onDragStart={(e) => {
                    setDragKey(group.key)
                    e.dataTransfer.effectAllowed = 'move'
                    e.dataTransfer.setData('text/plain', group.key)
                  }}
                  onDragEnd={() => {
                    setDragKey(null)
                    setDropKey(null)
                  }}
                  onDragOver={(e) => {
                    if (!dragKey || dragKey === group.key) return
                    e.preventDefault()
                    setDropKey(group.key)
                  }}
                  onDragLeave={() => {
                    if (dropKey === group.key) setDropKey(null)
                  }}
                  onDrop={(e) => {
                    e.preventDefault()
                    if (dragKey && dragKey !== group.key)
                      reorderSpaces(dragKey, group.key, groups.map((g) => g.key))
                    setDragKey(null)
                    setDropKey(null)
                  }}
                  onClick={() => toggleCollapse(group.key)}
                  title={group.hint}
                  className={`group/header relative flex items-center gap-1 px-1.5 h-7 rounded-btn cursor-grab active:cursor-grabbing select-none transition-colors ${
                    dragKey === group.key ? 'opacity-40' : ''
                  } ${
                    dropKey === group.key
                      ? 'bg-accent-soft before:absolute before:-top-[3px] before:left-1 before:right-1 before:h-[2px] before:rounded-full before:bg-accent'
                      : 'hover:bg-surface-2'
                  }`}
                >
                  {/* Grip hints that the header can be dragged to reorder. It
                      sits in the chevron's spot on hover so nothing shifts. */}
                  <span className="relative shrink-0 w-3 h-3">
                    <ChevronDown
                      size={12}
                      className={`absolute inset-0 text-content-tertiary transition-transform group-hover/header:opacity-0 ${
                        isCollapsed ? '-rotate-90' : ''
                      }`}
                    />
                    <GripVertical
                      size={12}
                      className="absolute inset-0 text-content-tertiary opacity-0 group-hover/header:opacity-100"
                    />
                  </span>
                  {group.isDefault ? (
                    <House size={12} className="shrink-0 text-content-tertiary" />
                  ) : (
                    <Folder size={12} className="shrink-0 text-content-tertiary" />
                  )}
                  <span className="flex-1 min-w-0 truncate text-[12px] font-medium text-content-secondary">
                    {group.label}
                  </span>
                  <span className="ml-auto text-[11px] text-content-disabled tabular-nums group-hover/header:invisible">
                    {group.items.length}
                  </span>
                  <span className="absolute right-1 top-1/2 -translate-y-1/2 hidden group-hover/header:flex items-center gap-0.5">
                    <IconBtn
                      onClick={(e) => {
                        e.stopPropagation()
                        newChatInSpace(group.key)
                      }}
                      title={t('project_new_chat')}
                    >
                      <Plus size={12} />
                    </IconBtn>
                    {!group.isDefault && (
                      <>
                        <IconBtn
                          onClick={(e) => {
                            e.stopPropagation()
                            setRenameTarget({ path: group.key, name: group.label })
                            setRenameValue(group.label)
                          }}
                          title={t('project_rename')}
                        >
                          <Pencil size={12} />
                        </IconBtn>
                        <IconBtn
                          onClick={(e) => {
                            e.stopPropagation()
                            setDeleteTarget({ path: group.key, name: group.label })
                          }}
                          title={t('project_delete')}
                          danger
                        >
                          <Trash2 size={12} />
                        </IconBtn>
                      </>
                    )}
                  </span>
                </div>
              ) : (
                <div className="px-2 pt-2 pb-1 text-[11px] font-medium uppercase tracking-wide text-content-disabled">
                  {group.label}
                </div>
              )}

              {!isCollapsed &&
                group.items.map((s) => {
                  const isActive = s.session_id === activeId
                  const isEditing = editingId === s.session_id
                  return (
                    <div
                      key={s.session_id}
                      ref={isActive ? activeRef : undefined}
                      onClick={() => !isEditing && setActive(s.session_id)}
                      className={`group relative flex items-center gap-1.5 pr-2 h-9 rounded-btn cursor-pointer transition-colors ${
                        indentSessions ? 'pl-[22px]' : 'pl-2'
                      } ${isActive ? 'bg-accent-soft' : 'hover:bg-surface-2'}`}
                    >
                      {isEditing ? (
                        <input
                          autoFocus
                          value={editValue}
                          onChange={(e) => setEditValue(e.target.value)}
                          onKeyDown={(e) => {
                            if (e.key === 'Enter') commitEdit()
                            if (e.key === 'Escape') setEditingId(null)
                          }}
                          onClick={(e) => e.stopPropagation()}
                          className="flex-1 min-w-0 bg-inset border border-strong rounded px-1.5 py-0.5 text-[13px] text-content focus:outline-none focus:border-accent"
                        />
                      ) : (
                        <span
                          className={`flex-1 min-w-0 truncate text-[13px] pr-5 group-hover:pr-0 ${
                            isActive ? 'text-accent font-medium' : 'text-content-secondary'
                          }`}
                        >
                          {s.title || s.session_id}
                        </span>
                      )}

                      {isEditing ? (
                        <div className="flex items-center gap-0.5">
                          <IconBtn
                            onClick={(e) => {
                              e.stopPropagation()
                              commitEdit()
                            }}
                          >
                            <Check size={13} />
                          </IconBtn>
                          <IconBtn
                            onClick={(e) => {
                              e.stopPropagation()
                              setEditingId(null)
                            }}
                          >
                            <X size={13} />
                          </IconBtn>
                        </div>
                      ) : (
                        <div className="hidden group-hover:flex items-center gap-0.5 shrink-0">
                          <IconBtn
                            onClick={(e) => {
                              e.stopPropagation()
                              togglePin(s.session_id)
                            }}
                            title={t(s.pinned ? 'unpin_session' : 'pin_session')}
                          >
                            <Pin
                              size={13}
                              className={s.pinned ? 'text-accent fill-accent' : ''}
                            />
                          </IconBtn>
                          <IconBtn
                            onClick={(e) => {
                              e.stopPropagation()
                              startEdit(s)
                            }}
                            title={t('session_rename')}
                          >
                            <Pencil size={13} />
                          </IconBtn>
                          <IconBtn
                            onClick={(e) => {
                              e.stopPropagation()
                              setDeleteSessionTarget(s)
                            }}
                            title={t('session_delete')}
                            danger
                          >
                            <Trash2 size={13} />
                          </IconBtn>
                        </div>
                      )}
                      {s.pinned && !isEditing && (
                        <Pin
                          size={11}
                          className="absolute right-2 top-1/2 -translate-y-1/2 text-accent fill-accent pointer-events-none group-hover:hidden"
                        />
                      )}
                    </div>
                  )
                })}
            </div>
          )
        })}

        {loading && (
          <div className="px-2 py-2 space-y-2">
            {Array.from({ length: 4 }).map((_, i) => (
              <div key={i} className="skeleton h-7 w-full" />
            ))}
          </div>
        )}
      </div>

      <Modal
        open={!!renameTarget}
        title={t('project_rename_title')}
        onClose={() => setRenameTarget(null)}
        footer={
          <>
            <Btn onClick={() => setRenameTarget(null)}>{t('ws_sel_cancel')}</Btn>
            <Btn variant="primary" onClick={commitRename} disabled={busy || !renameValue.trim()}>
              {t('config_save')}
            </Btn>
          </>
        }
      >
        <TextInput
          autoFocus
          value={renameValue}
          onChange={(e) => setRenameValue(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') commitRename()
          }}
          maxLength={100}
        />
      </Modal>

      <Modal
        open={!!deleteTarget}
        title={t('project_delete_title')}
        onClose={() => setDeleteTarget(null)}
        footer={
          <>
            <Btn onClick={() => setDeleteTarget(null)}>{t('ws_sel_cancel')}</Btn>
            <Btn variant="danger" onClick={commitDelete} disabled={busy}>
              {t('project_delete')}
            </Btn>
          </>
        }
      >
        <p className="text-sm text-content-secondary">
          {t('project_delete_confirm').replace('{name}', deleteTarget?.name || '')}
        </p>
      </Modal>

      <Modal
        open={!!deleteSessionTarget}
        title={t('session_delete_title')}
        onClose={() => setDeleteSessionTarget(null)}
        footer={
          <>
            <Btn onClick={() => setDeleteSessionTarget(null)}>{t('ws_sel_cancel')}</Btn>
            <Btn
              variant="danger"
              onClick={async () => {
                if (deleteSessionTarget) await remove(deleteSessionTarget.session_id)
                setDeleteSessionTarget(null)
              }}
            >
              {t('session_delete')}
            </Btn>
          </>
        }
      >
        <p className="text-sm text-content-secondary">
          {t('session_delete_confirm').replace(
            '{name}',
            deleteSessionTarget?.title || deleteSessionTarget?.session_id || ''
          )}
        </p>
      </Modal>
    </div>
  )
}

const IconBtn: React.FC<{
  onClick: (e: React.MouseEvent) => void
  title?: string
  danger?: boolean
  children: React.ReactNode
}> = ({ onClick, title, danger, children }) => {
  const btn = (
    <button
      onClick={onClick}
      className={`inline-flex items-center justify-center w-6 h-6 rounded cursor-pointer transition-colors text-content-tertiary ${
        danger ? 'hover:text-danger hover:bg-danger-soft' : 'hover:text-content hover:bg-surface'
      }`}
    >
      {children}
    </button>
  )
  return title ? <Tooltip label={title}>{btn}</Tooltip> : btn
}

export default SessionList
