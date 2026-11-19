import React, { useState, useEffect, useRef, useLayoutEffect, useCallback } from 'react'
import { createPortal } from 'react-dom'
import { ChevronDown, Info } from 'lucide-react'
import { t } from '../../i18n'

// Shared presentational building blocks for the settings tabs.

/**
 * A small info icon that reveals its help on hover, so a form label can carry a
 * hint without a permanent paragraph under the field. The bubble is rendered in
 * a body-level portal (never clipped by a scroll container) and preserves line
 * breaks in `tip`, so multi-line help (e.g. one line per option) lays out as
 * written.
 */
export const FieldTip: React.FC<{ tip: string }> = ({ tip }) => {
  const [pos, setPos] = useState<{ x: number; y: number } | null>(null)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const show = useCallback((el: HTMLElement) => {
    if (timerRef.current) clearTimeout(timerRef.current)
    timerRef.current = setTimeout(() => {
      const r = el.getBoundingClientRect()
      setPos({ x: r.left + r.width / 2, y: r.top - 8 })
    }, 100)
  }, [])
  const hide = useCallback(() => {
    if (timerRef.current) clearTimeout(timerRef.current)
    setPos(null)
  }, [])

  if (!tip) return null
  return (
    <>
      <span
        className="inline-flex items-center justify-center text-content-tertiary hover:text-content-secondary cursor-help"
        onMouseEnter={(e) => show(e.currentTarget)}
        onMouseLeave={hide}
      >
        <Info size={13} />
      </span>
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
              whiteSpace: 'pre-line',
            }}
            className="px-2.5 py-1.5 rounded-md bg-elevated border border-default shadow-lg text-[11px] leading-snug text-content max-w-[280px]"
          >
            {tip}
          </div>,
          document.body,
        )}
    </>
  )
}

export const Card: React.FC<{
  icon: React.ReactNode
  title: string
  subtitle?: string
  // Optional trailing element on the header row (right-aligned), e.g. a small
  // secondary action such as the chat-fallback gear on the main model card.
  action?: React.ReactNode
  children: React.ReactNode
}> = ({ icon, title, subtitle, action, children }) => (
  <div className="rounded-card border border-default bg-surface p-5">
    <div className="flex items-center gap-2.5 mb-4">
      <div className="w-8 h-8 rounded-lg bg-accent-soft text-accent flex items-center justify-center">{icon}</div>
      <div className="min-w-0">
        <h3 className="font-semibold text-content leading-tight">{title}</h3>
        {subtitle && <p className="text-xs text-content-tertiary mt-0.5">{subtitle}</p>}
      </div>
      {action && <div className="ml-auto flex-shrink-0">{action}</div>}
    </div>
    {children}
  </div>
)

export const Field: React.FC<{
  label: string
  hint?: string
  // Help shown in an info icon next to the label (hover), instead of a
  // permanent line under the field. Supports \n for multi-line hints.
  labelTip?: string
  // Draw a red asterisk after the label to mark the field as required.
  required?: boolean
  // Optional trailing element on the label row (right-aligned), e.g. a helper
  // link. Kept generic so any build can attach an action next to a field.
  labelAction?: React.ReactNode
  children: React.ReactNode
}> = ({ label, hint, labelTip, required, labelAction, children }) => (
  <div>
    <div className="mb-1.5 flex items-center justify-between gap-2">
      <div className="flex items-center gap-1.5 min-w-0">
        <label className="block text-sm font-medium text-content-secondary">
          {label}
          {required && <span className="text-danger ml-0.5">*</span>}
        </label>
        {labelTip && <FieldTip tip={labelTip} />}
      </div>
      {labelAction}
    </div>
    {children}
    {hint && <p className="text-xs text-content-tertiary mt-1">{hint}</p>}
  </div>
)

export interface DropdownOption {
  value: string
  label: string
  hint?: string
}

