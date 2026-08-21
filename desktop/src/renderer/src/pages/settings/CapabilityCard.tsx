import React, { useMemo, useState } from 'react'
import type { LucideIcon } from 'lucide-react'
import { Loader2 } from 'lucide-react'
import { t } from '../../i18n'
import type { CapabilityState, ModelsData } from '../../types'
import { Card, Field, Dropdown, TextInput, type DropdownOption } from './primitives'
import { resolveModels, providerLabel, CUSTOM_OPTION } from './modelsHelpers'

// Generic provider+model capability card used by chat/vision/asr/embedding/image.
// tts (voice) and search have bespoke cards.

export interface CapabilityCardProps {
  icon: LucideIcon
  title: string
  subtitle?: string
  capKey: string
  state: CapabilityState
  data: ModelsData | null
  // whether picking "no provider" (auto / disabled) is allowed
  allowAuto?: boolean
  autoLabel?: string
  // whether to allow a free-form custom model entry
  allowCustomModel?: boolean
  busy?: boolean
  status?: string
  onSave: (providerId: string, model: string) => void
  children?: React.ReactNode
}

const CapabilityCard: React.FC<CapabilityCardProps> = ({
  icon: Icon,
  title,
  subtitle,
  state,
  data,
  allowAuto,
  autoLabel,
  allowCustomModel,
  busy,
  status,
  onSave,
  children,
}) => {
  const [provider, setProvider] = useState(state.current_provider || '')
  const [model, setModel] = useState(state.current_model || '')
  // Custom providers render the model as a free-form input; seed it with the
  // saved model so it isn't blank (placeholder-only) on load.
  const [customModel, setCustomModel] = useState(
    (state.current_provider || '').startsWith('custom:') ? state.current_model || '' : ''
  )
  const [showCustom, setShowCustom] = useState(false)

  // Custom providers expose no preset model catalog, so the model must always
  // be typed in freely instead of picked from an (empty) dropdown.
  const isCustomProvider = provider.startsWith('custom:')

  // A provider is configured when it has credentials (a custom provider counts
  // only once it actually carries a name/key, not as an empty placeholder).
  const isConfigured = (id: string): boolean => {
    const p = data?.providers?.find((x) => x.id === id)
    if (!p) return true
    return p.configured || (p.is_custom && !!p.custom_name)
  }

  // Only surface providers that are actually configured (built-in or custom).
  // An unconfigured vendor has no usable credentials, so listing it — and
  // flagging it "unconfigured" — only adds noise. The currently-selected
  // provider is always kept so a saved value never silently disappears.
  const providerOptions: DropdownOption[] = useMemo(() => {
    const opts = (state.providers || [])
      .filter((id) => isConfigured(id) || id === provider)
      .map((id) => ({ value: id, label: providerLabel(data, id) }))
    if (allowAuto) return [{ value: '', label: autoLabel || t('models_auto') }, ...opts]
    return opts
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.providers, data, allowAuto, autoLabel, provider])

  const currentUnconfigured = !!provider && !isConfigured(provider)

  const modelOptions: DropdownOption[] = useMemo(() => {
    const list = resolveModels(data, provider, state.provider_models).map((o) => ({
      value: o.value,
      label: o.value,
      hint: o.hint,
    }))
    // Keep the currently-saved model selectable even if it's not in the preset list.
    if (model && !showCustom && !list.some((o) => o.value === model)) {
      list.unshift({ value: model, label: model, hint: undefined })
    }
    if (allowCustomModel) list.push({ value: CUSTOM_OPTION, label: t('config_custom_option'), hint: undefined })
    return list
  }, [data, state.provider_models, provider, allowCustomModel, model, showCustom])

  const handleProvider = (id: string) => {
    setProvider(id)
    setShowCustom(false)
    if (id.startsWith('custom:')) {
      // Prefill with the saved model when re-selecting the same provider.
      const saved = id === state.current_provider ? state.current_model || '' : ''
      setCustomModel(saved)
      setModel('')
      return
    }
    setCustomModel('')
    const first = resolveModels(data, id, state.provider_models)[0]
    setModel(first?.value || '')
  }

  const handleModel = (val: string) => {
    if (val === CUSTOM_OPTION) {
      setShowCustom(true)
      setModel('')
    } else {
      setShowCustom(false)
      setModel(val)
      setCustomModel('')
    }
  }

  const finalModel = showCustom || isCustomProvider ? customModel.trim() : model
  const isAuto = allowAuto && !provider

  return (
    <Card icon={<Icon size={16} />} title={title} subtitle={subtitle}>
      <div className="space-y-4">
        <Field label={t('models_provider')}>
          <Dropdown
            value={provider}
            options={providerOptions}
            placeholder={t('models_select_provider')}
            onChange={handleProvider}
          />
          {/* The provider's API key is configured in the vendor cards above on
              this same tab, so warn instead of linking elsewhere. */}
          {currentUnconfigured && (
            <p className="text-xs text-danger mt-1.5">{t('config_provider_unconfigured_hint')}</p>
          )}
        </Field>
        {!isAuto && (
          <Field label={t('models_model')}>
            {isCustomProvider ? (
              // Custom providers have no preset catalog: type the model directly.
              <TextInput
                className="font-mono"
                value={customModel}
                onChange={(e) => setCustomModel(e.target.value)}
                placeholder={t('config_custom_model_hint')}
              />
            ) : (
              <>
                <Dropdown
                  value={showCustom ? CUSTOM_OPTION : model}
                  options={modelOptions}
                  placeholder={t('models_select_model')}
                  onChange={handleModel}
                />
                {showCustom && (
                  <TextInput
                    className="mt-2 font-mono"
                    value={customModel}
                    onChange={(e) => setCustomModel(e.target.value)}
                    placeholder={t('config_custom_model_hint')}
                  />
                )}
              </>
            )}
          </Field>
        )}
        {children}
        <div className="flex items-center justify-end gap-3 pt-1">
          <span className={`text-xs text-accent transition-opacity ${status ? 'opacity-100' : 'opacity-0'}`}>
            {status}
          </span>
          <button
            disabled={busy}
            onClick={() => onSave(provider, finalModel)}
            className="px-4 py-2 rounded-btn bg-accent text-accent-contrast hover:bg-accent-hover text-sm font-medium cursor-pointer transition-colors disabled:opacity-50 inline-flex items-center gap-2"
          >
            {busy && <Loader2 size={14} className="animate-spin" />}
            {t('config_save')}
          </button>
        </div>
      </div>
    </Card>
  )
}

export default CapabilityCard
