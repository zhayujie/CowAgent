import React, { useEffect, useRef, useState } from 'react'
import { ChevronRight, CheckCircle2, XCircle, Loader2, AlertCircle, List, Code2, PlugZap } from 'lucide-react'
import { t } from '../../i18n'
import apiClient from '../../api/client'
import type { McpServerConfig, McpTestResult } from '../../types'
import { Btn, Dropdown, Field, Modal, TextInput, Toggle } from '../settings/primitives'
import { SegTabs } from './SegTabs'
import { MCP_JSON_PLACEHOLDER, kvToObject, mcpServersToJson, mcpTransport, objectToKv, parseMcpJson } from './mcpConfig'

type Tab = 'form' | 'json'
type Probe = McpTestResult & { name: string }
type Result =
  | { kind: 'error'; message: string }
  | { kind: 'testing' }
  | { kind: 'probes'; probes: Probe[]; note?: string }
  | null

interface FormState {
  name: string
  type: string
  command: string
  args: string
  env: string
  url: string
  headers: string
  scope: string
  prefix: string
  timeout: string
  disabled: boolean
}

function toForm(server?: McpServerConfig | null): FormState {
  const s = server || ({ name: '' } as McpServerConfig)
  return {
    name: s.name || '',
    type: mcpTransport(s),
    command: s.command || '',
    args: (s.args || []).join('\n'),
    env: objectToKv(s.env),
    url: s.url || '',
    headers: objectToKv(s.headers),
    scope: s.scope || '',
    prefix: s.tool_name_prefix || '',
    timeout: s.timeout ? String(s.timeout) : '',
    disabled: !!s.disabled || s.status === 'disabled',
  }
}

function fromForm(form: FormState): McpServerConfig {
  const cfg: McpServerConfig = { name: form.name.trim(), type: form.type }
  if (form.prefix) cfg.tool_name_prefix = form.prefix
  if (form.disabled) cfg.disabled = true
  if (form.timeout.trim()) cfg.timeout = Number(form.timeout.trim())
  if (form.type === 'stdio') {
    cfg.command = form.command.trim()
    const args = form.args.split(/\r?\n/).map((line) => line.trim()).filter(Boolean)
    if (args.length) cfg.args = args
    const env = kvToObject(form.env)
    if (Object.keys(env).length) cfg.env = env
  } else {
    cfg.url = form.url.trim()
    const headers = kvToObject(form.headers)
    if (Object.keys(headers).length) cfg.headers = headers
    if (form.scope.trim()) cfg.scope = form.scope.trim()
  }
  return cfg
}

const textareaClass =
  'w-full px-3 py-2 rounded-btn border border-strong bg-inset text-xs font-mono leading-relaxed text-content placeholder:text-content-tertiary placeholder:opacity-60 focus:outline-none focus:border-accent transition-colors resize-y'

interface McpEditorModalProps {
  /** `undefined` while closed, `null` to add, or the server being edited. */
  server: McpServerConfig | null | undefined
  existing: McpServerConfig[]
  onClose: () => void
  /** Persist the full server list; throws with a readable message on failure. */
  onSave: (servers: McpServerConfig[], notice: string) => Promise<void>
}

