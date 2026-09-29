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
import { useNavigate, useSearchParams } from 'react-router-dom'
import MessageBubble from '../components/MessageBubble'
import ChatInput, { type ChatInputHandle } from '../components/ChatInput'
import ChatTimeline from '../components/ChatTimeline'
import { useTimelineStore } from '../store/timelineStore'
import { TeamChatModal } from '../components/NewChatMenu'
import { product } from '@product'
import { t } from '../i18n'
import apiClient from '../api/client'
import type { Attachment, ChatMessage } from '../types'
import { useChatStore } from '../store/chatStore'
import { useSessionStore, sessionOwner } from '../store/sessionStore'
import { useAgentStore } from '../store/agentStore'
import { useWorkspaceStore } from '../store/workspaceStore'
import { startNewChat } from '../lib/newChat'

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

const useProductSuggestions = product.chat?.useSuggestions ?? (() => null)

function useSuggestionCards() {
  const custom = useProductSuggestions()
  if (custom) {
    return custom.map((s, i) => {
      const base = SUGGESTIONS[i % SUGGESTIONS.length]
      return {
        key: `custom-${i}`,
        title: s.title,
        text: s.text,
        prompt: s.prompt || s.text,
        icon: s.icon ?? base.icon,
        iconClass: base.iconClass,
        bgClass: base.bgClass,
      }
    })
  }
  return SUGGESTIONS.map(({ key, send, icon, iconClass, bgClass }) => {
    const text = t(`${key}_text` as Parameters<typeof t>[0])
    return { key, title: t(`${key}_title` as Parameters<typeof t>[0]), text, prompt: send ?? text, icon, iconClass, bgClass }
  })
}

