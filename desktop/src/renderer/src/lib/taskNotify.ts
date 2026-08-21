import { useSessionStore } from '../store/sessionStore'
import { useUIStore } from '../store/uiStore'
import { t } from '../i18n'

const SNIPPET_LIMIT = 80

/**
 * Fire the OS notification for a finished (or failed) agent run. Honors the
 * "task notify" settings; clicking the notification jumps to the session.
 */
export function notifyRunDone(sid: string, kind: 'done' | 'error', text: string): void {
  const { taskNotify, taskNotifySound } = useUIStore.getState()
  if (!taskNotify) return
  const prefix = t(kind === 'error' ? 'notify_task_error' : 'notify_task_done')
  const snippet = text.split('\n')[0].trim().slice(0, SNIPPET_LIMIT)
  // Omit title when there's no session name so the main process falls back to
  // app.name rather than a hardcoded product name.
  const title = useSessionStore.getState().sessions.find((s) => s.session_id === sid)?.title
  window.electronAPI
    ?.notify?.({
      title: title || undefined,
      body: snippet ? `${prefix}: ${snippet}` : prefix,
      sessionId: sid,
      silent: !taskNotifySound,
    })
    .catch(() => {})
}
