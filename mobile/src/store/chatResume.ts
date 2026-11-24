import {AppState} from 'react-native';
import {readJSON, writeJSON} from '../storage/kv';

/**
 * iOS ends apps left in the background whenever it needs the memory. Back
 * within this long, the app opens on the chat it was showing, draft and all,
 * as if it had never been closed; later on it starts a new chat as usual.
 */
const RESUME_MS = 30 * 60 * 1000;
const KEY = 'chat:resume';

export interface OpenChat {
  serverId: string;
  sessionId: string;
  /** Nothing sent yet: the server has no history for it. */
  isNew: boolean;
  draft: string;
}

let resumable: OpenChat | null = null;
let open: OpenChat | null = null;

export async function loadChatResume(): Promise<void> {
  const saved = await readJSON<(OpenChat & {at: number}) | null>(KEY, null);
  resumable = saved && Date.now() - saved.at < RESUME_MS ? saved : null;
}

/** The chat to come back to on `serverId`, until a chat screen has opened. */
export function chatToResume(serverId: string | null): OpenChat | null {
  return resumable && resumable.serverId === serverId ? resumable : null;
}

/** The chat on screen, saved as the app leaves for the background. */
export function trackOpenChat(chat: OpenChat): void {
  resumable = null;
  open = chat;
}

AppState.addEventListener('change', state => {
  if (state === 'background' && open) {
    writeJSON(KEY, {...open, at: Date.now()}).catch(() => undefined);
  }
});
