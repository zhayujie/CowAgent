import { TurboModule, TurboModuleContext } from '@rnoh/react-native-openharmony/ts';
import { calendarManager } from '@kit.CalendarKit';
import { contact } from '@kit.ContactsKit';
import { geoLocationManager } from '@kit.LocationKit';
import { notificationManager } from '@kit.NotificationKit';
import { backgroundTaskManager, reminderAgentManager } from '@kit.BackgroundTasksKit';
import { batteryInfo, deviceInfo, power } from '@kit.BasicServicesKit';
import type { BusinessError } from '@kit.BasicServicesKit';
import { statfs } from '@kit.CoreFileKit';
import { connection } from '@kit.NetworkKit';
import { audio } from '@kit.AudioKit';
import { wantAgent } from '@kit.AbilityKit';
import type { ApplicationStateChangeCallback } from '@kit.AbilityKit';
import { NotificationTap, SESSION_PARAM } from './SharedIntake';

export const COW_DEVICE_MODULE = 'CowDevice';

const PERMISSION_DENIED = 201;
const LOCATION_SWITCH_OFF = 3301100;
const LOCATE_TIMEOUT_MS = 15000;
// The system keeps at most 30 reminders per app.
const MAX_REMINDERS = 30;

/** Rejections carry one of the codes the JS side knows (handlers.ts). */
class CodedError extends Error {
  code: string;

  constructor(code: string, message: string) {
    super(message);
    this.code = code;
  }
}

function codeOf(e: Object): number {
  return (e as BusinessError).code ?? 0;
}

export interface Fix {
  latitude: number;
  longitude: number;
  accuracy: number;
  altitude: number;
  time: number;
  address?: string;
}

export interface NativeEvent {
  title: string;
  start: number;
  end: number;
  allDay: boolean;
  location: string;
  notes: string;
  calendar: string;
}

export interface NewEvent {
  title: string;
  start: number;
  end: number;
  allDay: boolean;
  location?: string;
  notes?: string;
  reminderMinutes?: number;
}

export interface CreatedEvent {
  id: string;
  calendar: string;
}

export interface Labeled {
  value: string;
  label: string;
}

export interface NativeContact {
  name: string;
  phones: Labeled[];
  emails: Labeled[];
  organization: string;
}

export interface NativeStatus {
  battery: number;
  charging: boolean;
  powerSaving: boolean;
  network: string;
  metered?: boolean;
  storageFree?: number;
  storageTotal?: number;
  ringer?: string;
  model: string;
  system: string;
}

export interface Reminder {
  at: number;
  title: string;
  body: string;
  session?: string;
}

function calendarName(cal: calendarManager.Calendar): string {
  const account = cal.getAccount();
  return account.displayName || account.name;
}

function hashOf(text: string): number {
  let h = 0;
  for (let i = 0; i < text.length; i++) {
    h = (h * 31 + text.charCodeAt(i)) | 0;
  }
  return h;
}

/**
 * The phone itself for the agent's phone tools, and the notifications and reminders that
 * reach the user while the app is away. The same interface as CowDevice on Android.
 * Contacts come from the system picker: reading the address book is a restricted
 * permission on HarmonyOS, the picker needs none and hands back only what the user chose.
 */
export class CowDeviceModule extends TurboModule {
  private foreground = true;
  private suspendDelay = -1;
  private readonly watcher: ApplicationStateChangeCallback = {
    onApplicationForeground: () => {
      this.foreground = true;
    },
    onApplicationBackground: () => {
      this.foreground = false;
    },
  };

  constructor(ctx: TurboModuleContext) {
    super(ctx);
    ctx.uiAbilityContext.getApplicationContext().on('applicationStateChange', this.watcher);
  }

  __onDestroy__(): void {
    this.releaseBackground();
    this.ctx.uiAbilityContext.getApplicationContext().off('applicationStateChange', this.watcher);
  }

  async currentLocation(): Promise<Fix> {
    if (!geoLocationManager.isLocationEnabled()) {
      throw new CodedError('location_off', 'Location is turned off');
    }
    const request: geoLocationManager.SingleLocationRequest = {
      locatingPriority: geoLocationManager.LocatingPriority.PRIORITY_LOCATING_SPEED,
      locatingTimeoutMs: LOCATE_TIMEOUT_MS,
    };
    let loc: geoLocationManager.Location;
    try {
      loc = await geoLocationManager.getCurrentLocation(request);
    } catch (e) {
      const code = codeOf(e as Object);
      const message = (e as BusinessError).message ?? String(e);
      if (code === PERMISSION_DENIED) {
        throw new CodedError('permission_denied', message);
      }
      throw new CodedError(code === LOCATION_SWITCH_OFF ? 'location_off' : 'no_fix', message);
    }
    const fix: Fix = {
      latitude: loc.latitude,
      longitude: loc.longitude,
      accuracy: loc.accuracy,
      altitude: loc.altitude,
      time: loc.timeStamp,
    };
    try {
      if (geoLocationManager.isGeocoderAvailable()) {
        const found = await geoLocationManager.getAddressesFromLocation({
          latitude: loc.latitude,
          longitude: loc.longitude,
          maxItems: 1,
        });
        const place = found.length > 0 ? found[0].placeName : undefined;
        if (place) {
          fix.address = place;
        }
      }
    } catch (e) {
      // The coordinates are the answer; the address only helps reading them.
    }
    return fix;
  }

