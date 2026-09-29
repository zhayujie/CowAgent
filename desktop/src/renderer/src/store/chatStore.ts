import { create } from 'zustand'
import apiClient from '../api/client'
import { useWorkspaceStore } from './workspaceStore'
import { sessionOwner } from './sessionStore'
import { cfgFor } from './sessionSettingsStore'
import { findAgent } from './agentStore'
import { notifyRunDone } from '../lib/taskNotify'
import { parseAttachmentMarkers } from '../lib/fileKind'
import { handoffPayload } from '../lib/handoff'
import { t } from '../i18n'
import type { Artifact, ChatMessage, MessageStep, Attachment, StreamEvent, HistoryMessage, AgentBadge, ContextUsage } from '../types'

// Result of a synchronous context compaction (mirrors the backend payload).
export interface CompactResult {
  ok: boolean
  noop: boolean
  before: number
  after: number
  usage: ContextUsage | null
}

/**
 * Per-session chat state. Supports parallel sessions: each session keeps its
 * own message list and active stream, so switching sessions never interrupts a
 * background run. The active EventSource lives in `streams` (outside React).
 */

interface SessionRuntime {
  messages: ChatMessage[]
  isStreaming: boolean
  requestId: string | null
  // history pagination
  historyPage: number
  historyHasMore: boolean
  historyLoaded: boolean
}

interface ChatState {
  sessions: Record<string, SessionRuntime>

  getSession: (sid: string) => SessionRuntime
  ensureSession: (sid: string) => void

  send: (sid: string, text: string, attachments: Attachment[]) => Promise<void>
  cancel: (sid: string) => Promise<void>
  regenerate: (sid: string, botMessageId: string) => Promise<void>
  editUserMessage: (sid: string, messageId: string) => { text: string; attachments: Attachment[] } | null
  deleteMessage: (sid: string, userSeq: number, cascade: boolean) => Promise<void>

  /** With untilSeq, loads every page from `page` back to the one holding that
   *  message in a single request. Resolves false when it could not be fetched. */
  loadHistory: (sid: string, page?: number, untilSeq?: number) => Promise<boolean>
  clearContext: (sid: string) => Promise<boolean>
  // Synchronous context compaction. On success a divider is appended to the
  // thread; the raw result is returned so the caller can refresh the pie and
  // surface noop/failure toasts.
  compactContext: (sid: string) => Promise<CompactResult>
  clearLocal: (sid: string) => void

  // Append a server-pushed message (scheduler/push) polled outside the SSE
  // stream. Deduped by requestId so a reply already on screen isn't repeated.
  receivePush: (sid: string, content: string, requestId?: string) => boolean
}

// EventSource instances kept outside the store (not serializable).
const streams: Record<string, EventSource> = {}

// A backend restarting after a crash is back within seconds; after a minute
// the history is left to load on the next visit to the session.
const RELOAD_AFTER_DROP_ATTEMPTS = 30
const RELOAD_AFTER_DROP_INTERVAL_MS = 2000

// A reply running with no stream here (the window was reloaded mid-reply, or
// its stream dropped while the backend went on) is followed by rereading the
// history until it ends.
const FOLLOW_RUNNING_INTERVAL_MS = 3000
const followTimers: Record<string, ReturnType<typeof setTimeout>> = {}

const EMPTY: SessionRuntime = {
  messages: [],
  isStreaming: false,
  requestId: null,
  historyPage: 0,
  historyHasMore: false,
  historyLoaded: false,
}

function uid(prefix: string): string {
  return `${prefix}_${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`
}

/**
 * History keeps the English cancel marker for the LLM; strip it for display so
 * the bubble shows a clean answer + a dedicated "cancelled" badge instead.
 */
function stripCancelMarker(text: string): string {
  if (!text) return text
  return text
    .replace(/_\(Cancelled by user\)_/g, '')
    .replace(/_\(Cancelled\)_/g, '')
    .trim()
}

function hasCancelMarker(text: string): boolean {
  return /_\(Cancelled(?: by user)?\)_/.test(text || '')
}

/**
 * Everyone addressable in a conversation, owner first: the owner plus any
 * invited teammates. Empty outside a group chat.
 */
function sessionRoster(sid: string): AgentBadge[] {
  const team = cfgFor(sid)?.team
  if (!team || !team.members?.length) return []
  const roster: AgentBadge[] = [team.owner]
  for (const m of team.members) {
    if (!roster.some((a) => a.id === m.id)) roster.push(m)
  }
  return roster
}

