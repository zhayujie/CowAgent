import React from 'react'
import { ExternalLink } from 'lucide-react'
import { getLang, localizedLabel, t } from '../i18n'
import type { ApiBasePreset, ModelProvider } from '../types'

function domainOf(url: string): string {
  try {
    return new URL(url.trim()).hostname.split('.').slice(-2).join('.')
  } catch {
    return ''
  }
}

// The catalogue lists the China site first; other languages lead with the global one.
export function orderedBasePresets(presets: ApiBasePreset[] | undefined): ApiBasePreset[] {
  const list = presets || []
  return getLang() === 'zh' ? list : list.slice().reverse()
}

// Sites are told apart by domain, so any host under cowagent.cn (staging
// included) maps to the China site and its key console.
export function activeBasePreset(presets: ApiBasePreset[], base: string): ApiBasePreset | undefined {
  const domain = domainOf(base)
  return domain ? presets.find((p) => domainOf(p.value) === domain) : undefined
}

/** The base to prefill: a vendor that was never set up starts on the site matching the UI language. */
export function initialApiBase(p: ModelProvider | undefined): string {
  const presets = orderedBasePresets(p?.api_base_presets)
  const unset = !p?.configured && (!p?.api_base || p.api_base === p.api_base_default)
  return presets.length && unset ? presets[0].value : p?.api_base || ''
}

export const BasePresetChips: React.FC<{
  presets: ApiBasePreset[]
  value: string
  onPick: (value: string) => void
}> = ({ presets, value, onPick }) => {
  // Only the Chinese UI offers the site switch; other languages keep the
  // prefilled global site and edit the field by hand if needed.
  if (!presets.length || getLang() !== 'zh') return null
  const active = activeBasePreset(presets, value)
  return (
    <div className="flex items-center gap-1">
      {presets.map((p) => (
        <button
          key={p.value}
          type="button"
          onClick={() => onPick(p.value)}
          className={`px-2 py-0.5 rounded-md text-xs border transition-colors cursor-pointer ${
            active?.value === p.value
              ? 'border-accent text-accent'
              : 'border-default text-content-tertiary hover:text-content-secondary'
          }`}
        >
          {localizedLabel(p.label)}
        </button>
      ))}
    </div>
  )
}

export const ManageKeyLink: React.FC<{ href: string }> = ({ href }) => (
  <button
    type="button"
    onClick={() => window.open(href, '_blank', 'noopener,noreferrer')}
    className="inline-flex items-center gap-1 text-xs text-accent hover:underline cursor-pointer"
  >
    {t('models_manage_api_key')}
    <ExternalLink size={11} className="shrink-0" />
  </button>
)
