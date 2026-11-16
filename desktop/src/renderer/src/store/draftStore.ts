import { create } from 'zustand'
import type { Attachment } from '../types'

// Per-session drafts of the chat input (text + attachments). The input lives in
// local component state, which is lost when the chat route unmounts and is
// shared by every session; drafts keyed by session id keep what was typed in
// each conversation. Persisted to localStorage so they survive a restart.
export interface ChatDraft {
  text: string
  attachments: Attachment[]
}

const STORAGE_KEY = 'cow_chat_drafts'
const PERSIST_DELAY_MS = 300

const EMPTY_DRAFT: ChatDraft = { text: '', attachments: [] }

function load(): Record<string, ChatDraft> {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    const parsed = raw ? JSON.parse(raw) : {}
    return parsed && typeof parsed === 'object' ? parsed : {}
  } catch {
    return {}
  }
}

const drafts: Record<string, ChatDraft> = load()
let persistTimer: ReturnType<typeof setTimeout> | null = null

function draftIds(): Record<string, true> {
  return Object.fromEntries(Object.keys(drafts).map((id) => [id, true as const]))
}

// Which sessions hold an unsent draft, for the session list. Updated only when
// a session gains or loses its draft, not on every keystroke.
export const useDraftIds = create<{ ids: Record<string, true> }>(() => ({ ids: draftIds() }))

function persistNow(): void {
  if (persistTimer) {
    clearTimeout(persistTimer)
    persistTimer = null
  }
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(drafts))
  } catch {
    /* quota exceeded or storage unavailable: drafts stay in memory */
  }
}

function schedulePersist(): void {
  if (persistTimer) return
  persistTimer = setTimeout(persistNow, PERSIST_DELAY_MS)
}

window.addEventListener('beforeunload', persistNow)

export function getDraft(sid: string): ChatDraft {
  return drafts[sid] || EMPTY_DRAFT
}

export function setDraft(sid: string, draft: ChatDraft): void {
  if (!sid) return
  const empty = !draft.text.trim() && draft.attachments.length === 0
  const had = sid in drafts
  if (empty) {
    if (!had) return
    delete drafts[sid]
  } else {
    drafts[sid] = { text: draft.text, attachments: draft.attachments }
  }
  if (had === empty) useDraftIds.setState({ ids: draftIds() })
  schedulePersist()
}

export function clearDraft(sid: string): void {
  setDraft(sid, EMPTY_DRAFT)
}

export const PREFILL_EVENT = 'cow:prefill-chat-input'

// Put `text` in the chat input of session `sid` without sending it: a mounted
// input showing that session picks it up from the event, otherwise the input
// restores it from the draft when the session is opened.
export function prefillChatInput(sid: string, text: string): void {
  setDraft(sid, { text, attachments: [] })
  window.dispatchEvent(new CustomEvent<{ sid: string; text: string }>(PREFILL_EVENT, { detail: { sid, text } }))
}