/**
 * The teammate a message hands the turn to, or '' for nobody. Mirrors the
 * server's rule: only a leading mention counts (naming someone mid-sentence is
 * talking *about* them), matched by display name or id, longest label first so
 * a name containing another name still resolves to the one written.
 */
function addressedAgentId(text: string, roster: AgentBadge[]): string {
  const stripped = (text || '').replace(/^\s+/, '')
  if (!stripped.startsWith('@') || roster.length < 2) return ''
  const labels: Array<[string, string]> = []
  for (const a of roster) {
    for (const label of [a.name, a.id]) {
      if (label) labels.push([String(label), a.id])
    }
  }
  labels.sort((x, y) => y[0].length - x[0].length)
  for (const [label, id] of labels) {
    const re = new RegExp(`^@${label.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}(?=[\\s，,：:、]|$)`, 'i')
    if (re.test(stripped)) return id
  }
  return ''
}

const SUBSTEP_ARGS_CHARS = 90

/** Tool arguments on one line, for a step in a list of dozens. */
function summarizeArgs(args?: Record<string, unknown>): string {
  if (!args || typeof args !== 'object') return ''
  const joined = Object.entries(args)
    .map(([key, value]) => `${key}=${typeof value === 'object' ? JSON.stringify(value) : String(value)}`)
    .join(', ')
  return joined.length > SUBSTEP_ARGS_CHARS ? joined.slice(0, SUBSTEP_ARGS_CHARS) + '…' : joined
}

/**
 * Rebuild attachments from `send`-tool results persisted in the message steps.
 * SSE `file_to_send` events aren't stored, so on history reload the only record
 * of a sent image/file is the tool result JSON. Mirrors the web console's
 * `_renderSentFileFromToolResult` so media survives an app restart.
 */
function attachmentsFromSteps(steps: MessageStep[]): Attachment[] {
  const out: Attachment[] = []
  for (const s of steps) {
    if (s.type !== 'tool' || !s.result) continue
    let payload: Record<string, unknown>
    try {
      payload = typeof s.result === 'string' ? JSON.parse(s.result) : (s.result as unknown as Record<string, unknown>)
    } catch {
      continue
    }
    if (!payload || payload.type !== 'file_to_send') continue
    const rawPath = (payload.path as string) || ''
    const url = (payload.url as string) || ''
    if (!rawPath && !url) continue
    const isRemote = url.toLowerCase().startsWith('http://') || url.toLowerCase().startsWith('https://')
    // Local files are served via /api/file; remote URLs are used directly.
    const previewUrl = isRemote
      ? url
      : rawPath.toLowerCase().startsWith('http')
        ? rawPath
        : apiClient.getServeFileUrl(rawPath)
    const kind = (payload.file_type as string) || 'file'
    const fileType: Attachment['file_type'] =
      kind === 'image' ? 'image' : kind === 'video' ? 'video' : 'file'
    out.push({
      file_path: previewUrl,
      file_name: (payload.file_name as string) || 'file',
      file_type: fileType,
      preview_url: previewUrl,
      abs_path: isRemote ? undefined : rawPath,
    })
  }
  return out
}

/**
 * The bubbles one stored message was shown as while it streamed.
 *
 * A hand-off is stored as an `agent_delegate` step inside the asking Agent's
 * turn, but it was watched as the teammate answering in a bubble of its own.
 * Replaying it as a card would tell a different story from the one that was
 * watched, so split the turn back apart: what the Agent did up to the
 * hand-off, the teammate's reply, then whatever the Agent said next. Anything
 * without a hand-off comes back as the single message it always was.
 */
function historyToMessages(m: HistoryMessage): ChatMessage[] {
  const steps = m.steps || []
  if (m.role === 'user' || !steps.some(handoffPayload)) return [historyToMessage(m)]

  const out: ChatMessage[] = []
  let pending: MessageStep[] = []
  for (const step of steps) {
    pending.push(step)
    const payload = handoffPayload(step)
    if (!payload) continue
    // What the Agent did up to and including asking for help. The answer, the
    // artifacts, the seq and an unfinished run's state belong to the turn's
    // last bubble, not this one.
    out.push(
      historyToMessage({
        ...m, steps: pending, content: '', artifacts: undefined, _seq: undefined, run_state: undefined,
      })
    )
    out.push({
      id: uid('assistant'),
      role: 'assistant',
      content: payload.content,
      timestamp: m.created_at,
      extras: { agent_id: payload.agent_id, peer: true },
    })
    pending = []
  }
  if (pending.length || (m.content || '').trim() || m.run_state) {
    out.push(historyToMessage({ ...m, steps: pending }))
  }
  return out
}

