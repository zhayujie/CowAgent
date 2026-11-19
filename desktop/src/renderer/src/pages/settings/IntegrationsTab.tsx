import React, { useCallback, useEffect, useState } from 'react'
import { ArrowRight, Globe } from 'lucide-react'
import { t } from '../../i18n'
import apiClient, { type IntegrationsState } from '../../api/client'
import ChatApiCard, { CopyButton } from './ChatApiCard'
import GuestSharesCard from './shares/GuestSharesCard'
import { askConfirm } from '../../store/confirmStore'
import { Btn, Card, Dropdown, Field, TextInput } from './primitives'

const LISTEN_PRESETS = ['127.0.0.1', '0.0.0.0']
const PUBLIC_URL_RE = /^https?:\/\/[^\s/?#]+(\/[^\s?#]*)?$/i
const LOCAL_HOST_RE = /^(localhost|127\.|::1$)/

/** LAN addresses, preferring what the OS reports for real interfaces over the backend's guess. */
async function lanUrls(state: IntegrationsState): Promise<string[]> {
  if (state.local_only || !state.listen?.port) return []
  const ips = (await window.electronAPI?.getLanAddresses?.().catch(() => [])) || []
  const urls = ips.map((ip) => `http://${ip}:${state.listen.port}`)
  return Array.from(new Set([...urls, ...(state.lan_urls || [])]))
}

const IntegrationsTab: React.FC<{
  baseUrl: string
  onGoToPassword: () => void
}> = ({ baseUrl, onGoToPassword }) => {
  const [state, setState] = useState<IntegrationsState | null>(null)
  const [lan, setLan] = useState<string[]>([])
  const [publicUrl, setPublicUrl] = useState('')
  const [status, setStatus] = useState<{
    text: string
    error?: boolean
  } | null>(null)
  const [listenChoice, setListenChoice] = useState('')
  const [customHost, setCustomHost] = useState('')
  const [listenBusy, setListenBusy] = useState(false)
  const [listenProblem, setListenProblem] = useState('')
  const [restarted, setRestarted] = useState(false)
  const [toast, setToast] = useState<{ text: string; shown: boolean } | null>(null)

  const apply = useCallback(
    async (data: IntegrationsState) => {
      setState(data)
      const detected = await lanUrls(data)
      setLan(detected)
      // Empty means detected automatically; show what is in use rather than a blank.
      setPublicUrl(data.public_url || detected[0] || baseUrl)
      const host = data.listen?.host || ''
      setListenChoice(LISTEN_PRESETS.includes(host) ? host : 'custom')
      setCustomHost(LISTEN_PRESETS.includes(host) ? '' : host)
    },
    [baseUrl],
  )

  useEffect(() => {
    apiClient
      .getIntegrations()
      .then((data) => {
        if (data.status === 'success') void apply(data)
      })
      .catch(() => {})
  }, [baseUrl, apply])

  useEffect(() => {
    if (!toast?.shown) return
    const timer = setTimeout(() => setToast((v) => (v ? { ...v, shown: false } : v)), 2200)
    return () => clearTimeout(timer)
  }, [toast])

  const notice = useCallback((text: string) => {
    if (text) setToast({ text, shown: true })
  }, [])

  const savePublicUrl = async () => {
    let value = publicUrl.trim().replace(/\/+$/, '')
    if (value === (lan[0] || baseUrl)) value = ''
    if (value && !PUBLIC_URL_RE.test(value)) return setStatus({ text: t('config_public_url_invalid'), error: true })
    try {
      const data = await apiClient.savePublicUrl(value)
      if (data.status !== 'success') throw new Error(t('config_public_url_invalid'))
      await apply(data)
      setStatus({ text: t('config_saved') })
      setTimeout(() => setStatus(null), 2000)
    } catch (e) {
      setStatus({ text: (e as Error).message, error: true })
    }
  }

  const targetHost = listenChoice === 'custom' ? customHost.trim() : listenChoice
  const changed = !!targetHost && targetHost !== state?.listen?.host
  const needsPassword = changed && !state?.password_set && !LOCAL_HOST_RE.test(targetHost)
  const shownProblem = listenProblem || (needsPassword ? 'password_required' : '')

  /** The server answers first and moves a moment later, to the new address
   *  or, if that fails, back to the old one. */
  const settle = async (): Promise<IntegrationsState | null> => {
    for (let i = 0; i < 20; i++) {
      await new Promise((r) => setTimeout(r, i ? 500 : 1500))
      try {
        const data = await apiClient.getIntegrations()
        if (data.status === 'success') return data
      } catch {
        // still restarting
      }
    }
    return null
  }

  const saveListenHost = async () => {
    setRestarted(false)
    if (!targetHost) return setListenProblem('invalid_host')
    if (!changed) return
    if (needsPassword) return setListenProblem('password_required')
    const ok = await askConfirm({
      titleKey: 'config_listen_apply',
      msgKey: 'config_listen_restart_confirm',
      okKey: 'config_listen_apply',
      tone: 'primary',
    })
    if (!ok) return
    setListenBusy(true)
    setListenProblem('')
    try {
      const data = await apiClient.saveListenHost(targetHost)
      if (data.status !== 'success') return setListenProblem(data.reason || 'invalid_host')
      const landed = await settle()
      if (!landed) return
      await apply(landed)
      if (landed.listen.host !== targetHost) return setListenProblem('failed')
      setRestarted(true)
      setTimeout(() => setRestarted(false), 3000)
    } catch (e) {
      notice((e as Error).message)
    } finally {
      setListenBusy(false)
    }
  }

  const hostOptions = [
    { value: '127.0.0.1', label: '127.0.0.1', hint: t('config_listen_local') },
    { value: '0.0.0.0', label: '0.0.0.0', hint: t('config_listen_all') },
    { value: 'custom', label: t('config_listen_custom') },
  ]

  const linkBase = (state?.public_url || lan[0] || baseUrl).replace(/\/+$/, '')

  return (
    <div className="space-y-5">
      <Card icon={<Globe size={16} />} title={t('config_public_url')} subtitle={t('config_public_url_desc')}>
        <div className="space-y-4">
          <Field label={t('config_public_url_label')} labelTip={t('config_public_url_hint')}>
            <div className="flex gap-2">
              <TextInput
                spellCheck={false}
                className="font-mono"
                value={publicUrl}
                placeholder={lan[0] || baseUrl}
                onChange={(e) => setPublicUrl(e.target.value)}
              />
              <Btn variant="primary" className="flex-shrink-0" onClick={() => void savePublicUrl()}>
                {t('config_save')}
              </Btn>
            </div>
            {status && (
              <p className={`text-xs mt-1.5 ${status.error ? 'text-danger' : 'text-accent'}`}>{status.text}</p>
            )}
          </Field>

          {state?.listen?.port ? (
            <div className="pt-4 border-t border-default">
              <Field label={t('config_listen_host')} labelTip={t('config_listen_host_tip')}>
                <div className="flex gap-2">
                  <div className={listenChoice === 'custom' ? 'w-56 flex-shrink-0' : 'flex-1 min-w-0'}>
                    <Dropdown
                      value={listenChoice}
                      options={hostOptions}
                      onChange={(v) => {
                        setListenChoice(v)
                        setListenProblem('')
                      }}
                    />
                  </div>
                  {listenChoice === 'custom' && (
                    <TextInput
                      autoFocus={!customHost}
                      spellCheck={false}
                      className="font-mono"
                      value={customHost}
                      placeholder={t('config_listen_custom_placeholder')}
                      onChange={(e) => {
                        setCustomHost(e.target.value)
                        setListenProblem('')
                      }}
                    />
                  )}
                  <span className="self-center text-content-tertiary">:</span>
                  <div
                    className="w-24 flex-shrink-0"
                    title={state.port_fixed ? t('config_listen_port_fixed') : undefined}
                  >
                    <TextInput className="font-mono" value={state.listen.port} disabled readOnly />
                  </div>
                  <Btn
                    variant="primary"
                    className="flex-shrink-0"
                    disabled={listenBusy || !changed}
                    onClick={() => void saveListenHost()}
                  >
                    {t(
                      listenBusy
                        ? 'config_listen_restarting'
                        : restarted
                          ? 'config_listen_restarted'
                          : 'config_listen_apply',
                    )}
                  </Btn>
                </div>
                {shownProblem ? (
                  <p className="text-xs text-danger mt-1.5">
                    {t(`config_listen_${shownProblem}`)}
                    {shownProblem === 'password_required' && (
                      <button
                        type="button"
                        onClick={onGoToPassword}
                        className="ml-1.5 inline-flex items-center gap-1 text-accent hover:underline cursor-pointer"
                      >
                        {t('shares_go_settings')}
                        <ArrowRight size={11} />
                      </button>
                    )}
                  </p>
                ) : (
                  lan.length > 0 && (
                    <div className="mt-2 flex flex-wrap items-center gap-1.5 text-xs text-content-tertiary">
                      <span>{t('config_listen_lan')}</span>
                      {lan.map((u) => (
                        <span
                          key={u}
                          className="inline-flex items-center gap-1 pl-2 pr-0.5 py-0.5 rounded-md bg-surface-2 font-mono text-content-secondary"
                        >
                          {u}
                          <CopyButton
                            text={u}
                            className="p-1 text-content-tertiary hover:text-content-secondary cursor-pointer"
                          />
                        </span>
                      ))}
                    </div>
                  )
                )}
              </Field>
            </div>
          ) : null}
        </div>
      </Card>

      <ChatApiCard baseUrl={linkBase} />

      <GuestSharesCard base={linkBase} onNotice={notice} onGoToPassword={onGoToPassword} />

      {toast && (
        <div className={`art-toast${toast.shown ? ' show' : ''}`} style={{ position: 'fixed', zIndex: 70 }}>
          {toast.text}
        </div>
      )}
    </div>
  )
}

export default IntegrationsTab
