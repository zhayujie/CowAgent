import React, { useState, useEffect, useRef } from 'react'
import { Cpu, Bot, ShieldCheck, Settings, Eye, EyeOff, ArrowRight, Loader2 } from 'lucide-react'
import { t, localizedLabel } from '../../i18n'
import apiClient from '../../api/client'
import { product } from '@product'
import type { ConfigData, ProviderMeta } from '../../types'
import { useUIStore } from '../../store/uiStore'
import { useSessionStore } from '../../store/sessionStore'
import { useSessionSettingsStore } from '../../store/sessionSettingsStore'
import { Card, Field, Dropdown, Toggle, TextInput, SaveRow, MASK_RE } from './primitives'
import { PERMISSION_META, PERMISSION_MODE_ORDER, asPermissionMode } from '../../lib/permission'

const CustomModelPicker = product.models?.ModelPicker
const hideProviderSelect = product.models?.hideProviderSelect === true
const showManagedApiKey = product.models?.showManagedApiKey === true
const ModelFieldLink = product.models?.ModelFieldLink
const ApiKeyFieldLink = product.models?.ApiKeyFieldLink

// Numeric settings are kept as raw text while editing so an emptied field stays
// empty instead of snapping back to a digit the user then cannot delete. Only
// on save is the text turned into a number, falling back to `fallback` when the
// field was left blank.
const digitsOnly = (text: string): string => text.replace(/\D/g, '').replace(/^0+(?=\d)/, '')

const toInt = (text: string, fallback: number): number => {
  const n = parseInt(text, 10)
  return Number.isFinite(n) && n >= 0 ? n : fallback
}

interface BasicSettingsProps {
  baseUrl: string
  onOpenModels?: () => void
}

