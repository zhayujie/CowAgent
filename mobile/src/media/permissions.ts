import {Platform} from 'react-native';
import {
  check,
  checkNotifications,
  openSettings,
  PERMISSIONS,
  request,
  requestMultiple,
  requestNotifications,
  RESULTS,
  type Permission,
  type PermissionStatus,
} from 'react-native-permissions';

export type AppPermission = 'notifications' | 'microphone' | 'camera' | 'location' | 'calendar' | 'contacts';

/** `denied` can still be asked for in the app; `blocked` only changes in the system settings. */
export type PermissionState = 'granted' | 'denied' | 'blocked' | 'unavailable';

/** The permissions the app asks for at the moment a feature needs them. */
export const APP_PERMISSIONS: AppPermission[] = ['notifications', 'microphone', 'camera', 'location', 'calendar', 'contacts'];

export const canOpenAppSettings = true;

export const permissionNote = 'perm_note' as const;

const NATIVE: Record<Exclude<AppPermission, 'notifications'>, Permission> =
  Platform.OS === 'ios'
    ? {
        microphone: PERMISSIONS.IOS.MICROPHONE,
        camera: PERMISSIONS.IOS.CAMERA,
        location: PERMISSIONS.IOS.LOCATION_WHEN_IN_USE,
        calendar: PERMISSIONS.IOS.CALENDARS,
        contacts: PERMISSIONS.IOS.CONTACTS,
      }
    : {
        microphone: PERMISSIONS.ANDROID.RECORD_AUDIO,
        camera: PERMISSIONS.ANDROID.CAMERA,
        location: PERMISSIONS.ANDROID.ACCESS_FINE_LOCATION,
        calendar: PERMISSIONS.ANDROID.READ_CALENDAR,
        contacts: PERMISSIONS.ANDROID.READ_CONTACTS,
      };

const toState = (s: PermissionStatus): PermissionState =>
  s === RESULTS.GRANTED || s === RESULTS.LIMITED
    ? 'granted'
    : s === RESULTS.DENIED
      ? 'denied'
      : s === RESULTS.BLOCKED
        ? 'blocked'
        : 'unavailable';

const unavailable = (): PermissionState => 'unavailable';

const either = (fine: PermissionStatus, coarse: PermissionStatus): PermissionState =>
  toState(coarse === RESULTS.GRANTED ? coarse : fine);

const WORST: PermissionState[] = ['unavailable', 'blocked', 'denied', 'granted'];
const both = (a: PermissionStatus, b: PermissionStatus): PermissionState =>
  WORST.find(s => s === toState(a) || s === toState(b)) ?? 'unavailable';

/** Android permissions asked for in the same dialog as the main one, and what their answers add up to. */
const PAIRED: Partial<Record<AppPermission, [Permission, (main: PermissionStatus, also: PermissionStatus) => PermissionState]>> =
  Platform.OS === 'android'
    ? {
        // Android 12+ lets the user grant approximate location only, which is enough.
        location: [PERMISSIONS.ANDROID.ACCESS_COARSE_LOCATION, either],
        // Reading events and adding them.
        calendar: [PERMISSIONS.ANDROID.WRITE_CALENDAR, both],
      }
    : {};

export function checkPermission(p: AppPermission): Promise<PermissionState> {
  if (p === 'notifications') {
    return checkNotifications().then(r => toState(r.status), unavailable);
  }
  const paired = PAIRED[p];
  return paired
    ? Promise.all([check(NATIVE[p]), check(paired[0])]).then(([main, also]) => paired[1](main, also), unavailable)
    : check(NATIVE[p]).then(toState, unavailable);
}

export function requestPermission(p: AppPermission): Promise<PermissionState> {
  if (p === 'notifications') {
    return requestNotifications(['alert', 'sound', 'badge']).then(r => toState(r.status), unavailable);
  }
  const paired = PAIRED[p];
  return paired
    ? requestMultiple([NATIVE[p], paired[0]]).then(r => paired[1](r[NATIVE[p]], r[paired[0]]), unavailable)
    : request(NATIVE[p]).then(toState, unavailable);
}

/** Notifications open their own settings page; everything else the app's page. */
export const openAppSettings = (p?: AppPermission) =>
  openSettings(p === 'notifications' ? 'notifications' : undefined).catch(() => undefined);