const ChatPage: React.FC<ChatPageProps> = ({ baseUrl }) => {
  const activeId = useSessionStore((s) => s.activeId)
  const loadSessions = useSessionStore((s) => s.loadSessions)
  const activeAgentId = useAgentStore((s) => s.activeAgentId)

  const session = useChatStore((s) => s.sessions[activeId])
  const send = useChatStore((s) => s.send)
  const cancel = useChatStore((s) => s.cancel)
  const regenerate = useChatStore((s) => s.regenerate)
  const editUserMessage = useChatStore((s) => s.editUserMessage)
  const deleteMessage = useChatStore((s) => s.deleteMessage)
  const loadHistory = useChatStore((s) => s.loadHistory)
  const ensureSession = useChatStore((s) => s.ensureSession)
  const clearContext = useChatStore((s) => s.clearContext)
  const wsOnSessionSwitch = useWorkspaceStore((s) => s.onSessionSwitch)
  const suggestions = useSuggestionCards()

  const messages = session?.messages ?? []
  const isStreaming = session?.isStreaming ?? false

  const scrollRef = useRef<HTMLDivElement>(null)
  const bottomRef = useRef<HTMLDivElement>(null)
  const inputResetRef = useRef<ChatInputHandle>(null)
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()

  // The Agents page can hand the user straight into a group chat: it navigates
  // here with ?team=1 to pop the group-chat picker over the conversation. Clear
  // the flag once consumed so a back/refresh doesn't reopen it.
  const [teamOpen, setTeamOpen] = useState(false)
  useEffect(() => {
    if (searchParams.get('team') === '1') {
      setTeamOpen(true)
      searchParams.delete('team')
      setSearchParams(searchParams, { replace: true })
    }
  }, [searchParams, setSearchParams])

  // "Config" action on the context pie: jump to settings and flag the budget
  // field to scroll/highlight (read in BasicSettings on mount).
  const handleAdjustContext = useCallback(() => {
    sessionStorage.setItem('cow_focus_max_tokens', '1')
    navigate('/settings')
  }, [navigate])
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

  // History lives in the owner Agent's store. If the owner of the open
  // conversation changes under us (the roster resolved after the first load,
  // or the backend list corrected who owns it), what we loaded came from the
  // wrong store — fetch it again from the right one. Idle sessions only.
  const loadedOwnerRef = useRef<{ sid: string; owner: string } | null>(null)
  useEffect(() => {
    const owner = sessionOwner(activeId)
    const prev = loadedOwnerRef.current
    loadedOwnerRef.current = { sid: activeId, owner }
    // A session switch is handled by the effect above; only a same-session
    // owner change means the loaded history came from the wrong store.
    if (!prev || prev.sid !== activeId || prev.owner === owner) return
    // Unscoped (pre-roster) requests already read the default Agent's store.
    if (prev.owner === '' && owner === useAgentStore.getState().defaultAgentId) return
    const s = useChatStore.getState().sessions[activeId]
    if (s && !s.isStreaming) loadHistory(activeId, 1)
  }, [activeId, activeAgentId, loadHistory])

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
  // Id of the newest message: it changes when a message is appended, but not
  // when an older history page is prepended above the reader.
  const lastIdRef = useRef<string | undefined>(undefined)
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

    const lastId = messages[messages.length - 1]?.id
    if (lastSessionRef.current !== activeId) {
      lastSessionRef.current = activeId
      lastIdRef.current = lastId
      pendingSnapRef.current = true
      followBottomRef.current = true
    }

    if (pendingSnapRef.current) {
      // Instant snap on switch and on the first content that lands afterwards.
      lastIdRef.current = lastId
      scrollToBottom(false)
      if (messages.length > 0) pendingSnapRef.current = false
      return
    }

    const grew = lastId !== lastIdRef.current
    lastIdRef.current = lastId
    // A message-navigator jump owns the scroll position until it lands.
    if (useTimelineStore.getState().jumping) return

    const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 160
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
      // Resolve the owner before the await: the title request must land in the
      // same store the message did, even if the user switches meanwhile.
      const owner = sessionOwner(sid) || undefined
      await send(sid, text, attachments)
      // After the first message, refresh the list and ask backend to title it.
      if (isFirst) {
        try {
          await apiClient.generateSessionTitle(sid, text, undefined, owner)
        } catch {
          /* ignore */
        }
        loadSessions(1)
        titlePendingRef.current = false
      }
    },
    [activeId, send, loadSessions]
  )

  const handleNewChat = useCallback(async () => {
    // A new chat re-scopes the workspace panel, closing any open editor.
    if (!(await useWorkspaceStore.getState().guardUnsavedEdit())) return
    startNewChat()
  }, [])

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
    if (followBottomRef.current && !useTimelineStore.getState().jumping) scrollToBottom(false)
  }, [scrollToBottom])

  const handleScroll = useCallback(
    async (e: React.UIEvent<HTMLDivElement>) => {
      const el = e.currentTarget
      // Track whether the user wants to stay pinned to the bottom: scrolling up
      // pauses auto-follow; returning near the bottom resumes it.
      followBottomRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 160
      const s = useChatStore.getState().sessions[activeId]
      // A navigator jump loads the pages it needs itself.
      if (useTimelineStore.getState().jumping) return
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
  // A sent question only gets its seq once the turn is persisted, which leaves
  // the length unchanged, so the navigator keys on the persisted seqs too.
  const persistedUserSeqs = messages.filter((m) => m.role === 'user' && m.userSeq != null).length
  const timelineRevision = `${messages.length}:${persistedUserSeqs}`

  return (
    <div className="flex flex-col flex-1 min-h-0 relative">
      {!isEmpty && (
        <ChatTimeline sessionId={activeId} scrollRef={scrollRef} revision={timelineRevision} />
      )}
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

            {suggestions.length > 0 && (
              <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 w-full max-w-2xl">
                {suggestions.map(({ key, title, text, prompt, icon: Icon, iconClass, bgClass }) => (
                  <button
                    key={key}
                    onClick={() => {
                      // Fill the input (don't auto-send) so the user can tweak it first.
                      inputResetRef.current?.(prompt, [])
                    }}
                    className="group flex flex-col justify-start text-left bg-surface border border-default rounded-xl p-3.5 cursor-pointer hover:border-accent hover:shadow-sm transition-all"
                  >
                    <div className="flex items-center gap-2 mb-1.5">
                      <span
                        className={`w-7 h-7 rounded-lg flex items-center justify-center shrink-0 ${bgClass}`}
                      >
                        <Icon size={15} className={iconClass} />
                      </span>
                      <span className="font-medium text-sm text-content">{title}</span>
                    </div>
                    <p className="text-xs text-content-tertiary leading-relaxed line-clamp-2">{text}</p>
                  </button>
                ))}
              </div>
            )}
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
                  <span className="text-xs whitespace-nowrap">{msg.content || t('context_cleared')}</span>
                  <span
                    className="flex-1 h-px"
                    style={{ background: 'linear-gradient(to right, transparent, var(--border-strong), transparent)' }}
                  />
                </div>
              ) : (
                // Tag user bubbles with their seq so the navigation timeline
                // can locate and scroll to them on click.
                <div
                  key={msg.id}
                  data-user-seq={msg.role === 'user' && msg.userSeq != null ? msg.userSeq : undefined}
                >
                  <MessageBubble
                    message={msg}
                    // A teammate's bubble is part of the asking Agent's turn, not
                    // a turn of its own: regenerating it would re-run the whole
                    // turn, which the asking Agent's own bubble already offers.
                    onRegenerate={msg.extras?.peer ? undefined : handleRegenerate}
                    onEdit={handleEdit}
                    onDelete={handleDelete}
                    onMediaLoad={handleMediaLoad}
                  />
                </div>
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
        onAdjustContext={handleAdjustContext}
        ref={inputResetRef}
      />

      <TeamChatModal
        open={teamOpen}
        onClose={() => setTeamOpen(false)}
        onStarted={() => setTeamOpen(false)}
      />
    </div>
  )
}

export default ChatPage
