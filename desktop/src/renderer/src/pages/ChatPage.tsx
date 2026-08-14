import React, { useEffect, useRef, useCallback, useState } from 'react'
import {
  ChevronUp,
  Loader2,
  FolderOpen,
  Clock,
  Code2,
  BookOpen,
  Puzzle,
  Terminal,
  type LucideIcon,
} from 'lucide-react'
import MessageBubble from '../components/MessageBubble'
import ChatInput, { type ChatInputHandle } from '../components/ChatInput'
import { product } from '@product'
import { t } from '../i18n'
import apiClient from '../api/client'
import type { Attachment, ChatMessage } from '../types'
import { useChatStore } from '../store/chatStore'
import { useSessionStore } from '../store/sessionStore'
import { useUIStore } from '../store/uiStore'
import { useWorkspaceStore } from '../store/workspaceStore'

interface ChatPageProps {
  baseUrl: string
}

// Welcome-screen suggestion cards (aligned with the web console: 6 cards).
// `send` overrides the text dropped into the input (e.g. show "查看全部命令"
// but fill "/help"); otherwise the card's *_text is used.
// Icon + accent color per card, aligned with the web console palette.
const SUGGESTIONS: {
  key: string
  send?: string
  icon: LucideIcon
  iconClass: string
  bgClass: string
}[] = [
  { key: 'example_sys', icon: FolderOpen, iconClass: 'text-blue-500', bgClass: 'bg-blue-500/10' },
  { key: 'example_task', icon: Clock, iconClass: 'text-amber-500', bgClass: 'bg-amber-500/10' },
  { key: 'example_code', icon: Code2, iconClass: 'text-emerald-500', bgClass: 'bg-emerald-500/10' },
  { key: 'example_knowledge', icon: BookOpen, iconClass: 'text-violet-500', bgClass: 'bg-violet-500/10' },
  { key: 'example_skill', icon: Puzzle, iconClass: 'text-rose-500', bgClass: 'bg-rose-500/10' },
  { key: 'example_web', send: '/help', icon: Terminal, iconClass: 'text-content-tertiary', bgClass: 'bg-content-tertiary/10' },
]