const BasicSettings: React.FC<BasicSettingsProps> = ({ baseUrl, onOpenModels }) => {
  const [config, setConfig] = useState<ConfigData | null>(null)
  const [loading, setLoading] = useState(true)
  // When arriving from the context pie's "Config" action, scroll to and briefly
  // highlight the max-context-tokens field (signal set in sessionStorage).
  const [highlightBudget, setHighlightBudget] = useState(false)
  useEffect(() => {
    if (sessionStorage.getItem('cow_focus_max_tokens') !== '1') return
    sessionStorage.removeItem('cow_focus_max_tokens')
    const el = document.getElementById('cfg-max-tokens')
    if (el) {
      el.scrollIntoView({ behavior: 'smooth', block: 'center' })
      ;(el as HTMLInputElement).focus?.({ preventScroll: true })
    }
    setHighlightBudget(true)
    const timer = setTimeout(() => setHighlightBudget(false), 2000)
    return () => clearTimeout(timer)
  }, [])

  // notifications card (client-side preference, applied instantly)
  const taskNotify = useUIStore((s) => s.taskNotify)
  const taskNotifySound = useUIStore((s) => s.taskNotifySound)
  const setTaskNotify = useUIStore((s) => s.setTaskNotify)
  const setTaskNotifySound = useUIStore((s) => s.setTaskNotifySound)

  // Launch-at-login (macOS + Windows only). State lives in the OS registry, so
  // read it from the main process rather than persisting it ourselves.
  const platform = window.electronAPI?.platform
  const supportsLaunchAtLogin =
    !!window.electronAPI?.setLoginItemEnabled && (platform === 'darwin' || platform === 'win32')
  const [launchAtLogin, setLaunchAtLogin] = useState(false)
  const [launchAtLoginError, setLaunchAtLoginError] = useState('')

  useEffect(() => {
    if (!supportsLaunchAtLogin) return
    window.electronAPI?.getLoginItemEnabled?.().then((v) => setLaunchAtLogin(!!v)).catch(() => {})
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [supportsLaunchAtLogin])

  const toggleLaunchAtLogin = async (v: boolean) => {
    setLaunchAtLogin(v)
    setLaunchAtLoginError('')
    try {
      const res = await window.electronAPI?.setLoginItemEnabled?.(v)
      if (!res) return
      // Reflect what the OS actually did — never silently pretend it worked.
      setLaunchAtLogin(res.enabled)
      if (!res.ok) {
        setLaunchAtLoginError(
          res.error
            ? `${t('config_launch_at_login_error')}: ${res.error}`
            : t('config_launch_at_login_refused')
        )
      }
    } catch (e) {
      // IPC itself failed: revert and surface it rather than swallowing.
      setLaunchAtLogin(!v)
      const msg = e instanceof Error ? e.message : String(e)
      setLaunchAtLoginError(`${t('config_launch_at_login_error')}: ${msg}`)
    }
  }

  // model card — credentials (key/base) now live in the Models tab
  const [provider, setProvider] = useState('')
  const [model, setModel] = useState('')
  const [customModel, setCustomModel] = useState('')
  const [showCustom, setShowCustom] = useState(false)
  const [modelStatus, setModelStatus] = useState('')
  // Remembers the custom model typed per provider so switching vendors and
  // back doesn't lose it. Keyed by provider id.
  const customModelByProvider = useRef<Record<string, string>>({})

  // managed API key (shown only when the standalone models tab is hidden)
  const [apiKey, setApiKey] = useState('')
  const [apiKeyDirty, setApiKeyDirty] = useState(false)
  const [apiKeyVisible, setApiKeyVisible] = useState(false)

  // agent card
  // Manual cap on the input budget (compact once reached, to control cost);
  // 0 disables the cap and follows the model window.
  const [maxTokens, setMaxTokens] = useState('64000')
  const [maxTurns, setMaxTurns] = useState('20')
  const [maxSteps, setMaxSteps] = useState('20')
  const [thinking, setThinking] = useState(false)
  const [reasoningEffort, setReasoningEffort] = useState('high')
  const [subagent, setSubagent] = useState(true)
  const [evolution, setEvolution] = useState(false)
  const [agentStatus, setAgentStatus] = useState('')

  // security card
  const [password, setPassword] = useState('')
  const [pwDirty, setPwDirty] = useState(false)
  const [pwVisible, setPwVisible] = useState(false)
  const [pwStatus, setPwStatus] = useState('')
  const [permissionMode, setPermissionMode] = useState('full-access')
  const [permStatus, setPermStatus] = useState('')

  useEffect(() => {
    apiClient.setBaseUrl(baseUrl)
    loadConfig()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [baseUrl])

  const providerMeta = (id: string): ProviderMeta | undefined => config?.providers?.[id] as ProviderMeta | undefined

  // Custom providers (custom:<id> or legacy "custom") have no preset model
  // catalog, so their model is always typed into a free-form input.
  const isCustomProviderId = (id: string) => id.startsWith('custom:') || id === 'custom'

  // Canonical per-model key shared with the backend resolve path: lowercased
  // model so the key is stable regardless of how the user typed the model name.
  const currentModelKey = () => {
    const m = (
      CustomModelPicker
        ? model
        : isCustomProviderId(provider) || showCustom
          ? customModel.trim()
          : model
    )
      .trim()
      .toLowerCase()
    return m ? `${provider}:${m}` : ''
  }

  const currentSavedEffort = () => config?.reasoning_effort_by_model?.[currentModelKey()] ?? config?.reasoning_effort

  // When the active provider/model changes, surface that model's own saved
  // effort instead of leaving the previous model's value visible.
  useEffect(() => {
    if (!config) return
    const saved = currentSavedEffort()
    setReasoningEffort(saved || 'high')
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [provider, model, showCustom, customModel, config])

  const loadConfig = async () => {
    try {
      setLoading(true)
      const data = await apiClient.getConfig()
      setConfig(data)
      setModel(data.model || '')
      setMaxTokens(String(data.agent_max_context_tokens ?? 64000))
      setMaxTurns(String(data.agent_max_context_turns ?? 20))
      setMaxSteps(String(data.agent_max_steps ?? 20))
      setThinking(!!data.enable_thinking)
      setReasoningEffort(data.reasoning_effort || 'high')
      setSubagent(data.subagent_enabled !== false)
      setEvolution(!!data.self_evolution_enabled)
      setPermissionMode(asPermissionMode(data.agent_permission_mode))
      // Prefer the real password (desktop only) so it can be edited in place;
      // fall back to the masked value for browser access.
      setPassword(data.web_password ?? data.web_password_masked ?? '')
      setPwDirty(false)

      const ids = data.providers ? Object.keys(data.providers) : []
      const current = showManagedApiKey ? 'linkai' : data.use_linkai ? 'linkai' : data.bot_type || ids[0] || ''
      setProvider(current)
      const meta = data.providers?.[current] as ProviderMeta | undefined
      // Managed key: show the masked value for the current provider's key field.
      const keyField = meta?.api_key_field
      setApiKey((keyField && data.api_keys?.[keyField]) || '')
      setApiKeyDirty(false)
      const presets = meta?.models || []
      if (current.startsWith('custom:') || current === 'custom') {
        // Custom providers always use the free-form model input; seed it with
        // the saved model so it isn't blank on load.
        setCustomModel(data.model || '')
      } else if (data.model && presets.length && !presets.includes(data.model)) {
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
    // Stash the custom model typed under the provider we're leaving so a
    // later switch back to it restores the value.
    if (showCustom || isCustomProviderId(provider)) {
      const typed = customModel.trim()
      if (typed) customModelByProvider.current[provider] = typed
    }
    setProvider(id)
    setShowCustom(false)
    const remembered = customModelByProvider.current[id]
    if (id.startsWith('custom:') || id === 'custom') {
      // Prefill with a remembered value, else the provider's default model (or
      // the saved one when re-selecting the active provider).
      const meta = config?.providers?.[id] as ProviderMeta | undefined
      const saved = id === config?.bot_type ? config?.model || '' : ''
      setCustomModel(remembered || saved || meta?.models?.[0] || '')
      setModel('')
      return
    }
    if (remembered) {
      // A remembered custom model for a preset provider: reopen custom input.
      setShowCustom(true)
      setCustomModel(remembered)
      setModel('')
      return
    }
    setCustomModel('')
    if (config) {
      const meta = config.providers?.[id] as ProviderMeta | undefined
      const models = meta?.models || []
      setModel(models[0] || '')
    }
  }

  // Keep the per-provider memory in sync as the user types a custom model.
  const handleCustomModelInput = (val: string) => {
    setCustomModel(val)
    const trimmed = val.trim()
    if (trimmed) customModelByProvider.current[provider] = trimmed
    else delete customModelByProvider.current[provider]
  }

  const handleModelChange = (val: string) => {
    if (val === '__custom__') {
      setShowCustom(true)
      setModel('')
      // Restore any custom model previously typed for this provider.
      const remembered = customModelByProvider.current[provider]
      if (remembered) setCustomModel(remembered)
    } else {
      setShowCustom(false)
      setModel(val)
      setCustomModel('')
    }
  }

  const saveModelConfig = async () => {
    const finalModel = CustomModelPicker
      ? model
      : isCustomProviderId(provider) || showCustom
        ? customModel.trim()
        : model
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

  const currentKeyField =
    (config?.providers?.[provider] as ProviderMeta | undefined)?.api_key_field ||
    (showManagedApiKey ? 'linkai_api_key' : undefined)

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
    const selectedModel = CustomModelPicker
      ? model
      : isCustomProviderId(provider) || showCustom
        ? customModel.trim()
        : model
    const reasoning = meta?.reasoning_by_model?.[selectedModel] || meta?.reasoning
    const reasoningOptions = reasoning?.supported ? reasoning.options || [] : []
    const nextReasoningEffort = reasoningOptions.some((o) => o.value === reasoningEffort)
      ? reasoningEffort
      : reasoning?.default || reasoningOptions[0]?.value || reasoningEffort

    try {
      // Persist the effort per model so switching vendors never reinterprets a
      // value the user set for a different model. Merge with the existing map so
      // other models' saved efforts are not overwritten by the flat config save.
      const effortKey = currentModelKey()
      // A field left blank keeps whatever is already persisted rather than
      // silently saving 0, which would drop the context cap or turn limit.
      const nextMaxTokens = toInt(maxTokens, config?.agent_max_context_tokens ?? 64000)
      const nextMaxTurns = toInt(maxTurns, config?.agent_max_context_turns ?? 20)
      const nextMaxSteps = toInt(maxSteps, config?.agent_max_steps ?? 20)
      await apiClient.updateConfig({
        agent_max_context_tokens: nextMaxTokens,
        agent_max_context_turns: nextMaxTurns,
        agent_max_steps: nextMaxSteps,
        enable_thinking: thinking,
        reasoning_effort_by_model: {
          ...(config?.reasoning_effort_by_model || {}),
          ...(effortKey ? { [effortKey]: nextReasoningEffort } : {}),
        },
        subagent_enabled: subagent,
        self_evolution_enabled: evolution,
      })
      // Refresh so the in-memory config carries the just-saved per-model value;
      // otherwise switching model and back would show/submit a stale value.
      const fresh = await apiClient.getConfig()
      setConfig(fresh)
      // Show what was actually saved, so a field left blank doesn't stay blank.
      setMaxTokens(String(nextMaxTokens))
      setMaxTurns(String(nextMaxTurns))
      setMaxSteps(String(nextMaxSteps))
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

  const savePermission = async (mode: string) => {
    setPermissionMode(mode)
    try {
      await apiClient.updateConfig({ agent_permission_mode: mode })
      setPermStatus(t('config_saved'))
      const sid = useSessionStore.getState().activeId
      if (sid) useSessionSettingsStore.getState().refresh(sid)
    } catch {
      setPermStatus(t('config_save_error'))
    }
    setTimeout(() => setPermStatus(''), 2000)
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
  const isCustomProvider = isCustomProviderId(provider)
  const selectedModel = CustomModelPicker
    ? model
    : isCustomProvider || showCustom
      ? customModel.trim()
      : model
  const reasoning = currentMeta?.reasoning_by_model?.[selectedModel] || currentMeta?.reasoning
  const reasoningOptions = reasoning?.supported ? reasoning.options || [] : []
  const reasoningValue = reasoningOptions.some((o) => o.value === reasoningEffort)
    ? reasoningEffort
    : reasoning?.default || reasoningOptions[0]?.value || ''
  // Effort only shapes a thinking pass, so the field follows the toggle.
  const showReasoningEffort = thinking && !!reasoning?.supported && reasoningOptions.length > 0
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
          <Field
            label={t('config_model_name')}
            labelAction={ModelFieldLink ? <ModelFieldLink /> : undefined}
          >
            {CustomModelPicker ? (
              <CustomModelPicker value={model} onChange={setModel} />
            ) : isCustomProvider ? (
              // Custom providers have no preset catalog: type the model directly.
              <TextInput
                className="font-mono"
                value={customModel}
                onChange={(e) => handleCustomModelInput(e.target.value)}
                placeholder={t('config_custom_model_hint')}
              />
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
                    onChange={(e) => handleCustomModelInput(e.target.value)}
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
            <Field
              label={t('onboarding_apikey')}
              labelAction={ApiKeyFieldLink ? <ApiKeyFieldLink /> : undefined}
            >
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
                  : 'border-default bg-inset-2 hover:border-accent'
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
              id="cfg-max-tokens"
              type="number"
              className={`font-mono transition-shadow ${
                highlightBudget ? 'ring-2 ring-accent/50 border-accent' : ''
              }`}
              value={maxTokens}
              onChange={(e) => setMaxTokens(digitsOnly(e.target.value))}
            />
          </Field>
          <Field label={t('config_max_turns')} hint={t('config_max_turns_hint')}>
            <TextInput
              type="number"
              className="font-mono"
              value={maxTurns}
              onChange={(e) => setMaxTurns(digitsOnly(e.target.value))}
            />
          </Field>
          <Field label={t('config_max_steps')} hint={t('config_max_steps_hint')}>
            <TextInput
              type="number"
              className="font-mono"
              value={maxSteps}
              onChange={(e) => setMaxSteps(digitsOnly(e.target.value))}
            />
          </Field>
          <div className="flex items-center justify-between py-1">
            <div>
              <div className="text-sm font-medium text-content">{t('config_thinking')}</div>
              <div className="text-xs text-content-tertiary mt-0.5">{t('config_thinking_hint')}</div>
            </div>
            <Toggle checked={thinking} onChange={setThinking} />
          </div>
          {showReasoningEffort && (
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
              <div className="text-sm font-medium text-content">{t('config_subagent')}</div>
              <div className="text-xs text-content-tertiary mt-0.5">{t('config_subagent_hint')}</div>
            </div>
            <Toggle checked={subagent} onChange={setSubagent} />
          </div>
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
          <Field label={t('config_permission')} hint={t('config_permission_desc')}>
            <Dropdown
              value={permissionMode}
              options={PERMISSION_MODE_ORDER.filter(
                (m) => !config?.permission_modes?.length || config.permission_modes.includes(m)
              ).map((m) => ({
                value: m,
                label: t(PERMISSION_META[m].key),
                hint: t(PERMISSION_META[m].descKey),
              }))}
              onChange={savePermission}
            />
            {permStatus && <p className="text-xs text-accent mt-1">{permStatus}</p>}
          </Field>
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

      {/* System — notification preferences (client-side, no save) */}
      <Card icon={<Settings size={16} />} title={t('config_system')}>
        <div className="space-y-4">
          <div className="flex items-center justify-between py-1">
            <div>
              <div className="text-sm font-medium text-content">{t('config_task_notify')}</div>
              <div className="text-xs text-content-tertiary mt-0.5">{t('config_task_notify_hint')}</div>
            </div>
            <Toggle checked={taskNotify} onChange={setTaskNotify} />
          </div>
          <div className="flex items-center justify-between py-1">
            <div>
              <div className="text-sm font-medium text-content">{t('config_task_notify_sound')}</div>
              <div className="text-xs text-content-tertiary mt-0.5">{t('config_task_notify_sound_hint')}</div>
            </div>
            <Toggle checked={taskNotifySound} onChange={setTaskNotifySound} />
          </div>
          {supportsLaunchAtLogin && (
            <div className="py-1">
              <div className="flex items-center justify-between">
                <div>
                  <div className="text-sm font-medium text-content">{t('config_launch_at_login')}</div>
                  <div className="text-xs text-content-tertiary mt-0.5">{t('config_launch_at_login_hint')}</div>
                </div>
                <Toggle checked={launchAtLogin} onChange={toggleLaunchAtLogin} />
              </div>
              {launchAtLoginError && (
                <div className="text-xs text-danger mt-1.5">{launchAtLoginError}</div>
              )}
            </div>
          )}
        </div>
      </Card>
    </div>
  )
}

export default BasicSettings
