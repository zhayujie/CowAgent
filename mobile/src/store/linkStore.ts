import {AppState} from 'react-native';
import {create} from 'zustand';
import {http} from '../api/http';
import {activeServer, useServerStore} from './serverStore';

const PROBE_TIMEOUT_MS = 5000;
/** How often a remote device that answers is checked on, while the app is open. */
const HEARTBEAT_MS = 30_000;
/** Checks after a failure; it takes two failures in a row to call the device unreachable. */
const RETRY_MS = [2000, 4000, 8000, 15_000];

interface LinkState {
  /** The remote device in use has stopped answering. */
  down: boolean;
  /** A check asked for from the screen is under way. */
  checking: boolean;
  /** Bumped when the device answers again after failing, for screens to reload what failed meanwhile. */
  recovered: number;
}

export const useLinkStore = create<LinkState>(() => ({down: false, checking: false, recovered: 0}));

let failing = false;
let attempts = 0;
let timer: ReturnType<typeof setTimeout> | null = null;

/** The address to watch: a remote device signed in to, never the kernel on this phone. */
function watched(): string | null {
  const server = activeServer();
  return useServerStore.getState().authed && server && !server.local ? server.baseUrl : null;
}

function schedule(ms: number) {
  if (timer) {
    clearTimeout(timer);
  }
  timer = setTimeout(probe, ms);
}

function report(baseUrl: string, answered: boolean) {
  if (baseUrl !== watched()) {
    return;
  }
  if (answered) {
    const wasFailing = failing;
    failing = false;
    attempts = 0;
    useLinkStore.setState(s => ({down: false, recovered: wasFailing ? s.recovered + 1 : s.recovered}));
    schedule(HEARTBEAT_MS);
    return;
  }
  if (failing) {
    useLinkStore.setState({down: true});
  }
  failing = true;
  schedule(RETRY_MS[Math.min(attempts, RETRY_MS.length - 1)]);
  attempts += 1;
}

async function probe(): Promise<void> {
  const baseUrl = watched();
  if (!baseUrl || AppState.currentState !== 'active') {
    return;
  }
  const controller = new AbortController();
  const cut = setTimeout(() => controller.abort(), PROBE_TIMEOUT_MS);
  try {
    await fetch(`${baseUrl}/api/health`, {credentials: 'omit', signal: controller.signal});
    report(baseUrl, true);
  } catch {
    report(baseUrl, false);
  } finally {
    clearTimeout(cut);
  }
}

/** Checks right away instead of waiting for the next try. */
export async function checkLinkNow(): Promise<void> {
  attempts = 0;
  useLinkStore.setState({checking: true});
  await probe();
  useLinkStore.setState({checking: false});
}

function restart() {
  failing = false;
  attempts = 0;
  useLinkStore.setState({down: false});
  if (timer) {
    clearTimeout(timer);
    timer = null;
  }
  probe();
}

http.onReach = report;

useServerStore.subscribe((s, prev) => {
  if (s.activeId !== prev.activeId || s.authed !== prev.authed) {
    restart();
  }
});

AppState.addEventListener('change', state => {
  if (state === 'active') {
    attempts = 0;
    probe();
  } else if (timer) {
    clearTimeout(timer);
    timer = null;
  }
});
