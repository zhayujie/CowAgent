export type AppPermission = 'notifications' | 'microphone' | 'camera';

/** `denied` can still be asked for in the app; `blocked` only changes in the system settings. */
export type PermissionState = 'granted' | 'denied' | 'blocked' | 'unavailable';

/**
 * No camera: scanning, taking photos and picking them all run in system pickers
 * (ets/native), so module.json5 declares neither the camera nor the photo library.
 */
export const APP_PERMISSIONS: AppPermission[] = ['notifications', 'microphone'];

export const canOpenAppSettings = true;

/** Footnote that also says why the camera and photos are missing from the list. */
export const permissionNote = 'perm_note_system_pickers' as const;

// Resolves to the ohos build, which knows HARMONY permissions.
const perms = require('react-native-permissions');

const toState = (s: string): PermissionState =>
  s === perms.RESULTS.GRANTED || s === perms.RESULTS.LIMITED
    ? 'granted'
    : s === perms.RESULTS.DENIED
      ? 'denied'
      : s === perms.RESULTS.BLOCKED
        ? 'blocked'
        : 'unavailable';

const unavailable = (): PermissionState => 'unavailable';

/**
 * isNotificationEnabled can't tell "never asked" from "turned down", so the system dialog is offered
 * until it has been turned down once; it rejects then and won't show again.
 */
let notificationsDeclined = false;

async function checkNotifications(): Promise<PermissionState> {
  try {
    const {status} = await perms.checkNotifications();
    if (status === perms.RESULTS.GRANTED) {
      return 'granted';
    }
    return notificationsDeclined ? 'blocked' : 'denied';
  } catch {
    return 'unavailable';
  }
}

async function requestNotifications(): Promise<PermissionState> {
  try {
    await perms.requestNotifications(['alert', 'sound', 'badge']);
    return 'granted';
  } catch {
    notificationsDeclined = true;
    return 'blocked';
  }
}

function viaPermission(p: AppPermission, ask: boolean): Promise<PermissionState> {
  if (p === 'notifications') {
    return ask ? requestNotifications() : checkNotifications();
  }
  const mic = perms.PERMISSIONS.HARMONY.MICROPHONE;
  return (ask ? perms.request(mic) : perms.check(mic)).then(toState, unavailable);
}

export const checkPermission = (p: AppPermission) => viaPermission(p, false);

export const requestPermission = (p: AppPermission) => viaPermission(p, true);

/** Notifications open their own settings page; everything else the app's page. */
export const openAppSettings = (p?: AppPermission): Promise<void> =>
  perms.openSettings(p === 'notifications' ? 'notifications' : undefined).catch(() => undefined);
