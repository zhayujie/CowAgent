import React, { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { BookOpen, FileUp, FolderOpen, Loader2, Sparkles } from 'lucide-react'
import { Modal } from '../pages/settings/primitives'
import type { ThemeImportResult } from '../types'
import { getLang, t, tf } from '../i18n'
import { product } from '@product'
import { guardDocEditors } from '../store/docEditorStore'
import { useWorkspaceStore } from '../store/workspaceStore'
import { prefillChatInput } from '../store/draftStore'
import { startNewChat } from '../lib/newChat'

const themesDocsUrl = () =>
  `${getLang() === 'zh' ? 'https://docs.cowagent.ai/zh' : 'https://docs.cowagent.ai'}/extensions/custom-theme`

// "Custom theme" dialog: import a package (drop a .zip / folder, or pick one) or
// hand off to the Agent with a ready-made prompt to design a new theme.
const ThemeAddModal: React.FC<{
  open: boolean
  onClose: () => void
  onImport: (path?: string) => Promise<ThemeImportResult>
  onOpenDir: () => void
}> = ({ open, onClose, onImport, onOpenDir }) => {
  const navigate = useNavigate()
  const zoneRef = useRef<HTMLDivElement>(null)
  const [busy, setBusy] = useState(false)
  const [dragOver, setDragOver] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!open) return
    setBusy(false)
    setDragOver(false)
    setError('')
    // While open, file drags anywhere but the drop zone are inert, so they
    // can't reach the chat input's window-wide attachment drop.
    const guard = (e: DragEvent) => {
      if (zoneRef.current?.contains(e.target as Node)) return
      e.preventDefault()
      e.stopPropagation()
      if (e.dataTransfer) e.dataTransfer.dropEffect = 'none'
    }
    const types = ['dragenter', 'dragover', 'drop'] as const
    for (const type of types) window.addEventListener(type, guard, true)
    return () => {
      for (const type of types) window.removeEventListener(type, guard, true)
    }
  }, [open])

  const runImport = async (path?: string) => {
    if (busy) return
    setBusy(true)
    setError('')
    try {
      const res = await onImport(path)
      if (res.status === 'ok') onClose()
      else if (res.status === 'error') setError(t(`theme_import_err_${res.code}`))
    } catch {
      setError(t('theme_import_err_failed'))
    } finally {
      setBusy(false)
    }
  }

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setDragOver(false)
    const file = e.dataTransfer.files[0]
    if (!file || busy) return
    const path = window.electronAPI?.getPathForFile?.(file) || ''
    if (path) void runImport(path)
    else setError(t('theme_import_err_failed'))
  }

  const stopDrag = (e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
  }

  const askAgent = async () => {
    if (!(await guardDocEditors())) return
    if (!(await useWorkspaceStore.getState().guardUnsavedEdit())) return
    const dir = (await window.electronAPI?.getThemesDir?.()) || '~/cow/system/themes'
    onClose()
    startNewChat()
    prefillChatInput(tf('theme_agent_prompt', { dir }))
    navigate('/')
  }

  return (
    <Modal
      open={open}
      title={t('theme_add_title')}
      onClose={onClose}
      footer={
        <div className="flex w-full items-center gap-4 text-xs">
          <FooterLink icon={<FolderOpen size={13} />} label={t('theme_open_dir')} onClick={onOpenDir} />
          {!product.nav?.hideExternalLinks && (
            <FooterLink
              icon={<BookOpen size={13} />}
              label={t('theme_docs')}
              onClick={() => window.open(themesDocsUrl(), '_blank', 'noopener,noreferrer')}
            />
          )}
        </div>
      }
    >
      <div
        ref={zoneRef}
        role="button"
        tabIndex={0}
        onClick={() => void runImport()}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault()
            void runImport()
          }
        }}
        onDragEnter={(e) => {
          stopDrag(e)
          if (!busy) setDragOver(true)
        }}
        onDragOver={stopDrag}
        onDragLeave={(e) => {
          stopDrag(e)
          if (!zoneRef.current?.contains(e.relatedTarget as Node)) setDragOver(false)
        }}
        onDrop={onDrop}
        className={`flex flex-col items-center justify-center px-4 py-8 rounded-card border-[1.5px] border-dashed text-center outline-none transition-colors ${
          busy ? 'cursor-default' : 'cursor-pointer'
        } ${dragOver ? 'border-accent bg-accent-soft' : 'border-strong bg-inset hover:border-accent focus-visible:border-accent'}`}
      >
        <div className="w-11 h-11 mb-3 rounded-card border border-default bg-surface flex items-center justify-center">
          {busy ? (
            <Loader2 size={18} className="animate-spin text-accent" />
          ) : (
            <FileUp size={18} className={dragOver ? 'text-accent' : 'text-content-tertiary'} />
          )}
        </div>
        <p className="text-sm text-content-secondary">
          {busy ? (
            t('theme_importing')
          ) : (
            <>
              {t('theme_drop_hint')} <span className="text-accent font-medium">{t('theme_drop_pick')}</span>
            </>
          )}
        </p>
        <p className="text-xs text-content-tertiary mt-1.5">{t('theme_drop_types')}</p>
      </div>
      {error && (
        <p role="alert" className="-mt-2 text-xs text-danger leading-relaxed">
          {error}
        </p>
      )}

      <div className="flex items-center gap-3 p-3.5 rounded-card border border-default bg-surface">
        <div className="w-8 h-8 rounded-lg bg-accent-soft text-accent flex items-center justify-center flex-shrink-0">
          <Sparkles size={16} />
        </div>
        <div className="flex-1 min-w-0">
          <p className="text-sm font-medium text-content">{t('theme_agent_title')}</p>
          <p className="text-xs text-content-tertiary leading-relaxed mt-0.5">{t('theme_agent_desc')}</p>
        </div>
        <button
          type="button"
          onClick={() => void askAgent()}
          className="flex-shrink-0 px-3 py-1.5 rounded-btn text-xs font-medium text-accent bg-accent-soft hover:opacity-80 cursor-pointer transition-opacity"
        >
          {t('theme_agent_start')}
        </button>
      </div>
    </Modal>
  )
}

const FooterLink: React.FC<{ icon: React.ReactNode; label: string; onClick: () => void }> = ({
  icon,
  label,
  onClick,
}) => (
  <button
    type="button"
    onClick={onClick}
    className="inline-flex items-center gap-1.5 text-content-tertiary hover:text-content cursor-pointer transition-colors"
  >
    {icon}
    {label}
  </button>
)

export default ThemeAddModal
