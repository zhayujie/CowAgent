import React, { useState, useEffect, useRef, useCallback } from 'react'
import { ChevronDown, Check, Loader2 } from 'lucide-react'
import apiClient from '../api/client'
import type { ModelsData } from '../types'
import { localizedLabel } from '../i18n'

interface ModelSelectorProps {
  baseUrl: string
}

const ModelSelector: React.FC<ModelSelectorProps> = ({ baseUrl }) => {
  const [data, setData] = useState<ModelsData | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [open, setOpen] = useState(false)
  const [feedback, setFeedback] = useState<string | null>(null)
  const ref = useRef<HTMLDivElement>(null)

  const load = useCallback(async () => {
    try {
      const fresh = await apiClient.getModels()
      setData(fresh)
    } catch {
      // silently fail — the selector just won't appear
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    apiClient.setBaseUrl(baseUrl)
    load()
  }, [baseUrl, load])

  // Close dropdown when clicking outside
  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [open])

  if (loading || !data) return null

  const chatState = data.capabilities?.chat
  if (!chatState) return null

  const currentProvider = chatState.current_provider || ''
  const currentModel = chatState.current_model || ''
  const providerIds = chatState.providers || []

  // Build the full model-to-provider mapping
  const modelEntries: {
    providerId: string
    providerLabel: string
    model: string
  }[] = []

  for (const pid of providerIds) {
    const models = chatState.provider_models?.[pid]
    if (!models || models.length === 0) continue
    const label = localizedLabel(
      data.providers?.find((p) => p.id === pid)?.label || pid
    )
    for (const entry of models) {
      const modelName = typeof entry === 'string' ? entry : entry.value
      if (modelName) {
        modelEntries.push({
          providerId: pid,
          providerLabel: label,
          model: modelName,
        })
      }
    }
  }

  // If there's only one provider+model or nothing to switch to, hide entirely
  if (modelEntries.length <= 1) return null

  // Group by provider for the dropdown display
  const grouped: Record<string, { providerId: string; models: string[] }> = {}
  for (const e of modelEntries) {
    const key = e.providerId
    if (!grouped[key]) {
      grouped[key] = { providerId: key, models: [] }
    }
    if (!grouped[key].models.includes(e.model)) {
      grouped[key].models.push(e.model)
    }
  }

  const currentLabel =
    currentProvider && currentModel
      ? `${localizedLabel(
          data.providers?.find((p) => p.id === currentProvider)?.label || currentProvider
        )} · ${currentModel}`
      : currentModel || currentProvider || '--'

  const handleSwitch = async (providerId: string, model: string) => {
    setOpen(false)
    if (providerId === currentProvider && model === currentModel) return
    setSaving(true)
    try {
      const res = await apiClient.modelsAction({
        action: 'set_capability',
        capability: 'chat',
        provider_id: providerId,
        model,
      })
      if (res.status === 'success') {
        setFeedback(`${model}`)
        await load()
      } else {
        setFeedback('error')
      }
    } catch {
      setFeedback('error')
    } finally {
      setSaving(false)
      setTimeout(() => setFeedback(null), 2000)
    }
  }

  return (
    <div ref={ref} className="relative flex-shrink-0 px-4">
      <div className="max-w-3xl mx-auto flex items-center gap-2 pb-1.5">
        {/* Current model pill / trigger */}
        <button
          onClick={() => setOpen((v) => !v)}
          disabled={saving}
          className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[11px] text-content-tertiary hover:text-content-secondary hover:bg-surface-2 cursor-pointer transition-colors whitespace-nowrap disabled:opacity-50"
        >
          {saving ? (
            <Loader2 size={10} className="animate-spin" />
          ) : (
            <>
              <span className="truncate max-w-[160px]">{currentLabel}</span>
              <ChevronDown
                size={10}
                className={`transition-transform ${open ? 'rotate-180' : ''}`}
              />
            </>
          )}
          {feedback && feedback !== 'error' && (
            <span className="text-accent ml-1">✓ {feedback}</span>
          )}
          {feedback === 'error' && (
            <span className="text-danger ml-1">✗</span>
          )}
        </button>
      </div>

      {/* Dropdown menu */}
      {open && (
        <div className="absolute left-4 right-4 z-30 max-w-3xl mx-auto">
          <div className="rounded-xl border border-default bg-elevated shadow-xl p-1.5 max-h-64 overflow-y-auto">
            {Object.entries(grouped).map(([key, group]) => (
              <div key={key}>
                <div className="px-2.5 pt-1.5 pb-1 text-[11px] font-semibold uppercase tracking-wider text-content-tertiary">
                  {localizedLabel(
                    data.providers?.find((p) => p.id === group.providerId)?.label ||
                      group.providerId
                  )}
                </div>
                {group.models.map((m) => {
                  const isActive =
                    group.providerId === currentProvider && m === currentModel
                  return (
                    <button
                      key={`${group.providerId}::${m}`}
                      onClick={() => handleSwitch(group.providerId, m)}
                      className={`w-full flex items-center justify-between gap-3 px-2.5 py-2 rounded-lg text-left cursor-pointer transition-colors text-[13px] ${
                        isActive
                          ? 'bg-accent-soft text-accent font-medium'
                          : 'text-content-secondary hover:bg-surface-2'
                      }`}
                    >
                      <span>{m}</span>
                      {isActive && <Check size={13} className="shrink-0" />}
                    </button>
                  )
                })}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

export default ModelSelector