const McpEditorModal: React.FC<McpEditorModalProps> = ({ server, existing, onClose, onSave }) => {
  const open = server !== undefined
  const originalName = server?.name || null
  const [tab, setTab] = useState<Tab>('form')
  const [form, setForm] = useState<FormState>(toForm(null))
  const [json, setJson] = useState('')
  const [advanced, setAdvanced] = useState(false)
  const [result, setResult] = useState<Result>(null)
  const [saving, setSaving] = useState(false)
  // After a failed check, the next save skips it: the user has seen why and chose to keep the config.
  const [saveAnyway, setSaveAnyway] = useState(false)

  useEffect(() => {
    if (!open) return
    const next = toForm(server)
    setTab('form')
    setForm(next)
    setJson(server ? mcpServersToJson([server]) : '')
    setAdvanced(!!(next.prefix || next.timeout || next.scope))
    setResult(null)
    setSaving(false)
    setSaveAnyway(false)
  }, [open, server])

  const patch = (p: Partial<FormState>) => {
    setForm((prev) => ({ ...prev, ...p }))
    setSaveAnyway(false)
  }
  const editJson = (value: string) => {
    setJson(value)
    setSaveAnyway(false)
  }
  const stdio = form.type === 'stdio'

  const switchTab = (next: Tab) => {
    if (next === tab) return
    if (next === 'json') {
      const cfg = fromForm(form)
      if (cfg.name || cfg.command || cfg.url) setJson(mcpServersToJson([cfg]))
    } else if (json.trim()) {
      let servers: McpServerConfig[]
      try {
        servers = parseMcpJson(json)
      } catch (err) {
        setResult({ kind: 'error', message: (err as Error).message })
        return
      }
      if (servers.length > 1) {
        setResult({ kind: 'error', message: t('mcp_json_multi_to_form') })
        return
      }
      const parsed = toForm(servers[0])
      if (originalName) parsed.name = originalName
      setForm(parsed)
      if (parsed.prefix || parsed.timeout || parsed.scope) setAdvanced(true)
    }
    setResult(null)
    setSaveAnyway(false)
    setTab(next)
  }

  const readServers = (): McpServerConfig[] => {
    if (tab === 'json') {
      const servers = parseMcpJson(json)
      if (originalName && servers.length > 1) throw new Error(t('mcp_json_edit_single'))
      return servers
    }
    const cfg = fromForm(form)
    if (!cfg.name) throw new Error(t('mcp_name_required'))
    return [cfg]
  }

  const runCheck = async (servers: McpServerConfig[]): Promise<Probe[]> => {
    setResult({ kind: 'testing' })
    const probes = await Promise.all(
      servers.map(async (cfg): Promise<Probe> => {
        try {
          return { name: cfg.name, ...(await apiClient.testMcpServer({ ...cfg, disabled: false })) }
        } catch (err) {
          return { name: cfg.name, status: 'error', ok: false, tools: [], error: (err as Error).message }
        }
      })
    )
    setResult({ kind: 'probes', probes })
    return probes
  }

  const test = async () => {
    if (result?.kind === 'testing' || saving) return
    let servers: McpServerConfig[]
    try {
      servers = readServers()
    } catch (err) {
      setResult({ kind: 'error', message: (err as Error).message })
      return
    }
    await runCheck(servers)
  }

  const save = async () => {
    if (saving || result?.kind === 'testing') return
    let servers: McpServerConfig[]
    try {
      servers = readServers()
    } catch (err) {
      setResult({ kind: 'error', message: (err as Error).message })
      return
    }
    const incoming = new Set(servers.map((s) => s.name))
    if (!originalName) {
      const clash = existing.filter((s) => incoming.has(s.name)).map((s) => s.name)
      if (clash.length) {
        setResult({ kind: 'error', message: t('mcp_name_exists').replace('{name}', clash.join(', ')) })
        return
      }
    }
    setSaving(true)
    try {
      let notice = t('mcp_saved')
      const active = servers.filter((s) => !s.disabled)
      if (!saveAnyway && active.length) {
        const probes = await runCheck(active)
        // A server waiting for authorization can only be authorized once saved.
        if (!probes.every((p) => p.ok || p.needs_auth)) {
          setResult({ kind: 'probes', probes, note: t('mcp_check_failed') })
          setSaveAnyway(true)
          return
        }
        const toolCount = probes.reduce((sum, p) => sum + (p.tools || []).length, 0)
        if (toolCount) notice = t('mcp_saved_tools').replace('{n}', String(toolCount))
      }
      const kept = existing.filter((s) => s.name !== originalName && !incoming.has(s.name))
      await onSave(kept.concat(servers), notice)
    } catch (err) {
      setResult({ kind: 'error', message: (err as Error).message || t('mcp_save_error') })
    } finally {
      setSaving(false)
    }
  }

  const testing = result?.kind === 'testing'

  return (
    <Modal
      open={open}
      size="lg"
      title={originalName ? t('mcp_edit') : t('mcp_add_title')}
      onClose={onClose}
      headerRight={
        <SegTabs<Tab>
          value={tab}
          onChange={switchTab}
          tabs={[
            { value: 'form', label: t('mcp_tab_form'), icon: List },
            { value: 'json', label: 'JSON', icon: Code2 },
          ]}
        />
      }
      footer={
        <>
          <button
            type="button"
            onClick={() => void test()}
            disabled={testing || saving}
            className="inline-flex items-center gap-1.5 px-3 py-2 rounded-btn text-sm font-medium text-accent hover:bg-accent-soft cursor-pointer transition-colors disabled:opacity-50 disabled:cursor-wait"
          >
            {testing && !saving ? <Loader2 size={14} className="animate-spin" /> : <PlugZap size={14} />}
            {t('mcp_test')}
          </button>
          <div className="flex-1" />
          <Btn onClick={onClose}>{t('mcp_cancel')}</Btn>
          <Btn variant="primary" onClick={() => void save()} disabled={saving || testing}>
            {saveAnyway ? t('mcp_save_anyway') : t('mcp_save')}
          </Btn>
        </>
      }
    >
      {tab === 'form' ? (
        <>
          <div className="grid grid-cols-2 gap-4">
            <Field label={t('mcp_field_name')}>
              <TextInput
                value={form.name}
                disabled={!!originalName}
                placeholder={t('mcp_field_name_ph')}
                autoFocus={!originalName}
                spellCheck={false}
                onChange={(e) => patch({ name: e.target.value })}
                className="disabled:opacity-60 disabled:cursor-not-allowed"
              />
            </Field>
            <Field label={t('mcp_field_type')}>
              <Dropdown
                value={form.type}
                hintAlign="inline"
                onChange={(type) => patch({ type })}
                options={[
                  { value: 'stdio', label: 'stdio', hint: t('mcp_transport_stdio_hint') },
                  { value: 'sse', label: 'SSE', hint: t('mcp_transport_remote_hint') },
                  { value: 'streamable-http', label: 'Streamable HTTP', hint: t('mcp_transport_remote_hint') },
                ]}
              />
            </Field>
          </div>
          {stdio ? (
            <>
              <Field label={t('mcp_field_command')}>
                <TextInput
                  value={form.command}
                  placeholder="npx / uvx / python"
                  spellCheck={false}
                  className="font-mono"
                  onChange={(e) => patch({ command: e.target.value })}
                />
              </Field>
              <Field label={t('mcp_field_args')}>
                <textarea
                  rows={3}
                  value={form.args}
                  spellCheck={false}
                  placeholder={'-y\n@modelcontextprotocol/server-github'}
                  onChange={(e) => patch({ args: e.target.value })}
                  className={textareaClass}
                />
              </Field>
              <Field label={t('mcp_field_env')}>
                <textarea
                  rows={2}
                  value={form.env}
                  spellCheck={false}
                  placeholder="API_KEY=your-key"
                  onChange={(e) => patch({ env: e.target.value })}
                  className={textareaClass}
                />
              </Field>
            </>
          ) : (
            <>
              <Field label={t('mcp_field_url')}>
                <TextInput
                  value={form.url}
                  placeholder="https://mcp.example.com/mcp"
                  spellCheck={false}
                  className="font-mono"
                  onChange={(e) => patch({ url: e.target.value })}
                />
              </Field>
              <Field label={t('mcp_field_headers')}>
                <textarea
                  rows={2}
                  value={form.headers}
                  spellCheck={false}
                  placeholder="Authorization=Bearer YOUR_API_KEY"
                  onChange={(e) => patch({ headers: e.target.value })}
                  className={textareaClass}
                />
              </Field>
            </>
          )}
          <div className="flex items-center justify-between gap-3">
            <button
              type="button"
              onClick={() => setAdvanced((v) => !v)}
              className="inline-flex items-center gap-1 text-xs text-content-tertiary hover:text-content-secondary cursor-pointer transition-colors"
            >
              <ChevronRight size={12} className={`transition-transform ${advanced ? 'rotate-90' : ''}`} />
              {t('mcp_advanced')}
            </button>
            <label className="inline-flex items-center gap-2 text-xs text-content-tertiary">
              {t('mcp_field_disabled')}
              <Toggle checked={form.disabled} onChange={(disabled) => patch({ disabled })} />
            </label>
          </div>
          {advanced && (
            <div className="grid grid-cols-2 gap-4">
              <Field label={t('mcp_field_prefix')}>
                <TextInput
                  value={form.prefix}
                  placeholder="myserver_"
                  spellCheck={false}
                  className="font-mono"
                  onChange={(e) => patch({ prefix: e.target.value })}
                />
              </Field>
              <Field label={t('mcp_field_timeout')}>
                <TextInput
                  type="number"
                  min={1}
                  value={form.timeout}
                  placeholder="30"
                  onChange={(e) => patch({ timeout: e.target.value })}
                />
              </Field>
              {!stdio && (
                <div className="col-span-2">
                  <Field label={t('mcp_field_scope')}>
                    <TextInput
                      value={form.scope}
                      spellCheck={false}
                      className="font-mono"
                      onChange={(e) => patch({ scope: e.target.value })}
                    />
                  </Field>
                </div>
              )}
            </div>
          )}
        </>
      ) : (
        <div>
          <p className="text-xs text-content-tertiary mb-2">{t('mcp_json_hint')}</p>
          <textarea
            rows={14}
            autoFocus
            value={json}
            spellCheck={false}
            placeholder={MCP_JSON_PLACEHOLDER}
            onChange={(e) => editJson(e.target.value)}
            className={textareaClass}
          />
        </div>
      )}
      {result && <ResultBox result={result} />}
    </Modal>
  )
}

