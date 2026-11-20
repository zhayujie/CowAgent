/// <reference lib="dom" />

export type AppPermission = 'notifications' | 'microphone' | 'camera';

export type PermissionState = 'granted' | 'denied' | 'blocked' | 'unavailable';

export const APP_PERMISSIONS: AppPermission[] = ['notifications', 'microphone', 'camera'];

/** A page can't open the browser's site settings; the user changes a block there by hand. */
export const canOpenAppSettings = false;

export const permissionNote = 'perm_note_browser' as const;

const CONSTRAINT: Record<Exclude<AppPermission, 'notifications'>, MediaStreamConstraints> = {
  microphone: {audio: true},
  camera: {video: true},
};

const fromNotification = (p: NotificationPermission): PermissionState =>
  p === 'granted' ? 'granted' : p === 'denied' ? 'blocked' : 'denied';

// Firefox and pages served over plain http on the LAN can't answer; they read as unavailable.
export async function checkPermission(p: AppPermission): Promise<PermissionState> {
  if (p === 'notifications') {
    return typeof Notification === 'undefined' ? 'unavailable' : fromNotification(Notification.permission);
  }
  if (!navigator.mediaDevices?.getUserMedia) {
    return 'unavailable';
  }
  try {
    const status = await navigator.permissions.query({name: p as PermissionName});
    return status.state === 'granted' ? 'granted' : status.state === 'denied' ? 'blocked' : 'denied';
  } catch {
    return 'unavailable';
  }
}

/** The browser only asks when the page opens the device, so open it and let go at once. */
export async function requestPermission(p: AppPermission): Promise<PermissionState> {
  if (p === 'notifications') {
    if (typeof Notification === 'undefined') {
      return 'unavailable';
    }
    return fromNotification(await Notification.requestPermission());
  }
  if (!navigator.mediaDevices?.getUserMedia) {
    return 'unavailable';
  }
  try {
    const stream = await navigator.mediaDevices.getUserMedia(CONSTRAINT[p]);
    stream.getTracks().forEach(track => track.stop());
    return 'granted';
  } catch {
    const state = await checkPermission(p);
    return state === 'unavailable' ? 'blocked' : state;
  }
}

export const openAppSettings = async (_p?: AppPermission) => undefined;