const ChatPage: React.FC<ChatPageProps> = ({ baseUrl }) => {
  const activeId = useSessionStore((s) => s.activeId)
  const newSession = useSessionStore((s) => s.newSession)
  const loadSessions = useSessionStore((s) => s.loadSessions)

  const session = useChatStore((s) => s.sessions[activeId])
  const send = useChatStore((s) => s.send)
  const cancel = useChatStore((s) => s.cancel)
  const regenerate = useChatStore((s) => s.regenerate)
  const editUserMessage = useChatStore((s) => s.editUserMessage)
  const deleteMessage = useChatStore((s) => s.deleteMessage)
  const loadHistory = useChatStore((s) => s.loadHistory)
  const ensureSession = useChatStore((s) => s.ensureSession)
  const clearContext = useChatStore((s) => s.clearContext)
  const setSessionsCollapsed = useUIStore((s) => s.setSessionsCollapsed)
  const wsOnSessionSwitch = useWorkspaceStore((s) => s.onSessionSwitch)

  const messages = session?.messages ?? []
  const isStreaming = session?.isStreaming ?? false

  const scrollRef = useRef<HTMLDivElement>(null)
  const bottomRef = useRef<HTMLDivElement>(null)
  const inputResetRef = useRef<ChatInputHandle>(null)
  const [loadingMore, setLoadingMore] = useState(false)
  const titlePendingRef = useRef(false)

  useEffect(() => {
    apiClient.setBaseUrl(baseUrl)
  }, [baseUrl])

  // Load history when switching to a session that hasn't been loaded yet.
  useEffect(() => {
    ensureSession(activeId)
    const s = useChatStore.getState().sessions[activeId]
    if (s && !s.historyLoaded && !s.isStreaming) {
      loadHistory(activeId, 1)
    }
  }, [activeId, ensureSession, loadHistory])

  // Keep the workspace panel scoped to the active session (project vs default).
  useEffect(() => {
    wsOnSessionSwitch(activeId)
  }, [activeId, wsOnSessionSwitch])

  const scrollToBottom = useCallback((smooth = true) => {
    // Defer to the next frame so we read the height *after* the new content has
    // been laid out (markdown/streaming renders a frame later than the effect).
    requestAnimationFrame(() => {
      const el = scrollRef.current
      if (!el) return
      // Smooth animations get interrupted by high-frequency streaming updates
      // and never catch up, so jump instantly while following the stream.
      if (smooth) {
        bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
      } else {
        el.scrollTop = el.scrollHeight
      }
    })
  }, [])

  // Snap to the bottom instantly when switching sessions (no top-to-bottom animation).
  // History may load a frame later, so keep snapping instantly until content arrives.
  const lastSessionRef = useRef('')
  const lastLenRef = useRef(0)
  const pendingSnapRef = useRef(false)
  // True while we should keep the view pinned to the bottom (e.g. during
  // streaming). Cleared when the user scrolls up to read earlier messages.
  const followBottomRef = useRef(true)
  // Tracks the previous streaming state so we can do one final snap to the
  // bottom right when streaming ends (the last chunk of a long command output
  // often lands together with isStreaming flipping to false).
  const wasStreamingRef = useRef(false)
  useEffect(() => {
    const el = scrollRef.current
    if (!el) return

    if (lastSessionRef.current !== activeId) {
      lastSessionRef.current = activeId
      lastLenRef.current = messages.length
      pendingSnapRef.current = true
      followBottomRef.current = true
    }

    if (pendingSnapRef.current) {
      // Instant snap on switch and on the first content that lands afterwards.
      lastLenRef.current = messages.length
      scrollToBottom(false)
      if (messages.length > 0) pendingSnapRef.current = false
      return
    }

    const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 160
    const grew = messages.length !== lastLenRef.current
    lastLenRef.current = messages.length
    // Follow the bottom when: a new message arrived, the user is already near
    // the bottom, or we're streaming and the user hasn't scrolled up. This
    // keeps long command/streaming output (where length is unchanged but the
    // content keeps growing) glued to the latest line.
    // One final snap right when streaming ends, so the tail of a long command
    // output isn't left scrolled off-screen.
    const justFinished = wasStreamingRef.current && !isStreaming
    wasStreamingRef.current = isStreaming

    const following = isStreaming && followBottomRef.current
    if (grew || nearBottom || following || (justFinished && followBottomRef.current)) {
      // Instant jump while streaming/new content (smooth animations get
      // interrupted by rapid updates and never reach the bottom); smooth only
      // for a lone increment when the user is already sitting near the bottom.
      const smooth = nearBottom && !following && !grew && !justFinished
      scrollToBottom(smooth)
    }
  }, [messages, activeId, isStreaming, scrollToBottom])

  const handleSend = useCallback(
    async (text: string, attachments: Attachment[]) => {
      const sid = activeId
      const isFirst = (useChatStore.getState().sessions[sid]?.messages.length ?? 0) === 0
      titlePendingRef.current = isFirst
      await send(sid, text, attachments)
      // After the first message, refresh the list and ask backend to title it.
      if (isFirst) {
        try {
          await apiClient.generateSessionTitle(sid, text)
        } catch {
          /* ignore */
        }
        loadSessions(1)
        titlePendingRef.current = false
      }
    },
    [activeId, send, loadSessions]
  )

  const handleNewChat = useCallback(() => {
    const id = newSession()
    ensureSession(id)
    loadHistory(id, 1)
    // Auto-expand the session list so the user sees the new/switched session.
    setSessionsCollapsed(false)
  }, [newSession, ensureSession, loadHistory, setSessionsCollapsed])

  const handleClearContext = useCallback(async () => {
    await clearContext(activeId)
    scrollToBottom(true)
  }, [clearContext, activeId, scrollToBottom])

  const handleStop = useCallback(() => cancel(activeId), [cancel, activeId])

  const handleRegenerate = useCallback((id: string) => regenerate(activeId, id), [regenerate, activeId])

  const handleEdit = useCallback(
    (id: string) => {
      const result = editUserMessage(activeId, id)
      if (result && inputResetRef.current) inputResetRef.current(result.text, result.attachments)
    },
    [editUserMessage, activeId]
  )

  const handleDelete = useCallback(
    (msg: ChatMessage) => {
      if (msg.userSeq != null) deleteMessage(activeId, msg.userSeq, true)
    },
    [deleteMessage, activeId]
  )

  // Inline images/videos load asynchronously and grow the bubble after mount,
  // so a scroll triggered on message change fires before the final height is
  // known. Re-scroll once media loads, but only while following the bottom.
  const handleMediaLoad = useCallback(() => {
    if (followBottomRef.current) scrollToBottom(false)
  }, [scrollToBottom])

  const handleScroll = useCallback(
    async (e: React.UIEvent<HTMLDivElement>) => {
      const el = e.currentTarget
      // Track whether the user wants to stay pinned to the bottom: scrolling up
      // pauses auto-follow; returning near the bottom resumes it.
      followBottomRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 160
      const s = useChatStore.getState().sessions[activeId]
      if (el.scrollTop < 40 && s?.historyHasMore && !loadingMore && !isStreaming) {
        setLoadingMore(true)
        const prevHeight = el.scrollHeight
        await loadHistory(activeId, s.historyPage + 1)
        requestAnimationFrame(() => {
          // preserve scroll position after prepending older messages
          el.scrollTop = el.scrollHeight - prevHeight
          setLoadingMore(false)
        })
      }
    },
    [activeId, loadHistory, loadingMore, isStreaming]
  )

  const isEmpty = messages.length === 0

  return (
    <div className="flex flex-col flex-1 min-h-0">
      <div ref={scrollRef} className="flex-1 overflow-y-auto" onScroll={handleScroll}>
        {loadingMore && (
          <div className="flex items-center justify-center py-3 text-content-tertiary">
            <Loader2 size={16} className="animate-spin" />
          </div>
        )}

        {isEmpty ? (
          <div data-home className="chat-home flex flex-col items-center justify-center h-full px-6 py-12">
            {product.slots?.HomeLogo ? (
              <div className="w-16 h-16 rounded-2xl mb-5 shadow-md overflow-hidden">
                <product.slots.HomeLogo />
              </div>
            ) : (
              <img src="./logo.jpg" alt="CowAgent" className="w-16 h-16 rounded-2xl mb-5 shadow-md" />
            )}
            <h1 className="text-xl font-semibold text-content mb-2">{t('chat_welcome')}</h1>
            <p className="text-content-tertiary text-sm text-center max-w-md mb-8 leading-relaxed whitespace-pre-line">
              {t('welcome_subtitle')}
            </p>

            <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 w-full max-w-2xl">
              {SUGGESTIONS.map(({ key, send, icon: Icon, iconClass, bgClass }) => (
                <button
                  key={key}
                  onClick={() => {
                    // Fill the input (don't auto-send) so the user can tweak it first.
                    const draft = send ?? t(`${key}_text` as Parameters<typeof t>[0])
                    inputResetRef.current?.(draft, [])
                  }}
                  className="group text-left bg-surface border border-default rounded-xl p-3.5 cursor-pointer hover:border-accent hover:shadow-sm transition-all"
                >
                  <div className="flex items-center gap-2 mb-1.5">
                    <span
                      className={`w-7 h-7 rounded-lg flex items-center justify-center shrink-0 ${bgClass}`}
                    >
                      <Icon size={15} className={iconClass} />
                    </span>
                    <span className="font-medium text-sm text-content">
                      {t(`${key}_title` as Parameters<typeof t>[0])}
                    </span>
                  </div>
                  <p className="text-xs text-content-tertiary leading-relaxed line-clamp-2">
                    {t(`${key}_text` as Parameters<typeof t>[0])}
                  </p>
                </button>
              ))}
            </div>
          </div>
        ) : (
          <div className="py-3 max-w-3xl mx-auto">
            {messages.map((msg) =>
              msg.kind === 'divider' ? (
                <div key={msg.id} className="flex items-center gap-3 px-6 py-3 text-content-tertiary">
                  <span
                    className="flex-1 h-px"
                    style={{ background: 'linear-gradient(to right, transparent, var(--border-strong), transparent)' }}
                  />
                  <span className="text-xs whitespace-nowrap">{t('context_cleared')}</span>
                  <span
                    className="flex-1 h-px"
                    style={{ background: 'linear-gradient(to right, transparent, var(--border-strong), transparent)' }}
                  />
                </div>
              ) : (
                <MessageBubble
                  key={msg.id}
                  message={msg}
                  onRegenerate={handleRegenerate}
                  onEdit={handleEdit}
                  onDelete={handleDelete}
                  onMediaLoad={handleMediaLoad}
                />
              )
            )}
            <div ref={bottomRef} />
          </div>
        )}
      </div>

      {/* Jump-to-bottom affordance could go here in a later pass */}

      <ChatInput
        onSend={handleSend}
        onNewChat={handleNewChat}
        onStop={handleStop}
        onClearContext={handleClearContext}
        isStreaming={isStreaming}
        sessionId={activeId}
        ref={inputResetRef}
      />
    </div>
  )
}

export default ChatPage
