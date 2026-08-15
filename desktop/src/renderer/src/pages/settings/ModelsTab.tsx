import React, { useCallback, useEffect, useMemo, useState } from 'react'
import {
  MessageSquare,
  Eye,
  Image as ImageIcon,
  Mic,
  Volume2,
  Database,
  Search as SearchIcon,
  Plus,
  Check,
  Loader2,
  Pencil,
  Eye as EyeIcon,
  EyeOff,
} from 'lucide-react'
import { t, localizedLabel } from '../../i18n'
import apiClient from '../../api/client'
import type { CapabilityState, ModelsData, ModelProvider, SearchCapabilityState } from '../../types'
import { Card, Field, Dropdown, TextInput, Modal, Btn, MASK_RE } from './primitives'
import CapabilityCard from './CapabilityCard'
import { normEntries, providerLabel, resolveVoices, CUSTOM_OPTION } from './modelsHelpers'
import { product } from '@product'

// Whether the "add custom provider" entry is available. Defaults to true.
const allowCustomProviders = product.models?.allowCustomProviders !== false

interface ModelsTabProps {
  baseUrl: string
}

const REPLY_MODES: { value: 'off' | 'voice_if_voice' | 'always'; key: string }[] = [
  { value: 'off', key: 'models_tts_mode_off' },
  { value: 'voice_if_voice', key: 'models_tts_mode_if_voice' },
  { value: 'always', key: 'models_tts_mode_always' },
]

