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
  ExternalLink,
} from 'lucide-react'
import { t, localizedLabel } from '../../i18n'
import apiClient from '../../api/client'
import type {
  CapabilityState,
  ModelCatalogEntry,
  ModelsData,
  ModelProvider,
  SearchCapabilityState,
  SearchProviderMeta,
} from '../../types'
import { Card, Field, Dropdown, TextInput, Modal, Btn, MASK_RE } from './primitives'
import CapabilityCard from './CapabilityCard'
import { ChatFallbackButton } from './ChatFallbackCard'
import {
  ModelCatalogEditor,
  toDraftRows,
  diffAgainstSeed,
  normalizeRows,
  type CatalogDraftRow,
} from './ModelCatalogEditor'
import { normEntries, providerLabel, resolveVoices, CUSTOM_OPTION } from './modelsHelpers'
import { product } from '@product'

// Whether the "add custom provider" entry is available. Defaults to true.
const allowCustomProviders = product.models?.allowCustomProviders !== false

// LinkAI is an aggregation platform, so when the LinkAI provider is selected we
// point users to its console to create/manage the aggregated key. Only shown
// for that provider — other vendors manage keys on their own sites.
const ManageLinkAIKeyLink: React.FC = () => (
  <button
    type="button"
    onClick={() =>
      window.open('https://link-ai.tech/console/models?apikey=1', '_blank', 'noopener,noreferrer')
    }
    className="inline-flex items-center gap-1 text-xs text-accent hover:underline cursor-pointer"
  >
    {t('models_manage_api_key')}
    <ExternalLink size={11} className="shrink-0" />
  </button>
)

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

      {/* Chat — the fallback is a small button on this card's header rather
          than a separate card, since it's a rarely-touched safety net. */}
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
        action={
          <ChatFallbackButton
            state={caps.chat_fallback}
            data={data}
            busy={busy === 'chat_fallback'}
            status={statusMap.chat_fallback}
            onSave={({ enabled, chain }) =>
              run('chat_fallback', {
                action: 'set_capability',
                capability: 'chat_fallback',
                enabled,
                chain,
              })
            }
          />
        }
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
        onSaveSearchKey={(provider, value, anonymous) =>
          run(
            'search_key',
            provider === 'searxng'
              ? // SearXNG persists an instance URL, not an API key.
                { action: 'set_search_credential', provider, url: value }
              : { action: 'set_search_credential', provider, api_key: value, anonymous }
          )
        }
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
    className="group flex items-center gap-2.5 px-3 py-2.5 rounded-btn border border-default bg-inset-2 hover:border-accent cursor-pointer transition-colors text-left"
  >
    <span className="flex-shrink-0 w-7 h-7 rounded-lg bg-surface-2 text-content-secondary flex items-center justify-center text-xs font-bold">
      {(localizedLabel(provider.label) || provider.id || '?').slice(0, 1).toUpperCase()}
    </span>
    <span className="flex-1 min-w-0 text-sm font-medium text-content truncate">{localizedLabel(provider.label)}</span>
    <Pencil size={12} className="flex-shrink-0 text-content-tertiary group-hover:text-accent transition-colors" />
  </button>
)

const CUSTOM_PICK = '__custom_new__'

// Persist a provider's catalog overlay only when the draft's diff against the
// presets differs from what is already stored, so saving credentials alone
// never rewrites (or accidentally clears) a catalog the user didn't touch. The
// backend drops the overlay entirely when both overrides and hidden are empty.
async function persistCatalogIfChanged(
  provider: ModelProvider,
  rows: CatalogDraftRow[],
): Promise<void> {
  const seed = provider.seed || []
  const { models, hidden } = diffAgainstSeed(rows, seed)
  const savedOverrides = normalizeRows(toDraftRows(provider.catalog || []))
  const savedHidden = (provider.hidden || []).slice().sort()
  const unchanged =
    JSON.stringify(models) === JSON.stringify(savedOverrides) &&
    JSON.stringify(hidden.slice().sort()) === JSON.stringify(savedHidden)
  if (unchanged) return
  await apiClient.modelsAction({
    action: 'save_catalog',
    provider_id: provider.id,
    models,
    hidden,
  })
}

