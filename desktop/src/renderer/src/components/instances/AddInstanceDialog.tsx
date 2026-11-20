import React, { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { CheckCircle2, Link2, Loader2, Server, X } from 'lucide-react'
import { t } from '../../i18n'
import { addressCandidates, parsePairLink, type Instance } from '../../api/instances'
import { useInstanceStore } from '../../store/instanceStore'
import { Btn, TextInput } from '../../pages/settings/primitives'
import { failureText } from './failure'

/** Joins another CowAgent device with the address and one-time code it shows. */
const AddInstanceDialog: React.FC = () => {
  const request = useInstanceStore((s) => s.addRequest)
  const close = useInstanceStore((s) => s.closeAdd)
  const pair = useInstanceStore((s) => s.pair)
  const switchTo = useInstanceStore((s) => s.switchTo)
  const activeId = useInstanceStore((s) => s.activeId)

  const [url, setUrl] = useState('')
  const [code, setCode] = useState('')
  const [link, setLink] = useState<{ code: string; urls: string[] } | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [added, setAdded] = useState<Instance | null>(null)
  const urlRef = useRef<HTMLInputElement>(null)
  const codeRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (!request) return
    setUrl(request.url || '')
    setCode('')
    setLink(null)
    setBusy(false)
    setError('')
    setAdded(null)
    const timer = setTimeout(() => (request.url ? codeRef : urlRef).current?.focus(), 50)
    return () => clearTimeout(timer)
  }, [request])

  useEffect(() => {
    if (!request) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !busy) close()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [request, busy, close])

  if (!request) return null

  const takeLink = (value: string) => {
    const parsed = parsePairLink(value)
    if (!parsed) return false
    setLink(parsed)
    setUrl(parsed.urls[0])
    setCode(parsed.code)
    setError('')
    return true
  }

  const submit = async (e?: React.FormEvent) => {
    e?.preventDefault()
    if (busy) return
    const typed = addressCandidates(url)
    const typedCode = code.trim()
    if (!typed.length) return setError(t('devices_err_url'))
    if (!typedCode) return setError(t('devices_err_code'))
    const linked = link && link.code === typedCode
    const candidates = linked ? [...typed, ...link.urls.filter((u) => !typed.includes(u))] : typed
    setBusy(true)
    setError('')
    try {
      setAdded(await pair(candidates, typedCode, request.replaceId))
    } catch (err) {
      setError(failureText(err))
    } finally {
      setBusy(false)
    }
  }

  const goThere = () => {
    if (!added) return
    close()
    if (added.id === activeId) window.location.reload()
    else switchTo(added.id)
  }

  const linked = !!link && link.code === code.trim()

  return createPortal(
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget && !busy) close()
      }}
    >
      <div className="w-full max-w-[440px] rounded-card border border-default bg-elevated shadow-xl overflow-hidden">
        {added ? (
          <div className="px-6 pt-8 pb-6 text-center">
            <div className="w-12 h-12 mx-auto rounded-2xl bg-[color-mix(in_srgb,var(--success)_10%,transparent)] text-success flex items-center justify-center">
              <CheckCircle2 size={24} />
            </div>
            <h3 className="mt-4 text-base font-semibold text-content">
              {t('devices_added')} · {added.name}
            </h3>
            <p className="mt-1 text-xs font-mono text-content-tertiary">{added.url}</p>
            <p className="mt-3 text-sm text-content-secondary leading-relaxed">{t('devices_added_hint')}</p>
            <div className="mt-6 flex justify-center gap-2">
              <Btn onClick={close}>{t('devices_later')}</Btn>
              <Btn variant="primary" onClick={goThere} autoFocus>
                {t('devices_switch_now')}
              </Btn>
            </div>
          </div>
        ) : (
          <form onSubmit={(e) => void submit(e)}>
            <div className="flex items-start gap-3 px-5 pt-5">
              <div className="w-9 h-9 rounded-xl bg-accent-soft text-accent flex items-center justify-center flex-shrink-0">
                <Server size={17} />
              </div>
              <div className="min-w-0 flex-1">
                <h3 className="font-semibold text-content">{t('devices_add_title')}</h3>
                <p className="text-xs text-content-tertiary mt-0.5">{t('devices_add_desc')}</p>
              </div>
              <button
                type="button"
                onClick={close}
                disabled={busy}
                className="p-1 -mr-1 rounded-md text-content-tertiary hover:text-content hover:bg-surface-2 cursor-pointer disabled:opacity-40"
              >
                <X size={16} />
              </button>
            </div>

            <div className="px-5 pt-4 pb-5 space-y-4">
              <p className="text-xs leading-relaxed text-content-secondary bg-surface-2 rounded-lg px-3 py-2.5">
                {t('devices_add_hint')}
              </p>
              <label className="block">
                <span className="block text-xs font-medium text-content-secondary mb-1.5">{t('devices_addr')}</span>
                <TextInput
                  ref={urlRef}
                  value={url}
                  disabled={busy}
                  spellCheck={false}
                  placeholder={t('devices_addr_placeholder')}
                  className="font-mono"
                  onChange={(e) => {
                    if (!takeLink(e.target.value)) setUrl(e.target.value)
                  }}
                />
              </label>
              {linked ? (
                <div className="flex items-center gap-2 text-xs text-accent bg-accent-soft rounded-lg px-3 py-2.5">
                  <Link2 size={13} className="flex-shrink-0" />
                  {t('devices_link_detected')}
                </div>
              ) : (
                <label className="block">
                  <span className="block text-xs font-medium text-content-secondary mb-1.5">{t('devices_code')}</span>
                  <TextInput
                    ref={codeRef}
                    value={code}
                    disabled={busy}
                    spellCheck={false}
                    autoComplete="off"
                    placeholder="XXXX-XXXX"
                    className="font-mono tracking-[0.2em] uppercase"
                    onChange={(e) => {
                      if (!takeLink(e.target.value)) setCode(e.target.value)
                    }}
                  />
                </label>
              )}
              {error && <p className="text-xs text-danger leading-relaxed">{error}</p>}
            </div>

            <div className="flex items-center justify-end gap-2 px-5 py-3.5 border-t border-default bg-[color-mix(in_srgb,var(--bg-surface)_40%,transparent)]">
              <Btn type="button" onClick={close} disabled={busy}>
                {t('config_cancel')}
              </Btn>
              <Btn type="submit" variant="primary" disabled={busy}>
                <span className="inline-flex items-center gap-1.5">
                  {busy && <Loader2 size={14} className="animate-spin" />}
                  {busy ? t('devices_connecting') : t('devices_connect')}
                </span>
              </Btn>
            </div>
          </form>
        )}
      </div>
    </div>,
    document.body,
  )
}

export default AddInstanceDialog
