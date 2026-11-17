import React, { useCallback, useEffect, useRef, useState } from 'react'
import {
  AlertTriangle,
  ArrowLeftRight,
  ArrowRight,
  Clock,
  Globe,
  Info,
  Laptop,
  Link2,
  Loader2,
  LogOut,
  Monitor,
  MonitorSmartphone,
  Pencil,
  QrCode,
  Server,
  ShieldCheck,
  Smartphone,
  Terminal,
  Trash2,
  X,
} from 'lucide-react'
import { t, tf } from '../../i18n'
import apiClient, {
  lanUrls,
  type DeviceList,
  type IntegrationsState,
  type PairedDevice,
  type PairingCode,
} from '../../api/client'
import { instanceHost } from '../../api/instances'
import { askConfirm } from '../../store/confirmStore'
import { useInstanceStore } from '../../store/instanceStore'
import { StatusDot } from '../../components/instances/InstanceSwitcher'
import Tooltip from '../../components/Tooltip'
import { Btn, Card } from './primitives'

type Pairing = PairingCode & { expiresAt: number; expired?: boolean }

const PAIR_POLL_MS = 2000
const REFRESH_MS = 30000

const SEP = <span className="mx-1.5 text-[color-mix(in_srgb,var(--text-tertiary)_50%,transparent)]">·</span>

function joinMeta(parts: (string | false | undefined)[]): React.ReactNode[] {
  return parts
    .filter(Boolean)
    .flatMap((p, i) => (i ? [<React.Fragment key={`s${i}`}>{SEP}</React.Fragment>, p] : [p])) as React.ReactNode[]
}

function seenLabel(d: PairedDevice): string {
  if (d.online) return t('devices_online')
  const ts = d.last_seen_at || d.created_at
  if (!ts) return ''
  const mins = Math.floor((Date.now() / 1000 - ts) / 60)
  if (mins < 10) return t('devices_seen_now')
  if (mins < 60) return tf('devices_seen_minutes', { n: mins })
  if (mins < 60 * 24) return tf('devices_seen_hours', { n: Math.floor(mins / 60) })
  return tf('devices_seen_days', { n: Math.floor(mins / 1440) })
}

function DeviceIcon({ platform, size = 15 }: { platform: string; size?: number }) {
  if (platform === 'desktop') return <Monitor size={size} />
  if (platform === 'web') return <Globe size={size} />
  if (['ios', 'android', 'harmony'].includes(platform)) return <Smartphone size={size} />
  return <MonitorSmartphone size={size} />
}

const Chip: React.FC<{ tone?: 'accent' | 'online' | 'plain'; children: React.ReactNode }> = ({
  tone = 'plain',
  children,
}) => (
  <span
    className={`inline-flex items-center gap-1 h-5 px-2 rounded-full text-[11px] font-medium whitespace-nowrap ${
      tone === 'accent'
        ? 'bg-accent-soft text-accent'
        : tone === 'online'
          ? 'bg-[color-mix(in_srgb,var(--success)_10%,transparent)] text-success'
          : 'bg-surface-2 text-content-tertiary'
    }`}
  >
    {children}
  </span>
)

const IconAction: React.FC<{ label: string; onClick: () => void; danger?: boolean; children: React.ReactNode }> = ({
  label,
  onClick,
  danger,
  children,
}) => (
  <Tooltip label={label}>
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      className={`w-7 h-7 inline-flex items-center justify-center rounded-md text-content-tertiary cursor-pointer transition-colors hover:bg-surface-2 ${
        danger ? 'hover:text-danger' : 'hover:text-content'
      }`}
    >
      {children}
    </button>
  </Tooltip>
)

/** Settings > Devices, all about the instance this app drives: a line naming
 *  it, connecting one more device to it, and the devices that may reach it.
 *  Which instance the app drives belongs to the switcher. */
