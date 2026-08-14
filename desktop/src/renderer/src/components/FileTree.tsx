import React, { useCallback, useEffect, useRef, useState } from 'react'
import { Search, RotateCw, Home, ChevronRight, Loader2, AlertTriangle, FolderOpen } from 'lucide-react'
import { t } from '../i18n'
import apiClient from '../api/client'
import { useWorkspaceStore } from '../store/workspaceStore'
import { iconFor, colorFor, formatSize } from '../lib/fileKind'
import type { WorkspaceEntry } from '../types'

/** MIME type used to tell a workspace-file drag apart from an OS file drop. */
export const WORKSPACE_DRAG_TYPE = 'application/x-cow-workspace-file'

const FileTree: React.FC = () => {
  const preview = useWorkspaceStore((s) => s.preview)
  const current = useWorkspaceStore((s) => s.current)

  const sessionId = useWorkspaceStore((s) => s.sessionId)

  const [dir, setDir] = useState('')
  const [root, setRoot] = useState('')
  const [entries, setEntries] = useState<WorkspaceEntry[]>([])
  const [truncated, setTruncated] = useState(false)
  const [query, setQuery] = useState('')
  const [searching, setSearching] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const loadDir = useCallback(async (path: string) => {
    setLoading(true)
    setError(null)
    try {
      const data = await apiClient.workspaceTree(path, sessionId)
      setDir(data.path || '')
      setRoot(data.root || '')
      setEntries(data.entries || [])
      setTruncated(!!data.truncated)
      setSearching(false)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }, [sessionId])

  // Initial load, plus jumps requested elsewhere (e.g. clicking a directory
  // reference in a message). The counter also covers the case where the panel
  // was closed, so this component mounts with the request already pending.
  const browseDir = useWorkspaceStore((s) => s.browseDir)
  const browseSeq = useWorkspaceStore((s) => s.browseSeq)
  useEffect(() => {
    setQuery('')
    loadDir(browseSeq > 0 ? browseDir || '' : '')
  }, [browseSeq, browseDir, loadDir])

  // Debounce search so typing doesn't hammer the backend walk.
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  useEffect(() => {
    if (timerRef.current) clearTimeout(timerRef.current)
    if (!query.trim()) {
      if (searching) loadDir(dir)
      return
    }
    timerRef.current = setTimeout(async () => {
      setLoading(true)
      setError(null)
      try {
        const data = await apiClient.workspaceSearch(query, 60, sessionId)
        setEntries(data.results || [])
        setTruncated(false)
        setSearching(true)
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e))
      } finally {
        setLoading(false)
      }
    }, 220)
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current)
    }
    // `dir`/`searching` are read only to restore the listing when the query
    // clears; re-running on their change would fight the user's typing.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [query])

  const crumbs = dir.split('/').filter(Boolean)

  return (
    <div className="flex flex-col flex-1 min-h-0">
      <div className="flex items-center gap-1.5 px-2.5 py-2">
        <div className="flex-1 flex items-center gap-2 h-8 px-2.5 rounded-btn bg-inset">
          <Search size={12} className="text-content-tertiary shrink-0" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            spellCheck={false}
            placeholder={t('ws_search_placeholder')}
            className="flex-1 min-w-0 bg-transparent border-0 outline-none text-[13px] text-content placeholder:text-content-tertiary"
          />
        </div>
        <button
          onClick={() => {
            setQuery('')
            loadDir(dir)
          }}
          title={t('ws_refresh')}
          className="w-7 h-7 flex items-center justify-center rounded-btn text-content-tertiary hover:text-content hover:bg-surface-2 cursor-pointer transition-colors"
        >
          <RotateCw size={13} />
        </button>
      </div>

      {!searching && (
        <div className="flex items-center flex-wrap gap-0.5 px-3 pb-2 text-[11px] text-content-tertiary">
          <button
            onClick={() => loadDir('')}
            title={root}
            className="inline-flex items-center gap-1 px-1 py-0.5 rounded hover:bg-surface-2 hover:text-content cursor-pointer min-w-0"
          >
            <Home size={11} className="shrink-0" />
            {/* At the root, show the absolute root path so the user knows which
                directory (project or ~/cow) the panel is anchored to. */}
            {crumbs.length === 0 && root && (
              <span className="truncate max-w-[240px]">{root}</span>
            )}
          </button>
          {crumbs.map((part, i) => (
            <React.Fragment key={i}>
              <ChevronRight size={10} className="opacity-50" />
              <button
                onClick={() => loadDir(crumbs.slice(0, i + 1).join('/'))}
                className="px-1 py-0.5 rounded hover:bg-surface-2 hover:text-content cursor-pointer"
              >
                {part}
              </button>
            </React.Fragment>
          ))}
        </div>
      )}

      <div className="flex-1 min-h-0 overflow-y-auto px-1.5 pb-3">
        {loading ? (
          <div className="flex items-center justify-center py-8 text-content-tertiary">
            <Loader2 size={16} className="animate-spin" />
          </div>
        ) : error ? (
          <div className="flex flex-col items-center gap-2 py-8 text-content-tertiary text-[13px]">
            <AlertTriangle size={20} className="opacity-50" />
            <span>{error}</span>
          </div>
        ) : entries.length === 0 ? (
          <div className="flex flex-col items-center gap-2 py-8 text-content-tertiary text-[13px]">
            <FolderOpen size={20} className="opacity-40" />
            <span>{searching ? t('ws_no_results') : t('ws_empty_dir')}</span>
          </div>
        ) : (
          <>
            {entries.map((entry) => {
              const Icon = iconFor(entry.kind)
              const active = !entry.is_dir && current?.path === entry.path
              return (
                <div
                  key={entry.path}
                  draggable
                  onDragStart={(e) => {
                    e.dataTransfer.effectAllowed = 'copy'
                    e.dataTransfer.setData(WORKSPACE_DRAG_TYPE, JSON.stringify(entry))
                  }}
                  onClick={() => (entry.is_dir ? loadDir(entry.path) : preview(entry))}
                  className={`flex items-center gap-2.5 px-2 py-[7px] rounded-lg cursor-pointer select-none transition-colors ${
                    active ? 'bg-accent-soft' : 'hover:bg-surface-2'
                  }`}
                >
                  <Icon size={14} className={`shrink-0 ${colorFor(entry.kind)}`} />
                  <span className="flex-1 min-w-0 text-[13px] text-content truncate">{entry.name}</span>
                  <span className="shrink-0 text-[11px] text-content-tertiary max-w-[45%] truncate">
                    {searching ? entry.path : entry.is_dir ? '' : formatSize(entry.size)}
                  </span>
                </div>
              )
            })}
            {truncated && (
              <div className="px-2 py-3 text-center text-[11px] text-content-tertiary">
                {t('ws_truncated')}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}

export default FileTree
