import {AppState, NativeModules} from 'react-native';
import {tr, trf} from '../i18n';
import {realtime} from '../realtime/RealtimeClient';
import {useChatStore, type ChatMessage} from '../store/chatStore';
import {useSessionStore} from '../store/sessionStore';
import {canNotify, notice} from './notice';

/**
 * A reply that finishes while the app is away is told with a notification. While one is
 * under way the app keeps its connection through the background: Android lets it run on,
 * iOS gives about half a minute, enough for a short reply.
 */

const native: {holdBackground?(): void; releaseBackground?(): void} | undefined = NativeModules.CowDevice;

const BODY_MAX = 200;
const TITLE_MAX = 40;

const clip = (text: string, max: number) => (text.length > max ? `${text.slice(0, max)}…` : text);

const plain = (markdown: string) =>
  markdown
    .replace(/```[\s\S]*?```/g, ' ')
    .replace(/!\[[^\]]*\]\([^)]*\)/g, ' ')
    .replace(/\[([^\]]*)\]\([^)]*\)/g, '$1')
    .replace(/[#>*_`~|]/g, '')
    .replace(/\s+/g, ' ')
    .trim();

function bodyOf(reply: ChatMessage): string {
  if (reply.error) {
    return trf('reply_notice_failed', {error: clip(reply.error, BODY_MAX)});
  }
  return clip(plain(reply.content), BODY_MAX) || tr('reply_notice_done');
}

/** A new chat has no title yet; what the user asked names it then. */
function titleOf(sessionId: string, messages: ChatMessage[]): string {
  const title = useSessionStore.getState().sessions.find(s => s.session_id === sessionId)?.title;
  const asked = [...messages].reverse().find(m => m.role === 'user')?.content ?? '';
  return title || clip(plain(asked), TITLE_MAX) || tr('reply_notice_title');
}

async function tell(sessionId: string) {
  const messages = useChatStore.getState().messages[sessionId] ?? [];
  const reply = [...messages].reverse().find(m => m.role === 'assistant');
  if (!reply || reply.cancelled) {
    return;
  }
  await notice('reply', sessionId, titleOf(sessionId, messages), bodyOf(reply));
}

let watching = false;

export function watchReplies(): void {
  if (watching || !canNotify()) {
    return;
  }
  watching = true;
  let before = useChatStore.getState().active;
  useChatStore.subscribe(state => {
    const now = state.active;
    if (now === before) {
      return;
    }
    const away = AppState.currentState === 'background';
    const told = Object.keys(before)
      .filter(id => !now[id] && away)
      .map(id => tell(id).catch(() => undefined));
    before = now;
    const replying = Object.keys(now).length > 0;
    realtime.holdInBackground(replying);
    if (replying) {
      native?.holdBackground?.();
    } else {
      // iOS suspends the app once let go, so the notices go out first.
      Promise.all(told).finally(() => native?.releaseBackground?.());
    }
  });
}
