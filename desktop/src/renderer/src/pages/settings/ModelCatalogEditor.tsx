import React, { useEffect, useMemo, useState } from 'react'
import { ChevronDown, CloudDownload, Loader2, Plus, RotateCcw, Trash2 } from 'lucide-react'
import { t, tf } from '../../i18n'
import type { ModelCapability, ModelCatalogEntry, ModelProvider } from '../../types'
import { TextInput } from './primitives'
import { apiClient } from '../../api/client'

// The per-provider model catalog editor, embedded as a collapsible advanced
// section inside the vendor / custom-provider modals. It mirrors the web
// console's editor exactly, including the OVERLAY semantics:
//
// - The editor prefills the provider's EFFECTIVE list (presets − removals +
//   overrides), so the user always edits the full list — adding one model can
//   no longer wipe the rest.
// - On save we diff the draft against the provider's presets (`seed`) and
//   persist only `overrides` (rows the user changed or added) and `hidden`
//   (preset names the user removed). A row identical to its preset is NOT
//   persisted, so that model keeps following the code-side metadata and a later
//   constant bump still reaches it.
// - A custom provider has no presets (`seed` is empty), so every row is an
//   override and nothing is ever tombstoned.

const CAPABILITIES: ModelCapability[] = ['text', 'vision', 'video', 'image', 'embedding', 'asr', 'tts']

const CAP_TAG_KEYS: Record<ModelCapability, string> = {
  text: 'models_cap_tag_text',
  vision: 'models_cap_tag_vision',
  video: 'models_cap_tag_video',
  image: 'models_cap_tag_image',
  embedding: 'models_cap_tag_embedding',
  asr: 'models_cap_tag_asr',
  tts: 'models_cap_tag_tts',
}

// Capabilities with no notion of a text budget: an embedding/image/asr/tts model
// has no context window or max output, so those inputs are hidden for a row
// tagged only with these.
const UNBUDGETED: ModelCapability[] = ['embedding', 'image', 'asr', 'tts']

// A draft row keeps the numeric budgets as strings so an empty field means
// "unset" rather than 0; they are coerced back to numbers on save.
export interface CatalogDraftRow {
  name: string
  capabilities: ModelCapability[]
  context_window: string
  max_output_tokens: string
  alias?: string
}

const rowIsBudgeted = (caps: ModelCapability[]): boolean =>
  caps.length === 0 || caps.some((c) => !UNBUDGETED.includes(c))

/** Build a draft row list from stored catalog entries (effective/seed). */
export function toDraftRows(entries: ModelCatalogEntry[] | undefined): CatalogDraftRow[] {
  return (entries || []).map((e) => ({
    name: e.name || '',
    capabilities: (e.capabilities || []).slice(),
    context_window: e.context_window ? String(e.context_window) : '',
    max_output_tokens: e.max_output_tokens ? String(e.max_output_tokens) : '',
    alias: e.alias || '',
  }))
}

/** Normalize draft rows into the payload shape the backend stores, matching the
 *  web console's collectCatalogPayload/_normalizeEntries: drop unnamed rows,
 *  default capabilities to ['text'], and keep only positive budgets. */
export function normalizeRows(rows: CatalogDraftRow[]): ModelCatalogEntry[] {
  return rows
    .filter((e) => e.name.trim())
    .map((e) => {
      const caps = e.capabilities.length ? e.capabilities : (['text'] as ModelCapability[])
      const out: ModelCatalogEntry = { name: e.name.trim(), capabilities: caps }
      const cw = parseInt(e.context_window, 10)
      const mo = parseInt(e.max_output_tokens, 10)
      if (!Number.isNaN(cw) && cw > 0) out.context_window = cw
      // A model with no text budget can't carry a max output either.
      if (rowIsBudgeted(caps) && !Number.isNaN(mo) && mo > 0) out.max_output_tokens = mo
      const alias = (e.alias || '').trim()
      if (alias && alias !== out.name) out.alias = alias
      return out
    })
}

/** Diff the draft against the provider's presets into the overlay the backend
 *  stores: `models` (overrides) + `hidden` (removed preset names). */
