import React, { useState } from 'react'
import { KeyRound, Laptop, Loader2, PlugZap, RotateCw, ServerOff, ShieldAlert } from 'lucide-react'
import { t, tf } from '../../i18n'
import { InstanceError, instanceHost, type Instance } from '../../api/instances'
import { useInstanceStore, type RemoteProblemReason } from '../../store/instanceStore'
import { usePlatform } from '../../hooks/usePlatform'
import WindowControls from '../../layout/WindowControls'
import { Btn } from '../../pages/settings/primitives'
import { failureText } from './failure'

export type { RemoteProblemReason }

const ICONS: Record<RemoteProblemReason, React.ReactNode> = {
  unreachable: <PlugZap size={26} />,
  auth_lost: <KeyRound size={26} />,
  wrong_device: <ShieldAlert size={26} />,
  not_cowagent: <ServerOff size={26} />,
  outdated: <ServerOff size={26} />,
}

// Reasons with words of their own; the rest are explained by the connect error.
const WORDED = new Set<RemoteProblemReason>(['unreachable', 'auth_lost', 'wrong_device'])

/** Shown instead of the app when the device it drives can't be used. */
const RemoteProblem: React.FC<{
  instance: Instance
  reason: RemoteProblemReason
  onRetry: () => Promise<void> | void
}> = ({ instance, reason, onRetry }) => {
  const { isWin } = usePlatform()
  const switchTo = useInstanceStore((s) => s.switchTo)
  const openAdd = useInstanceStore((s) => s.openAdd)
  const [retrying, setRetrying] = useState(false)

  const retry = async () => {
    setRetrying(true)
    try {
      await onRetry()
    } finally {
      setRetrying(false)
    }
  }

  const worded = WORDED.has(reason)
  const title = tf(worded ? `devices_problem_${reason}_title` : 'devices_problem_other_title', { name: instance.name })
  const body = worded
    ? t(`devices_problem_${reason}`)
    : failureText(new InstanceError(reason, 0, instanceHost(instance.url)))
  const repair = reason === 'auth_lost' || reason === 'wrong_device'

  return (
    <div className="h-screen w-screen flex flex-col bg-base text-content">
      <div className="titlebar-drag h-[44px] flex-shrink-0 flex items-center justify-end px-2">
        {isWin && <WindowControls />}
      </div>
      <div className="flex-1 flex items-center justify-center px-6 pb-16">
        <div className="w-full max-w-sm text-center">
          <div
            className={`w-14 h-14 mx-auto rounded-2xl flex items-center justify-center ${
              reason === 'unreachable' ? 'bg-[color-mix(in_srgb,var(--warning)_10%,transparent)] text-warning' : 'bg-danger-soft text-danger'
            }`}
          >
            {ICONS[reason]}
          </div>
          <h2 className="mt-5 text-lg font-semibold text-content">{title}</h2>
          <p className="mt-1 text-xs font-mono text-content-tertiary">{instance.url}</p>
          <p className="mt-3 text-sm text-content-secondary leading-relaxed">{body}</p>
          <div className="mt-7 flex flex-col gap-2">
            {repair ? (
              <Btn variant="primary" onClick={() => openAdd({ url: instance.url, replaceId: instance.id })}>
                {t('devices_repair')}
              </Btn>
            ) : (
              <Btn variant="primary" onClick={() => void retry()} disabled={retrying}>
                <span className="inline-flex items-center justify-center gap-1.5">
                  {retrying ? <Loader2 size={14} className="animate-spin" /> : <RotateCw size={14} />}
                  {t('devices_retry')}
                </span>
              </Btn>
            )}
            <Btn onClick={() => switchTo('')}>
              <span className="inline-flex items-center justify-center gap-1.5">
                <Laptop size={14} />
                {t('devices_back_local')}
              </span>
            </Btn>
          </div>
        </div>
      </div>
    </div>
  )
}

export default RemoteProblem
