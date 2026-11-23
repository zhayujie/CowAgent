import {StackActions} from '@react-navigation/native';
import {AppState, NativeModules} from 'react-native';
import {navigationRef} from '../navigation/ref';
import {useAgentStore} from '../store/agentStore';
import {useSessionStore} from '../store/sessionStore';

/**
 * A tapped notification opens the chat it is about. The system hands the tap to the native side,
 * possibly before JS runs, and it is kept there until taken here on coming to the front.
 */

const native: {takeNotificationTap?(): Promise<string | null>} | undefined = NativeModules.CowDevice;

/** iOS may report the tap just after the app turned active. */
const LATE_TAP_MS = 600;

let wanted: string | null = null;

/** Only once signed in, when the chat is among the screens. */
function openWanted() {
  if (!wanted || !navigationRef.isReady() || !navigationRef.getRootState()?.routeNames.includes('Chat')) {
    return;
  }
  const sessionId = wanted;
  wanted = null;
  const agentId = useSessionStore.getState().sessions.find(s => s.session_id === sessionId)?.agent?.id;
  if (agentId) {
    useAgentStore.getState().select(agentId);
  }
  navigationRef.dispatch(StackActions.popTo('Chat', {sessionId, isNew: false}));
}

async function take() {
  const session = await native?.takeNotificationTap?.().catch(() => null);
  if (session) {
    wanted = session;
    openWanted();
  }
}

let watching = false;

export function watchNotificationTaps(): void {
  if (watching || !native?.takeNotificationTap) {
    return;
  }
  watching = true;
  take();
  AppState.addEventListener('change', state => {
    if (state === 'active') {
      take();
      setTimeout(take, LATE_TAP_MS);
    }
  });
  // Opening the app from a notification starts it signed out until the kernel is up, and then
  // the chat appears; a tap reported late on that start is looked for once more then.
  let signedIn = false;
  navigationRef.addListener('state', () => {
    const now = !!navigationRef.getRootState()?.routeNames.includes('Chat');
    if (now && !signedIn) {
      take();
    }
    signedIn = now;
    openWanted();
  });
}