const DevicesTab: React.FC<{
  onGoToPassword: () => void
  onGoToIntegrations: () => void
}> = ({ onGoToPassword, onGoToIntegrations }) => {
  const instance = apiClient.getInstance()
  const { openManage, forget } = useInstanceStore()

  const [list, setList] = useState<DeviceList | null>(null)
  const [loadFailed, setLoadFailed] = useState(false)
  const [net, setNet] = useState<IntegrationsState | null>(null)
  const [lan, setLan] = useState<string[]>([])
  const [pairing, setPairing] = useState<Pairing | null>(null)
  const [pairBusy, setPairBusy] = useState(false)
  const [renaming, setRenaming] = useState<{ id: string; name: string } | null>(null)
  const [toast, setToast] = useState<{ text: string; shown: boolean } | null>(null)
  const [, setTick] = useState(0)
  const pairingRef = useRef<Pairing | null>(null)
  pairingRef.current = pairing
  const renamingRef = useRef(renaming)
  renamingRef.current = renaming

  const notice = useCallback((text: string) => setToast({ text, shown: true }), [])
  useEffect(() => {
    if (!toast?.shown) return
    const timer = setTimeout(() => setToast((v) => (v ? { ...v, shown: false } : v)), 2400)
    return () => clearTimeout(timer)
  }, [toast])

  const loadDevices = useCallback(async () => {
    try {
      const data = await apiClient.listDevices()
      if (data.status !== 'success') throw new Error(data.message)
      setList({ devices: data.devices || [], current: data.current || '', instance: data.instance })
      setLoadFailed(false)
    } catch {
      setLoadFailed(true)
    }
  }, [])

  useEffect(() => {
    void loadDevices()
    apiClient
      .getIntegrations()
      .then(async (data) => {
        if (data.status !== 'success') return
        const detected = await lanUrls(data)
        setLan(detected)
        setNet(data)
      })
      .catch(() => {})
    const timer = setInterval(() => {
      if (!renamingRef.current) void loadDevices()
    }, REFRESH_MS)
    return () => clearInterval(timer)
  }, [loadDevices])

  // ---- this instance ----------------------------------------------------

  const addresses = (() => {
    const out: string[] = []
    const add = (u?: string) => u && !out.includes(u) && out.push(u)
    if (instance) add(instance.url)
    add(net?.public_url)
    lan.forEach(add)
    if (!out.length) add(apiClient.getBaseUrl())
    return out
  })()
  const reachable = !!instance || !net || !!(net.public_url || lan.length)
  const devices = list?.devices || []
  const current = list?.current || ''
  const online = devices.filter((d) => d.online).length
  const name = list?.instance?.name || (instance ? instance.name : t('instances_this'))

  const startPairing = async () => {
    setPairBusy(true)
    try {
      const data = await apiClient.createPairing(instance ? instance.url : lan[0] || '')
      if (data.status !== 'success') {
        notice(data.reason === 'local_only' ? t('devices_local_only') : data.message || t('devices_pair_failed'))
        return
      }
      setPairing({ ...data, expiresAt: Date.now() + data.expires_in * 1000 })
    } catch {
      notice(t('devices_pair_failed'))
    } finally {
      setPairBusy(false)
    }
  }

  const pairingId = pairing && !pairing.expired ? pairing.pairing_id : ''
  useEffect(() => {
    if (!pairingId) return
    const timer = setInterval(async () => {
      const cur = pairingRef.current
      if (!cur || cur.pairing_id !== pairingId) return
      if (Date.now() >= cur.expiresAt) {
        setPairing({ ...cur, expired: true })
        return
      }
      setTick((n) => n + 1)
      try {
        const data = await apiClient.getPairing(pairingId)
        if (pairingRef.current?.pairing_id !== pairingId) return
        if (data.state === 'paired') {
          setPairing(null)
          notice(tf('devices_paired', { name: data.device?.name || '' }))
          void loadDevices()
        } else if (data.state === 'expired') {
          setPairing({ ...cur, expired: true })
        }
      } catch {
        // try again on the next tick
      }
    }, PAIR_POLL_MS)
    return () => clearInterval(timer)
  }, [pairingId, notice, loadDevices])

  const copyLink = () => {
    if (!pairing || pairing.expired) return
    navigator.clipboard
      .writeText(pairing.link)
      .then(() => notice(t('devices_link_copied')))
      .catch(() => {})
  }

  // ---- signed-in devices ------------------------------------------------

  const commitRename = async () => {
    const r = renamingRef.current
    renamingRef.current = null
    setRenaming(null)
    if (!r) return
    const device = devices.find((d) => d.id === r.id)
    const next = r.name.trim()
    if (!device || !next || next === device.name) return
    setList((l) => l && { ...l, devices: l.devices.map((d) => (d.id === r.id ? { ...d, name: next } : d)) })
    try {
      await apiClient.renameDevice(r.id, next)
    } catch {
      // the refresh below shows what the server kept
    }
    void loadDevices()
  }

  const removeDevice = async (device: PairedDevice) => {
    const isCurrent = device.id === current
    if (isCurrent && instance) {
      const ok = await askConfirm({
        titleKey: 'instances_sign_out',
        msgKey: 'instances_sign_out_confirm',
        okKey: 'instances_sign_out',
        vars: { name: instance.name },
      })
      if (ok) await forget(instance.id)
      return
    }
    const ok = await askConfirm({
      titleKey: isCurrent ? 'devices_sign_out_here' : 'devices_remove',
      msgKey: isCurrent ? 'devices_sign_out_here_confirm' : 'devices_remove_confirm',
      okKey: isCurrent ? 'devices_sign_out_here' : 'devices_remove',
      vars: { name: device.name },
    })
    if (!ok) return
    try {
      if (isCurrent) {
        await apiClient.authLogout()
        window.location.reload()
        return
      }
      await apiClient.removeDevice(device.id)
      setList((l) => l && { ...l, devices: l.devices.filter((d) => d.id !== device.id) })
    } catch (e) {
      notice((e as Error).message)
    }
  }

  const revokeOthers = async () => {
    const others = devices.filter((d) => d.id !== current).length
    if (!others) return
    const ok = await askConfirm({
      titleKey: 'devices_revoke_others',
      msgKey: 'devices_revoke_others_confirm',
      okKey: 'devices_revoke_others',
      vars: { n: String(others) },
    })
    if (!ok) return
    try {
      const res = await apiClient.revokeOtherDevices()
      if (res.status === 'success') notice(tf('devices_revoked', { n: res.removed || 0 }))
    } catch (e) {
      notice((e as Error).message)
    }
    void loadDevices()
  }

  const sorted = [...devices].sort(
    (a, b) =>
      Number(b.id === current) - Number(a.id === current) ||
      Number(!!b.online) - Number(!!a.online) ||
      (b.last_seen_at || b.created_at || 0) - (a.last_seen_at || a.created_at || 0),
  )

  const left = pairing ? Math.max(0, Math.round((pairing.expiresAt - Date.now()) / 1000)) : 0
  const clock = `${Math.floor(left / 60)}:${String(left % 60).padStart(2, '0')}`

  return (
    <div className="space-y-5">
      {/* Which instance everything below applies to */}
      <div className="flex items-center gap-3 px-4 py-2.5 rounded-card border border-[color-mix(in_srgb,var(--accent)_22%,transparent)] bg-[color-mix(in_srgb,var(--accent)_5%,transparent)]">
        <div className="w-8 h-8 rounded-lg bg-accent text-accent-contrast flex items-center justify-center flex-shrink-0">
          {instance ? <Server size={15} /> : <Laptop size={15} />}
        </div>
        <div className="min-w-0 flex-1">
          <div className="text-[11px] leading-4 text-content-tertiary">{t('devices_scope_label')}</div>
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1 min-w-0">
            <span className="text-sm font-semibold text-content truncate">{name}</span>
            <span className="text-xs font-mono text-content-tertiary truncate">{addresses[0] && instanceHost(addresses[0])}</span>
            {instance && <Chip tone="accent">{t('devices_instance_remote')}</Chip>}
            {list?.instance?.version && <Chip>v{list.instance.version}</Chip>}
            {online > 0 && (
              <Chip tone="online">
                <span className="w-1.5 h-1.5 rounded-full bg-success" />
                {tf('devices_online_count', { n: online })}
              </Chip>
            )}
          </div>
        </div>
        <Btn onClick={openManage} className="!px-3 !py-1.5 text-xs flex-shrink-0">
          <span className="inline-flex items-center gap-1.5">
            <ArrowLeftRight size={13} />
            {t('devices_scope_switch')}
          </span>
        </Btn>
      </div>

      {/* Connecting one more device */}
      <div className="rounded-card border border-default bg-surface p-5">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-lg bg-accent-soft text-accent flex items-center justify-center flex-shrink-0">
            <QrCode size={16} />
          </div>
          <div className="min-w-0 flex-1">
            <h3 className="font-semibold text-content">{t('devices_connect_title')}</h3>
            <p className="text-xs text-content-tertiary mt-0.5">{tf('devices_connect_desc', { name })}</p>
          </div>
          <Btn
            variant={pairing ? 'ghost' : 'primary'}
            disabled={pairBusy || (!pairing && !reachable)}
            onClick={() => (pairing ? setPairing(null) : void startPairing())}
            className="flex-shrink-0"
          >
            <span className="inline-flex items-center gap-1.5">
              {pairBusy ? <Loader2 size={14} className="animate-spin" /> : pairing ? <X size={14} /> : <QrCode size={14} />}
              {pairing ? t('devices_cancel') : t('devices_add')}
            </span>
          </Btn>
        </div>

        {net && !reachable && (
          <p className="relative mt-4 flex items-start gap-2 text-xs text-content-secondary bg-surface-2 rounded-lg px-3 py-2.5">
            <Info size={13} className="mt-px flex-shrink-0" />
            <span>
              {t('devices_local_only')}
              <button
                type="button"
                onClick={onGoToIntegrations}
                className="ml-1.5 inline-flex items-center gap-1 text-accent hover:underline cursor-pointer"
              >
                {t('shares_go_settings')}
                <ArrowRight size={11} />
              </button>
            </span>
          </p>
        )}
        {net && reachable && !net.password_set && (
          <p className="relative mt-4 flex items-start gap-2 text-xs text-warning bg-surface-2 rounded-lg px-3 py-2.5">
            <AlertTriangle size={13} className="mt-px flex-shrink-0" />
            <span>
              {t('devices_no_password')}
              <button
                type="button"
                onClick={onGoToPassword}
                className="ml-1.5 inline-flex items-center gap-1 text-accent hover:underline cursor-pointer"
              >
                {t('shares_go_settings')}
                <ArrowRight size={11} />
              </button>
            </span>
          </p>
        )}

        {pairing && (
          <div className="relative mt-5 flex gap-6 p-5 rounded-xl border border-default bg-[color-mix(in_srgb,var(--bg-base)_60%,transparent)]">
            <div className="relative flex-shrink-0 self-start">
              {pairing.qr_image ? (
                <img
                  src={pairing.qr_image}
                  alt="QR"
                  className={`w-44 h-44 rounded-xl bg-white p-2 shadow-sm ring-1 ring-black/5 ${
                    pairing.expired ? 'opacity-20' : ''
                  }`}
                />
              ) : (
                <div className="w-44 h-44 rounded-xl bg-surface-2 flex items-center justify-center text-xs text-content-tertiary">
                  {t('devices_no_qr')}
                </div>
              )}
              {pairing.expired && (
                <Btn
                  variant="primary"
                  className="absolute inset-0 m-auto w-28 h-9 !px-2 text-xs shadow"
                  onClick={() => void startPairing()}
                >
                  {t('devices_regenerate')}
                </Btn>
              )}
            </div>
            <div className="min-w-0 flex-1 space-y-4">
              <ol className="space-y-2 text-sm text-content-secondary">
                {[t('devices_step_app'), t('devices_step_other')].map((text, i) => (
                  <li key={i} className="flex gap-2.5">
                    <span className="w-5 h-5 rounded-full bg-accent-soft text-accent text-[11px] font-semibold flex items-center justify-center flex-shrink-0">
                      {i + 1}
                    </span>
                    <span className="leading-relaxed">{text}</span>
                  </li>
                ))}
              </ol>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <div className="text-xs text-content-tertiary mb-1">{t('devices_code')}</div>
                  <div
                    className={`font-mono text-[26px] leading-none font-semibold tracking-[0.18em] text-content select-all ${
                      pairing.expired ? 'line-through opacity-40' : ''
                    }`}
                  >
                    {pairing.code}
                  </div>
                </div>
                <div className="min-w-0">
                  <div className="text-xs text-content-tertiary mb-1">{t('devices_address')}</div>
                  {pairing.urls.map((u) => (
                    <div key={u} className="text-xs font-mono text-content-secondary break-all select-all">
                      {u}
                    </div>
                  ))}
                </div>
              </div>
              <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-xs">
                <span
                  className={`inline-flex items-center gap-1.5 ${pairing.expired ? 'text-danger' : 'text-content-tertiary'}`}
                >
                  <Clock size={12} />
                  {pairing.expired ? t('devices_expired') : tf('devices_expires_in', { t: clock })}
                </span>
                {!pairing.expired && (
                  <>
                    <button
                      type="button"
                      onClick={copyLink}
                      className="inline-flex items-center gap-1.5 text-accent hover:underline cursor-pointer"
                    >
                      <Link2 size={12} />
                      {t('devices_copy_link')}
                    </button>
                    <span className="inline-flex items-center gap-1.5 text-content-tertiary">
                      <Loader2 size={11} className="animate-spin" />
                      {t('devices_waiting')}
                    </span>
                  </>
                )}
              </div>
            </div>
          </div>
        )}

        {!pairing && (
          <>
            <div className="mt-5 grid grid-cols-2 gap-3">
              {[
                { icon: <Smartphone size={15} />, title: t('devices_method_app_title'), text: t('devices_method_app') },
                { icon: <Monitor size={15} />, title: t('devices_method_other_title'), text: t('devices_method_other') },
              ].map((m) => (
                <div key={m.title} className="flex items-start gap-3 p-3.5 rounded-xl bg-[color-mix(in_srgb,var(--bg-surface-2)_70%,transparent)]">
                  <div className="w-8 h-8 rounded-lg bg-elevated text-accent flex items-center justify-center flex-shrink-0 shadow-sm">
                    {m.icon}
                  </div>
                  <div className="min-w-0">
                    <div className="text-sm font-medium text-content">{m.title}</div>
                    <div className="mt-0.5 text-xs leading-relaxed text-content-tertiary">{m.text}</div>
                  </div>
                </div>
              ))}
            </div>
            <p className="mt-4 flex items-center gap-2 text-xs text-content-tertiary">
              <Terminal size={12} className="flex-shrink-0" />
              <span>
                {t('devices_cli_hint')
                  .split('{cmd}')
                  .flatMap((part, i) =>
                    i
                      ? [
                          <code key={i} className="px-1.5 py-px rounded bg-surface-2 font-mono text-[11px] text-content-secondary">
                            cow pair
                          </code>,
                          part,
                        ]
                      : [part],
                  )}
              </span>
            </p>
          </>
        )}
      </div>

      {/* Signed-in devices */}
      <Card
        icon={<ShieldCheck size={16} />}
        title={devices.length ? `${t('devices_connected_title')} (${devices.length})` : t('devices_connected_title')}
        subtitle={tf('devices_connected_desc', { name })}
        action={
          current && devices.some((d) => d.id !== current) ? (
            <Btn onClick={() => void revokeOthers()} className="!px-3 !py-1.5 text-xs">
              {t('devices_revoke_others')}
            </Btn>
          ) : undefined
        }
      >
        {loadFailed && !devices.length ? (
          <p className="py-6 text-center text-sm text-content-tertiary">{t('devices_load_failed')}</p>
        ) : !list ? (
          <div className="py-6 flex justify-center text-content-tertiary">
            <Loader2 size={16} className="animate-spin" />
          </div>
        ) : !devices.length ? (
          <div className="py-7 text-center">
            <div className="w-11 h-11 mx-auto rounded-xl bg-surface-2 text-content-tertiary flex items-center justify-center mb-3">
              <Smartphone size={18} />
            </div>
            <p className="text-sm text-content-secondary">{t('devices_empty')}</p>
            <p className="text-xs text-content-tertiary mt-1">{t('devices_empty_hint')}</p>
          </div>
        ) : (
          <div className="-mx-2 divide-y divide-subtle">
            {sorted.map((d) => {
              const isCurrent = d.id === current
              const editing = renaming?.id === d.id
              return (
                <div
                  key={d.id}
                  className={`group flex items-center gap-3 px-2 py-2.5 rounded-lg transition-colors hover:bg-[color-mix(in_srgb,var(--bg-surface-2)_60%,transparent)] ${
                    isCurrent ? 'bg-[color-mix(in_srgb,var(--accent-soft)_40%,transparent)]' : ''
                  }`}
                >
                  <div className="relative w-9 h-9 rounded-lg bg-surface-2 text-content-secondary flex items-center justify-center flex-shrink-0">
                    <DeviceIcon platform={d.platform} />
                    {d.online && <StatusDot status="online" className="absolute -right-0.5 -bottom-0.5" />}
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2 min-w-0">
                      {editing ? (
                        <input
                          autoFocus
                          value={renaming.name}
                          maxLength={60}
                          onChange={(e) => setRenaming({ id: d.id, name: e.target.value })}
                          onFocus={(e) => e.target.select()}
                          onBlur={() => void commitRename()}
                          onKeyDown={(e) => {
                            if (e.key === 'Enter') void commitRename()
                            if (e.key === 'Escape') {
                              renamingRef.current = null
                              setRenaming(null)
                            }
                          }}
                          className="min-w-0 flex-1 max-w-xs px-2 py-0.5 -ml-2 rounded-md border border-accent bg-inset text-sm text-content focus:outline-none"
                        />
                      ) : (
                        <span className="text-sm font-medium text-content truncate">{d.name}</span>
                      )}
                      {isCurrent && <Chip tone="accent">{t('devices_this')}</Chip>}
                    </div>
                    <div className="mt-0.5 text-xs text-content-tertiary truncate">
                      {joinMeta([
                        d.via === 'password' ? t('devices_via_password') : t('devices_via_pairing'),
                        d.app_version && `v${d.app_version}`,
                        d.origin && tf('devices_from_page', { origin: instanceHost(d.origin) }),
                        d.last_ip,
                      ])}
                    </div>
                  </div>
                  <span className={`text-xs whitespace-nowrap ${d.online ? 'text-success' : 'text-content-tertiary'}`}>
                    {seenLabel(d)}
                  </span>
                  <div className="flex items-center gap-0.5 opacity-0 group-hover:opacity-100 focus-within:opacity-100 transition-opacity">
                    <IconAction label={t('devices_rename')} onClick={() => setRenaming({ id: d.id, name: d.name })}>
                      <Pencil size={13} />
                    </IconAction>
                    <IconAction
                      danger
                      label={isCurrent ? (instance ? t('instances_sign_out') : t('devices_sign_out_here')) : t('devices_remove')}
                      onClick={() => void removeDevice(d)}
                    >
                      {isCurrent ? <LogOut size={13} /> : <Trash2 size={13} />}
                    </IconAction>
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </Card>

      {toast && (
        <div className={`art-toast${toast.shown ? ' show' : ''}`} style={{ position: 'fixed', zIndex: 70 }}>
          {toast.text}
        </div>
      )}
    </div>
  )
}

export default DevicesTab