/** Convert a backend history message into a UI ChatMessage. */
function historyToMessage(m: HistoryMessage): ChatMessage {
  if (m.role === 'user') {
    // History persists only the prompt text, so the attachment chips have to be
    // recovered from the `[label: path]` markers appended to it.
    const { text, attachments } = parseAttachmentMarkers(m.content)
    return {
      id: uid('user'),
      role: 'user',
      content: text,
      timestamp: m.created_at,
      userSeq: m._seq,
      attachments,
    }
  }

  // A stopped reply keeps the cancel marker for the LLM; it shows as a status
  // line instead. Stopped with nothing said, cut off, or still running, a reply
  // has no answer, so every text it has stays a step.
  const cancelled = hasCancelMarker(m.content)
  const answer = stripCancelMarker(m.content || '')
  const unanswered = !!m.run_state || (cancelled && !answer)
  const raw = (m.steps || []).filter(
    (s) => !(s.type === 'content' && hasCancelMarker(s.content || '') && !stripCancelMarker(s.content || ''))
  )

  // The backend stores the final answer both as `content` and as the LAST
  // `content` step. Strip that trailing content step so it isn't rendered
  // twice (matches the web console's renderStepsHtml logic).
  let lastContentIdx = -1
  for (let i = raw.length - 1; i >= 0 && !unanswered; i--) {
    if (raw[i].type === 'content') {
      lastContentIdx = i
      break
    }
  }
  const steps: MessageStep[] = raw
    .filter((_, i) => i !== lastContentIdx)
    .map((s) => ({ ...s }))
  const finalContent = unanswered
    ? ''
    : answer || (lastContentIdx >= 0 ? stripCancelMarker(raw[lastContentIdx].content || '') : '')
  const attachments = attachmentsFromSteps(raw)
  // Artifacts are rebuilt by the backend, which alone knows the workspace root.
  const artifacts = m.artifacts || []

  return {
    id: uid('assistant'),
    role: 'assistant',
    content: finalContent,
    timestamp: m.created_at,
    steps,
    reasoning: m.reasoning,
    kind: m.kind,
    extras: m.extras,
    botSeq: m._seq,
    isCancelled: cancelled || undefined,
    runState: m.run_state,
    attachments: attachments.length > 0 ? attachments : undefined,
    artifacts: artifacts.length > 0 ? artifacts : undefined,
  }
}

