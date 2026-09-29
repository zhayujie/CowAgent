import React, { useEffect, useRef, useState } from 'react'
import {
  ArrowLeft,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  FileArchive,
  FileQuestion,
  FileText,
  FileUp,
  Folder,
  FolderOpen,
  FolderPlus,
  Loader2,
  Lock,
  Paperclip,
  Pencil,
  Plus,
  Puzzle,
  UploadCloud,
  Wrench,
  X,
  Zap,
} from 'lucide-react'
import { t, tf } from '../i18n'
import apiClient from '../api/client'
import type { ApiResult } from '../api/client'
import type { ToolInfo, SkillInfo, SkillContent, SkillFileEntry } from '../types'
import { Toggle } from './settings/primitives'
import Markdown from '../components/Markdown'
import { DocActions, DocEditor, DocNotice, DocView } from '../components/DocEditor'
import { createDocEditorStore, docRefusal } from '../store/docEditorStore'

interface SkillsPageProps {
  baseUrl: string
}

const SKILL_HUB_URL = 'https://skills.cowagent.ai/'

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

/** Drop the surrounding quotes a YAML scalar may carry. */
function yamlScalar(raw: string): string {
  return raw.trim().replace(/^(['"])(.*)\1$/, '$2')
}

/**
 * Split a skill's SKILL.md into its YAML frontmatter fields and the markdown
 * body. The `---` header is metadata, not prose: handed to the markdown
 * renderer as-is it becomes a giant bold heading and a horizontal rule. Pull it
 * out so name/description show as a proper header instead.
 *
 * Frontmatter nests: `metadata.cowagent.requires.anyEnv` is a list four levels
 * down. Read line by line with no regard for indentation, each container key
 * showed up as an empty row and the list under it vanished. So this walks the
 * indentation instead: a nested map becomes one row per leaf, keyed by its
 * dotted path; a list or a block scalar (`|`, `>`) becomes one row with its
 * lines joined. Only leaves are rows - a key that merely holds others has
 * nothing to say on its own.
 */
function parseSkillFrontmatter(content: string): { fields: Array<[string, string]>; body: string } {
  const text = content || ''
  const match = text.match(/^---\s*\r?\n([\s\S]*?)\r?\n---\s*\r?\n?/)
  if (!match) return { fields: [], body: text }

  const lines = match[1].split(/\r?\n/)
  const fields: Array<[string, string]> = []
  // The key at each indentation level above the current line.
  const path: Array<{ indent: number; key: string }> = []
  // A key whose value is still being collected from the lines below it: the
  // items of a list, or the lines of a block scalar.
  let open: { key: string; indent: number; items: string[]; block: boolean } | null = null

  const flush = () => {
    if (!open) return
    const joined = open.block ? open.items.join(' ').trim() : open.items.join(', ')
    fields.push([open.key, joined])
    open = null
  }

  for (const raw of lines) {
    const line = raw.trim()
    if (!line) continue
    const indent = raw.length - raw.trimStart().length
    // Inside a block scalar a `#` line is text, not a comment.
    if (open && open.block && indent > open.indent) {
      open.items.push(line)
      continue
    }
    if (line.startsWith('#')) continue
    // A list's dashes may sit level with their key or under it.
    if (open && !open.block && indent >= open.indent && line.startsWith('- ')) {
      open.items.push(yamlScalar(line.slice(2)))
      continue
    }
    // Anything else ends an open value: what follows is the next key, or -
    // under a key opened as a possible list - the first key of a nested map.
    flush()

    while (path.length && path[path.length - 1].indent >= indent) path.pop()
    const idx = line.indexOf(':')
    if (idx === -1) continue
    const key = yamlScalar(line.slice(0, idx))
    if (!key) continue
    const dotted = [...path.map((p) => p.key), key].join('.')
    const rest = line.slice(idx + 1).trim()

    if (!rest) {
      // Either a nested map, or a list that starts on the next line: which one
      // is decided by the line that follows. Open both readings and let the
      // next indented line settle it.
      path.push({ indent, key })
      open = { key: dotted, indent, items: [], block: false }
    } else if (/^[|>][-+0-9]*$/.test(rest)) {
      open = { key: dotted, indent, items: [], block: true }
    } else {
      fields.push([dotted, yamlScalar(rest)])
    }
  }
  flush()

  // A container key opened as a possible list but then held a map instead: its
  // children have their own rows, so drop the empty one it left behind.
  return { fields: fields.filter(([, value]) => value !== ''), body: text.slice(match[0].length) }
}

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

const SkillsPage: React.FC<SkillsPageProps> = ({ baseUrl }) => {
  const [tools, setTools] = useState<ToolInfo[]>([])
  const [skills, setSkills] = useState<SkillInfo[]>([])
  const [loading, setLoading] = useState(true)
  const [creating, setCreating] = useState(false)
  const [status, setStatus] = useState('')

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

  const loadData = async () => {
    try {
      setLoading(true)
      const [toolsData, skillsData] = await Promise.all([apiClient.getTools(), apiClient.getSkills()])
      setTools(toolsData || [])
      setSkills(skillsData || [])
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

  return (
    <div className="flex-1 flex flex-col min-h-0">
      <div className="flex items-center justify-between px-6 pt-5 pb-3 flex-shrink-0">
        <div>
          <h2 className="text-xl font-bold text-content">{t('skills_title')}</h2>
          <p className="text-xs text-content-tertiary mt-1">{t('skills_desc')}</p>
        </div>
        {!doc && (
          <div className="flex items-center gap-2">
            {status && (
              <span className="text-xs max-w-[260px] truncate text-content-tertiary" title={status}>
                {status}
              </span>
            )}
            <a
              href={SKILL_HUB_URL}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-btn text-xs font-medium text-accent bg-accent-soft hover:bg-accent-soft transition-colors"
            >
              <Puzzle size={12} />
              {t('skills_hub_btn')}
            </a>
            <button
              type="button"
              onClick={() => setCreating(true)}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-btn text-xs font-medium text-white bg-accent hover:opacity-90 transition-opacity cursor-pointer"
            >
              <Plus size={12} />
              {t('skill_new_btn')}
            </button>
          </div>
        )}
      </div>

      {creating && (
        <SkillCreateDialog
          onClose={() => setCreating(false)}
          onDone={(message) => {
            setCreating(false)
            setStatus(message)
            window.setTimeout(() => setStatus(''), 6000)
            void loadData()
          }}
        />
      )}

      <DocNotice store={skillEditor} />

      {doc ? (
        /* Skill viewer / editor */
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
                  •
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

              <Section title={t('skills_section_title')} count={skills.length}>
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
                            {/* The pencil and switch sit inside a card that opens
                                the skill, so their clicks must not reach it. */}
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
    </div>
  )
}

// ---------------------------------------------------------------------------
// Creating a skill: a form, or an uploaded folder / archive
// ---------------------------------------------------------------------------

// The server's own ceilings, mirrored so a 50 MB folder is refused here rather
// than after being uploaded. See SkillService.MAX_UPLOAD_*.
const SKILL_UPLOAD_MAX_FILES = 500
const SKILL_UPLOAD_MAX_FILE_SIZE = 10 * 1024 * 1024
const SKILL_UPLOAD_MAX_TOTAL_SIZE = 50 * 1024 * 1024

// `webkitdirectory` is what turns a file input into a folder picker; React's
// typings do not carry the attribute.
const FOLDER_INPUT_PROPS = {
  webkitdirectory: '',
  directory: '',
} as unknown as React.InputHTMLAttributes<HTMLInputElement>

/**
 * The directory name a title reduces to. Mirrors `normalize_skill_name` on the
 * server, so the preview under the field is what actually gets created.
 */
function skillNameSlug(raw: string): string {
  return (raw || '')
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 64)
    .replace(/-+$/, '')
}

function formatSkillFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

/**
 * Where an attachment lands inside the skill directory.
 *
 * A folder pick carries the path the file sat at under the chosen folder, so
 * `scripts/` picked as a folder installs as `scripts/`. A loose file has only
 * its own name, and lands beside SKILL.md.
 */
function skillAttachmentPath(file: File): string {
  return file.webkitRelativePath || file.name
}

/**
 * The files of a picked folder that are worth installing.
 *
 * A directory on disk carries more than what someone wrote: caches, a
 * virtualenv, an editor's dotfiles. Bundling those would install megabytes the
 * skill never uses, and the console's file tree hides them anyway - so the tree
 * would not even show what had been added.
 */
function skillUploadCandidates(files: File[]): File[] {
  const noise = ['__pycache__', 'node_modules', 'venv']
  return files.filter((file) =>
    skillAttachmentPath(file)
      .split('/')
      .every((part) => !part.startsWith('.') && !noise.includes(part))
  )
}

/** Validate a batch of picked files. Returns an error message, or ''. */
function validateSkillUploadFiles(files: File[]): string {
  if (!files.length) return t('skill_upload_required')
  if (files.length > SKILL_UPLOAD_MAX_FILES) {
    return tf('skill_upload_too_many', { max: SKILL_UPLOAD_MAX_FILES })
  }
  let total = 0
  for (const file of files) {
    total += file.size || 0
    if ((file.size || 0) > SKILL_UPLOAD_MAX_FILE_SIZE) {
      return tf('skill_upload_file_too_large', {
        name: file.name,
        max: SKILL_UPLOAD_MAX_FILE_SIZE / 1024 / 1024,
      })
    }
  }
  if (total > SKILL_UPLOAD_MAX_TOTAL_SIZE) {
    return tf('skill_upload_total_too_large', { max: SKILL_UPLOAD_MAX_TOTAL_SIZE / 1024 / 1024 })
  }
  return ''
}

const SkillCreateDialog: React.FC<{
  onClose: () => void
  /** Called with the line to show in the header once something was installed. */
  onDone: (message: string) => void
}> = ({ onClose, onDone }) => {
  const [mode, setMode] = useState<'form' | 'upload'>('form')
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [body, setBody] = useState('')
  const [files, setFiles] = useState<File[]>([])
  const [archive, setArchive] = useState<File | null>(null)
  const [folder, setFolder] = useState<File[]>([])
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [dragOver, setDragOver] = useState(false)
  // Two picks behind one button: a native file dialog browses for files or for a
  // directory, never both, so the choice is made before it opens.
  const [attachOpen, setAttachOpen] = useState(false)
  const filesRef = useRef<HTMLInputElement>(null)
  const createFolderRef = useRef<HTMLInputElement>(null)
  const archiveRef = useRef<HTMLInputElement>(null)
  const folderRef = useRef<HTMLInputElement>(null)
  const attachRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!attachOpen) return
    const onDown = (e: MouseEvent) => {
      if (attachRef.current && !attachRef.current.contains(e.target as Node)) setAttachOpen(false)
    }
    // Captured rather than bubbled: the dialog stops mousedown from leaving it,
    // so a bubbling listener would never see a click on the fields behind the
    // menu - only one on the overlay, which closes the whole dialog anyway.
    document.addEventListener('mousedown', onDown, true)
    return () => document.removeEventListener('mousedown', onDown, true)
  }, [attachOpen])

  const slug = skillNameSlug(name)

  const pickArchive = (file: File) => {
    if (!/\.(zip|tgz|tar|gz)$/i.test(file.name || '')) {
      setError(t('skill_upload_bad_archive'))
      return
    }
    setError('')
    setFolder([])
    setArchive(file)
  }

  const pickFolder = (picked: File[]) => {
    const wanted = skillUploadCandidates(picked)
    const err = validateSkillUploadFiles(wanted)
    if (err) {
      setError(err)
      return
    }
    setError('')
    setArchive(null)
    setFolder(wanted)
  }

  /** Add what one of the attachment inputs picked to the list under the field. */
  const addAttachments = (picked: File[], asFolder: boolean) => {
    const wanted = asFolder ? skillUploadCandidates(picked) : picked
    // One path is one attachment: the same file picked twice does not become
    // two, and two files of that name in different folders stay two.
    setFiles((prev) => [
      ...prev,
      ...wanted.filter(
        (file) => !prev.some((f) => skillAttachmentPath(f) === skillAttachmentPath(file))
      ),
    ])
  }

  const submitForm = async () => {
    if (!slug) return setError(t('skill_new_name_invalid'))
    // The loader drops a skill with no description, so it is required here too.
    if (!description.trim()) return setError(t('skill_new_desc_required'))
    if (files.length) {
      const err = validateSkillUploadFiles(files)
      if (err) return setError(err)
    }
    setBusy(true)
    setError('')
    try {
      const res = await apiClient.createSkill({ name, description, body, files })
      if (res.status !== 'success') return setError(res.message || t('skill_new_failed'))
      onDone(`${t('skill_new_created')}: ${res.name}`)
    } catch {
      setError(t('skill_new_failed'))
    } finally {
      setBusy(false)
    }
  }

  const submitUpload = async () => {
    if (!archive && !folder.length) return setError(t('skill_upload_required'))
    setBusy(true)
    setError('')
    try {
      const res = archive
        ? await apiClient.uploadSkillArchive(archive)
        : await apiClient.uploadSkillFolder(folder)
      if (res.status !== 'success') return setError(res.message || t('skill_new_failed'))

      const installed = (res.installed || []).concat(res.replaced || [])
      const skipped = res.skipped || []
      if (!installed.length) {
        // Every skill in the upload was refused: show the first reason, which is
        // the only actionable part of the answer.
        return setError(
          skipped.length ? `${skipped[0].name}: ${skipped[0].reason}` : t('skill_upload_none')
        )
      }
      let message = `${t('skill_upload_installed')}: ${installed.join(', ')}`
      if (skipped.length) {
        message += ` · ${t('skill_upload_skipped')}: ${skipped.map((s) => s.name).join(', ')}`
      }
      onDone(message)
    } catch {
      setError(t('skill_new_failed'))
    } finally {
      setBusy(false)
    }
  }

  const submit = () => (mode === 'upload' ? void submitUpload() : void submitForm())

  const fieldClass =
    'w-full px-3 py-2 rounded-btn border border-strong bg-inset text-sm text-content placeholder:text-content-tertiary focus:outline-none focus:border-accent transition-colors'

  return (
    <div
      className="fixed inset-0 z-[70] flex items-center justify-center bg-black/40 p-4"
      onMouseDown={() => !busy && onClose()}
    >
      <div
        // `overflow-hidden` keeps the body's scrollbar inside the rounded corners.
        className="w-full max-w-lg max-h-[90vh] flex flex-col bg-surface border border-default rounded-xl shadow-xl overflow-hidden"
        onMouseDown={(e) => e.stopPropagation()}
      >
        {/* Title and tabs stay put; only the fields below scroll. */}
        <div className="px-5 pt-5 pb-4 flex-shrink-0">
          <h3 className="text-base font-semibold text-content">{t('skill_new_title')}</h3>
          <p className="text-xs text-content-tertiary mt-1 mb-4">{t('skill_new_subtitle')}</p>

          <div className="flex gap-1 p-1 rounded-btn bg-inset">
            {(['form', 'upload'] as const).map((value) => (
              <button
                key={value}
                type="button"
                onClick={() => {
                  setMode(value)
                  setError('')
                }}
                className={`flex-1 inline-flex items-center justify-center gap-1.5 px-3 py-1.5 rounded-btn text-xs font-medium transition-colors cursor-pointer ${
                  mode === value ? 'bg-surface text-content shadow-sm' : 'text-content-tertiary'
                }`}
              >
                {value === 'form' ? <Pencil size={11} /> : <UploadCloud size={11} />}
                {t(value === 'form' ? 'skill_new_tab_form' : 'skill_new_tab_upload')}
              </button>
            ))}
          </div>
        </div>

        <div className="px-5 pb-5 min-h-0 overflow-y-auto">
          {mode === 'form' ? (
            <div className="space-y-4">
              <div>
                <label className="block text-sm text-content-secondary mb-1.5">{t('skill_new_name')}</label>
                <input
                  autoFocus
                  value={name}
                  maxLength={64}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="weather-api"
                  className={fieldClass}
                />
                <p
                  className={`text-xs mt-1.5 break-all ${
                    name.trim() && !slug ? 'text-danger' : 'text-content-tertiary'
                  }`}
                >
                  {!name.trim()
                    ? t('skill_new_name_hint')
                    : !slug
                      ? t('skill_new_name_invalid')
                      : slug === name.trim()
                        ? t('skill_new_name_hint')
                        : `${t('skill_new_name_dir')}: ${slug}`}
                </p>
              </div>
              <div>
                <label className="block text-sm text-content-secondary mb-1.5">{t('skill_new_desc')}</label>
                <textarea
                  rows={3}
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  className={`${fieldClass} resize-y`}
                />
                <p className="text-xs text-content-tertiary mt-1.5">{t('skill_new_desc_hint')}</p>
              </div>
              <div>
                <label className="block text-sm text-content-secondary mb-1.5">{t('skill_new_body')}</label>
                <textarea
                  rows={6}
                  value={body}
                  onChange={(e) => setBody(e.target.value)}
                  placeholder={'## Usage\n\n...'}
                  className={`${fieldClass} font-mono resize-y`}
                />
                <p className="text-xs text-content-tertiary mt-1.5">{t('skill_new_body_hint')}</p>
              </div>
              <div>
                <div className="flex items-center justify-between mb-1.5">
                  <label className="text-sm text-content-secondary">{t('skill_new_files')}</label>
                  {/* A skill's resources come as a directory as often as they come as
                      loose files - `scripts/`, `references/` - and the paths are kept,
                      so the layout picked here is the one installed. */}
                  <div ref={attachRef} className="relative">
                    <button
                      type="button"
                      onClick={() => setAttachOpen((v) => !v)}
                      className="inline-flex items-center gap-1 text-xs text-accent hover:opacity-80 cursor-pointer"
                    >
                      <Paperclip size={11} />
                      {t('skill_new_files_add')}
                    </button>
                    {attachOpen && (
                      // Opening upwards: the attachments are the last field of a
                      // dialog that scrolls, so a menu below the button would be
                      // clipped by the dialog's own overflow.
                      <div className="absolute right-0 bottom-full mb-1.5 w-36 z-30 rounded-xl border border-default bg-elevated shadow-xl p-1">
                        {[
                          { icon: FileUp, label: t('skill_new_files_pick'), ref: filesRef },
                          { icon: FolderPlus, label: t('skill_upload_pick_folder'), ref: createFolderRef },
                        ].map(({ icon: Icon, label, ref }) => (
                          <button
                            key={label}
                            type="button"
                            onClick={() => {
                              setAttachOpen(false)
                              ref.current?.click()
                            }}
                            className="w-full flex items-center gap-2 px-2 py-1.5 rounded-lg text-xs text-left text-content hover:bg-inset cursor-pointer"
                          >
                            <Icon size={12} className="flex-shrink-0 opacity-70" />
                            {label}
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
                {files.length === 0 ? (
                  <p className="text-xs text-content-tertiary">{t('skill_new_files_hint')}</p>
                ) : (
                  // A picked folder can be dozens of files, so the list scrolls
                  // rather than pushing the create button off the dialog.
                  <div className="space-y-1.5 max-h-40 overflow-y-auto">
                    {files.map((file, index) => (
                      <div
                        key={skillAttachmentPath(file)}
                        className="flex items-center gap-2 px-2.5 py-1.5 rounded-btn border border-default bg-inset"
                      >
                        <span
                          title={skillAttachmentPath(file)}
                          className="flex-1 min-w-0 text-xs font-mono text-content truncate"
                        >
                          {skillAttachmentPath(file)}
                        </span>
                        <span className="text-[11px] text-content-tertiary">{formatSkillFileSize(file.size)}</span>
                        <button
                          type="button"
                          onClick={() => setFiles(files.filter((_, i) => i !== index))}
                          className="text-content-tertiary hover:text-danger cursor-pointer"
                        >
                          <X size={11} />
                        </button>
                      </div>
                    ))}
                  </div>
                )}
                <input
                  ref={filesRef}
                  type="file"
                  multiple
                  className="hidden"
                  onChange={(e) => {
                    const picked = Array.from(e.target.files || [])
                    e.target.value = ''
                    addAttachments(picked, false)
                  }}
                />
                <input
                  ref={createFolderRef}
                  type="file"
                  multiple
                  {...FOLDER_INPUT_PROPS}
                  className="hidden"
                  onChange={(e) => {
                    const picked = Array.from(e.target.files || [])
                    e.target.value = ''
                    addAttachments(picked, true)
                  }}
                />
              </div>
            </div>
          ) : (
            <div>
              <div
                onDragEnter={(e) => {
                  if (e.dataTransfer?.types?.includes('Files')) {
                    e.preventDefault()
                    setDragOver(true)
                  }
                }}
                onDragOver={(e) => {
                  if (e.dataTransfer?.types?.includes('Files')) e.preventDefault()
                }}
                onDragLeave={() => setDragOver(false)}
                onDrop={(e) => {
                  e.preventDefault()
                  setDragOver(false)
                  // A dropped directory arrives as an entry whose contents this
                  // handler cannot read, so it points at the folder picker
                  // rather than uploading an empty archive.
                  const entry = e.dataTransfer?.items?.[0]?.webkitGetAsEntry?.()
                  if (entry?.isDirectory) {
                    setError(t('skill_upload_drop_dir'))
                    return
                  }
                  const file = (e.dataTransfer?.files || [])[0]
                  if (file) pickArchive(file)
                }}
                className={`rounded-xl border-2 border-dashed px-4 py-8 text-center transition-colors ${
                  dragOver ? 'border-accent bg-accent-soft' : 'border-default'
                }`}
              >
                <UploadCloud size={24} className="mx-auto text-content-tertiary" />
                <p className="mt-3 text-sm text-content-secondary">{t('skill_upload_drop')}</p>
                <div className="mt-4 flex items-center justify-center gap-2">
                  <button
                    type="button"
                    onClick={() => archiveRef.current?.click()}
                    className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-btn border border-strong text-xs text-content-secondary hover:bg-inset cursor-pointer"
                  >
                    <FileArchive size={11} />
                    {t('skill_upload_pick_archive')}
                  </button>
                  <button
                    type="button"
                    onClick={() => folderRef.current?.click()}
                    className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-btn border border-strong text-xs text-content-secondary hover:bg-inset cursor-pointer"
                  >
                    <FolderOpen size={11} />
                    {t('skill_upload_pick_folder')}
                  </button>
                </div>
              </div>

              {(archive || folder.length > 0) && (
                <div className="mt-3 flex items-center gap-2 px-3 py-2 rounded-btn border border-default bg-inset">
                  {archive ? (
                    <FileArchive size={12} className="text-content-tertiary" />
                  ) : (
                    <FolderOpen size={12} className="text-content-tertiary" />
                  )}
                  <span className="flex-1 min-w-0 text-xs font-mono text-content truncate">
                    {archive
                      ? `${archive.name} · ${formatSkillFileSize(archive.size)}`
                      : tf('skill_upload_folder_files', {
                          root: (folder[0].webkitRelativePath || folder[0].name).split('/')[0],
                          count: folder.length,
                        })}
                  </span>
                  <button
                    type="button"
                    onClick={() => {
                      setArchive(null)
                      setFolder([])
                    }}
                    className="text-content-tertiary hover:text-content cursor-pointer"
                  >
                    <X size={12} />
                  </button>
                </div>
              )}

              <p className="mt-3 text-xs text-content-tertiary">{t('skill_upload_hint')}</p>

              <input
                ref={archiveRef}
                type="file"
                accept=".zip,.tgz,.gz,.tar"
                className="hidden"
                onChange={(e) => {
                  const file = (e.target.files || [])[0]
                  e.target.value = ''
                  if (file) pickArchive(file)
                }}
              />
              <input
                ref={folderRef}
                type="file"
                multiple
                {...FOLDER_INPUT_PROPS}
                className="hidden"
                onChange={(e) => {
                  const picked = Array.from(e.target.files || [])
                  e.target.value = ''
                  if (picked.length) pickFolder(picked)
                }}
              />
            </div>
          )}

          {error && <p className="mt-3 text-xs text-danger break-all">{error}</p>}
        </div>

        <div className="flex justify-end gap-2 px-5 py-4 border-t border-subtle">
          <button
            type="button"
            disabled={busy}
            onClick={onClose}
            className="px-4 py-2 rounded-btn border border-strong text-sm text-content-secondary hover:bg-inset disabled:opacity-50 cursor-pointer"
          >
            {t('cancel')}
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={submit}
            className="inline-flex items-center gap-1.5 px-4 py-2 rounded-btn bg-accent text-white text-sm font-medium hover:opacity-90 disabled:opacity-50 cursor-pointer"
          >
            {busy && <Loader2 size={13} className="animate-spin" />}
            {t(mode === 'upload' ? 'skill_upload_submit' : 'skill_new_submit')}
          </button>
        </div>
      </div>
    </div>
  )
}

const Section: React.FC<{ title: string; count: number; children: React.ReactNode }> = ({ title, count, children }) => (
  <div>
    <div className="flex items-center gap-2 mb-3">
      <span className="text-xs font-semibold uppercase tracking-wider text-content-tertiary">{title}</span>
      {count > 0 && (
        <span className="px-1.5 py-0.5 rounded-full text-xs bg-inset-2 text-content-tertiary min-w-[20px] text-center">{count}</span>
      )}
    </div>
    {children}
  </div>
)

const Empty: React.FC<{ text: string }> = ({ text }) => (
  <p className="text-sm text-content-tertiary py-2">{text}</p>
)

export default SkillsPage
