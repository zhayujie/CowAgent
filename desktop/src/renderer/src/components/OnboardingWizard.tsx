import React, { useEffect, useMemo, useState } from 'react'
import { Sparkles, KeyRound, Loader2, ArrowRight, ArrowLeft, ExternalLink } from 'lucide-react'
import { t } from '../i18n'
import apiClient from '../api/client'
import type { ModelsData } from '../types'
import { Field, Dropdown, TextInput, type DropdownOption } from '../pages/settings/primitives'
import { resolveModels, providerLabel } from '../pages/settings/modelsHelpers'
import { useOnboardingStore } from '../store/onboardingStore'

interface OnboardingWizardProps {
  // Called after the wizard finishes so the host can refresh language/state.
  onDone: () => void
}

const TOTAL_STEPS = 2

// Optional "where to get an API key" console link, per provider.
const PROVIDER_KEY_CONSOLE: Record<string, string> = {
  linkai: 'https://link-ai.tech/console/interface',
}

// First-run guided setup: language -> chat model (provider + key + model).
// After saving the model the user goes straight into the chat (no extra
// confirmation step). Rendered as a full-screen overlay above the main UI;
// reuses the same models API and primitives as the settings page.
const OnboardingWizard: React.FC<OnboardingWizardProps> = ({ onDone }) => {
  const finish = useOnboardingStore((s) => s.finish)

  const [step, setStep] = useState(1)
  const [models, setModels] = useState<ModelsData | null>(null)

  // Step 2 form state.
  const [provider, setProvider] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [apiBase, setApiBase] = useState('')
  const [model, setModel] = useState('')

  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  // Load the models console data once for the provider/model dropdowns.
  useEffect(() => {
    apiClient
      .getModels()
      .then(setModels)
      .catch(() => setError(t('onboarding_save_failed')))
  }, [])

  const providerOptions: DropdownOption[] = useMemo(() => {
    const chat = models?.capabilities?.chat
    const ids = chat?.providers || []
    return ids.map((id) => ({ value: id, label: providerLabel(models, id) }))
  }, [models])

  const modelOptions: DropdownOption[] = useMemo(() => {
    return resolveModels(models, provider, models?.capabilities?.chat?.provider_models).map((o) => ({
      value: o.value,
      label: o.value,
      hint: o.hint,
    }))
  }, [models, provider])

  // The currently selected provider's api_base placeholder/default, if any.
  const providerMeta = models?.providers?.find((p) => p.id === provider)
  const apiBasePlaceholder = providerMeta?.api_base_placeholder || providerMeta?.api_base_default

  const handleProvider = (id: string) => {
    setProvider(id)
    setApiBase('')
    const first = resolveModels(models, id, models?.capabilities?.chat?.provider_models)[0]
    setModel(first?.value || '')
  }

  // Step 1 (welcome) can always advance; step 2 needs a provider, key, model.
  const canNext = step === 1 || (!!provider && !!apiKey.trim() && !!model)

  const goNext = async () => {
    setError('')
    // Step 1 (language) just advances to the model step.
    if (step === 1) {
      setStep(2)
      return
    }
    // Step 2 is the last step: persist the provider credentials, point the chat
    // capability at it, then finish straight into the chat (no extra step).
    setSaving(true)
    try {
      await apiClient.modelsAction({
        action: 'set_provider',
        provider_id: provider,
        api_key: apiKey.trim(),
        ...(apiBase.trim() ? { api_base: apiBase.trim() } : {}),
      })
      await apiClient.modelsAction({
        action: 'set_capability',
        capability: 'chat',
        provider_id: provider,
        model,
      })
    } catch {
      setSaving(false)
      setError(t('onboarding_save_failed'))
      return
    }
    setSaving(false)
    complete()
  }

  const goBack = () => {
    setError('')
    setStep((s) => Math.max(1, s - 1))
  }

  const complete = () => {
    finish()
    onDone()
  }

  const stepLabel = t('onboarding_step').replace('{n}', String(step)).replace('{total}', String(TOTAL_STEPS))

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-base">
      <div className="w-full max-w-lg px-8">
        {/* Progress dots */}
        <div className="flex items-center justify-center gap-2 mb-8">
          {Array.from({ length: TOTAL_STEPS }).map((_, i) => (
            <span
              key={i}
              className={`h-1.5 rounded-full transition-all ${
                i + 1 === step ? 'w-8 bg-accent' : i + 1 < step ? 'w-4 bg-accent/50' : 'w-4 bg-surface-2'
              }`}
            />
          ))}
        </div>

        {step === 1 && (
          <div className="text-center space-y-6">
            <div className="w-16 h-16 rounded-2xl bg-accent-soft text-accent flex items-center justify-center mx-auto">
              <Sparkles size={30} />
            </div>
            <div className="space-y-2">
              <h1 className="text-2xl font-bold text-content">{t('onboarding_welcome_title')}</h1>
              <p className="text-sm text-content-secondary">{t('onboarding_welcome_desc')}</p>
            </div>
          </div>
        )}

        {step === 2 && (
          <div className="space-y-6">
            <div className="text-center space-y-2">
              <div className="w-16 h-16 rounded-2xl bg-accent-soft text-accent flex items-center justify-center mx-auto">
                <KeyRound size={28} />
              </div>
              <h1 className="text-2xl font-bold text-content">{t('onboarding_model_title')}</h1>
              <p className="text-sm text-content-secondary">{t('onboarding_model_desc')}</p>
            </div>
            <div className="space-y-4">
              <Field label={t('onboarding_provider')}>
                <Dropdown
                  value={provider}
                  options={providerOptions}
                  placeholder={t('onboarding_select_provider')}
                  onChange={handleProvider}
                />
              </Field>
              {provider && (
                <>
                  <Field label={t('onboarding_apikey')}>
                    <TextInput
                      type="password"
                      value={apiKey}
                      onChange={(e) => setApiKey(e.target.value)}
                      placeholder={t('onboarding_apikey_placeholder')}
                      className="font-mono"
                    />
                    {PROVIDER_KEY_CONSOLE[provider] && (
                      <a
                        href={PROVIDER_KEY_CONSOLE[provider]}
                        target="_blank"
                        rel="noreferrer"
                        className="mt-1.5 inline-flex items-center gap-1 text-xs text-accent hover:underline"
                      >
                        {t('onboarding_key_guide')}
                        <ExternalLink size={11} />
                      </a>
                    )}
                  </Field>
                  {providerMeta?.api_base_field && (
                    <Field label={t('onboarding_apibase')}>
                      <TextInput
                        value={apiBase}
                        onChange={(e) => setApiBase(e.target.value)}
                        placeholder={apiBasePlaceholder || ''}
                        className="font-mono"
                      />
                    </Field>
                  )}
                  <Field label={t('onboarding_model')}>
                    <Dropdown
                      value={model}
                      options={modelOptions}
                      placeholder={t('onboarding_select_model')}
                      onChange={setModel}
                    />
                  </Field>
                </>
              )}
              {error && <p className="text-sm text-danger">{error}</p>}
            </div>
          </div>
        )}

        {/* Footer controls */}
        <div className="mt-10 flex items-center justify-between">
          <div className="text-xs text-content-tertiary">{stepLabel}</div>
          <div className="flex items-center gap-2">
            {/* Step 2: back to language. */}
            {step === 2 && (
              <button
                onClick={goBack}
                disabled={saving}
                className="px-4 py-2 rounded-btn border border-strong text-content-secondary hover:bg-surface-2 text-sm font-medium cursor-pointer transition-colors disabled:opacity-50 inline-flex items-center gap-1.5"
              >
                <ArrowLeft size={15} />
                {t('onboarding_back')}
              </button>
            )}
            {/* Skip is available on every step: dismiss and go straight to chat. */}
            <button
              onClick={complete}
              disabled={saving}
              className="px-4 py-2 rounded-btn text-sm font-medium text-content-tertiary hover:text-content cursor-pointer transition-colors disabled:opacity-50"
            >
              {t('onboarding_skip')}
            </button>
            {/* Primary action: advance on step 1, save + finish on the last step. */}
            <button
              onClick={goNext}
              disabled={!canNext || saving}
              className="px-5 py-2 rounded-btn bg-accent text-accent-contrast hover:bg-accent-hover text-sm font-medium cursor-pointer transition-colors disabled:opacity-50 disabled:cursor-not-allowed inline-flex items-center gap-1.5"
            >
              {saving && <Loader2 size={15} className="animate-spin" />}
              {saving
                ? t('onboarding_saving')
                : step === TOTAL_STEPS
                  ? t('onboarding_finish')
                  : t('onboarding_next')}
              {!saving && <ArrowRight size={15} />}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

export default OnboardingWizard
