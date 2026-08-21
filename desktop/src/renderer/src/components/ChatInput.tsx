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
  Folder,
  Mic
} from 'lucide-react'
import { t } from '../i18n'
import type { Attachment, WorkspaceEntry } from '../types'
import { chatDraft } from '../store/draftStore'
import apiClient from '../api/client'
import { PaperPlaneIcon } from './icons'
import { WORKSPACE_DRAG_TYPE } from './FileTree'
import { iconFor, colorFor } from '../lib/fileKind'
import WorkspaceSelector from './WorkspaceSelector'
import PermissionSelector from './PermissionSelector'
import ModelSelector from './ModelSelector'
import Tooltip from './Tooltip'
import { useSessionSettingsStore } from '../store/sessionSettingsStore'

export type ChatInputHandle = (text: string, attachments: Attachment[]) => void

// Voice input needs MediaRecorder + getUserMedia; hide the mic when absent.
const micSupported =
  typeof navigator !== 'undefined' &&
  !!navigator.mediaDevices?.getUserMedia &&
  typeof window.MediaRecorder !== 'undefined'

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

  // Voice input: record via MediaRecorder, transcribe via the configured ASR
  // provider (same flow as the web console's mic button).
  const [micState, setMicState] = useState<'idle' | 'recording' | 'busy'>('idle')
  const [micError, setMicError] = useState('')
  const mediaRecorderRef = useRef<MediaRecorder | null>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const chunksRef = useRef<Blob[]>([])
  const micStartedAtRef = useRef(0)
  const micErrorTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const pickMicMimeType = () => {
    const candidates = ['audio/webm;codecs=opus', 'audio/webm', 'audio/ogg;codecs=opus', 'audio/mp4']
    for (const m of candidates) {
      if (window.MediaRecorder.isTypeSupported?.(m)) return m
    }
    return ''
  }

  const flashMicError = (msg: string) => {
    setMicError(msg)
    if (micErrorTimerRef.current) clearTimeout(micErrorTimerRef.current)
    micErrorTimerRef.current = setTimeout(() => setMicError(''), 2500)
  }

  const stopMicStream = () => {
    streamRef.current?.getTracks().forEach((tr) => tr.stop())
    streamRef.current = null
  }

  const uploadRecording = async (blob: Blob) => {
    setMicState('busy')
    try {
      const res = await apiClient.voiceAsr(blob)
      if (res.status === 'success' && res.text) {
        const recognized = res.text
        // Fill the recognized text into the input for the user to review and send.
        setText((prev) => (prev ? (prev.endsWith(' ') ? prev : prev + ' ') + recognized : recognized))
        requestAnimationFrame(() => {
          const el = textareaRef.current
          if (el) {
            el.focus()
            el.selectionStart = el.selectionEnd = el.value.length
            autoSize(el)
          }
        })
      } else {
        flashMicError(res.message || t('mic_error'))
      }
    } catch (e) {
      flashMicError(`${t('mic_error')}: ${(e as Error).message}`)
    } finally {
      setMicState('idle')
    }
  }

  const startRecording = async () => {
    let stream: MediaStream
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true })
    } catch (e) {
      // Surface the concrete failure name so a denied/missing-device/insecure
      // context can be told apart instead of always blaming permissions.
      const err = e as Error
      flashMicError(`${t('mic_permission_denied')} (${err.name || 'Error'})`)
      return
    }
    streamRef.current = stream
    chunksRef.current = []
    const mimeType = pickMicMimeType()
    let recorder: MediaRecorder
    try {
      recorder = mimeType ? new MediaRecorder(stream, { mimeType }) : new MediaRecorder(stream)
    } catch (e) {
      stopMicStream()
      flashMicError(`${t('mic_error')}: ${(e as Error).message}`)
      return
    }
    mediaRecorderRef.current = recorder
    recorder.ondataavailable = (ev) => {
      if (ev.data && ev.data.size > 0) chunksRef.current.push(ev.data)
    }
    recorder.onstop = () => {
      stopMicStream()
      const blob = new Blob(chunksRef.current, { type: recorder.mimeType || 'audio/webm' })
      // 256 bytes ≈ container header only — treat as an accidental tap.
      if (blob.size < 256) {
        setMicState('idle')
        flashMicError(t('mic_too_short'))
        return
      }
      uploadRecording(blob)
    }
    // timeslice=250ms: flush a chunk every 250ms so very short taps aren't lost.
    recorder.start(250)
    micStartedAtRef.current = Date.now()
    setMicState('recording')
  }

  const stopRecording = () => {
    const recorder = mediaRecorderRef.current
    if (!recorder || recorder.state === 'inactive') return
    // Give the recorder a moment to capture at least one chunk on quick taps.
    const elapsed = Date.now() - micStartedAtRef.current
    const minMs = 350
    if (elapsed < minMs) {
      setTimeout(() => {
        if (recorder.state !== 'inactive') recorder.stop()
      }, minMs - elapsed)
    } else {
      recorder.stop()
    }
  }

  const toggleMic = () => {
    if (micState === 'recording') stopRecording()
    else if (micState === 'idle') startRecording()
  }

  // Release the mic and timers when the chat page unmounts.
  useEffect(() => {
    return () => {
      const recorder = mediaRecorderRef.current
      if (recorder && recorder.state !== 'inactive') {
        recorder.onstop = null
        recorder.stop()
      }
      stopMicStream()
      if (micErrorTimerRef.current) clearTimeout(micErrorTimerRef.current)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Per-session model / permission chips follow the active conversation.
  useEffect(() => {
    useSessionSettingsStore.getState().refresh(sessionId)
    useSessionSettingsStore.getState().setOpenMenu(null)
  }, [sessionId])

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
    el.style.height = '48px'
    const h = Math.min(el.scrollHeight, 200)
    el.style.height = h + 'px'
    el.style.overflowY = el.scrollHeight > 200 ? 'auto' : 'hidden'
  }

  const resetHeight = () => {
    const el = textareaRef.current
    if (!el) return
    el.style.height = '48px'
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
      {/* One tall rounded card holds the textarea on top and a toolbar row
          (chips + actions) at the bottom, matching the web console composer. */}
      <div
        className={`max-w-3xl mx-auto relative rounded-2xl border bg-inset transition-colors ${
          dragOver ? 'border-accent ring-2 ring-accent/30' : 'border-strong focus-within:border-accent'
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

        {/* Attachment previews sit at the top of the card, above the textarea. */}
        {attachments.length > 0 && (
          <div className="flex items-center gap-2 relative px-3 pt-2.5">
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
          </div>
        )}

        <input
          ref={fileInputRef}
          type="file"
          className="hidden"
          multiple
          onChange={handleFileSelect}
        />

        {/* Textarea sits at the top of the card, borderless (the card owns the
            border) and taller than a single line so the composer reads tall. */}
        <div className="relative">
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
            className="w-full px-4 pt-3 pb-0 bg-transparent text-content placeholder:text-content-tertiary focus:outline-none text-sm leading-relaxed resize-none overflow-y-hidden"
          />
          {micError && (
            // Transient error tip above the input, mirroring the web console.
            <div className="absolute right-3 bottom-full mb-2 px-2 py-1 rounded-md text-xs text-white bg-black/80 dark:bg-white/20 shadow-md pointer-events-none whitespace-nowrap z-10">
              {micError}
            </div>
          )}
        </div>

        {/* Toolbar row inside the card: chips on the left, actions on the right.
            This is what makes the composer read as one tall card like the web
            console, instead of a short input with controls floating around it.
            The middle chip group shrinks/truncates so a narrow composer (right
            panel open) never overflows the card. */}
        <div className="composer-toolbar flex items-center gap-1 px-2 pb-1 pt-2 min-w-0">
          <Tooltip label={t('session_new')}>
            <button
              onClick={onNewChat}
              className="shrink-0 w-8 h-8 flex items-center justify-center rounded-btn text-content-secondary hover:text-accent hover:bg-accent-soft cursor-pointer transition-colors"
            >
              <Plus size={17} />
            </button>
          </Tooltip>
          <Tooltip label={t('chat_attach')}>
            <button
              onClick={() => fileInputRef.current?.click()}
              disabled={uploading}
              className="shrink-0 w-8 h-8 flex items-center justify-center rounded-btn text-content-secondary hover:text-accent hover:bg-accent-soft cursor-pointer transition-colors disabled:opacity-50"
            >
              {uploading ? <Loader2 size={17} className="animate-spin" /> : <Paperclip size={17} />}
            </button>
          </Tooltip>
          <Tooltip label={t('chat_clear_context')}>
            <button
              onClick={onClearContext}
              className="shrink-0 w-8 h-8 flex items-center justify-center rounded-btn text-content-secondary hover:text-danger hover:bg-danger-soft cursor-pointer transition-colors"
            >
              <Trash2 size={17} />
            </button>
          </Tooltip>

          <div className="mx-1 h-4 w-px bg-default shrink-0" />

          {/* Chips share the flexible middle; each may shrink and truncate. */}
          <div className="flex items-center gap-1 min-w-0 flex-1">
            <WorkspaceSelector sessionId={sessionId} />
            <PermissionSelector sessionId={sessionId} />
          </div>

          <div className="flex items-center gap-1 shrink-0 pl-1">
            <div className="max-w-[200px] min-w-0">
              <ModelSelector sessionId={sessionId} />
            </div>
            {micSupported && (
              <Tooltip
                label={
                  micState === 'recording'
                    ? t('mic_recording_title')
                    : micState === 'busy'
                      ? t('mic_busy_title')
                      : t('mic_idle_title')
                }
              >
                <button
                  onClick={toggleMic}
                  disabled={micState === 'busy'}
                  className={`w-8 h-8 flex items-center justify-center rounded-btn cursor-pointer transition-colors disabled:cursor-not-allowed ${
                    micState === 'recording'
                      ? 'text-red-500 animate-pulse hover:text-red-600'
                      : micState === 'busy'
                        ? 'text-accent'
                        : 'text-content-tertiary hover:text-accent hover:bg-accent-soft'
                  }`}
                >
                  {micState === 'recording' ? (
                    <Square size={12} className="fill-current" />
                  ) : micState === 'busy' ? (
                    <Loader2 size={16} className="animate-spin" />
                  ) : (
                    <Mic size={16} />
                  )}
                </button>
              </Tooltip>
            )}
            {isStreaming ? (
              <Tooltip label={t('msg_stop')}>
                <button
                  onClick={onStop}
                  className="flex-shrink-0 w-9 h-9 flex items-center justify-center rounded-btn bg-surface-2 text-content hover:bg-inset cursor-pointer transition-colors"
                >
                  <Square size={14} className="fill-current" />
                </button>
              </Tooltip>
            ) : (
              <Tooltip label={t('chat_send')}>
                <button
                  onClick={handleSubmit}
                  disabled={!canSend}
                  className="flex-shrink-0 w-9 h-9 flex items-center justify-center rounded-btn bg-accent text-white hover:bg-accent-hover disabled:bg-surface-2 disabled:text-content-disabled disabled:cursor-not-allowed cursor-pointer transition-none [&_*]:transition-none"
                >
                  <PaperPlaneIcon size={14} />
                </button>
              </Tooltip>
            )}
          </div>
        </div>
      </div>
    </div>
  )
})

export default ChatInput
