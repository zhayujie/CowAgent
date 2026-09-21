import React, { useEffect, useRef, useState } from 'react'
import { Loader2, Wrench, Zap, Puzzle, ArrowLeft, Lock, Pencil } from 'lucide-react'
import { t } from '../i18n'
import apiClient from '../api/client'
import type { ApiResult } from '../api/client'
import type { ToolInfo, SkillInfo, SkillContent } from '../types'
import { Toggle } from './settings/primitives'
import Markdown from '../components/Markdown'
import { DocActions, DocEditor, DocNotice, DocView } from '../components/DocEditor'
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

const SkillsPage: React.FC<SkillsPageProps> = ({ baseUrl }) => {
  const [tools, setTools] = useState<ToolInfo[]>([])
  const [skills, setSkills] = useState<SkillInfo[]>([])
  const [loading, setLoading] = useState(true)

  const doc = skillEditor((s) => s.doc)
  const content = skillEditor((s) => s.content)
  const docLoading = skillEditor((s) => s.loading)
  const readonly = skillEditor((s) => s.readonly)
  const edit = skillEditor((s) => s.edit)
  const editorRef = useRef<HTMLTextAreaElement>(null)

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
        /* Skill viewer / editor */
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
          {edit ? (
            <div className="flex-1 min-h-0 overflow-hidden">
              <DocEditor key={doc.name} store={skillEditor} textareaRef={editorRef} />
            </div>
          ) : (
            <DocView store={skillEditor}>
              <div className="max-w-3xl mx-auto px-6 py-6">
                {docLoading ? (
                  <div className="flex items-center text-content-tertiary py-8">
                    <Loader2 size={16} className="animate-spin mr-2" />
                  </div>
                ) : (
                  <SkillContentView content={content} />
                )}
              </div>
            </DocView>
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