// A custom provider has no presets: its catalog is simply the whole model list,
// so there is no seed to diff against and nothing is ever tombstoned. Persist
// the normalized rows, skipping the write when they match the stored list.
async function persistCustomCatalog(
  providerId: string,
  rows: CatalogDraftRow[],
  saved: ModelCatalogEntry[],
): Promise<void> {
  const models = normalizeRows(rows)
  const savedNorm = normalizeRows(toDraftRows(saved))
  if (JSON.stringify(models) === JSON.stringify(savedNorm)) return
  await apiClient.modelsAction({
    action: 'save_catalog',
    provider_id: providerId,
    models,
    hidden: [],
  })
}

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
  // Catalog draft for the effective provider. Prefilled from its EFFECTIVE list
  // (presets − removals + overrides) so the user edits the full list; reloaded
  // whenever the effective provider changes.
  const [catalogRows, setCatalogRows] = useState<CatalogDraftRow[]>([])

  const loadCatalogRows = (p: ModelProvider | undefined) => {
    setCatalogRows(toDraftRows(p?.effective || p?.catalog || []))
  }

  // Load fields whenever the effective provider changes.
  useEffect(() => {
    if (!open) return
    const init = provider || (addMode ? firstUnconfigured : undefined)
    setPickId(provider ? provider.id : firstUnconfigured?.id || '')
    setApiKey(init?.api_key_masked || '')
    setApiBase(init?.api_base || '')
    setKeyDirty(false)
    setKeyVisible(false)
    loadCatalogRows(init)
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
    loadCatalogRows(p)
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
      await persistCatalogIfChanged(effective, catalogRows)
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
      size="lg"
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
      <Field
        label="API Key"
        labelAction={effective?.id === 'linkai' ? <ManageLinkAIKeyLink /> : undefined}
      >
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
      {effective && (
        <ModelCatalogEditor
          key={effective.id}
          provider={effective}
          rows={catalogRows}
          onRowsChange={setCatalogRows}
          isCustom={false}
          providerId={effective.id}
          apiBase={apiBase}
          apiKey={apiKey}
        />
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
  // A custom provider has no presets, so its catalog is simply its whole model
  // list (effective === catalog). Prefill from it when editing; empty for new.
  const [catalogRows, setCatalogRows] = useState<CatalogDraftRow[]>([])

  useEffect(() => {
    if (!target) return
    if (editing) {
      setName(editing.custom_name || localizedLabel(editing.label))
      setApiBase(editing.api_base || '')
      setApiKey(editing.api_key_masked || '')
      setCatalogRows(toDraftRows(editing.effective || editing.catalog || []))
    } else {
      setName('')
      setApiBase('')
      setApiKey('')
      setCatalogRows([])
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
      // The custom provider key is optional. Only touch it when the user
      // edited the field (keyDirty) and it isn't the masked placeholder; send
      // the value even when empty so an explicit clear is honored server-side.
      if (keyDirty && !MASK_RE.test(apiKey)) payload.api_key = apiKey.trim()
      const res = await apiClient.modelsAction(payload)
      // The provider id is `custom:<id>`; a create returns the new id, an edit
      // reuses the existing one. A custom provider has no presets, so the whole
      // list is its overrides and nothing is ever hidden.
      const cid = (res.id as string) || editing?.custom_id || ''
      if (cid) await persistCustomCatalog(`custom:${cid}`, catalogRows, editing?.catalog || [])
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
      size="lg"
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
      <ModelCatalogEditor
        key={editing?.custom_id || 'new'}
        provider={editing}
        rows={catalogRows}
        onRowsChange={setCatalogRows}
        isCustom
        providerId={editing ? `custom:${editing.custom_id}` : ''}
        apiBase={apiBase}
        apiKey={apiKey}
      />
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
  // With a catalog the model becomes a dropdown pick like built-in vendors;
  // free-form input remains only for catalog-less custom vendors.
  const providerHasCatalog = (id: string) =>
    !!data?.providers?.find((x) => x.id === id)?.catalog?.length
  const [customModel, setCustomModel] = useState(
    isCustomProvider(state.current_provider || '') && !providerHasCatalog(state.current_provider || '')
      ? state.current_model || ''
      : ''
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
    if (isCustomProvider(id) && !providerHasCatalog(id)) {
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
  const useFreeText = isCustomProvider(provider) && !providerHasCatalog(provider)
  const finalModel = useFreeText ? customModel.trim() : model

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
              {useFreeText ? (
                // Catalog-less custom vendor: type the model directly.
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

// Search providers that own a dedicated credential (as opposed to reusing a
// model-vendor key): a dedicated API key, or — for SearXNG — a self-hosted
// instance URL. AnySearch additionally supports an anonymous tier, so it
// counts as "configured" even without a key. Mirrors the web console flow.
const isDedicatedKeyProvider = (p: SearchProviderMeta): boolean =>
  p.needs_dedicated_key ||
  p.needs_url ||
  ['bocha', 'anysearch', 'serply', 'tavily', 'searxng', 'keenable'].includes(p.id)

const SearchCard: React.FC<{
  state: SearchCapabilityState
  busy: boolean
  status?: string
  onSaveStrategy: (strategy: string, provider: string) => void
  onSaveSearchKey: (provider: string, key: string, anonymous: boolean) => void
  keyStatus?: string
  keyBusy: boolean
}> = ({ state, busy, status, onSaveStrategy, onSaveSearchKey, keyStatus, keyBusy }) => {
  const [strategy, setStrategy] = useState<string>(state.strategy || 'auto')
  const [provider, setProvider] = useState<string>(state.fixed_provider || state.current_provider || '')
  // The dedicated-key provider currently open in the credential modal, or null.
  const [keyProvider, setKeyProvider] = useState<SearchProviderMeta | null>(null)
  // Two-step add flow: when >1 dedicated provider is unconfigured, first show a
  // picker; a single unconfigured one opens its editor directly.
  const [pickerOpen, setPickerOpen] = useState(false)

  const providerOptions = useMemo(
    () => state.providers.map((p) => ({ value: p.id, label: localizedLabel(p.label) })),
    [state.providers]
  )

  // Providers that hold their own key: split into configured (editable chips)
  // and unconfigured (offered behind the "+ add" entry).
  const dedicated = useMemo(() => state.providers.filter(isDedicatedKeyProvider), [state.providers])
  const configured = dedicated.filter((p) => p.configured)
  const missing = dedicated.filter((p) => !p.configured)

  const openProvider = (p: SearchProviderMeta) => {
    setPickerOpen(false)
    setKeyProvider(p)
  }
  const onAdd = () => {
    if (missing.length === 0) return
    if (missing.length === 1) openProvider(missing[0])
    else setPickerOpen(true)
  }

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

        {/* Dedicated-key providers: configured chips (click to edit) + add entry. */}
        <Field label={t('models_search_bocha_key')}>
          <div className="flex items-center flex-wrap gap-2">
            {configured.map((p) => (
              <button
                key={p.id}
                onClick={() => openProvider(p)}
                title={t('models_search_edit_hint')}
                className="inline-flex items-center gap-1 px-2 py-1 rounded-btn text-xs bg-accent-soft text-accent hover:opacity-80 cursor-pointer transition-opacity"
              >
                <Check size={12} />
                {localizedLabel(p.label)}
                {p.anonymous && ` · ${t('models_search_anonymous_badge')}`}
              </button>
            ))}
            {missing.length > 0 && (
              <button
                onClick={onAdd}
                className="inline-flex items-center gap-1 px-2 py-1 rounded-btn text-xs border border-dashed border-default text-content-tertiary hover:border-accent hover:text-accent cursor-pointer transition-colors"
              >
                <Plus size={12} />
                {t('models_search_add_provider')}
              </button>
            )}
            {configured.length === 0 && missing.length === 0 && (
              <span className="text-xs text-content-tertiary">{t('models_search_none_configured')}</span>
            )}
          </div>
        </Field>

        <div className="flex items-center justify-end gap-3">
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

      {/* Add-provider picker (only when >1 unconfigured dedicated provider). */}
      <Modal
        open={pickerOpen}
        title={t('models_search_add_provider')}
        onClose={() => setPickerOpen(false)}
        footer={
          <Btn variant="ghost" onClick={() => setPickerOpen(false)}>
            {t('config_cancel')}
          </Btn>
        }
      >
        <p className="text-xs text-content-tertiary mb-3">{t('models_search_add_desc')}</p>
        <div className="space-y-2">
          {missing.map((p) => (
            <button
              key={p.id}
              onClick={() => openProvider(p)}
              className="w-full flex items-center justify-between px-3 py-2.5 rounded-btn bg-inset-2 hover:bg-surface-2 text-sm text-content cursor-pointer transition-colors"
            >
              <span>{localizedLabel(p.label)}</span>
              <ExternalLink size={12} className="text-content-tertiary" />
            </button>
          ))}
        </div>
      </Modal>

      <SearchKeyModal
        provider={keyProvider}
        busy={keyBusy}
        status={keyStatus}
        onClose={() => setKeyProvider(null)}
        onSave={(key, anonymous) => {
          if (keyProvider) onSaveSearchKey(keyProvider.id, key, anonymous)
          setKeyProvider(null)
        }}
      />
    </Card>
  )
}

// Dedicated-credential editor for a single search provider. Most providers
// hold an API key; SearXNG holds a self-hosted instance URL (echoed back
// verbatim, not masked). AnySearch adds an anonymous option: saving with an
// empty key enables the anonymous tier.
const SearchKeyModal: React.FC<{
  provider: SearchProviderMeta | null
  busy: boolean
  status?: string
  onClose: () => void
  onSave: (value: string, anonymous: boolean) => void
}> = ({ provider, busy, onClose, onSave }) => {
  const open = !!provider
  // anysearch and keenable share the "save empty = enable anonymous tier" contract.
  const isAnonymousProvider = provider?.id === 'anysearch' || provider?.id === 'keenable'
  const isSearxng = provider?.id === 'searxng' || !!provider?.needs_url
  // SearXNG prefills its plain instance URL; others prefill the masked key.
  const initial = isSearxng ? provider?.url_masked || '' : provider?.api_key_masked || ''
  const [value, setValue] = useState('')
  const [dirty, setDirty] = useState(false)

  useEffect(() => {
    if (open) {
      setValue(initial)
      setDirty(false)
    }
  }, [open, initial])

  if (!provider) return null

  const title = t(`models_search_${provider.id}_title`)
  const desc = t(`models_search_${provider.id}_desc`)

  const handleSave = () => {
    if (isSearxng) {
      // URL is plain text (never masked). Empty is a no-op here — use the
      // configured chip / clear flow to remove it.
      const trimmed = value.trim()
      if (!dirty || !trimmed) {
        onClose()
        return
      }
      onSave(trimmed, false)
      return
    }
    // Kept the masked placeholder untouched -> nothing to persist.
    if (!dirty || MASK_RE.test(value)) {
      // anysearch/keenable: an untouched-but-empty field still means "anonymous".
      if (isAnonymousProvider && !initial) onSave('', true)
      else onClose()
      return
    }
    const trimmed = value.trim()
    // anysearch/keenable: empty key = enable anonymous mode.
    onSave(trimmed, isAnonymousProvider && !trimmed)
  }

  const fieldLabel = isSearxng ? t('models_search_instance_url') : 'API Key'
  const fieldHint = isSearxng
    ? undefined
    : isAnonymousProvider
      ? t('models_search_anysearch_anon_hint')
      : undefined
  const placeholder = isSearxng ? 'https://searxng.example.com' : 'sk-...'

  return (
    <Modal
      open={open}
      title={title}
      onClose={onClose}
      footer={
        <>
          <Btn variant="ghost" onClick={onClose}>
            {t('config_cancel')}
          </Btn>
          <Btn variant="primary" disabled={busy} onClick={handleSave}>
            {busy ? <Loader2 size={14} className="animate-spin" /> : t('config_save')}
          </Btn>
        </>
      }
    >
      <p className="text-xs text-content-tertiary mb-3">{desc}</p>
      <Field label={fieldLabel} hint={fieldHint}>
        <TextInput
          className={isSearxng ? '' : 'font-mono'}
          value={value}
          placeholder={placeholder}
          onFocus={() => {
            // Only API keys use a masked sentinel; URLs stay as-is.
            if (!isSearxng && !dirty && MASK_RE.test(value)) setValue('')
          }}
          onChange={(e) => {
            setValue(e.target.value)
            setDirty(true)
          }}
        />
      </Field>
    </Modal>
  )
}

export default ModelsTab
