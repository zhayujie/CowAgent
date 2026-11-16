import { useEffect } from 'react'
import apiClient from '../api/client'
import { notifyScheduledRun } from '../lib/taskNotify'
import { useUnreadStore } from '../store/unreadStore'

// Poll the GLOBAL runs ledger for scheduled executions, independent of which
// session is active. usePushPoll only watches the currently open session, so a
// scheduled task firing into any other session (the common case for reminders)
// would never surface. This loop asks "any scheduled execution since I last
// checked?" and is the SINGLE source of scheduler notifications: it forces a
// notice for every client-delivered execution — timer or manual "run now",
// current session or not — and dedupes by run id (usePushPoll deliberately
// stays silent for scheduler pushes). The delivered body is already persisted
// to the session history, so clicking the notification (open-session) loads it.
const POLL_INTERVAL_MS = 10000

// Module-level guard so only ONE loop runs process-wide (StrictMode double-mount
// in dev, or the hook accidentally mounted twice, would otherwise notify twice).
let loopActive = false

// Runs we've already notified for, so overlapping polls (or a run that lingers
// in the `since` window across two ticks) never double-fire a notification.
const notifiedRunIds = new Set<string>()

export function useSchedulerNotifyPoll(ready: boolean): void {
  useEffect(() => {
    if (!ready || loopActive) return
    loopActive = true
    let cancelled = false
    let timer: ReturnType<typeof setTimeout> | null = null
    // Ignore anything that ran before this client came up: on first tick we only
    // want NEW executions, not a backlog of history replayed as notifications.
    let since = Math.floor(Date.now() / 1000)

    const schedule = () => {
      if (cancelled) return
      timer = setTimeout(tick, POLL_INTERVAL_MS)
    }

    async function tick() {
      if (cancelled) return
      try {
        const runs = await apiClient.getSchedulerRunsSince(since, 20)
        if (cancelled) return
        // Oldest first so `since` advances monotonically and notifications
        // arrive in execution order.
        const ordered = runs
          .slice()
          .sort((a, b) => (a.started_at || 0) - (b.started_at || 0))
        for (const run of ordered) {
          if (run.started_at && run.started_at > since) since = run.started_at
          maybeNotify(run)
        }
      } catch {
        /* transient; keep polling */
      }
      schedule()
    }

    tick()
    return () => {
      cancelled = true
      loopActive = false
      if (timer) clearTimeout(timer)
    }
  }, [ready])
}

function maybeNotify(run: {
  run_id?: string
  session_id?: string
  status?: string
  channel_type?: string
  task_name?: string
  output_preview?: string
}): void {
  const sid = run.session_id
  if (!sid) return
  // Only client-delivered tasks: WeChat/Feishu etc. already push into the IM
  // app, so re-notifying in the desktop client would be noise.
  const channel = run.channel_type || ''
  if (channel && channel !== 'web') return
  // Skip failed runs — nothing was delivered to jump to.
  if (run.status && run.status !== 'done') return
  // Dedupe: a run can appear in two overlapping poll windows.
  const runId = run.run_id || ''
  if (runId) {
    if (notifiedRunIds.has(runId)) return
    notifiedRunIds.add(runId)
    // Bound memory for long-lived clients with frequent tasks; the poll only
    // looks back a short window, so trimmed ids can never reappear.
    if (notifiedRunIds.size > 500) {
      const drop = notifiedRunIds.size - 500
      let i = 0
      for (const id of notifiedRunIds) {
        if (i++ >= drop) break
        notifiedRunIds.delete(id)
      }
    }
  }
  // Always force a notification, even for the currently-open session and for
  // manual "run now": a scheduled execution should announce itself wherever the
  // user is. usePushPoll deliberately skips notifying for scheduler pushes so
  // this is the single source of scheduler notifications (no double-fire).
  notifyScheduledRun(sid, run.task_name || '', run.output_preview || '')
  useUnreadStore.getState().mark(sid)
}
