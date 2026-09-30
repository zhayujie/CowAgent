import React, { useEffect, useRef, useState } from 'react'
import { ArrowLeft, Box, Check, ChevronRight, FileUp, Loader2, PawPrint, ShieldAlert, Store, Upload, Zap } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { t } from '../../i18n'
import apiClient from '../../api/client'
import type { SkillMarketSource, SkillPreviewItem, SkillPreviewResult } from '../../types'
import Markdown from '../../components/Markdown'
import { Btn, Field, Modal, TextInput } from '../settings/primitives'
import { SegTabs } from './SegTabs'
import { parseSkillFrontmatter } from './frontmatter'
import { product } from '@product'

type Tab = 'market' | 'upload'

const uploadOnly = product.skills?.uploadOnly === true
const initialTab: Tab = uploadOnly ? 'upload' : 'market'
type Step = 'input' | 'preview' | 'done'
type UploadFile = { file: File; path: string }

type IconComponent = LucideIcon | React.FC<{ size?: number; className?: string }>

const UPLOAD_MAX_BYTES = 50 * 1024 * 1024

/** lucide dropped its brand icons, so the GitHub mark is drawn here. */
const GithubMark: React.FC<{ size?: number; className?: string }> = ({ size = 14, className }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor" className={className} aria-hidden="true">
    <path d="M12 .5C5.65.5.5 5.65.5 12a11.5 11.5 0 0 0 7.86 10.92c.58.1.79-.25.79-.56v-2c-3.2.7-3.87-1.37-3.87-1.37-.52-1.33-1.28-1.69-1.28-1.69-1.05-.72.08-.7.08-.7 1.16.08 1.77 1.19 1.77 1.19 1.03 1.77 2.7 1.26 3.36.96.1-.75.4-1.26.73-1.55-2.55-.29-5.24-1.28-5.24-5.69 0-1.26.45-2.29 1.19-3.1-.12-.29-.52-1.46.11-3.05 0 0 .97-.31 3.17 1.18a11 11 0 0 1 5.77 0c2.2-1.49 3.17-1.18 3.17-1.18.63 1.59.23 2.76.11 3.05.74.81 1.19 1.84 1.19 3.1 0 4.42-2.7 5.4-5.26 5.68.41.36.78 1.06.78 2.14v3.17c0 .31.21.67.8.56A11.5 11.5 0 0 0 23.5 12C23.5 5.65 18.35.5 12 .5Z" />
  </svg>
)

const SOURCES: Record<
  SkillMarketSource,
  { label: string; icon: IconComponent; valueKey: string; hintKey: string; placeholder: string; link?: string }
> = {
  hub: {
    label: 'Cow Skill Hub',
    icon: Box,
    valueKey: 'skill_value_hub',
    hintKey: 'skill_hint_hub',
    placeholder: 'skill-name',
    link: 'https://skills.cowagent.ai/',
  },
  github: {
    label: 'GitHub',
    icon: GithubMark,
    valueKey: 'skill_value_github',
    hintKey: 'skill_hint_github',
    placeholder: 'https://github.com/owner/repo/tree/main/skills/my-skill',
  },
  clawhub: {
    label: 'ClawHub',
    icon: PawPrint,
    valueKey: 'skill_value_clawhub',
    hintKey: 'skill_hint_clawhub',
    placeholder: 'skill-name',
    link: 'https://clawhub.ai/skills',
  },
}

const SOURCE_LABELS: Record<string, string> = { cowhub: 'Cow Skill Hub', github: 'GitHub', clawhub: 'ClawHub', url: 'URL' }

function sourceLabel(source: string): string {
  if (!source) return ''
  return source === 'local' ? t('skill_source_local') : SOURCE_LABELS[source] || source
}

function formatBytes(bytes: number): string {
  if (!bytes) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB']
  let n = bytes
  let i = 0
  while (n >= 1024 && i < units.length - 1) {
    n /= 1024
    i++
  }
  return `${n >= 10 || i === 0 ? Math.round(n) : n.toFixed(1)} ${units[i]}`
}

