import React, { useEffect, useRef, useState } from 'react'
import { Loader2, Check, RotateCcw } from 'lucide-react'
import { t } from '../i18n'
import apiClient from '../api/client'

type Provider = 'weixin' | 'feishu'
// 'downloading': Feishu only, the SDK bundle is fetched before the QR exists.
type Phase = 'loading' | 'downloading' | 'waiting' | 'scanned' | 'success' | 'error'

interface QrScanPanelProps {
  provider: Provider
  // Fired once the channel is connected so the page can refresh.
  onConnected: () => void
  // Multi-Agent only: when true, the connect that follows a successful scan
  // mints a NEW channel instance (instance_id '') rather than editing the
  // single legacy one. Undefined/false keeps the legacy single-instance path.
  newInstance?: boolean
  // Existing instance this card belongs to. Its QR is read off that channel,
  // and a confirm reconnects the same id; an empty id would mint a second card.
  instanceId?: string
}

const POLL_INTERVAL = 2000
// A live instance may still be fetching its code, or restarting after an
// expired attempt; keep asking for this many polls before giving up.
const WEIXIN_QR_PENDING_MAX_TRIES = 15

// Shared inline QR panel for WeChat login and Feishu app registration. Mirrors
// the web console: fetch a QR, poll its status, then connect the channel. The
// scan starts as soon as the panel mounts, so the caller decides when to show
// it rather than wiring up a separate "start" button.
const QrScanPanel: React.FC<QrScanPanelProps> = ({ provider, onConnected, newInstance, instanceId }) => {
  // When minting a new instance, pass instance_id ''; an existing card passes
  // its own id. Omit it entirely for the legacy per-type path.
  const instanceArg = newInstance ? '' : instanceId || undefined
  const [phase, setPhase] = useState<Phase>('loading')
  const [qr, setQr] = useState('')
  const [openLink, setOpenLink] = useState('')
  const [errMsg, setErrMsg] = useState('')
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const aliveRef = useRef(true)

  const stopPoll = () => {
    if (timerRef.current) {
      clearTimeout(timerRef.current)
      timerRef.current = null
    }
  }

  const fail = (msg: string) => {
    if (!aliveRef.current) return
    setPhase('error')
    setErrMsg(msg)
  }

  // ---- WeChat: GET qr, POST poll {scaned|confirmed|expired} -----------------
  const pollWeixin = () => {
    timerRef.current = setTimeout(async () => {
      if (!aliveRef.current) return
      try {
        const data = await apiClient.weixinQrAction('poll')
        if (!aliveRef.current) return
        if (data.status !== 'success') return pollWeixin()
        const s = data.qr_status as string
        if (s === 'confirmed') {
          setPhase('success')
          await apiClient.channelAction('connect', 'weixin', {}, instanceArg)
          if (aliveRef.current) onConnected()
        } else if (s === 'expired' && (data.qr_image || data.qrcode_url)) {
          setQr((data.qr_image as string) || (data.qrcode_url as string))
          setPhase('waiting')
          pollWeixin()
        } else if (s === 'scaned') {
          setPhase('scanned')
          pollWeixin()
        } else {
          pollWeixin()
        }
      } catch {
        pollWeixin()
      }
    }, POLL_INTERVAL)
  }

  // ---- WeChat, QR owned by the running channel ------------------------------
  // A live channel that lost its login runs its own scan loop, so the console
  // has no QR session to poll — watch the channel's login_status instead. The
  // channel also swaps in a fresh QR when the old one expires, so re-read it
  // every few ticks.

  // Returns false once the channel gave up on its own scan loop and the
  // console owns the QR session instead, so polling has to switch over.
  const refreshChannelQr = async (): Promise<boolean> => {
    try {
      const data = await apiClient.getWeixinQr(instanceId)
      if (!aliveRef.current || data.status !== 'success') return true
      const img = data.qr_image || data.qrcode_url
      if (img) setQr(img)
      return data.source === 'channel'
    } catch {
      return true
    }
  }

  const pollWeixinChannel = (tick = 0) => {
    timerRef.current = setTimeout(async () => {
      if (!aliveRef.current) return
      let handedOver = false
      try {
        const data = await apiClient.getChannelsFull()
        if (!aliveRef.current) return
        const wx = instanceId
          ? (data.instances || []).find((c) => c.instance_id === instanceId)
          : (data.channels || []).find((c) => c.name === 'weixin')
        if (wx?.login_status === 'logged_in') {
          setPhase('success')
          onConnected()
          return
        }
        setPhase(wx?.login_status === 'scanned' ? 'scanned' : 'waiting')
        if (tick % 5 === 4) handedOver = !(await refreshChannelQr())
      } catch {
        // Keep watching: a transient API failure shouldn't kill the panel.
      }
      if (!aliveRef.current) return
      if (handedOver) pollWeixin()
      else pollWeixinChannel(tick + 1)
    }, POLL_INTERVAL)
  }

  const startWeixin = async () => {
    setPhase('loading')
    try {
      let data = await apiClient.getWeixinQr(instanceId)
      let pendingTries = 0
      while (data.status === 'pending' && pendingTries < WEIXIN_QR_PENDING_MAX_TRIES) {
        pendingTries += 1
        await new Promise((r) => setTimeout(r, POLL_INTERVAL))
        if (!aliveRef.current) return
        data = await apiClient.getWeixinQr(instanceId)
      }
      if (!aliveRef.current) return
      if (data.status !== 'success') return fail(data.message || t('weixin_scan_fail'))
      setQr(data.qr_image || data.qrcode_url || '')
      setPhase('waiting')
      if (data.source === 'channel') pollWeixinChannel()
      else pollWeixin()
    } catch {
      fail(t('weixin_scan_fail'))
    }
  }

  // ---- Feishu: GET qr, POST poll {done|expired|denied|error} ----------------
  const pollFeishu = () => {
    timerRef.current = setTimeout(async () => {
      if (!aliveRef.current) return
      try {
        const data = await apiClient.feishuRegisterPoll()
        if (!aliveRef.current) return
        if (data.status !== 'success') return fail((data.message as string) || t('feishu_scan_fail'))
        const rs = data.register_status as string
        if (rs === 'downloading') {
          setPhase('downloading')
          return pollFeishu()
        }
        // The QR may only appear after the bundle finished downloading, in
        // which case the initial GET could not carry it.
        const img = (data.qr_image as string) || (data.qrcode_url as string)
        if (img) {
          setQr(img)
          setOpenLink((data.qrcode_url as string) || '')
          setPhase((p) => (p === 'downloading' ? 'waiting' : p))
        }
        if (rs === 'done') {
          setPhase('success')
          await apiClient.channelAction(
            'connect',
            'feishu',
            {
              feishu_app_id: data.app_id,
              feishu_app_secret: data.app_secret,
            },
            instanceArg
          )
          if (aliveRef.current) onConnected()
        } else if (rs === 'expired') {
          fail(t('feishu_scan_expired'))
        } else if (rs === 'denied') {
          fail(t('feishu_scan_denied'))
        } else if (rs === 'error') {
          fail((data.message as string) || t('feishu_scan_fail'))
        } else {
          pollFeishu()
        }
      } catch {
        pollFeishu()
      }
    }, POLL_INTERVAL)
  }

  const startFeishu = async () => {
    setPhase('loading')
    try {
      const data = await apiClient.getFeishuRegister()
      if (!aliveRef.current) return
      if (data.status !== 'success') return fail(data.message || t('feishu_scan_fail'))
      if (data.register_status === 'downloading') {
        // First run in the desktop build: the SDK bundle lands before the QR.
        setPhase('downloading')
        return pollFeishu()
      }
      setQr(data.qr_image || data.qrcode_url || '')
      setOpenLink(data.qrcode_url || '')
      setPhase('waiting')
      pollFeishu()
    } catch {
      fail(t('feishu_scan_fail'))
    }
  }

  const start = () => {
    stopPoll()
    if (provider === 'weixin') void startWeixin()
    else void startFeishu()
  }

  useEffect(() => {
    aliveRef.current = true
    start()
    return () => {
      aliveRef.current = false
      stopPoll()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [provider])

  const isWeixin = provider === 'weixin'
  const desc = isWeixin ? t('weixin_scan_desc') : t('feishu_scan_desc')
  const tip = isWeixin ? t('weixin_qr_tip') : t('feishu_scan_tip')
  const statusText = isWeixin
    ? phase === 'scanned'
      ? t('weixin_scan_scanned')
      : t('weixin_scan_waiting')
    : t('feishu_scan_waiting')

  return (
    <div className="flex flex-col items-center py-2">
      {phase === 'loading' && (
        <div className="flex items-center text-content-tertiary py-10 text-sm">
          <Loader2 size={16} className="animate-spin mr-2" />
          {isWeixin ? t('weixin_scan_loading') : t('feishu_scan_loading')}
        </div>
      )}

      {phase === 'downloading' && (
        <div className="flex flex-col items-center py-10">
          <div className="flex items-center text-content-tertiary text-sm">
            <Loader2 size={16} className="animate-spin mr-2" />
            {t('feishu_sdk_downloading')}
          </div>
          <p className="text-xs text-content-tertiary mt-2">{t('feishu_sdk_downloading_tip')}</p>
        </div>
      )}

      {(phase === 'waiting' || phase === 'scanned') && (
        <>
          <p className="text-sm text-content-secondary mb-3 text-center">{desc}</p>
          <div className="bg-white p-2.5 rounded-card border border-subtle mb-3">
            {qr ? (
              <img src={qr} alt="QR" className="w-44 h-44" style={{ imageRendering: 'pixelated' }} />
            ) : (
              <div className="w-44 h-44 flex items-center justify-center text-content-tertiary text-xs">QR</div>
            )}
          </div>
          <p className={`text-xs mb-1 ${phase === 'scanned' ? 'text-accent' : 'text-warning'}`}>{statusText}</p>
          <p className="text-xs text-content-tertiary">{tip}</p>
          {openLink && (
            <a
              href={openLink}
              target="_blank"
              rel="noopener noreferrer"
              className="text-xs text-info hover:underline mt-2"
            >
              {t('feishu_scan_open_link')}
            </a>
          )}
        </>
      )}

      {phase === 'success' && (
        <div className="flex flex-col items-center py-8">
          <div className="w-12 h-12 rounded-full bg-accent-soft flex items-center justify-center mb-3">
            <Check size={22} className="text-accent" />
          </div>
          <p className="text-sm font-medium text-accent">
            {isWeixin ? t('weixin_scan_success') : t('feishu_scan_success')}
          </p>
        </div>
      )}

      {phase === 'error' && (
        <div className="flex flex-col items-center py-8">
          <p className="text-sm text-danger text-center mb-3">{errMsg}</p>
          <button
            onClick={start}
            className="inline-flex items-center gap-1.5 px-4 py-1.5 rounded-btn border border-strong text-sm text-content-secondary hover:bg-inset-2 cursor-pointer transition-colors"
          >
            <RotateCcw size={13} />
            {t('feishu_scan_retry')}
          </button>
        </div>
      )}
    </div>
  )
}

export default QrScanPanel
