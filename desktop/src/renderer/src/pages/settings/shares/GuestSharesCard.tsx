import React, { useCallback, useEffect, useRef, useState } from 'react'
import {
  ArrowRight,
  BookOpen,
  CircleAlert,
  Clock,
  Code2,
  Copy,
  ExternalLink,
  History,
  Info,
  KeyRound,
  Lock,
  LockOpen,
  MessageCircle,
  MoreHorizontal,
  Pause,
  Play,
  Plus,
  RotateCw,
  Share2,
  Trash2,
  Wrench,
} from 'lucide-react'
import { t, tf } from '../../../i18n'
import apiClient, { type GuestShare, type GuestSharesOverview } from '../../../api/client'
import { askConfirm } from '../../../store/confirmStore'
import Tooltip from '../../../components/Tooltip'
import { Card, Toggle } from '../primitives'
import ShareEditor from './ShareEditor'
import { ShareEmbedDialog, ShareLogsDialog } from './ShareDialogs'
import { shareConfig, shareUrl } from './shareCommon'

const STATUS: Record<string, { dot: string; text: string; key: string }> = {
  active: { dot: 'bg-primary-400', text: 'text-primary-500', key: 'shares_status_active' },
  unconfirmed: { dot: 'bg-amber-400', text: 'text-amber-500', key: 'shares_status_unconfirmed' },
  password_missing: { dot: 'bg-amber-400', text: 'text-amber-500', key: 'shares_status_password_missing' },
  disabled: { dot: 'bg-content-tertiary', text: 'text-content-tertiary', key: 'shares_status_disabled' },
  expired: { dot: 'bg-content-tertiary', text: 'text-content-tertiary', key: 'shares_status_expired' },
}

type Action = 'confirm' | 'reset-link' | 'disable' | 'enable' | 'delete'

const CONFIRMS: Partial<Record<Action, { title: string; msg: string }>> = {
  'reset-link': { title: 'shares_reset_link', msg: 'shares_reset_link_confirm' },
  disable: { title: 'shares_disable', msg: 'shares_disable_confirm' },
  delete: { title: 'shares_delete', msg: 'shares_delete_confirm' },
}

const ICON_BTN =
  'w-7 h-7 flex items-center justify-center rounded-md text-content-tertiary hover:text-content-secondary hover:bg-surface-2 cursor-pointer transition-colors'
const ACTION_BTN =
  'inline-flex items-center gap-1.5 px-2 py-1.5 rounded-md text-xs text-content-tertiary hover:text-content-secondary hover:bg-surface-2 cursor-pointer transition-colors disabled:opacity-40 disabled:cursor-not-allowed'
const CALLOUT =
  'flex gap-2.5 px-3 py-2.5 rounded-btn border text-xs leading-relaxed border-amber-200 bg-amber-50 text-amber-800 dark:border-amber-500/20 dark:bg-amber-500/10 dark:text-amber-200'
const CALLOUT_BTN =
  'flex-shrink-0 self-center px-3 py-1.5 rounded-btn bg-accent text-accent-contrast hover:bg-accent-hover text-xs font-medium cursor-pointer transition-colors'

const Chip: React.FC<{ icon: React.ReactNode; title?: string; children: React.ReactNode }> = ({ icon, title, children }) => (
  <span title={title} className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-surface-2 text-[11px] text-content-tertiary">
    {icon}
    {children}
  </span>
)

