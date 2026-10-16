import React, { useEffect, useMemo, useRef, useCallback, useState } from 'react'
import {
  ChevronDown,
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
import TodoPanel from '../components/TodoPanel'
import { todoOwner } from '../store/chatStore'
import { todoScope, useTodoStore } from '../store/todoStore'
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
import { followingAfterUserScroll, shouldApplyBottomScroll, shouldFollowContentChange, shouldShowScrollToBottom } from '../lib/chatScroll'

interface ChatPageProps {
  baseUrl: string
}

// Welcome-screen suggestion cards (aligned with the web console: 6 cards).
// `send` overrides the text dropped into the input (e.g. show "View all commands"
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

  const defaultAgentId = useAgentStore((s) => s.defaultAgentId)
  const planScope = todoScope(todoOwner(activeId), activeId)
  const todoSnapshot = useTodoStore(s => planScope ? s.snapshots[planScope] : undefined)
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
  const isEmpty = messages.length === 0

  const scrollRef = useRef<HTMLDivElement>(null)
  const followBottomRef = useRef(true)
  const userScrollDirectionRef = useRef<'up' | 'down' | 'scrollbar' | null>(null)
  const touchStartYRef = useRef<number | null>(null)
  const programmaticScrollRef = useRef(false)
  const programmaticScrollTopRef = useRef<number | null>(null)
  const contentRef = useRef<HTMLDivElement>(null)
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

  const [showScrollToBottom, setShowScrollToBottom] = useState(false)
  const scrollFrameRef = useRef<number | null>(null)
  const previousScrollTopRef = useRef(0)
  const scrollSessionRef = useRef('')
  const bottomScrollRef = useRef<() => void>(() => {})

  const updateScrollButton = useCallback((el: HTMLDivElement, following = followBottomRef.current) => {
    setShowScrollToBottom(shouldShowScrollToBottom(following, {
      scrollTop: el.scrollTop,
      scrollHeight: el.scrollHeight,
      clientHeight: el.clientHeight,
    }))
  }, [])

  const cancelQueuedScroll = useCallback(() => {
    if (scrollFrameRef.current !== null) {
      cancelAnimationFrame(scrollFrameRef.current)
      scrollFrameRef.current = null
    }
  }, [])

  const scrollToBottom = useCallback((force = false) => {
    const el = scrollRef.current
    if (force) {
      followBottomRef.current = true
      useTimelineStore.getState().setJumping(false)
    }
    if (!el || (!force && (!followBottomRef.current || useTimelineStore.getState().jumping))) {
      if (el) updateScrollButton(el)
      return
    }
    if (force) cancelQueuedScroll()
    if (scrollFrameRef.current !== null) return
    const sid = activeId
    const apply = () => {
      scrollFrameRef.current = null
      const current = scrollRef.current
      if (!current || !shouldApplyBottomScroll({
        following: followBottomRef.current,
        jumping: useTimelineStore.getState().jumping,
        currentSession: scrollSessionRef.current,
        scheduledSession: sid,
      })) {
        if (current) updateScrollButton(current)
        return
      }
      const target = Math.max(0, current.scrollHeight - current.clientHeight)
      if (Math.abs(current.scrollTop - target) > 1) {
        programmaticScrollRef.current = true
        programmaticScrollTopRef.current = target
        current.scrollTop = target
      }
      previousScrollTopRef.current = current.scrollTop
      updateScrollButton(current)
    }
    if (force) {
      const target = Math.max(0, el.scrollHeight - el.clientHeight)
      if (Math.abs(el.scrollTop - target) > 1) {
        programmaticScrollRef.current = true
        programmaticScrollTopRef.current = target
        el.scrollTop = target
      }
      previousScrollTopRef.current = el.scrollTop
      updateScrollButton(el)
      return
    }
    scrollFrameRef.current = requestAnimationFrame(apply)
  }, [activeId, cancelQueuedScroll, updateScrollButton])
  bottomScrollRef.current = () => scrollToBottom(true)

  // Snap to the bottom instantly when switching sessions (no top-to-bottom animation).
  // History may load a frame later, so keep snapping instantly until content arrives.
  const lastSessionRef = useRef('')
  // Id of the newest message: it changes when a message is appended, but not
  // when an older history page is prepended above the reader.
  const lastIdRef = useRef<string | undefined>(undefined)
  const pendingSnapRef = useRef(false)
  // Follow intent changes only from user scrolling or explicit return-to-bottom.
  // Tracks the previous streaming state so we can do one final snap to the
  // bottom right when streaming ends (the last chunk of a long command output
  // often lands together with isStreaming flipping to false).
  const wasStreamingRef = useRef(false)

  // The task card and input occupy layout space. Keep an already-following
  // conversation pinned when their height changes, without moving a reader.
  useEffect(() => {
    const viewport = scrollRef.current
    if (!viewport) return
    let observedContent: HTMLDivElement | null = null
    const observer = new ResizeObserver(() => {
      if (shouldFollowContentChange(followBottomRef.current, useTimelineStore.getState().jumping)) scrollToBottom()
      else updateScrollButton(viewport)
    })
    observer.observe(viewport)
    const syncContent = () => {
      const content = contentRef.current
      if (content === observedContent) return
      if (observedContent) observer.unobserve(observedContent)
      observedContent = content
      if (content) observer.observe(content)
    }
    syncContent()
    const mutation = new MutationObserver(syncContent)
    mutation.observe(viewport, { childList: true, subtree: true })
    return () => {
      mutation.disconnect()
      observer.disconnect()
      cancelQueuedScroll()
    }
  }, [cancelQueuedScroll, scrollToBottom, updateScrollButton])

  useEffect(() => {
    const el = scrollRef.current
    if (!el) return

    const lastId = messages[messages.length - 1]?.id
    if (lastSessionRef.current !== activeId) {
      lastSessionRef.current = activeId
      scrollSessionRef.current = activeId
      lastIdRef.current = lastId
      pendingSnapRef.current = true
      followBottomRef.current = true
      previousScrollTopRef.current = el.scrollTop
      cancelQueuedScroll()
      setShowScrollToBottom(false)
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

    const justFinished = wasStreamingRef.current && !isStreaming
    wasStreamingRef.current = isStreaming
    if (grew || isStreaming || justFinished || followBottomRef.current) scrollToBottom()
    else updateScrollButton(el)
  }, [messages, activeId, isStreaming, cancelQueuedScroll, scrollToBottom, updateScrollButton])

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
          const res = await apiClient.generateSessionTitle(sid, text, undefined, owner)
          if (res.status === 'success' && res.title) {
            useSessionStore.setState((s) => ({
              sessions: s.sessions.map((x) => (x.session_id === sid ? { ...x, title: res.title } : x)),
            }))
          }
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
      if (shouldFollowContentChange(followBottomRef.current, useTimelineStore.getState().jumping)) scrollToBottom()
    }, [scrollToBottom])

  const handleUserScrollIntent = useCallback((direction: 'up' | 'down' | 'scrollbar') => {
    userScrollDirectionRef.current = direction
    if (direction === 'up') {
      followBottomRef.current = false
      cancelQueuedScroll()
      const el = scrollRef.current
      if (el) updateScrollButton(el, false)
    } else {
      const el = scrollRef.current
      if (el) {
        if (el.scrollHeight - el.scrollTop - el.clientHeight <= 48) followBottomRef.current = true
        updateScrollButton(el)
      }
    }
  }, [cancelQueuedScroll, updateScrollButton])

  const handleScroll = useCallback(
    async (e: React.UIEvent<HTMLDivElement>) => {
      const el = e.currentTarget
      const intent = userScrollDirectionRef.current
      if (programmaticScrollRef.current && intent === null) {
        programmaticScrollRef.current = false
        programmaticScrollTopRef.current = null
      } else if (intent !== null) {
        const direction = intent === 'scrollbar'
          ? (el.scrollTop < previousScrollTopRef.current - 1 ? 'up' : el.scrollTop > previousScrollTopRef.current + 1 ? 'down' : null)
          : intent
        if (direction !== null) {
          followBottomRef.current = followingAfterUserScroll(followBottomRef.current, direction, {
            scrollTop: el.scrollTop, scrollHeight: el.scrollHeight, clientHeight: el.clientHeight,
          })
        }
        if (!followBottomRef.current) cancelQueuedScroll()
        programmaticScrollRef.current = false
        programmaticScrollTopRef.current = null
      }
      userScrollDirectionRef.current = null
      previousScrollTopRef.current = el.scrollTop
      updateScrollButton(el)
      const s = useChatStore.getState().sessions[activeId]
      // Explicit user input takes ownership from an in-flight timeline jump.
      if (intent !== null && useTimelineStore.getState().jumping) {
        cancelQueuedScroll()
        useTimelineStore.getState().setJumping(false)
      }
      // A navigator jump loads the pages it needs itself.
      if (useTimelineStore.getState().jumping) return
      if (el.scrollTop < 40 && s?.historyHasMore && !loadingMore && !isStreaming) {
        setLoadingMore(true)
        const prevHeight = el.scrollHeight
        await loadHistory(activeId, s.historyPage + 1)
          requestAnimationFrame(() => {
            // Preserve scroll position after prepending older messages. This is
            // layout compensation, not a new user scroll intent.
            const target = Math.max(0, el.scrollHeight - prevHeight)
            if (Math.abs(el.scrollTop - target) > 1) {
              programmaticScrollRef.current = true
              programmaticScrollTopRef.current = target
              el.scrollTop = target
            }
            previousScrollTopRef.current = el.scrollTop
            updateScrollButton(el)
            setLoadingMore(false)
          })
      }
    },
    [activeId, cancelQueuedScroll, loadHistory, loadingMore, isStreaming, updateScrollButton]
  )

  // A sent question only gets its seq once the turn is persisted, which leaves
  // the length unchanged, so the navigator keys on the persisted seqs too.
  const persistedUserSeqs = messages.filter((m) => m.role === 'user' && m.userSeq != null).length
  const timelineRevision = `${messages.length}:${persistedUserSeqs}`
  // Each message's turn: the seq of the question that opened it.
  const turnSeqs = useMemo(() => {
    let turn: number | null = null
    return messages.map((m) => {
      if (m.role === 'user') turn = m.userSeq ?? null
      return turn
    })
  }, [messages])

  return (
    <div className="flex flex-col flex-1 min-h-0 relative">
      {!isEmpty && (
        <ChatTimeline sessionId={activeId} scrollRef={scrollRef} revision={timelineRevision} />
      )}
      <div
        ref={scrollRef}
        className="relative min-h-0 flex-1 overflow-y-auto"
        onScroll={handleScroll}
        onWheel={e => { if (e.deltaY < 0) handleUserScrollIntent('up'); else if (e.deltaY > 0) handleUserScrollIntent('down') }}
        onTouchStart={e => { touchStartYRef.current = e.touches[0]?.clientY ?? null }}
        onTouchMove={e => {
          const start = touchStartYRef.current
          const current = e.touches[0]?.clientY
          if (start !== null && current !== undefined && Math.abs(current - start) > 2) {
            handleUserScrollIntent(current > start ? 'up' : 'down')
          }
        }}
        onTouchEnd={() => { touchStartYRef.current = null }}
        onKeyDown={e => {
          if (['ArrowUp', 'PageUp', 'Home'].includes(e.key)) handleUserScrollIntent('up')
          else if (['ArrowDown', 'PageDown', 'End', ' '].includes(e.key)) handleUserScrollIntent('down')
        }}
        onPointerDown={e => {
          const el = scrollRef.current
          if (el && e.target === el && e.clientX >= el.getBoundingClientRect().right - 16) handleUserScrollIntent('scrollbar')
        }}
      >
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
          <div ref={contentRef} className="py-3 max-w-3xl mx-auto">
            {messages.map((msg, i) =>
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
                    turnSeq={turnSeqs[i]}
                  />
                </div>
              )
            )}
          </div>
        )}
        {showScrollToBottom && (
          <button
            type="button"
            title={t('chat_scroll_to_bottom')}
            aria-label={t('chat_scroll_to_bottom')}
            onClick={() => bottomScrollRef.current()}
            className="sticky bottom-3 z-20 mx-auto -mt-9 flex h-9 w-9 shrink-0 items-center justify-center rounded-full border border-default bg-surface text-content-secondary shadow-md transition-colors hover:bg-surface-2 hover:text-content focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
          >
            <ChevronDown size={16} aria-hidden="true" />
          </button>
        )}
      </div>

      <div className="shrink-0">
        <ChatInput
          aboveInput={todoSnapshot?.todos.length ? <TodoPanel snapshot={todoSnapshot} /> : undefined}
          onSend={handleSend}
          onNewChat={handleNewChat}
          onStop={handleStop}
          onClearContext={handleClearContext}
          isStreaming={isStreaming}
          sessionId={activeId}
          onAdjustContext={handleAdjustContext}
          ref={inputResetRef}
        />
      </div>

      <TeamChatModal
        open={teamOpen}
        onClose={() => setTeamOpen(false)}
        onStarted={() => setTeamOpen(false)}
      />
    </div>
  )
}

export default ChatPage
