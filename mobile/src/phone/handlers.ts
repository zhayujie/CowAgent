import {Linking, NativeModules, Platform} from 'react-native';
import {checkPermission, requestPermission, type AppPermission} from '../media/permissions';
import {pickPhotos} from '../media/picker';
import {setPurpose, showBlocked, showLocationOff} from './prompts';
import {DAY_MS, describeSpan, formatLocal, nextDay, parseLocal} from './time';

/** Why a request did not run, as the kernel's phone tools know the reasons. */
export class PhoneError extends Error {
  constructor(
    readonly code: string,
    message?: string,
  ) {
    super(message ?? code);
  }
}

type Args = Record<string, unknown>;

interface Handler {
  /** The system permission it needs; when that is off for good, the settings are offered instead of asking. */
  permission?: AppPermission;
  /** What the user is asked to allow: an action key, and what it acts on. Without it nothing is asked. */
  ask?: (args: Args) => {action: string; target?: string};
  /** Which "always allow" covers the call; reading and changing the same data are trusted apart. */
  scope?: (args: Args) => string;
  run: (args: Args, id: string) => Promise<unknown>;
}

const str = (v: unknown) => (typeof v === 'string' ? v.trim() : '');

// Schemes that would reach into this app's own files or run script rather than hand off to another app.
const REFUSED_SCHEMES = /^(file|content|intent|javascript|data|about|blob):/i;

function openUrl(args: Args): string {
  const action = str(args.action);
  const target = str(args.target);
  const text = str(args.text);
  const q = encodeURIComponent;
  switch (action) {
    case 'url': {
      const url = /^[a-z][a-z0-9+.-]*:/i.test(target) ? target : `https://${target}`;
      if (REFUSED_SCHEMES.test(url)) {
        throw new PhoneError('unsupported', `Links starting with ${url.split(':')[0]}: are not opened`);
      }
      return url;
    }
    case 'navigate':
      return Platform.OS === 'ios' ? `https://maps.apple.com/?q=${q(target)}` : `geo:0,0?q=${q(target)}`;
    case 'call':
      return `tel:${target.replace(/[^0-9+*#,;]/g, '')}`;
    case 'sms': {
      const number = target.replace(/[^0-9+]/g, '');
      // iOS reads the body after "&", Android after "?"; the app hands Android's over natively when it can.
      return text ? `sms:${number}${Platform.OS === 'ios' ? '&' : '?'}body=${q(text)}` : `sms:${number}`;
    }
    case 'email': {
      const query = [str(args.subject) && `subject=${q(str(args.subject))}`, text && `body=${q(text)}`].filter(Boolean);
      return `mailto:${target.split(/[?&#]/)[0]}${query.length ? `?${query.join('&')}` : ''}`;
    }
  }
  throw new PhoneError('unsupported', `Unknown action ${action}`);
}

/** A link to anything but a web page opens another app, which is asked about apart. */
function openKind(args: Args): string {
  const action = str(args.action);
  const target = str(args.target);
  const web = /^https?:\/\//i.test(target) || !/^[a-z][a-z0-9+.-]*:/i.test(target);
  return action === 'url' ? (web ? 'url' : 'app') : action;
}

const open: Handler = {
  ask: args => ({action: openKind(args), target: str(args.target)}),
  // Allowing links for good does not allow calls, messages or other apps.
  scope: args => `phone_open:${openKind(args)}`,
  run: async args => {
    const url = openUrl(args);
    try {
      if (Platform.OS === 'android' && str(args.action) === 'sms' && str(args.text) && native?.composeSms) {
        await native.composeSms(str(args.target).replace(/[^0-9+]/g, ''), str(args.text));
      } else {
        await Linking.openURL(url);
      }
    } catch {
      throw new PhoneError('no_app');
    }
    return {opened: true};
  },
};

const NO_DIALOG_MS = 600;

/** Asks when it may, and offers the settings when only the user can change it there. */
async function ensurePermission(permission: AppPermission, id: string): Promise<void> {
  let state = await checkPermission(permission);
  if (state === 'denied') {
    setPurpose(Platform.OS === 'android' ? permission : null);
    const asked = Date.now();
    try {
      state = await requestPermission(permission);
    } finally {
      setPurpose(null);
    }
    // Android reads "don't ask again" as denied until a request finds it, and that request
    // answers at once without a dialog. Anything slower was the user turning it down just now.
    const answeredAtOnce = Date.now() - asked < NO_DIALOG_MS;
    if (state !== 'granted' && !(state === 'blocked' && answeredAtOnce)) {
      throw new PhoneError('permission_denied');
    }
  }
  if (state === 'blocked') {
    showBlocked(id, permission);
    throw new PhoneError('permission_blocked');
  }
  if (state !== 'granted') {
    throw new PhoneError('unsupported', `${permission} is not available on this phone`);
  }
}

interface Fix {
  latitude: number;
  longitude: number;
  accuracy?: number;
  altitude?: number;
  time: number;
  address?: string;
}

interface NativeEvent {
  title: string;
  start: number;
  end: number;
  allDay: boolean;
  location: string;
  notes: string;
  calendar: string;
}