export const Dropdown: React.FC<{
  value: string
  display?: string
  placeholder?: string
  options: DropdownOption[]
  disabled?: boolean
  // 'stack' (default) renders the hint on a dim second line; 'inline' renders it
  // as a dim label pushed to the right of the row, on the same line as the label
  // (e.g. an instance name on the left, its channel type on the right).
  hintAlign?: 'stack' | 'inline'
  onChange: (val: string) => void
}> = ({ value, display, placeholder, options, disabled, hintAlign = 'stack', onChange }) => {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  const menuRef = useRef<HTMLDivElement>(null)
  // The menu is rendered in a portal with fixed positioning so it's never
  // clipped by an ancestor's `overflow` (e.g. a modal's scroll container).
  // `top` is used when opening downward, `bottom` when the menu flips upward.
  const [rect, setRect] = useState<{
    left: number
    width: number
    maxHeight: number
    top?: number
    bottom?: number
  } | null>(null)

  const place = () => {
    const el = ref.current
    if (!el) return
    const r = el.getBoundingClientRect()
    const gap = 4
    const margin = 8 // keep the menu off the very edge of the viewport
    const below = window.innerHeight - r.bottom - gap - margin
    const above = r.top - gap - margin
    // Flip upward when there isn't enough room below AND there's more above,
    // so a trigger near the bottom edge doesn't drop its options off-screen.
    const flipUp = below < 240 && above > below
    const maxHeight = Math.max(120, Math.floor(flipUp ? above : below))
    setRect({
      left: r.left,
      width: r.width,
      maxHeight,
      ...(flipUp
        ? { bottom: window.innerHeight - r.top + gap }
        : { top: r.bottom + gap }),
    })
  }

  useLayoutEffect(() => {
    if (open) place()
  }, [open])

  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => {
      const target = e.target as Node
      if (ref.current?.contains(target) || menuRef.current?.contains(target)) return
      setOpen(false)
    }
    // Keep the fixed menu anchored to the trigger on scroll/resize by
    // re-measuring — NOT closing. Closing on scroll makes the dropdown vanish
    // the moment the user scrolls the settings page.
    document.addEventListener('mousedown', onDown)
    window.addEventListener('resize', place, true)
    window.addEventListener('scroll', place, true)
    return () => {
      document.removeEventListener('mousedown', onDown)
      window.removeEventListener('resize', place, true)
      window.removeEventListener('scroll', place, true)
    }
  }, [open])

  const current = display ?? options.find((o) => o.value === value)?.label ?? ''
  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        disabled={disabled}
        onClick={() => !disabled && setOpen((v) => !v)}
        className={`w-full flex items-center justify-between px-3 py-2 rounded-btn border bg-inset text-sm transition-colors ${
          disabled
            ? 'border-default text-content-tertiary cursor-not-allowed opacity-70'
            : 'border-strong text-content cursor-pointer hover:border-accent'
        }`}
      >
        <span className={`truncate ${current ? '' : 'text-content-tertiary'}`}>{current || placeholder || '--'}</span>
        <ChevronDown size={15} className={`text-content-tertiary transition-transform ${open ? 'rotate-180' : ''}`} />
      </button>
      {open &&
        rect &&
        createPortal(
          <div
            ref={menuRef}
            style={{
              position: 'fixed',
              left: rect.left,
              width: rect.width,
              maxHeight: rect.maxHeight,
              ...(rect.bottom !== undefined ? { bottom: rect.bottom } : { top: rect.top }),
            }}
            className="z-[100] overflow-y-auto rounded-btn border border-default bg-elevated shadow-lg py-1"
          >
            {options.length === 0 && (
              <div className="px-3 py-2 text-sm text-content-tertiary">{t('models_no_options')}</div>
            )}
            {options.map((o) => (
              <div
                key={o.value}
                // Select on mousedown, not click: the document-level mousedown
                // listener that closes the menu can otherwise fire first (e.g.
                // on the very first open, before menuRef is populated) and swallow
                // the click, which made the first option look unselectable.
                // preventDefault keeps focus stable; stopPropagation stops the
                // outside-close handler from also running for this same event.
                onMouseDown={(e) => {
                  e.preventDefault()
                  e.stopPropagation()
                  onChange(o.value)
                  setOpen(false)
                }}
                className={`px-3 py-2 text-sm cursor-pointer transition-colors ${
                  o.value === value ? 'bg-accent-soft text-accent' : 'text-content-secondary hover:bg-surface-2'
                }`}
              >
                {hintAlign === 'inline' ? (
                  <div className="flex items-center gap-2 min-w-0">
                    <span className="truncate">{o.label}</span>
                    {o.hint && (
                      <span className="ml-auto flex-shrink-0 text-xs text-content-tertiary">{o.hint}</span>
                    )}
                  </div>
                ) : (
                  <>
                    <div className="truncate">{o.label}</div>
                    {o.hint && <div className="text-xs text-content-tertiary mt-0.5 truncate">{o.hint}</div>}
                  </>
                )}
              </div>
            ))}
          </div>,
          document.body
        )}
    </div>
  )
}

export const Toggle: React.FC<{ checked: boolean; onChange: (v: boolean) => void }> = ({ checked, onChange }) => (
  <button
    type="button"
    role="switch"
    aria-checked={checked}
    onClick={() => onChange(!checked)}
    className={`relative inline-flex h-5 w-9 flex-shrink-0 items-center rounded-full transition-colors cursor-pointer ${
      checked ? 'bg-accent' : 'bg-surface-2 border border-strong'
    }`}
  >
    <span
      className={`inline-block h-3.5 w-3.5 rounded-full bg-white shadow transition-transform ${
        checked ? 'translate-x-[18px]' : 'translate-x-[3px]'
      }`}
    />
  </button>
)

