import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  Loader2,
  Search,
  FileText,
  ChevronRight,
  ChevronDown,
  MessageSquarePlus,
  Network,
  Files,
  Plus,
  FolderPlus,
  FilePlus2,
  Upload,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { t, getLang } from '../i18n'
import apiClient from '../api/client'
import type {
  KnowledgeDir,
  KnowledgeFile,
  KnowledgeList,
  KnowledgeGraph as KnowledgeGraphData,
} from '../types'
import Markdown from '../components/Markdown'
import KnowledgeGraph from '../components/KnowledgeGraph'

interface KnowledgePageProps {
  baseUrl: string
}

type Tab = 'docs' | 'graph'

const KNOWLEDGE_IMPORT_MAX_FILES = 100
const KNOWLEDGE_IMPORT_MAX_FILE_SIZE = 10 * 1024 * 1024
const KNOWLEDGE_IMPORT_MAX_TOTAL_SIZE = 200 * 1024 * 1024

// t() with simple {placeholder} interpolation.
const tf = (key: string, vars: Record<string, string | number>): string => {
  let out = t(key)
  for (const [k, v] of Object.entries(vars)) out = out.replace(`{${k}}`, String(v))
  return out
}

const formatSize = (bytes: number): string => {
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB'
}

// The viewer already shows the doc title above the body, so a leading `# H1`
// that repeats it looks duplicated. Drop that first H1 (and any blank lines
// right after it) when it matches the title; leave the body untouched otherwise.
function stripDuplicateH1(content: string, title: string): string {
  if (!content) return content
  const norm = (s: string) => s.trim().toLowerCase()
  // Skip a leading blank/whitespace region, then match the first `# heading`.
  const m = content.match(/^\s*#\s+(.+?)\s*(?:\r?\n|$)/)
  if (!m) return content
  if (norm(m[1]) !== norm(title)) return content
  return content.slice(m[0].length).replace(/^\s*\r?\n/, '')
}

// Flatten the tree into category paths (for destination selectors).
function categoryPaths(dirs: KnowledgeDir[], parent = ''): string[] {
  const paths: string[] = []
  for (const dir of dirs || []) {
    const path = parent ? `${parent}/${dir.dir}` : dir.dir
    paths.push(path, ...categoryPaths(dir.children || [], path))
  }
  return paths
}

// Validate a batch of files chosen for import. Returns an error message or ''.
function validateImportFiles(files: File[]): string {
  if (!files.length) return t('knowledge_import_choose_files')
  if (files.length > KNOWLEDGE_IMPORT_MAX_FILES) {
    return tf('knowledge_import_too_many', { max: KNOWLEDGE_IMPORT_MAX_FILES })
  }
  let total = 0
  for (const file of files) {
    total += file.size || 0
    if ((file.size || 0) > KNOWLEDGE_IMPORT_MAX_FILE_SIZE) {
      return tf('knowledge_import_file_too_large', { name: file.name })
    }
  }
  if (total > KNOWLEDGE_IMPORT_MAX_TOTAL_SIZE) return t('knowledge_import_total_too_large')
  return ''
}

// ---- Dialog model ----------------------------------------------------------

interface DialogState {
  kind: 'category' | 'doc-pick-category' | 'document' | 'import'
  category?: string
  files?: File[]
}

// Find the first document (root files first, then a DFS over the tree).
function firstFile(list: KnowledgeList): { path: string; title: string } | null {
  const root = list.root_files?.[0]
  if (root) return { path: root.name, title: root.title || root.name }
  const walk = (dir: KnowledgeDir, prefix: string): { path: string; title: string } | null => {
    const dirPath = prefix ? `${prefix}/${dir.dir}` : dir.dir
    const f = dir.files[0]
    if (f) return { path: `${dirPath}/${f.name}`, title: f.title || f.name }
    for (const c of dir.children) {
      const hit = walk(c, dirPath)
      if (hit) return hit
    }
    return null
  }
  for (const d of list.tree || []) {
    const hit = walk(d, '')
    if (hit) return hit
  }
  return null
}

// Find a document by its bare filename anywhere in the tree (root files first,
// then a DFS). Used to resolve relative `../foo.md` links from index docs.
function findFileByName(list: KnowledgeList, filename: string): { path: string; title: string } | null {
  for (const f of list.root_files || []) {
    if (f.name === filename) return { path: f.name, title: f.title || f.name }
  }
  const walk = (dir: KnowledgeDir, prefix: string): { path: string; title: string } | null => {
    const dirPath = prefix ? `${prefix}/${dir.dir}` : dir.dir
    for (const f of dir.files) {
      if (f.name === filename) return { path: `${dirPath}/${f.name}`, title: f.title || f.name }
    }
    for (const c of dir.children) {
      const hit = walk(c, dirPath)
      if (hit) return hit
    }
    return null
  }
  for (const d of list.tree || []) {
    const hit = walk(d, '')
    if (hit) return hit
  }
  return null
}

// Resolve a relative `.md` link (from a document body) into a knowledge path.
// Supports `knowledge/…/x.md`, `category/x.md`, and bare/relative `../x.md`
// (matched by filename).
function resolveKnowledgeLink(list: KnowledgeList, href: string): { path: string; title: string } | null {
  const clean = href.split('#')[0].split('?')[0]
  if (!clean.endsWith('.md')) return null
  if (clean.startsWith('knowledge/')) {
    const path = clean.replace(/^knowledge\//, '')
    return { path, title: findTitle(list, path) }
  }
  if (/^[a-z0-9_-]+\/[a-z0-9_.-]+\.md$/i.test(clean) && !clean.startsWith('/') && !clean.startsWith('.')) {
    return { path: clean, title: findTitle(list, clean) }
  }
  // Relative/other path: fall back to matching by filename.
  const filename = clean.split('/').pop() || clean
  return findFileByName(list, filename)
}

// Resolve a document's display title from its path, falling back to the stem.
function findTitle(list: KnowledgeList, path: string): string {
  const fallback = path.split('/').pop()?.replace(/\.md$/i, '') || path
  for (const f of list.root_files || []) {
    if (f.name === path) return f.title || fallback
  }
  const walk = (dir: KnowledgeDir, prefix: string): string | null => {
    const dirPath = prefix ? `${prefix}/${dir.dir}` : dir.dir
    for (const f of dir.files) {
      if (`${dirPath}/${f.name}` === path) return f.title || fallback
    }
    for (const c of dir.children) {
      const hit = walk(c, dirPath)
      if (hit) return hit
    }
    return null
  }
  for (const d of list.tree || []) {
    const hit = walk(d, '')
    if (hit) return hit
  }
  return fallback
}

const KnowledgePage: React.FC<KnowledgePageProps> = ({ baseUrl }) => {
  const navigate = useNavigate()
  const [tab, setTab] = useState<Tab>('docs')
  const [data, setData] = useState<KnowledgeList | null>(null)
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')

  const [activePath, setActivePath] = useState<string | null>(null)
  const [docTitle, setDocTitle] = useState('')
  const [content, setContent] = useState('')
  // Absolute dir of the open doc, for resolving doc-relative image srcs.
  const [docDir, setDocDir] = useState('')
  const [docLoading, setDocLoading] = useState(false)

  const [graph, setGraph] = useState<KnowledgeGraphData | null>(null)
  const [graphLoading, setGraphLoading] = useState(false)

  // Management UI state.
  const [menuOpen, setMenuOpen] = useState(false)
  const [dialog, setDialog] = useState<DialogState | null>(null)
  const [status, setStatus] = useState<{ text: string; error: boolean } | null>(null)
  const [dragOver, setDragOver] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const statusTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  const showStatus = useCallback((text: string, error = false, sticky = false) => {
    if (statusTimer.current) clearTimeout(statusTimer.current)
    setStatus({ text, error })
    if (!sticky) {
      statusTimer.current = setTimeout(() => setStatus(null), 4000)
    }
  }, [])

  const openDoc = useCallback(async (path: string, title: string) => {
    setActivePath(path)
    setDocTitle(title)
    setDocLoading(true)
    setContent('')
    setDocDir('')
    try {
      const res = await apiClient.readKnowledge(path)
      setContent(stripDuplicateH1(res.content || '', title))
      setDocDir(res.dir || '')
    } catch {
      setContent(`> ${t('knowledge_doc_load_error')}`)
    } finally {
      setDocLoading(false)
    }
  }, [])

  // Open an internal knowledge link (relative `.md`) from within a doc body.
  // Falls back silently when the target can't be resolved in the current tree.
  const openInternalLink = useCallback(
    (href: string) => {
      if (!data) return
      const hit = resolveKnowledgeLink(data, href)
      if (hit) void openDoc(hit.path, hit.title)
    },
    [data, openDoc]
  )

  // Reload the tree. When targetPath is given, open it; otherwise keep the
  // currently open doc (or open the first one on the initial load).
  const refresh = useCallback(
    async (targetPath?: string) => {
      try {
        const fresh = await apiClient.getKnowledgeList()
        setData(fresh)
        if (targetPath) {
          void openDoc(targetPath, findTitle(fresh, targetPath))
        } else if (!activePath) {
          const first = firstFile(fresh)
          if (first) void openDoc(first.path, first.title)
        }
        return fresh
      } catch (e) {
        console.error('Failed to load knowledge:', e)
        return null
      }
    },
    [openDoc, activePath]
  )

  useEffect(() => {
    apiClient.setBaseUrl(baseUrl)
    let cancelled = false
    ;(async () => {
      setLoading(true)
      try {
        const fresh = await apiClient.getKnowledgeList()
        if (cancelled) return
        setData(fresh)
        const first = firstFile(fresh)
        if (first) void openDoc(first.path, first.title)
      } catch (e) {
        console.error('Failed to load knowledge:', e)
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
    // Only run on baseUrl change (initial mount). refresh() handles later reloads.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [baseUrl])

  const loadGraph = useCallback(async () => {
    if (graph) return
    setGraphLoading(true)
    try {
      setGraph(await apiClient.getKnowledgeGraph())
    } catch (e) {
      console.error('Failed to load graph:', e)
      setGraph({ nodes: [], links: [] })
    } finally {
      setGraphLoading(false)
    }
  }, [graph])

  const switchTab = (next: Tab) => {
    setTab(next)
    if (next === 'graph') void loadGraph()
  }

  // Jump from a graph node to its document.
  const onGraphSelect = useCallback(
    (id: string, label: string) => {
      setTab('docs')
      void openDoc(id, label)
    },
    [openDoc]
  )

  // ---- Management actions --------------------------------------------------

  const categories = useMemo(() => categoryPaths(data?.tree || []), [data])

  const createCategory = useCallback(
    async (path: string): Promise<string | null> => {
      showStatus(t('knowledge_working'), false, true)
      try {
        const res = await apiClient.knowledgeAction({ action: 'create_category', payload: { path } })
        if (res.status !== 'success') {
          showStatus((res.message as string) || t('knowledge_request_failed'), true)
          return null
        }
        showStatus(t('knowledge_category_created'))
        await refresh()
        return path
      } catch {
        showStatus(t('knowledge_request_failed'), true)
        return null
      }
    },
    [refresh, showStatus]
  )

  const createDocument = useCallback(
    async (path: string, content: string): Promise<string | null> => {
      showStatus(t('knowledge_working'), false, true)
      try {
        const res = await apiClient.knowledgeAction({
          action: 'create_document',
          payload: { path, content, overwrite: false },
        })
        if (res.status !== 'success') {
          showStatus((res.message as string) || t('knowledge_request_failed'), true)
          return null
        }
        const created = ((res.payload as { path?: string })?.path) || path
        showStatus(t('knowledge_document_created'))
        await refresh(created)
        return created
      } catch {
        showStatus(t('knowledge_request_failed'), true)
        return null
      }
    },
    [refresh, showStatus]
  )

  const importDocuments = useCallback(
    async (files: File[], targetCategory: string): Promise<boolean> => {
      const err = validateImportFiles(files)
      if (err) {
        showStatus(err, true)
        return false
      }
      const supported = files.filter((f) => /\.(md|txt)$/i.test(f.name || ''))
      if (!supported.length) {
        showStatus(t('knowledge_import_choose_files'), true)
        return false
      }
      showStatus(t('knowledge_importing'), false, true)
      try {
        const res = await apiClient.importKnowledge(supported, targetCategory)
        if (res.status !== 'success') {
          showStatus(res.message || t('knowledge_import_failed'), true)
          await refresh()
          return false
        }
        const p = res.payload
        showStatus(
          tf('knowledge_import_result', {
            imported: p?.imported ?? 0,
            skipped: p?.skipped ?? 0,
            failed: p?.failed ?? 0,
          })
        )
        const first = (p?.results || []).find((r) => r.status === 'imported')
        await refresh(first?.path)
        return true
      } catch {
        showStatus(t('knowledge_import_failed'), true)
        return false
      }
    },
    [refresh, showStatus]
  )

  // Open the import dialog after validating the chosen files.
  const startImport = useCallback(
    (files: File[]) => {
      const err = validateImportFiles(files)
      if (err) {
        showStatus(err, true)
        return
      }
      setDialog({ kind: 'import', files })
    },
    [showStatus]
  )

  const onFilesPicked = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const files = Array.from(e.target.files || [])
      e.target.value = ''
      if (files.length) startImport(files)
    },
    [startImport]
  )

  const totalPages = data?.stats?.pages ?? 0
  const statsLabel = useMemo(() => {
    if (!data) return ''
    return t('knowledge_stats')
      .replace('{pages}', String(data.stats?.pages ?? 0))
      .replace('{size}', formatSize(data.stats?.size ?? 0))
  }, [data])

  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center text-content-tertiary">
        <Loader2 size={18} className="animate-spin mr-2" />
        {t('knowledge_loading')}
      </div>
    )
  }

  const isEmpty = !data || totalPages === 0

  if (isEmpty) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center px-6 text-center">
        <div className="w-14 h-14 rounded-2xl bg-accent-soft text-accent flex items-center justify-center mb-5">
          <Files size={26} />
        </div>
        <h2 className="text-lg font-semibold text-content mb-2">
          {data?.enabled === false ? t('knowledge_disabled') : t('knowledge_empty')}
        </h2>
        <p className="text-sm text-content-tertiary max-w-md mb-6">{t('knowledge_empty_guide')}</p>
        <button
          onClick={() => navigate('/')}
          className="inline-flex items-center gap-2 px-4 py-2 rounded-btn bg-accent text-accent-contrast hover:bg-accent-hover text-sm font-medium cursor-pointer transition-colors"
        >
          <MessageSquarePlus size={15} />
          {t('knowledge_go_chat')}
        </button>
      </div>
    )
  }

  return (
    <div className="flex-1 flex flex-col min-h-0">
      {/* Header */}
      <div className="flex items-center justify-between px-6 pt-5 pb-3 flex-shrink-0">
        <div>
          <h2 className="text-xl font-bold text-content">{t('knowledge_title')}</h2>
          <p className="text-xs text-content-tertiary mt-1">{statsLabel}</p>
        </div>
        <div className="flex items-center gap-2">
          {status && (
            <span
              className={`text-xs max-w-[260px] truncate ${
                status.error ? 'text-danger' : 'text-content-tertiary'
              }`}
              title={status.text}
            >
              {status.text}
            </span>
          )}
          <div className="flex items-center gap-1 bg-inset rounded-btn p-0.5">
            <TabBtn icon={Files} label={t('knowledge_tab_docs')} active={tab === 'docs'} onClick={() => switchTab('docs')} />
            <TabBtn
              icon={Network}
              label={t('knowledge_tab_graph')}
              active={tab === 'graph'}
              onClick={() => switchTab('graph')}
            />
          </div>
          <NewMenu
            open={menuOpen}
            setOpen={setMenuOpen}
            onCreateCategory={() => setDialog({ kind: 'category' })}
            onCreateDocument={() => {
              if (!categories.length) {
                showStatus(t('knowledge_need_category'), true)
                return
              }
              setDialog({ kind: 'doc-pick-category' })
            }}
            onImport={() => fileInputRef.current?.click()}
          />
        </div>
        <input
          ref={fileInputRef}
          type="file"
          multiple
          accept=".md,.txt,text/markdown,text/plain"
          className="hidden"
          onChange={onFilesPicked}
        />
      </div>

      {tab === 'docs' ? (
        <div
          className="flex-1 flex min-h-0 border-t border-default relative"
          onDragEnter={(e) => {
            if (e.dataTransfer?.types?.includes('Files')) {
              e.preventDefault()
              setDragOver(true)
            }
          }}
          onDragOver={(e) => {
            if (e.dataTransfer?.types?.includes('Files')) e.preventDefault()
          }}
          onDragLeave={(e) => {
            // Only clear when leaving the panel, not its children.
            if (e.currentTarget === e.target) setDragOver(false)
          }}
          onDrop={(e) => {
            e.preventDefault()
            setDragOver(false)
            const files = Array.from(e.dataTransfer?.files || [])
            if (files.length) startImport(files)
          }}
        >
          {dragOver && (
            <div className="absolute inset-0 z-30 flex items-center justify-center bg-accent-soft/80 border-2 border-dashed border-accent rounded-lg m-2 pointer-events-none">
              <div className="flex flex-col items-center gap-2 text-accent">
                <Upload size={28} />
                <p className="text-sm font-medium">{t('knowledge_drop_hint')}</p>
              </div>
            </div>
          )}
          {/* Tree sidebar */}
          <div className="w-72 flex-shrink-0 flex flex-col border-r border-default min-h-0">
            <div className="p-3 flex-shrink-0">
              <div className="relative">
                <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-content-tertiary" />
                <input
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  placeholder={t('knowledge_search')}
                  className="w-full pl-8 pr-3 py-2 rounded-btn border border-strong bg-inset text-sm text-content placeholder:text-content-tertiary focus:outline-none focus:border-accent transition-colors"
                />
              </div>
            </div>
            <div className="flex-1 overflow-y-auto px-2 pb-3">
              <Tree
                data={data}
                search={search.trim().toLowerCase()}
                activePath={activePath}
                onOpen={openDoc}
              />
            </div>
          </div>

          {/* Document viewer */}
          <div className="flex-1 min-w-0 overflow-y-auto">
            {!activePath ? (
              <div className="h-full flex flex-col items-center justify-center text-content-tertiary">
                <FileText size={28} className="mb-3 opacity-50" />
                <p className="text-sm">{t('knowledge_select_hint')}</p>
              </div>
            ) : (
              <div className="max-w-3xl mx-auto px-6 py-6">
                <h1 className="text-lg font-semibold text-content mb-1">{docTitle}</h1>
                <p className="text-xs text-content-tertiary mb-5 font-mono">{activePath}</p>
                {docLoading ? (
                  <div className="flex items-center text-content-tertiary py-8">
                    <Loader2 size={16} className="animate-spin mr-2" />
                  </div>
                ) : (
                  <Markdown content={content} onInternalLink={openInternalLink} imageBaseDir={docDir} />
                )}
              </div>
            )}
          </div>
        </div>
      ) : (
        <div className="flex-1 min-h-0 border-t border-default relative">
          {graphLoading ? (
            <div className="absolute inset-0 flex items-center justify-center text-content-tertiary">
              <Loader2 size={18} className="animate-spin mr-2" />
            </div>
          ) : graph && graph.nodes.length > 0 ? (
            <KnowledgeGraph data={graph} onSelect={onGraphSelect} />
          ) : (
            <div className="absolute inset-0 flex items-center justify-center text-content-tertiary text-sm">
              {t('knowledge_graph_empty')}
            </div>
          )}
        </div>
      )}

      {dialog && (
        <KnowledgeDialog
          state={dialog}
          categories={categories}
          onClose={() => setDialog(null)}
          onCreateCategory={createCategory}
          onPickDocCategory={(category) => setDialog({ kind: 'document', category })}
          onCreateDocument={createDocument}
          onImport={importDocuments}
        />
      )}
    </div>
  )
}

// ---- New menu --------------------------------------------------------------

const NewMenu: React.FC<{
  open: boolean
  setOpen: (v: boolean) => void
  onCreateCategory: () => void
  onCreateDocument: () => void
  onImport: () => void
}> = ({ open, setOpen, onCreateCategory, onCreateDocument, onImport }) => {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    const onClickOutside = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onClickOutside)
    return () => document.removeEventListener('mousedown', onClickOutside)
  }, [open, setOpen])

  const pick = (fn: () => void) => {
    setOpen(false)
    fn()
  }

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen(!open)}
        className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-btn bg-accent text-accent-contrast hover:bg-accent-hover text-sm font-medium cursor-pointer transition-colors"
      >
        <Plus size={14} />
        {t('knowledge_new')}
        <ChevronDown size={12} className="opacity-80" />
      </button>
      {open && (
        <div className="absolute right-0 mt-1.5 w-44 z-50 bg-surface border border-default rounded-lg shadow-lg py-1">
          <MenuItem icon={FolderPlus} label={t('knowledge_new_category')} onClick={() => pick(onCreateCategory)} />
          <MenuItem icon={FilePlus2} label={t('knowledge_new_document')} onClick={() => pick(onCreateDocument)} />
          <MenuItem icon={Upload} label={t('knowledge_import_documents')} onClick={() => pick(onImport)} />
        </div>
      )}
    </div>
  )
}