export function diffAgainstSeed(
  rows: CatalogDraftRow[],
  seed: ModelCatalogEntry[],
): { models: ModelCatalogEntry[]; hidden: string[] } {
  const normSeed = normalizeRows(toDraftRows(seed))
  const draft = normalizeRows(rows)
  const seedByName: Record<string, ModelCatalogEntry> = {}
  normSeed.forEach((e) => {
    seedByName[e.name] = e
  })
  const draftNames = new Set(draft.map((e) => e.name))

  const models = draft.filter((e) => {
    const preset = seedByName[e.name]
    // A new model, or a preset the user edited: persist it. An unchanged preset
    // (deep-equal) is left out so it stays code-driven.
    return !preset || JSON.stringify(preset) !== JSON.stringify(e)
  })
  const hidden = normSeed.map((e) => e.name).filter((name) => !draftNames.has(name))
  return { models, hidden }
}

interface ModelCatalogEditorProps {
  provider: ModelProvider | null
  rows: CatalogDraftRow[]
  onRowsChange: (rows: CatalogDraftRow[]) => void
  // Custom providers show a hint (their catalog turns the model field into a
  // dropdown); built-in vendors show the "restore defaults" control instead.
  isCustom: boolean
  // Credentials currently typed in the parent modal. Discovery uses these
  // without persisting them first, so a provider can be inspected before Save.
  providerId?: string
  apiBase?: string
  apiKey?: string
}

const CapTag: React.FC<{ on: boolean; label: string; onClick: () => void }> = ({ on, label, onClick }) => (
  <button
    type="button"
    onClick={onClick}
    className={
      'px-1.5 py-0.5 rounded text-[10px] font-medium cursor-pointer transition-colors ' +
      (on
        ? 'bg-accent-soft text-accent'
        : 'bg-surface-2 text-content-tertiary hover:bg-hover')
    }
  >
    {label}
  </button>
)

