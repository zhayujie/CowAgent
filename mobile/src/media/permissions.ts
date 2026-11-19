import {Platform} from 'react-native';
import {
  check,
  checkNotifications,
  openSettings,
  PERMISSIONS,
  request,
  requestNotifications,
  RESULTS,
  type Permission,
  type PermissionStatus,
} from 'react-native-permissions';

export type AppPermission = 'notifications' | 'microphone' | 'camera';

/** `denied` can still be asked for in the app; `blocked` only changes in the system settings. */
export type PermissionState = 'granted' | 'denied' | 'blocked' | 'unavailable';

/** The permissions the app asks for at the moment a feature needs them. */
export const APP_PERMISSIONS: AppPermission[] = ['notifications', 'microphone', 'camera'];

export const canOpenAppSettings = true;

export const permissionNote = 'perm_note' as const;

const NATIVE: Record<Exclude<AppPermission, 'notifications'>, Permission> =
  Platform.OS === 'ios'
    ? {microphone: PERMISSIONS.IOS.MICROPHONE, camera: PERMISSIONS.IOS.CAMERA}
    : {microphone: PERMISSIONS.ANDROID.RECORD_AUDIO, camera: PERMISSIONS.ANDROID.CAMERA};

const toState = (s: PermissionStatus): PermissionState =>
  s === RESULTS.GRANTED || s === RESULTS.LIMITED
    ? 'granted'
    : s === RESULTS.DENIED
      ? 'denied'
      : s === RESULTS.BLOCKED
        ? 'blocked'
        : 'unavailable';

const unavailable = (): PermissionState => 'unavailable';

export const checkPermission = (p: AppPermission): Promise<PermissionState> =>
  p === 'notifications'
    ? checkNotifications().then(r => toState(r.status), unavailable)
    : check(NATIVE[p]).then(toState, unavailable);

export const requestPermission = (p: AppPermission): Promise<PermissionState> =>
  p === 'notifications'
    ? requestNotifications(['alert', 'sound', 'badge']).then(r => toState(r.status), unavailable)
    : request(NATIVE[p]).then(toState, unavailable);

/** Notifications open their own settings page; everything else the app's page. */
export const openAppSettings = (p?: AppPermission) =>
  openSettings(p === 'notifications' ? 'notifications' : undefined).catch(() => undefined);
