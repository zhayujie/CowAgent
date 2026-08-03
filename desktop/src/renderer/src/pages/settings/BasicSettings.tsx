import React, { useState, useEffect } from 'react'
import { Cpu, Bot, ShieldCheck, Languages, Eye, EyeOff, ArrowRight, Loader2 } from 'lucide-react'
import { t, getLang, setLang, localizedLabel, type Lang } from '../../i18n'
import apiClient from '../../api/client'
import { product } from '@product'
import type { ConfigData, ProviderMeta } from '../../types'
import { Card, Field, Dropdown, Toggle, TextInput, SaveRow, MASK_RE } from './primitives'

const CustomModelPicker = product.models?.ModelPicker
const hideProviderSelect = product.models?.hideProviderSelect === true
const showManagedApiKey = product.models?.showManagedApiKey === true

interface BasicSettingsProps {
  baseUrl: string
  onLangChange?: () => void
  onOpenModels?: () => void
}

const BasicSettings: React.FC<BasicSettingsProps> = ({ baseUrl, onLangChange, onOpenModels }) => {
  const [config, setConfig] = useState<ConfigData | null>(null)
  const [loading, setLoading] = useState(true)

  // model card — credentials (key/base) now live in the Models tab
  const [provider, setProvider] = useState('')
  const [model, setModel] = useState('')
  const [customModel, setCustomModel] = useState('')
  const [showCustom, setShowCustom] = useState(false)
  const [modelStatus, setModelStatus] = useState('')

  // managed API key (shown only when the standalone models tab is hidden)
  const [apiKey, setApiKey] = useState('')
  const [apiKeyDirty, setApiKeyDirty] = useState(false)
  const [apiKeyVisible, setApiKeyVisible] = useState(false)

  // agent card
  const [maxTokens, setMaxTokens] = useState(100000)
  const [maxTurns, setMaxTurns] = useState(20)
  const [maxSteps, setMaxSteps] = useState(20)
  const [thinking, setThinking] = useState(false)
  const [reasoningEffort, setReasoningEffort] = useState('high')
  const [evolution, setEvolution] = useState(false)
  const [agentStatus, setAgentStatus] = useState('')

  // security card
  const [password, setPassword] = useState('')
  const [pwDirty, setPwDirty] = useState(false)
  const [pwVisible, setPwVisible] = useState(false)
  const [pwStatus, setPwStatus] = useState('')

  useEffect(() => {
    apiClient.setBaseUrl(baseUrl)
    loadConfig()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [baseUrl])

  const providerMeta = (id: string): ProviderMeta | undefined => config?.providers?.[id] as ProviderMeta | undefined

  const loadConfig = async () => {
    try {
      setLoading(true)
      const data = await apiClient.getConfig()
      setConfig(data)
      setModel(data.model || '')
      setMaxTokens(data.agent_max_context_tokens ?? 100000)
      setMaxTurns(data.agent_max_context_turns ?? 20)
      setMaxSteps(data.agent_max_steps ?? 20)
      setThinking(!!data.enable_thinking)
      setReasoningEffort(data.reasoning_effort || 'high')
      setEvolution(!!data.self_evolution_enabled)
      // Prefer the real password (desktop only) so it can be edited in place;
      // fall back to the masked value for browser access.
      setPassword(data.web_password ?? data.web_password_masked ?? '')
      setPwDirty(false)

      const ids = data.providers ? Object.keys(data.providers) : []
      const current = data.use_linkai ? 'linkai' : data.bot_type || ids[0] || ''
      setProvider(current)
      const meta = data.providers?.[current] as ProviderMeta | undefined
      // Managed key: show the masked value for the current provider's key field.
      const keyField = meta?.api_key_field
      setApiKey((keyField && data.api_keys?.[keyField]) || '')
      setApiKeyDirty(false)
      const presets = meta?.models || []
      if (data.model && presets.length && !presets.includes(data.model)) {
        setShowCustom(true)
        setCustomModel(data.model)
      }
    } catch (err) {
      console.error('Failed to load config:', err)
    } finally {
      setLoading(false)
    }
  }

  const handleProviderChange = (id: string) => {
    setProvider(id)
    setShowCustom(false)
    setCustomModel('')
    if (config) {
      const meta = config.providers?.[id] as ProviderMeta | undefined
      const models = meta?.models || []
      setModel(models[0] || '')
    }
  }

  const handleModelChange = (val: string) => {
    if (val === '__custom__') {
      setShowCustom(true)
      setModel('')
    } else {
      setShowCustom(false)
      setModel(val)
      setCustomModel('')
    }
  }

  const saveModelConfig = async () => {
    const finalModel = CustomModelPicker ? model : showCustom ? customModel.trim() : model
    // With a managed model source the provider selector is hidden; route through
    // the managed provider so credentials resolve consistently.
    const isLinkai = CustomModelPicker ? true : provider === 'linkai'
    try {
      await apiClient.updateConfig({
        model: finalModel,
        use_linkai: isLinkai,
        bot_type: isLinkai ? '' : provider,
      })
      setModelStatus(t('config_saved'))
      const fresh = await apiClient.getConfig()
      setConfig(fresh)
    } catch {
      setModelStatus(t('config_save_error'))
    }
    setTimeout(() => setModelStatus(''), 2000)
  }

  const currentKeyField = (config?.providers?.[provider] as ProviderMeta | undefined)?.api_key_field

  const saveApiKey = async () => {
    if (!apiKeyDirty || !currentKeyField) return
    // Never save a masked value back as the real key.
    if (MASK_RE.test(apiKey)) return
    try {
      await apiClient.updateConfig({ [currentKeyField]: apiKey })
      setModelStatus(t('config_saved'))
      setApiKeyDirty(false)
      const fresh = await apiClient.getConfig()
      setConfig(fresh)
      const meta = fresh.providers?.[provider] as ProviderMeta | undefined
      const keyField = meta?.api_key_field
      setApiKey((keyField && fresh.api_keys?.[keyField]) || '')
    } catch {
      setModelStatus(t('config_save_error'))
    }
    setTimeout(() => setModelStatus(''), 2000)
  }

  const saveAgentConfig = async () => {
    const meta = config?.providers?.[provider] as ProviderMeta | undefined
    const selectedModel = CustomModelPicker ? model : showCustom ? customModel.trim() : model
    const reasoning = meta?.reasoning_by_model?.[selectedModel] || meta?.reasoning
    const reasoningOptions = reasoning?.supported ? reasoning.options || [] : []
    const nextReasoningEffort = reasoningOptions.some((o) => o.value === reasoningEffort)
      ? reasoningEffort
      : reasoning?.default || reasoningOptions[0]?.value || reasoningEffort

    try {
      await apiClient.updateConfig({
        agent_max_context_tokens: maxTokens,
        agent_max_context_turns: maxTurns,
        agent_max_steps: maxSteps,
        enable_thinking: thinking,
        reasoning_effort: thinking ? nextReasoningEffort : reasoningEffort,
        self_evolution_enabled: evolution,
      })
      setAgentStatus(t('config_saved'))
    } catch {
      setAgentStatus(t('config_save_error'))
    }
    setTimeout(() => setAgentStatus(''), 2000)
  }

  // Desktop returns the real password, so the field holds plaintext and can be
  // saved (including cleared) directly. Browser access only has the masked
  // value, where a masked string must never be saved as the real password.
  const hasRealPassword = config?.web_password !== undefined

  const savePassword = async () => {
    if (!pwDirty) return
    if (!hasRealPassword && MASK_RE.test(password)) return
    try {
      await apiClient.updateConfig({ web_password: password })
      setPwStatus(password ? t('config_password_saved') : t('config_password_cleared'))
      setPwDirty(false)
    } catch {
      setPwStatus(t('config_save_error'))
    }
    setTimeout(() => setPwStatus(''), 3000)
  }

  const changeLanguage = async (lang: Lang) => {
    setLang(lang)
    onLangChange?.()
    try {
      await apiClient.updateConfig({ cow_lang: lang })
    } catch {
      /* non-blocking */
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20 text-content-tertiary">
        <Loader2 size={18} className="animate-spin mr-2" />
        {t('skills_loading')}
      </div>
    )
  }

  // A provider counts as configured when its key field holds a value.
  // Custom providers (no key field) carry their own credential, so treat as configured.
  const isConfigured = (id: string): boolean => {
    const meta = providerMeta(id)
    const f = meta?.api_key_field
    if (!f) return true
    return !!config?.api_keys?.[f]
  }

  // Only list configured providers (built-in or custom). Unconfigured vendors
  // have no usable credentials, so showing them — flagged "unconfigured" — is
  // just noise. Keep the current selection so a saved value never disappears.
  const providerIds = config?.providers ? Object.keys(config.providers) : []
  const providerOptions = providerIds
    .filter((id) => isConfigured(id) || id === provider)
    .map((id) => ({
      value: id,
      label: localizedLabel(providerMeta(id)?.label) || id,
    }))
  const currentMeta = providerMeta(provider)
  const selectedModel = CustomModelPicker ? model : showCustom ? customModel.trim() : model
  const reasoning = currentMeta?.reasoning_by_model?.[selectedModel] || currentMeta?.reasoning
  const reasoningOptions = reasoning?.supported ? reasoning.options || [] : []
  const reasoningValue = reasoningOptions.some((o) => o.value === reasoningEffort)
    ? reasoningEffort
    : reasoning?.default || reasoningOptions[0]?.value || ''
  const currentUnconfigured = !!provider && !isConfigured(provider)
  const modelOptions = [
    ...(currentMeta?.models || []).map((m) => ({ value: m, label: m })),
    { value: '__custom__', label: t('config_custom_option') },
  ]

  return (
    <div className="grid gap-5">
      {/* Model — provider/model selection only; credentials live in Models tab */}
      <Card icon={<Cpu size={16} />} title={t('config_model')}>
        <div className="space-y-4">
          {!hideProviderSelect && (
            <Field label={t('config_provider')}>
              <Dropdown value={provider} options={providerOptions} onChange={handleProviderChange} />
            </Field>
          )}
          <Field label={t('config_model_name')}>
            {CustomModelPicker ? (
              <CustomModelPicker value={model} onChange={setModel} />
            ) : (
              <>
                <Dropdown
                  value={showCustom ? '__custom__' : model}
                  options={modelOptions}
                  onChange={handleModelChange}
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

          {/* Managed API key: hidden by default, click the eye to reveal the
              partially-masked value (e.g. sk-1****9aL7). Editable in place; if
              left untouched (still contains a mask char) it is not overwritten. */}
          {showManagedApiKey && currentKeyField && (
            <Field label={t('onboarding_apikey')}>
              <div className="relative">
                <TextInput
                  type={apiKeyVisible ? 'text' : 'password'}
                  className="pr-10 font-mono"
                  value={apiKey}
                  placeholder="sk-..."
                  onChange={(e) => {
                    setApiKey(e.target.value.trim())
                    setApiKeyDirty(true)
                  }}
                />
                <button
                  type="button"
                  onClick={() => setApiKeyVisible((v) => !v)}
                  className="absolute right-2.5 top-1/2 -translate-y-1/2 text-content-tertiary hover:text-content-secondary cursor-pointer p-1"
                >
                  {apiKeyVisible ? <EyeOff size={14} /> : <Eye size={14} />}
                </button>
              </div>
            </Field>
          )}

          {/* Guide users to the Models tab for API key / base config.
              When the selected provider has no credentials, surface a warning. */}
          {onOpenModels && (
            <button
              onClick={onOpenModels}
              className={`w-full flex items-center justify-between gap-2 rounded-btn border px-3 py-2.5 cursor-pointer transition-colors text-left ${
                currentUnconfigured
                  ? 'border-danger-border bg-danger-soft hover:border-danger'
                  : 'border-default bg-inset hover:border-accent'
              }`}
            >
              <span className={`text-xs ${currentUnconfigured ? 'text-danger' : 'text-content-tertiary'}`}>
                {currentUnconfigured ? t('config_provider_unconfigured_hint') : t('config_credentials_link')}
              </span>
              <span
                className={`flex-shrink-0 inline-flex items-center gap-1 text-xs ${
                  currentUnconfigured ? 'text-danger font-medium' : 'text-accent'
                }`}
              >
                {t('config_goto_models')}
                <ArrowRight size={13} />
              </span>
            </button>
          )}

          <SaveRow
            status={modelStatus}
            onSave={async () => {
              await saveModelConfig()
              if (showManagedApiKey && apiKeyDirty) await saveApiKey()
            }}
          />
        </div>
      </Card>

      {/* Agent */}
      <Card icon={<Bot size={16} />} title={t('config_agent')}>
        <div className="space-y-4">
          <Field label={t('config_max_tokens')} hint={t('config_max_tokens_hint')}>
            <TextInput
              type="number"
              className="font-mono"
              value={maxTokens}
              onChange={(e) => setMaxTokens(parseInt(e.target.value) || 0)}
            />
          </Field>
          <Field label={t('config_max_turns')} hint={t('config_max_turns_hint')}>
            <TextInput
              type="number"
              className="font-mono"
              value={maxTurns}
              onChange={(e) => setMaxTurns(parseInt(e.target.value) || 0)}
            />
          </Field>
          <Field label={t('config_max_steps')} hint={t('config_max_steps_hint')}>
            <TextInput
              type="number"
              className="font-mono"
              value={maxSteps}
              onChange={(e) => setMaxSteps(parseInt(e.target.value) || 0)}
            />
          </Field>
          <div className="flex items-center justify-between py-1">
            <div>
              <div className="text-sm font-medium text-content">{t('config_thinking')}</div>
              <div className="text-xs text-content-tertiary mt-0.5">{t('config_thinking_hint')}</div>
            </div>
            <Toggle checked={thinking} onChange={setThinking} />
          </div>
          {thinking && reasoning?.supported && reasoningOptions.length > 0 && (
            <Field label={t('config_reasoning_effort')} hint={t('config_reasoning_effort_hint')}>
              <Dropdown
                value={reasoningValue}
                options={reasoningOptions}
                onChange={setReasoningEffort}
              />
            </Field>
          )}
          <div className="flex items-center justify-between py-1">
            <div>
              <div className="text-sm font-medium text-content">{t('config_evolution')}</div>
              <div className="text-xs text-content-tertiary mt-0.5">{t('config_evolution_hint')}</div>
            </div>
            <Toggle checked={evolution} onChange={setEvolution} />
          </div>
          <SaveRow status={agentStatus} onSave={saveAgentConfig} />
        </div>
      </Card>

      {/* Security */}
      <Card icon={<ShieldCheck size={16} />} title={t('config_security')}>
        <div className="space-y-4">
          <Field label={t('config_password')} hint={t('config_password_hint')}>
            <div className="relative">
              <TextInput
                type={pwVisible ? 'text' : 'password'}
                className="pr-10"
                value={password}
                placeholder={t('config_password_placeholder')}
                onFocus={() => {
                  // Browser access shows a mask; clear it on focus so the user
                  // types a fresh password. Desktop holds the real password and
                  // must stay editable in place (cursor at the end).
                  if (!hasRealPassword && !pwDirty && MASK_RE.test(password)) setPassword('')
                }}
                onBlur={() => {
                  if (!hasRealPassword && !pwDirty) setPassword(config?.web_password_masked || '')
                }}
                onChange={(e) => {
                  setPassword(e.target.value)
                  setPwDirty(true)
                }}
              />
              <button
                type="button"
                onClick={() => setPwVisible((v) => !v)}
                className="absolute right-2.5 top-1/2 -translate-y-1/2 text-content-tertiary hover:text-content-secondary cursor-pointer p-1"
              >
                {pwVisible ? <EyeOff size={14} /> : <Eye size={14} />}
              </button>
            </div>
          </Field>
          <SaveRow status={pwStatus} onSave={savePassword} />
        </div>
      </Card>

      {/* Language */}
      <Card icon={<Languages size={16} />} title={t('config_language')}>
        <Field label={t('config_language')} hint={t('config_language_hint')}>
          <Dropdown
            value={getLang()}
            options={[
              { value: 'zh', label: '简体中文' },
              { value: 'en', label: 'English' },
            ]}
            onChange={(v) => changeLanguage(v as Lang)}
          />
        </Field>
      </Card>
    </div>
  )
}

export default BasicSettings
