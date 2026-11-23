import {Alert, AppState, NativeModules, Platform} from 'react-native';
import {tr, type MessageKey} from '../i18n';
import {checkPermission, openAppSettings, requestPermission, type PermissionState} from '../media/permissions';
import {readJSON, writeJSON} from '../storage/kv';

/** System notifications for what happened while the app was away; on screen the chat shows it. */

const native:
  | {
      notice?(kind: string, key: string, title: string, body: string, session: string): Promise<void>;
      takeDroppedNotice?(): Promise<boolean>;
    }
  | undefined = NativeModules.CowDevice;

export const canNotify = () => !!native?.notice;

const OFF_KEY = 'notify:off_tip';
const DROPPED_KEY = 'notify:dropped_tip';
const AGAIN_MS = 24 * 60 * 60 * 1000;
/** One tip on coming back is enough, whichever it was. */
const QUIET_MS = 60_000;
let lastTip = 0;

/** MIUI files apps outside its list under "unimportant notifications", a place its users know by that name. */
const filtersNotifications = () =>
  Platform.OS === 'android' &&
  /xiaomi|redmi|poco/i.test(String((Platform.constants as {Manufacturer?: string}).Manufacturer ?? ''));

/** A tip that comes back at most daily, until told not to. */
async function nowAndThen(key: string, title: MessageKey, text: MessageKey) {
  const seen = await readJSON<{at?: number; never?: boolean}>(key, {});
  if (seen.never || Date.now() - (seen.at ?? 0) < AGAIN_MS) {
    return;
  }
  await writeJSON(key, {at: Date.now()});
  lastTip = Date.now();
  Alert.alert(tr(title), tr(text), [
    {text: tr('notify_off_never'), onPress: () => writeJSON(key, {never: true})},
    {text: tr('notify_filter_later'), style: 'cancel'},
    {text: tr('notify_filter_open'), onPress: () => openAppSettings('notifications')},
  ]);
}

/**
 * Asks if never asked. With `remind`, notifications turned off in the settings, where no dialog
 * of the app's can reach, are pointed out too.
 */
export async function askNotifications(remind = false): Promise<PermissionState> {
  let state = await checkPermission('notifications');
  if (state === 'denied') {
    state = await requestPermission('notifications');
  }
  if (state === 'blocked' && remind) {
    await nowAndThen(OFF_KEY, 'notify_off_title', 'notify_off_text');
  }
  return state;
}

let pending = false;

/**
 * Back in the app. After a notice was due, notifications are asked for if they were never
 * allowed or pointed out if turned off. And if the system dropped one of them or turned them
 * down, which some do to apps outside their own list, it is said how to undo that.
 */
async function onReturn() {
  if (pending) {
    pending = false;
    if ((await askNotifications(true)) !== 'granted') {
      return;
    }
  }
  if ((await native?.takeDroppedNotice?.()) && Date.now() - lastTip > QUIET_MS) {
    await nowAndThen(DROPPED_KEY, 'notify_dropped_title', filtersNotifications() ? 'notify_dropped_text_miui' : 'notify_dropped_text');
  }
}

/** Once the app has settled after starting, as its language loads then. */
const START_DELAY_MS = 2000;

let watching = false;

/** From the app's start on. */
export function watchNotices(): void {
  if (watching || !canNotify()) {
    return;
  }
  watching = true;
  setTimeout(() => onReturn().catch(() => undefined), START_DELAY_MS);
  AppState.addEventListener('change', state => state === 'active' && onReturn().catch(() => undefined));
}

/** Tapping it opens `session`. */
export async function notice(kind: 'reply' | 'task', key: string, title: string, body: string, session = ''): Promise<void> {
  if (!native?.notice) {
    return;
  }
  pending = true;
  if ((await checkPermission('notifications')) === 'granted') {
    await native.notice(kind, key, title, body, session);
  }
}
