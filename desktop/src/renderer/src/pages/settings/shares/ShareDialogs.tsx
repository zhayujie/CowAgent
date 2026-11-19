import React, { useEffect, useState } from 'react'
import { Check, Copy, Inbox, Loader2, MessagesSquare, Paperclip, X } from 'lucide-react'
import { t } from '../../../i18n'
import apiClient, { type GuestLogRecord, type GuestLogSession, type GuestShare } from '../../../api/client'
import Markdown from '../../../components/Markdown'
import { Btn, Field, Modal } from '../primitives'
import { SHARE_ORIGIN_RE, embedSnippet, shareTime } from './shareCommon'

const TEXTAREA =
  'w-full px-3 py-2 rounded-btn border border-strong bg-inset text-[13px] font-mono text-content placeholder:text-content-tertiary placeholder:opacity-60 focus:outline-none focus:border-accent transition-colors resize-none'

// ---------------------------------------------------------------------------
// Embed
// ---------------------------------------------------------------------------

export const ShareEmbedDialog: React.FC<{
  share: GuestShare | null
  base: string
  onClose: () => void
  onSaved: (share: GuestShare) => void
  onNotice: (text: string) => void
}> = ({ share, base, onClose, onSaved, onNotice }) => {
  const [origins, setOrigins] = useState('')
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (!share) return
    const cfg = share.file_config || share.effective_config || {}
    setOrigins((cfg.access?.allowed_origins || []).join('\n'))
    setError('')
    setSaving(false)
  }, [share])

  if (!share) return null
  const code = embedSnippet(share, base)

  const save = async () => {
    const list = origins
      .split('\n')
      .map((o) => o.trim().replace(/\/+$/, '').toLowerCase())
      .filter(Boolean)
    const bad = list.find((o) => !SHARE_ORIGIN_RE.test(o))
    if (bad) return setError(t('shares_origin_invalid').replace('{o}', bad))
    setSaving(true)
    setError('')
    try {
      const { share: fresh } = await apiClient.getGuestShare(share.slug)
      const config = JSON.parse(JSON.stringify(fresh.raw_config || {}))
      config.access = { ...(config.access || {}), allowed_origins: Array.from(new Set(list)) }
      const { share: saved } = await apiClient.updateGuestShare(share.slug, config)
      onSaved(saved)
      onNotice(t('shares_saved'))
      onClose()
    } catch (e) {
      setSaving(false)
      setError((e as Error).message)
    }
  }

  return (
    <Modal
      open
      size="lg"
      title={t('shares_embed_title')}
      onClose={onClose}
      footer={
        <>
          <span className="flex-1 min-w-0 text-xs text-danger truncate">{error}</span>
          <Btn onClick={onClose}>{t('cancel')}</Btn>
          <Btn variant="primary" disabled={saving} onClick={() => void save()}>
            {t('config_save')}
          </Btn>
        </>
      }
    >
      <p className="text-xs text-content-tertiary">{t('shares_embed_desc')}</p>
      <div className="rounded-btn border border-strong bg-inset overflow-hidden">
        <div className="flex items-center justify-between px-3 py-1.5 border-b border-default text-xs text-content-tertiary">
          <span>HTML</span>
          <CopyText text={code} label={t('shares_copy')} onCopied={() => onNotice(t('shares_code_copied'))} />
        </div>
        <pre className="text-xs leading-relaxed font-mono text-content p-3 overflow-x-auto whitespace-pre">{code}</pre>
      </div>
      <Field label={t('shares_field_origins')} labelTip={t('shares_field_origins_tip')} hint={t('shares_embed_origins_hint')}>
        <textarea
          rows={3}
          spellCheck={false}
          className={TEXTAREA}
          value={origins}
          placeholder={t('shares_field_origins_ph')}
          onChange={(e) => setOrigins(e.target.value)}
        />
      </Field>
    </Modal>
  )
}

const CopyText: React.FC<{ text: string; label: string; onCopied: () => void }> = ({ text, label, onCopied }) => {
  const [copied, setCopied] = useState(false)
  return (
    <button
      type="button"
      className="inline-flex items-center gap-1.5 hover:text-content-secondary cursor-pointer"
      onClick={() =>
        void navigator.clipboard.writeText(text).then(() => {
          setCopied(true)
          onCopied()
          setTimeout(() => setCopied(false), 1200)
        })
      }
    >
      {copied ? <Check size={12} /> : <Copy size={12} />}
      {label}
    </button>
  )
}

// ---------------------------------------------------------------------------
// Visitor logs
// ---------------------------------------------------------------------------

const Empty: React.FC<{ icon?: React.ReactNode; text?: string; danger?: boolean }> = ({ icon, text, danger }) => (
  <div className={`h-full flex flex-col items-center justify-center gap-2 text-sm ${danger ? 'text-danger' : 'text-content-tertiary'}`}>
    {icon}
    {text && <span>{text}</span>}
  </div>
)

