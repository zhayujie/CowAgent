import React, { useState } from 'react'
import { Copy, Check, RefreshCw, Trash2, File as FileIcon, Folder, Sprout } from 'lucide-react'
import type { ChatMessage } from '../types'
import { t } from '../i18n'
import apiClient from '../api/client'
import { useWorkspaceStore } from '../store/workspaceStore'
import Markdown from './Markdown'
import MessageSteps, { ThinkingStep } from './MessageSteps'
import FileCard from './FileCard'
import { useLightboxStore } from './Lightbox'
import { product } from '@product'

interface MessageBubbleProps {
  message: ChatMessage
  onRegenerate?: (id: string) => void
  onEdit?: (id: string) => void
  onDelete?: (msg: ChatMessage) => void
  /** Fired when an inline image/video finishes loading, so the parent can
   *  re-scroll to the bottom (async media changes bubble height after mount). */
  onMediaLoad?: () => void
}

function fmtTime(ts: number): string {
  if (!ts) return ''
  const d = new Date(ts * 1000)
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

const HoverAction: React.FC<{ onClick: () => void; title: string; danger?: boolean; children: React.ReactNode }> = ({
  onClick,
  title,
  danger,
  children,
}) => (
  <button
    onClick={onClick}
    title={title}
    className={`inline-flex items-center justify-center w-7 h-7 rounded-md cursor-pointer transition-colors text-content-tertiary ${
      danger ? 'hover:text-danger hover:bg-danger-soft' : 'hover:text-content hover:bg-surface-2'
    }`}
  >
    {children}
  </button>
)

const MessageBubble: React.FC<MessageBubbleProps> = ({ message, onRegenerate, onEdit, onDelete, onMediaLoad }) => {
  const isUser = message.role === 'user'
  const [copied, setCopied] = useState(false)
  const preview = useWorkspaceStore((s) => s.preview)
  const openLightbox = useLightboxStore((s) => s.open)

  const copy = () => {
    navigator.clipboard.writeText(message.content)
    setCopied(true)
    setTimeout(() => setCopied(false), 1800)
  }

  // Open a sent file: prefer the local path via Electron (Finder / default
  // app); fall back to the served URL in a browser when unavailable.
  const openAttachment = (att: { abs_path?: string; preview_url?: string; file_path: string }) => {
    if (att.abs_path && window.electronAPI?.openPath) {
      window.electronAPI.openPath(att.abs_path)
      return
    }
    window.open(apiClient.getFileUrl(att.preview_url || att.file_path), '_blank')
  }

  if (isUser) {
    return (
      <div className="group flex flex-col items-end px-4 sm:px-6 py-2">
        {message.attachments && message.attachments.length > 0 && (
          <div className="flex flex-wrap gap-2 mb-1.5 justify-end max-w-[75%]">
            {message.attachments.map((att, i) => {
              if (att.file_type === 'image' && (att.preview_url || att.file_path)) {
                // History replay recovers attachments from prompt markers,
                // which carry only the local file_path — serve it via /api/file.
                const url = att.preview_url
                  ? apiClient.getFileUrl(att.preview_url)
                  : apiClient.getServeFileUrl(att.file_path)
                return (
                  <img
                    key={i}
                    src={url}
                    alt={att.file_name}
                    onClick={() => openLightbox(url)}
                    className="max-w-[260px] max-h-[220px] rounded-xl object-cover border border-default cursor-zoom-in"
                  />
                )
              }
              if (att.file_type === 'workspace_ref') {
                return (
                  <div
                    key={i}
                    title={att.file_path}
                    onClick={() => preview(att.file_path)}
                    className="flex items-center gap-1.5 px-3 py-2 bg-surface-2 hover:bg-surface-3 rounded-xl text-xs text-content-secondary cursor-pointer transition-colors"
                  >
                    {att.is_dir ? <Folder size={13} /> : <FileIcon size={13} />}
                    {att.file_name}
                  </div>
                )
              }
              return (
                <div key={i} className="flex items-center gap-1.5 px-3 py-2 bg-surface-2 rounded-xl text-xs text-content-secondary">
                  <FileIcon size={13} />
                  {att.file_name}
                </div>
              )
            })}
          </div>
        )}
        <div className="max-w-[75%] rounded-2xl rounded-br-md px-4 py-2.5 bg-bubble-user text-bubble-user-text">
          <div className="text-sm whitespace-pre-wrap break-words">{message.content}</div>
        </div>
        <div className="flex items-center gap-0.5 mt-1 opacity-0 group-hover:opacity-100 transition-opacity">
          <span className="text-[11px] text-content-tertiary mr-1">{fmtTime(message.timestamp)}</span>
          {/* Edit entry hidden: editing a past question cascade-deletes all
              subsequent turns, which surprises users. Kept off until we support
              non-destructive editing. */}
          {onDelete && message.userSeq != null && (
            <HoverAction onClick={() => onDelete(message)} title={t('msg_delete')} danger>
              <Trash2 size={13} />
            </HoverAction>
          )}
        </div>
      </div>
    )
  }

  // Assistant
  const showCursor = message.isStreaming && !message.content && (!message.steps || message.steps.length === 0)

  const hasSteps = !!(message.steps && message.steps.length > 0)
  const hasLiveReasoning = !!(message.reasoning && message.isStreaming)

  return (
    <div className="group flex gap-3 px-4 sm:px-6 py-2">
      {product.slots?.AssistantAvatar ? (
        <div className="w-7 h-7 rounded-lg flex-shrink-0 mt-1 overflow-hidden">
          <product.slots.AssistantAvatar />
        </div>
      ) : (
        <img src="./logo.jpg" alt="Agent" className="w-7 h-7 rounded-lg flex-shrink-0 mt-1" />
      )}
      <div className="flex-1 min-w-0 max-w-[calc(100%-2.5rem)]">
        <div className="inline-block w-full rounded-2xl border border-default bg-surface px-4 py-3">
          {message.kind === 'evolution' && (
            <div className="inline-flex items-center gap-1 mb-1.5 text-[11px] text-content-tertiary">
              <Sprout size={11} />
              {t('msg_self_learned')}
            </div>
          )}

          {/* Steps area (thinking / tools / intermediate content), web-aligned:
              muted, separated from the final answer by a dashed divider. */}
          {(hasSteps || hasLiveReasoning) && (
            <div className="mb-2.5 pb-2 border-b border-dashed border-default">
              {hasSteps && <MessageSteps steps={message.steps!} />}
              {/* Live reasoning is the current, not-yet-committed thinking, so it
                  must render after all committed steps (tools/thinking), not at
                  the very top of the bubble. */}
              {hasLiveReasoning && (
                <div className={hasSteps ? 'mt-1' : ''}>
                  <ThinkingStep content={message.reasoning!} streaming />
                </div>
              )}
            </div>
          )}

          {/* Final answer */}
          {message.content && <Markdown content={message.content} />}

          {/* Files the agent wrote this turn — click to open the preview panel. */}
          {message.artifacts && message.artifacts.length > 0 && (
            <div className="flex flex-col items-start">
              {message.artifacts.map((a) => (
                <FileCard key={a.abs_path || a.rel_path} meta={a} />
              ))}
            </div>
          )}

          {/* Media attachments sent via the `send` tool (images / files). */}
          {message.attachments && message.attachments.length > 0 && (
            <div className="flex flex-wrap gap-2 mt-2">
              {message.attachments.map((att, i) => {
                const url = apiClient.getFileUrl(att.preview_url || att.file_path)
                if (att.file_type === 'image') {
                  return (
                    <img
                      key={i}
                      src={url}
                      alt={att.file_name}
                      onLoad={() => onMediaLoad?.()}
                      onClick={() => openLightbox(url)}
                      className="max-w-[320px] w-full rounded-xl border border-default cursor-zoom-in"
                    />
                  )
                }
                if (att.file_type === 'video') {
                  return (
                    <video
                      key={i}
                      src={url}
                      controls
                      onLoadedData={() => onMediaLoad?.()}
                      className="max-w-[360px] w-full rounded-xl border border-default"
                    />
                  )
                }
                return (
                  <button
                    key={i}
                    type="button"
                    onClick={() => openAttachment(att)}
                    className="flex items-center gap-1.5 px-3 py-2 bg-surface-2 rounded-xl text-xs text-content-secondary hover:text-content cursor-pointer"
                  >
                    <FileIcon size={13} />
                    {att.file_name}
                  </button>
                )
              })}
            </div>
          )}

          {showCursor && (
            <div className="flex items-center gap-1 py-0.5">
              <span className="typing-dot" />
              <span className="typing-dot" />
              <span className="typing-dot" />
            </div>
          )}

          {message.isStreaming && message.content && (
            <span className="inline-block w-[6px] h-[14px] bg-accent ml-0.5 align-middle animate-blink" />
          )}

          {message.isCancelled && <div className="text-xs text-warning mt-1">{t('msg_cancelled')}</div>}
          {message.error && <div className="text-xs text-danger mt-1">{message.error}</div>}
        </div>

        {/* Hover actions (only when finished) */}
        {!message.isStreaming && (message.content || message.error) && (
          <div className="flex items-center gap-0.5 mt-1 opacity-0 group-hover:opacity-100 transition-opacity">
            <span className="text-[11px] text-content-tertiary mr-1">{fmtTime(message.timestamp)}</span>
            <HoverAction onClick={copy} title={t('msg_copy')}>
              {copied ? <Check size={13} /> : <Copy size={13} />}
            </HoverAction>
            {onRegenerate && (
              <HoverAction onClick={() => onRegenerate(message.id)} title={t('msg_regenerate')}>
                <RefreshCw size={13} />
              </HoverAction>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

export default MessageBubble