  private calendars(): calendarManager.CalendarManager {
    return calendarManager.getCalendarManager(this.ctx.uiAbilityContext);
  }

  /** Only the calendars this app may read: its own and the default one. */
  async calendarEvents(start: number, end: number): Promise<NativeEvent[]> {
    let all: calendarManager.Calendar[];
    try {
      all = await this.calendars().getAllCalendars();
    } catch (e) {
      throw new CodedError(codeOf(e as Object) === PERMISSION_DENIED ? 'permission_denied' : 'failed', String(e));
    }
    const found: NativeEvent[] = [];
    for (const cal of all) {
      const events = await cal.getEvents(calendarManager.EventFilter.filterByTime(start, end));
      const name = calendarName(cal);
      for (const ev of events) {
        found.push({
          title: ev.title ?? '',
          start: ev.startTime,
          end: ev.endTime,
          allDay: ev.isAllDay ?? false,
          location: ev.location?.location ?? '',
          notes: ev.description ?? '',
          calendar: name,
        });
      }
    }
    return found.sort((a, b) => a.start - b.start);
  }

  async createCalendarEvent(event: NewEvent): Promise<CreatedEvent> {
    let cal: calendarManager.Calendar;
    try {
      cal = await this.calendars().getCalendar();
    } catch (e) {
      throw new CodedError(codeOf(e as Object) === PERMISSION_DENIED ? 'permission_denied' : 'no_calendar', String(e));
    }
    const added: calendarManager.Event = {
      type: calendarManager.EventType.NORMAL,
      title: event.title,
      startTime: event.start,
      endTime: event.end,
      isAllDay: event.allDay,
    };
    if (event.location) {
      added.location = { location: event.location };
    }
    if (event.notes) {
      added.description = event.notes;
    }
    if (event.reminderMinutes !== undefined && event.reminderMinutes >= 0) {
      added.reminderTime = [event.reminderMinutes];
    }
    try {
      const id = await cal.addEvent(added);
      return { id: String(id), calendar: calendarName(cal) };
    } catch (e) {
      throw new CodedError(codeOf(e as Object) === PERMISSION_DENIED ? 'permission_denied' : 'failed', String(e));
    }
  }

  /** The user picks who; the agent's query can't be searched without the address book permission. */
  async searchContacts(_query: string, limit: number): Promise<NativeContact[]> {
    let picked: contact.Contact[];
    try {
      picked = await contact.selectContacts({ isMultiSelect: limit > 1, maxSelectable: Math.max(1, limit) });
    } catch (e) {
      // Backing out of the picker.
      return [];
    }
    return picked.slice(0, limit).map((c): NativeContact => ({
      name: c.name?.fullName ?? '',
      phones: (c.phoneNumbers ?? []).map((p): Labeled => ({ value: p.phoneNumber, label: p.labelName ?? '' })),
      emails: (c.emails ?? []).map((m): Labeled => ({ value: m.email, label: m.labelName ?? '' })),
      organization: c.organization?.name ?? '',
    }));
  }

  async deviceStatus(): Promise<NativeStatus> {
    const charge = batteryInfo.chargingStatus;
    const powerMode = power.getPowerMode();
    const status: NativeStatus = {
      battery: batteryInfo.batterySOC,
      charging: charge === batteryInfo.BatteryChargeState.ENABLE || charge === batteryInfo.BatteryChargeState.FULL,
      powerSaving: powerMode === power.DevicePowerMode.MODE_POWER_SAVE ||
        powerMode === power.DevicePowerMode.MODE_EXTREME_POWER_SAVE,
      network: 'none',
      model: deviceInfo.marketName || deviceInfo.productModel,
      system: `${deviceInfo.distributionOSName || 'HarmonyOS'} ${deviceInfo.distributionOSVersion}`.trim(),
    };
    try {
      if (connection.hasDefaultNetSync()) {
        const caps = connection.getNetCapabilitiesSync(connection.getDefaultNetSync());
        const bearers = caps.bearerTypes;
        status.network = bearers.includes(connection.NetBearType.BEARER_WIFI) ? 'wifi'
          : bearers.includes(connection.NetBearType.BEARER_CELLULAR) ? 'cellular'
            : bearers.includes(connection.NetBearType.BEARER_ETHERNET) ? 'ethernet'
              : bearers.includes(connection.NetBearType.BEARER_VPN) ? 'vpn' : 'other';
        status.metered = !(caps.networkCap ?? []).includes(connection.NetCap.NET_CAPABILITY_NOT_METERED);
      }
    } catch (e) {
      status.network = 'other';
    }
    try {
      const dir = this.ctx.uiAbilityContext.filesDir;
      status.storageFree = statfs.getFreeSizeSync(dir);
      status.storageTotal = statfs.getTotalSizeSync(dir);
    } catch (e) {
      // Left out rather than guessed.
    }
    try {
      const volume = audio.getAudioManager().getVolumeManager().getVolumeGroupManagerSync(audio.DEFAULT_VOLUME_GROUP_ID);
      const mode = await volume.getRingerMode();
      status.ringer = mode === audio.AudioRingMode.RINGER_MODE_SILENT ? 'silent'
        : mode === audio.AudioRingMode.RINGER_MODE_VIBRATE ? 'vibrate' : 'normal';
    } catch (e) {
      // Left out rather than guessed.
    }
    return status;
  }

