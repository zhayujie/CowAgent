import React, { useCallback, useEffect, useState } from 'react'
import { t } from '../i18n'

interface StatusScreenProps {
  status: 'connecting' | 'error'
  error?: string
  slow?: boolean
  // Recovering a backend that had already been serving, rather than a cold
  // start — the copy differs because the user was mid-session.
  reconnecting?: boolean
  onRetry: () => void
}

const StatusScreen: React.FC<StatusScreenProps> = ({ status, error, slow, reconnecting, onRetry }) => {
  const [dataDir, setDataDir] = useState('')

  useEffect(() => {
    if (status !== 'error') return
    window.electronAPI?.getDataDir().then(setDataDir).catch(() => setDataDir(''))
  }, [status])

  const openLogs = useCallback(() => {
    if (!dataDir) return
    void window.electronAPI?.openPath(dataDir)
  }, [dataDir])

  return (
    <div className="h-screen w-screen flex items-center justify-center bg-gray-50 dark:bg-[#111111]">
      <div className="text-center space-y-6 max-w-md px-8">
        <img src="./logo.jpg" alt="Agent" className="w-16 h-16 rounded-2xl mx-auto shadow-lg shadow-primary-500/20" />

        {status === 'connecting' && (
          <>
            <div className="space-y-2">
              <h1 className="text-xl font-bold text-slate-800 dark:text-slate-100">
                {reconnecting ? t('status_reconnecting') : t('status_starting')}
              </h1>
              <p className="text-sm text-slate-500 dark:text-slate-400">
                {slow
                  ? t('status_starting_slow')
                  : reconnecting
                    ? t('status_reconnecting_desc')
                    : t('status_starting_desc')}
              </p>
            </div>
            <div className="flex justify-center gap-1">
              <span className="w-2 h-2 rounded-full bg-primary-400 animate-pulse-dot" style={{ animationDelay: '0s' }} />
              <span className="w-2 h-2 rounded-full bg-primary-400 animate-pulse-dot" style={{ animationDelay: '0.2s' }} />
              <span className="w-2 h-2 rounded-full bg-primary-400 animate-pulse-dot" style={{ animationDelay: '0.4s' }} />
            </div>
          </>
        )}

        {status === 'error' && (
          <>
            <div className="space-y-2">
              <h1 className="text-xl font-bold text-slate-800 dark:text-slate-100">
                {t('status_error')}
              </h1>
              <p className="text-sm text-slate-500 dark:text-slate-400">
                {t('status_error_desc')}
              </p>
            </div>

            {/* The backend's own error line. Without it a user who can't reach
                the (unstarted) UI has no way to see why it failed. */}
            {error && (
              <p className="text-xs text-left font-mono break-words text-slate-500 dark:text-slate-400 bg-slate-100 dark:bg-white/5 rounded-lg px-3 py-2 max-h-32 overflow-auto">
                {error}
              </p>
            )}

            <div className="flex justify-center gap-2">
              <button
                onClick={onRetry}
                className="inline-flex items-center gap-2 px-4 py-2 bg-primary-500 hover:bg-primary-600 text-white rounded-lg transition-colors text-sm font-medium cursor-pointer"
              >
                <i className="fas fa-rotate-right text-xs" />
                {t('status_retry')}
              </button>
              {dataDir && (
                <button
                  onClick={openLogs}
                  className="inline-flex items-center gap-2 px-4 py-2 border border-slate-300 dark:border-white/15 text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-white/5 rounded-lg transition-colors text-sm font-medium cursor-pointer"
                >
                  <i className="fas fa-folder-open text-xs" />
                  {t('status_open_logs')}
                </button>
              )}
            </div>

            <p className="text-xs text-slate-400 dark:text-slate-500">{t('status_error_hint')}</p>
          </>
        )}
      </div>
    </div>
  )
}

export default StatusScreen