interface NativeStatus {
  battery?: number;
  charging?: boolean;
  powerSaving?: boolean;
  network?: string;
  metered?: boolean;
  storageFree?: number;
  storageTotal?: number;
  ringer?: string;
  model?: string;
  system?: string;
}

interface NativeContact {
  name: string;
  phones: {value: string; label: string}[];
  emails: {value: string; label: string}[];
  organization: string;
}

const native:
  | {
      currentLocation(): Promise<Fix>;
      calendarEvents(start: number, end: number): Promise<NativeEvent[]>;
      createCalendarEvent(event: Record<string, unknown>): Promise<{id: string; calendar: string}>;
      searchContacts(query: string, limit: number): Promise<NativeContact[]>;
      deviceStatus(): Promise<NativeStatus>;
      composeSms?(number: string, body: string): Promise<void>;
    }
  | undefined = NativeModules.CowDevice;

const files: {share(source: string, fileName: string, mime: string): Promise<unknown>} | undefined =
  NativeModules.CowDownloads;

/** What a native call failed with, as one of the codes the kernel knows; anything else is `failed`. */
function nativeFailure(e: unknown, known: string[]): PhoneError {
  const code = (e as {code?: string}).code ?? '';
  return new PhoneError(known.includes(code) ? code : 'failed', String((e as {message?: string}).message ?? e));
}

const location: Handler = {
  permission: 'location',
  ask: () => ({action: 'location'}),
  run: async (_args, id) => {
    await ensurePermission('location', id);
    let fix: Fix;
    try {
      fix = await native!.currentLocation();
    } catch (e) {
      const code = (e as {code?: string}).code;
      if (code === 'location_off') {
        showLocationOff(id);
      }
      throw new PhoneError(code === 'location_off' || code === 'permission_denied' ? code : 'no_fix', String(e));
    }
    return {
      latitude: fix.latitude,
      longitude: fix.longitude,
      coordinate_system: 'WGS-84',
      ...(fix.accuracy !== undefined && {accuracy_m: Math.round(fix.accuracy)}),
      ...(fix.address && {address: fix.address}),
      age_seconds: Math.max(0, Math.round((Date.now() - fix.time) / 1000)),
    };
  },
};

const MAX_EVENTS = 50;
const MAX_RANGE_MS = 366 * DAY_MS;

function localTime(args: Args, key: string) {
  const value = str(args[key]);
  if (!value) {
    return null;
  }
  const parsed = parseLocal(value);
  if (!parsed) {
    throw new PhoneError('invalid', `${key} is not a valid date or time: ${value}`);
  }
  return parsed;
}

/** Where a new event starts and ends; a date alone makes a whole day of it. */
function eventSpan(args: Args) {
  const start = localTime(args, 'start');
  if (!start) {
    throw new PhoneError('invalid', 'start is required');
  }
  const end = localTime(args, 'end');
  const allDay = start.dateOnly;
  const endMs = end
    ? allDay
      ? nextDay(end.ms)
      : end.ms
    : allDay
      ? nextDay(start.ms)
      : start.ms + 60 * 60 * 1000;
  if (endMs <= start.ms) {
    throw new PhoneError('invalid', 'end must come after start');
  }
  return {start: start.ms, end: endMs, allDay};
}

const clip = (text: string, max: number) => (text.length > max ? `${text.slice(0, max)}…` : text);

const calendar: Handler = {
  permission: 'calendar',
  ask: args => {
    if (str(args.action) !== 'create') {
      const range = [str(args.start), str(args.end)].filter(Boolean).join(' – ');
      return {action: 'calendar_list', target: [range, str(args.query)].filter(Boolean).join('\n') || undefined};
    }
    const title = str(args.title);
    try {
      const span = eventSpan(args);
      const place = str(args.location);
      return {action: 'calendar_create', target: [title, describeSpan(span.start, span.end, span.allDay), place].filter(Boolean).join('\n')};
    } catch {
      return {action: 'calendar_create', target: title};
    }
  },
  scope: args => `phone_calendar:${str(args.action) === 'create' ? 'create' : 'list'}`,
  run: async (args, id) => {
    const create = str(args.action) === 'create';
    const span = create ? eventSpan(args) : null;
    await ensurePermission('calendar', id);
    if (span) {
      const reminder = typeof args.reminder_minutes === 'number' ? args.reminder_minutes : undefined;
      const created = await native!
        .createCalendarEvent({
          title: str(args.title),
          ...span,
          ...(str(args.location) && {location: str(args.location)}),
          ...(str(args.notes) && {notes: str(args.notes)}),
          ...(reminder !== undefined && {reminderMinutes: reminder}),
        })
        .catch(e => {
          throw nativeFailure(e, ['no_calendar', 'permission_denied']);
        });
      return {
        created: true,
        title: str(args.title),
        start: formatLocal(span.start, span.allDay),
        end: formatLocal(span.allDay ? span.end - 1 : span.end, span.allDay),
        all_day: span.allDay,
        calendar: created.calendar,
      };
    }

    const from = localTime(args, 'start');
    const to = localTime(args, 'end');
    const start = from?.ms ?? Date.now();
    const end = to ? (to.dateOnly ? nextDay(to.ms) : to.ms) : start + 7 * DAY_MS;
    if (end <= start) {
      throw new PhoneError('invalid', 'end must come after start');
    }
    if (end - start > MAX_RANGE_MS) {
      throw new PhoneError('invalid', 'Ask for at most a year at a time');
    }
    const query = str(args.query).toLowerCase();
    const found = (
      await native!.calendarEvents(start, end).catch(e => {
        throw nativeFailure(e, ['permission_denied']);
      })
    ).filter(
      e =>
        e.start < end &&
        e.end > start &&
        (!query || [e.title, e.location, e.notes].some(t => t.toLowerCase().includes(query))),
    );
    return {
      from: formatLocal(start),
      to: formatLocal(end),
      events: found.slice(0, MAX_EVENTS).map(e => ({
        title: e.title,
        start: formatLocal(e.start, e.allDay),
        end: formatLocal(e.allDay ? e.end - 1 : e.end, e.allDay),
        ...(e.allDay && {all_day: true}),
        ...(e.location && {location: e.location}),
        ...(e.notes && {notes: clip(e.notes, 300)}),
        calendar: e.calendar,
      })),
      ...(found.length > MAX_EVENTS && {more: found.length - MAX_EVENTS}),
    };
  },
};