const ToolChips: React.FC<{ tools: McpTestResult['tools'] }> = ({ tools }) => {
  const named = tools.filter((tool) => tool && tool.name)
  if (!named.length) return <p className="mt-2 text-xs opacity-80">{t('mcp_test_no_tools')}</p>
  return (
    <>
      <p className="mt-2.5 mb-1.5 text-xs font-medium opacity-80">
        {t('mcp_test_tools')} ({named.length})
      </p>
      <div className="flex flex-wrap gap-1.5 max-h-40 overflow-y-auto">
        {named.map((tool) => (
          <span
            key={tool.name}
            title={tool.description || tool.name}
            className="max-w-full truncate px-2 py-0.5 rounded-[6px] border border-default bg-surface text-[11px] font-mono text-content-secondary"
          >
            {tool.name}
          </span>
        ))}
      </div>
    </>
  )
}

const ProbeView: React.FC<{ probe: Probe; withName: boolean; mixed: boolean }> = ({ probe, withName, mixed }) => {
  const name = withName && (
    <>
      <span className="font-mono">{probe.name}</span>
      <span className="opacity-50">·</span>
    </>
  )
  if (probe.ok) {
    return (
      <div>
        <div className="flex items-center gap-2 font-medium">
          <CheckCircle2 size={15} className={mixed ? 'text-emerald-500' : ''} />
          {name}
          <span>{t('mcp_test_ok')}</span>
        </div>
        <ToolChips tools={probe.tools || []} />
      </div>
    )
  }
  const detail = probe.needs_auth ? t('mcp_test_needs_auth') : probe.error || probe.message || ''
  return (
    <div>
      <div className="flex items-center gap-2 font-medium">
        <XCircle size={15} className={mixed ? 'text-red-500' : ''} />
        {name}
        <span>{t('mcp_test_fail')}</span>
      </div>
      {detail && <p className="mt-1.5 text-xs break-words opacity-90">{detail}</p>}
    </div>
  )
}

