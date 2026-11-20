import React, { useCallback, useEffect, useRef, useState } from 'react'
import {
  AlertTriangle,
  ArrowRight,
  ArrowRightLeft,
  Clock,
  Globe,
  HelpCircle,
  Info,
  Laptop,
  Link2,
  Loader2,
  LogOut,
  Monitor,
  MonitorSmartphone,
  Pencil,
  Plus,
  QrCode,
  RotateCw,
  Server,
  ShieldCheck,
  Smartphone,
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
import { instanceHost, type Instance } from '../../api/instances'
import { askConfirm } from '../../store/confirmStore'
import { guardDocEditors } from '../../store/docEditorStore'
import { useInstanceStore, type InstanceStatus } from '../../store/instanceStore'
import { StatusDot } from '../../components/instances/InstanceSwitcher'
import { failureText } from '../../components/instances/failure'
import Tooltip from '../../components/Tooltip'
import { Btn, Card } from './primitives'

type Pairing = PairingCode & { expiresAt: number; expired?: boolean }

// Off until the mobile app is published: hides the QR code and the app step.
const MOBILE_PAIRING = false
const PAIR_POLL_MS = 2000
const REFRESH_MS = 30000
const NAME_MAX = 60

const BTN_SM = '!h-8 !px-3 !py-0 !text-xs inline-flex items-center justify-center gap-1.5 whitespace-nowrap'
const BTN_ROW = '!h-7 !px-2.5 !py-0 !text-xs inline-flex items-center justify-center gap-1 whitespace-nowrap'

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

/** Whether another device could open `url`. */
function openElsewhere(url?: string): boolean {
  try {
    return !!url && !/^(localhost|127\.|\[::1\]$)/.test(new URL(url).hostname)
  } catch {
    return false
  }
}

const HelpTip: React.FC<{ text: string }> = ({ text }) => (
  <Tooltip label={text} multiline>
    <span className="inline-flex text-content-tertiary hover:text-content-secondary cursor-help">
      <HelpCircle size={13} />
    </span>
  </Tooltip>
)

const CardTitle: React.FC<{ text: string; tip: string }> = ({ text, tip }) => (
  <span className="inline-flex items-center gap-1.5">
    {text}
    <HelpTip text={tip} />
  </span>
)

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

const Notice: React.FC<{ tone?: 'warning' | 'plain'; children: React.ReactNode }> = ({ tone = 'plain', children }) => (
  <p
    className={`mt-4 flex items-start gap-2 text-xs leading-relaxed bg-surface-2 rounded-lg px-3 py-2.5 ${
      tone === 'warning' ? 'text-warning' : 'text-content-secondary'
    }`}
  >
    {tone === 'warning' ? (
      <AlertTriangle size={13} className="mt-0.5 flex-shrink-0" />
    ) : (
      <Info size={13} className="mt-0.5 flex-shrink-0" />
    )}
    <span>{children}</span>
  </p>
)

const GoLink: React.FC<{ onClick: () => void; children: React.ReactNode }> = ({ onClick, children }) => (
  <button
    type="button"
    onClick={onClick}
    className="ml-1.5 inline-flex items-center gap-1 text-accent hover:underline cursor-pointer"
  >
    {children}
  </button>
)

/** A name edited in place; Enter or leaving the field keeps it, Escape drops it. */
const NameInput: React.FC<{ value: string; onDone: (name: string | null) => void }> = ({ value, onDone }) => {
  const [text, setText] = useState(value)
  const done = useRef(false)
  const finish = (name: string | null) => {
    if (done.current) return
    done.current = true
    onDone(name)
  }
  return (
    <input
      autoFocus
      value={text}
      maxLength={NAME_MAX}
      onChange={(e) => setText(e.target.value)}
      onFocus={(e) => e.target.select()}
      onBlur={() => finish(text)}
      onKeyDown={(e) => {
        if (e.key === 'Enter') finish(text)
        if (e.key === 'Escape') finish(null)
      }}
      className="min-w-0 flex-1 max-w-xs px-2 py-0.5 -ml-2 rounded-md border border-accent bg-inset text-sm text-content focus:outline-none"
    />
  )
}

/** Settings > Devices: this device and its name, the devices this computer
 *  connects to, and the devices allowed to connect to the one in use. */
const DevicesTab: React.FC<{
  onGoToPassword: () => void
  onGoToIntegrations: () => void
}> = ({ onGoToPassword, onGoToIntegrations }) => {
  const instance = apiClient.getInstance()
  const {
    items,
    activeId,
    status,
    localName,
    refreshStatus,
    openAdd,
    switchTo,
    forget,
    noteDevice,
    renameRemote,
  } = useInstanceStore()

  const [list, setList] = useState<DeviceList | null>(null)
  const [loadFailed, setLoadFailed] = useState(false)
  const [net, setNet] = useState<IntegrationsState | null>(null)
  const [lan, setLan] = useState<string[]>([])
  const [pairing, setPairing] = useState<Pairing | null>(null)
  const [pairBusy, setPairBusy] = useState(false)
  // `self`, `out:<id>` or `in:<id>`: the one name being edited.
  const [renaming, setRenaming] = useState('')
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
      setList({
        devices: data.devices || [],
        current: data.current || '',
        instance: data.instance,
      })
      noteDevice(data.instance)
      setLoadFailed(false)
    } catch {
      setLoadFailed(true)
    }
  }, [noteDevice])

  useEffect(() => {
    void loadDevices()
    void refreshStatus()
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
  }, [loadDevices, refreshStatus])

  // ---- this device ------------------------------------------------------

  const name = list?.instance?.name || (instance ? instance.name : localName || t('devices_this_device'))

  const renameSelf = async (next: string | null) => {
    setRenaming('')
    const value = (next || '').trim()
    if (!value || value === name) return
    try {
      const res = await apiClient.renameSelf(value)
      if (res.status !== 'success' || !res.instance) throw new Error(res.message)
      setList((l) => l && { ...l, instance: res.instance })
      noteDevice(res.instance)
    } catch {
      notice(tf('devices_rename_failed', { name }))
    }
  }

  // ---- devices this computer connects to ---------------------------------

  const outStatus = (item: Instance): InstanceStatus =>
    item.id === activeId ? 'online' : item.token ? status[item.id] || 'checking' : 'offline'

  const outSub = (item: Instance, st: InstanceStatus): string => {
    if (!item.token) return t('devices_needs_pairing')
    if (st === 'other') return t('devices_status_other')
    if (st === 'offline') return t('devices_status_offline')
    if (st === 'checking') return t('devices_status_checking')
    return t('devices_status_online')
  }

  const switchOut = async (id: string) => {
    if (!(await guardDocEditors())) return
    switchTo(id)
  }

  const renameOut = async (item: Instance, next: string | null) => {
    setRenaming('')
    if (!next || !next.trim() || next.trim() === item.name) return
    try {
      await renameRemote(item.id, next)
    } catch (e) {
      const reason = (e as { reason?: string }).reason
      notice(reason && reason !== 'refused' ? failureText(e) : tf('devices_rename_failed', { name: item.name }))
    }
  }

  const forgetOut = async (item: Instance) => {
    const ok = await askConfirm({
      titleKey: 'devices_forget',
      msgKey: 'devices_forget_confirm',
      okKey: 'devices_forget',
      vars: { name: item.name },
    })
    if (ok) await forget(item.id)
  }

  // ---- devices connected to the one in use --------------------------------

  // Whoever runs a managed device controls how it is reached and what it is called.
  const managed = !!list?.instance?.managed
  const reachable = !!instance || managed || !net || openElsewhere(net.public_url) || lan.length > 0
  const accessNotice = !!net && !managed && (!reachable || !net.password_set)
  const current = list?.current || ''
  // This computer is listed only on a remote device, where it can disconnect.
  const devices = (list?.devices || []).filter((d) => instance || d.id !== current)

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

  const renameIn = async (device: PairedDevice, next: string | null) => {
    setRenaming('')
    const value = (next || '').trim()
    if (!value || value === device.name) return
    setList((l) => l && { ...l, devices: l.devices.map((d) => (d.id === device.id ? { ...d, name: value } : d)) })
    try {
      await apiClient.renameDevice(device.id, value)
    } catch {
      // the refresh below shows what the server kept
    }
    void loadDevices()
  }

  const removeIn = async (device: PairedDevice) => {
    if (device.id === current && instance) {
      const ok = await askConfirm({
        titleKey: 'devices_disconnect',
        msgKey: 'devices_disconnect_confirm',
        okKey: 'devices_disconnect',
        vars: { name: instance.name, local: localName || t('devices_this_device') },
      })
      if (ok) await forget(instance.id)
      return
    }
    const ok = await askConfirm({
      titleKey: 'devices_remove',
      msgKey: 'devices_remove_confirm',
      okKey: 'devices_remove',
      vars: { name: device.name },
    })
    if (!ok) return
    try {
      await apiClient.removeDevice(device.id)
      setList((l) => l && { ...l, devices: l.devices.filter((d) => d.id !== device.id) })
    } catch (e) {
      notice((e as Error).message)
    }
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
      {/* The device in use and its name */}
      <div
        className={`flex items-center gap-3 px-4 py-3 rounded-card border ${
          instance
            ? 'border-[color-mix(in_srgb,var(--accent)_35%,transparent)] bg-[color-mix(in_srgb,var(--accent)_8%,transparent)]'
            : 'border-default bg-surface'
        }`}
      >
        <div className="w-9 h-9 rounded-lg flex items-center justify-center flex-shrink-0 bg-accent-soft text-accent">
          {instance ? <Server size={16} /> : <Laptop size={16} />}
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 min-w-0">
            {renaming === 'self' ? (
              <NameInput value={name} onDone={(v) => void renameSelf(v)} />
            ) : (
              <>
                <span className="text-sm font-semibold text-content truncate">{name}</span>
                {list?.instance && !managed && (
                  <IconAction label={t('devices_rename_device')} onClick={() => setRenaming('self')}>
                    <Pencil size={12} />
                  </IconAction>
                )}
              </>
            )}
          </div>
          <div className="text-xs text-content-tertiary truncate">
            {joinMeta([
              instance ? t('devices_operating_remote') : t('devices_this_device'),
              !!instance && instanceHost(instance.url),
              list?.instance?.version && `v${list.instance.version}`,
            ])}
          </div>
        </div>
        {instance && (
          <Btn onClick={() => void switchOut('')} className={`${BTN_SM} flex-shrink-0`}>
            <span className="inline-flex items-center gap-1.5">
              <Laptop size={13} />
              {t('devices_back_local')}
            </span>
          </Btn>
        )}
      </div>

      {/* Devices this computer connects to */}
      <Card
        icon={<ArrowRightLeft size={16} />}
        title={<CardTitle text={t('devices_out_title')} tip={t('devices_out_tip')} />}
        subtitle={t('devices_out_desc')}
        action={
          <Btn onClick={() => openAdd()} className={BTN_SM}>
            <span className="inline-flex items-center gap-1.5">
              <Plus size={13} />
              {t('devices_connect_other')}
            </span>
          </Btn>
        }
      >
        {!items.length ? (
          <p className="py-4 text-center text-sm text-content-tertiary">{t('devices_out_empty')}</p>
        ) : (
          <div className="-mx-2 divide-y divide-subtle">
            {items.map((item) => {
              const st = outStatus(item)
              const on = item.id === activeId
              return (
                <div
                  key={item.id}
                  className={`group flex items-center gap-3 px-2 py-2.5 rounded-lg transition-colors hover:bg-[color-mix(in_srgb,var(--bg-surface-2)_60%,transparent)] ${
                    on ? 'bg-[color-mix(in_srgb,var(--accent-soft)_40%,transparent)]' : ''
                  }`}
                >
                  <div className="relative w-9 h-9 rounded-lg bg-surface-2 text-content-secondary flex items-center justify-center flex-shrink-0">
                    <Server size={15} />
                    <StatusDot status={st} className="absolute -right-0.5 -bottom-0.5" />
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2 min-w-0">
                      {renaming === `out:${item.id}` ? (
                        <NameInput value={item.name} onDone={(v) => void renameOut(item, v)} />
                      ) : (
                        <span className="text-sm font-medium text-content truncate">{item.name}</span>
                      )}
                      {on && <Chip tone="accent">{t('devices_current')}</Chip>}
                    </div>
                    <div
                      className={`mt-0.5 text-xs truncate ${
                        st === 'other' || !item.token ? 'text-danger' : 'text-content-tertiary'
                      }`}
                    >
                      {joinMeta([instanceHost(item.url), outSub(item, st)])}
                    </div>
                  </div>
                  <div className="flex items-center gap-0.5 opacity-0 group-hover:opacity-100 focus-within:opacity-100 transition-opacity">
                    {item.token && st !== 'other' && !item.managed && (
                      <IconAction label={t('devices_rename_device')} onClick={() => setRenaming(`out:${item.id}`)}>
                        <Pencil size={13} />
                      </IconAction>
                    )}
                    <IconAction danger label={t('devices_forget')} onClick={() => void forgetOut(item)}>
                      <Trash2 size={13} />
                    </IconAction>
                  </div>
                  {!on && item.token && st !== 'other' && (
                    <Btn onClick={() => void switchOut(item.id)} className={BTN_ROW}>
                      {t('devices_switch')}
                    </Btn>
                  )}
                  {(!item.token || st === 'other') && (
                    <Btn
                      onClick={() => openAdd({ url: item.url, replaceId: item.id })}
                      className={BTN_ROW}
                    >
                      <span className="inline-flex items-center gap-1">
                        <RotateCw size={12} />
                        {t('devices_repair')}
                      </span>
                    </Btn>
                  )}
                </div>
              )
            })}
          </div>
        )}
      </Card>

      {/* Devices connected to the one in use */}
      <Card
        icon={<ShieldCheck size={16} />}
        title={
          <CardTitle
            text={`${instance ? tf('devices_in_title_remote', { name }) : t('devices_in_title')}${
              devices.length ? ` (${devices.length})` : ''
            }`}
            tip={t('devices_in_tip')}
          />
        }
        subtitle={t('devices_in_desc')}
        action={
          <Btn
            variant={pairing ? 'ghost' : 'primary'}
            disabled={pairBusy || (!pairing && !reachable)}
            onClick={() => (pairing ? setPairing(null) : void startPairing())}
            className={BTN_SM}
          >
            <span className="inline-flex items-center gap-1.5">
              {pairBusy ? (
                <Loader2 size={13} className="animate-spin" />
              ) : pairing ? (
                <X size={13} />
              ) : (
                <QrCode size={13} />
              )}
              {pairing ? t('devices_cancel') : t('devices_let_connect')}
            </span>
          </Btn>
        }
      >
        {accessNotice && (
          <>
            {!reachable && (
              <Notice>
                {t('devices_local_only')}
                <GoLink onClick={onGoToIntegrations}>
                  {t('shares_go_settings')}
                  <ArrowRight size={11} />
                </GoLink>
              </Notice>
            )}
            {reachable && !net?.password_set && (
              <Notice tone="warning">
                {t('devices_no_password')}
                <GoLink onClick={onGoToPassword}>
                  {t('shares_go_settings')}
                  <ArrowRight size={11} />
                </GoLink>
              </Notice>
            )}
          </>
        )}

        {pairing && (
          <div className="mt-4 flex gap-6 p-5 rounded-xl border border-default bg-[color-mix(in_srgb,var(--bg-base)_60%,transparent)]">
            {MOBILE_PAIRING && (
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
                    className="absolute inset-0 m-auto w-28 !h-9 !px-2 !py-0 !text-xs inline-flex items-center justify-center shadow"
                    onClick={() => void startPairing()}
                  >
                    {t('devices_regenerate')}
                  </Btn>
                )}
              </div>
            )}
            <div className="min-w-0 flex-1 space-y-4">
              {MOBILE_PAIRING ? (
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
              ) : (
                <p className="text-sm leading-relaxed text-content-secondary">{t('devices_step_other')}</p>
              )}
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
                {pairing.expired && !MOBILE_PAIRING && (
                  <button
                    type="button"
                    onClick={() => void startPairing()}
                    className="inline-flex items-center gap-1.5 text-accent hover:underline cursor-pointer"
                  >
                    <RotateCw size={12} />
                    {t('devices_regenerate')}
                  </button>
                )}
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

        <div className={pairing || accessNotice ? 'mt-4' : ''}>
          {loadFailed && !devices.length ? (
            <p className="py-6 text-center text-sm text-content-tertiary">{t('devices_load_failed')}</p>
          ) : !list ? (
            <div className="py-6 flex justify-center text-content-tertiary">
              <Loader2 size={16} className="animate-spin" />
            </div>
          ) : !devices.length ? (
            <div className="py-6 text-center">
              <div className="w-11 h-11 mx-auto rounded-xl bg-surface-2 text-content-tertiary flex items-center justify-center mb-3">
                <Smartphone size={18} />
              </div>
              <p className="text-sm text-content-secondary">{t('devices_empty')}</p>
            </div>
          ) : (
            <div className="-mx-2 divide-y divide-subtle">
              {sorted.map((d) => {
                const isCurrent = d.id === current
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
                        {renaming === `in:${d.id}` ? (
                          <NameInput value={d.name} onDone={(v) => void renameIn(d, v)} />
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
                      <IconAction label={t('devices_rename_device')} onClick={() => setRenaming(`in:${d.id}`)}>
                        <Pencil size={13} />
                      </IconAction>
                      <IconAction
                        danger
                        label={
                          isCurrent ? t('devices_disconnect') : t('devices_remove')
                        }
                        onClick={() => void removeIn(d)}
                      >
                        {isCurrent ? <LogOut size={13} /> : <Trash2 size={13} />}
                      </IconAction>
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </div>
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
