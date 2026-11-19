import React, { useEffect, useState } from 'react'
import { Check, Copy, Eye, EyeOff, Plug, RotateCw } from 'lucide-react'
import { t, getLang } from '../../i18n'
import apiClient, { type ExternalApiState } from '../../api/client'
import { askConfirm } from '../../store/confirmStore'
import Tooltip from '../../components/Tooltip'
import { Card, FieldTip, Toggle } from './primitives'

type ExampleLang = 'curl' | 'python' | 'node'

const LANG_LABELS: Record<ExampleLang, string> = { curl: 'cURL', python: 'Python', node: 'Node.js' }

const maskKey = (key: string) => (key ? key.slice(0, 7) + '********' + key.slice(-4) : '')

function example(lang: ExampleLang, base: string, key: string): string {
  if (lang === 'python') {
    return [
      'import requests',
      '',
      'resp = requests.post(',
      `    "${base}/chat/completions",`,
      `    headers={"Authorization": "Bearer ${key}"},`,
      '    json={"messages": [{"role": "user", "content": "Hello"}]},',
      ')',
      'print(resp.json()["choices"][0]["message"]["content"])',
    ].join('\n')
  }
  if (lang === 'node') {
    return [
      `const resp = await fetch("${base}/chat/completions", {`,
      '  method: "POST",',
      `  headers: { "Authorization": "Bearer ${key}", "Content-Type": "application/json" },`,
      '  body: JSON.stringify({ messages: [{ role: "user", content: "Hello" }] }),',
      '});',
      'const data = await resp.json();',
      'console.log(data.choices[0].message.content);',
    ].join('\n')
  }
  return [
    `curl ${base}/chat/completions \\`,
    `  -H "Authorization: Bearer ${key}" \\`,
    '  -H "Content-Type: application/json" \\',
    `  -d '{"messages": [{"role": "user", "content": "Hello"}]}'`,
  ].join('\n')
}

export const CopyButton: React.FC<{ text: string; className?: string }> = ({ text, className }) => {
  const [copied, setCopied] = useState(false)
  return (
    <Tooltip label={t('config_api_copy')}>
      <button
        type="button"
        onClick={() => {
          void navigator.clipboard.writeText(text).then(() => {
            setCopied(true)
            setTimeout(() => setCopied(false), 1200)
          })
        }}
        className={className ?? ICON_BTN}
      >
        {copied ? <Check size={13} /> : <Copy size={13} />}
      </button>
    </Tooltip>
  )
}

const ICON_BTN =
  'flex-shrink-0 w-9 flex items-center justify-center rounded-btn border border-strong text-content-tertiary hover:text-content-secondary hover:bg-surface-2 cursor-pointer transition-colors'
const READONLY =
  'w-full px-3 py-2 rounded-btn border border-strong bg-inset text-sm text-content font-mono focus:outline-none'

