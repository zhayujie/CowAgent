import React, { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Eye, FolderTree, ExternalLink, Download, Link2, Check, X,
  Pencil, Save, RotateCcw, Loader2, AlertTriangle, Layers, FolderOpen,
} from 'lucide-react'
import { t } from '../i18n'
import apiClient from '../api/client'
import FilePreview from './FilePreview'
import FileEditor from './FileEditor'
import FileTree from './FileTree'
import Tooltip from './Tooltip'
import { isEditable } from '../lib/fileKind'
import { useWorkspaceStore, WS_MIN_WIDTH } from '../store/workspaceStore'
import { focusProduced } from '../store/artifactStore'
import { usePlatform } from '../hooks/usePlatform'

const TabButton: React.FC<{
  active: boolean
  onClick: () => void
  icon: React.ReactNode
  label: string
}> = ({ active, onClick, icon, label }) => (
  <button
    onClick={onClick}
    className={`inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-btn text-[13px] font-medium cursor-pointer transition-colors ${
      active ? 'bg-accent-soft text-accent' : 'text-content-tertiary hover:text-content hover:bg-surface-2'
    }`}
  >
    {icon}
    {label}
  </button>
)

const IconButton: React.FC<{ onClick: () => void; title: string; children: React.ReactNode }> = ({
  onClick,
  title,
  children,
}) => (
  <Tooltip label={title} placement="bottom">
    <button
      onClick={onClick}
      aria-label={title}
      className="w-7 h-7 flex items-center justify-center rounded-btn text-content-tertiary hover:text-content hover:bg-surface-2 cursor-pointer transition-colors"
    >
      {children}
    </button>
  </Tooltip>
)

