import React, { useState } from 'react'
import { Check, Plus } from 'lucide-react'
import type { Theme } from '../theme/themes'
import { t } from '../i18n'

const FALLBACK_PREVIEW = { accent: '#4abe6e', bg: '#111', surface: '#1c1c1f' }

// Hover flyout around a menu row (`children`): the theme list plus an entry
// that opens the add-theme dialog.
const ThemeFlyout: React.FC<{
  children: React.ReactNode
  themes: Theme[]
  themeId: string
  onSelect: (id: string) => void
  onAdd: () => void
  // Called on open, e.g. to re-scan the themes folder.
  onOpen?: () => void
  className?: string
  // Positions the flyout against its containing block.
  flyoutClassName: string
}> = ({ children, themes, themeId, onSelect, onAdd, onOpen, className, flyoutClassName }) => {
  const [open, setOpen] = useState(false)
  const show = () => {
    setOpen(true)
    onOpen?.()
  }
  return (
    <div className={className} onMouseEnter={show} onMouseLeave={() => setOpen(false)}>
      <div onClick={show}>{children}</div>
      <div className={`absolute z-50 ${flyoutClassName} ${open ? '' : 'hidden'}`}>
        <div className="w-[212px] rounded-lg border border-default bg-elevated shadow-lg py-1">
          <div className="max-h-[296px] overflow-y-auto">
            {themes.map((th) => (
              <button
                key={th.id}
                onClick={() => onSelect(th.id)}
                className="w-full flex items-center gap-2.5 px-3 h-9 text-[13px] text-content-secondary hover:bg-surface-2 hover:text-content cursor-pointer transition-colors"
              >
                <ThemeSwatch preview={th.preview ?? FALLBACK_PREVIEW} />
                <span className="flex-1 text-left truncate">{th.name}</span>
                {themeId === th.id && <Check size={14} className="flex-shrink-0 text-accent" />}
              </button>
            ))}
          </div>
          <div className="my-1 border-t border-subtle" />
          <button
            onClick={onAdd}
            className="w-full flex items-center gap-2.5 px-3 h-9 text-[13px] text-content-secondary hover:bg-surface-2 hover:text-content cursor-pointer transition-colors"
          >
            <span className="flex-shrink-0 w-4 flex justify-center text-content-tertiary">
              <Plus size={15} />
            </span>
            <span className="flex-1 text-left truncate">{t('theme_add')}</span>
          </button>
        </div>
      </div>
    </div>
  )
}

// Tiny 3-color preview (bg / surface / accent) for a theme row.
const ThemeSwatch: React.FC<{ preview: { accent: string; bg: string; surface: string } }> = ({
  preview,
}) => (
  <span className="flex-shrink-0 inline-flex h-4 w-4 rounded-full overflow-hidden border border-default">
    <span className="w-1/3 h-full" style={{ background: preview.bg }} />
    <span className="w-1/3 h-full" style={{ background: preview.surface }} />
    <span className="w-1/3 h-full" style={{ background: preview.accent }} />
  </span>
)

export default ThemeFlyout