/** The switch, key and a ready-to-run example for the OpenAI-compatible /v1 API. */
const ChatApiCard: React.FC<{ baseUrl: string }> = ({ baseUrl }) => {
  const [state, setState] = useState<ExternalApiState | null>(null)
  const [revealed, setRevealed] = useState(false)
  const [lang, setLang] = useState<ExampleLang>('curl')

  useEffect(() => {
    apiClient
      .getExternalApi()
      .then((res) => res.status === 'success' && setState(res))
      .catch(() => {})
  }, [baseUrl])

  const post = async (action: 'enable' | 'disable' | 'regenerate') => {
    try {
      const res = await apiClient.updateExternalApi(action)
      if (res.status === 'success') setState(res)
    } catch {
      /* the card keeps showing the last known state */
    }
  }

  const onToggle = async (on: boolean) => {
    const confirmed = on
      ? await askConfirm({ titleKey: 'config_api_enable', msgKey: 'config_api_enable_confirm', okKey: 'config_api_enable_ok', tone: 'primary' })
      : await askConfirm({ titleKey: 'config_api_disable', msgKey: 'config_api_disable_confirm', okKey: 'config_api_disable_ok' })
    if (confirmed) await post(on ? 'enable' : 'disable')
  }

  const regenerate = async () => {
    if (await askConfirm({ titleKey: 'config_api_regenerate', msgKey: 'config_api_regenerate_confirm', okKey: 'config_api_regenerate' }))
      await post('regenerate')
  }

  const enabled = !!state?.enabled
  const key = state?.api_key || ''
  const apiBase = `${baseUrl.replace(/\/$/, '')}/v1`
  const docsUrl = `${getLang() === 'zh' ? 'https://docs.cowagent.ai/zh' : 'https://docs.cowagent.ai'}/extensions/chat-api`

  return (
    <Card
      icon={<Plug size={16} />}
      title={t('config_api')}
      subtitle={t('config_api_desc')}
      action={<Toggle checked={enabled} onChange={(v) => void onToggle(v)} />}
    >
      {enabled ? (
        <div className="space-y-4">
          <div>
            <div className="mb-1.5 text-sm font-medium text-content-secondary">{t('config_api_base_url')}</div>
            <div className="flex gap-2">
              <input readOnly value={apiBase} className={READONLY} />
              <CopyButton text={apiBase} />
            </div>
          </div>
          <div>
            <div className="mb-1.5 flex items-center gap-1.5 text-sm font-medium text-content-secondary">
              API Key
              <FieldTip tip={t('config_api_key_hint')} />
            </div>
            <div className="flex gap-2">
              <div className="relative flex-1 min-w-0">
                <input readOnly value={revealed ? key : maskKey(key)} className={`${READONLY} pr-10`} />
                <button
                  type="button"
                  onClick={() => setRevealed((v) => !v)}
                  className="absolute right-2.5 top-1/2 -translate-y-1/2 text-content-tertiary hover:text-content-secondary cursor-pointer p-1"
                >
                  {revealed ? <EyeOff size={14} /> : <Eye size={14} />}
                </button>
              </div>
              <CopyButton text={key} />
              <Tooltip label={t('config_api_regenerate')}>
                <button type="button" onClick={() => void regenerate()} className={ICON_BTN}>
                  <RotateCw size={13} />
                </button>
              </Tooltip>
            </div>
          </div>
          <div>
            <div className="mb-1.5 flex items-center justify-between">
              <span className="flex items-center gap-1.5 text-sm font-medium text-content-secondary">
                {t('config_api_example')}
                <FieldTip tip={t('config_api_example_hint')} />
              </span>
              <div className="flex items-center rounded-md bg-surface-2 p-0.5">
                {(Object.keys(LANG_LABELS) as ExampleLang[]).map((l) => (
                  <button
                    key={l}
                    type="button"
                    onClick={() => setLang(l)}
                    className={`px-2.5 py-0.5 rounded text-xs cursor-pointer transition-colors ${
                      lang === l ? 'bg-surface text-content shadow-sm' : 'text-content-tertiary hover:text-content-secondary'
                    }`}
                  >
                    {LANG_LABELS[l]}
                  </button>
                ))}
              </div>
            </div>
            <div className="relative">
              <pre className="text-xs leading-relaxed font-mono rounded-btn border border-strong bg-inset text-content p-3 pr-10 overflow-x-auto whitespace-pre">
                {example(lang, apiBase, revealed ? key : maskKey(key))}
              </pre>
              <CopyButton
                text={example(lang, apiBase, key)}
                className="absolute right-2 top-2 p-1 text-content-tertiary hover:text-content-secondary cursor-pointer"
              />
            </div>
            <p className="text-xs mt-1">
              <a href={docsUrl} target="_blank" rel="noopener noreferrer" className="text-accent hover:underline">
                {t('config_api_docs')}
              </a>
            </p>
          </div>
        </div>
      ) : (
        <p className="text-xs text-content-tertiary">
          {t('config_api_off_hint')}{' '}
          <a href={docsUrl} target="_blank" rel="noopener noreferrer" className="text-accent hover:underline">
            {t('config_api_docs')}
          </a>
        </p>
      )}
    </Card>
  )
}

export default ChatApiCard