export const useChatStore = create<ChatState>((set, get) => {
  // --- helpers operating on a single session immutably ---
  const patchSession = (sid: string, patch: Partial<SessionRuntime>) =>
    set((st) => ({
      sessions: { ...st.sessions, [sid]: { ...(st.sessions[sid] || EMPTY), ...patch } },
    }))

  const patchMessages = (sid: string, fn: (msgs: ChatMessage[]) => ChatMessage[]) =>
    set((st) => {
      const cur = st.sessions[sid] || EMPTY
      return { sessions: { ...st.sessions, [sid]: { ...cur, messages: fn(cur.messages) } } }
    })

  const updateMsg = (sid: string, id: string, fn: (m: ChatMessage) => ChatMessage) =>
    patchMessages(sid, (msgs) => msgs.map((m) => (m.id === id ? fn(m) : m)))

  /** Attach an EventSource for a request and wire all SSE events to a bot message. */
  const attachStream = (sid: string, requestId: string, botId: string) => {
    const es = apiClient.createSSEStream(requestId)
    streams[sid] = es
    let tailTimer: ReturnType<typeof setTimeout> | null = null
    // Set on a user-initiated cancel so a trailing error event doesn't fire a
    // spurious "task failed" notification.
    let userCancelled = false
    // Set once the run reports its end; a stream closing before that dropped.
    let ended = false

    // A turn can change hands. Work handed to a teammate is answered by that
    // teammate in a bubble of its own, and the Agent that asked resumes in a
    // fresh one below it. `main` is the asking Agent's bubble, `peers` the
    // teammates currently holding the floor (a teammate may hand on again).
    type Speaker = { id: string; agentId?: string }
    let main: Speaker = { id: botId }
    const peers: Speaker[] = []
    // Set when the floor comes back, so the next thing said opens a new bubble
    // instead of reopening the one the teammate's reply now sits below.
    let resumed = false

    const openBubble = (agentId?: string): Speaker => {
      const id = uid('assistant')
      patchMessages(sid, (msgs) => [
        ...msgs,
        {
          id,
          role: 'assistant',
          content: '',
          timestamp: Date.now(),
          isStreaming: true,
          // `peer` marks a bubble as part of someone else's turn rather than a
          // turn of its own, which is what the regenerate affordance acts on.
          extras: agentId ? { agent_id: agentId, peer: true } : undefined,
        },
      ])
      return { id, agentId }
    }

    /** The bubble whoever is speaking writes into. */
    const speaking = (): string => {
      const cur = peers[peers.length - 1] || main
      if (!resumed) return cur.id
      resumed = false
      const next = openBubble(cur.agentId)
      if (peers.length) peers[peers.length - 1] = next
      else main = next
      return next.id
    }

    /**
     * Update whichever bubble owns a tool card.
     *
     * A hand-off's card outlives the teammate's turn: the floor comes back
     * before the call returns, so by the time it reports the card is no longer
     * on the bubble in hand.
     */
    const updateCard = (stepId: string | undefined, fn: (m: ChatMessage) => ChatMessage) => {
      if (!stepId) return
      patchMessages(sid, (msgs) =>
        msgs.map((m) =>
          (m.steps || []).some((s) => s.type === 'tool' && s.id === stepId) ? fn(m) : m
        )
      )
    }

    const closeStream = () => {
      if (tailTimer) {
        clearTimeout(tailTimer)
        tailTimer = null
      }
      es.close()
      if (streams[sid] === es) delete streams[sid]
    }

    // A stream the user stopped keeps running detached from its session (see
    // `cancel`): only what its steps did still lands.
    const detached = () => streams[sid] !== es

    // Mark the turn as complete: UI becomes interactive again immediately.
    const completeTurn = () => {
      if (!detached()) patchSession(sid, { isStreaming: false, requestId: null })
      // Every bubble the turn was spoken in, not just the one it started in.
      const ids = new Set([botId, main.id, ...peers.map((p) => p.id)])
      patchMessages(sid, (msgs) =>
        msgs.map((m) => (ids.has(m.id) ? { ...m, isStreaming: false } : m))
      )
    }

    const finishStream = () => {
      completeTurn()
      closeStream()
    }

    es.onmessage = (event) => {
      let data: StreamEvent
      try {
        data = JSON.parse(event.data)
      } catch {
        return // keepalive
      }
      // Stopped: nothing more is said, but a step already running still ends.
      if (detached() && (data.type === 'delta' || data.type === 'reasoning')) return

      switch (data.type) {
        case 'reasoning':
          updateMsg(sid, speaking(), (m) => ({ ...m, reasoning: (m.reasoning || '') + (data.content || '') }))
          break

        case 'delta':
          updateMsg(sid, speaking(), (m) => ({ ...m, content: m.content + (data.content || '') }))
          break

        // A teammate given work answers as itself: its reply, reasoning and
        // tool calls arrive as the same events as anyone's, bracketed by this
        // pair. Tagging the bubble with its id is what puts its face on it.
        case 'peer_start':
          if (!data.agent_id) break
          peers.push(openBubble(data.agent_id))
          break

        case 'peer_end': {
          const done = peers.pop()
          if (done) updateMsg(sid, done.id, (m) => ({ ...m, isStreaming: false }))
          resumed = true
          break
        }

        case 'message_end':
          // Freeze accumulated text as a content step when tool calls follow,
          // mirroring the web console's interleaved step model.
          if (data.has_tool_calls) {
            updateMsg(sid, speaking(), (m) => {
              if (!m.content.trim()) return m
              const steps = [...(m.steps || []), { type: 'content' as const, content: m.content.trim() }]
              return { ...m, steps, content: '' }
            })
          }
          break

        case 'tool_retrieval':
          updateMsg(sid, speaking(), (m) => ({
            ...m,
            steps: [
              ...(m.steps || []),
              {
                type: 'retrieval',
                retrieval: {
                  mode: data.mode === 'fallback' ? 'fallback' : 'retrieved',
                  total_mcp_tools: data.total_mcp_tools || 0,
                  selected_mcp_tools: data.selected_mcp_tools || 0,
                  builtin_tools: data.builtin_tools || 0,
                  top_k: data.top_k || 0,
                  candidate_count: data.candidate_count || 0,
                  selected_tools: data.selected_tools || [],
                  ranked_tools: data.ranked_tools || [],
                  fallback_reason: data.fallback_reason,
                },
              },
            ],
          }))
          break

        case 'tool_start':
          updateMsg(sid, speaking(), (m) => {
            // commit any reasoning into a thinking step
            const steps = [...(m.steps || [])]
            if (m.reasoning && m.reasoning.trim()) {
              steps.push({ type: 'thinking', content: m.reasoning.trim() })
            }
            steps.push({
              type: 'tool',
              id: data.tool_call_id,
              name: data.tool,
              arguments: data.arguments,
              status: 'running',
            })
            return { ...m, steps, reasoning: '', content: '' }
          })
          break

        case 'tool_progress':
          updateCard(data.tool_call_id, (m) => ({
            ...m,
            steps: (m.steps || []).map((s) =>
              s.type === 'tool' && s.id === data.tool_call_id ? { ...s, result: data.content } : s
            ),
          }))
          break

        case 'tool_end':
          updateCard(data.tool_call_id, (m) => ({
            ...m,
            steps: (m.steps || []).map((s) =>
              s.type === 'tool' && s.id === data.tool_call_id
                ? {
                    ...s,
                    status: data.status,
                    result: data.result ?? s.result,
                    display: data.display ?? s.display,
                    execution_time: data.execution_time,
                    is_error: data.status !== 'success',
                    permission_denied: data.permission_denied,
                    permission_mode: data.permission_mode,
                  }
                : s
            ),
          }))
          break

        // A tool call made inside a sub agent, filed under that sub agent's
        // step so its minutes of work can be followed rather than guessed at.
        // Ignored when the step is gone: a sub agent cancelled on a timeout
        // keeps going until its next checkpoint, and what it reports after
        // that describes work nobody is waiting on.
        case 'subagent_step':
          if (!data.card_id || !data.step_id) break
          updateCard(data.card_id, (m) => ({
            ...m,
            steps: (m.steps || []).map((s) => {
              if (s.type !== 'tool' || s.id !== data.card_id) return s
              const substeps = [...(s.substeps || [])]
              const at = substeps.findIndex((sub) => sub.id === data.step_id)
              if (at < 0) {
                if (data.phase !== 'start') return s
                substeps.push({
                  id: data.step_id!,
                  name: data.tool || 'tool',
                  args: summarizeArgs(data.arguments),
                  status: 'running',
                })
              } else {
                if (data.phase !== 'end') return s
                substeps[at] = {
                  ...substeps[at],
                  status: data.status || 'success',
                  execution_time: data.execution_time,
                  error: data.error,
                }
              }
              return { ...s, substeps }
            }),
          }))
          break

        case 'image':
        case 'file': {
          // Media pushed by the `send` tool (file_to_send). `content` is either
          // a backend /api/file?path=... URL or a passed-through http(s) URL.
          const url = data.content || ''
          if (!url) break
          // Prefer the concrete media kind from the backend (image/video/...);
          // fall back to the coarse SSE event type.
          const kind = data.file_type || (data.type === 'image' ? 'image' : 'file')
          const attType: Attachment['file_type'] =
            kind === 'image' ? 'image' : kind === 'video' ? 'video' : 'file'
          const att: Attachment = {
            file_path: url,
            file_name: data.file_name || 'file',
            file_type: attType,
            preview_url: url,
            abs_path: data.abs_path,
          }
          updateMsg(sid, speaking(), (m) => ({
            ...m,
            attachments: [...(m.attachments || []), att],
          }))
          break
        }

        case 'artifact': {
          if (!data.abs_path) break
          const artifact: Artifact = {
            abs_path: data.abs_path,
            rel_path: data.rel_path || data.file_name || '',
            file_name: data.file_name || '',
            kind: data.kind || 'file',
            previewable: !!data.previewable,
            size: data.size || 0,
            raw_url: data.raw_url || '',
            preview_url: data.preview_url || '',
          }
          updateMsg(sid, speaking(), (m) =>
            (m.artifacts || []).some((a) => a.abs_path === artifact.abs_path)
              ? m
              : { ...m, artifacts: [...(m.artifacts || []), artifact] }
          )
          useWorkspaceStore.getState().addTurnArtifact(artifact)
          break
        }

        case 'cancelled':
          userCancelled = true
          updateMsg(sid, main.id, (m) => ({ ...m, isCancelled: true }))
          break

        case 'done': {
          ended = true
          // Stopped, the bubble keeps what was shown by the time stop was
          // pressed; the reply's last text would repeat one of its steps.
          const stopped = detached()
          // The answer and the seq belong to the Agent that was asked, in
          // whichever bubble it finished in — never a teammate's.
          updateMsg(sid, main.id, (m) => {
            const next = stopped ? m.content : stripCancelMarker(data.content || m.content)
            return {
              ...m,
              content: next,
              botSeq: data.bot_seq ?? m.botSeq,
              isStreaming: false,
            }
          })
          // backfill the preceding user message's seq for edit/delete
          if (data.user_seq != null) {
            patchMessages(sid, (msgs) => {
              const idx = msgs.findIndex((m) => m.id === main.id)
              for (let i = idx - 1; i >= 0; i--) {
                if (msgs[i].role === 'user') {
                  msgs[i] = { ...msgs[i], userSeq: data.user_seq }
                  break
                }
              }
              return [...msgs]
            })
          }
          // The answer is final: free the UI now (don't wait for onerror).
          completeTurn()
          if (!stopped) {
            notifyRunDone(sid, 'done', data.content || '')
            useWorkspaceStore.getState().maybeAutoOpen()
          }
          // Backend keeps the stream open for a short tail (e.g. TTS audio via
          // voice_attach). Close it ourselves if nothing else arrives.
          if (tailTimer) clearTimeout(tailTimer)
          tailTimer = setTimeout(closeStream, 1500)
          break
        }

        case 'voice_attach':
          if (data.audio_url) {
            updateMsg(sid, main.id, (m) => ({
              ...m,
              extras: { ...(m.extras || {}), audio: data.audio_url },
            }))
          }
          finishStream()
          break

        case 'error':
          // The backend restarted and no longer knows this request: the reply
          // was cut off, not failed.
          if (data.reason === 'unknown_request' && !ended) {
            dropStream()
            break
          }
          ended = true
          // After a stop the bubble is already marked stopped; don't stack a
          // failure on top.
          if (userCancelled || detached()) {
            updateMsg(sid, main.id, (m) => ({ ...m, isStreaming: false }))
          } else {
            updateMsg(sid, main.id, (m) => ({ ...m, error: data.message || 'stream error', isStreaming: false }))
            notifyRunDone(sid, 'error', data.message || 'stream error')
          }
          finishStream()
          break
      }
    }

    // The stream went away before the run ended (the backend crashed or was
    // restarted): show what the backend kept of the reply instead of a bubble
    // frozen mid-way, or a step left spinning after a stop.
    const dropStream = () => {
      finishStream()
      void reloadAfterDrop(sid)
    }

    es.onerror = () => {
      // Stream closed (often the normal end after `done`/tail). Finalize.
      if (ended) finishStream()
      else dropStream()
    }
  }

  /** Reload a session's history once the backend answers again, unless a new turn began. */
  const reloadAfterDrop = async (sid: string) => {
    for (let attempt = 0; attempt < RELOAD_AFTER_DROP_ATTEMPTS; attempt++) {
      if (get().sessions[sid]?.isStreaming) return
      if (await get().loadHistory(sid, 1)) return
      await new Promise((resolve) => setTimeout(resolve, RELOAD_AFTER_DROP_INTERVAL_MS))
    }
  }

  return {
    sessions: {},

    getSession: (sid) => get().sessions[sid] || EMPTY,

    ensureSession: (sid) => {
      if (!get().sessions[sid]) patchSession(sid, { ...EMPTY })
    },

    send: async (sid, text, attachments) => {
      const userMsg: ChatMessage = {
        id: uid('user'),
        role: 'user',
        content: text,
        timestamp: Date.now() / 1000,
        attachments: attachments.length ? attachments : undefined,
      }
      const botId = uid('assistant')
      // The conversation's owner answers unless a teammate was addressed with a
      // leading @mention (group chat). Lock the speaker onto the reply at send
      // time so a later Agent switch never rewrites who spoke in the history.
      // Empty in single-Agent mode, so those replies keep the product logo
      // exactly as before.
      const owner = sessionOwner(sid)
      const addressed = owner ? addressedAgentId(text, sessionRoster(sid)) : ''
      const speakerAgentId = addressed || owner
      const botMsg: ChatMessage = {
        id: botId,
        role: 'assistant',
        content: '',
        timestamp: Date.now() / 1000,
        steps: [],
        isStreaming: true,
        extras: speakerAgentId ? { agent_id: speakerAgentId } : undefined,
      }
      patchMessages(sid, (msgs) => [...msgs, userMsg, botMsg])
      patchSession(sid, { isStreaming: true })
      useWorkspaceStore.getState().resetTurnArtifacts()

      try {
        const res = await apiClient.sendMessage(sid, text, {
          stream: true,
          attachments: attachments.length ? attachments : undefined,
          agentId: owner || undefined,
          speakerAgentId: addressed && addressed !== owner ? addressed : undefined,
        })
        // The server is the authority on who took the turn; repaint the live
        // bubble if it resolved the mention differently than we guessed.
        if (owner && res.status === 'success') {
          const speaker = res.speaker || owner
          if (speaker !== speakerAgentId && findAgent(speaker)) {
            updateMsg(sid, botId, (m) => ({ ...m, extras: { ...(m.extras || {}), agent_id: speaker } }))
          }
        }
        if (res.status === 'success' && res.stream && res.request_id) {
          patchSession(sid, { requestId: res.request_id })
          attachStream(sid, res.request_id, botId)
        } else if (res.inline_reply) {
          updateMsg(sid, botId, (m) => ({ ...m, content: res.inline_reply || '', isStreaming: false }))
          patchSession(sid, { isStreaming: false })
        } else {
          updateMsg(sid, botId, (m) => ({ ...m, error: 'send failed', isStreaming: false }))
          patchSession(sid, { isStreaming: false })
        }
      } catch (err) {
        updateMsg(sid, botId, (m) => ({ ...m, error: `${err}`, isStreaming: false }))
        patchSession(sid, { isStreaming: false })
      }
    },

    cancel: async (sid) => {
      const s = get().sessions[sid]
      if (!s?.requestId) return
      // Optimistically stop the UI right away: mark the last assistant bubble
      // cancelled and free the input. The stream is detached from the session
      // rather than closed: nothing more it says is shown, but a step running
      // when stop was pressed still reports how it ended. The backend still
      // gets the cancel request to abort the running agent task.
      patchMessages(sid, (msgs) => {
        for (let i = msgs.length - 1; i >= 0; i--) {
          if (msgs[i].role === 'assistant') {
            msgs[i] = { ...msgs[i], isCancelled: true, isStreaming: false }
            break
          }
        }
        return [...msgs]
      })
      patchSession(sid, { isStreaming: false, requestId: null })
      delete streams[sid]
      try {
        await apiClient.cancel({ requestId: s.requestId, sessionId: sid })
      } catch {
        /* ignore */
      }
    },

    regenerate: async (sid, botMessageId) => {
      const s = get().sessions[sid] || EMPTY
      const idx = s.messages.findIndex((m) => m.id === botMessageId)
      if (idx < 0) return
      // find the user message that produced this bot reply
      let userMsg: ChatMessage | null = null
      for (let i = idx - 1; i >= 0; i--) {
        if (s.messages[i].role === 'user') {
          userMsg = s.messages[i]
          break
        }
      }
      if (!userMsg) return
      // delete the turn on the backend (by the user's seq) then resend
      if (userMsg.userSeq != null) {
        try {
          await apiClient.deleteMessage({
            sessionId: sid,
            userSeq: userMsg.userSeq,
            deleteUser: true,
            cascade: true,
            agentId: sessionOwner(sid) || undefined,
          })
        } catch {
          /* ignore */
        }
      }
      // drop the user+bot messages locally from idx-? : remove from the user msg onward
      const userIdx = s.messages.indexOf(userMsg)
      patchMessages(sid, (msgs) => msgs.slice(0, userIdx))
      await get().send(sid, userMsg.content, userMsg.attachments || [])
    },

    editUserMessage: (sid, messageId) => {
      const s = get().sessions[sid] || EMPTY
      const msg = s.messages.find((m) => m.id === messageId)
      if (!msg || msg.role !== 'user') return null
      const userIdx = s.messages.indexOf(msg)
      // cascade-delete this turn on the backend
      if (msg.userSeq != null) {
        apiClient
          .deleteMessage({
            sessionId: sid,
            userSeq: msg.userSeq,
            deleteUser: true,
            cascade: true,
            agentId: sessionOwner(sid) || undefined,
          })
          .catch(() => {})
      }
      patchMessages(sid, (msgs) => msgs.slice(0, userIdx))
      return { text: msg.content, attachments: msg.attachments || [] }
    },

    deleteMessage: async (sid, userSeq, cascade) => {
      try {
        await apiClient.deleteMessage({
          sessionId: sid,
          userSeq,
          deleteUser: true,
          cascade,
          agentId: sessionOwner(sid) || undefined,
        })
      } catch {
        /* ignore */
      }
      // reload history to reflect server state
      await get().loadHistory(sid, 1)
    },

    loadHistory: async (sid, page = 1, untilSeq) => {
      try {
        const res = await apiClient.getHistory(sid, page, 20, sessionOwner(sid) || undefined, untilSeq)
        // A turn sent while this was loading owns the live bubbles now.
        if (page === 1 && get().sessions[sid]?.isStreaming) return true
        const uiMsgs = res.messages.flatMap(historyToMessages)
        patchSession(sid, {
          historyPage: res.page,
          historyHasMore: res.has_more,
          historyLoaded: true,
        })
        if (page === 1) {
          patchMessages(sid, () => uiMsgs)
          clearTimeout(followTimers[sid])
          delete followTimers[sid]
          if (uiMsgs[uiMsgs.length - 1]?.runState === 'running') {
            followTimers[sid] = setTimeout(() => {
              delete followTimers[sid]
              if (!get().sessions[sid]?.isStreaming) void get().loadHistory(sid, 1)
            }, FOLLOW_RUNNING_INTERVAL_MS)
          }
        } else {
          // older page: prepend
          patchMessages(sid, (msgs) => [...uiMsgs, ...msgs])
        }
        return true
      } catch {
        patchSession(sid, { historyLoaded: true })
        return false
      }
    },

    clearContext: async (sid) => {
      try {
        const res = await apiClient.clearContext(sid, sessionOwner(sid) || undefined)
        if (res.status !== 'success') return false
        // Append a visual divider so the user sees the context was cleared
        // (mirrors the web console's context-divider).
        patchMessages(sid, (msgs) => [
          ...msgs,
          {
            id: uid('divider'),
            role: 'system',
            kind: 'divider',
            content: '',
            timestamp: Date.now() / 1000,
          },
        ])
        return true
      } catch {
        return false
      }
    },

    compactContext: async (sid) => {
      const fail: CompactResult = { ok: false, noop: false, before: 0, after: 0, usage: null }
      try {
        const data = await apiClient.compactContext(sid, sessionOwner(sid) || undefined)
        if (!data || data.status === 'error') return fail
        const ok = !!data.ok
        const before = data.before || 0
        const after = data.after || 0
        if (ok) {
          // Drop a labeled divider into the thread so the summarize is visible,
          // mirroring the web console (clear uses the same divider, unlabeled).
          const label = t('ctx_compacted_divider')
            .replace('{before}', String(before))
            .replace('{after}', String(after))
          patchMessages(sid, (msgs) => [
            ...msgs,
            {
              id: uid('divider'),
              role: 'system',
              kind: 'divider',
              content: label,
              timestamp: Date.now() / 1000,
            },
          ])
        }
        return { ok, noop: !ok, before, after, usage: data.usage ?? null }
      } catch {
        return fail
      }
    },

    clearLocal: (sid) => {
      clearTimeout(followTimers[sid])
      delete followTimers[sid]
      const es = streams[sid]
      if (es) {
        es.close()
        delete streams[sid]
      }
      patchSession(sid, { ...EMPTY })
    },

    receivePush: (sid, content, requestId) => {
      if (!content) return false
      const cur = get().sessions[sid]
      // Already streaming this request via SSE, or the same push already
      // landed — don't render it twice.
      if (requestId && cur?.messages.some((m) => m.pushRequestId === requestId)) {
        return false
      }
      const msg: ChatMessage = {
        id: uid('assistant'),
        role: 'assistant',
        content,
        timestamp: Date.now() / 1000,
        pushRequestId: requestId,
      }
      patchMessages(sid, (msgs) => [...msgs, msg])
      return true
    },
  }
})