const WorkspacePanel: React.FC = () => {
  const navigate = useNavigate()
  const { isMac } = usePlatform()
  const { open, tab, width, current, previewError, edit, editNotice } = useWorkspaceStore()
  const dismissEditNotice = useWorkspaceStore((s) => s.dismissEditNotice)
  const setTab = useWorkspaceStore((s) => s.setTab)
  const setWidth = useWorkspaceStore((s) => s.setWidth)
  const closePanel = useWorkspaceStore((s) => s.closePanel)
  const startEdit = useWorkspaceStore((s) => s.startEdit)
  const saveEdit = useWorkspaceStore((s) => s.saveEdit)
  const cancelEdit = useWorkspaceStore((s) => s.cancelEdit)
  const [copied, setCopied] = useState(false)
  // Dragging the divider over the preview iframe would otherwise lose the
  // mousemove stream to the iframe's document.
  const [resizing, setResizing] = useState(false)
  const editorRef = useRef<HTMLTextAreaElement>(null)
  const widthRef = useRef(width)
  widthRef.current = width

  const startResize = useCallback(
    (e: React.MouseEvent) => {
      e.preventDefault()
      const startX = e.clientX
      const startWidth = widthRef.current
      setResizing(true)
      const onMove = (ev: MouseEvent) => {
        setWidth(Math.min(window.innerWidth * 0.7, Math.max(WS_MIN_WIDTH, startWidth + startX - ev.clientX)))
      }
      const onUp = () => {
        setResizing(false)
        document.removeEventListener('mousemove', onMove)
        document.removeEventListener('mouseup', onUp)
      }
      document.addEventListener('mousemove', onMove)
      document.addEventListener('mouseup', onUp)
    },
    [setWidth]
  )

  // Both are about the file on screen, so opening another one retires them.
  useEffect(() => {
    setCopied(false)
    dismissEditNotice()
  }, [current?.path, dismissEditNotice])

  if (!open) return null

  const onFile = tab === 'preview' && !!current
  const editing = onFile && !!edit
  // While editing, the viewer actions would act on the file on disk rather than
  // on what is in the text area, which reads as a bug. Hide them instead.
  const showFileActions = onFile && !editing
  const showEditButton = showFileActions && !current.is_dir && isEditable(current.kind)
  const canReveal = showFileActions && !!current.abs_path && !!window.electronAPI?.revealPath && !apiClient.isRemote()

  const openExternally = () => {
    if (!current) return
    // Desktop can hand the file to the OS default app; fall back to the browser.
    if (current.abs_path && window.electronAPI?.openPath && !apiClient.isRemote()) {
      window.electronAPI.openPath(current.abs_path)
      return
    }
    window.open(apiClient.getPreviewUrl(current.preview_url || ''), '_blank')
  }

  const viewInArtifacts = () => {
    if (!current?.origin || !current.abs_path) return
    focusProduced({
      abs_path: current.abs_path,
      file_name: current.name,
      rel_path: current.path,
      kind: current.kind,
      size: current.size,
      raw_url: current.raw_url,
      preview_url: current.preview_url,
      previewable: current.previewable,
      origin: current.origin,
    })
    navigate('/artifacts')
  }

  const download = () => {
    if (!current) return
    window.open(apiClient.getFileUrl(current.raw_url || current.preview_url || ''), '_blank')
  }

  const copyPath = () => {
    if (!current) return
    navigator.clipboard.writeText(current.abs_path || current.path)
    setCopied(true)
    setTimeout(() => setCopied(false), 1600)
  }

  return (
    <aside
      // Cap against the viewport so a width remembered on a large window
      // can't crowd out the chat on a smaller one.
      style={{ width, maxWidth: '70vw' }}
      className="relative shrink-0 h-full flex border-l border-default bg-base"
    >
      <div
        onMouseDown={startResize}
        className="absolute -left-[3px] top-0 bottom-0 w-1.5 cursor-col-resize z-20 hover:bg-accent/30"
      />

      <div className="flex-1 min-w-0 flex flex-col">
        <div className="h-[44px] shrink-0 flex items-center justify-between gap-2 pl-2.5 pr-1.5 border-b border-default">
          <div className="flex items-center gap-0.5">
            <TabButton
              active={tab === 'preview'}
              onClick={() => setTab('preview')}
              icon={<Eye size={13} />}
              label={t('ws_tab_preview')}
            />
            <TabButton
              active={tab === 'files'}
              onClick={() => setTab('files')}
              icon={<FolderTree size={13} />}
              label={t('ws_tab_files')}
            />
          </div>
          <div className="flex items-center gap-0.5">
            {editing && (
              <>
                <IconButton
                  // Never fall back to '' for a missing text area: that would
                  // write an empty file over the user's content.
                  onClick={() => {
                    const el = editorRef.current
                    if (el) saveEdit(el.value)
                  }}
                  title={t('ws_edit_save')}
                >
                  {edit.saving ? <Loader2 size={13} className="animate-spin" /> : <Save size={13} />}
                </IconButton>
                <IconButton onClick={cancelEdit} title={t('ws_edit_cancel')}>
                  <RotateCcw size={13} />
                </IconButton>
              </>
            )}
            {showEditButton && (
              <IconButton onClick={startEdit} title={t('ws_edit')}>
                <Pencil size={13} />
              </IconButton>
            )}
            {/* Only files a conversation produced have a place in the artifacts view. */}
            {showFileActions && current.origin && current.abs_path && (
              <IconButton onClick={viewInArtifacts} title={t('artifacts_view_in')}>
                <Layers size={13} />
              </IconButton>
            )}
            {showFileActions && (
              <>
                <IconButton onClick={openExternally} title={t('ws_open_external')}>
                  <ExternalLink size={13} />
                </IconButton>
                {canReveal && (
                  <IconButton
                    onClick={() => void window.electronAPI?.revealPath?.(current.abs_path!)}
                    title={t(isMac ? 'ws_reveal_mac' : 'ws_reveal')}
                  >
                    <FolderOpen size={13} />
                  </IconButton>
                )}
                <IconButton onClick={download} title={t('ws_download')}>
                  <Download size={13} />
                </IconButton>
                <IconButton onClick={copyPath} title={t('ws_copy_path')}>
                  {copied ? <Check size={13} /> : <Link2 size={13} />}
                </IconButton>
              </>
            )}
            <IconButton onClick={() => closePanel(true)} title={t('ws_close')}>
              <X size={14} />
            </IconButton>
          </div>
        </div>

        {/* Both tabs stay mounted so the file tree keeps its scroll position
            and loaded directory when the user flips to a preview and back. */}
        <div className={`flex-1 min-h-0 flex-col ${tab === 'preview' ? 'flex' : 'hidden'}`}>
          {current && (
            <div className="shrink-0 px-3 py-2 text-[11px] font-mono text-content-tertiary border-b border-default break-all">
              {current.path}
              {edit?.dirty && <span className="text-accent" title={t('ws_edit_unsaved')}> •</span>}
            </div>
          )}
          {editNotice && !edit && (
            <div className="shrink-0 flex items-start gap-1.5 px-3 py-2 text-[12px] text-amber-600 bg-amber-500/10 border-b border-default">
              <AlertTriangle size={13} className="mt-0.5 shrink-0" />
              <span className="flex-1 break-all">{editNotice}</span>
              <button
                onClick={dismissEditNotice}
                title={t('ws_close')}
                className="shrink-0 opacity-60 hover:opacity-100 cursor-pointer"
              >
                <X size={13} />
              </button>
            </div>
          )}
          <div
            // The editor manages its own scrolling; letting this wrapper scroll
            // too would stop the text area from filling the panel.
            className={`flex-1 min-h-0 ${editing ? 'overflow-hidden' : 'overflow-auto'}`}
            style={resizing ? { pointerEvents: 'none' } : undefined}
          >
            {edit ? (
              // Keyed so switching the edited file remounts the text area and
              // reseeds it, instead of keeping the previous file's text.
              <FileEditor key={edit.file.path} edit={edit} textareaRef={editorRef} />
            ) : (
              <FilePreview file={current} error={previewError} />
            )}
          </div>
        </div>

        <div className={`flex-1 min-h-0 flex-col ${tab === 'files' ? 'flex' : 'hidden'}`}>
          <FileTree />
        </div>
      </div>
    </aside>
  )
}

export default WorkspacePanel
