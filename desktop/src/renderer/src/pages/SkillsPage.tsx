import React, { useEffect, useRef, useState } from 'react'
import {
  Loader2,
  Zap,
  ArrowLeft,
  Lock,
  Pencil,
  Plus,
  Plug,
  Trash2,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Compass,
  ExternalLink,
  Terminal,
  FileQuestion,
  FileText,
  FilePen,
  SquarePen,
  Folder,
  FolderOpen,
  Send,
  Search,
  Globe,
  KeyRound,
  Clock,
  Brain,
  Wrench,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { t } from '../i18n'
import apiClient from '../api/client'
import type { ApiResult } from '../api/client'
import type { ToolInfo, SkillInfo, SkillContent, SkillFileEntry, McpServerConfig } from '../types'
import { Toggle } from './settings/primitives'
import Markdown from '../components/Markdown'
import { DocActions, DocEditor, DocNotice, DocView } from '../components/DocEditor'
import { createDocEditorStore, docRefusal } from '../store/docEditorStore'
import { askConfirm } from '../store/confirmStore'
import McpEditorModal from './skills/McpEditorModal'
import SkillAddModal from './skills/SkillAddModal'
import { formatSkillFileSize } from './skills/SkillCreateForm'
import { parseSkillFrontmatter } from './skills/frontmatter'
import { MCP_TRANSPORT_LABELS, mcpTransport } from './skills/mcpConfig'
import { product } from '@product'

interface SkillsPageProps {
  baseUrl: string
}

const SKILL_HUB_URL = 'https://skills.cowagent.ai/'
const TOOLS_COLLAPSED_COUNT = 4
const MCP_POLL_INTERVAL_MS = 1500
const MCP_POLL_MAX_MS = 120000

const TOOL_ICONS: Record<string, LucideIcon> = {
  bash: Terminal,
  edit: SquarePen,
  read: FileText,
  write: FilePen,
  ls: FolderOpen,
  send: Send,
  web_search: Search,
  browser: Globe,
  env_config: KeyRound,
  scheduler: Clock,
  memory_get: Brain,
  memory_search: Brain,
}

/** Where the file list's own show/hide state is kept, as in the web console. */
const SKILL_FILES_PANEL_KEY = 'cow_skill_files_panel'

/**
 * A skill is addressed by name, not by path: which directory a name resolves to
 * is the loader's business, and a builtin skill sits outside the workspace.
 * `path` then names one file inside it - a skill is a directory, and the files
 * beside its SKILL.md are as much part of it.
 */
interface SkillRef {
  name: string
  label: string
  /** File within the skill directory; its SKILL.md when empty. */
  path?: string
}

/** Created at module scope so an unsaved edit survives a route change. */
const skillEditor = createDocEditorStore<SkillRef, SkillContent & ApiResult>({
  // The file, not just the skill: switching between two files of one skill has
  // to read as a different document, or a late response would be dropped as a
  // duplicate of the one on screen.
  keyOf: (doc) => `${doc.name}/${doc.path || ''}`,
  read: (doc) => apiClient.readSkill(doc.name, doc.path),
  write: (doc, content, expectedMtime) =>
    apiClient.writeSkill({ name: doc.name, path: doc.path, content, expectedMtime }),
  refusal: (data) => (data.ships_with_install ? t('skill_builtin_readonly') : docRefusal(data)),
})

/**
 * A non-markdown file as a fenced code block, so it renders with the same
 * highlighting and copy button as code anywhere else in the app.
 *
 * The fence is longer than any run of backticks in the file, or a code sample
 * inside it would end the block early.
 */
function skillCodeBlock(path: string, content: string): string {
  // Only a real extension names a language: left unguarded a `LICENSE` would be
  // labelled one, and the highlighter asked to find it.
  const filename = path.split('/').pop() || ''
  const lang = filename.includes('.') ? (filename.split('.').pop() || '').toLowerCase() : ''
  // Folded rather than spread into Math.max: a file can hold more runs of
  // backticks than an argument list takes.
  const longest = (content.match(/`+/g) || []).reduce((n, run) => Math.max(n, run.length), 2)
  const fence = '`'.repeat(longest + 1)
  return `${fence}${lang}\n${content}\n${fence}`
}

/**
 * The read-only view of one of a skill's files.
 *
 * A markdown file - its SKILL.md above all - reads as prose, with the
 * frontmatter lifted out into a header: handed to the markdown renderer as-is
 * the `---` block becomes a giant bold heading and a horizontal rule. Anything
 * else is a script or a data file, and reads as code.
 */
const SkillContentView: React.FC<{
  content: string
  /** Which file is open; empty for the skill's own SKILL.md. */
  path?: string
  /** How it was listed, when the tree knows it. */
  file?: SkillFileEntry
}> = ({ content, path, file }) => {
  // A bundled asset belongs in the tree - it is part of the skill - but showing
  // it here would only print mojibake.
  if (file && !file.text) {
    return (
      <div className="py-12 flex flex-col items-center gap-2 text-content-tertiary">
        <FileQuestion size={22} />
        <span className="text-sm">{t('skill_file_not_text')}</span>
      </div>
    )
  }

  const isMarkdown = file ? file.kind === 'markdown' : !path || /\.(md|markdown)$/i.test(path)
  if (!isMarkdown) return <Markdown content={skillCodeBlock(path || '', content)} />

  const { fields, body } = parseSkillFrontmatter(content)
  return (
    <>
      {fields.length > 0 && (
        // The label column sizes to the longest key, up to a cap; past it a
        // dotted path like `metadata.cowagent.requires.anyEnv` wraps at its
        // dots rather than squeezing the values into a sliver.
        <dl className="mb-6 grid grid-cols-[minmax(5rem,9rem)_1fr] gap-x-4 gap-y-1.5 rounded-card border border-default bg-inset px-4 py-3 text-sm">
          {/* Index keys: a hand-written header may repeat a key. */}
          {fields.map(([key, value], row) => (
            <React.Fragment key={row}>
              <dt className="font-mono text-xs leading-6 text-content-tertiary break-words" title={key}>
                {key.split('.').map((part, i, parts) => (
                  <React.Fragment key={i}>
                    {part}
                    {i < parts.length - 1 && (
                      <>
                        .<wbr />
                      </>
                    )}
                  </React.Fragment>
                ))}
              </dt>
              <dd className="min-w-0 leading-6 text-content break-words">{value}</dd>
            </React.Fragment>
          ))}
        </dl>
      )}
      <Markdown content={body} />
    </>
  )
}

/**
 * The open skill's files, indented by the depth the server listed them at.
 *
 * Shown even for a skill that is only its SKILL.md: the panel is what says what
 * a skill is made of, and "one file, this big" is an answer to that. It only
 * goes away when the listing could not be fetched at all, where an empty tree
 * beside the file on screen would just look broken.
 */
const SkillFileTree: React.FC<{
  files: SkillFileEntry[]
  current: string
  /** Directories the reader has folded away, by path. Empty means all open. */
  folded: Set<string>
  onSelect: (path: string) => void
  onToggleDir: (path: string) => void
}> = ({ files, current, folded, onSelect, onToggleDir }) => {
  if (!files.length) return null

  const hiddenByFold = (path: string): boolean => {
    for (const dir of folded) if (path.startsWith(`${dir}/`)) return true
    return false
  }

  return (
    <div className="w-60 flex-shrink-0 flex flex-col min-h-0 border-r border-default">
      <div className="flex-shrink-0 px-4 pt-3 pb-1.5 truncate text-xs font-semibold uppercase tracking-wider text-content-tertiary">
        {t('skill_files_title')}
      </div>
      <div className="flex-1 overflow-y-auto px-2 pb-2 space-y-0.5">
        {files
          .filter((file) => !hiddenByFold(file.path))
          .map((file) => {
            const isFolded = folded.has(file.path)
            const active = !file.is_dir && file.path === current
            return (
              <button
                key={file.path}
                type="button"
                title={file.path}
                onClick={() => (file.is_dir ? onToggleDir(file.path) : onSelect(file.path))}
                style={{ paddingLeft: 8 + file.depth * 14 }}
                className={`w-full flex items-center gap-1.5 py-1.5 pr-2 rounded-btn text-[13px] text-left transition-colors cursor-pointer ${
                  active
                    ? 'bg-accent-soft text-accent'
                    : file.is_dir
                      ? 'text-content-secondary font-medium hover:bg-surface-2'
                      : 'text-content-secondary hover:bg-surface-2'
                }`}
              >
                {/* A caret only where there is something to fold; the others keep
                    its width so every name in one directory starts at one column. */}
                {file.is_dir ? (
                  isFolded ? (
                    <ChevronRight size={13} className="flex-shrink-0 opacity-70" />
                  ) : (
                    <ChevronDown size={13} className="flex-shrink-0 opacity-70" />
                  )
                ) : (
                  <span className="w-[13px] flex-shrink-0" />
                )}
                {file.is_dir ? (
                  isFolded ? (
                    <Folder size={13} className="flex-shrink-0 opacity-70" />
                  ) : (
                    <FolderOpen size={13} className="flex-shrink-0 opacity-70" />
                  )
                ) : (
                  <FileText size={13} className="flex-shrink-0 opacity-70" />
                )}
                <span className="flex-1 min-w-0 truncate">{file.name}</span>
                {/* Only for files: a directory's own size says nothing about what
                    the tree shows inside it. */}
                {!file.is_dir && (
                  <span
                    className={`flex-shrink-0 text-[10px] tabular-nums ${
                      active ? 'text-accent opacity-70' : 'text-content-tertiary'
                    }`}
                  >
                    {formatSkillFileSize(file.size)}
                  </span>
                )}
              </button>
            )
          })}
      </div>
    </div>
  )
}

/**
 * The switch that folds the file list away and brings it back, riding the
 * border the list sits against: centred on the divider while the list is out
 * (15rem is the panel's w-60), on the card's own left edge once it is folded,
 * level with the list's title. The half pixel centres it on a 1px line rather
 * than beside it. Mirrors `.skill-files-switch` in the web console.
 */
const SkillFilesSwitch: React.FC<{ expanded: boolean; onClick: () => void }> = ({
  expanded,
  onClick,
}) => (
  <button
    type="button"
    onClick={onClick}
    aria-expanded={expanded}
    aria-label={t(expanded ? 'skill_files_collapse' : 'skill_files_expand')}
    title={t(expanded ? 'skill_files_collapse' : 'skill_files_expand')}
    style={{ left: expanded ? 'calc(15rem + 0.5px)' : '0.5px' }}
    className="absolute top-[10px] z-10 -translate-x-1/2 w-[22px] h-[22px] inline-flex items-center justify-center rounded-full border border-default bg-surface shadow-sm text-content-tertiary hover:text-accent hover:border-accent transition-colors cursor-pointer"
  >
    {expanded ? <ChevronLeft size={12} /> : <ChevronRight size={12} />}
  </button>
)

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

function mcpStatusClass(status?: string): string {
  if (status === 'ready') return 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400'
  if (status === 'failed') return 'bg-red-500/10 text-red-500'
  if (status === 'needs_auth') return 'bg-amber-500/10 text-amber-600 dark:text-amber-400'
  if (status === 'disabled') return 'bg-inset-2 text-content-tertiary'
  return 'bg-blue-500/10 text-blue-600 dark:text-blue-400'
}

const cardClass = 'rounded-card border border-default bg-surface p-4 flex items-start gap-3'
const iconBtnClass = 'flex-shrink-0 p-1 -my-1 rounded text-content-tertiary transition-colors cursor-pointer'

const SkillsPage: React.FC<SkillsPageProps> = ({ baseUrl }) => {
  const [tools, setTools] = useState<ToolInfo[]>([])
  const [skills, setSkills] = useState<SkillInfo[]>([])
  const [servers, setServers] = useState<McpServerConfig[]>([])
  const [loading, setLoading] = useState(true)
  const [toolsExpanded, setToolsExpanded] = useState(false)
  // undefined: closed; null: adding; a config: editing that server.
  const [editing, setEditing] = useState<McpServerConfig | null | undefined>(undefined)
  const [addingSkill, setAddingSkill] = useState(false)
  const [freshSkills, setFreshSkills] = useState<Set<string>>(new Set())
  const [mcpError, setMcpError] = useState('')
  const [skillError, setSkillError] = useState('')
  const [notice, setNotice] = useState('')
  const noticeTimer = useRef<ReturnType<typeof setTimeout>>()

  const doc = skillEditor((s) => s.doc)
  const content = skillEditor((s) => s.content)
  const docLoading = skillEditor((s) => s.loading)
  const readonly = skillEditor((s) => s.readonly)
  const edit = skillEditor((s) => s.edit)
  const editorRef = useRef<HTMLTextAreaElement>(null)
  const [skillFiles, setSkillFiles] = useState<SkillFileEntry[]>([])
  /** Directories the reader has folded away, by path. Empty means all open. */
  const [foldedDirs, setFoldedDirs] = useState<Set<string>>(new Set())
  // Whether the file list is showing at all. Remembered across sessions:
  // someone who reads skills on a narrow window should not have to fold it
  // away again on every visit.
  const [filesPanelOpen, setFilesPanelOpen] = useState(
    () => localStorage.getItem(SKILL_FILES_PANEL_KEY) !== '0'
  )
  const openSkillName = doc?.name
  // A skill opens on its SKILL.md, which the tree lists under that name even
  // though the document was opened without naming a path.
  const currentPath = doc?.path || 'SKILL.md'

  const flash = (text: string) => {
    setNotice(text)
    clearTimeout(noticeTimer.current)
    noticeTimer.current = setTimeout(() => setNotice(''), 2600)
  }

  useEffect(() => () => clearTimeout(noticeTimer.current), [])

  // Saved servers start in the background, so keep refreshing while any is still loading.
  const mcpPollDeadline = useRef(0)
  useEffect(() => {
    if (!servers.some((s) => s.status === 'pending')) {
      mcpPollDeadline.current = 0
      return
    }
    if (!mcpPollDeadline.current) mcpPollDeadline.current = Date.now() + MCP_POLL_MAX_MS
    if (Date.now() > mcpPollDeadline.current) return
    const timer = setTimeout(() => {
      apiClient
        .getMcpServers()
        .then((data) => setServers(data.servers || []))
        .catch(() => {})
    }, MCP_POLL_INTERVAL_MS)
    return () => clearTimeout(timer)
  }, [servers])

  const loadData = async () => {
    try {
      setLoading(true)
      setMcpError('')
      const [toolsData, skillsData, mcpData] = await Promise.all([
        apiClient.getTools(),
        apiClient.getSkills(),
        // A broken mcp.json must not take the tools and skills lists down with it.
        apiClient.getMcpServers().catch((err: Error) => {
          setMcpError(`${t('mcp_load_failed')}: ${err.message}`)
          return { servers: [] as McpServerConfig[] }
        }),
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

  // Keyed on the skill rather than on the open file: moving between two files
  // of one skill must not refetch the tree they are both listed in. The tree is
  // a convenience, so a failure leaves it empty rather than reporting itself.
  useEffect(() => {
    // The folds belonged to the tree being left behind, not to the next one.
    setFoldedDirs(new Set())
    if (!openSkillName) {
      setSkillFiles([])
      return
    }
    let live = true
    apiClient
      .listSkillFiles(openSkillName)
      .then((files) => live && setSkillFiles(files))
      .catch(() => live && setSkillFiles([]))
    return () => {
      live = false
    }
  }, [openSkillName])

  const toggle = async (skill: SkillInfo, enabled: boolean) => {
    // Optimistic flip; revert on failure.
    setSkills((prev) => prev.map((s) => (s.name === skill.name ? { ...s, enabled } : s)))
    try {
      const res = await apiClient.toggleSkill(skill.name, enabled ? 'open' : 'close')
      if (res.status !== 'success') throw new Error()
    } catch {
      setSkills((prev) => prev.map((s) => (s.name === skill.name ? { ...s, enabled: !enabled } : s)))
      flash(t('skill_toggle_error'))
    }
  }

  // The card's pencil opens the viewer and jumps straight into editing,
  // skipping the read-only view. `startEdit` no-ops for a read-only skill, so
  // the built-in ones simply open to their content.
  const openSkillForEdit = async (skill: SkillInfo) => {
    await skillEditor
      .getState()
      .open({ name: skill.name, label: skill.display_name || skill.name })
    await skillEditor.getState().startEdit()
  }

  const toggleFilesPanel = () => {
    const open = !filesPanelOpen
    setFilesPanelOpen(open)
    localStorage.setItem(SKILL_FILES_PANEL_KEY, open ? '1' : '0')
  }

  const toggleSkillDir = (path: string) =>
    setFoldedDirs((prev) => {
      const next = new Set(prev)
      if (!next.delete(path)) next.add(path)
      return next
    })

  /** Show another of the open skill's files. */
  const selectSkillFile = async (path: string) => {
    if (!doc || currentPath === path) return
    // `open` is what asks about an unsaved edit before the text area is
    // replaced by another file's contents.
    await skillEditor.getState().open({ ...doc, path })
  }

  const closeViewer = async () => {
    if (!(await skillEditor.getState().close())) return
    // A saved edit can change the name and description in the frontmatter, so
    // the cards behind this panel may be out of date.
    void loadData()
  }

  const persistServers = async (next: McpServerConfig[]) => {
    const res = await apiClient.saveMcpServers(next)
    if (res.status !== 'success') throw new Error(res.message || t('mcp_save_error'))
    mcpPollDeadline.current = 0
    setServers(res.servers || next)
  }

  const saveFromEditor = async (next: McpServerConfig[], notice: string) => {
    await persistServers(next)
    setEditing(undefined)
    flash(notice)
  }

  const removeServer = async (name: string) => {
    const ok = await askConfirm({ titleKey: 'mcp_delete', msgKey: 'mcp_delete_confirm', okKey: 'mcp_delete' })
    if (!ok) return
    setMcpError('')
    try {
      await persistServers(servers.filter((item) => item.name !== name))
    } catch (err) {
      setMcpError(err instanceof Error ? err.message : t('mcp_save_error'))
    }
  }

  const reloadSkills = async () => {
    setSkills((await apiClient.getSkills()) || [])
  }

  const onSkillsInstalled = (names: string[]) => {
    void reloadSkills()
    setFreshSkills(new Set(names))
    setTimeout(() => setFreshSkills(new Set()), 2600)
  }

  const uninstall = async (name: string) => {
    const ok = await askConfirm({ titleKey: 'skill_delete', msgKey: 'skill_delete_confirm', okKey: 'skill_delete' })
    if (!ok) return
    setSkillError('')
    try {
      const res = await apiClient.deleteSkill(name)
      if (res.status !== 'success') throw new Error(res.message || t('skill_delete_error'))
      await reloadSkills()
    } catch (err) {
      setSkillError(`${t('skill_delete_error')}: ${err instanceof Error ? err.message : ''}`)
    }
  }

  const visibleTools = toolsExpanded ? tools : tools.slice(0, TOOLS_COLLAPSED_COUNT)

  return (
    <div className="flex-1 flex flex-col min-h-0">
      <div className="flex items-center justify-between px-6 pt-5 pb-3 flex-shrink-0">
        <div>
          <h2 className="text-xl font-bold text-content">{t('skills_title')}</h2>
          <p className="text-xs text-content-tertiary mt-1">{t('skills_desc')}</p>
        </div>
      </div>

      <DocNotice store={skillEditor} />

      {doc ? (
        <div className="flex-1 flex flex-col min-h-0 border-t border-default">
          <div className="flex items-center gap-3 px-6 py-3 flex-shrink-0">
            <button
              onClick={() => void closeViewer()}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-btn text-sm text-content-secondary hover:bg-inset border border-strong transition-colors cursor-pointer"
            >
              <ArrowLeft size={14} />
              {t('skill_back')}
            </button>
            <h3 className="flex-1 text-sm font-semibold text-content truncate">
              {doc.path ? `${doc.label}/${doc.path}` : doc.label}
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
          {/* One card for the file list and the document, inset to the header's
              padding so its edges line up with Back and the actions above. */}
          <div className="flex-1 min-h-0 px-6 pb-6">
            <div className="relative h-full">
              {/* Folding the list away is the only way back to a full-width
                  document, so the switch cannot live inside the panel it hides.
                  It rides the border instead: the divider while the list is
                  out, the card's left edge once it is folded. */}
              {skillFiles.length > 0 && (
                <SkillFilesSwitch expanded={filesPanelOpen} onClick={toggleFilesPanel} />
              )}
              <div className="h-full flex rounded-card border border-default bg-surface overflow-hidden">
                {skillFiles.length > 0 && filesPanelOpen && (
                  <SkillFileTree
                    files={skillFiles}
                    current={currentPath}
                    folded={foldedDirs}
                    onSelect={(path) => void selectSkillFile(path)}
                    onToggleDir={toggleSkillDir}
                  />
                )}
                {edit ? (
                  <div className="flex-1 min-w-0 min-h-0 overflow-hidden">
                    <DocEditor
                      key={`${doc.name}/${doc.path || ''}`}
                      store={skillEditor}
                      textareaRef={editorRef}
                    />
                  </div>
                ) : (
                  <DocView store={skillEditor}>
                    <div className="max-w-3xl mx-auto px-8 py-6">
                      {docLoading ? (
                        <div className="flex items-center text-content-tertiary py-8">
                          <Loader2 size={16} className="animate-spin mr-2" />
                        </div>
                      ) : (
                        <SkillContentView
                          content={content}
                          path={currentPath}
                          file={skillFiles.find((file) => file.path === currentPath)}
                        />
                      )}
                    </div>
                  </DocView>
                )}
              </div>
            </div>
          </div>
        </div>
      ) : (
      <div className="flex-1 overflow-y-auto border-t border-default">
        <div className="max-w-4xl mx-auto px-6 py-6">
          {loading ? (
            <div className="flex items-center justify-center py-20 text-content-tertiary">
              <Loader2 size={18} className="animate-spin mr-2" />
              {t('skills_loading')}
            </div>
          ) : (
            <div className="space-y-10">
              <Section
                title={t('tools_section_title')}
                count={tools.length}
                action={
                  tools.length > TOOLS_COLLAPSED_COUNT && (
                    <LinkBtn onClick={() => setToolsExpanded((v) => !v)}>
                      {t(toolsExpanded ? 'tools_collapse' : 'tools_show_all')}
                      <ChevronDown size={12} className={`transition-transform ${toolsExpanded ? 'rotate-180' : ''}`} />
                    </LinkBtn>
                  )
                }
              >
                {tools.length === 0 ? (
                  <p className="text-sm text-content-tertiary py-2">{t('tools_empty')}</p>
                ) : (
                  <div className="grid gap-3 sm:grid-cols-2">
                    {visibleTools.map((tool) => {
                      const Icon = TOOL_ICONS[tool.name] || Wrench
                      return (
                        <div key={tool.name} className={cardClass}>
                          <div className="w-9 h-9 rounded-lg bg-blue-500/10 flex items-center justify-center flex-shrink-0">
                            <Icon size={15} className="text-blue-500" />
                          </div>
                          <div className="flex-1 min-w-0">
                            <span className="block text-sm font-medium text-content font-mono truncate">{tool.name}</span>
                            <p className="text-xs text-content-tertiary leading-relaxed mt-1 line-clamp-2">{tool.description || '--'}</p>
                          </div>
                        </div>
                      )
                    })}
                  </div>
                )}
              </Section>

              <Section
                title={t('mcp_section_title')}
                count={servers.length}
                action={
                  <ActionBtn onClick={() => setEditing(null)}>
                    <Plus size={12} />
                    {t('mcp_add')}
                  </ActionBtn>
                }
              >
                {mcpError && <p className="mb-3 text-sm text-danger">{mcpError}</p>}
                {servers.length === 0 ? (
                  !mcpError && (
                    <EmptyState icon={Plug} title={t('mcp_empty')} hint={t('mcp_empty_hint')} tone="amber" />
                  )
                ) : (
                  <div className="grid gap-3 sm:grid-cols-2">
                    {servers.map((server) => {
                      const type = mcpTransport(server)
                      const summary =
                        type === 'stdio'
                          ? [server.command, ...(server.args || [])].filter(Boolean).join(' ')
                          : server.url || ''
                      return (
                        <div
                          key={server.name}
                          onClick={() => setEditing(server)}
                          className={`${cardClass} cursor-pointer hover:border-strong transition-colors`}
                        >
                          <div className="w-9 h-9 rounded-lg bg-amber-500/10 flex items-center justify-center flex-shrink-0">
                            <Plug size={15} className={server.status === 'disabled' ? 'text-content-tertiary' : 'text-amber-500'} />
                          </div>
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-2 mb-1">
                              <span className="text-sm font-medium text-content font-mono truncate">{server.name}</span>
                              <span className="flex-shrink-0 px-1.5 py-0.5 rounded text-[10px] font-medium bg-inset-2 text-content-tertiary">
                                {MCP_TRANSPORT_LABELS[type] || type}
                              </span>
                              <span className={`flex-shrink-0 px-1.5 py-0.5 rounded-full text-[10px] ${mcpStatusClass(server.status)}`}>
                                {mcpStatusLabel(server.status)}
                              </span>
                              <span className="flex-1" />
                              <button
                                type="button"
                                title={t('mcp_edit')}
                                onClick={(e) => {
                                  e.stopPropagation()
                                  setEditing(server)
                                }}
                                className={`${iconBtnClass} hover:text-content-secondary`}
                              >
                                <Pencil size={11} />
                              </button>
                              <button
                                type="button"
                                title={t('mcp_delete')}
                                onClick={(e) => {
                                  e.stopPropagation()
                                  void removeServer(server.name)
                                }}
                                className={`${iconBtnClass} hover:text-red-500`}
                              >
                                <Trash2 size={11} />
                              </button>
                            </div>
                            <p className="text-xs text-content-tertiary font-mono truncate" title={summary}>
                              {summary || '--'}
                            </p>
                          </div>
                        </div>
                      )
                    })}
                  </div>
                )}
              </Section>

              <Section
                title={t('skills_section_title')}
                count={skills.length}
                action={
                  <>
                    {!product.skills?.uploadOnly && (
                      <a
                        href={SKILL_HUB_URL}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="inline-flex items-center gap-1.5 px-2 py-1.5 rounded-btn text-xs text-content-tertiary hover:text-content-secondary hover:bg-surface-2 transition-colors"
                      >
                        <Compass size={12} />
                        {t('skills_hub_btn')}
                        <ExternalLink size={10} className="opacity-60" />
                      </a>
                    )}
                    <ActionBtn onClick={() => setAddingSkill(true)}>
                      <Plus size={12} />
                      {t('skill_add')}
                    </ActionBtn>
                  </>
                }
              >
                {skillError && <p className="mb-3 text-sm text-danger">{skillError}</p>}
                {skills.length === 0 ? (
                  <EmptyState icon={Zap} title={t('skills_empty')} hint={t(product.skills?.uploadOnly ? 'skills_empty_hint_upload' : 'skills_empty_hint')} tone="accent" />
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
                        className={`${cardClass} cursor-pointer transition-all ${
                          freshSkills.has(skill.name)
                            ? 'border-accent shadow-[0_0_0_3px_var(--accent-soft)]'
                            : 'hover:border-strong'
                        }`}
                      >
                        <div className="w-9 h-9 rounded-lg bg-accent-soft flex items-center justify-center flex-shrink-0">
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
                              className={`${iconBtnClass} hover:text-content-secondary`}
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
                                className={`${iconBtnClass} hover:text-red-500`}
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

      <McpEditorModal
        server={editing}
        existing={servers}
        onClose={() => setEditing(undefined)}
        onSave={saveFromEditor}
      />
      <SkillAddModal
        open={addingSkill}
        onClose={() => setAddingSkill(false)}
        onInstalled={onSkillsInstalled}
        onCreated={(name) => {
          setAddingSkill(false)
          flash(`${t('skill_new_created')}: ${name}`)
          onSkillsInstalled([name])
        }}
      />

      {notice && (
        <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-[80] px-4 py-2 rounded-btn bg-neutral-900/90 text-white text-sm shadow-lg pointer-events-none">
          {notice}
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
  <section>
    <div className="flex items-center gap-2 mb-3 min-h-[28px]">
      <span className="text-xs font-semibold uppercase tracking-wider text-content-tertiary">{title}</span>
      {count > 0 && (
        <span className="px-1.5 py-0.5 rounded-full text-xs bg-inset-2 text-content-tertiary min-w-[20px] text-center">{count}</span>
      )}
      <div className="ml-auto flex items-center gap-1">{action}</div>
    </div>
    {children}
  </section>
)

const ActionBtn: React.FC<{ onClick: () => void; children: React.ReactNode }> = ({ onClick, children }) => (
  <button
    type="button"
    onClick={onClick}
    className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-btn text-xs font-medium text-accent bg-accent-soft hover:brightness-95 dark:hover:brightness-110 cursor-pointer transition-all"
  >
    {children}
  </button>
)

const LinkBtn: React.FC<{ onClick: () => void; children: React.ReactNode }> = ({ onClick, children }) => (
  <button
    type="button"
    onClick={onClick}
    className="inline-flex items-center gap-1.5 px-2 py-1.5 rounded-btn text-xs text-content-tertiary hover:text-content-secondary hover:bg-surface-2 cursor-pointer transition-colors"
  >
    {children}
  </button>
)

const EmptyState: React.FC<{ icon: LucideIcon; title: string; hint: string; tone: 'accent' | 'amber' }> = ({
  icon: Icon,
  title,
  hint,
  tone,
}) => (
  <div className="flex flex-col items-center justify-center px-4 py-7 rounded-card border border-dashed border-strong text-center">
    <div
      className={`w-10 h-10 mb-2.5 rounded-card flex items-center justify-center ${
        tone === 'accent' ? 'bg-accent-soft text-accent' : 'bg-amber-500/10 text-amber-500'
      }`}
    >
      <Icon size={17} />
    </div>
    <p className="text-sm font-medium text-content-secondary">{title}</p>
    <p className="text-xs text-content-tertiary mt-1">{hint}</p>
  </div>
)

export default SkillsPage
