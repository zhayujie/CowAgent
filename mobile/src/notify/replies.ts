import {AppState, NativeModules, Platform} from 'react-native';
import {requestPermission} from '../media/permissions';
import {navigationRef} from '../navigation/ref';
import {noticeTitle, replyPreview} from './preview';
import {useAgentStore} from '../store/agentStore';
import {useChatStore} from '../store/chatStore';
import {useSessionStore} from '../store/sessionStore';
import {useUnreadStore} from '../store/unreadStore';

/**
 * A finished reply as a system notification, and the tap that brings its reader back.
 *
 * Only Android posts: the JS below is the same everywhere, and the module is simply absent
 * elsewhere, which makes these calls no-ops.
 */
const native: {
  notify(title: string, body: string, sessionId: string): Promise<boolean>;
  consumeOpen(): Promise<string | null>;
  clear?(sessionId: string): Promise<void>;
} | undefined = Platform.OS === 'android' ? NativeModules.CowNotify : undefined;

/** The answer that just landed, flattened to one line; empty when there is nothing to show. */
function previewOf(sessionId: string): string {
  const messages = useChatStore.getState().messages[sessionId] ?? [];
  for (let i = messages.length - 1; i >= 0; i -= 1) {
    const message = messages[i];
    if (message.role !== 'assistant' || !message.content.trim()) {
      continue;
    }
    return replyPreview(message.content);
  }
  return '';
}

/** The conversation's own name, or the Agent answering in it. */
function titleOf(sessionId: string): string {
  const session = useSessionStore.getState().sessions.find(s => s.session_id === sessionId);
  const agents = useAgentStore.getState();
  const agent = agents.agents.find(a => a.id === session?.agent?.id) ?? agents.agents.find(a => a.id === agents.currentId);
  return noticeTitle(session?.title, agent?.name || session?.agent?.name);
}

/** Opens the conversation a notification belongs to, from wherever the app happens to be. */
export function openSession(sessionId: string) {
  if (!sessionId || !navigationRef.isReady()) {
    return;
  }
  navigationRef.navigate('Chat', {sessionId, isNew: false});
}

/** A notice that was tapped while the app was closed or in the background. */
export function drainPendingSession() {
  native?.consumeOpen()
    .then(sessionId => sessionId && openSession(sessionId))
    .catch(() => undefined);
}

/** The conversation is open now, so its notice has done its job. */
export function clearNotice(sessionId: string) {
  native?.clear?.(sessionId).catch(() => undefined);
}

/**
 * Announces every reply that finishes, and follows the taps back. Mounted once, by the app.
 * A tap reaches JS as a resume: the session id waits on the native side until this runs.
 */
/** Asked once per run: a refused or blocked permission is the settings screen's business. */
let askedForPermission = false;

function announce(title: string, body: string, sessionId: string) {
  native?.notify(title, body, sessionId).then(
    posted => {
      if (!posted && !askedForPermission) {
        askedForPermission = true;
        requestPermission('notifications').catch(() => undefined);
      }
    },
    () => undefined,
  );
}

export function watchReplies(): () => void {
  const subscription = AppState.addEventListener('change', state => {
    if (state === 'active') {
      drainPendingSession();
    }
  });
  let previous = useChatStore.getState().active;
  const unsubscribe = useChatStore.subscribe(state => {
    // A session leaves `active` exactly when its reply settles, however it settled.
    Object.keys(previous).forEach(sessionId => {
      if (state.active[sessionId]) {
        return;
      }
      const body = previewOf(sessionId);
      if (body) {
        announce(titleOf(sessionId), body, sessionId);
        // The left list keeps a green dot until the conversation is opened.
        if (useChatStore.getState().currentSessionId !== sessionId) {
          useUnreadStore.getState().mark(sessionId);
        }
      }
    });
    previous = state.active;
  });
  return () => {
    subscription.remove();
    unsubscribe();
  };
}
