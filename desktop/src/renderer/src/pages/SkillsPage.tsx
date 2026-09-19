import React, { useEffect, useRef, useState } from 'react'
import { Loader2, Wrench, Zap, Puzzle, ArrowLeft, Lock, Pencil, Plus, Plug, Trash2 } from 'lucide-react'
import { t } from '../i18n'
import apiClient from '../api/client'
import type { ApiResult } from '../api/client'
import type { ToolInfo, SkillInfo, SkillContent, McpServerConfig } from '../types'
import { Toggle } from './settings/primitives'
import Markdown from '../components/Markdown'
import { DocActions, DocEditor, DocNotice } from '../components/DocEditor'
import { createDocEditorStore, docRefusal } from '../store/docEditorStore'

interface SkillsPageProps {
  baseUrl: string
}

const SKILL_HUB_URL = 'https://skills.cowagent.ai/'

/**
 * Skills are addressed by name, not by path: which file a name resolves to is
 * the loader's business, and a builtin skill's file sits outside the workspace.
 */
interface SkillRef {
  name: string
  label: string
}

/** Created at module scope so an unsaved edit survives a route change. */
const skillEditor = createDocEditorStore<SkillRef, SkillContent & ApiResult>({
  keyOf: (doc) => doc.name,
  read: (doc) => apiClient.readSkill(doc.name),
  write: (doc, content, expectedMtime) =>
    apiClient.writeSkill({ name: doc.name, content, expectedMtime }),
  refusal: (data) => (data.ships_with_install ? t('skill_builtin_readonly') : docRefusal(data)),
})

/**
 * Split a skill's SKILL.md into its YAML frontmatter fields and the markdown
 * body. The `---` header is metadata, not prose: handed to the markdown
 * renderer as-is it becomes a giant bold heading and a horizontal rule. Pull it
 * out so name/description show as a proper header instead.
 */
