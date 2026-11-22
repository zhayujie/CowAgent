import {useEffect} from 'react';
import {AppState, NativeModules} from 'react-native';
import {http} from '../api/http';
import {tr, trf} from '../i18n';
import {LOCAL_SERVER_ID} from '../kernel/localKernel';
import {askNotifications} from '../notify/notice';
import {onToolDone} from '../store/chatStore';
import {useServerStore} from '../store/serverStore';

/**
 * The kernel inside the app stops when the system suspends or ends the app, and its
 * scheduled tasks with it. So the system is handed the coming runs as notifications,
 * which fire whether the app is open or not; on screen the chat shows the delivery
 * instead. A task for the agent says to open the app to run it, unless the kernel is
 * still there when it comes due (Android), which runs it then and tells its result.
 */

interface Upcoming {
  task_id: string;
  name: string;
  /** Epoch seconds. */
  at: number;
  action_type: string;
  channel_type: string;
  text: string;
}

interface Reminder {
  at: number;
  title: string;
  body: string;
  /** For a task the agent carries out: its id, and what to say about its run. */
  task?: string;
  done?: string;
  failed?: string;
  running?: string;
}

const native: {scheduleReminders?(items: Reminder[]): Promise<number>} | undefined = NativeModules.CowDevice;

const AHEAD_HOURS = 24 * 7;
const MAX_REMINDERS = 50;
const REFRESH_MS = 60_000;

const onLocalKernel = () => {
  const {activeId, authed} = useServerStore.getState();
  return activeId === LOCAL_SERVER_ID && authed;
};

let syncing: Promise<void> | null = null;

/**
 * Hands the system the runs of the next week. With `ask`, right after the user set a task
 * up, notifications are asked for if they never were.
 */
export function syncReminders(ask = false): Promise<void> {
  if (!native?.scheduleReminders || !onLocalKernel()) {
    return Promise.resolve();
  }
  const run = async () => {
    // Queued behind another sync, by when the app may be on another server.
    if (!onLocalKernel()) {
      return;
    }
    const res = await http.request<{runs?: Upcoming[]}>(
      `/api/scheduler/upcoming?hours=${AHEAD_HOURS}&limit=${MAX_REMINDERS}`,
    );
    // Tasks for a chat channel reach the user there.
    const runs = (res.runs ?? []).filter(r => r.channel_type === 'web');
    if (runs.length && ask) {
      await askNotifications(true);
    }
    if (!onLocalKernel()) {
      return;
    }
    await native.scheduleReminders!(
      runs.map((r): Reminder => {
        const name = r.name || tr('task_reminder_fallback');
        const at = r.at * 1000;
        if (r.action_type === 'send_message') {
          return {at, title: name, body: r.text || name};
        }
        // A task for the agent only runs with the kernel, which may be gone by then.
        return {
          at,
          title: name,
          body: trf('task_reminder_open', {text: r.text || name}),
          task: r.task_id,
          done: tr('task_done_notice'),
          failed: tr('task_failed_notice'),
          running: tr('task_running_notice'),
        };
      }),
    );
  };
  // A sync asked for while one runs follows it, so the last word is the newest list.
  syncing = (syncing ?? Promise.resolve()).then(run).catch(() => undefined);
  return syncing;
}

/** Keeps the system's reminders in step while the app runs on its own kernel, and once more on leaving. */
export function useTaskReminders(): void {
  const local = useServerStore(s => s.activeId === LOCAL_SERVER_ID && s.authed);
  useEffect(() => {
    if (!local) {
      return;
    }
    syncReminders();
    const timer = setInterval(() => AppState.currentState === 'active' && syncReminders(), REFRESH_MS);
    const sub = AppState.addEventListener('change', state => state === 'background' && syncReminders());
    // A task the agent just set up is handed over at once, and notifications asked for with it.
    const off = onToolDone(tool => tool === 'scheduler' && syncReminders(true));
    return () => {
      clearInterval(timer);
      sub.remove();
      off();
    };
  }, [local]);
}
