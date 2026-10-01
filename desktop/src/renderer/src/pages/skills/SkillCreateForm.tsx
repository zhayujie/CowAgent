import React, { useEffect, useRef, useState } from 'react'
import { FileUp, FolderPlus, Paperclip, X } from 'lucide-react'
import { t, tf } from '../../i18n'
import apiClient from '../../api/client'
import { Field, TextInput } from '../settings/primitives'

/** The form's id, so the add dialog's footer button can submit it from outside. */
export const SKILL_CREATE_FORM_ID = 'skill-create-form'

// The server's own ceilings for a form's attachments, mirrored so a 50 MB
// folder is refused here rather than after being uploaded. See
// SkillService.MAX_UPLOAD_*.
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

export function formatSkillFileSize(bytes: number): string {
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

const textareaClass =
  'w-full px-3 py-2 rounded-btn border border-strong bg-inset text-sm text-content placeholder:text-content-tertiary placeholder:opacity-60 focus:outline-none focus:border-accent transition-colors resize-y'

/**
 * Write a new skill from a name, a description and its instructions: the add
 * dialog's third tab. It has no preview step - what is typed here is what gets
 * written - so it posts straight to /api/skills/create.
 */
const SkillCreateForm: React.FC<{
  /** Whether this is the tab on screen; the form stays mounted behind the others. */
  active: boolean
  busy: boolean
  onBusyChange: (busy: boolean) => void
  /** Called with the directory name the server created the skill under. */
  onCreated: (name: string) => void
}> = ({ active, busy, onBusyChange, onCreated }) => {
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [body, setBody] = useState('')
  const [files, setFiles] = useState<File[]>([])
  const [error, setError] = useState('')
  // Two picks behind one button: a native file dialog browses for files or for a
  // directory, never both, so the choice is made before it opens.
  const [attachOpen, setAttachOpen] = useState(false)
  const filesRef = useRef<HTMLInputElement>(null)
  const folderRef = useRef<HTMLInputElement>(null)
  const attachRef = useRef<HTMLDivElement>(null)
  const formRef = useRef<HTMLFormElement>(null)

  useEffect(() => {
    if (active) formRef.current?.querySelector('input')?.focus()
  }, [active])

  useEffect(() => {
    if (!attachOpen) return
    const onDown = (e: MouseEvent) => {
      if (attachRef.current && !attachRef.current.contains(e.target as Node)) setAttachOpen(false)
    }
    // Captured rather than bubbled, so a click that something below stops from
    // propagating still closes the menu.
    document.addEventListener('mousedown', onDown, true)
    return () => document.removeEventListener('mousedown', onDown, true)
  }, [attachOpen])

  const slug = skillNameSlug(name)

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

  const submit = async () => {
    if (busy) return
    if (!slug) return setError(t('skill_new_name_invalid'))
    // The loader drops a skill with no description, so it is required here too.
    if (!description.trim()) return setError(t('skill_new_desc_required'))
    if (files.length) {
      const err = validateSkillUploadFiles(files)
      if (err) return setError(err)
    }
    onBusyChange(true)
    setError('')
    try {
      const res = await apiClient.createSkill({ name, description, body, files })
      if (res.status !== 'success') return setError(res.message || t('skill_new_failed'))
      onCreated(res.name || slug)
    } catch {
      setError(t('skill_new_failed'))
    } finally {
      onBusyChange(false)
    }
  }

  return (
    <form
      ref={formRef}
      id={SKILL_CREATE_FORM_ID}
      className="space-y-4"
      onSubmit={(e) => {
        e.preventDefault()
        void submit()
      }}
    >
      <Field label={t('skill_new_name')} required>
        <TextInput
          value={name}
          maxLength={64}
          onChange={(e) => {
            setName(e.target.value)
            setError('')
          }}
          placeholder="weather-api"
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
      </Field>
      <Field label={t('skill_new_desc')} hint={t('skill_new_desc_hint')} required>
        <textarea
          rows={3}
          value={description}
          onChange={(e) => {
            setDescription(e.target.value)
            setError('')
          }}
          className={textareaClass}
        />
      </Field>
      <Field label={t('skill_new_body')} hint={t('skill_new_body_hint')}>
        <textarea
          rows={6}
          value={body}
          onChange={(e) => setBody(e.target.value)}
          placeholder={'## Usage\n\n...'}
          className={`${textareaClass} font-mono`}
        />
      </Field>
      <Field
        label={t('skill_new_files')}
        labelAction={
          // A skill's resources come as a directory as often as they come as
          // loose files - `scripts/`, `references/` - and the paths are kept, so
          // the layout picked here is the one installed.
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
              // Opening upwards: the attachments are the last field of a body
              // that scrolls, so a menu below the button would be clipped.
              <div className="absolute right-0 bottom-full mb-1.5 w-36 z-30 rounded-xl border border-default bg-elevated shadow-xl p-1">
                {[
                  { icon: FileUp, label: t('skill_new_files_pick'), ref: filesRef },
                  { icon: FolderPlus, label: t('skill_new_files_pick_folder'), ref: folderRef },
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
        }
      >
        {files.length === 0 ? (
          <p className="text-xs text-content-tertiary">{t('skill_new_files_hint')}</p>
        ) : (
          // A picked folder can be dozens of files, so the list scrolls rather
          // than pushing the footer off the dialog.
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
          ref={folderRef}
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
      </Field>
      {error && <p className="text-sm text-danger break-all">{error}</p>}
    </form>
  )
}

export default SkillCreateForm