const Turn: React.FC<{ rec: GuestLogRecord }> = ({ rec }) => {
  if (rec.role === 'event') {
    const key = rec.event === 'deleted' ? 'shares_logs_event_deleted' : 'shares_logs_event_clear'
    return (
      <div className="flex items-center gap-3 text-[11px] text-content-tertiary">
        <div className="flex-1 border-t border-default" />
        <span>
          {t(key)} · {shareTime(rec.ts)}
        </span>
        <div className="flex-1 border-t border-default" />
      </div>
    )
  }
  const isUser = rec.role === 'user'
  const files = isUser ? rec.attachments || [] : (rec.files || []).map((f) => f.path || f.file_name || '')
  const tools = (rec.steps || []).filter((s) => s.type === 'tool')
  const meta: string[] = []
  if (!isUser && rec.tokens) meta.push(`${rec.tokens} tokens`)
  if (!isUser && rec.status && rec.status !== 'done' && rec.status !== 'success') meta.push(rec.status)
  return (
    <div className={`rounded-btn px-3.5 py-3 ${isUser ? 'bg-surface-2' : 'border border-default'}`}>
      <div className="flex items-center gap-1.5 text-[11px] text-content-tertiary mb-1.5">
        <span className="font-medium text-content-secondary">{t(isUser ? 'shares_logs_visitor' : 'shares_logs_agent')}</span>
        <span>{shareTime(rec.ts)}</span>
        {meta.length > 0 && <span>· {meta.join(' · ')}</span>}
      </div>
      {!isUser && tools.length > 0 && (
        <div className="flex flex-wrap gap-1.5 mb-2">
          {tools.map((s, i) => (
            <span
              key={i}
              className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full border border-default text-[11px] ${s.is_error ? 'text-danger' : 'text-content-tertiary'}`}
            >
              {s.is_error ? <X size={11} /> : <Check size={11} />}
              {s.name}
            </span>
          ))}
        </div>
      )}
      {isUser ? (
        <div className="text-sm text-content whitespace-pre-wrap break-words">{rec.content}</div>
      ) : (
        <div className="text-sm">
          <Markdown content={rec.content || (rec.error ? `_${rec.error}_` : '')} />
        </div>
      )}
      {files.length > 0 && (
        <div className="flex flex-wrap gap-1.5 mt-2">
          {files.map((f, i) => (
            <span key={i} className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full border border-default text-[11px] text-content-tertiary">
              <Paperclip size={11} />
              {String(f)}
            </span>
          ))}
        </div>
      )}
    </div>
  )
}

export const ShareLogsDialog: React.FC<{ share: GuestShare | null; onClose: () => void }> = ({ share, onClose }) => {
  const [sessions, setSessions] = useState<GuestLogSession[] | null>(null)
  const [listError, setListError] = useState('')
  const [active, setActive] = useState('')
  const [records, setRecords] = useState<GuestLogRecord[] | null>(null)
  const [detailError, setDetailError] = useState('')

  const openLog = (slug: string, sid: string) => {
    setActive(sid)
    setRecords(null)
    setDetailError('')
    apiClient
      .guestShareLog(slug, sid)
      .then((res) => setRecords(res.records || []))
      .catch((e: Error) => setDetailError(e.message))
  }

  useEffect(() => {
    if (!share) return
    setSessions(null)
    setListError('')
    setActive('')
    setRecords(null)
    apiClient
      .guestShareLogs(share.slug)
      .then((res) => {
        const list = res.sessions || []
        setSessions(list)
        if (list.length) openLog(share.slug, list[0].session_id)
      })
      .catch((e: Error) => setListError(e.message))
  }, [share])

  if (!share) return null
  return (
    <Modal
      open
      size="xl"
      title={t('shares_logs_title')}
      headerRight={<span className="text-xs text-content-tertiary truncate">{share.name || share.slug}</span>}
      onClose={onClose}
    >
      <div className="h-full flex rounded-btn border border-default overflow-hidden">
        <div className="w-64 flex-shrink-0 border-r border-default overflow-y-auto">
          {listError ? (
            <Empty text={listError} danger />
          ) : sessions === null ? (
            <Empty icon={<Loader2 size={16} className="animate-spin" />} />
          ) : !sessions.length ? (
            <Empty icon={<Inbox size={18} />} text={t('shares_logs_empty')} />
          ) : (
            sessions.map((s) => (
              <button
                key={s.session_id}
                type="button"
                onClick={() => openLog(share.slug, s.session_id)}
                className={`w-full text-left px-3 py-2.5 border-b border-default cursor-pointer transition-colors ${
                  active === s.session_id ? 'bg-accent-soft' : 'hover:bg-surface-2'
                }`}
              >
                <div className="flex items-center justify-between gap-2 text-[11px] text-content-tertiary">
                  <span className="font-mono">
                    #{s.session_id.slice(-8)}
                    {s.deleted ? ` · ${t('shares_logs_deleted')}` : ''}
                  </span>
                  <span>{shareTime(s.updated_at)}</span>
                </div>
                <div className="text-xs text-content-secondary truncate mt-0.5">{s.last || ''}</div>
              </button>
            ))
          )}
        </div>
        <div className="flex-1 min-w-0 overflow-y-auto p-4 space-y-3">
          {detailError ? (
            <Empty text={detailError} danger />
          ) : !active ? (
            sessions?.length ? <Empty icon={<MessagesSquare size={18} />} text={t('shares_logs_pick')} /> : null
          ) : records === null ? (
            <Empty icon={<Loader2 size={16} className="animate-spin" />} />
          ) : !records.length ? (
            <Empty text={t('shares_logs_empty')} />
          ) : (
            records.map((r, i) => <Turn key={i} rec={r} />)
          )}
        </div>
      </div>
    </Modal>
  )
}