const ShareMenu: React.FC<{ share: GuestShare; onAction: (a: Action) => void }> = ({ share, onAction }) => {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    const close = (e: MouseEvent) => {
      if (!ref.current?.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', close)
    return () => document.removeEventListener('mousedown', close)
  }, [open])
  const item = (action: Action, icon: React.ReactNode, label: string, danger = false) => (
    <button
      type="button"
      onClick={() => {
        setOpen(false)
        onAction(action)
      }}
      className={`w-full flex items-center gap-2 px-3 py-2 text-sm text-left cursor-pointer transition-colors ${
        danger ? 'text-danger hover:bg-danger-soft' : 'text-content-secondary hover:bg-surface-2'
      }`}
    >
      {icon}
      {label}
    </button>
  )
  return (
    <div ref={ref} className="relative flex-shrink-0">
      <button type="button" className={ICON_BTN} onClick={() => setOpen((v) => !v)}>
        <MoreHorizontal size={15} />
      </button>
      {open && (
        <div className="absolute right-0 top-8 z-20 w-44 py-1 rounded-btn border border-default bg-elevated shadow-lg">
          {item('reset-link', <RotateCw size={14} />, t('shares_reset_link'))}
          {share.disabled
            ? item('enable', <Play size={14} />, t('shares_enable'))
            : item('disable', <Pause size={14} />, t('shares_disable'))}
          <div className="my-1 border-t border-default" />
          {item('delete', <Trash2 size={14} />, t('shares_delete'), true)}
        </div>
      )}
    </div>
  )
}

