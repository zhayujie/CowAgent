import {useEffect, useState} from 'react';
import {AppState} from 'react-native';
import {ApiError, http} from '../api/http';
import {LOCAL_SERVER_ID} from '../kernel/localKernel';
import {useServerStore} from '../store/serverStore';
import {checkPermission} from '../media/permissions';
import {HANDLERS, PHONE_CAPABILITIES, PhoneError, trustScope} from './handlers';
import {askConfirm, clearPrompts, dismissPrompt, isTrusted, loadTrusted, setTrusted, showBlocked} from './prompts';

/**
 * Carries out the phone tools of the kernel embedded in this app: polls it
 * for what the agent asked the phone to do and answers each request. Runs
 * while the app shows and is signed in to its own kernel; other servers have
 * no phone to act on.
 */

interface PhoneRequest {
  id: string;
  tool: string;
  args: Record<string, unknown>;
}

type Answer = {ok: true; result?: unknown} | {ok: false; error: string; message?: string};

const POLL_WAIT_S = 25;

const onLocalKernel = () => {
  const {activeId, authed} = useServerStore.getState();
  return activeId === LOCAL_SERVER_ID && authed;
};

function reply(id: string, answer: Answer) {
  if (onLocalKernel()) {
    http.request(`/api/phone/requests/${id}`, {method: 'POST', body: answer}).catch(() => undefined);
  }
}

async function carryOut(req: PhoneRequest) {
  const handler = HANDLERS[req.tool];
  try {
    if (!handler) {
      throw new PhoneError('unsupported');
    }
    const args = req.args ?? {};
    // Allowing it here would only lead to a dialog the system no longer shows.
    if (handler.permission && (await checkPermission(handler.permission)) === 'blocked') {
      showBlocked(req.id, handler.permission);
      throw new PhoneError('permission_blocked');
    }
    const scope = trustScope(req.tool, args);
    await loadTrusted();
    if (handler.ask && scope && !isTrusted(scope)) {
      const {action, target} = handler.ask(args);
      const choice = await askConfirm(req.id, action, target ?? '');
      if (choice === 'deny') {
        throw new PhoneError('declined');
      }
      if (choice === 'always') {
        setTrusted(scope, true);
      }
    }
    reply(req.id, {ok: true, result: await handler.run(args, req.id)});
  } catch (e) {
    reply(req.id, e instanceof PhoneError ? {ok: false, error: e.code, message: e.message} : {ok: false, error: 'failed', message: String(e)});
  }
}

/** Whether requests are carried out now. */
let active = false;
let polling = false;

/**
 * A poll still out when the app leaves the screen can bring a request back, and
 * Android counts a permission dialog or a call overlay as leaving. Such a
 * request waits for the app to return, as long as the kernel would have waited
 * to deliver it, before it is turned down.
 */
const HOLD_MS = 15000;
const held = new Map<string, {req: PhoneRequest; timer: ReturnType<typeof setTimeout>}>();

function hold(req: PhoneRequest) {
  const timer = setTimeout(() => {
    held.delete(req.id);
    reply(req.id, {ok: false, error: 'app_inactive'});
  }, HOLD_MS);
  held.set(req.id, {req, timer});
}

function drop(id: string) {
  clearTimeout(held.get(id)?.timer);
  held.delete(id);
}

function releaseHeld() {
  const reqs = [...held.values()].map(h => h.req);
  reqs.forEach(req => drop(req.id));
  reqs.forEach(carryOut);
}

/** One loop at most: coming back while a poll is still out only turns the flag back on. */
function poll() {
  if (polling) {
    return;
  }
  polling = true;
  (async () => {
    let backoff = 1000;
    while (active) {
      try {
        const res = await http.request<{requests?: PhoneRequest[]; cancelled?: string[]}>('/api/phone/poll', {
          method: 'POST',
          body: {capabilities: PHONE_CAPABILITIES, wait: POLL_WAIT_S},
          timeoutMs: (POLL_WAIT_S + 15) * 1000,
        });
        backoff = 1000;
        res.cancelled?.forEach(id => {
          drop(id);
          dismissPrompt(id);
        });
        res.requests?.forEach(req => (active ? carryOut(req) : hold(req)));
      } catch (e) {
        // A kernel from before phone tools; asked again only on the next activation.
        if (e instanceof ApiError && e.status === 404) {
          active = false;
          return;
        }
        await new Promise(r => setTimeout(r, backoff));
        backoff = Math.min(backoff * 2, 5000);
      }
    }
  })().finally(() => {
    polling = false;
    if (active) {
      poll();
    }
  });
}

export function usePhoneBridge(): void {
  const local = useServerStore(s => s.activeId === LOCAL_SERVER_ID && s.authed);
  // iOS goes inactive under a system dialog, which is still the app on screen.
  const [shown, setShown] = useState(AppState.currentState !== 'background');
  useEffect(() => {
    const sub = AppState.addEventListener('change', state => setShown(state !== 'background'));
    return () => sub.remove();
  }, []);
  useEffect(() => {
    if (!local) {
      // Nothing asked by the kernel left behind can still be carried out.
      clearPrompts();
      [...held.keys()].forEach(drop);
    }
    if (!local || !shown || !PHONE_CAPABILITIES.length) {
      return;
    }
    active = true;
    releaseHeld();
    poll();
    return () => {
      active = false;
    };
  }, [local, shown]);
}
