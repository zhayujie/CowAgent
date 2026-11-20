import React from 'react'
import { useNavigate } from 'react-router-dom'
import { Eye, Download, Layers } from 'lucide-react'
import { t } from '../i18n'
import apiClient from '../api/client'
import Tooltip from './Tooltip'
import { useWorkspaceStore } from '../store/workspaceStore'
import { useSessionStore } from '../store/sessionStore'
import { focusProduced } from '../store/artifactStore'
import { iconFor, colorFor, formatSize, kindOf, PREVIEWABLE_KINDS } from '../lib/fileKind'
import type { Artifact, ArtifactOrigin, WorkspaceEntry } from '../types'

/** Partial artifact: history-rebuilt cards only know the path. */
export type FileCardMeta = Pick<Artifact, 'file_name' | 'rel_path'> & Partial<Artifact>

interface FileCardProps {
  meta: FileCardMeta
  /** Seq of the question whose turn wrote the file; null while it isn't persisted. */
  turnSeq?: number | null
  /** Open the file with the system app when the backend won't serve it
   *  (outside its allowed roots) and runs on this machine. */
  openLocallyIfDenied?: boolean
}

const action =
  'w-6 h-6 flex items-center justify-center rounded-md text-content-tertiary hover:text-content hover:bg-surface transition-colors'

const FileCard: React.FC<FileCardProps> = ({ meta, turnSeq = null, openLocallyIfDenied = false }) => {
  const navigate = useNavigate()
  const preview = useWorkspaceStore((s) => s.preview)
  const kind = meta.kind || kindOf(meta.file_name)
  const Icon = iconFor(kind)
  const canPreview = meta.previewable ?? PREVIEWABLE_KINDS.has(kind)
  // Only show the path when it says more than the file name already does.
  const sub = [meta.rel_path === meta.file_name ? '' : meta.rel_path, formatSize(meta.size)]
    .filter(Boolean)
    .join(' · ')

  // Where the card sits, so the artifacts view can attribute the file to this
  // turn if it has to index it again.
  const origin = (): ArtifactOrigin => ({
    session_id: useSessionStore.getState().activeId,
    agent_id: '',
    turn_seq: turnSeq,
  })

  // The file is on this machine's disk, so the system can still reach it when
  // the backend won't serve it.
  const localPath =
    openLocallyIfDenied && meta.abs_path && window.electronAPI?.openPath && apiClient.isLoopbackBackend()
      ? meta.abs_path
      : null

  /** The backend's entry for the file; undefined when it won't serve it. */
  const served = async (): Promise<WorkspaceEntry | undefined> => {
    try {
      return (await apiClient.workspaceResolve(meta.abs_path || meta.rel_path, useWorkspaceStore.getState().sessionId)).file
    } catch {
      return undefined
    }
  }

  const resolved = async (): Promise<FileCardMeta> => {
    if (meta.abs_path && meta.raw_url && meta.preview_url) return meta
    const file = await served()
    if (!file) throw new Error('file not served')
    return { ...meta, abs_path: file.abs_path, raw_url: file.raw_url, preview_url: file.preview_url, size: file.size }
  }

  const open = async () => {
    if (localPath && !meta.preview_url) {
      const file = await served()
      if (file) preview(file, { origin: origin() })
      else void window.electronAPI!.openPath(localPath)
      return
    }
    preview(meta.preview_url ? (meta as Artifact) : meta.abs_path || meta.rel_path, { origin: origin() })
  }

  const download = async (e: React.MouseEvent) => {
    e.stopPropagation()
    let url = meta.raw_url
    if (!url) {
      try {
        url = (await resolved()).raw_url
      } catch {
        if (localPath) void window.electronAPI?.revealPath?.(localPath)
        return
      }
    }
    window.open(apiClient.getFileUrl(url!), '_blank')
  }

  const viewInArtifacts = async (e: React.MouseEvent) => {
    e.stopPropagation()
    let file = meta
    try {
      file = await resolved()
    } catch {
      // The artifacts view couldn't preview it either.
      if (localPath) {
        void window.electronAPI!.openPath(localPath)
        return
      }
      /* the view looks the file up by path, or shows what the card knows */
    }
    if (!file.abs_path) return
    focusProduced({ ...file, abs_path: file.abs_path, kind, origin: origin() })
    navigate('/artifacts')
  }

  return (
    <div
      onClick={open}
      data-artifact-path={meta.abs_path || undefined}
      className="group/card inline-flex items-center gap-2.5 max-w-full mt-2 px-3 py-2 rounded-xl border border-default bg-surface-2 cursor-pointer hover:border-accent transition-colors"
    >
      <Icon size={16} className={`shrink-0 ${colorFor(kind)}`} />
      <div className="min-w-0 flex-1">
        <div className="text-[13px] font-medium text-content truncate">{meta.file_name}</div>
        {sub && <div className="text-[11px] text-content-tertiary truncate">{sub}</div>}
      </div>
      <div className="flex items-center gap-0.5 shrink-0">
        {canPreview && (
          <Tooltip label={t('ws_preview')}>
            <span className={action}>
              <Eye size={12} />
            </span>
          </Tooltip>
        )}
        <Tooltip label={t('ws_download')}>
          <span onClick={download} className={action}>
            <Download size={12} />
          </span>
        </Tooltip>
        <Tooltip label={t('artifacts_view_in')}>
          <span onClick={viewInArtifacts} className={action}>
            <Layers size={12} />
          </span>
        </Tooltip>
      </div>
    </div>
  )
}

export default FileCard