const MenuItem: React.FC<{ icon: LucideIcon; label: string; onClick: () => void }> = ({
  icon: Icon,
  label,
  onClick,
}) => (
  <button
    onClick={onClick}
    className="w-full flex items-center gap-2.5 px-3 py-2 text-sm text-content-secondary hover:bg-surface-2 cursor-pointer transition-colors text-left"
  >
    <Icon size={14} className="opacity-70 flex-shrink-0" />
    {label}
  </button>
)

// ---- Dialog ----------------------------------------------------------------

function templateFor(filename: string): string {
  const title = (filename || 'untitled').replace(/\.md$/i, '')
  return getLang() === 'zh'
    ? `# ${title}\n\n## 摘要\n\n\n## 关键点\n\n- \n\n## 参考\n\n`
    : `# ${title}\n\n## Summary\n\n\n## Key points\n\n- \n\n## References\n\n`
}

const KnowledgeDialog: React.FC<{
  state: DialogState
  categories: string[]
  onClose: () => void
  onCreateCategory: (path: string) => Promise<string | null>
  onPickDocCategory: (category: string) => void
  onCreateDocument: (path: string, content: string) => Promise<string | null>
  onImport: (files: File[], target: string) => Promise<boolean>
}> = ({ state, categories, onClose, onCreateCategory, onPickDocCategory, onCreateDocument, onImport }) => {
  const [categoryInput, setCategoryInput] = useState('')
  const [selected, setSelected] = useState(categories[0] || '')
  const [filename, setFilename] = useState('')
  const [contentInput, setContentInput] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const submit = async () => {
    setError('')
    if (state.kind === 'category') {
      const path = categoryInput.trim()
      if (!path) return setError(t('knowledge_field_required'))
      setBusy(true)
      const ok = await onCreateCategory(path)
      setBusy(false)
      if (ok !== null) onClose()
      return
    }
    if (state.kind === 'doc-pick-category') {
      if (!selected) return setError(t('knowledge_field_required'))
      onPickDocCategory(selected)
      return
    }
    if (state.kind === 'document') {
      const name = filename.trim()
      if (!name) return setError(t('knowledge_doc_filename_required'))
      if (/\.[^.]+$/i.test(name) && !/\.md$/i.test(name)) return setError(t('knowledge_doc_must_md'))
      if (!contentInput.trim()) return setError(t('knowledge_doc_content_required'))
      if (new Blob([contentInput]).size > KNOWLEDGE_IMPORT_MAX_FILE_SIZE) {
        return setError(t('knowledge_doc_content_too_large'))
      }
      const safeName = name.endsWith('.md') ? name : `${name}.md`
      setBusy(true)
      const ok = await onCreateDocument(`${state.category}/${safeName}`, contentInput)
      setBusy(false)
      if (ok !== null) onClose()
      return
    }
    if (state.kind === 'import') {
      if (!selected) return setError(t('knowledge_field_required'))
      setBusy(true)
      const ok = await onImport(state.files || [], selected)
      setBusy(false)
      if (ok) onClose()
      return
    }
  }

  const titleMap: Record<DialogState['kind'], string> = {
    category: t('knowledge_new_category'),
    'doc-pick-category': t('knowledge_new_document'),
    document: t('knowledge_new_document'),
    import: t('knowledge_import_documents'),
  }

  const noCategory = (state.kind === 'doc-pick-category' || state.kind === 'import') && !categories.length

  return (
    <div className="fixed inset-0 z-[70] flex items-center justify-center bg-black/40 p-4" onMouseDown={onClose}>
      <div
        className="w-full max-w-lg bg-surface border border-default rounded-xl shadow-xl p-5"
        onMouseDown={(e) => e.stopPropagation()}
      >
        <h3 className="text-base font-semibold text-content mb-1">{titleMap[state.kind]}</h3>

        {state.kind === 'category' && (
          <>
            <p className="text-xs text-content-tertiary mb-4">{t('knowledge_category_subtitle')}</p>
            <label className="block text-sm text-content-secondary mb-1.5">{t('knowledge_category_label')}</label>
            <input
              autoFocus
              value={categoryInput}
              onChange={(e) => setCategoryInput(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && submit()}
              placeholder="research/ai"
              className="w-full px-3 py-2 rounded-btn border border-strong bg-inset text-sm text-content placeholder:text-content-tertiary focus:outline-none focus:border-accent transition-colors"
            />
            <p className="text-xs text-content-tertiary mt-1.5">{t('knowledge_category_hint')}</p>
          </>
        )}

        {state.kind === 'doc-pick-category' && (
          <>
            <p className="text-xs text-content-tertiary mb-4">{t('knowledge_doc_choose_category')}</p>
            <label className="block text-sm text-content-secondary mb-1.5">{t('knowledge_destination')}</label>
            <CategorySelect value={selected} options={categories} onChange={setSelected} />
          </>
        )}

        {state.kind === 'document' && (
          <>
            <p className="text-xs text-content-tertiary mb-4">
              {tf('knowledge_doc_save_to', { category: state.category || '' })}
            </p>
            <label className="block text-sm text-content-secondary mb-1.5">{t('knowledge_doc_filename')}</label>
            <input
              autoFocus
              value={filename}
              onChange={(e) => setFilename(e.target.value)}
              placeholder="my-note.md"
              className="w-full px-3 py-2 rounded-btn border border-strong bg-inset text-sm text-content placeholder:text-content-tertiary focus:outline-none focus:border-accent transition-colors mb-3"
            />
            <div className="flex items-center justify-between mb-1.5">
              <label className="text-sm text-content-secondary">{t('knowledge_doc_content')}</label>
              <button
                onClick={() => {
                  if (!contentInput.trim()) setContentInput(templateFor(filename))
                }}
                className="text-xs text-accent hover:underline cursor-pointer"
              >
                {t('knowledge_doc_insert_template')}
              </button>
            </div>
            <textarea
              value={contentInput}
              onChange={(e) => setContentInput(e.target.value)}
              rows={10}
              className="w-full px-3 py-2 rounded-btn border border-strong bg-inset text-sm text-content placeholder:text-content-tertiary focus:outline-none focus:border-accent transition-colors font-mono resize-y"
            />
          </>
        )}

        {state.kind === 'import' && (
          <>
            <p className="text-xs text-content-tertiary mb-4">
              {tf('knowledge_import_selected', { count: state.files?.length ?? 0 })}
            </p>
            <label className="block text-sm text-content-secondary mb-1.5">{t('knowledge_destination')}</label>
            <CategorySelect value={selected} options={categories} onChange={setSelected} />
            <p className="text-xs text-content-tertiary mt-1.5">
              {categories.length ? t('knowledge_import_hint') : t('knowledge_import_need_category')}
            </p>
          </>
        )}

        {error && <p className="text-xs text-danger mt-3">{error}</p>}

        <div className="flex justify-end gap-2 mt-5">
          <button
            onClick={onClose}
            className="px-4 py-2 rounded-btn border border-strong text-content-secondary hover:bg-surface-2 text-sm font-medium cursor-pointer transition-colors"
          >
            {t('knowledge_dialog_cancel')}
          </button>
          <button
            onClick={submit}
            disabled={busy || noCategory}
            className="px-4 py-2 rounded-btn bg-accent text-accent-contrast hover:bg-accent-hover text-sm font-medium cursor-pointer transition-colors disabled:opacity-50 disabled:cursor-not-allowed inline-flex items-center gap-1.5"
          >
            {busy && <Loader2 size={14} className="animate-spin" />}
            {t('knowledge_dialog_confirm')}
          </button>
        </div>
      </div>
    </div>
  )
}

// Custom dropdown: keeps the arrow / menu styling consistent with the rest of
// the desktop UI (a native <select> renders an OS arrow we can't space out).
const CategorySelect: React.FC<{ value: string; options: string[]; onChange: (v: string) => void }> = ({
  value,
  options,
  onChange,
}) => {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const onClickOutside = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onClickOutside)
    return () => document.removeEventListener('mousedown', onClickOutside)
  }, [open])

  const disabled = !options.length

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        disabled={disabled}
        onClick={() => setOpen((v) => !v)}
        className={`w-full flex items-center justify-between gap-2 px-3 py-2 rounded-btn border text-sm text-content transition-colors cursor-pointer ${
          open ? 'border-accent' : 'border-strong'
        } bg-inset hover:border-accent/70 disabled:opacity-50 disabled:cursor-not-allowed`}
      >
        <span className="truncate">{value || '--'}</span>
        <ChevronDown
          size={14}
          className={`flex-shrink-0 text-content-tertiary transition-transform ${open ? 'rotate-180' : ''}`}
        />
      </button>
      {open && (
        <div className="absolute left-0 right-0 top-full mt-1 z-50 max-h-60 overflow-y-auto bg-surface border border-default rounded-lg shadow-lg p-1">
          {options.map((opt) => (
            <button
              key={opt}
              type="button"
              onClick={() => {
                onChange(opt)
                setOpen(false)
              }}
              className={`w-full text-left px-2.5 py-1.5 rounded-md text-sm cursor-pointer transition-colors truncate ${
                opt === value ? 'bg-accent-soft text-accent' : 'text-content-secondary hover:bg-surface-2'
              }`}
            >
              {opt}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

const TabBtn: React.FC<{
  icon: LucideIcon
  label: string
  active: boolean
  onClick: () => void
}> = ({ icon: Icon, label, active, onClick }) => (
  <button
    onClick={onClick}
    className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-[6px] text-sm font-medium cursor-pointer transition-colors ${
      active ? 'bg-surface text-content shadow-sm' : 'text-content-tertiary hover:text-content-secondary'
    }`}
  >
    <Icon size={14} />
    {label}
  </button>
)

// ---- Tree rendering --------------------------------------------------------

const Tree: React.FC<{
  data: KnowledgeList
  search: string
  activePath: string | null
  onOpen: (path: string, title: string) => void
}> = ({ data, search, activePath, onOpen }) => {
  const matches = (f: KnowledgeFile) => !search || f.title.toLowerCase().includes(search) || f.name.toLowerCase().includes(search)

  return (
    <div className="space-y-0.5">
      {(data.root_files || []).filter(matches).map((f) => (
        <FileLeaf
          key={f.name}
          path={f.name}
          title={f.title || f.name}
          active={activePath === f.name}
          onOpen={onOpen}
        />
      ))}
      {(data.tree || []).map((dir) => (
        <DirNode key={dir.dir} dir={dir} prefix="" search={search} activePath={activePath} onOpen={onOpen} />
      ))}
    </div>
  )
}

// Count files in a dir subtree that match the search.
function countMatches(dir: KnowledgeDir, search: string): number {
  const own = dir.files.filter(
    (f) => !search || f.title.toLowerCase().includes(search) || f.name.toLowerCase().includes(search)
  ).length
  return own + dir.children.reduce((acc, c) => acc + countMatches(c, search), 0)
}

const DirNode: React.FC<{
  dir: KnowledgeDir
  prefix: string
  search: string
  activePath: string | null
  onOpen: (path: string, title: string) => void
}> = ({ dir, prefix, search, activePath, onOpen }) => {
  const dirPath = prefix ? `${prefix}/${dir.dir}` : dir.dir
  const [open, setOpen] = useState(true)
  const matchCount = search ? countMatches(dir, search) : dir.files.length + dir.children.length
  if (search && matchCount === 0) return null

  const visibleFiles = dir.files.filter(
    (f) => !search || f.title.toLowerCase().includes(search) || f.name.toLowerCase().includes(search)
  )
  const expanded = open || !!search

  return (
    <div>
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center gap-1 px-2 py-1.5 rounded-btn text-sm text-content-secondary hover:bg-surface-2 cursor-pointer transition-colors"
      >
        {expanded ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
        <span className="truncate font-medium">{dir.dir}</span>
        <span className="ml-auto text-xs text-content-tertiary">{matchCount}</span>
      </button>
      {expanded && (
        <div className="ml-3 border-l border-default pl-1.5 space-y-0.5">
          {visibleFiles.map((f) => {
            const fpath = `${dirPath}/${f.name}`
            return (
              <FileLeaf
                key={fpath}
                path={fpath}
                title={f.title || f.name}
                active={activePath === fpath}
                onOpen={onOpen}
              />
            )
          })}
          {dir.children.map((c) => (
            <DirNode
              key={c.dir}
              dir={c}
              prefix={dirPath}
              search={search}
              activePath={activePath}
              onOpen={onOpen}
            />
          ))}
        </div>
      )}
    </div>
  )
}

const FileLeaf: React.FC<{
  path: string
  title: string
  active: boolean
  onOpen: (path: string, title: string) => void
}> = ({ path, title, active, onOpen }) => (
  <button
    onClick={() => onOpen(path, title)}
    className={`w-full flex items-center gap-2 px-2 py-1.5 rounded-btn text-[13px] cursor-pointer transition-colors text-left ${
      active ? 'bg-accent-soft text-accent' : 'text-content-secondary hover:bg-surface-2'
    }`}
  >
    <FileText size={13} className="flex-shrink-0 opacity-70" />
    <span className="truncate">{title}</span>
  </button>
)

export default KnowledgePage
