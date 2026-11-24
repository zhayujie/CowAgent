import React, { useCallback, useEffect, useRef, useState } from 'react'
import { AlertCircle, CheckCircle2, ExternalLink, Hourglass, Loader2 } from 'lucide-react'
import { t, tf } from '../../i18n'
import apiClient from '../../api/client'
import { Btn, Modal } from './primitives'

// ChatGPT-subscription (Codex) sign-in, same backend contract as the web
// console's openCodexSetup in channel/web/static/js/views/models.js.

export const CODEX_PROVIDER_ID = 'codex'

type CodexAction = 'status' | 'login' | 'cancel' | 'refresh' | 'logout'

export interface CodexSnapshot {
  phase: string
  installed?: boolean
  cli_version?: string
  signed_in?: boolean
  models_ready?: boolean
  models?: string[]
  account?: { email?: string; plan?: string } | null
  user_code?: string
  verification_url?: string
  downloaded?: number
  total?: number
  message?: string
}

const BUSY_PHASES: Record<string, string> = {
  checking: 'models_codex_checking',
  starting: 'models_codex_starting',
  installing: 'models_codex_installing',
  waiting: 'models_codex_waiting',
  canceling: 'models_codex_canceling',
  refreshing: 'models_codex_refreshing',
  signing_out: 'models_codex_signing_out',
}

interface CodexSetupOptions {
  // Whether the models data currently lists Codex as configured; a mismatch
  // with the backend snapshot means the caller's data is stale.
  configured: boolean
  // A sign-in started here finished and the model list is ready.
  onSignedIn?: (snap: CodexSnapshot) => void
  // The Codex model catalog changed (refresh, sign-out, stale data).
  onChanged?: () => void
}

export function useCodexSetup(options: CodexSetupOptions) {
  const [snap, setSnap] = useState<CodexSnapshot>({ phase: 'checking' })
  const [error, setError] = useState('')
  const [synced, setSynced] = useState(false)
  const operation = useRef<CodexAction | ''>('')
  const timer = useRef<ReturnType<typeof setTimeout>>()
  const alive = useRef(true)
  const opts = useRef(options)
  opts.current = options

  const request = useCallback(async (action: CodexAction, attempts = 0): Promise<void> => {
    if (!alive.current) return
    clearTimeout(timer.current)
    if (action !== 'status') {
      operation.current = action
      setError('')
      setSynced(false)
      setSnap((s) => ({ ...s, phase: action === 'cancel' ? 'canceling' : 'starting' }))
    }
    try {
      const res = await apiClient.modelsAction({ action: `codex_${action}` })
      if (!alive.current) return
      if (res.status !== 'success') {
        operation.current = ''
        setError(res.message_key ? t(res.message_key as string) : (res.message as string) || t('config_save_error'))
        setSnap((s) => ({ ...s, phase: 'idle' }))
        return
      }
      const next = res as unknown as CodexSnapshot
      setError('')
      setSnap(next)
      if (BUSY_PHASES[next.phase]) {
        if (next.phase === 'waiting' && !operation.current) operation.current = 'login'
        timer.current = setTimeout(() => request('status'), next.phase === 'installing' ? 500 : 1200)
        return
      }
      const op = operation.current
      operation.current = ''
      const done = next.phase === 'idle'
      if (done && op === 'login' && next.models_ready) {
        opts.current.onSignedIn?.(next)
        return
      }
      const catalogChanged = !!next.models_ready !== opts.current.configured
      if (done && (catalogChanged || op === 'refresh' || op === 'logout')) opts.current.onChanged?.()
      setSynced(done && op === 'refresh' && !!next.signed_in)
    } catch {
      if (!alive.current) return
      setError(t('models_codex_connection_error'))
      if (attempts < 3) timer.current = setTimeout(() => request('status', attempts + 1), 1500)
    }
  }, [])

  useEffect(() => {
    alive.current = true
    request('status')
    return () => {
      alive.current = false
      clearTimeout(timer.current)
    }
  }, [request])

  const busy = !!BUSY_PHASES[snap.phase]
  return {
    snap,
    error,
    synced,
    busy,
    waiting: snap.phase === 'waiting',
    signedIn: !busy && !!snap.signed_in,
    login: () => request('login'),
    cancel: () => request('cancel'),
    refresh: () => request('refresh'),
    logout: () => request('logout'),
  }
}