  /** What happened while the app was away; shown only then, as on screen the chat tells it. Tapping it opens `session`. */
  async notice(kind: string, key: string, title: string, body: string, session?: string): Promise<void> {
    if (this.foreground) {
      return;
    }
    const context = this.ctx.uiAbilityContext;
    const parameters: Record<string, Object> = {};
    if (session) {
      parameters[SESSION_PARAM] = session;
    }
    const open = await wantAgent.getWantAgent({
      wants: [{ bundleName: context.abilityInfo.bundleName, abilityName: context.abilityInfo.name, parameters }],
      actionType: wantAgent.OperationType.START_ABILITY,
      // Each notice keeps its own want, so a tap opens its own chat.
      requestCode: hashOf(key),
      actionFlags: [wantAgent.WantAgentFlags.UPDATE_PRESENT_FLAG],
    });
    await notificationManager.publish({
      // A newer notice for the same chat or task takes the place of the last one.
      id: hashOf(key),
      label: kind,
      notificationSlotType: kind === 'task' ? notificationManager.SlotType.SERVICE_INFORMATION
        : notificationManager.SlotType.SOCIAL_COMMUNICATION,
      content: {
        notificationContentType: notificationManager.ContentType.NOTIFICATION_CONTENT_LONG_TEXT,
        longText: { title, text: body, longText: body, briefText: '', expandedTitle: title },
      },
      wantAgent: open,
      tapDismissed: true,
    });
  }

  /** The chat of the notification or reminder the app was opened from, once; null otherwise. */
  async takeNotificationTap(): Promise<string | null> {
    return NotificationTap.take();
  }

  /** A short-term task: the system lets the app run on for a few minutes in the background. */
  holdBackground(): void {
    if (this.suspendDelay >= 0) {
      return;
    }
    try {
      const info = backgroundTaskManager.requestSuspendDelay('reply', () => this.releaseBackground());
      this.suspendDelay = info.requestId;
    } catch (e) {
      // Out of quota for today: the reply goes on until the system suspends the app.
    }
  }

  releaseBackground(): void {
    if (this.suspendDelay < 0) {
      return;
    }
    const id = this.suspendDelay;
    this.suspendDelay = -1;
    try {
      backgroundTaskManager.cancelSuspendDelay(id);
    } catch (e) {
      // Already expired.
    }
  }

  /**
   * Replaces the app's reminders with these, which the system shows when due whether the app
   * runs or not. The kernel can't run with the app suspended, so a task reminder only says to
   * open the app. Resolves with how many were set.
   */
  async scheduleReminders(items: Reminder[]): Promise<number> {
    await reminderAgentManager.cancelAllReminders();
    const context = this.ctx.uiAbilityContext;
    const now = Date.now();
    let set = 0;
    for (const item of items) {
      if (set >= MAX_REMINDERS) {
        break;
      }
      if (item.at <= now) {
        continue;
      }
      const at = new Date(item.at);
      const parameters: Record<string, Object> = {};
      if (item.session) {
        parameters[SESSION_PARAM] = item.session;
      }
      const request: reminderAgentManager.ReminderRequestCalendar = {
        reminderType: reminderAgentManager.ReminderType.REMINDER_TYPE_CALENDAR,
        dateTime: {
          year: at.getFullYear(),
          month: at.getMonth() + 1,
          day: at.getDate(),
          hour: at.getHours(),
          minute: at.getMinutes(),
          second: at.getSeconds(),
        },
        title: item.title,
        content: item.body,
        ringDuration: 0,
        snoozeTimes: 0,
        tapDismissed: true,
        wantAgent: {
          pkgName: context.abilityInfo.bundleName,
          abilityName: context.abilityInfo.name,
          parameters,
        },
        slotType: notificationManager.SlotType.SERVICE_INFORMATION,
      };
      try {
        await reminderAgentManager.publishReminder(request);
        set++;
      } catch (e) {
        // Notifications off, or the system's limit reached: the rest would fail alike.
        if (set === 0) {
          throw e as Error;
        }
        break;
      }
    }
    return set;
  }
}
