import type { Attachment } from '../types'

// Draft of the chat input (text + attachments). The input lives in local
// component state and the chat route unmounts ChatPage when the user navigates
// to another page, which would otherwise destroy what was typed. This module-
// scoped variable survives the unmount and is restored on the next mount.
// Lives for the renderer process only — no persistence across app restarts.
export const chatDraft: { text: string; attachments: Attachment[] } = {
  text: '',
  attachments: [],
}

export const PREFILL_EVENT = 'cow:prefill-chat-input'

// Put `text` in the chat input without sending it: a mounted chat page picks
// it up from the event, otherwise the input restores it from the draft.
export function prefillChatInput(text: string): void {
  chatDraft.text = text
  chatDraft.attachments = []
  window.dispatchEvent(new CustomEvent<string>(PREFILL_EVENT, { detail: text }))
}