export type CodexSetup = ReturnType<typeof useCodexSetup>

function accountLabel(account: CodexSnapshot['account']): string {
  const plan = account?.plan ? account.plan.charAt(0).toUpperCase() + account.plan.slice(1) : ''
  const who = account?.email || 'ChatGPT'
  return plan ? `${who} · ${plan}` : who
}

const mb = (bytes: number) => (bytes / 1048576).toFixed(1)

// Status, device code and synced model list. Actions live in CodexActions so
// a modal can put them in its footer.
export const CodexPanel: React.FC<{ setup: CodexSetup }> = ({ setup }) => {
  const { snap, error, synced, busy, waiting, signedIn } = setup
  const [copied, setCopied] = useState(false)
  useEffect(() => setCopied(false), [snap.user_code])

  const copyCode = async () => {
    if (!snap.user_code) return
    try {
      await navigator.clipboard.writeText(snap.user_code)
      setCopied(true)
    } catch {
      // Clipboard may be unavailable; the code stays selectable in the input.
    }
  }

  let message = ''
  let icon: React.ReactNode = null
  if (error || (snap.phase === 'error' && snap.message)) {
    message = error || snap.message || ''
    icon = <AlertCircle size={16} className="flex-shrink-0 text-danger" />
  } else if (busy) {
    message = t(BUSY_PHASES[snap.phase])
    if (snap.phase === 'installing' && snap.downloaded) {
      message += snap.total ? ` ${mb(snap.downloaded)} / ${mb(snap.total)} MB` : ` ${mb(snap.downloaded)} MB`
    }
    icon = waiting ? (
      <Hourglass size={16} className="flex-shrink-0 text-accent" />
    ) : (
      <Loader2 size={16} className="flex-shrink-0 animate-spin text-content-tertiary" />
    )
  } else if (signedIn) {
    message = tf('models_codex_connected_as', { account: accountLabel(snap.account) })
    if (synced) message += ` ${t('models_codex_models_synced')}`
    icon = <CheckCircle2 size={16} className="flex-shrink-0 text-accent" />
  }

  const models = snap.models || []
  const progress = snap.phase === 'installing' && snap.total ? Math.min(100, ((snap.downloaded || 0) * 100) / snap.total) : 0

  return (
    <div className="space-y-4 text-sm">
      {!busy && !snap.signed_in && (
        <div className="space-y-2 text-content-secondary leading-relaxed">
          <p>{t('models_codex_intro')}</p>
          <p className="text-xs text-content-tertiary">
            {snap.installed
              ? tf('models_codex_intro_installed', { version: snap.cli_version || '' })
              : t('models_codex_intro_install')}
          </p>
        </div>
      )}
      {message && (
        <div className="space-y-2.5 rounded-btn border border-default bg-inset-2 p-3.5">
          <div className="flex items-center gap-3">
            {icon}
            <p className="min-w-0 break-words text-content" role="status">
              {message}
            </p>
          </div>
          {snap.phase === 'installing' && (
            <div className="h-1.5 overflow-hidden rounded-full bg-surface-2">
              <div className="h-full rounded-full bg-accent transition-all duration-300" style={{ width: `${progress}%` }} />
            </div>
          )}
        </div>
      )}
      {waiting && snap.user_code && (
        <div className="space-y-3 rounded-btn border border-default p-3.5">
          <ol className="list-decimal space-y-1 pl-5 text-content-secondary">
            <li>{t('models_codex_step_open')}</li>
            <li>{t('models_codex_step_sign_in')}</li>
            <li>{t('models_codex_step_code')}</li>
          </ol>
          <div className="flex items-center gap-2">
            <input
              readOnly
              aria-label={t('models_codex_device_code')}
              value={snap.user_code}
              onFocus={(e) => e.currentTarget.select()}
              className="min-w-0 flex-1 rounded-btn border border-strong bg-inset px-3 py-2 font-mono font-semibold tracking-wider text-content focus:outline-none"
            />
            <Btn onClick={copyCode}>{copied ? t('models_codex_copied') : t('config_api_copy')}</Btn>
          </div>
        </div>
      )}
      {!busy && models.length > 0 && (
        <details className="border-t border-default pt-3">
          <summary className="cursor-pointer text-sm font-medium text-content-secondary">
            {t('models_catalog')}
            <span className="ml-1.5 text-xs font-normal text-content-tertiary">{models.length}</span>
          </summary>
          <ul className="mt-2 max-h-44 overflow-y-auto rounded-btn border border-default bg-inset-2">
            {models.map((m) => (
              <li key={m} className="px-3 py-2 break-all font-mono text-xs text-content border-b border-default last:border-b-0">
                {m}
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  )
}

// Sign out (when signed in) or cancel (while waiting for authorization).
export const CodexSecondaryActions: React.FC<{ setup: CodexSetup; showLogout?: boolean }> = ({
  setup,
  showLogout = true,
}) => (
  <>
    {showLogout && setup.signedIn && (
      <Btn variant="danger" onClick={setup.logout}>
        {t('models_codex_logout')}
      </Btn>
    )}
    {setup.waiting && <Btn onClick={setup.cancel}>{t('models_codex_cancel')}</Btn>}
  </>
)

// Open authorization / sign in / sync models, according to the current phase.
export const CodexPrimaryActions: React.FC<{ setup: CodexSetup }> = ({ setup }) => {
  const { snap, busy, waiting, signedIn } = setup
  const openAuth = () => {
    if (!snap.verification_url) return
    if (snap.user_code) navigator.clipboard?.writeText(snap.user_code).catch(() => {})
    window.open(snap.verification_url, '_blank', 'noopener,noreferrer')
  }
  return (
    <>
      {waiting && snap.verification_url && (
        <Btn variant="primary" onClick={openAuth} className="inline-flex items-center gap-1.5">
          {t('models_codex_open')}
          <ExternalLink size={12} />
        </Btn>
      )}
      {!busy && !snap.signed_in && (
        <Btn variant="primary" onClick={setup.login}>
          {t('models_codex_sign_in')}
        </Btn>
      )}
      {signedIn && (
        <Btn variant="primary" onClick={setup.refresh}>
          {t('models_codex_refresh')}
        </Btn>
      )}
    </>
  )
}

// Vendor modal body for Codex: replaces the API key / base / catalog editor.
// `header` carries the add-flow provider picker so switching vendors still works.
export const CodexVendorModal: React.FC<{
  title: string
  header?: React.ReactNode
  configured: boolean
  onClose: () => void
  onSaved: () => Promise<void>
}> = ({ title, header, configured, onClose, onSaved }) => {
  const setup = useCodexSetup({
    configured,
    onSignedIn: () => {
      onSaved()
      onClose()
    },
    onChanged: () => {
      onSaved()
    },
  })
  return (
    <Modal
      open
      size="lg"
      title={title}
      headerRight={<span className="text-xs text-content-tertiary truncate">{t('models_codex_subscription')}</span>}
      onClose={onClose}
      footer={
        <>
          <div className="mr-auto flex items-center gap-2">
            <CodexSecondaryActions setup={setup} />
          </div>
          <Btn onClick={onClose}>{t('ws_close')}</Btn>
          <CodexPrimaryActions setup={setup} />
        </>
      }
    >
      {header}
      <CodexPanel setup={setup} />
    </Modal>
  )
}
