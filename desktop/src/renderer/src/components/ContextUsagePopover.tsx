import React, { useCallback, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { apiClient } from '../api/client'
import { t } from '../i18n'
import type { ContextUsage } from '../types'
import ContextUsageDonut, {
  CONTEXT_SLICE_COLORS,
  formatTokens,
  type ContextSliceKey,
} from './ContextUsageDonut'

const LEGEND: { key: ContextSliceKey; labelKey: string }[] = [
  { key: 'system', labelKey: 'ctx_system' },
  { key: 'tools', labelKey: 'ctx_tools' },
  { key: 'history', labelKey: 'ctx_history' },
  { key: 'free', labelKey: 'ctx_free' },
]

interface ContextUsagePopoverProps {
  sessionId: string
  children: React.ReactElement
}

/**
 * Hover card showing what is occupying the session's context window, anchored
 * to the clear-context button so the cost is visible before the button is used.
 *
 * Rendered in a body-level portal (like Tooltip) rather than as an absolute
 * panel, so the composer card's overflow can't clip it. Usage is fetched on
 * each open — it changes every turn, so caching it would show stale numbers.
 */
const ContextUsagePopover: React.FC<ContextUsagePopoverProps> = ({ sessionId, children }) => {
  const [pos, setPos] = useState<{ x: number; y: number } | null>(null)
  const [usage, setUsage] = useState<ContextUsage | null>(null)
  const [failed, setFailed] = useState(false)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  // Guards against a slow response landing after the pointer already left.
  const openRef = useRef(false)

  const show = useCallback(
    (el: HTMLElement) => {
      if (timerRef.current) clearTimeout(timerRef.current)
      timerRef.current = setTimeout(async () => {
        const r = el.getBoundingClientRect()
        openRef.current = true
        setUsage(null)
        setFailed(false)
        setPos({ x: r.left + r.width / 2, y: r.top - 8 })
        try {
          const res = await apiClient.getContextUsage(sessionId)
          if (openRef.current) setUsage(res)
        } catch {
          if (openRef.current) setFailed(true)
        }
      }, 120)
    },
    [sessionId],
  )

  const hide = useCallback(() => {
    if (timerRef.current) clearTimeout(timerRef.current)
    openRef.current = false
    setPos(null)
  }, [])

  const child = React.cloneElement(children, {
    onMouseEnter: (e: React.MouseEvent<HTMLElement>) => {
      show(e.currentTarget)
      children.props.onMouseEnter?.(e)
    },
    onMouseLeave: (e: React.MouseEvent<HTMLElement>) => {
      hide()
      children.props.onMouseLeave?.(e)
    },
    onClick: (e: React.MouseEvent<HTMLElement>) => {
      hide()
      children.props.onClick?.(e)
    },
  })

  const breakdown = usage?.breakdown
  const limit = usage?.limit ?? 0
  const used = usage?.used ?? 0
  const percent = limit > 0 ? Math.min(100, Math.round((used / limit) * 100)) : 0

  return (
    <>
      {child}
      {pos &&
        createPortal(
          <div
            style={{
              position: 'fixed',
              left: pos.x,
              top: pos.y,
              transform: 'translate(-50%, -100%)',
              pointerEvents: 'none',
              zIndex: 9999,
            }}
            className="w-[248px] p-3 rounded-xl bg-elevated border border-default shadow-xl"
          >
            <div className="flex items-baseline justify-between mb-2">
              <span className="text-[12px] font-medium text-content">{t('ctx_usage_title')}</span>
              {usage?.estimated && (
                <span className="text-[10px] text-content-tertiary">{t('ctx_estimated')}</span>
              )}
            </div>

            {failed ? (
              <div className="text-[11px] text-content-tertiary py-2">{t('ctx_error')}</div>
            ) : !usage ? (
              // Placeholder keeps the card from resizing when data lands.
              <div className="h-[96px]" />
            ) : !usage.available || !breakdown ? (
              <div className="text-[11px] text-content-tertiary py-2">{t('ctx_empty')}</div>
            ) : (
              <>
                <div className="flex justify-center mb-2">
                  <ContextUsageDonut
                    percent={percent}
                    slices={LEGEND.map((l) => ({ key: l.key, value: breakdown[l.key] }))}
                  />
                </div>
                <div className="space-y-1">
                  {LEGEND.map((l) => (
                    <div key={l.key} className="flex items-center gap-1.5 text-[11px]">
                      <span
                        className="w-2 h-2 rounded-sm shrink-0"
                        style={{ background: CONTEXT_SLICE_COLORS[l.key] }}
                      />
                      <span className="text-content-secondary flex-1 truncate">
                        {t(l.labelKey)}
                      </span>
                      <span className="text-content tabular-nums">
                        {formatTokens(breakdown[l.key])}
                      </span>
                    </div>
                  ))}
                </div>
                <div className="mt-2 pt-2 border-t border-default text-[10px] text-content-tertiary tabular-nums">
                  {t('ctx_used_of')
                    .replace('{used}', formatTokens(used))
                    .replace('{limit}', formatTokens(limit))}
                </div>
              </>
            )}
          </div>,
          document.body,
        )}
    </>
  )
}

export default ContextUsagePopover