const ResultBox: React.FC<{ result: NonNullable<Result> }> = ({ result }) => {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    ref.current?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
  }, [result])
  const tones = {
    ok: 'bg-emerald-500/10 border-emerald-500/25 text-emerald-700 dark:text-emerald-300',
    fail: 'bg-red-500/10 border-red-500/25 text-red-700 dark:text-red-300',
    info: 'bg-inset border-default text-content-secondary',
  }
  const box = (tone: keyof typeof tones, children: React.ReactNode, note?: string) => (
    <div ref={ref} className={`rounded-card border px-3.5 py-3 text-[13px] ${tones[tone]}`}>
      {children}
      {note && (
        <p className="mt-2.5 pt-2.5 border-t border-black/5 dark:border-white/10 text-xs font-medium">{note}</p>
      )}
    </div>
  )
  if (result.kind === 'testing') {
    return box(
      'info',
      <div className="flex items-center gap-2">
        <Loader2 size={14} className="animate-spin" />
        {t('mcp_testing')}
      </div>
    )
  }
  if (result.kind === 'error') {
    return box(
      'fail',
      <div className="flex items-start gap-2">
        <AlertCircle size={15} className="flex-shrink-0 mt-px" />
        <span className="flex-1 min-w-0 break-words">{result.message}</span>
      </div>
    )
  }
  const okCount = result.probes.filter((p) => p.ok).length
  const mixed = okCount > 0 && okCount < result.probes.length
  const multi = result.probes.length > 1
  return box(
    mixed ? 'info' : okCount ? 'ok' : 'fail',
    <div className={multi ? 'divide-y divide-black/5 dark:divide-white/10 [&>*]:py-2 [&>*:first-child]:pt-0 [&>*:last-child]:pb-0' : ''}>
      {result.probes.map((probe) => (
        <ProbeView key={probe.name} probe={probe} withName={multi} mixed={mixed} />
      ))}
    </div>,
    result.note
  )
}

export default McpEditorModal