export const ModelCatalogEditor: React.FC<ModelCatalogEditorProps> = ({
  provider,
  rows,
  onRowsChange,
  isCustom,
  providerId,
  apiBase,
  apiKey,
}) => {
  const seed = useMemo(() => provider?.seed || [], [provider])

  // Always start collapsed so credentials stay the focus — the catalog is an
  // advanced, opt-in section the user expands deliberately. The parent remounts
  // this editor per provider (via `key`), so it re-collapses on each open.
  const [open, setOpen] = useState(false)
  const [discovering, setDiscovering] = useState(false)
  const [discoverError, setDiscoverError] = useState('')
  const [discoverNotice, setDiscoverNotice] = useState('')
  const [discoverPick, setDiscoverPick] = useState<{
    candidates: CatalogDraftRow[]
    selected: string[]
  } | null>(null)

  useEffect(() => {
    setDiscoverPick(null)
    setDiscoverError('')
    setDiscoverNotice('')
  }, [providerId, provider?.id])

  const setRow = (idx: number, patch: Partial<CatalogDraftRow>) => {
    onRowsChange(rows.map((r, i) => (i === idx ? { ...r, ...patch } : r)))
  }

  const toggleCap = (idx: number, cap: ModelCapability) => {
    const row = rows[idx]
    const caps = row.capabilities.slice()
    const at = caps.indexOf(cap)
    if (at >= 0) caps.splice(at, 1)
    else caps.push(cap)
    const patch: Partial<CatalogDraftRow> = { capabilities: caps }
    // Clear budgets a now-unbudgeted row would otherwise keep sending.
    if (!rowIsBudgeted(caps)) {
      patch.context_window = ''
      patch.max_output_tokens = ''
    }
    setRow(idx, patch)
  }

  const addRow = () => {
    onRowsChange([
      ...rows,
      { name: '', capabilities: ['text'], context_window: '', max_output_tokens: '' },
    ])
  }

  const discover = async () => {
    setDiscovering(true)
    setDiscoverError('')
    setDiscoverNotice('')
    try {
      const key = apiKey && apiKey.includes('*') ? '' : (apiKey || '')
      const res = await apiClient.modelsAction({
        action: 'discover_models',
        provider_id: providerId || provider?.id || '',
        api_base: apiBase || '',
        api_key: key,
      })
      const found = Array.isArray(res.models) ? res.models : []
      const existing = new Set(rows.map((row) => row.name.trim()).filter(Boolean))
      const candidates: CatalogDraftRow[] = []
      for (const item of found) {
        const raw = item && typeof item === 'object' ? (item as Record<string, unknown>) : null
        const name = String((raw && raw.name) || '').trim()
        if (!name || existing.has(name)) continue
        existing.add(name)
        const caps = raw && (raw.capabilities as ModelCapability[] | undefined)
        const capabilities = Array.isArray(caps) && caps.length ? caps.slice() : (['text'] as ModelCapability[])
        candidates.push({
          name,
          capabilities,
          context_window: raw && raw.context_window ? String(raw.context_window) : '',
          max_output_tokens: raw && raw.max_output_tokens ? String(raw.max_output_tokens) : '',
        })
      }
      if (!candidates.length) {
        setDiscoverPick(null)
        setDiscoverNotice(t('models_catalog_discover_none'))
        return
      }
      setDiscoverPick({
        candidates,
        selected: candidates.filter((row) => row.capabilities.includes('text')).map((row) => row.name),
      })
    } catch (err) {
      setDiscoverError(err instanceof Error ? err.message : String(err))
    } finally {
      setDiscovering(false)
    }
  }

  const applyDiscoverPick = () => {
    if (!discoverPick) return
    const chosen = new Set(discoverPick.selected)
    const existing = new Set(rows.map((row) => row.name.trim()).filter(Boolean))
    const next = rows.slice()
    let added = 0
    for (const model of discoverPick.candidates) {
      if (!chosen.has(model.name) || existing.has(model.name)) continue
      existing.add(model.name)
      next.push(model)
      added += 1
    }
    onRowsChange(next)
    setDiscoverPick(null)
    setDiscoverNotice(tf('models_catalog_discovered', { n: added }))
  }

  const removeRow = (idx: number) => {
    onRowsChange(rows.filter((_, i) => i !== idx))
  }

  // Reset the draft to the vendor's presets: discard every override and un-hide
  // every removed preset. Saving afterwards clears the provider's overlay.
  const restoreDefaults = () => {
    onRowsChange(toDraftRows(seed))
  }

  return (
    <div className="rounded-lg border border-default">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center justify-between gap-2 px-3 py-2.5 cursor-pointer"
      >
        <span className="flex items-center gap-2 text-sm font-medium text-content-secondary">
          {t('models_catalog')}
          <span className="text-xs font-normal text-content-tertiary">{t('models_catalog_advanced')}</span>
        </span>
        <ChevronDown
          size={15}
          className={`text-content-tertiary transition-transform ${open ? 'rotate-180' : ''}`}
        />
      </button>

      {open && (
        <div className="px-3 pb-3 space-y-2">
          {isCustom && (
            <p className="text-xs text-content-tertiary leading-relaxed">{t('models_catalog_custom_hint')}</p>
          )}

          {rows.length > 0 && (
            <div className="space-y-2 max-h-[22rem] overflow-y-auto pr-0.5">
              {rows.map((row, idx) => {
                const budgeted = rowIsBudgeted(row.capabilities)
                return (
                  <div key={idx} className="rounded-lg border border-default bg-inset p-2.5">
                    <div className="flex items-center gap-2 mb-2">
                      <TextInput
                        className="flex-1 min-w-0 !py-1.5 text-xs font-mono"
                        value={row.name}
                        placeholder={t('models_catalog_name_ph')}
                        onChange={(e) => setRow(idx, { name: e.target.value })}
                      />
                      {isCustom && (
                        <TextInput
                          // The ! beats TextInput's own w-full, which comes
                          // later in the generated CSS.
                          className="!w-[38%] flex-shrink-0 !py-1.5 text-xs"
                          value={row.alias || ''}
                          maxLength={64}
                          placeholder={t('models_catalog_alias_ph')}
                          title={t('models_catalog_alias_tip')}
                          onChange={(e) => setRow(idx, { alias: e.target.value })}
                        />
                      )}
                      <button
                        type="button"
                        onClick={() => removeRow(idx)}
                        title={t('models_delete')}
                        className="flex-shrink-0 w-7 h-7 flex items-center justify-center rounded
                                   text-content-tertiary hover:text-danger hover:bg-danger/10
                                   cursor-pointer transition-colors"
                      >
                        <Trash2 size={12} />
                      </button>
                    </div>
                    <div className="flex flex-wrap gap-1.5 mb-2">
                      {CAPABILITIES.map((cap) => (
                        <CapTag
                          key={cap}
                          on={row.capabilities.includes(cap)}
                          label={t(CAP_TAG_KEYS[cap])}
                          onClick={() => toggleCap(idx, cap)}
                        />
                      ))}
                    </div>
                    {budgeted ? (
                      <div className="grid grid-cols-2 gap-2">
                        <label className="block">
                          <span className="block text-[10px] text-content-tertiary mb-0.5">
                            {t('models_catalog_window')}
                          </span>
                          <TextInput
                            type="number"
                            min={1}
                            className="!py-1 text-xs"
                            value={row.context_window}
                            placeholder="—"
                            onChange={(e) => setRow(idx, { context_window: e.target.value })}
                          />
                        </label>
                        <label className="block">
                          <span className="block text-[10px] text-content-tertiary mb-0.5">
                            {t('models_catalog_output')}
                          </span>
                          <TextInput
                            type="number"
                            min={1}
                            className="!py-1 text-xs"
                            value={row.max_output_tokens}
                            placeholder="—"
                            onChange={(e) => setRow(idx, { max_output_tokens: e.target.value })}
                          />
                        </label>
                      </div>
                    ) : (
                      <p className="text-[10px] text-content-tertiary">{t('models_catalog_no_budget')}</p>
                    )}
                  </div>
                )
              })}
            </div>
          )}

          <div className="flex items-center gap-2 pt-0.5">
            <button
              type="button"
              onClick={addRow}
              className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-btn text-xs font-medium
                         text-accent bg-accent-soft hover:bg-accent-soft/70 cursor-pointer transition-colors"
            >
              <Plus size={12} />
              {t('models_catalog_add')}
            </button>
            <button
              type="button"
              onClick={discover}
              disabled={discovering}
              className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-btn text-xs font-medium
                         text-content-secondary hover:bg-hover cursor-pointer transition-colors
                         disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {discovering ? <Loader2 size={12} className="animate-spin" /> : <CloudDownload size={12} />}
              {discovering ? t('models_catalog_discovering') : t('models_catalog_discover')}
            </button>
            {!isCustom && (
              <button
                type="button"
                onClick={restoreDefaults}
                className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-btn text-xs font-medium
                           text-content-tertiary hover:bg-hover cursor-pointer transition-colors"
              >
                <RotateCcw size={11} />
                {t('models_catalog_reset')}
              </button>
            )}
          </div>
          {discoverError && (
            <p className="text-xs text-danger break-words">{discoverError}</p>
          )}
          {discoverNotice && !discoverPick && (
            <p className="text-xs text-accent break-words">{discoverNotice}</p>
          )}
          {discoverPick && (
            <div className="rounded-lg border border-default p-2.5 space-y-2">
              <div className="text-xs font-medium text-content-secondary">
                {t('models_catalog_discover_pick')}
                <span className="font-normal text-content-tertiary">
                  {' '}
                  · {discoverPick.selected.length}/{discoverPick.candidates.length}
                </span>
              </div>
              <div className="max-h-48 overflow-y-auto space-y-1">
                {discoverPick.candidates.map((model) => {
                  const on = discoverPick.selected.includes(model.name)
                  return (
                    <label key={model.name} className="flex items-start gap-2 py-1 cursor-pointer">
                      <input
                        type="checkbox"
                        checked={on}
                        onChange={() =>
                          setDiscoverPick({
                            ...discoverPick,
                            selected: on
                              ? discoverPick.selected.filter((name) => name !== model.name)
                              : [...discoverPick.selected, model.name],
                          })
                        }
                        className="mt-0.5 cursor-pointer"
                      />
                      <span className="min-w-0">
                        <span className="block text-xs font-mono text-content break-all">{model.name}</span>
                        <span className="block text-[10px] text-content-tertiary">
                          {model.capabilities.map((cap) => t(CAP_TAG_KEYS[cap])).join(' · ')}
                        </span>
                      </span>
                    </label>
                  )
                })}
              </div>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={applyDiscoverPick}
                  className="inline-flex items-center px-2.5 py-1 rounded-btn text-xs font-medium
                             text-accent bg-accent-soft hover:bg-accent-soft/70 cursor-pointer"
                >
                  {t('models_catalog_discover_apply')}
                </button>
                <button
                  type="button"
                  onClick={() => setDiscoverPick(null)}
                  className="inline-flex items-center px-2.5 py-1 rounded-btn text-xs
                             text-content-tertiary hover:bg-hover cursor-pointer"
                >
                  {t('models_catalog_discover_cancel')}
                </button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export default ModelCatalogEditor
