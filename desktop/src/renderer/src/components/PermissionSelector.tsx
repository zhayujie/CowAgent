import React, { useCallback, useEffect } from 'react'
import { Check, Eye, LockOpen, Shield } from 'lucide-react'
import { t } from '../i18n'
import ComposerChip from './ComposerChip'
import { useSessionSettingsStore } from '../store/sessionSettingsStore'
import {
  PERMISSION_META,
  PERMISSION_MODE_ORDER,
  asPermissionMode,
  permLabel,
  type PermissionMode,
} from '../lib/permission'

const ICONS: Record<PermissionMode, React.ReactNode> = {
  'full-access': <LockOpen size={13} />,
  'workspace-write': <Shield size={13} />,
  'read-only': <Eye size={13} />,
}

interface PermissionSelectorProps {
  sessionId: string
}

const PermissionSelector: React.FC<PermissionSelectorProps> = ({ sessionId }) => {
  const cfg = useSessionSettingsStore((s) => (s.sessionId === sessionId ? s.cfg : null))
  const openMenu = useSessionSettingsStore((s) => s.openMenu)
  const setOpenMenu = useSessionSettingsStore((s) => s.setOpenMenu)
  const apply = useSessionSettingsStore((s) => s.apply)
  const refresh = useSessionSettingsStore((s) => s.refresh)
  const error = useSessionSettingsStore((s) => s.error)
  const open = openMenu === 'permission'

  const state = cfg?.permission
  const mode = asPermissionMode(state?.mode)
  const isGlobal = !state || state.source === 'global'
  const offered = (state?.modes?.length ? state.modes : PERMISSION_MODE_ORDER).filter(
    (m): m is PermissionMode => m in PERMISSION_META
  )

  useEffect(() => {
    if (!open) return
    const el = document.getElementById('permission-selector-chip')
    el?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
    refresh(sessionId)
  }, [open, refresh, sessionId])

  const close = useCallback(() => setOpenMenu(null), [setOpenMenu])

  const toggle = () => {
    if (open) {
      close()
      return
    }
    setOpenMenu('permission')
    if (!cfg) refresh(sessionId)
  }

  const select = async (next: PermissionMode | null) => {
    // Keep the menu open if the change fails, so the inline error is visible.
    const ok = await apply(sessionId, { permission: next })
    if (ok) close()
  }

  const tip =
    t('perm_tip').replace('{name}', permLabel(mode)) + (isGlobal ? ` · ${t('perm_follow_global')}` : '')

  return (
    <div id="permission-selector-chip">
      <ComposerChip
        icon={ICONS[mode]}
        label={permLabel(mode)}
        tip={tip}
        open={open}
        onToggle={toggle}
        onClose={close}
      >
        <div className="px-2.5 pt-1 pb-1.5 text-[11px] font-semibold text-content-tertiary">
          {t('perm_menu_title')}
        </div>
        {error && <div className="px-2.5 pb-1.5 text-[11px] text-red-500">{error}</div>}
        {PERMISSION_MODE_ORDER.filter((m) => offered.includes(m)).map((m) => {
          const active = m === mode
          const meta = PERMISSION_META[m]
          return (
            <button
              key={m}
              type="button"
              onClick={() => select(active && !isGlobal ? null : m)}
              className={`w-full flex items-start gap-2.5 px-2.5 py-2 rounded-lg text-left cursor-pointer transition-colors ${
                active ? 'bg-accent-soft text-accent' : 'hover:bg-surface-2 text-content'
              }`}
            >
              <span className="mt-0.5 shrink-0">{ICONS[m]}</span>
              <span className="flex-1 min-w-0">
                <span className="block text-[13px]">{t(meta.key)}</span>
                <span className={`block text-[11px] mt-0.5 leading-snug ${active ? 'text-accent/80' : 'text-content-tertiary'}`}>
                  {t(meta.descKey)}
                </span>
              </span>
              {active && <Check size={14} className="shrink-0 mt-0.5" />}
            </button>
          )
        })}
      </ComposerChip>
    </div>
  )
}

export default PermissionSelector
