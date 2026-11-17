import React, { useState } from 'react'
import { KeyRound, Laptop, Loader2, PlugZap, RotateCw, ServerOff } from 'lucide-react'
import { t, tf } from '../../i18n'
import type { Instance } from '../../api/instances'
import { useInstanceStore } from '../../store/instanceStore'
import { usePlatform } from '../../hooks/usePlatform'
import WindowControls from '../../layout/WindowControls'
import { Btn } from '../../pages/settings/primitives'

export type RemoteProblemReason = 'unreachable' | 'auth_lost' | 'not_instance'

const ICONS: Record<RemoteProblemReason, React.ReactNode> = {
  unreachable: <PlugZap size={26} />,
  auth_lost: <KeyRound size={26} />,
  not_instance: <ServerOff size={26} />,
}

/** Shown instead of the app when the instance it drives can't be used. */
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
          <h2 className="mt-5 text-lg font-semibold text-content">
            {tf(`instances_problem_${reason}_title`, { name: instance.name })}
          </h2>
          <p className="mt-1 text-xs font-mono text-content-tertiary">{instance.url}</p>
          <p className="mt-3 text-sm text-content-secondary leading-relaxed">{t(`instances_problem_${reason}`)}</p>
          <div className="mt-7 flex flex-col gap-2">
            {reason === 'auth_lost' ? (
              <Btn variant="primary" onClick={() => openAdd({ url: instance.url, replaceId: instance.id })}>
                {t('instances_repair')}
              </Btn>
            ) : (
              <Btn variant="primary" onClick={() => void retry()} disabled={retrying}>
                <span className="inline-flex items-center justify-center gap-1.5">
                  {retrying ? <Loader2 size={14} className="animate-spin" /> : <RotateCw size={14} />}
                  {t('instances_retry')}
                </span>
              </Btn>
            )}
            <Btn onClick={() => switchTo('')}>
              <span className="inline-flex items-center justify-center gap-1.5">
                <Laptop size={14} />
                {t('instances_back_local')}
              </span>
            </Btn>
          </div>
        </div>
      </div>
    </div>
  )
}

export default RemoteProblem
