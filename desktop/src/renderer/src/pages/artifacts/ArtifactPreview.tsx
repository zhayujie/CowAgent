import React, { useEffect, useMemo, useRef, useState } from 'react'
import {
  Plus, MessageSquare, ListPlus, ExternalLink, FolderOpen, Download, EyeOff, X, Pencil, FileX, Loader2,
} from 'lucide-react'
import { t } from '../../i18n'
import apiClient from '../../api/client'
import Tooltip from '../../components/Tooltip'
import AgentAvatar from '../../components/AgentAvatar'
import FilePreview from '../../components/FilePreview'
import { formatSize } from '../../lib/fileKind'
import { MENU_KINDS, MENU_TITLE_MAX, newMenuId } from '../../lib/menu'
import { usePlatform } from '../../hooks/usePlatform'
import { findAgent, selectMultiAgent, useAgentStore } from '../../store/agentStore'
import { useMenuStore } from '../../store/menuStore'
import { useArtifactStore, artName, ART_TITLE_MAX, type ArtifactShown } from '../../store/artifactStore'
import { downloadArtifact } from './ArtifactCard'
import { dateTime } from './format'
import type { WorkspaceEntry } from '../../types'

const HeadButton: React.FC<{
  label: string
  onClick: () => void
  disabled?: boolean
  className?: string
  children: React.ReactNode
}> = ({ label, onClick, disabled, className = '', children }) => (
  <Tooltip label={label} placement="bottom">
    <button
      type="button"
      onClick={disabled ? undefined : onClick}
      aria-disabled={disabled || undefined}
      className={`w-7 h-7 flex items-center justify-center rounded-btn transition-colors ${
        disabled
          ? 'text-content-tertiary opacity-40 cursor-default'
          : 'text-content-tertiary hover:text-content hover:bg-surface-2 cursor-pointer'
      } ${className}`}
    >
      {children}
    </button>
  </Tooltip>
)

/** The title, edited in place: Enter or leaving the field saves, Esc cancels. */
const NameField: React.FC<{ item: ArtifactShown }> = ({ item }) => {
  const rename = useArtifactStore((s) => s.rename)
  const [editing, setEditing] = useState(false)
  const settled = useRef(false)
  const name = artName(item)

  useEffect(() => setEditing(false), [item.id])

  if (item.id == null) return <div className="art-preview-name">{name}</div>

  if (editing) {
    const finish = (save: boolean, value: string) => {
      if (settled.current) return
      settled.current = true
      setEditing(false)
      if (save) void rename(item, value)
    }
    return (
      <div className="art-preview-name">
        <input
          autoFocus
          className="art-name-input"
          maxLength={ART_TITLE_MAX}
          defaultValue={name}
          placeholder={item.file_name}
          aria-label={t('artifacts_rename')}
          spellCheck={false}
          onFocus={(e) => e.currentTarget.select()}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.nativeEvent.isComposing) {
              e.preventDefault()
              finish(true, e.currentTarget.value)
            } else if (e.key === 'Escape') {
              e.preventDefault()
              finish(false, '')
            }
          }}
          onBlur={(e) => finish(true, e.currentTarget.value)}
        />
      </div>
    )
  }

  return (
    <div className="art-preview-name">
      <button
        type="button"
        className="art-name-btn"
        aria-label={t('artifacts_rename')}
        onClick={() => {
          settled.current = false
          setEditing(true)
        }}
      >
        <span className="truncate">{name}</span>
        <Pencil size={11} />
      </button>
    </div>
  )
}

interface ArtifactPreviewProps {
  item: ArtifactShown
  onJump: (item: ArtifactShown) => void
  /** Set while the divider is dragged, so the preview's iframe doesn't swallow the pointer. */
  resizing: boolean
}

