import React, { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import apiClient from '../api/client'
import { useChatStore } from '../store/chatStore'
import { sessionOwner } from '../store/sessionStore'
import { useTimelineStore } from '../store/timelineStore'
import type { UserMessageIndexEntry } from '../types'

// The rail stays a short column of dashes; the card lists every question.
const RAIL_MAX = 12
// Gap left above the question once the view lands on it.
const LAND_OFFSET = 16
const GLIDE_MS = 320

interface ChatTimelineProps {
  sessionId: string
  /** The scrollable conversation container, used to find bubbles and scroll. */
  scrollRef: React.RefObject<HTMLDivElement>
  /** Changes whenever the message list does, so the index is refetched after
   *  a turn is persisted, edited or deleted. */
  revision: string
}

const nextFrame = () => new Promise((r) => requestAnimationFrame(() => r(null)))

// Evenly sample down to RAIL_MAX dashes, keeping both ends.
function railIndexes(n: number): number[] {
  if (n <= RAIL_MAX) return Array.from({ length: n }, (_, i) => i)
  const step = (n - 1) / (RAIL_MAX - 1)
  return Array.from({ length: RAIL_MAX }, (_, k) => Math.round(k * step))
}

/**
 * Message navigator: a column of dashes on the right edge of the conversation,
 * one per question. Hovering it unfolds a card listing every question beside
 * it; picking one glides the view there.
 */
const ChatTimeline: React.FC<ChatTimelineProps> = ({ sessionId, scrollRef, revision }) => {
  const [items, setItems] = useState<UserMessageIndexEntry[]>([])
  const [activeSeq, setActiveSeq] = useState<number | null>(null)
  const [open, setOpen] = useState(false)
  const [railPos, setRailPos] = useState<{ right: number; top: number } | null>(null)
  const setJumping = useTimelineStore((s) => s.setJumping)

  const railRef = useRef<HTMLDivElement>(null)
  const panelRef = useRef<HTMLDivElement>(null)
  const listRef = useRef<HTMLDivElement>(null)
  const closeTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const glideRef = useRef(0)
  const jumpTokenRef = useRef(0)
  const fetchTokenRef = useRef(0)

  // Refetch the full question index on session switch and after every change
  // to the message list (a new turn adds a question, a delete removes one).
  useEffect(() => {
    const token = ++fetchTokenRef.current
    if (!sessionId) {
      setItems([])
      return
    }
    apiClient
      .getUserMessages(sessionId, sessionOwner(sessionId) || undefined)
      .then((res) => {
        if (token === fetchTokenRef.current && Array.isArray(res.messages)) setItems(res.messages)
      })
      .catch(() => {})
  }, [sessionId, revision])

  const stopGlide = useCallback(() => {
    if (glideRef.current) cancelAnimationFrame(glideRef.current)
    glideRef.current = 0
    if (scrollRef.current) scrollRef.current.style.overflowAnchor = ''
  }, [scrollRef])

  const endJump = useCallback(() => {
    stopGlide()
    setJumping(false)
  }, [stopGlide, setJumping])

  useEffect(() => {
    setOpen(false)
    setActiveSeq(null)
    jumpTokenRef.current++
    endJump()
  }, [sessionId, endJump])

  useEffect(() => () => endJump(), [endJump])

  // Which question the reader is at: the last user bubble above the upper
  // third of the viewport.
  const updateActive = useCallback(() => {
    const root = scrollRef.current
    if (!root) return
    const box = root.getBoundingClientRect()
    const line = box.top + box.height * 0.35
    const bubbles = Array.from(root.querySelectorAll<HTMLElement>('[data-user-seq]'))
    let seq: number | null = null
    for (const el of bubbles) {
      if (el.getBoundingClientRect().top <= line) seq = Number(el.dataset.userSeq)
      else break
    }
    if (seq === null && bubbles.length) seq = Number(bubbles[0].dataset.userSeq)
    setActiveSeq(seq)
  }, [scrollRef])

  useEffect(() => {
    const root = scrollRef.current
    if (!root) return
    let ticking = false
    const onScroll = () => {
      if (ticking) return
      ticking = true
      requestAnimationFrame(() => {
        ticking = false
        updateActive()
      })
    }
    // Keep the rail clear of the list's scrollbar (its width varies by OS) and
    // centred on the message list rather than on the list plus the composer.
    const place = () =>
      setRailPos({
        right: Math.max(0, root.offsetWidth - root.clientWidth) + 4,
        top: root.offsetTop + root.clientHeight / 2,
      })
    // Any gesture of the user's own takes the wheel back from a running glide.
    const gestures = ['wheel', 'touchstart', 'keydown', 'mousedown'] as const
    place()
    updateActive()
    root.addEventListener('scroll', onScroll, { passive: true })
    gestures.forEach((type) => root.addEventListener(type, endJump, { passive: true }))
    window.addEventListener('resize', place)
    return () => {
      root.removeEventListener('scroll', onScroll)
      gestures.forEach((type) => root.removeEventListener(type, endJump))
      window.removeEventListener('resize', place)
    }
  }, [scrollRef, updateActive, endJump, items, revision])

  const cancelClose = useCallback(() => {
    if (closeTimer.current) clearTimeout(closeTimer.current)
    closeTimer.current = null
  }, [])

  const scheduleClose = useCallback(() => {
    cancelClose()
    closeTimer.current = setTimeout(() => setOpen(false), 180)
  }, [cancelClose])

  useEffect(() => cancelClose, [cancelClose])

  const activeIndex = (() => {
    const i = items.findIndex((it) => it.seq === activeSeq)
    return i < 0 ? items.length - 1 : i
  })()

  // On open: sit beside the rail, vertically centred on it, and bring the
  // current question into view inside the list.
  useLayoutEffect(() => {
    const panel = panelRef.current
    const rail = railRef.current
    if (!open || !panel || !rail) return
    const r = rail.getBoundingClientRect()
    const h = panel.offsetHeight
    const mid = r.top + r.height / 2
    panel.style.right = `${Math.max(8, window.innerWidth - r.right)}px`
    panel.style.top = `${Math.max(8, Math.min(mid - h / 2, window.innerHeight - h - 8))}px`
    const list = listRef.current
    const row = list?.querySelector<HTMLElement>('.chat-timeline-row.is-active')
    if (list && row) list.scrollTop = row.offsetTop - list.clientHeight / 2 + row.offsetHeight / 2
    // Only on open: re-centring on every scroll tick would fight the reader.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])

  const findBubble = useCallback(
    (seq: number) => scrollRef.current?.querySelector<HTMLElement>(`[data-user-seq="${seq}"]`) ?? null,
    [scrollRef]
  )

  // Glide to a bubble. The target is re-measured every frame, so media or code
  // blocks that finish rendering mid-flight shift the landing spot instead of
  // leaving the view short and snapping back. A long hop starts a little way
  // off the target so the visible glide stays short.
  const glideTo = useCallback(
    (el: HTMLElement) => {
      const root = scrollRef.current
      if (!root) return endJump()
      stopGlide()
      // Freshly prepended bubbles keep growing for a few frames. Scroll
      // anchoring would answer each growth with a scroll of its own, after
      // ours, and the two tug the view back and forth; the glide already
      // tracks the target.
      root.style.overflowAnchor = 'none'
      const targetOf = () => {
        const y = el.getBoundingClientRect().top - root.getBoundingClientRect().top + root.scrollTop - LAND_OFFSET
        return Math.max(0, Math.min(y, root.scrollHeight - root.clientHeight))
      }
      const lead = root.clientHeight * 0.6
      let from = root.scrollTop
      const first = targetOf()
      if (Math.abs(first - from) > lead * 2) {
        from = first + (first > from ? -lead : lead)
        root.scrollTop = from
      }
      // Clocked from the first frame: a frame's timestamp is when it began,
      // which after a long task (a big history prepend) predates any
      // performance.now() taken before it, and a negative progress would
      // fling the view backwards.
      let started = 0
      let lastTarget = first
      const step = (now: number) => {
        if (!started) started = now
        const p = Math.min(1, (now - started) / GLIDE_MS)
        const eased = 1 - Math.pow(1 - p, 3)
        // Content above resized mid-flight: carry the start along with the
        // target so the glide keeps its direction instead of backing up.
        const target = targetOf()
        from += target - lastTarget
        lastTarget = target
        root.scrollTop = from + (target - from) * eased
        if (p < 1) {
          glideRef.current = requestAnimationFrame(step)
          return
        }
        stopGlide()
        setJumping(false)
        const bubble = el.querySelector<HTMLElement>('.bg-bubble-user') || el
        bubble.classList.remove('timeline-flash')
        void bubble.offsetWidth
        bubble.classList.add('timeline-flash')
        setTimeout(() => bubble.classList.remove('timeline-flash'), 1600)
      }
      glideRef.current = requestAnimationFrame(step)
    },
    [scrollRef, stopGlide, endJump, setJumping]
  )

  // Jump to a question. An old one may sit in a history page that isn't
  // loaded yet: fetch everything back to it in one request, holding the
  // viewport still while it prepends.
  const jumpTo = useCallback(
    async (seq: number) => {
      const token = ++jumpTokenRef.current
      stopGlide()
      setJumping(true)
      const target = sessionId
      let el = findBubble(seq)
      const s = useChatStore.getState().sessions[target]
      if (!el && s?.historyHasMore) {
        const root = scrollRef.current
        const prevHeight = root?.scrollHeight ?? 0
        const prevTop = root?.scrollTop ?? 0
        const hold = () => {
          if (root) root.scrollTop = prevTop + (root.scrollHeight - prevHeight)
        }
        await useChatStore.getState().loadHistory(target, (s.historyPage || 1) + 1, seq)
        // The store update usually commits synchronously; hold once now and
        // once after the next frame in case it landed a frame later.
        hold()
        await nextFrame()
        if (token !== jumpTokenRef.current) return
        hold()
        el = findBubble(seq)
      }
      if (token !== jumpTokenRef.current) return
      if (el) glideTo(el)
      else setJumping(false)
    },
    [findBubble, glideTo, scrollRef, sessionId, stopGlide, setJumping]
  )

  if (items.length < 2) return null

  const rail = railIndexes(items.length)
  let railActive = 0
  rail.forEach((idx, k) => {
    if (Math.abs(idx - activeIndex) < Math.abs(rail[railActive] - activeIndex)) railActive = k
  })

  return (
    <>
      <div
        ref={railRef}
        className={`chat-timeline${open ? ' is-open' : ''}`}
        style={railPos ? { right: railPos.right, top: railPos.top } : undefined}
        onMouseEnter={() => {
          cancelClose()
          setOpen(true)
        }}
        onMouseLeave={scheduleClose}
      >
        {rail.map((idx, k) => (
          <span key={idx} className={`chat-timeline-dash${k === railActive ? ' is-active' : ''}`} />
        ))}
      </div>

      {open && (
        <div ref={panelRef} className="chat-timeline-panel" onMouseEnter={cancelClose} onMouseLeave={scheduleClose}>
          <div ref={listRef} className="chat-timeline-list">
            {items.map((it, i) => (
              <button
                key={it.seq}
                type="button"
                className={`chat-timeline-row${i === activeIndex ? ' is-active' : ''}`}
                onClick={() => jumpTo(it.seq)}
              >
                <span className="chat-timeline-row-text">{it.preview}</span>
                <span className="chat-timeline-row-dash" />
              </button>
            ))}
          </div>
        </div>
      )}
    </>
  )
}

export default ChatTimeline