const ModelsTab: React.FC<ModelsTabProps> = ({ baseUrl }) => {
  const [data, setData] = useState<ModelsData | null>(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState<string>('') // capability key currently saving
  const [statusMap, setStatusMap] = useState<Record<string, string>>({})

  const load = useCallback(async () => {
    try {
      const fresh = await apiClient.getModels()
      setData(fresh)
    } catch (e) {
      console.error('Failed to load models:', e)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    apiClient.setBaseUrl(baseUrl)
    load()
  }, [baseUrl, load])

  const flash = (key: string, msg: string) => {
    setStatusMap((m) => ({ ...m, [key]: msg }))
    setTimeout(() => setStatusMap((m) => ({ ...m, [key]: '' })), 2000)
  }

  // Run a models action, then refresh and flash a status for the given key.
  const run = async (key: string, action: Parameters<typeof apiClient.modelsAction>[0]) => {
    setBusy(key)
    try {
      const res = await apiClient.modelsAction(action)
      if (res.status === 'success') {
        await load()
        flash(key, t('config_saved'))
      } else {
        flash(key, (res.message as string) || t('config_save_error'))
      }
    } catch {
      flash(key, t('config_save_error'))
    } finally {
      setBusy('')
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
  if (!data) {
    return <div className="text-center py-20 text-content-tertiary">{t('config_save_error')}</div>
  }

  const caps = data.capabilities

  return (
    <div className="grid gap-5">
      <VendorSection data={data} onChanged={load} statusMap={statusMap} flash={flash} />

      {/* Chat */}
      <CapabilityCard
        icon={MessageSquare}
        title={t('models_cap_chat')}
        subtitle={t('models_cap_chat_sub')}
        capKey="chat"
        state={caps.chat}
        data={data}
        allowCustomModel
        busy={busy === 'chat'}
        status={statusMap.chat}
        onSave={(p, m) => run('chat', { action: 'set_capability', capability: 'chat', provider_id: p, model: m })}
      />

      {/* Vision */}
      <CapabilityCard
        icon={Eye}
        title={t('models_cap_vision')}
        subtitle={t('models_cap_vision_sub')}
        capKey="vision"
        state={caps.vision}
        data={data}
        allowAuto
        autoLabel={t('models_auto')}
        busy={busy === 'vision'}
        status={statusMap.vision}
        onSave={(p, m) => run('vision', { action: 'set_capability', capability: 'vision', provider_id: p, model: m })}
      >
        <FallbackHint state={caps.vision} data={data} />
      </CapabilityCard>

      {/* Image */}
      <CapabilityCard
        icon={ImageIcon}
        title={t('models_cap_image')}
        subtitle={t('models_cap_image_sub')}
        capKey="image"
        state={caps.image}
        data={data}
        allowAuto
        autoLabel={t('models_auto')}
        busy={busy === 'image'}
        status={statusMap.image}
        onSave={(p, m) => run('image', { action: 'set_capability', capability: 'image', provider_id: p, model: m })}
      >
        <FallbackHint state={caps.image} data={data} />
      </CapabilityCard>

      {/* ASR */}
      <CapabilityCard
        icon={Mic}
        title={t('models_cap_asr')}
        subtitle={t('models_cap_asr_sub')}
        capKey="asr"
        state={caps.asr}
        data={data}
        allowAuto
        autoLabel={t('models_asr_auto')}
        allowCustomModel
        busy={busy === 'asr'}
        status={statusMap.asr}
        onSave={(p, m) => run('asr', { action: 'set_capability', capability: 'asr', provider_id: p, model: m })}
      />

      {/* TTS — bespoke (voice + reply mode) */}
      <TtsCard
        state={caps.tts}
        data={data}
        busy={busy === 'tts'}
        status={statusMap.tts}
        onSaveVoice={(p, m, v) =>
          run('tts', { action: 'set_capability', capability: 'tts', provider_id: p, model: m, voice: v })
        }
        onSaveMode={(mode) => run('tts_mode', { action: 'set_voice_reply_mode', mode })}
        modeStatus={statusMap.tts_mode}
        modeBusy={busy === 'tts_mode'}
      />

      {/* Embedding */}
      <EmbeddingCard
        state={caps.embedding}
        data={data}
        busy={busy === 'embedding'}
        status={statusMap.embedding}
        onSave={(p, m) => run('embedding', { action: 'set_capability', capability: 'embedding', provider_id: p, model: m })}
      />

      {/* Search — bespoke */}
      <SearchCard
        state={caps.search}
        busy={busy === 'search'}
        status={statusMap.search}
        onSaveStrategy={(strategy, provider) =>
          run('search', { action: 'set_capability', capability: 'search', strategy, provider })
        }
        onSaveBochaKey={(key) => run('search_key', { action: 'set_search_credential', api_key: key })}
        keyStatus={statusMap.search_key}
        keyBusy={busy === 'search_key'}
      />
    </div>
  )
}

// ============================================================
// Layer 1 — vendor credentials
// ============================================================

interface VendorSectionProps {
  data: ModelsData
  onChanged: () => Promise<void>
  statusMap: Record<string, string>
  flash: (key: string, msg: string) => void
}

const VendorSection: React.FC<VendorSectionProps> = ({ data, onChanged }) => {
  // Edit an existing built-in vendor.
  const [editing, setEditing] = useState<ModelProvider | null>(null)
  // Add flow: open the vendor modal with a provider picker.
  const [adding, setAdding] = useState(false)
  // Custom provider modal: 'new' to create, or a provider to edit.
  const [customEditing, setCustomEditing] = useState<ModelProvider | 'new' | null>(null)

  const isCustomCard = (p: ModelProvider) => p.is_custom && !!p.custom_name
  // Unified grid: configured built-ins + all custom provider cards (web parity).
  const shown = data.providers.filter((p) => p.configured || isCustomCard(p))

  return (
    <Card icon={<Database size={16} />} title={t('models_vendors')} subtitle={t('models_vendors_sub')}>
      {shown.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-8 rounded-btn border border-dashed border-default">
          <p className="text-sm text-content-tertiary">{t('models_no_vendor')}</p>
          <button
            onClick={() => setAdding(true)}
            className="mt-3 inline-flex items-center gap-1 px-3 py-1.5 rounded-btn text-xs font-medium bg-accent-soft text-accent hover:bg-accent-soft/70 cursor-pointer transition-colors"
          >
            <Plus size={12} /> {t('models_add_vendor')}
          </button>
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5">
          {shown.map((p) =>
            isCustomCard(p) ? (
              <VendorChip key={p.id} provider={p} onClick={() => setCustomEditing(p)} />
            ) : (
              <VendorChip key={p.id} provider={p} onClick={() => setEditing(p)} />
            )
          )}
          <button
            onClick={() => setAdding(true)}
            className="flex items-center justify-center gap-1.5 px-3 py-2.5 rounded-btn border border-dashed border-default text-content-tertiary hover:border-accent hover:text-accent cursor-pointer transition-colors text-sm"
          >
            <Plus size={14} /> {t('models_add_vendor')}
          </button>
        </div>
      )}

      <VendorModal
        provider={editing}
        addMode={adding}
        data={data}
        onClose={() => {
          setEditing(null)
          setAdding(false)
        }}
        onPickCustom={() => {
          setAdding(false)
          setCustomEditing('new')
        }}
        onSaved={onChanged}
      />
      <CustomProviderModal target={customEditing} onClose={() => setCustomEditing(null)} onSaved={onChanged} />
    </Card>
  )
}

const VendorChip: React.FC<{ provider: ModelProvider; onClick: () => void }> = ({ provider, onClick }) => (
  <button
    onClick={onClick}
    className="group flex items-center gap-2.5 px-3 py-2.5 rounded-btn border border-default bg-inset hover:border-accent cursor-pointer transition-colors text-left"
  >
    <span className="flex-shrink-0 w-7 h-7 rounded-lg bg-surface-2 text-content-secondary flex items-center justify-center text-xs font-bold">
      {(localizedLabel(provider.label) || provider.id || '?').slice(0, 1).toUpperCase()}
    </span>
    <span className="flex-1 min-w-0 text-sm font-medium text-content truncate">{localizedLabel(provider.label)}</span>
    <Pencil size={12} className="flex-shrink-0 text-content-tertiary group-hover:text-accent transition-colors" />
  </button>
)

const CUSTOM_PICK = '__custom_new__'

const VendorModal: React.FC<{
  provider: ModelProvider | null
  addMode: boolean
  data: ModelsData
  onClose: () => void
  onPickCustom: () => void
  onSaved: () => Promise<void>
}> = ({ provider, addMode, data, onClose, onPickCustom, onSaved }) => {
  const open = !!provider || addMode

  // In add-mode the user first picks a built-in provider; that selection
  // becomes the effective provider whose key/base fields we edit. Exclude ALL
  // custom providers (named or empty placeholder): custom vendors are added via
  // the single "custom vendor" option below, so an empty custom placeholder must
  // not show up here as a second, duplicate custom entry.
  const builtins = useMemo(() => data.providers.filter((p) => !p.is_custom), [data.providers])
  const firstUnconfigured = builtins.find((p) => !p.configured) || builtins[0]
  const [pickId, setPickId] = useState('')

  const effective: ModelProvider | undefined = provider || builtins.find((p) => p.id === pickId)

  const [apiKey, setApiKey] = useState('')
  const [keyDirty, setKeyDirty] = useState(false)
  const [keyVisible, setKeyVisible] = useState(false)
  const [apiBase, setApiBase] = useState('')
  const [saving, setSaving] = useState(false)

  // Load fields whenever the effective provider changes.
  useEffect(() => {
    if (!open) return
    const init = provider || (addMode ? firstUnconfigured : undefined)
    setPickId(provider ? provider.id : firstUnconfigured?.id || '')
    setApiKey(init?.api_key_masked || '')
    setApiBase(init?.api_base || '')
    setKeyDirty(false)
    setKeyVisible(false)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [provider, addMode, open])

  if (!open) return null

  const pickOptions = [
    ...builtins.map((p) => ({
      value: p.id,
      label: localizedLabel(p.label),
      hint: p.configured ? t('models_configured') : undefined,
    })),
    ...(allowCustomProviders
      ? [{ value: CUSTOM_PICK, label: t('models_custom_vendor'), hint: t('models_add_custom_hint') }]
      : []),
  ]

  const onPick = (val: string) => {
    if (val === CUSTOM_PICK) {
      onPickCustom()
      return
    }
    setPickId(val)
    const p = builtins.find((x) => x.id === val)
    setApiKey(p?.api_key_masked || '')
    setApiBase(p?.api_base || '')
    setKeyDirty(false)
  }

  const hasBase = !!effective?.api_base_field

  const save = async () => {
    if (!effective) return
    setSaving(true)
    try {
      const payload: { action: 'set_provider'; provider_id: string; api_key?: string; api_base?: string } = {
        action: 'set_provider',
        provider_id: effective.id,
      }
      if (keyDirty && apiKey && !MASK_RE.test(apiKey)) payload.api_key = apiKey
      if (hasBase) payload.api_base = apiBase
      await apiClient.modelsAction(payload)
      await onSaved()
      onClose()
    } finally {
      setSaving(false)
    }
  }

  const clear = async () => {
    if (!effective || !confirm(t('models_clear_confirm'))) return
    setSaving(true)
    try {
      await apiClient.modelsAction({ action: 'delete_provider', provider_id: effective.id })
      await onSaved()
      onClose()
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal
      open={open}
      title={addMode ? t('models_add_vendor') : localizedLabel(effective?.label)}
      onClose={onClose}
      footer={
        <>
          {!addMode && effective?.configured && (
            <Btn variant="danger" onClick={clear} disabled={saving}>
              {t('models_clear')}
            </Btn>
          )}
          <Btn variant="ghost" onClick={onClose}>
            {t('config_cancel')}
          </Btn>
          <Btn variant="primary" onClick={save} disabled={saving || !effective}>
            {saving ? <Loader2 size={14} className="animate-spin" /> : t('config_save')}
          </Btn>
        </>
      }
    >
      {addMode && (
        <Field label={t('models_provider')}>
          <Dropdown value={pickId} options={pickOptions} onChange={onPick} />
        </Field>
      )}
      <Field label="API Key">
        <div className="relative">
          <TextInput
            type={keyVisible ? 'text' : 'password'}
            className="pr-10 font-mono"
            value={apiKey}
            placeholder="sk-..."
            onFocus={() => {
              if (!keyDirty && MASK_RE.test(apiKey)) setApiKey('')
            }}
            onBlur={() => {
              if (!keyDirty) setApiKey(effective?.api_key_masked || '')
            }}
            onChange={(e) => {
              setApiKey(e.target.value)
              setKeyDirty(true)
            }}
          />
          <button
            type="button"
            onClick={() => setKeyVisible((v) => !v)}
            className="absolute right-2.5 top-1/2 -translate-y-1/2 text-content-tertiary hover:text-content-secondary cursor-pointer p-1"
          >
            {keyVisible ? <EyeOff size={14} /> : <EyeIcon size={14} />}
          </button>
        </div>
      </Field>
      {hasBase && (
        <Field label="API Base">
          <TextInput
            className="font-mono"
            value={apiBase}
            onChange={(e) => setApiBase(e.target.value)}
            placeholder={effective?.api_base_placeholder || 'https://...'}
          />
        </Field>
      )}
    </Modal>
  )
}

const CustomProviderModal: React.FC<{
  target: ModelProvider | 'new' | null
  onClose: () => void
  onSaved: () => Promise<void>
}> = ({ target, onClose, onSaved }) => {
  const editing = target && target !== 'new' ? target : null
  const [name, setName] = useState('')
  const [apiBase, setApiBase] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [keyDirty, setKeyDirty] = useState(false)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (!target) return
    if (editing) {
      setName(editing.custom_name || localizedLabel(editing.label))
      setApiBase(editing.api_base || '')
      setApiKey(editing.api_key_masked || '')
    } else {
      setName('')
      setApiBase('')
      setApiKey('')
    }
    setKeyDirty(false)
  }, [target, editing])

  if (!target) return null

  const save = async () => {
    if (!name.trim()) return
    setSaving(true)
    try {
      const payload: {
        action: 'set_custom_provider'
        name: string
        id?: string
        api_base: string
        api_key?: string
      } = {
        action: 'set_custom_provider',
        name: name.trim(),
        api_base: apiBase.trim(),
      }
      if (editing) payload.id = editing.custom_id
      if (keyDirty && apiKey && !MASK_RE.test(apiKey)) payload.api_key = apiKey
      await apiClient.modelsAction(payload)
      await onSaved()
      onClose()
    } finally {
      setSaving(false)
    }
  }

  const remove = async () => {
    if (!editing || !confirm(t('models_delete_confirm'))) return
    setSaving(true)
    try {
      await apiClient.modelsAction({ action: 'delete_custom_provider', id: editing.custom_id || '' })
      await onSaved()
      onClose()
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal
      open={!!target}
      title={editing ? t('models_edit_custom') : t('models_add_custom')}
      onClose={onClose}
      footer={
        <>
          {editing && (
            <Btn variant="danger" onClick={remove} disabled={saving}>
              {t('models_delete')}
            </Btn>
          )}
          <Btn variant="ghost" onClick={onClose}>
            {t('config_cancel')}
          </Btn>
          <Btn variant="primary" onClick={save} disabled={saving || !name.trim() || (!editing && !apiBase.trim())}>
            {saving ? <Loader2 size={14} className="animate-spin" /> : t('config_save')}
          </Btn>
        </>
      }
    >
      <Field label={t('models_custom_name')}>
        <TextInput value={name} onChange={(e) => setName(e.target.value)} placeholder="My Provider" />
      </Field>
      <Field label="API Base" hint={t('models_custom_base_hint')}>
        <TextInput
          className="font-mono"
          value={apiBase}
          onChange={(e) => setApiBase(e.target.value)}
          placeholder="https://...../v1"
        />
      </Field>
      <Field label="API Key">
        <TextInput
          type="text"
          className="font-mono"
          value={apiKey}
          placeholder="sk-..."
          onFocus={() => {
            if (!keyDirty && MASK_RE.test(apiKey)) setApiKey('')
          }}
          onChange={(e) => {
            setApiKey(e.target.value)
            setKeyDirty(true)
          }}
        />
      </Field>
    </Modal>
  )
}

// ============================================================
// Bespoke capability cards
// ============================================================

const FallbackHint: React.FC<{ state: CapabilityState; data: ModelsData }> = ({ state, data }) => {
  if (!state.fallback_provider && !state.fallback_model) return null
  const label = providerLabel(data, state.fallback_provider || '')
  return (
    <p className="text-xs text-content-tertiary">
      {t('models_fallback')}: {label} {state.fallback_model ? `· ${state.fallback_model}` : ''}
    </p>
  )
}

const TtsCard: React.FC<{
  state: CapabilityState
  data: ModelsData
  busy: boolean
  status?: string
  onSaveVoice: (provider: string, model: string, voice: string) => void
  onSaveMode: (mode: 'off' | 'voice_if_voice' | 'always') => void
  modeStatus?: string
  modeBusy: boolean
}> = ({ state, data, busy, status, onSaveVoice, onSaveMode, modeStatus, modeBusy }) => {
  const [provider, setProvider] = useState(state.current_provider || '')
  const [model, setModel] = useState(state.current_model || '')
  // Custom (OpenAI-compatible) vendors have no preset catalog: type the model.
  // Covers expanded custom:<id> cards and the legacy flat "custom" entry.
  const isCustomProvider = (id: string) => id.startsWith('custom:') || id === 'custom'
  const [customModel, setCustomModel] = useState(
    isCustomProvider(state.current_provider || '') ? state.current_model || '' : ''
  )
  const [voice, setVoice] = useState(state.current_voice || '')
  const [mode, setMode] = useState<'off' | 'voice_if_voice' | 'always'>(state.reply_mode || 'off')

  const providerOptions = (state.providers || []).map((id) => ({ value: id, label: providerLabel(data, id) }))
  const modelOptions = normEntries(state.provider_models?.[provider]).map((o) => ({
    value: o.value,
    label: o.value,
    hint: o.hint,
  }))
  const voiceOptions = resolveVoices(provider, model, state.provider_voices).map((o) => ({
    value: o.value,
    label: o.value,
    hint: o.hint,
  }))

  const handleProvider = (id: string) => {
    setProvider(id)
    if (isCustomProvider(id)) {
      // Prefill with the saved model when re-selecting the same provider.
      setCustomModel(id === state.current_provider ? state.current_model || '' : '')
      setModel('')
      setVoice('')
      return
    }
    setCustomModel('')
    const first = normEntries(state.provider_models?.[id])[0]
    const fm = first?.value || ''
    setModel(fm)
    setVoice(resolveVoices(id, fm, state.provider_voices)[0]?.value || '')
  }
  const handleModel = (m: string) => {
    setModel(m)
    setVoice(resolveVoices(provider, m, state.provider_voices)[0]?.value || '')
  }
  const finalModel = isCustomProvider(provider) ? customModel.trim() : model

  return (
    <Card icon={<Volume2 size={16} />} title={t('models_cap_tts')} subtitle={t('models_cap_tts_sub')}>
      <div className="space-y-4">
        {/* Reply mode — saved immediately */}
        <Field label={t('models_tts_reply_mode')} hint={t('models_tts_reply_mode_hint')}>
          <Dropdown
            value={mode}
            options={REPLY_MODES.map((m) => ({ value: m.value, label: t(m.key) }))}
            onChange={(v) => {
              const next = v as 'off' | 'voice_if_voice' | 'always'
              setMode(next)
              onSaveMode(next)
            }}
            disabled={modeBusy}
          />
          {modeStatus && <span className="text-xs text-accent">{modeStatus}</span>}
        </Field>

        {mode !== 'off' && (
          <>
            <Field label={t('models_provider')}>
              <Dropdown
                value={provider}
                options={providerOptions}
                placeholder={t('models_select_provider')}
                onChange={handleProvider}
              />
            </Field>
            <Field label={t('models_model')}>
              {isCustomProvider(provider) ? (
                // Custom vendors have no preset catalog: type the model directly.
                <TextInput
                  className="font-mono"
                  value={customModel}
                  onChange={(e) => setCustomModel(e.target.value)}
                  placeholder={t('config_custom_model_hint')}
                />
              ) : (
                <Dropdown
                  value={model}
                  options={modelOptions}
                  placeholder={t('models_select_model')}
                  onChange={handleModel}
                />
              )}
            </Field>
            {voiceOptions.length > 0 && (
              <Field label={t('models_voice')}>
                <Dropdown value={voice} options={voiceOptions} placeholder={t('models_select_voice')} onChange={setVoice} />
              </Field>
            )}
            <div className="flex items-center justify-end gap-3 pt-1">
              <span className={`text-xs text-accent transition-opacity ${status ? 'opacity-100' : 'opacity-0'}`}>
                {status}
              </span>
              <button
                disabled={busy}
                onClick={() => onSaveVoice(provider, finalModel, voice)}
                className="px-4 py-2 rounded-btn bg-accent text-accent-contrast hover:bg-accent-hover text-sm font-medium cursor-pointer transition-colors disabled:opacity-50 inline-flex items-center gap-2"
              >
                {busy && <Loader2 size={14} className="animate-spin" />}
                {t('config_save')}
              </button>
            </div>
          </>
        )}
      </div>
    </Card>
  )
}

const EmbeddingCard: React.FC<{
  state: CapabilityState
  data: ModelsData
  busy: boolean
  status?: string
  onSave: (provider: string, model: string) => void
}> = ({ state, data, busy, status, onSave }) => (
  <CapabilityCard
    icon={Database}
    title={t('models_cap_embedding')}
    subtitle={t('models_cap_embedding_sub')}
    capKey="embedding"
    state={state}
    data={data}
    allowAuto
    autoLabel={t('models_disabled')}
    busy={busy}
    status={status}
    onSave={onSave}
  >
    {state.current_dim != null && (
      <p className="text-xs text-content-tertiary">
        {t('models_embedding_dim')}: {state.current_dim} · {t('models_embedding_rebuild_hint')}
      </p>
    )}
  </CapabilityCard>
)

const SearchCard: React.FC<{
  state: SearchCapabilityState
  busy: boolean
  status?: string
  onSaveStrategy: (strategy: string, provider: string) => void
  onSaveBochaKey: (key: string) => void
  keyStatus?: string
  keyBusy: boolean
}> = ({ state, busy, status, onSaveStrategy, onSaveBochaKey, keyStatus, keyBusy }) => {
  const [strategy, setStrategy] = useState<string>(state.strategy || 'auto')
  const [provider, setProvider] = useState<string>(state.fixed_provider || state.current_provider || '')
  const [bochaOpen, setBochaOpen] = useState(false)

  const providerOptions = useMemo(
    () => state.providers.map((p) => ({ value: p.id, label: localizedLabel(p.label) })),
    [state.providers]
  )
  const bocha = state.providers.find((p) => p.id === 'bocha')

  return (
    <Card icon={<SearchIcon size={16} />} title={t('models_cap_search')} subtitle={t('models_cap_search_sub')}>
      <div className="space-y-4">
        <Field label={t('models_search_strategy')}>
          <Dropdown
            value={strategy}
            options={[
              { value: 'auto', label: t('models_search_auto') },
              { value: 'fixed', label: t('models_search_fixed') },
            ]}
            onChange={setStrategy}
          />
        </Field>
        {strategy === 'fixed' && (
          <Field label={t('models_search_provider')}>
            <Dropdown
              value={provider}
              options={providerOptions}
              placeholder={t('models_select_provider')}
              onChange={setProvider}
            />
          </Field>
        )}
        <div className="flex items-center justify-between">
          <button
            onClick={() => setBochaOpen(true)}
            className="text-xs text-accent hover:text-accent-hover cursor-pointer inline-flex items-center gap-1"
          >
            {t('models_search_bocha_key')}
            {bocha?.configured && <Check size={12} />}
          </button>
          <div className="flex items-center gap-3">
            <span className={`text-xs text-accent transition-opacity ${status ? 'opacity-100' : 'opacity-0'}`}>
              {status}
            </span>
            <button
              disabled={busy || (strategy === 'fixed' && !provider)}
              onClick={() => onSaveStrategy(strategy, provider)}
              className="px-4 py-2 rounded-btn bg-accent text-accent-contrast hover:bg-accent-hover text-sm font-medium cursor-pointer transition-colors disabled:opacity-50 inline-flex items-center gap-2"
            >
              {busy && <Loader2 size={14} className="animate-spin" />}
              {t('config_save')}
            </button>
          </div>
        </div>
      </div>

      <BochaKeyModal
        open={bochaOpen}
        masked={bocha?.api_key_masked || ''}
        busy={keyBusy}
        status={keyStatus}
        onClose={() => setBochaOpen(false)}
        onSave={(k) => {
          onSaveBochaKey(k)
          setBochaOpen(false)
        }}
      />
    </Card>
  )
}

const BochaKeyModal: React.FC<{
  open: boolean
  masked: string
  busy: boolean
  status?: string
  onClose: () => void
  onSave: (key: string) => void
}> = ({ open, masked, busy, onClose, onSave }) => {
  const [key, setKey] = useState('')
  const [dirty, setDirty] = useState(false)
  useEffect(() => {
    if (open) {
      setKey(masked)
      setDirty(false)
    }
  }, [open, masked])
  return (
    <Modal
      open={open}
      title={t('models_search_bocha_key')}
      onClose={onClose}
      footer={
        <>
          <Btn variant="ghost" onClick={onClose}>
            {t('config_cancel')}
          </Btn>
          <Btn variant="primary" disabled={busy} onClick={() => onSave(dirty && !MASK_RE.test(key) ? key : '')}>
            {busy ? <Loader2 size={14} className="animate-spin" /> : t('config_save')}
          </Btn>
        </>
      }
    >
      <Field label="Bocha API Key" hint={t('models_search_bocha_hint')}>
        <TextInput
          className="font-mono"
          value={key}
          placeholder="sk-..."
          onFocus={() => {
            if (!dirty && MASK_RE.test(key)) setKey('')
          }}
          onChange={(e) => {
            setKey(e.target.value)
            setDirty(true)
          }}
        />
      </Field>
    </Modal>
  )
}

export default ModelsTab