export const TextInput = React.forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>((props, ref) => (
  <input
    ref={ref}
    {...props}
    // Typed text is primary; the placeholder is the dim tertiary color at
    // reduced opacity so it never reads as a real value while filling in fields
    // like a cron expression.
    className={`w-full px-3 py-2 rounded-btn border border-strong bg-inset text-sm text-content placeholder:text-content-tertiary placeholder:opacity-60 focus:outline-none focus:border-accent transition-colors ${
      props.className || ''
    }`}
  />
))
TextInput.displayName = 'TextInput'

export const SaveRow: React.FC<{ status: string; onSave: () => void; label?: string }> = ({
  status,
  onSave,
  label,
}) => (
  <div className="flex items-center justify-end gap-3 pt-1">
    <span className={`text-xs text-accent transition-opacity ${status ? 'opacity-100' : 'opacity-0'}`}>{status}</span>
    <button
      onClick={onSave}
      className="px-4 py-2 rounded-btn bg-accent text-accent-contrast hover:bg-accent-hover text-sm font-medium cursor-pointer transition-colors"
    >
      {label ?? t('config_save')}
    </button>
  </div>
)

export const MASK_RE = /[*•]/

const MODAL_WIDTH = { md: 'max-w-md', lg: 'max-w-2xl', xl: 'max-w-4xl' } as const

export const Modal: React.FC<{
  open: boolean
  title: string
  onClose: () => void
  children: React.ReactNode
  footer?: React.ReactNode
  // Optional content shown in the header, right-aligned before the close button
  // (e.g. an owner chip), so it doesn't consume a full body row.
  headerRight?: React.ReactNode
  // Dialog width. 'md' (default) keeps the compact settings dialog; 'lg' gives
  // form-heavy dialogs (e.g. the task editor) more breathing room; 'xl' suits
  // browsing dialogs that lay out a grid of cards.
  size?: 'md' | 'lg' | 'xl'
  // Stack above another open modal. A confirm dialog spawned from inside a modal
  // (e.g. "delete this task?" over the task editor) must sit on top; both share
  // the base z-50 otherwise and the later-painted one wins, hiding the confirm.
  elevated?: boolean
}> = ({ open, title, onClose, children, footer, headerRight, size = 'md', elevated = false }) => {
  if (!open) return null
  // Portaled to <body>: a modal opened from inside a panel with a
  // backdrop-filter (glass themes) would otherwise be positioned and clipped
  // relative to that panel instead of the window.
  return createPortal(
    <div
      className={`fixed inset-0 ${elevated ? 'z-[60]' : 'z-50'} flex items-center justify-center bg-black/40 p-4`}
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose()
      }}
    >
      <div
        className={`w-full ${MODAL_WIDTH[size]} rounded-card border border-default bg-elevated shadow-xl`}
      >
        <div className="flex items-center justify-between gap-3 px-5 py-4 border-b border-default">
          <h3 className="font-semibold text-content flex-shrink-0">{title}</h3>
          <div className="flex items-center gap-3 min-w-0">
            {headerRight}
            <button
              onClick={onClose}
              className="text-content-tertiary hover:text-content cursor-pointer text-lg leading-none px-1 flex-shrink-0"
            >
              ×
            </button>
          </div>
        </div>
        <div className={`px-5 py-4 space-y-4 overflow-y-auto ${size === 'xl' ? 'h-[70vh]' : 'max-h-[60vh]'}`}>{children}</div>
        {footer && <div className="flex items-center justify-end gap-2 px-5 py-3.5 border-t border-default">{footer}</div>}
      </div>
    </div>,
    document.body
  )
}

export const Btn: React.FC<
  React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: 'primary' | 'ghost' | 'danger' }
> = ({ variant = 'ghost', className, children, ...props }) => {
  const styles =
    variant === 'primary'
      ? 'bg-accent text-accent-contrast hover:bg-accent-hover'
      : variant === 'danger'
        ? 'bg-danger-soft text-danger hover:bg-danger/15 border border-danger-border'
        : 'border border-strong text-content-secondary hover:bg-surface-2'
  return (
    <button
      {...props}
      className={`px-4 py-2 rounded-btn text-sm font-medium cursor-pointer transition-colors disabled:opacity-50 disabled:cursor-not-allowed ${styles} ${className || ''}`}
    >
      {children}
    </button>
  )
}
