import React, { useEffect, useRef } from 'react'
import { ChevronDown } from 'lucide-react'
import Tooltip from './Tooltip'

interface ComposerChipProps {
  icon: React.ReactNode
  label: string
  tip: string
  open: boolean
  onToggle: () => void
  onClose: () => void
  disabled?: boolean
  /** Model menu sits on the right of the composer row. */
  align?: 'start' | 'end'
  menuClassName?: string
  children: React.ReactNode
}

/**
 * Shared chip + popover used by the workspace / permission / model selectors
 * under the chat input. Matches WorkspaceSelector styling so the three chips
 * read as one family.
 */
const ComposerChip: React.FC<ComposerChipProps> = ({
  icon,
  label,
  tip,
  open,
  onToggle,
  onClose,
  disabled,
  align = 'start',
  menuClassName,
  children,
}) => {
  const rootRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) onClose()
    }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [open, onClose])

  return (
    <div ref={rootRef} className="relative min-w-0">
      <Tooltip label={tip}>
        <button
          type="button"
          onClick={onToggle}
          disabled={disabled}
          className={`inline-flex items-center gap-1.5 h-8 px-2 rounded-btn text-xs cursor-pointer transition-colors max-w-full min-w-0 disabled:opacity-50 ${
            open
              ? 'text-accent bg-accent-soft'
              : 'text-content-secondary hover:text-accent hover:bg-accent-soft'
          }`}
        >
          <span className="shrink-0">{icon}</span>
          <span className="composer-chip-label truncate">{label}</span>
          <ChevronDown size={11} className={`opacity-60 shrink-0 transition-transform ${open ? 'rotate-180' : ''}`} />
        </button>
      </Tooltip>

      {open && (
        <div
          className={`absolute bottom-full mb-1.5 max-h-[380px] overflow-y-auto rounded-xl border border-default bg-elevated shadow-xl z-30 p-1.5 ${
            align === 'end' ? 'right-0' : 'left-0'
          } ${menuClassName || 'w-80'}`}
        >
          {children}
        </div>
      )}
    </div>
  )
}

export default ComposerChip