/** Walk a drop: plain files, or folders read through the entries API. */
async function collectDropped(dt: DataTransfer): Promise<UploadFile[]> {
  const entries = Array.from(dt.items || [])
    .map((item) => item.webkitGetAsEntry?.())
    .filter((entry): entry is FileSystemEntry => !!entry)
  if (!entries.length) return Array.from(dt.files || []).map((file) => ({ file, path: file.name }))

  const out: UploadFile[] = []
  const readAll = (reader: FileSystemDirectoryReader): Promise<FileSystemEntry[]> =>
    new Promise((resolve) => {
      const acc: FileSystemEntry[] = []
      const next = (): void =>
        reader.readEntries(
          (batch) => {
            if (!batch.length) return resolve(acc)
            acc.push(...batch)
            next()
          },
          () => resolve(acc)
        )
      next()
    })
  const walk = async (entry: FileSystemEntry, prefix: string): Promise<void> => {
    if (entry.isFile) {
      const file = await new Promise<File | null>((resolve) =>
        (entry as FileSystemFileEntry).file(resolve, () => resolve(null))
      )
      if (file) out.push({ file, path: prefix + file.name })
    } else if (entry.isDirectory) {
      const children = await readAll((entry as FileSystemDirectoryEntry).createReader())
      for (const child of children) await walk(child, `${prefix}${entry.name}/`)
    }
  }
  for (const entry of entries) await walk(entry, '')
  return out
}

interface SkillAddModalProps {
  open: boolean
  onClose: () => void
  onInstalled: (names: string[]) => void
}

