import React, { useCallback, useLayoutEffect, useRef } from 'react'
import { Check, Cpu } from 'lucide-react'
import { product } from '@product'
import { t, localizedLabel } from '../i18n'
import ComposerChip from './ComposerChip'
import { useSessionSettingsStore } from '../store/sessionSettingsStore'

interface ModelSelectorProps {
  sessionId: string
}

// A build may replace the per-session model chip entirely (e.g. models sourced
// from a different catalog). Absent -> the built-in provider-grouped menu below.
const CustomSessionModelPicker = product.models?.SessionModelPicker

const CatalogModelSelector: React.FC<ModelSelectorProps> = ({ sessionId }) => {
  const cfg = useSessionSettingsStore((s) => (s.sessionId === sessionId ? s.cfg : null))
  const openMenu = useSessionSettingsStore((s) => s.openMenu)
  const setOpenMenu = useSessionSettingsStore((s) => s.setOpenMenu)
  const apply = useSessionSettingsStore((s) => s.apply)
  const refresh = useSessionSettingsStore((s) => s.refresh)
  const error = useSessionSettingsStore((s) => s.error)
  const open = openMenu === 'model'

  const state = cfg?.model
  const model = state?.model || ''
  const pinned = state?.source === 'session'
  const activeModel = state?.model || state?.global.model || ''
  const activeProvider = state?.provider || state?.global.provider || ''
  const providers = state?.providers || []
  // Display name only; the chip tip and every request keep the real model name.
  const modelAlias = model
    ? providers.find((p) => p.id === (state?.provider || activeProvider))?.labels?.[model] || ''
    : ''

  const close = useCallback(() => setOpenMenu(null), [setOpenMenu])

  // Once per opening, scroll the menu so the active model sits in the middle;
  // a model typed by hand has no row, so fall back to its provider's heading.
  const titleRef = useRef<HTMLDivElement>(null)
  const scrolledRef = useRef(false)
  useLayoutEffect(() => {
    if (!open) {
      scrolledRef.current = false
      return
    }
    const menu = titleRef.current?.parentElement
    if (!menu || scrolledRef.current || providers.length === 0) return
    const target =
      menu.querySelector<HTMLElement>('[data-active-model]') ||
      menu.querySelector<HTMLElement>('[data-current-provider]')
    scrolledRef.current = true
    if (!target) return
    const offset = target.getBoundingClientRect().top - menu.getBoundingClientRect().top + menu.scrollTop
    menu.scrollTop = Math.max(0, offset - (menu.clientHeight - target.offsetHeight) / 2)
  }, [open, providers])

  const toggle = () => {
    if (open) {
      close()
      return
    }
    setOpenMenu('model')
    // Catalog depends on which providers have keys — always refresh, like web.
    refresh(sessionId)
  }

  const select = async (provider: string | null, nextModel: string | null) => {
    // Keep the menu open if the change fails, so the inline error is visible.
    const ok = await apply(sessionId, { provider, model: nextModel })
    if (ok) close()
  }

  const tip =
    t('model_tip').replace('{name}', model || t('model_unset')) +
    (state?.source === 'global' ? ` · ${t('model_follow_global')}` : '') +
    (state?.source === 'agent' ? ` · ${t('model_follow_agent')}` : '')

  return (
    <ComposerChip
      icon={<Cpu size={13} />}
      label={modelAlias || model || t('model_unset')}
      tip={tip}
      open={open}
      onToggle={toggle}
      onClose={close}
      align="end"
      menuClassName="w-[340px]"
    >
      <div ref={titleRef} className="px-2.5 pt-1 pb-1.5 text-[11px] font-semibold text-content-tertiary">
        {t('model_menu_title')}
      </div>
      {error && <div className="px-2.5 pb-1.5 text-[11px] text-red-500">{error}</div>}
      {providers.length === 0 && (
        <div className="px-2.5 py-2 text-[13px] text-content-tertiary">{t('model_unset')}</div>
      )}
      {providers.map((p, idx) => (
        <React.Fragment key={p.id}>
          {idx > 0 && <div className="my-1 h-px bg-default" />}
          <div
            data-current-provider={p.id === activeProvider ? '' : undefined}
            className="px-2.5 pt-1 pb-1 text-[11px] font-semibold text-content-tertiary"
          >
            {localizedLabel(p.label)}
          </div>
          {(p.models || []).map((m) => {
            const active = m === activeModel && p.id === activeProvider
            const alias = p.labels?.[m]
            return (
              <button
                key={`${p.id}:${m}`}
                type="button"
                data-active-model={active ? '' : undefined}
                onClick={() => select(active && pinned ? null : p.id, active && pinned ? null : m)}
                className={`w-full flex items-center gap-2.5 px-2.5 py-2 rounded-lg text-left cursor-pointer transition-colors ${
                  active ? 'bg-accent-soft text-accent' : 'hover:bg-surface-2 text-content'
                }`}
              >
                <Cpu size={13} className="shrink-0" />
                {alias ? (
                  <span className="flex-1 min-w-0" title={m}>
                    <span className="block text-[13px] truncate">{alias}</span>
                    <span className="block text-[11px] text-content-tertiary truncate font-mono">{m}</span>
                  </span>
                ) : (
                  <span className="flex-1 min-w-0 text-[13px] truncate">{m}</span>
                )}
                {active && <Check size={14} className="shrink-0" />}
              </button>
            )
          })}
        </React.Fragment>
      ))}
    </ComposerChip>
  )
}

const ModelSelector: React.FC<ModelSelectorProps> = (props) =>
  CustomSessionModelPicker ? <CustomSessionModelPicker {...props} /> : <CatalogModelSelector {...props} />

export default ModelSelector