const ShareItem: React.FC<{
  share: GuestShare
  base: string
  defaultModel: string
  onEdit: (focus?: 'password') => void
  onAction: (a: Action) => void
  onEmbed: () => void
  onLogs: () => void
  onNotice: (text: string) => void
}> = ({ share, base, defaultModel, onEdit, onAction, onEmbed, onLogs, onNotice }) => {
  const st = STATUS[share.status] || STATUS.disabled
  const cfg = shareConfig(share)
  const url = shareUrl(share, base)
  const access = cfg.access || {}
  const quota = cfg.limits?.daily_messages
  const refs = (cfg.references || []).map((r) => r.path)
  const origins = access.allowed_origins || []
  const pending = share.pending || []

  return (
    <div className="rounded-btn border border-default p-4">
      <div className="flex items-center gap-3">
        <img src={apiClient.guestShareLogoUrl(share)} alt="" className="w-9 h-9 rounded-lg object-cover border border-default flex-shrink-0" />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 min-w-0">
            <span className="font-medium text-content truncate">{share.name || share.slug}</span>
            <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${st.dot}`} />
            <span className={`text-xs flex-shrink-0 ${st.text}`}>{t(st.key)}</span>
          </div>
          <div className="text-xs text-content-tertiary truncate mt-0.5">{cfg.model || defaultModel || t('shares_model_default_short')}</div>
        </div>
        <button
          type="button"
          onClick={() => onEdit()}
          className="flex-shrink-0 px-3 py-1.5 rounded-btn text-xs font-medium bg-surface-2 text-content-secondary hover:text-content cursor-pointer transition-colors"
        >
          {t('shares_edit')}
        </button>
        <ShareMenu share={share} onAction={onAction} />
      </div>

      <div className="mt-3 space-y-3">
        <div
          className={`flex items-center gap-1 pl-3 pr-1 py-1 rounded-btn border border-default bg-inset ${
            url && share.status === 'active' ? '' : 'opacity-60'
          }`}
        >
          <span className="flex-1 min-w-0 truncate font-mono text-xs text-content-secondary" title={url}>
            {url || t('shares_no_link')}
          </span>
          {url && (
            <>
              <Tooltip label={t('shares_copy_link')}>
                <button
                  type="button"
                  className={ICON_BTN}
                  onClick={() =>
                    void navigator.clipboard
                      .writeText(url)
                      .then(() => onNotice(t('shares_link_copied')))
                      .catch(() => onNotice(t('shares_copy_failed')))
                  }
                >
                  <Copy size={13} />
                </button>
              </Tooltip>
              <Tooltip label={t('shares_open')}>
                <a href={url} target="_blank" rel="noopener noreferrer" className={ICON_BTN}>
                  <ExternalLink size={13} />
                </a>
              </Tooltip>
            </>
          )}
        </div>

        <div className="flex flex-wrap gap-1.5">
          {access.password_required ? (
            <Chip icon={<Lock size={11} />}>{t('shares_chip_password')}</Chip>
          ) : (
            <Chip icon={<LockOpen size={11} />}>{t('shares_chip_public')}</Chip>
          )}
          <Chip icon={<MessageCircle size={11} />}>
            {quota ? tf('shares_chip_quota', { n: quota }) : t('shares_chip_quota_unlimited')}
          </Chip>
          <Chip icon={<Wrench size={11} />}>{tf('shares_chip_tools', { n: (cfg.tools || []).length })}</Chip>
          {refs.length > 0 && (
            <Chip icon={<BookOpen size={11} />} title={refs.join('\n')}>
              {tf('shares_chip_paths', { n: refs.length })}
            </Chip>
          )}
          {cfg.expires_at && <Chip icon={<Clock size={11} />}>{tf('shares_chip_expires', { d: cfg.expires_at })}</Chip>}
          {origins.length > 0 && (
            <Chip icon={<Code2 size={11} />} title={origins.join('\n')}>
              {tf('shares_chip_embed', { n: origins.length })}
            </Chip>
          )}
        </div>

        {(share.status === 'unconfirmed' || pending.length > 0) && (
          <div className={CALLOUT}>
            <CircleAlert size={14} className="flex-shrink-0 mt-0.5" />
            <div className="flex-1 min-w-0">
              <div>{t(pending.length ? 'shares_pending' : 'shares_unconfirmed')}</div>
              {pending.length > 0 && (
                <ul className="list-disc pl-4 mt-1">
                  {pending.map((p, i) => (
                    <li key={i}>{p}</li>
                  ))}
                </ul>
              )}
            </div>
            <button type="button" className={CALLOUT_BTN} onClick={() => onAction('confirm')}>
              {t('shares_confirm')}
            </button>
          </div>
        )}
        {share.status === 'password_missing' && (
          <div className={`${CALLOUT} items-center`}>
            <KeyRound size={14} className="flex-shrink-0" />
            <span className="flex-1">{t('shares_password_missing')}</span>
            <button type="button" className={CALLOUT_BTN} onClick={() => onEdit('password')}>
              {t('shares_set_password')}
            </button>
          </div>
        )}
        {(share.notices || []).length > 0 && (
          <div className="flex gap-2.5 px-3 py-2.5 rounded-btn border border-default bg-surface-2 text-xs leading-relaxed text-content-secondary">
            <Info size={14} className="flex-shrink-0 mt-0.5" />
            <div className="flex-1 min-w-0">
              <div>{t('shares_notices')}</div>
              <ul className="list-disc pl-4 mt-1">
                {share.notices.map((n, i) => (
                  <li key={i}>{n}</li>
                ))}
              </ul>
            </div>
          </div>
        )}
      </div>

      <div className="flex flex-wrap items-center gap-1 mt-3 pt-2 -mx-2 px-0.5 border-t border-default">
        <button type="button" className={ACTION_BTN} disabled={!url} onClick={onEmbed}>
          <Code2 size={13} />
          {t('shares_embed')}
        </button>
        <button type="button" className={ACTION_BTN} onClick={onLogs}>
          <History size={13} />
          {t('shares_logs')}
        </button>
      </div>
    </div>
  )
}

/** Guest pages: shareable chat pages backed by profiles under guests/. */
const GuestSharesCard: React.FC<{
  base: string
  onNotice: (text: string) => void
  onGoToPassword: () => void
}> = ({ base, onNotice, onGoToPassword }) => {
  const [overview, setOverview] = useState<GuestSharesOverview | null>(null)
  const [loadError, setLoadError] = useState(false)
  const [defaultModel, setDefaultModel] = useState('')
  const [editor, setEditor] = useState<{ slug: string; focus?: 'password' } | null>(null)
  const [embedSlug, setEmbedSlug] = useState('')
  const [logsSlug, setLogsSlug] = useState('')

  const load = useCallback(() => {
    apiClient
      .listGuestShares()
      .then((data) => {
        setOverview(data)
        setLoadError(false)
      })
      .catch(() => setLoadError(true))
  }, [])

  useEffect(() => {
    load()
    apiClient
      .getConfig()
      .then((cfg) => setDefaultModel(String((cfg as { model?: string }).model || '')))
      .catch(() => {})
  }, [load])

  const replace = (share: GuestShare) =>
    setOverview((prev) => {
      if (!prev) return prev
      const exists = prev.shares.some((s) => s.slug === share.slug)
      return { ...prev, shares: exists ? prev.shares.map((s) => (s.slug === share.slug ? share : s)) : [...prev.shares, share] }
    })

  const toggleFeature = async (enabled: boolean) => {
    try {
      const { feature } = await apiClient.setGuestSharesEnabled(enabled)
      setOverview((prev) => (prev ? { ...prev, feature } : prev))
      if (enabled) load()
    } catch (e) {
      onNotice((e as Error).message)
    }
  }

  const runAction = async (share: GuestShare, action: Action) => {
    const ask = CONFIRMS[action]
    if (ask && !(await askConfirm({ titleKey: ask.title, msgKey: ask.msg, okKey: ask.title, vars: { name: share.name || share.slug } }))) return
    try {
      if (action === 'delete') {
        await apiClient.deleteGuestShare(share.slug)
        setOverview((prev) => (prev ? { ...prev, shares: prev.shares.filter((s) => s.slug !== share.slug) } : prev))
      } else {
        replace((await apiClient.guestShareAction(share.slug, action)).share)
      }
      onNotice(t(`shares_done_${action.replace('-', '_')}`))
    } catch (e) {
      onNotice((e as Error).message)
    }
  }

  const feature = overview?.feature
  const shares = overview?.shares || []
  const find = (slug: string) => shares.find((s) => s.slug === slug) || null

  return (
    <Card
      icon={<Share2 size={16} />}
      title={t('shares_title')}
      subtitle={t('shares_desc')}
      action={<Toggle checked={!!feature?.enabled} onChange={(v) => void toggleFeature(v)} />}
    >
      {loadError ? (
        <p className="text-sm text-danger text-center py-2">{t('shares_load_failed')}</p>
      ) : feature?.enabled ? (
        <div className="space-y-3">
          {!feature.web_password_set && (
            <div className={`${CALLOUT} items-center`}>
              <Lock size={14} className="flex-shrink-0" />
              <span className="flex-1">{t('shares_need_console_password')}</span>
              <button
                type="button"
                onClick={onGoToPassword}
                className="flex-shrink-0 inline-flex items-center gap-1 px-2 py-1 rounded-md font-medium hover:bg-amber-100 dark:hover:bg-amber-500/10 cursor-pointer"
              >
                {t('shares_go_settings')}
                <ArrowRight size={12} />
              </button>
            </div>
          )}
          {shares.map((s) => (
            <ShareItem
              key={s.slug}
              share={s}
              base={base}
              defaultModel={defaultModel}
              onEdit={(focus) => setEditor({ slug: s.slug, focus })}
              onAction={(a) => void runAction(s, a)}
              onEmbed={() => setEmbedSlug(s.slug)}
              onLogs={() => setLogsSlug(s.slug)}
              onNotice={onNotice}
            />
          ))}
          <button
            type="button"
            onClick={() => setEditor({ slug: '' })}
            className="w-full flex items-center justify-center gap-1.5 py-2.5 rounded-btn border border-dashed border-strong text-sm text-content-tertiary hover:text-accent hover:border-accent cursor-pointer transition-colors"
          >
            <Plus size={14} />
            {t('shares_new')}
          </button>
        </div>
      ) : null}

      <ShareEditor
        slug={editor ? editor.slug : null}
        focus={editor?.focus}
        overview={overview}
        defaultModel={defaultModel}
        onClose={() => setEditor(null)}
        onSaved={(share, notice) => {
          replace(share)
          if (notice) {
            onNotice(notice)
            load()
          }
        }}
        onNotice={onNotice}
      />
      <ShareEmbedDialog share={embedSlug ? find(embedSlug) : null} base={base} onClose={() => setEmbedSlug('')} onSaved={replace} onNotice={onNotice} />
      <ShareLogsDialog share={logsSlug ? find(logsSlug) : null} onClose={() => setLogsSlug('')} />
    </Card>
  )
}

export default GuestSharesCard