const SkillAddModal: React.FC<SkillAddModalProps> = ({ open, onClose, onInstalled }) => {
  const [tab, setTab] = useState<Tab>(initialTab)
  const [source, setSource] = useState<SkillMarketSource>('hub')
  const [value, setValue] = useState('')
  const [step, setStep] = useState<Step>('input')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [token, setToken] = useState<string | null>(null)
  const [skills, setSkills] = useState<SkillPreviewItem[]>([])
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [installed, setInstalled] = useState<string[]>([])
  const [dragOver, setDragOver] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)
  const folderRef = useRef<HTMLInputElement>(null)
  // Bumped when a fetch or upload is abandoned, so its late reply is ignored.
  const reqRef = useRef(0)

  useEffect(() => {
    if (!open) return
    setTab(initialTab)
    setSource('hub')
    setValue('')
    setStep('input')
    setBusy(false)
    setError('')
    setToken(null)
    setSkills([])
    setSelected(new Set())
    setInstalled([])
  }, [open])

  const discard = (): void => {
    if (!token) return
    void apiClient.discardSkill(token).catch(() => undefined)
    setToken(null)
  }

  const close = (): void => {
    if (busy) {
      // Installing is quick and not safely interruptible; fetching can hang on the network.
      if (step !== 'input') return
      reqRef.current++
      setBusy(false)
    }
    discard()
    onClose()
  }

  const showPreview = (data: SkillPreviewResult): void => {
    if (data.status !== 'success' || !data.token) throw new Error(data.message || t('skill_install_error'))
    discard()
    const found = data.skills || []
    setToken(data.token)
    setSkills(found)
    setSelected(new Set(found.map((s) => s.name)))
    setStep('preview')
  }

  const run = async (task: () => Promise<void>, onError: (msg: string) => void): Promise<void> => {
    setBusy(true)
    try {
      await task()
    } catch (err) {
      onError((err as Error).message || t('skill_install_error'))
    } finally {
      setBusy(false)
    }
  }

  const stage = (request: () => Promise<SkillPreviewResult>): void => {
    const req = ++reqRef.current
    setError('')
    setBusy(true)
    request()
      .then((data) => {
        if (req !== reqRef.current) {
          if (data.token) void apiClient.discardSkill(data.token).catch(() => undefined)
          return
        }
        showPreview(data)
      })
      .catch((err) => {
        if (req === reqRef.current) setError((err as Error).message || t('skill_install_error'))
      })
      .finally(() => {
        if (req === reqRef.current) setBusy(false)
      })
  }

  const fetchPreview = (): void => {
    const spec = value.trim()
    if (!spec || busy) return
    stage(() => apiClient.previewSkill(source, spec))
  }

  const upload = (files: UploadFile[]): void => {
    if (busy || !files.length) return
    setError('')
    const total = files.reduce((sum, f) => sum + (f.file.size || 0), 0)
    if (total > UPLOAD_MAX_BYTES) {
      setError(t('skill_upload_too_large'))
      return
    }
    stage(() => apiClient.uploadSkill(files))
  }

  const confirm = (): void => {
    if (busy || !token || !selected.size) return
    setError('')
    void run(async () => {
      const res = await apiClient.confirmSkill(token, Array.from(selected))
      if (res.status !== 'success') throw new Error(res.message || t('skill_install_error'))
      setToken(null)
      const names = res.installed || []
      setInstalled(names)
      setStep('done')
      onInstalled(names)
    }, setError)
  }

  const back = (): void => {
    if (busy) return
    discard()
    setSkills([])
    setSelected(new Set())
    setError('')
    setStep('input')
  }

  const toggleSelected = (name: string, on: boolean): void => {
    setSelected((prev) => {
      const next = new Set(prev)
      if (on) next.add(name)
      else next.delete(name)
      return next
    })
  }

  const meta = SOURCES[source]
  const multi = skills.length > 1

  let footer: React.ReactNode
  if (step === 'input') {
    footer = (
      <>
        <Btn onClick={close}>
          {t('mcp_cancel')}
        </Btn>
        {tab === 'market' && (
          <Btn variant="primary" onClick={fetchPreview} disabled={busy || !value.trim()} className="inline-flex items-center gap-1.5">
            {busy && <Loader2 size={13} className="animate-spin" />}
            {t(busy ? 'skill_fetching' : 'skill_fetch')}
          </Btn>
        )}
      </>
    )
  } else if (step === 'preview') {
    footer = (
      <>
        <button
          type="button"
          onClick={back}
          disabled={busy}
          className="inline-flex items-center gap-1.5 px-3 py-2 rounded-btn text-sm font-medium text-content-tertiary hover:bg-surface-2 cursor-pointer transition-colors disabled:opacity-50"
        >
          <ArrowLeft size={14} />
          {t('skill_back_edit')}
        </button>
        <div className="flex-1" />
        <Btn onClick={close} disabled={busy}>
          {t('mcp_cancel')}
        </Btn>
        <Btn variant="primary" onClick={confirm} disabled={busy || !selected.size} className="inline-flex items-center gap-1.5">
          {busy && <Loader2 size={13} className="animate-spin" />}
          {busy ? t('skill_installing') : t('skill_confirm_install_n').replace('{n}', String(selected.size))}
        </Btn>
      </>
    )
  } else {
    footer = (
      <Btn variant="primary" onClick={onClose}>
        {t('skill_done')}
      </Btn>
    )
  }

  return (
    <Modal open={open} size="lg" title={t('skill_add')} onClose={close} footer={footer}>
      {step === 'input' && (
        <>
          {!uploadOnly && (
            <SegTabs<Tab>
              value={tab}
              onChange={(next) => {
                if (busy) return
                setTab(next)
                setError('')
              }}
              tabs={[
                { value: 'market', label: t('skill_add_tab_market'), icon: Store },
                { value: 'upload', label: t('skill_add_tab_upload'), icon: Upload },
              ]}
            />
          )}
          {tab === 'market' ? (
            <>
              <Field label={t('skill_source')}>
                <div className="grid grid-cols-3 gap-2">
                  {(Object.keys(SOURCES) as SkillMarketSource[]).map((key) => {
                    const { label, icon: Icon } = SOURCES[key]
                    const active = key === source
                    return (
                      <button
                        key={key}
                        type="button"
                        onClick={() => {
                          setSource(key)
                          setError('')
                        }}
                        className={`flex items-center justify-center gap-2 px-2 py-2.5 rounded-btn border text-[13px] font-medium cursor-pointer transition-colors ${
                          active
                            ? 'border-accent bg-accent-soft text-content'
                            : 'border-default text-content-secondary hover:border-strong hover:bg-surface-2'
                        }`}
                      >
                        <Icon size={14} className={active ? 'text-accent' : 'text-content-tertiary'} />
                        {label}
                      </button>
                    )
                  })}
                </div>
              </Field>
              <Field label={t(meta.valueKey)}>
                <TextInput
                  autoFocus
                  value={value}
                  spellCheck={false}
                  placeholder={meta.placeholder}
                  className="font-mono"
                  onChange={(e) => {
                    setValue(e.target.value)
                    setError('')
                  }}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') {
                      e.preventDefault()
                      fetchPreview()
                    }
                  }}
                />
                <p className="text-xs text-content-tertiary mt-1.5">
                  {t(meta.hintKey)}
                  {meta.link && (
                    <>
                      {' '}
                      <a href={meta.link} target="_blank" rel="noopener noreferrer" className="text-accent hover:underline">
                        {meta.link.replace(/^https:\/\/|\/$/g, '')}
                      </a>
                    </>
                  )}
                </p>
              </Field>
            </>
          ) : (
            <div
              onDragEnter={(e) => {
                e.preventDefault()
                if (!busy) setDragOver(true)
              }}
              onDragOver={(e) => e.preventDefault()}
              onDragLeave={() => setDragOver(false)}
              onDrop={(e) => {
                e.preventDefault()
                setDragOver(false)
                if (busy) return
                void collectDropped(e.dataTransfer).then(upload)
              }}
              className={`flex flex-col items-center justify-center px-4 py-8 rounded-card border-[1.5px] border-dashed text-center transition-colors ${
                dragOver ? 'border-accent bg-accent-soft' : 'border-strong bg-inset'
              }`}
            >
              <div className="w-11 h-11 mb-3 rounded-card border border-default bg-surface flex items-center justify-center">
                {busy ? <Loader2 size={18} className="animate-spin text-accent" /> : <FileUp size={18} className="text-content-tertiary" />}
              </div>
              {busy ? (
                <p className="text-sm text-content-secondary">{t('skill_uploading')}</p>
              ) : (
                <p className="text-sm text-content-secondary">
                  {t('skill_upload_drop')}{' '}
                  <button type="button" onClick={() => fileRef.current?.click()} className="text-accent font-medium hover:underline cursor-pointer">
                    {t('skill_upload_pick_file')}
                  </button>
                  <span className="text-content-tertiary mx-1">/</span>
                  <button type="button" onClick={() => folderRef.current?.click()} className="text-accent font-medium hover:underline cursor-pointer">
                    {t('skill_upload_pick_folder')}
                  </button>
                </p>
              )}
              <p className="text-xs text-content-tertiary mt-1.5">{t('skill_upload_types')}</p>
              <input
                ref={fileRef}
                type="file"
                className="hidden"
                accept=".zip,.tar.gz,.tgz,.md"
                onChange={(e) => {
                  const files = Array.from(e.target.files || []).map((file) => ({ file, path: file.name }))
                  e.target.value = ''
                  upload(files)
                }}
              />
              <input
                ref={folderRef}
                type="file"
                className="hidden"
                multiple
                {...({ webkitdirectory: '' } as Record<string, string>)}
                onChange={(e) => {
                  const files = Array.from(e.target.files || []).map((file) => ({
                    file,
                    path: file.webkitRelativePath || file.name,
                  }))
                  e.target.value = ''
                  upload(files)
                }}
              />
            </div>
          )}
          {error && <p className="text-sm text-danger">{error}</p>}
        </>
      )}

      {step === 'preview' && (
        <>
          <div className="flex items-start gap-2.5 px-3.5 py-3 rounded-card border border-amber-500/25 bg-amber-500/10">
            <span className="flex items-center h-5 flex-shrink-0">
              <ShieldAlert size={14} className="text-amber-500" />
            </span>
            <p className="text-xs leading-5 text-amber-800 dark:text-amber-200">{t('skill_preview_warning')}</p>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium text-content">
              {t('skill_preview_found').replace('{n}', String(skills.length))}
            </span>
            {multi && (
              <label className="ml-auto inline-flex items-center gap-1.5 text-xs text-content-tertiary cursor-pointer select-none">
                <input
                  type="checkbox"
                  className="accent-accent cursor-pointer"
                  checked={selected.size === skills.length}
                  onChange={(e) => setSelected(e.target.checked ? new Set(skills.map((s) => s.name)) : new Set())}
                />
                {t('skill_preview_select_all')}
              </label>
            )}
          </div>
          <div className="space-y-3">
            {skills.map((skill) => (
              <PreviewCard
                key={skill.name}
                skill={skill}
                selectable={multi}
                selected={selected.has(skill.name)}
                defaultOpen={!multi}
                onSelect={(on) => toggleSelected(skill.name, on)}
              />
            ))}
          </div>
          {error && <p className="text-sm text-danger">{error}</p>}
        </>
      )}

      {step === 'done' && (
        <div className="py-6 text-center">
          <div className="w-14 h-14 mx-auto mb-4 rounded-2xl bg-accent-soft flex items-center justify-center">
            <Check size={24} className="text-accent" />
          </div>
          <p className="text-base font-semibold text-content">{t('skill_installed_title')}</p>
          <p className="text-sm text-content-tertiary mt-1">
            {t('skill_installed_desc').replace('{n}', String(installed.length))}
          </p>
          <div className="flex flex-wrap justify-center gap-1.5 mt-4">
            {installed.map((name) => {
              const skill = skills.find((s) => s.name === name)
              return (
                <span key={name} className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-btn text-xs bg-inset-2 text-content">
                  <Zap size={11} className="text-accent" />
                  {skill?.display_name || name}
                </span>
              )
            })}
          </div>
        </div>
      )}
    </Modal>
  )
}

