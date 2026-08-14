import React, { useState, useRef, useCallback, useEffect, forwardRef, useImperativeHandle } from 'react'
import {
  Plus,
  Paperclip,
  Square,
  X,
  File as FileIcon,
  Loader2,
  Trash2,
  AtSign,
  Folder
} from 'lucide-react'
import { t } from '../i18n'
import type { Attachment, WorkspaceEntry } from '../types'
import { chatDraft } from '../store/draftStore'
import apiClient from '../api/client'
import { PaperPlaneIcon } from './icons'
import { WORKSPACE_DRAG_TYPE } from './FileTree'
import { iconFor, colorFor } from '../lib/fileKind'
import WorkspaceSelector from './WorkspaceSelector'
import Tooltip from './Tooltip'

export type ChatInputHandle = (text: string, attachments: Attachment[]) => void

interface SlashCommand {
  cmd: string
  desc: string
  // 'new'/'clear' run a local action; 'send' (default) is a completion that
  // gets sent to the backend as a normal message (handled by command plugins).
  action?: 'new' | 'clear'
}

interface ChatInputProps {
  onSend: (message: string, attachments: Attachment[]) => void
  onNewChat: () => void
  onStop: () => void
  onClearContext: () => void
  isStreaming: boolean
  sessionId: string
}