const ArtifactPreview: React.FC<ArtifactPreviewProps> = ({ item, onJump, resizing }) => {
  const { isMac } = usePlatform()
  const multiAgent = useAgentStore(selectMultiAgent)
  const adding = useArtifactStore((s) => s.adding)
  const { add, remove, closePreview, flash } = useArtifactStore.getState()

  const entry = useMemo<WorkspaceEntry>(
    () => ({
      name: item.file_name,
      path: item.rel_path,
      is_dir: false,
      kind: item.kind,
      previewable: item.previewable,
      size: item.size,
      mtime: 0,
      abs_path: item.abs_path,
      raw_url: item.raw_url,
      preview_url: item.preview_url,
    }),
    [item.file_name, item.rel_path, item.kind, item.previewable, item.size, item.abs_path, item.raw_url, item.preview_url]
  )

  const canAdd = item.id == null && item.exists && !!item.origin?.session_id
  const canMenu = item.exists && MENU_KINDS.has(item.kind)
  const canReveal = item.exists && !!item.abs_path && !!window.electronAPI?.revealPath && !apiClient.isRemote()

  const openExternally = async () => {
    // The desktop hands the file to the system app; the browser is the fallback.
    if (item.abs_path && window.electronAPI?.openPath && !apiClient.isRemote()) {
      const err = await window.electronAPI.openPath(item.abs_path)
      if (err) flash(err)
      return
    }
    window.open(apiClient.getPreviewUrl(item.preview_url || item.raw_url), '_blank')
  }

  /** Open the menu editor with this file placed in it, or pointed out if it is there already. */
  const addToMenu = () => {
    const { doc, openEditor } = useMenuStore.getState()
    const existing = doc.groups.flatMap((g) => g.items).find((i) => i.type === 'artifact' && i.path === item.abs_path)
    if (existing) {
      openEditor({ focus: existing.id })
      return
    }
    openEditor({
      add: {
        id: newMenuId('m_'),
        type: 'artifact',
        path: item.abs_path,
        icon: '',
        title: artName(item).slice(0, MENU_TITLE_MAX),
        file: {
          kind: item.kind,
          exists: true,
          file_name: item.file_name,
          preview_url: item.preview_url,
          raw_url: item.raw_url,
        },
      },
    })
  }

  const agent = multiAgent && item.agent_id ? findAgent(item.agent_id) : undefined
  const meta: React.ReactNode[] = []
  if (multiAgent && item.agent_id) {
    meta.push(
      <span key="agent" className="art-meta-item">
        <AgentAvatar agent={agent || null} size={16} />
        <span>{agent?.name || item.agent_name || item.agent_id}</span>
      </span>
    )
  }
  if (item.session_id) {
    const title = item.session_title || t('artifacts_untitled')
    meta.push(
      item.can_jump ? (
        <button key="session" type="button" className="art-meta-item art-meta-link" onClick={() => onJump(item)}>
          <MessageSquare size={11} />
          <span>{title}</span>
        </button>
      ) : (
        <span key="session" className="art-meta-item">
          <MessageSquare size={11} />
          <span>{title}</span>
        </span>
      )
    )
  }
  if (item.updated_at) meta.push(<span key="time" className="art-meta-item">{dateTime(item.updated_at)}</span>)
  if (item.size) meta.push(<span key="size" className="art-meta-item">{formatSize(item.size)}</span>)

  return (
    <>
      <div className="art-preview-head">
        <div className="flex-1 min-w-0">
          <NameField item={item} />
          <div className="art-preview-path" title={item.abs_path}>
            {item.rel_path}
          </div>
        </div>
        <div className="flex items-center gap-0.5 shrink-0">
          {canAdd && (
            <HeadButton label={t('artifacts_add')} onClick={() => void add(item)} className="art-add-btn">
              {adding ? <Loader2 size={14} className="animate-spin" /> : <Plus size={15} />}
            </HeadButton>
          )}
          {item.id != null && (
            <HeadButton
              label={t(item.can_jump ? 'artifacts_jump' : 'artifacts_jump_unavailable')}
              disabled={!item.can_jump}
              onClick={() => onJump(item)}
            >
              <MessageSquare size={14} />
            </HeadButton>
          )}
          {canMenu && (
            <HeadButton label={t('menu_add_to_menu')} onClick={addToMenu}>
              <ListPlus size={15} />
            </HeadButton>
          )}
          {item.exists && (
            <HeadButton label={t('ws_open_external')} onClick={() => void openExternally()}>
              <ExternalLink size={14} />
            </HeadButton>
          )}
          {canReveal && (
            <HeadButton
              label={t(isMac ? 'ws_reveal_mac' : 'ws_reveal')}
              onClick={() => void window.electronAPI?.revealPath?.(item.abs_path)}
            >
              <FolderOpen size={14} />
            </HeadButton>
          )}
          {item.exists && (
            <HeadButton label={t('ws_download')} onClick={() => downloadArtifact(item)}>
              <Download size={14} />
            </HeadButton>
          )}
          {item.id != null && (
            <HeadButton label={t('artifacts_remove')} onClick={() => void remove(item)}>
              <EyeOff size={14} />
            </HeadButton>
          )}
          <span className="art-preview-sep" />
          <HeadButton label={t('ws_close')} onClick={closePreview}>
            <X size={15} />
          </HeadButton>
        </div>
      </div>

      <div className="flex-1 min-h-0 overflow-auto" style={resizing ? { pointerEvents: 'none' } : undefined}>
        {item.exists ? (
          <FilePreview file={entry} />
        ) : (
          <div className="h-full flex flex-col items-center justify-center gap-2.5 text-content-tertiary text-[13px]">
            <FileX size={24} className="opacity-50" />
            <span>{t('artifacts_missing')}</span>
          </div>
        )}
      </div>

      {meta.length > 0 && <div className="art-preview-meta">{meta}</div>}
    </>
  )
}

export default ArtifactPreview