const PreviewCard: React.FC<{
  skill: SkillPreviewItem
  selectable: boolean
  selected: boolean
  defaultOpen: boolean
  onSelect: (on: boolean) => void
}> = ({ skill, selectable, selected, defaultOpen, onSelect }) => {
  const [pane, setPane] = useState<'md' | 'files' | null>(defaultOpen ? 'md' : null)
  const title = skill.display_name || skill.name
  const source = sourceLabel(skill.source)
  const { fields, body } = parseSkillFrontmatter(skill.skill_md)
  const toggle = (which: 'md' | 'files'): void => setPane((cur) => (cur === which ? null : which))

  return (
    <div className={`rounded-card border border-default bg-surface overflow-hidden transition-opacity ${selected ? '' : 'opacity-55'}`}>
      <div className="flex items-start gap-3 p-4">
        {selectable && (
          <input
            type="checkbox"
            className="mt-2.5 accent-accent cursor-pointer"
            checked={selected}
            onChange={(e) => onSelect(e.target.checked)}
          />
        )}
        <div className="w-9 h-9 rounded-lg bg-accent-soft flex items-center justify-center flex-shrink-0">
          <Zap size={15} className="text-accent" />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-sm font-medium text-content">{title}</span>
            {title !== skill.name && <span className="text-xs font-mono text-content-tertiary">{skill.name}</span>}
            {skill.exists && (
              <span className="px-1.5 py-0.5 rounded text-[10px] font-medium bg-amber-500/10 text-amber-600 dark:text-amber-400">
                {t('skill_preview_exists')}
              </span>
            )}
          </div>
          <p className="text-xs text-content-tertiary mt-1 line-clamp-3">{skill.description || '--'}</p>
          <div className="flex items-center gap-2.5 mt-2 text-[11px] text-content-tertiary">
            <span>{t('skill_preview_files').replace('{n}', String(skill.file_count))}</span>
            <span className="opacity-40">·</span>
            <span>{formatBytes(skill.size)}</span>
            {source && (
              <>
                <span className="opacity-40">·</span>
                <span>{source}</span>
              </>
            )}
          </div>
          <div className="flex items-center gap-3 mt-2">
            {(['md', 'files'] as const).map((which) => (
              <button
                key={which}
                type="button"
                onClick={() => toggle(which)}
                className="inline-flex items-center gap-1 text-xs text-content-tertiary hover:text-content-secondary cursor-pointer transition-colors"
              >
                <ChevronRight size={11} className={`transition-transform ${pane === which ? 'rotate-90' : ''}`} />
                {which === 'md' ? 'SKILL.md' : t('skill_preview_show_files')}
              </button>
            ))}
          </div>
        </div>
      </div>
      {pane === 'md' && (
        <div className="max-h-80 overflow-y-auto px-4 py-3.5 border-t border-subtle bg-inset text-[13px]">
          {!skill.has_skill_md ? (
            <p className="text-xs text-content-tertiary">{t('skill_preview_no_md')}</p>
          ) : (
            <>
              {fields.length > 0 && (
                <div className="mb-3 pb-3 border-b border-subtle space-y-1">
                  {fields.map(([key, val]) => (
                    <div key={key} className="flex gap-3 text-xs">
                      <span className="flex-shrink-0 w-20 font-medium text-content-tertiary">{key}</span>
                      <span className="flex-1 min-w-0 text-content-secondary break-words">{val}</span>
                    </div>
                  ))}
                </div>
              )}
              <Markdown content={body} />
              {skill.skill_md_truncated && <p className="mt-3 text-xs text-content-tertiary">{t('skill_preview_truncated')}</p>}
            </>
          )}
        </div>
      )}
      {pane === 'files' && (
        <div className="max-h-52 overflow-y-auto px-4 py-2.5 border-t border-subtle font-mono text-[11px] leading-relaxed text-content-tertiary">
          {skill.files.map((file) => (
            <div key={file} className="truncate">
              {file}
            </div>
          ))}
          {skill.file_count > skill.files.length && <div className="opacity-60">… +{skill.file_count - skill.files.length}</div>}
        </div>
      )}
    </div>
  )
}

export default SkillAddModal