function parseSkillFrontmatter(content: string): { fields: Array<[string, string]>; body: string } {
  const text = content || ''
  const match = text.match(/^---\s*\r?\n([\s\S]*?)\r?\n---\s*\r?\n?/)
  if (!match) return { fields: [], body: text }

  const fields: Array<[string, string]> = []
  for (const raw of match[1].split(/\r?\n/)) {
    const line = raw.trim()
    if (!line || line.startsWith('#')) continue
    const idx = line.indexOf(':')
    if (idx === -1) continue
    const key = line.slice(0, idx).trim()
    // Drop surrounding quotes a YAML scalar may carry.
    const value = line
      .slice(idx + 1)
      .trim()
      .replace(/^['"]|['"]$/g, '')
    if (key) fields.push([key, value])
  }
  return { fields, body: text.slice(match[0].length) }
}

/** A skill's read-only view: frontmatter as a titled header, body as markdown. */
const SkillContentView: React.FC<{ content: string }> = ({ content }) => {
  const { fields, body } = parseSkillFrontmatter(content)
  return (
    <>
      {fields.length > 0 && (
        <div className="mb-5 pb-5 border-b border-subtle space-y-2">
          {fields.map(([key, value]) => (
            <div key={key} className="flex gap-3 text-sm">
              <span className="flex-shrink-0 w-24 font-medium text-content-tertiary">{key}</span>
              <span className="flex-1 min-w-0 text-content break-words">{value}</span>
            </div>
          ))}
        </div>
      )}
      <Markdown content={body} />
    </>
  )
}
const emptyMcpForm = (): McpServerConfig => ({
  name: '',
  type: 'stdio',
  command: '',
  args: [],
  env: {},
  url: '',
  headers: {},
  scope: '',
  tool_name_prefix: '',
  disabled: false,
})

function kvToObject(text: string): Record<string, string> {
  const out: Record<string, string> = {}
  for (const line of (text || '').split(/\r?\n/)) {
    const trimmed = line.trim()
    if (!trimmed) continue
    const idx = trimmed.indexOf('=')
    if (idx <= 0) continue
    out[trimmed.slice(0, idx).trim()] = trimmed.slice(idx + 1)
  }
  return out
}

function objectToKv(obj?: Record<string, string>): string {
  if (!obj) return ''
  return Object.entries(obj)
    .map(([key, value]) => `${key}=${value}`)
    .join('\n')
}

function mcpStatusLabel(status?: string): string {
  const key: Record<string, string> = {
    ready: 'mcp_status_ready',
    pending: 'mcp_status_pending',
    failed: 'mcp_status_failed',
    needs_auth: 'mcp_status_needs_auth',
    disabled: 'mcp_status_disabled',
    idle: 'mcp_status_idle',
  }
  return t(key[status || ''] || 'mcp_status_idle')
}

const SkillsPage: React.FC<SkillsPageProps> = ({ baseUrl }) => {
  const [tools, setTools] = useState<ToolInfo[]>([])
  const [skills, setSkills] = useState<SkillInfo[]>([])
  const [servers, setServers] = useState<McpServerConfig[]>([])
  const [loading, setLoading] = useState(true)
  const [installSpec, setInstallSpec] = useState('')
  const [installing, setInstalling] = useState(false)
  const [editor, setEditor] = useState<McpServerConfig | null>(null)
  const [editorOriginalName, setEditorOriginalName] = useState<string | null>(null)
  const [argsText, setArgsText] = useState('')
  const [envText, setEnvText] = useState('')
  const [headersText, setHeadersText] = useState('')
  const [testResult, setTestResult] = useState('')
  const [saving, setSaving] = useState(false)

  const doc = skillEditor((s) => s.doc)
  const content = skillEditor((s) => s.content)
  const docLoading = skillEditor((s) => s.loading)
  const readonly = skillEditor((s) => s.readonly)
  const edit = skillEditor((s) => s.edit)
  const editorRef = useRef<HTMLTextAreaElement>(null)

  const loadData = async () => {
    try {
      setLoading(true)
      const [toolsData, skillsData, mcpData] = await Promise.all([
        apiClient.getTools(),
        apiClient.getSkills(),
        apiClient.getMcpServers(),
      ])
      setTools(toolsData || [])
      setSkills(skillsData || [])
      setServers(mcpData.servers || [])
    } catch (err) {
      console.error('Failed to load skills:', err)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    apiClient.setBaseUrl(baseUrl)
    void loadData()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [baseUrl])

  const toggle = async (skill: SkillInfo, enabled: boolean) => {
    setSkills((prev) => prev.map((s) => (s.name === skill.name ? { ...s, enabled } : s)))
    try {
      const res = await apiClient.toggleSkill(skill.name, enabled ? 'open' : 'close')
      if (res.status !== 'success') throw new Error()
    } catch {
      setSkills((prev) => prev.map((s) => (s.name === skill.name ? { ...s, enabled: !enabled } : s)))
    }
  }

  const openSkillForEdit = async (skill: SkillInfo) => {
    await skillEditor
      .getState()
      .open({ name: skill.name, label: skill.display_name || skill.name })
    await skillEditor.getState().startEdit()
  }

  const closeViewer = async () => {
    if (!(await skillEditor.getState().close())) return
    void loadData()
  }

  const persistServers = async (next: McpServerConfig[]) => {
    const res = await apiClient.saveMcpServers(next)
    if (res.status !== 'success') throw new Error(res.message || t('mcp_save_error'))
    setServers(res.servers || next)
  }

  const openEditor = (server?: McpServerConfig) => {
    const form = server ? { ...emptyMcpForm(), ...server } : emptyMcpForm()
    setEditor(form)
    setEditorOriginalName(server?.name || null)
    setArgsText((server?.args || []).join('\n'))
    setEnvText(objectToKv(server?.env))
    setHeadersText(objectToKv(server?.headers))
    setTestResult('')
  }

  const readEditor = (): McpServerConfig => {
    if (!editor) return emptyMcpForm()
    const type = editor.type || 'stdio'
    const cfg: McpServerConfig = {
      ...editor,
      name: (editor.name || '').trim(),
      type,
      tool_name_prefix: editor.tool_name_prefix || '',
      disabled: !!editor.disabled,
    }
    if (type === 'stdio') {
      cfg.command = (editor.command || '').trim()
      cfg.args = argsText.split(/\r?\n/).map((line) => line.trim()).filter(Boolean)
      cfg.env = kvToObject(envText)
      delete cfg.url
      delete cfg.headers
      delete cfg.scope
    } else {
      cfg.url = (editor.url || '').trim()
      cfg.headers = kvToObject(headersText)
      cfg.scope = editor.scope || ''
      delete cfg.command
      delete cfg.args
      delete cfg.env
    }
    return cfg
  }

  const saveEditor = async () => {
    if (!editor) return
    setSaving(true)
    try {
      const cfg = readEditor()
      const next = servers.filter((item) => item.name !== editorOriginalName && item.name !== cfg.name)
      next.push(cfg)
      await persistServers(next)
      setEditor(null)
    } catch (err) {
      setTestResult(err instanceof Error ? err.message : t('mcp_save_error'))
    } finally {
      setSaving(false)
    }
  }

  const testEditor = async () => {
    setTestResult(t('mcp_test') + '...')
    try {
      const data = await apiClient.testMcpServer(readEditor())
      if (data.ok) {
        const names = (data.tools || []).map((tool) => tool.name).filter(Boolean)
        setTestResult(t('mcp_test_ok') + (names.length ? `: ${names.join(', ')}` : ''))
      } else {
        setTestResult(`${t('mcp_test_fail')}: ${data.error || data.message || ''}`)
      }
    } catch (err) {
      setTestResult(`${t('mcp_test_fail')}: ${err instanceof Error ? err.message : ''}`)
    }
  }

  const removeServer = async (name: string) => {
    if (!window.confirm(t('mcp_delete_confirm'))) return
    try {
      await persistServers(servers.filter((item) => item.name !== name))
    } catch (err) {
      window.alert(err instanceof Error ? err.message : t('mcp_save_error'))
    }
  }

  const install = async () => {
    const spec = installSpec.trim()
    if (!spec) return
    setInstalling(true)
    try {
      const res = await apiClient.installSkill(spec)
      if (res.status !== 'success') throw new Error(res.message || t('skill_install_error'))
      setInstallSpec('')
      await loadData()
    } catch (err) {
      window.alert(err instanceof Error ? err.message : t('skill_install_error'))
    } finally {
      setInstalling(false)
    }
  }

  const uninstall = async (name: string) => {
    if (!window.confirm(t('skill_delete_confirm'))) return
    try {
      const res = await apiClient.deleteSkill(name)
      if (res.status !== 'success') throw new Error(res.message || t('skill_delete_error'))
      await loadData()
    } catch (err) {
      window.alert(err instanceof Error ? err.message : t('skill_delete_error'))
    }
  }

  return (
    <div className="flex-1 flex flex-col min-h-0">
      <div className="flex items-center justify-between px-6 pt-5 pb-3 flex-shrink-0">
        <div>
          <h2 className="text-xl font-bold text-content">{t('skills_title')}</h2>
          <p className="text-xs text-content-tertiary mt-1">{t('skills_desc')}</p>
        </div>
        {!doc && (
          <a
            href={SKILL_HUB_URL}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-btn text-xs font-medium text-accent bg-accent-soft hover:bg-accent-soft transition-colors"
          >
            <Puzzle size={12} />
            {t('skills_hub_btn')}
          </a>
        )}
      </div>

      <DocNotice store={skillEditor} />

      {doc ? (
        <div className="flex-1 flex flex-col min-h-0 border-t border-default">
          <div className="flex items-center gap-3 px-6 py-3 flex-shrink-0 border-b border-subtle">
            <button
              onClick={() => void closeViewer()}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-btn text-sm text-content-secondary hover:bg-inset border border-strong transition-colors cursor-pointer"
            >
              <ArrowLeft size={14} />
              {t('skill_back')}
            </button>
            <h3 className="flex-1 text-sm font-semibold text-content truncate">
              {doc.label}
              {edit?.dirty && (
                <span className="text-accent" title={t('ws_edit_unsaved')}>
                  {' '}
                  {'\u2022'}
                </span>
              )}
            </h3>
            {readonly && !docLoading && (
              <span
                title={readonly}
                className="inline-flex items-center gap-1.5 max-w-[45%] px-2 py-1 rounded-btn text-xs text-content-tertiary bg-inset"
              >
                <Lock size={11} className="flex-shrink-0" />
                <span className="truncate">{readonly}</span>
              </span>
            )}
            <DocActions store={skillEditor} textareaRef={editorRef} />
          </div>
          {edit ? (
            <div className="flex-1 min-h-0 overflow-hidden">
              <DocEditor key={doc.name} store={skillEditor} textareaRef={editorRef} />
            </div>
          ) : (
            <div className="flex-1 overflow-y-auto">
              <div className="max-w-3xl mx-auto px-6 py-6">
                {docLoading ? (
                  <div className="flex items-center text-content-tertiary py-8">
                    <Loader2 size={16} className="animate-spin mr-2" />
                  </div>
                ) : (
                  <SkillContentView content={content} />
                )}
              </div>
            </div>
          )}
        </div>
      ) : (
      <div className="flex-1 overflow-y-auto border-t border-default">
        <div className="max-w-4xl mx-auto px-6 py-5">
          {loading ? (
            <div className="flex items-center justify-center py-20 text-content-tertiary">
              <Loader2 size={18} className="animate-spin mr-2" />
              {t('skills_loading')}
            </div>
          ) : (
            <div className="space-y-8">
              <Section title={t('tools_section_title')} count={tools.length}>
                {tools.length === 0 ? (
                  <Empty text={t('tools_empty')} />
                ) : (
                  <div className="grid gap-3 sm:grid-cols-2">
                    {tools.map((tool) => (
                      <div key={tool.name} className="rounded-card border border-default bg-surface p-4">
                        <div className="flex items-center gap-2 mb-1.5">
                          <Wrench size={13} className="text-content-tertiary flex-shrink-0" />
                          <span className="text-sm font-medium text-content font-mono truncate">{tool.name}</span>
                        </div>
                        <p className="text-xs text-content-tertiary leading-relaxed line-clamp-2">{tool.description || '--'}</p>
                      </div>
                    ))}
                  </div>
                )}
              </Section>

              <Section
                title={t('mcp_section_title')}
                count={servers.length}
                action={
                  <button
                    type="button"
                    onClick={() => openEditor()}
                    className="ml-auto inline-flex items-center gap-1 px-2 py-1 rounded-btn text-xs font-medium text-accent bg-accent-soft"
                  >
                    <Plus size={12} />
                    {t('mcp_add')}
                  </button>
                }
              >
                <p className="text-xs text-content-tertiary mb-3">{t('mcp_section_hint')}</p>
                {servers.length === 0 ? (
                  <Empty text={t('mcp_empty')} />
                ) : (
                  <div className="grid gap-3 sm:grid-cols-2">
                    {servers.map((server) => (
                      <div key={server.name} className="rounded-card border border-default bg-surface p-4 flex items-start gap-3">
                        <div className="w-9 h-9 rounded-lg bg-inset-2 flex items-center justify-center flex-shrink-0">
                          <Plug size={15} className="text-accent" />
                        </div>
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2 mb-1">
                            <span className="text-sm font-medium text-content font-mono truncate flex-1">{server.name}</span>
                            <span className="px-1.5 py-0.5 rounded-full text-[10px] bg-inset-2 text-content-tertiary">
                              {mcpStatusLabel(server.status)}
                            </span>
                            <button type="button" title={t('mcp_edit')} onClick={() => openEditor(server)} className="p-1 text-content-tertiary hover:text-content">
                              <Pencil size={11} />
                            </button>
                            <button type="button" title={t('mcp_delete')} onClick={() => void removeServer(server.name)} className="p-1 text-content-tertiary hover:text-red-500">
                              <Trash2 size={11} />
                            </button>
                          </div>
                          <p className="text-xs text-content-tertiary truncate">
                            {server.type === 'stdio'
                              ? [server.command, ...(server.args || [])].filter(Boolean).join(' ')
                              : server.url || server.type}
                          </p>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </Section>

              <Section title={t('skills_section_title')} count={skills.length}>
                <div id="skill-install" className="flex items-center gap-2 mb-3">
                  <input
                    value={installSpec}
                    onChange={(e) => setInstallSpec(e.target.value)}
                    onKeyDown={(e) => e.key === 'Enter' && void install()}
                    placeholder={t('skill_install_placeholder')}
                    className="flex-1 min-w-0 px-3 py-1.5 rounded-btn border border-strong bg-inset text-sm text-content placeholder:text-content-tertiary focus:outline-none focus:border-accent"
                  />
                  <button
                    type="button"
                    onClick={() => void install()}
                    disabled={installing}
                    className="inline-flex items-center gap-1 px-3 py-1.5 rounded-btn text-xs font-medium text-white bg-accent disabled:opacity-50"
                  >
                    {installing && <Loader2 size={12} className="animate-spin" />}
                    {t('skill_install_btn')}
                  </button>
                </div>
                {skills.length === 0 ? (
                  <Empty text={t('skills_empty')} />
                ) : (
                  <div className="grid gap-3 sm:grid-cols-2">
                    {skills.map((skill) => (
                      <div
                        key={skill.name}
                        onClick={() =>
                          void skillEditor
                            .getState()
                            .open({ name: skill.name, label: skill.display_name || skill.name })
                        }
                        title={t('skill_open_hint')}
                        className="rounded-card border border-default bg-surface p-4 flex items-start gap-3 cursor-pointer hover:border-strong transition-colors"
                      >
                        <div className="w-9 h-9 rounded-lg bg-inset-2 flex items-center justify-center flex-shrink-0">
                          <Zap size={15} className={skill.enabled ? 'text-accent' : 'text-content-tertiary'} />
                        </div>
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2 mb-1">
                            <span className="text-sm font-medium text-content truncate flex-1">
                              {skill.display_name || skill.name}
                            </span>
                            <button
                              type="button"
                              title={t('skill_edit_hint')}
                              onClick={(e) => {
                                e.stopPropagation()
                                void openSkillForEdit(skill)
                              }}
                              className="flex-shrink-0 p-1 -mx-1 -mt-1.5 -mb-1 rounded text-content-tertiary hover:text-content-secondary transition-colors cursor-pointer"
                            >
                              <Pencil size={11} />
                            </button>
                            {skill.deletable && (
                              <button
                                type="button"
                                title={t('skill_delete')}
                                onClick={(e) => {
                                  e.stopPropagation()
                                  void uninstall(skill.name)
                                }}
                                className="flex-shrink-0 p-1 -mx-1 -mt-1.5 -mb-1 rounded text-content-tertiary hover:text-red-500 transition-colors cursor-pointer"
                              >
                                <Trash2 size={11} />
                              </button>
                            )}
                            <span onClick={(e) => e.stopPropagation()}>
                              <Toggle checked={skill.enabled} onChange={(v) => toggle(skill, v)} />
                            </span>
                          </div>
                          <p className="text-xs text-content-tertiary leading-relaxed line-clamp-2">{skill.description || '--'}</p>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </Section>
            </div>
          )}
        </div>
      </div>
      )}

      {editor && (
        <div className="fixed inset-0 z-[70] flex items-center justify-center bg-black/40 p-4" onMouseDown={() => setEditor(null)}>
          <div
            className="w-full max-w-lg bg-surface border border-default rounded-xl shadow-xl p-5 max-h-[85vh] overflow-y-auto"
            onMouseDown={(e) => e.stopPropagation()}
          >
            <h3 className="text-base font-semibold text-content mb-4">{editorOriginalName ? t('mcp_edit') : t('mcp_add')}</h3>
            <div className="space-y-3 text-sm">
              <label className="block">
                <span className="text-xs text-content-tertiary">{t('mcp_field_name')}</span>
                <input
                  value={editor.name}
                  disabled={!!editorOriginalName}
                  onChange={(e) => setEditor({ ...editor, name: e.target.value })}
                  className="mt-1 w-full px-3 py-2 rounded-btn border border-strong bg-inset text-sm text-content"
                />
              </label>
              <label className="block">
                <span className="text-xs text-content-tertiary">{t('mcp_field_type')}</span>
                <select
                  value={editor.type || 'stdio'}
                  onChange={(e) => setEditor({ ...editor, type: e.target.value })}
                  className="mt-1 w-full px-3 py-2 rounded-btn border border-strong bg-inset text-sm text-content"
                >
                  <option value="stdio">stdio</option>
                  <option value="sse">SSE</option>
                  <option value="streamable-http">streamable-http</option>
                </select>
              </label>
              {(editor.type || 'stdio') === 'stdio' ? (
                <>
                  <label className="block">
                    <span className="text-xs text-content-tertiary">{t('mcp_field_command')}</span>
                    <input
                      value={editor.command || ''}
                      onChange={(e) => setEditor({ ...editor, command: e.target.value })}
                      className="mt-1 w-full px-3 py-2 rounded-btn border border-strong bg-inset text-sm text-content"
                    />
                  </label>
                  <label className="block">
                    <span className="text-xs text-content-tertiary">{t('mcp_field_args')}</span>
                    <textarea
                      value={argsText}
                      onChange={(e) => setArgsText(e.target.value)}
                      rows={3}
                      className="mt-1 w-full px-3 py-2 rounded-btn border border-strong bg-inset text-xs font-mono text-content"
                    />
                  </label>
                  <label className="block">
                    <span className="text-xs text-content-tertiary">{t('mcp_field_env')}</span>
                    <textarea
                      value={envText}
                      onChange={(e) => setEnvText(e.target.value)}
                      rows={3}
                      className="mt-1 w-full px-3 py-2 rounded-btn border border-strong bg-inset text-xs font-mono text-content"
                    />
                  </label>
                </>
              ) : (
                <>
                  <label className="block">
                    <span className="text-xs text-content-tertiary">{t('mcp_field_url')}</span>
                    <input
                      value={editor.url || ''}
                      onChange={(e) => setEditor({ ...editor, url: e.target.value })}
                      className="mt-1 w-full px-3 py-2 rounded-btn border border-strong bg-inset text-sm text-content"
                    />
                  </label>
                  <label className="block">
                    <span className="text-xs text-content-tertiary">{t('mcp_field_headers')}</span>
                    <textarea
                      value={headersText}
                      onChange={(e) => setHeadersText(e.target.value)}
                      rows={3}
                      className="mt-1 w-full px-3 py-2 rounded-btn border border-strong bg-inset text-xs font-mono text-content"
                    />
                  </label>
                  <label className="block">
                    <span className="text-xs text-content-tertiary">{t('mcp_field_scope')}</span>
                    <input
                      value={editor.scope || ''}
                      onChange={(e) => setEditor({ ...editor, scope: e.target.value })}
                      className="mt-1 w-full px-3 py-2 rounded-btn border border-strong bg-inset text-sm text-content"
                    />
                  </label>
                </>
              )}
              <label className="block">
                <span className="text-xs text-content-tertiary">{t('mcp_field_prefix')}</span>
                <input
                  value={editor.tool_name_prefix || ''}
                  onChange={(e) => setEditor({ ...editor, tool_name_prefix: e.target.value })}
                  className="mt-1 w-full px-3 py-2 rounded-btn border border-strong bg-inset text-sm text-content"
                />
              </label>
              <label className="block">
                <span className="text-xs text-content-tertiary">{t('mcp_field_timeout')}</span>
                <input
                  type="number"
                  min={1}
                  value={editor.timeout || ''}
                  onChange={(e) => setEditor({ ...editor, timeout: e.target.value ? Number(e.target.value) : undefined })}
                  className="mt-1 w-full px-3 py-2 rounded-btn border border-strong bg-inset text-sm text-content"
                />
              </label>
              <label className="flex items-center gap-2 text-xs text-content-tertiary">
                <input
                  type="checkbox"
                  checked={!!editor.disabled}
                  onChange={(e) => setEditor({ ...editor, disabled: e.target.checked })}
                />
                {t('mcp_field_disabled')}
              </label>
              {testResult && <p className="text-xs text-content-secondary bg-inset rounded-btn px-3 py-2">{testResult}</p>}
            </div>
            <div className="flex items-center justify-end gap-2 mt-5">
              <button type="button" onClick={() => setEditor(null)} className="px-3 py-1.5 rounded-btn text-sm text-content-secondary">
                {t('mcp_cancel')}
              </button>
              <button type="button" onClick={() => void testEditor()} className="px-3 py-1.5 rounded-btn text-sm text-accent bg-accent-soft">
                {t('mcp_test')}
              </button>
              <button type="button" onClick={() => void saveEditor()} disabled={saving} className="px-3 py-1.5 rounded-btn text-sm text-white bg-accent disabled:opacity-50">
                {t('mcp_save')}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

const Section: React.FC<{ title: string; count: number; action?: React.ReactNode; children: React.ReactNode }> = ({
  title,
  count,
  action,
  children,
}) => (
  <div>
    <div className="flex items-center gap-2 mb-3">
      <span className="text-xs font-semibold uppercase tracking-wider text-content-tertiary">{title}</span>
      {count > 0 && (
        <span className="px-1.5 py-0.5 rounded-full text-xs bg-inset-2 text-content-tertiary min-w-[20px] text-center">{count}</span>
      )}
      {action}
    </div>
    {children}
  </div>
)

const Empty: React.FC<{ text: string }> = ({ text }) => (
  <p className="text-sm text-content-tertiary py-2">{text}</p>
)

export default SkillsPage