const ChatInput = forwardRef<ChatInputHandle, ChatInputProps>(function ChatInput(
  { onSend, onNewChat, onStop, onClearContext, isStreaming, sessionId },
  ref
) {
  // Restore the draft saved in `chatDraft` on mount (lazy init: the very first
  // render must already show it, otherwise the write-through effect below would
  // overwrite the saved draft with the initial empty state).
  const [text, setText] = useState(() => chatDraft.text)
  const [attachments, setAttachments] = useState(() => chatDraft.attachments)
  const [uploading, setUploading] = useState(false)
  const [uploadError, setUploadError] = useState('')
  const [dragOver, setDragOver] = useState(false)
  const [slashOpen, setSlashOpen] = useState(false)
  const [slashIndex, setSlashIndex] = useState(0)
  // `@` workspace-file picker
  const [mentionItems, setMentionItems] = useState<WorkspaceEntry[]>([])
  const [mentionIndex, setMentionIndex] = useState(0)
  const mentionStartRef = useRef(-1)
  const mentionTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const composingRef = useRef(false)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  // Local actions ('new'/'clear') plus completion commands handled by backend
  // command plugins (cow_cli/godcmd). Commands ending with a space expect an
  // argument, so selecting them keeps focus in the input instead of sending.
  const slashCommands: SlashCommand[] = [
    { cmd: '/new', desc: t('slash_new'), action: 'new' },
    { cmd: '/clear', desc: t('slash_clear'), action: 'clear' },
    { cmd: '/help', desc: t('slash_help') },
    { cmd: '/status', desc: t('slash_status') },
    { cmd: '/context', desc: t('slash_context') },
    { cmd: '/compact', desc: t('slash_compact') },
    { cmd: '/skill list', desc: t('slash_skill_list') },
    { cmd: '/skill search ', desc: t('slash_skill_search') },
    { cmd: '/skill install ', desc: t('slash_skill_install') },
    { cmd: '/memory dream ', desc: t('slash_memory_dream') },
    { cmd: '/knowledge', desc: t('slash_knowledge') },
    { cmd: '/knowledge list', desc: t('slash_knowledge_list') },
    { cmd: '/install-browser', desc: t('slash_install_browser') },
    { cmd: '/config', desc: t('slash_config') },
    { cmd: '/cancel', desc: t('slash_cancel') },
    { cmd: '/logs', desc: t('slash_logs') },
    { cmd: '/version', desc: t('slash_version') },
  ]
  const filtered = slashCommands.filter((c) => c.cmd.startsWith(text.trim().toLowerCase()))

  // Resize the textarea to fit its content (single line = 42px, capped at
  // 180px). Keep overflow hidden until we hit the cap, so an empty/short input
  // never shows a scrollbar (matches the web console behavior).
  const autoSize = (el: HTMLTextAreaElement | null) => {
    if (!el) return
    el.style.height = '42px'
    const h = Math.min(el.scrollHeight, 180)
    el.style.height = h + 'px'
    el.style.overflowY = el.scrollHeight > 180 ? 'auto' : 'hidden'
  }

  const resetHeight = () => {
    const el = textareaRef.current
    if (!el) return
    el.style.height = '42px'
    el.style.overflowY = 'hidden'
  }

  // Sync the height once on mount so the very first render matches the 42px
  // single-line height instead of the browser's default textarea size.
  useEffect(() => {
    autoSize(textareaRef.current)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Write the input through to `chatDraft` on every change so it survives this
  // component unmounting when the user navigates to another page (chat route
  // unmounts ChatPage; see store/draftStore.ts). Sending clears the input, which
  // therefore also clears the saved draft.
  useEffect(() => {
    chatDraft.text = text
    chatDraft.attachments = attachments
  }, [text, attachments])

  // Allow the parent to load a draft (e.g. when editing a past user message).
  useImperativeHandle(ref, () => (draft: string, atts: Attachment[]) => {
    setText(draft)
    setAttachments(atts)
    requestAnimationFrame(() => {
      const el = textareaRef.current
      if (el) {
        el.focus()
        autoSize(el)
      }
    })
  })

  const runSlash = (c: SlashCommand) => {
    setSlashOpen(false)
    if (c.action === 'new') {
      setText('')
      resetHeight()
      onNewChat()
      return
    }
    if (c.action === 'clear') {
      setText('')
      resetHeight()
      onClearContext()
      return
    }
    // Completion command. If it expects an argument (trailing space), keep it
    // in the input so the user can type the argument; otherwise send it now.
    const needsArg = c.cmd.endsWith(' ')
    if (needsArg) {
      setText(c.cmd)
      requestAnimationFrame(() => textareaRef.current?.focus())
    } else {
      onSend(c.cmd.trim(), [])
      setText('')
      resetHeight()
    }
  }

  const handleSubmit = useCallback(() => {
    const trimmed = text.trim()
    if (!trimmed && attachments.length === 0) return
    if (isStreaming) return
    onSend(trimmed, attachments)
    setText('')
    setAttachments([])
    setSlashOpen(false)
    resetHeight()
  }, [text, attachments, isStreaming, onSend])

  const mentionOpen = mentionStartRef.current >= 0 && mentionItems.length > 0

  const closeMention = () => {
    mentionStartRef.current = -1
    setMentionItems([])
    setMentionIndex(0)
  }

  /** Reference an existing workspace file or folder in place, not as an upload. */
  const addWorkspaceRef = (entry: WorkspaceEntry) => {
    setAttachments((prev) =>
      prev.some((a) => a.file_type === 'workspace_ref' && a.file_path === entry.path)
        ? prev
        : [
            ...prev,
            {
              file_path: entry.path,
              file_name: entry.name,
              file_type: 'workspace_ref',
              is_dir: entry.is_dir,
            },
          ]
    )
  }

  const acceptMention = (index: number) => {
    const item = mentionItems[index]
    const el = textareaRef.current
    if (!item || !el) return
    addWorkspaceRef(item)
    // Drop the "@query" fragment: the file rides along as an attachment.
    const caret = el.selectionStart
    const next = text.slice(0, mentionStartRef.current) + text.slice(caret)
    const caretAfter = mentionStartRef.current
    setText(next)
    closeMention()
    requestAnimationFrame(() => {
      el.focus()
      el.selectionStart = el.selectionEnd = caretAfter
      autoSize(el)
    })
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    // Mention menu takes precedence: it's only open while typing "@…".
    if (mentionOpen) {
      if (e.key === 'ArrowDown') {
        e.preventDefault()
        setMentionIndex((i) => (i + 1) % mentionItems.length)
        return
      }
      if (e.key === 'ArrowUp') {
        e.preventDefault()
        setMentionIndex((i) => (i - 1 + mentionItems.length) % mentionItems.length)
        return
      }
      if ((e.key === 'Enter' && !e.shiftKey) || e.key === 'Tab') {
        e.preventDefault()
        acceptMention(mentionIndex)
        return
      }
      if (e.key === 'Escape') {
        e.preventDefault()
        closeMention()
        return
      }
    }
    // Slash menu navigation
    if (slashOpen && filtered.length > 0) {
      if (e.key === 'ArrowDown') {
        e.preventDefault()
        setSlashIndex((i) => (i + 1) % filtered.length)
        return
      }
      if (e.key === 'ArrowUp') {
        e.preventDefault()
        setSlashIndex((i) => (i - 1 + filtered.length) % filtered.length)
        return
      }
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault()
        runSlash(filtered[slashIndex])
        return
      }
      if (e.key === 'Escape') {
        setSlashOpen(false)
        return
      }
    }
    // Don't submit while IME is composing (Chinese input)
    if (e.key === 'Enter' && !e.shiftKey && !composingRef.current) {
      e.preventDefault()
      handleSubmit()
    }
  }

  const handleTextChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    const v = e.target.value
    setText(v)
    autoSize(e.target)
    // open slash menu when the input starts with "/" and has no space
    setSlashOpen(v.startsWith('/') && !v.includes(' '))
    setSlashIndex(0)

    // Trigger the file picker on "@" at the start or after whitespace.
    const match = v.slice(0, e.target.selectionStart).match(/(?:^|\s)@([^\s@]*)$/)
    if (mentionTimerRef.current) clearTimeout(mentionTimerRef.current)
    if (!match) {
      closeMention()
      return
    }
    mentionStartRef.current = e.target.selectionStart - match[1].length - 1
    mentionTimerRef.current = setTimeout(async () => {
      try {
        const res = await apiClient.workspaceSearch(match[1], 12, sessionId)
        if (mentionStartRef.current < 0) return
        setMentionItems(res.results || [])
        setMentionIndex(0)
      } catch {
        closeMention()
      }
    }, 160)
  }

  const uploadFiles = async (files: File[]) => {
    if (!files.length) return
    setUploading(true)
    setUploadError('')
    // Report per-file outcomes: a silent failure here is indistinguishable from
    // the file picker never opening, which makes the feature look broken.
    const failed: string[] = []
    try {
      for (const file of files) {
        try {
          const result = await apiClient.uploadFile(file, sessionId)
          if (result.status === 'success') {
            setAttachments((prev) => [
              ...prev,
              {
                file_path: result.file_path,
                file_name: result.file_name,
                file_type: result.file_type as Attachment['file_type'],
                preview_url: result.preview_url,
              },
            ])
          } else {
            failed.push(`${file.name}: ${result.message || 'unknown error'}`)
          }
        } catch (err) {
          failed.push(`${file.name}: ${(err as Error).message}`)
        }
      }
    } finally {
      setUploading(false)
      if (failed.length) {
        console.error('Upload failed:', failed)
        setUploadError(`${t('upload_failed')} — ${failed.join('; ')}`)
      }
    }
  }

  const handleFileSelect = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files
    if (files) await uploadFiles(Array.from(files))
    if (fileInputRef.current) fileInputRef.current.value = ''
  }

  const handleDropData = (dt: DataTransfer) => {
    // A file dragged from the workspace panel is already on disk in the
    // workspace — reference it instead of uploading a duplicate.
    const wsPayload = dt.getData(WORKSPACE_DRAG_TYPE)
    if (wsPayload) {
      try {
        addWorkspaceRef(JSON.parse(wsPayload) as WorkspaceEntry)
      } catch {
        /* malformed drag payload */
      }
      return
    }
    const files = Array.from(dt.files || [])
    if (files.length) uploadFiles(files)
  }

  // Read through a ref so the window listeners below can stay bound once
  // instead of re-subscribing whenever the input's state changes.
  const dropHandlerRef = useRef(handleDropData)
  dropHandlerRef.current = handleDropData

  const handlePaste = (e: React.ClipboardEvent) => {
    const items = e.clipboardData?.items
    if (!items) return
    const files: File[] = []
    for (const item of Array.from(items)) {
      if (item.kind === 'file') {
        const f = item.getAsFile()
        if (f) files.push(f)
      }
    }
    if (files.length) {
      e.preventDefault()
      uploadFiles(files)
    }
  }

  const removeAttachment = (index: number) => {
    setAttachments((prev) => prev.filter((_, i) => i !== index))
  }

  // keep slash index in range
  useEffect(() => {
    if (slashIndex >= filtered.length) setSlashIndex(0)
  }, [filtered.length, slashIndex])

  // Accept drops anywhere in the window rather than only over the input box:
  // users aim at the conversation area, and a drop that no element handles makes
  // Chromium navigate to the dropped file, replacing the whole UI.
  useEffect(() => {
    const carriesFiles = (dt: DataTransfer | null) =>
      !!dt && (dt.types.includes('Files') || dt.types.includes(WORKSPACE_DRAG_TYPE))

    // dragenter/dragleave also fire when moving between descendants, so track
    // nesting depth and only drop the highlight once the drag really left.
    let depth = 0
    const onDragEnter = (e: DragEvent) => {
      if (!carriesFiles(e.dataTransfer)) return
      e.preventDefault()
      depth += 1
      setDragOver(true)
    }
    const onDragOver = (e: DragEvent) => {
      if (!carriesFiles(e.dataTransfer)) return
      e.preventDefault()
    }
    const onDragLeave = (e: DragEvent) => {
      if (!carriesFiles(e.dataTransfer)) return
      depth = Math.max(0, depth - 1)
      if (depth === 0) setDragOver(false)
    }
    const onDrop = (e: DragEvent) => {
      depth = 0
      setDragOver(false)
      if (!carriesFiles(e.dataTransfer)) return
      e.preventDefault()
      dropHandlerRef.current(e.dataTransfer!)
    }
    // A drag can end without ever dropping (Esc, or released outside the window).
    const onDragEnd = () => {
      depth = 0
      setDragOver(false)
    }

    window.addEventListener('dragenter', onDragEnter)
    window.addEventListener('dragover', onDragOver)
    window.addEventListener('dragleave', onDragLeave)
    window.addEventListener('drop', onDrop)
    window.addEventListener('dragend', onDragEnd)
    return () => {
      window.removeEventListener('dragenter', onDragEnter)
      window.removeEventListener('dragover', onDragOver)
      window.removeEventListener('dragleave', onDragLeave)
      window.removeEventListener('drop', onDrop)
      window.removeEventListener('dragend', onDragEnd)
    }
  }, [])

  const canSend = !isStreaming && (!!text.trim() || attachments.length > 0)

  return (
    <div className="flex-shrink-0 border-t border-default bg-surface px-4 py-3">
      <div
        className={`max-w-3xl mx-auto relative rounded-2xl transition-all ${
          dragOver ? 'ring-2 ring-accent ring-offset-2 ring-offset-surface' : ''
        }`}
      >
        {dragOver && (
          // accent-soft is a 12%-alpha tint, so it needs an opaque layer under
          // it — otherwise the textarea placeholder shows through the hint.
          <div className="absolute inset-0 z-20 rounded-2xl bg-surface pointer-events-none">
            <div className="flex h-full w-full items-center justify-center rounded-2xl bg-accent-soft text-accent text-sm font-medium">
              {t('drop_to_attach')}
            </div>
          </div>
        )}

        {uploadError && (
          <div className="mb-2 flex items-start gap-2 rounded-lg border border-danger-border bg-danger-soft px-3 py-2 text-xs text-danger">
            <span className="flex-1 break-all">{uploadError}</span>
            <button
              onClick={() => setUploadError('')}
              className="flex-shrink-0 cursor-pointer hover:opacity-70"
              title={t('ws_close')}
            >
              <X size={12} />
            </button>
          </div>
        )}

        {/* Slash command menu */}
        {slashOpen && filtered.length > 0 && (
          <div className="absolute bottom-full left-0 right-0 mb-1.5 max-h-80 overflow-y-auto rounded-xl border border-default bg-elevated shadow-xl z-30 p-1.5">
            <div className="px-2.5 pt-1 pb-1.5 text-[11px] font-semibold uppercase tracking-wider text-content-tertiary">
              {t('slash_menu_title')}
            </div>
            {filtered.map((c, i) => (
              <button
                key={c.cmd}
                onMouseEnter={() => setSlashIndex(i)}
                onClick={() => runSlash(c)}
                className={`w-full flex items-center justify-between gap-3 px-2.5 py-2 rounded-lg text-left cursor-pointer transition-colors ${
                  i === slashIndex ? 'bg-accent-soft' : 'hover:bg-surface-2'
                }`}
              >
                <span
                  className={`text-[13px] font-medium font-mono whitespace-nowrap ${
                    i === slashIndex ? 'text-accent' : 'text-content-secondary'
                  }`}
                >
                  {c.cmd}
                </span>
                <span className="text-xs text-content-tertiary whitespace-nowrap truncate">{c.desc}</span>
              </button>
            ))}
          </div>
        )}

        {/* Workspace file picker (@) */}
        {mentionOpen && (
          <div className="absolute bottom-full left-0 right-0 mb-1.5 max-h-72 overflow-y-auto rounded-xl border border-default bg-elevated shadow-xl z-30 p-1.5">
            {mentionItems.map((item, i) => {
              const Icon = iconFor(item.kind)
              return (
                <button
                  key={item.path}
                  onMouseEnter={() => setMentionIndex(i)}
                  onMouseDown={(e) => {
                    e.preventDefault()
                    acceptMention(i)
                  }}
                  className={`w-full flex items-center gap-2.5 px-2.5 py-1.5 rounded-lg text-left cursor-pointer transition-colors ${
                    i === mentionIndex ? 'bg-accent-soft' : 'hover:bg-surface-2'
                  }`}
                >
                  <Icon size={13} className={`shrink-0 ${colorFor(item.kind)}`} />
                  <span className="text-[13px] text-content shrink-0 max-w-[45%] truncate">{item.name}</span>
                  <span className="flex-1 min-w-0 text-[11px] text-content-tertiary text-right truncate">
                    {item.path}
                  </span>
                </button>
              )
            })}
          </div>
        )}

        {/* Workspace selector (always present) + attachment preview share a row.
            The selector stays left; attachments grow to its right and scroll.
            No bottom gap by default (selector sits snug above the input); add a
            little breathing room only when attachments are shown. */}
        <div className={`flex items-center gap-2 relative ${attachments.length > 0 ? 'mb-2' : 'mb-0.5'}`}>
          <WorkspaceSelector sessionId={sessionId} />
          {attachments.length > 0 && (
            <div className="flex-1 min-w-0 flex items-center gap-2 overflow-x-auto overflow-y-visible">
              {attachments.map((att, i) => (
                <div key={i} className="relative shrink-0">
                  {att.file_type === 'image' && att.preview_url ? (
                    <div className="relative">
                      <img
                        src={apiClient.getFileUrl(att.preview_url)}
                        alt={att.file_name}
                        className="w-8 h-8 rounded-lg object-cover border border-default"
                      />
                      <button
                        onClick={() => removeAttachment(i)}
                        className="absolute top-0 right-0 w-3.5 h-3.5 rounded-full bg-danger text-white flex items-center justify-center cursor-pointer ring-1 ring-surface leading-none"
                      >
                        <X size={8} strokeWidth={2.5} />
                      </button>
                    </div>
                  ) : (
                    <div className="flex items-center gap-1.5 pl-2 pr-1 py-1 bg-inset border border-default rounded-lg text-[11px] text-content-secondary max-w-[160px]">
                      {att.file_type === 'workspace_ref' ? (
                        att.is_dir ? (
                          <Folder size={11} className="text-accent shrink-0" />
                        ) : (
                          <AtSign size={11} className="text-accent shrink-0" />
                        )
                      ) : (
                        <FileIcon size={11} className="shrink-0" />
                      )}
                      <span className="truncate" title={att.file_path}>
                        {att.file_name}
                      </span>
                      <button
                        onClick={() => removeAttachment(i)}
                        className="shrink-0 w-4 h-4 rounded flex items-center justify-center text-content-tertiary hover:text-danger hover:bg-danger-soft cursor-pointer"
                      >
                        <X size={11} strokeWidth={2.5} />
                      </button>
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="flex items-end gap-2">
          <div className="flex items-center flex-shrink-0 gap-0.5 pb-0.5">
            <Tooltip label={t('session_new')}>
              <button
                onClick={onNewChat}
                className="w-9 h-9 flex items-center justify-center rounded-btn text-content-secondary hover:text-accent hover:bg-accent-soft cursor-pointer transition-colors"
              >
                <Plus size={18} />
              </button>
            </Tooltip>
            <Tooltip label={t('chat_attach')}>
              <button
                onClick={() => fileInputRef.current?.click()}
                disabled={uploading}
                className="w-9 h-9 flex items-center justify-center rounded-btn text-content-secondary hover:text-accent hover:bg-accent-soft cursor-pointer transition-colors disabled:opacity-50"
              >
                {uploading ? <Loader2 size={18} className="animate-spin" /> : <Paperclip size={18} />}
              </button>
            </Tooltip>
            <Tooltip label={t('chat_clear_context')}>
              <button
                onClick={onClearContext}
                className="w-9 h-9 flex items-center justify-center rounded-btn text-content-secondary hover:text-danger hover:bg-danger-soft cursor-pointer transition-colors"
              >
                <Trash2 size={18} />
              </button>
            </Tooltip>
          </div>
          <input
            ref={fileInputRef}
            type="file"
            className="hidden"
            multiple
            onChange={handleFileSelect}
          />

          <textarea
            ref={textareaRef}
            id="chat-input"
            value={text}
            onChange={handleTextChange}
            onKeyDown={handleKeyDown}
            onPaste={handlePaste}
            onCompositionStart={() => (composingRef.current = true)}
            onCompositionEnd={() => (composingRef.current = false)}
            placeholder={t('input_placeholder')}
            rows={1}
            className="flex-1 min-w-0 px-4 py-[10px] rounded-xl border border-strong bg-inset text-content placeholder:text-content-tertiary focus:outline-none focus:border-accent text-sm leading-relaxed transition-colors resize-none overflow-y-hidden"
          />

          {isStreaming ? (
            <Tooltip label={t('msg_stop')}>
              <button
                onClick={onStop}
                className="flex-shrink-0 w-10 h-10 flex items-center justify-center rounded-btn bg-surface-2 text-content hover:bg-inset cursor-pointer transition-colors"
              >
                <Square size={15} className="fill-current" />
              </button>
            </Tooltip>
          ) : (
            <Tooltip label={t('chat_send')}>
              <button
                onClick={handleSubmit}
                disabled={!canSend}
                className="flex-shrink-0 w-[42px] h-[42px] flex items-center justify-center rounded-btn bg-accent text-white hover:bg-accent-hover disabled:bg-surface-2 disabled:text-content-disabled disabled:cursor-not-allowed cursor-pointer transition-none [&_*]:transition-none"
              >
                <PaperPlaneIcon size={15} />
              </button>
            </Tooltip>
          )}
        </div>
      </div>
    </div>
  )
})

export default ChatInput
