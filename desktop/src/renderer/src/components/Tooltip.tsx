import React, { useCallback, useRef, useState } from 'react'
import { createPortal } from 'react-dom'

type Placement = 'top' | 'bottom'

interface TooltipProps {
  label: string
  placement?: Placement
  /** Delay before showing, ms. Short by default so it feels instant. */
  delay?: number
  children: React.ReactElement
}

/**
 * Lightweight hover tooltip rendered in a body-level portal, so it is never
 * clipped by overflow containers (chat scroll area, panels). Faster and more
 * consistent than the native `title` attribute. Wraps a single interactive
 * child and positions itself relative to that child's bounding box.
 */
const Tooltip: React.FC<TooltipProps> = ({ label, placement = 'top', delay = 120, children }) => {
  const [pos, setPos] = useState<{ x: number; y: number } | null>(null)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const show = useCallback(
    (el: HTMLElement) => {
      if (timerRef.current) clearTimeout(timerRef.current)
      timerRef.current = setTimeout(() => {
        const r = el.getBoundingClientRect()
        setPos({
          x: r.left + r.width / 2,
          y: placement === 'top' ? r.top - 8 : r.bottom + 8,
        })
      }, delay)
    },
    [delay, placement],
  )

  const hide = useCallback(() => {
    if (timerRef.current) clearTimeout(timerRef.current)
    setPos(null)
  }, [])

  if (!label) return children

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
              transform: placement === 'top' ? 'translate(-50%, -100%)' : 'translate(-50%, 0)',
              pointerEvents: 'none',
              zIndex: 9999,
            }}
            className="px-2 py-1 rounded-md bg-elevated border border-default shadow-lg text-[11px] leading-none text-content whitespace-nowrap max-w-[320px] overflow-hidden text-ellipsis"
          >
            {label}
          </div>,
          document.body,
        )}
    </>
  )
}

export default Tooltip
