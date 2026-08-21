import React, { useState, useEffect, useRef } from 'react'
import { Download } from 'lucide-react'
import { t } from '../i18n'
import apiClient from '../api/client'

interface LogsPageProps {
  baseUrl: string
}

const LogsPage: React.FC<LogsPageProps> = ({ baseUrl }) => {
  const [logs, setLogs] = useState<string[]>([])
  const [autoScroll, setAutoScroll] = useState(true)
  const [downloading, setDownloading] = useState(false)
  const containerRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    apiClient.setBaseUrl(baseUrl)

    const es = apiClient.createLogStream()

    es.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data)
        if (data.type === 'init' && data.content) {
          setLogs(data.content.split('\n').filter(Boolean))
        } else if (data.type === 'line' && data.content) {
          setLogs((prev) => {
            const next = [...prev, data.content]
            if (next.length > 2000) return next.slice(-1500)
            return next
          })
        }
      } catch { /* ignore */ }
    }

    return () => es.close()
  }, [baseUrl])

  useEffect(() => {
    if (autoScroll && containerRef.current) {
      containerRef.current.scrollTop = containerRef.current.scrollHeight
    }
  }, [logs, autoScroll])

  const handleScroll = () => {
    if (!containerRef.current) return
    const { scrollTop, scrollHeight, clientHeight } = containerRef.current
    setAutoScroll(scrollHeight - scrollTop - clientHeight < 50)
  }

  const handleDownload = async () => {
    if (downloading) return
    setDownloading(true)
    try {
      // Fetch as a blob (rather than a bare <a download>) so the auth token in
      // the query string is honored and the save uses our own file name.
      const res = await fetch(apiClient.getLogDownloadUrl())
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const blob = await res.blob()
      const url = URL.createObjectURL(blob)
      const ts = new Date().toISOString().replace(/[:T]/g, '-').slice(0, 19)
      const a = document.createElement('a')
      a.href = url
      a.download = `cowagent-${ts}.log`
      document.body.appendChild(a)
      a.click()
      a.remove()
      URL.revokeObjectURL(url)
    } catch (e) {
      // eslint-disable-next-line no-alert
      alert(`${t('logs_download_failed')}: ${(e as Error).message}`)
    } finally {
      setDownloading(false)
    }
  }

  const getLogColor = (line: string) => {
    if (line.includes('ERROR') || line.includes('error')) return 'text-red-400'
    if (line.includes('WARNING') || line.includes('warn')) return 'text-amber-400'
    if (line.includes('DEBUG')) return 'text-slate-500'
    return 'text-slate-300'
  }

  return (
    <div className="flex-1 overflow-y-auto p-6">
      <div className="max-w-5xl mx-auto">
        <div className="flex items-center justify-between mb-6">
          <div>
            <h2 className="text-xl font-bold text-slate-800 dark:text-slate-100">{t('logs_title')}</h2>
            <p className="text-sm text-slate-500 dark:text-slate-400 mt-1">{t('logs_desc')}</p>
          </div>
          <button
            type="button"
            onClick={handleDownload}
            disabled={downloading}
            className="inline-flex items-center gap-1 rounded-md border border-slate-300 dark:border-slate-600 bg-white dark:bg-slate-800 px-2 py-1 text-xs font-medium text-slate-700 dark:text-slate-200 transition-colors hover:bg-slate-50 dark:hover:bg-slate-700 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <Download size={13} />
            {t('logs_download')}
          </button>
        </div>

        {/* Terminal-style log viewer */}
        <div className="bg-slate-900 rounded-xl border border-slate-700 overflow-hidden shadow-lg">
          {/* Terminal header */}
          <div className="flex items-center gap-2 px-4 py-2.5 bg-slate-800 border-b border-slate-700">
            <div className="flex gap-1.5">
              <span className="w-3 h-3 rounded-full bg-red-500/80" />
              <span className="w-3 h-3 rounded-full bg-amber-500/80" />
              <span className="w-3 h-3 rounded-full bg-emerald-500/80" />
            </div>
            <span className="text-xs text-slate-400 ml-2 font-mono">run.log</span>
            <div className="flex-1" />
            <div className="flex items-center gap-1.5">
              <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
              <span className="text-xs text-slate-500">{t('logs_live')}</span>
            </div>
          </div>

          {/* Log content */}
          <div
            ref={containerRef}
            onScroll={handleScroll}
            className="p-4 overflow-y-auto font-mono text-xs leading-relaxed whitespace-pre-wrap break-all"
            style={{ height: 'calc(100vh - 272px)' }}
          >
            {logs.length > 0 ? (
              logs.map((line, i) => (
                <div key={i} className={getLogColor(line)}>{line}</div>
              ))
            ) : (
              <p className="text-slate-500">{t('logs_connecting')}</p>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

export default LogsPage