const MAX_CONTACTS = 10;

/** The same number saved twice in two accounts, or spelled with and without spaces, is listed once. */
function distinctBy<T>(items: T[], key: (item: T) => string): T[] {
  const seen = new Set<string>();
  return items.filter(item => {
    const k = key(item);
    return !seen.has(k) && !!seen.add(k);
  });
}

const contacts: Handler = {
  permission: 'contacts',
  ask: args => ({action: 'contacts', target: str(args.query)}),
  run: async (args, id) => {
    await ensurePermission('contacts', id);
    const found = await native!.searchContacts(str(args.query), MAX_CONTACTS).catch(e => {
      throw nativeFailure(e, ['permission_denied']);
    });
    return {
      contacts: found.map(c => ({
        name: c.name,
        phones: distinctBy(c.phones, p => p.value.replace(/[^0-9+]/g, '')).map(p => ({
          number: p.value,
          ...(p.label && {label: p.label}),
        })),
        emails: distinctBy(c.emails, e => e.value.toLowerCase()).map(e => ({
          address: e.value,
          ...(e.label && {label: e.label}),
        })),
        ...(c.organization && {organization: c.organization}),
      })),
    };
  },
};

const MAX_PHOTOS = 9;

const photos: Handler = {
  run: async args => {
    const count = typeof args.max_count === 'number' ? Math.min(Math.max(Math.round(args.max_count), 1), MAX_PHOTOS) : 1;
    let picked;
    try {
      picked = await pickPhotos(count);
    } catch (e) {
      throw new PhoneError('failed', e instanceof Error ? e.message : String(e));
    }
    return {photos: picked.slice(0, count).map(p => ({path: p.uri, name: p.name}))};
  },
};

const GB = 1024 ** 3;
const gigabytes = (bytes?: number) => (bytes === undefined ? undefined : Math.round((bytes / GB) * 10) / 10);

const device: Handler = {
  run: async () => {
    const s = await native!.deviceStatus().catch(e => {
      throw nativeFailure(e, []);
    });
    return {
      ...(s.battery !== undefined && {battery_percent: s.battery}),
      charging: !!s.charging,
      power_saving: !!s.powerSaving,
      network: s.network ?? 'unknown',
      ...(s.metered !== undefined && {metered: s.metered}),
      ...(s.storageFree !== undefined && {storage_free_gb: gigabytes(s.storageFree)}),
      ...(s.storageTotal !== undefined && {storage_total_gb: gigabytes(s.storageTotal)}),
      ...(s.ringer && {ringer: s.ringer}),
      ...(s.model && {model: s.model}),
      ...(s.system && {system: s.system}),
    };
  },
};

const share: Handler = {
  run: async args => {
    const outcome = await files!.share(str(args.path), str(args.name), str(args.mime)).catch(e => {
      throw new PhoneError('failed', String((e as {message?: string}).message ?? e));
    });
    // iOS says where it went once the sheet closes; Android only that it opened.
    return outcome === true ? {opened: true} : {shared: outcome !== null, ...(typeof outcome === 'string' && {to: outcome})};
  },
};

/** What this phone can do for the agent. HarmonyOS joins once its side is built and tested. */
export const HANDLERS: Record<string, Handler> =
  Platform.OS === 'android' || Platform.OS === 'ios'
    ? {
        phone_open: open,
        phone_photos: photos,
        ...(files?.share && {phone_share: share}),
        ...(native && {phone_location: location, phone_calendar: calendar, phone_contacts: contacts, phone_device: device}),
      }
    : {};

export const PHONE_CAPABILITIES = Object.keys(HANDLERS);

/** The "always allow" a call falls under, or null for a tool that never asks. */
export function trustScope(tool: string, args: Args = {}): string | null {
  const handler = HANDLERS[tool];
  return handler?.ask ? handler.scope?.(args) ?? tool : null;
}
