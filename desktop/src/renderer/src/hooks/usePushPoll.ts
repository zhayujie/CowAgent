import { useEffect } from 'react'
import apiClient from '../api/client'
import { useChatStore } from '../store/chatStore'
import { useSessionStore } from '../store/sessionStore'
import { useUIStore } from '../store/uiStore'

// Poll the active session for messages pushed outside the SSE stream (scheduler
// reminders, proactive pushes). Mirrors the web console: a live SSE reply is
// skipped server-side, so /poll only yields these out-of-band messages. Polls
// faster right after a hit, slower when idle.
const DELAY_HIT_MS = 5000
const DELAY_IDLE_MS = 10000

// Module-level guard so only ONE poll loop runs process-wide. /poll is a
// destructive get, so two loops (e.g. React StrictMode double-mounting the
// effect in dev) would steal messages from each other and drop notifications.
let loopActive = false

export function usePushPoll(ready: boolean): void {
  useEffect(() => {
    if (!ready || loopActive) return
    loopActive = true
    let cancelled = false
    let timer: ReturnType<typeof setTimeout> | null = null

    const schedule = (delay: number) => {
      if (cancelled) return
      timer = setTimeout(poll, delay)
    }

    async function poll() {
      if (cancelled) return
      // Keep polling while hidden: push messages are exactly what the OS
      // notification below should deliver to a background window.
      const sid = useSessionStore.getState().activeId
      if (!sid) {
        schedule(DELAY_IDLE_MS)
        return
      }
      try {
        const data = await apiClient.poll(sid)
        if (cancelled) return
        if (data.status === 'success' && data.has_content && data.content) {
          const added = useChatStore.getState().receivePush(sid, data.content, data.request_id)
          if (added) notify(sid, data.content)
          schedule(DELAY_HIT_MS)
          return
        }
      } catch {
        /* transient; keep polling */
      }
      schedule(DELAY_IDLE_MS)
    }

    poll()
    return () => {
      cancelled = true
      loopActive = false
      if (timer) clearTimeout(timer)
    }
  }, [ready])
}

function notify(sessionId: string, body: string): void {
  const { taskNotify, taskNotifySound } = useUIStore.getState()
  if (!taskNotify) return
  // Omit title when there's no session name so the main process falls back to
  // app.name rather than a hardcoded product name.
  const title = useSessionStore.getState().sessions.find((s) => s.session_id === sessionId)?.title
  window.electronAPI
    ?.notify?.({ title: title || undefined, body, sessionId, silent: !taskNotifySound })
    .catch(() => {})
}
