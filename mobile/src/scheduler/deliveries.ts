import {useEffect, useState} from 'react';
import {AppState, Platform} from 'react-native';
import {http} from '../api/http';
import {showToast} from '../components/Toast';
import {tr, trf} from '../i18n';
import {LOCAL_SERVER_ID} from '../kernel/localKernel';
import {canNotify, notice} from '../notify/notice';
import type {TaskRun} from '../protocol/resources';
import {useAgentStore} from '../store/agentStore';
import {useChatStore} from '../store/chatStore';
import {useServerStore} from '../store/serverStore';
import {useSessionStore} from '../store/sessionStore';

/**
 * A scheduled task delivers into a session's history; nothing streams it to the app.
 * While the app shows, the run ledger is asked what fired since, like the web
 * console does: the open conversation reloads to show it, any other one moves up
 * the list with a notice.
 */

const POLL_MS = 10_000;
const SNIPPET = 60;
const NOTICE_MAX = 200;
const FINISHED = new Set(['done', 'success']);
const FAILED = new Set(['failed', 'error']);

const snippet = (text?: string) => {
  const line = (text ?? '').split('\n').find(l => l.trim())?.trim() ?? '';
  return line.length > SNIPPET ? `${line.slice(0, SNIPPET)}…` : line;
};

const clip = (text: string | undefined, max: number) => {
  const flat = (text ?? '').replace(/\s+/g, ' ').trim();
  return flat.length > max ? `${flat.slice(0, max)}…` : flat;
};

function deliver(run: TaskRun) {
  const sessionId = run.session_id;
  if (!sessionId) {
    return;
  }
  const chat = useChatStore.getState();
  if (chat.currentSessionId === sessionId) {
    chat.loadHistory(sessionId, run.agent_id || useAgentStore.getState().currentId);
  } else {
    showToast(trf('task_delivered', {name: run.task_name || '', text: snippet(run.output_preview)}));
  }
  useSessionStore.getState().refresh().catch(() => undefined);
}

/** Per server, so what fired while the app was away is caught up on its return. */
const cursors = new Map<string, {since: number; seen: Set<string>}>();

function watch(server: string): () => void {
  let stopped = false;
  let timer: ReturnType<typeof setTimeout> | undefined;
  // Runs from before the app first looked are already in the history it loads.
  const cursor = cursors.get(server) ?? {since: Math.floor(Date.now() / 1000), seen: new Set<string>()};
  cursors.set(server, cursor);
  const {seen} = cursor;

  const tick = async () => {
    try {
      const res = await http.request<{runs?: TaskRun[]}>(`/api/scheduler/runs?since=${cursor.since}&limit=20&agent_id=`);
      const runs = [...(res.runs ?? [])].sort((a, b) => a.started_at - b.started_at);
      // A run still going is asked about again until it lands.
      const running = runs.filter(r => r.status === 'running').map(r => r.started_at);
      for (const run of runs) {
        if (stopped || seen.has(run.run_id) || !FINISHED.has(run.status)) {
          continue;
        }
        seen.add(run.run_id);
        if (!run.channel_type || run.channel_type === 'web') {
          deliver(run);
        }
      }
      const latest = running.length ? Math.floor(Math.min(...running)) - 1 : Math.floor(runs[runs.length - 1]?.started_at ?? 0);
      cursor.since = Math.max(cursor.since, latest);
    } catch {
      // Asked again on the next tick.
    }
    if (!stopped) {
      timer = setTimeout(tick, POLL_MS);
    }
  };
  tick();
  return () => {
    stopped = true;
    clearTimeout(timer);
  };
}

const WAIT_S = 25;
/** Timers hold in the background, so a failed poll is retried at once, a few times. */
const AWAY_TRIES = 3;
/** Told by notification already, across trips to the background. */
const told = new Set<string>();

/**
 * In the background Android holds the app's timers but not its network replies, so a
 * server's ledger is long-polled instead, and a run that lands is told by notification.
 * The app's own kernel is frozen with the app then; its reminders tell its runs instead.
 * A server that cannot wait answers without an etag, which ends this.
 */
function watchAway(server: string): () => void {
  let stopped = false;
  const cursor = cursors.get(server);
  const since = cursor?.since ?? Math.floor(Date.now() / 1000);

  const loop = async () => {
    let etag = '';
    let failures = 0;
    while (!stopped) {
      let res: {runs?: TaskRun[]; etag?: string};
      try {
        res = await http.request<{runs?: TaskRun[]; etag?: string}>(
          `/api/scheduler/runs?since=${since}&limit=20&agent_id=&wait=${etag ? WAIT_S : 0}&etag=${etag}`,
          {timeoutMs: (WAIT_S + 15) * 1000},
        );
        failures = 0;
      } catch {
        if (++failures >= AWAY_TRIES) {
          return;
        }
        continue;
      }
      if (stopped || !res.etag) {
        return;
      }
      etag = res.etag;
      for (const run of res.runs ?? []) {
        const failed = FAILED.has(run.status);
        if ((!FINISHED.has(run.status) && !failed) || told.has(run.run_id) || cursor?.seen.has(run.run_id)) {
          continue;
        }
        told.add(run.run_id);
        if (run.channel_type && run.channel_type !== 'web') {
          continue;
        }
        const title = run.task_name || tr('task_reminder_fallback');
        const body = failed
          ? trf('task_failed_notice', {error: clip(run.error, NOTICE_MAX)})
          : clip(run.output_preview, NOTICE_MAX) || tr('task_done_notice');
        notice('task', run.run_id, title, body, run.session_id).catch(() => undefined);
      }
    }
  };
  loop().catch(() => undefined);
  return () => {
    stopped = true;
  };
}

export function useScheduledDeliveries(): void {
  const server = useServerStore(s => (s.authed ? s.activeId : null));
  const [shown, setShown] = useState(AppState.currentState === 'active');
  useEffect(() => {
    const sub = AppState.addEventListener('change', state => setShown(state === 'active'));
    return () => sub.remove();
  }, []);
  useEffect(() => {
    if (!server) {
      return;
    }
    if (shown) {
      return watch(server);
    }
    return Platform.OS === 'android' && server !== LOCAL_SERVER_ID && canNotify() ? watchAway(server) : undefined;
  }, [server, shown]);
}
