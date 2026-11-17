import {create} from 'zustand';
import {checkAuth, login, probeServer, updateConfig} from '../api/cowApi';
import {ApiError, http, normalizeBaseUrl} from '../api/http';
import {DEFAULT_SERVER_NAME, DEFAULT_SERVER_URL} from '../config/defaults';
import {getLang, tr, trf, useLangStore} from '../i18n';
import {LOCAL_SERVER_ID, startLocalKernel} from '../kernel/localKernel';
import type {ServerEnvelope, ServerInfo} from '../protocol/envelope';
import {realtime, type RealtimeStatus} from '../realtime/RealtimeClient';
import {readJSON, removeKey, writeJSON} from '../storage/kv';
import {secureStore} from '../storage/secureStore';
import {resetServerData} from './reset';

export interface ServerProfile {
  id: string;
  name: string;
  baseUrl: string;
  wsUrl: string | null;
  /** The kernel embedded in this app; its address may change between launches. */
  local?: boolean;
}

interface PersistedServers {
  servers: ServerProfile[];
  activeId: string | null;
}

interface ServerState {
  hydrated: boolean;
  servers: ServerProfile[];
  activeId: string | null;
  authed: boolean;
  realtimeStatus: RealtimeStatus;
  hydrate: () => Promise<void>;
  connect: (rawUrl: string, password: string) => Promise<void>;
  /**
   * Tokens are signed with the password, so changing it needs a fresh one.
   * `issued` is the token the password change itself returned; older servers
   * send none, so the new password logs in again.
   */
  relogin: (password: string, issued?: string) => Promise<void>;
  /** Server to go back to from the login screen opened by `addServer`. */
  returnTo: string | null;
  /**
   * Make a saved server active; one without a stored token lands on the login screen.
   * `LOCAL_SERVER_ID` starts the embedded kernel and signs in to it.
   */
  switchTo: (id: string) => Promise<void>;
  /** Open the login screen for another server, keeping the current one's token. */
  addServer: () => void;
  removeServer: (id: string) => Promise<void>;
  logout: () => Promise<void>;
  /** After a 401: sign out only once the server confirms the token is really dead. */
  expireIfSignedOut: () => Promise<void>;
}

let passwordChange: Promise<unknown> | null = null;

/**
 * Requests answered after the server switched passwords but before this
 * device holds the new token fail with the old one; their 401s wait for this.
 */
export async function changingPassword<T>(work: Promise<T>): Promise<T> {
  passwordChange = work;
  try {
    return await work;
  } finally {
    if (passwordChange === work) {
      passwordChange = null;
    }
  }
}

const SERVERS_KEY = 'servers';
const tokenKey = (serverId: string) => `token:${serverId}`;
const seqKey = (serverId: string) => `seq:${serverId}`;

type EnvelopeHandler = (envelope: ServerEnvelope) => void;
const envelopeHandlers = new Set<EnvelopeHandler>();

/** Route server pushes (scheduler runs, proactive messages...) to stores. */
export function onServerEnvelope(handler: EnvelopeHandler): () => void {
  envelopeHandlers.add(handler);
  return () => envelopeHandlers.delete(handler);
}

export function resolveWsUrl(baseUrl: string, wsUrl: string | null | undefined): string | null {
  if (!wsUrl) {
    return null;
  }
  if (/^wss?:\/\//i.test(wsUrl)) {
    return wsUrl;
  }
  const origin = baseUrl.replace(/^http/i, 'ws').replace(/\/+$/, '');
  return `${origin}${wsUrl.startsWith('/') ? '' : '/'}${wsUrl}`;
}

function serverIdFor(baseUrl: string): string {
  return baseUrl.toLowerCase();
}

export function describeConnectError(e: unknown): string {
  if (e instanceof ApiError) {
    switch (e.kind) {
      case 'timeout':
        return tr('login_err_timeout');
      case 'network':
        return tr('login_err_network');
      case 'unauthorized':
        return tr('login_err_unauthorized');
      case 'invalid_response':
        return tr('login_err_not_cow');
      case 'server':
        return e.message;
      default:
        return trf('login_err_server_status', {status: e.status ?? tr('common_unknown')});
    }
  }
  return e instanceof Error ? e.message : String(e);
}

async function persist(servers: ServerProfile[], activeId: string | null) {
  await writeJSON(SERVERS_KEY, {servers, activeId} satisfies PersistedServers);
}

async function startRealtime(
  server: ServerProfile,
  token: string,
  setStatus: (s: RealtimeStatus) => void,
) {
  realtime.stop();
  const url = resolveWsUrl(server.baseUrl, server.wsUrl);
  if (!url) {
    // Server has no shared WebSocket yet: chat streams fall back to SSE.
    return;
  }
  const lastSeq = await readJSON<number>(seqKey(server.id), 0);
  realtime.start({
    url,
    token,
    lastSeq,
    onEnvelope: envelope => envelopeHandlers.forEach(h => h(envelope)),
    onSeqCommitted: seq => {
      writeJSON(seqKey(server.id), seq).catch(() => undefined);
    },
    onStatus: setStatus,
  });
}

async function signIn(
  baseUrl: string,
  password: string,
  identity: {id: string; name?: string; local?: boolean},
) {
  const info: ServerInfo = await probeServer(baseUrl);
  if (!info.auth_required) {
    throw new ApiError('server', tr('login_err_no_password'));
  }
  http.setBaseUrl(baseUrl);
  const token = await login(password);
  if (!token) {
    throw new ApiError('server', tr('login_err_no_token'));
  }
  const {id} = identity;
  const profile: ServerProfile = {
    id,
    name: identity.name ?? info.name ?? baseUrl,
    baseUrl,
    wsUrl: info.ws_url ?? null,
    ...(identity.local ? {local: true} : {}),
  };
  const servers = [profile, ...useServerStore.getState().servers.filter(s => s.id !== id)];
  await secureStore.set(tokenKey(id), token);
  await persist(servers, id);
  http.setToken(token);
  useServerStore.setState({servers, activeId: id, authed: true, returnTo: null});
  await startRealtime(profile, token, s => useServerStore.setState({realtimeStatus: s}));
}

/**
 * This app is the embedded kernel's only client, so the kernel's replies and
 * logs follow the app's language, which only Settings pushes to other servers.
 */
async function syncKernelLanguage() {
  const langs = useLangStore.getState();
  if (!langs.hydrated) {
    await langs.hydrate();
  }
  await updateConfig({cow_lang: getLang()}).catch(() => undefined);
}

/** Drop the active server's live state; its token stays, so switching back needs no password. */
function leaveActive() {
  realtime.stop();
  http.setToken(null);
  resetServerData();
  useServerStore.setState({realtimeStatus: 'idle'});
}

export const useServerStore = create<ServerState>((set, get) => ({
  hydrated: false,
  servers: [],
  activeId: null,
  authed: false,
  realtimeStatus: 'idle',
  returnTo: null,

  hydrate: async () => {
    const saved = await readJSON<PersistedServers>(SERVERS_KEY, {
      servers: [],
      activeId: null,
    });
    let servers = saved.servers;
    if (servers.length === 0 && DEFAULT_SERVER_URL) {
      const baseUrl = normalizeBaseUrl(DEFAULT_SERVER_URL);
      servers = [
        {
          id: serverIdFor(baseUrl),
          // Resolved on read: the saved language may load after this, and a switch keeps the store.
          get name() {
            return DEFAULT_SERVER_NAME || tr('access_default_server_name');
          },
          baseUrl,
          wsUrl: null,
        },
      ];
    }
    const activeId = saved.activeId ?? servers[0]?.id;
    const active = servers.find(s => s.id === activeId) ?? servers[0];
    if (!active) {
      set({hydrated: true, servers, activeId: null, authed: false});
      return;
    }
    if (active.local) {
      // Signed in afresh on every launch: the native side keeps the password,
      // and a token from an earlier run may no longer verify.
      try {
        const {baseUrl, password} = await startLocalKernel();
        await signIn(baseUrl, password, {id: active.id, name: active.name, local: true});
        await syncKernelLanguage();
      } catch {
        set({hydrated: true, servers, activeId: active.id, authed: false});
        return;
      }
      set({hydrated: true});
      return;
    }
    http.setBaseUrl(active.baseUrl);
    const token = await secureStore.get(tokenKey(active.id));
    http.setToken(token);
    set({hydrated: true, servers, activeId: active.id, authed: !!token});
    if (token) {
      await startRealtime(active, token, s => set({realtimeStatus: s}));
    }
  },

  connect: async (rawUrl, password) => {
    const baseUrl = normalizeBaseUrl(rawUrl);
    const id = serverIdFor(baseUrl);
    await signIn(baseUrl, password, {id, name: get().servers.find(s => s.id === id)?.name});
  },

  relogin: async (password, issued) => {
    const profile = activeServer();
    const token = issued || (await login(password));
    if (!profile || !token) {
      throw new ApiError('server', tr('login_err_relogin'));
    }
    await secureStore.set(tokenKey(profile.id), token);
    http.setToken(token);
    await startRealtime(profile, token, s => set({realtimeStatus: s}));
  },

  switchTo: async id => {
    const {activeId, authed, servers} = get();
    if (id === activeId && authed) {
      return;
    }
    if (id === LOCAL_SERVER_ID) {
      // Started before leaving, so a kernel that fails to come up keeps the current server.
      const {baseUrl, password} = await startLocalKernel();
      leaveActive();
      try {
        await signIn(baseUrl, password, {id: LOCAL_SERVER_ID, local: true});
        // Wait so the first reply already follows the app language.
        await syncKernelLanguage();
      } catch (e) {
        set({activeId: LOCAL_SERVER_ID, authed: false});
        throw e;
      }
      return;
    }
    const target = servers.find(s => s.id === id);
    if (!target) {
      return;
    }
    const token = await secureStore.get(tokenKey(id));
    leaveActive();
    http.setBaseUrl(target.baseUrl);
    http.setToken(token);
    await persist(servers, id);
    set({activeId: id, authed: !!token, returnTo: null});
    if (token) {
      await startRealtime(target, token, s => set({realtimeStatus: s}));
    }
  },

  addServer: () => {
    const {activeId} = get();
    leaveActive();
    set({authed: false, activeId: null, returnTo: activeId});
  },

  removeServer: async id => {
    const {servers, activeId} = get();
    if (id === activeId) {
      return;
    }
    const rest = servers.filter(s => s.id !== id);
    await secureStore.remove(tokenKey(id));
    await removeKey(seqKey(id));
    await persist(rest, activeId);
    set({servers: rest});
  },

  logout: async () => {
    const {activeId} = get();
    realtime.stop();
    if (activeId) {
      await secureStore.remove(tokenKey(activeId));
    }
    http.setToken(null);
    set({authed: false, realtimeStatus: 'idle', returnTo: null});
    resetServerData();
  },

  expireIfSignedOut: async () => {
    if (passwordChange) {
      await passwordChange.catch(() => undefined);
    }
    // A failed check (offline, timeout) is no proof the token is dead.
    const dead = await checkAuth().then(
      r => r.auth_required && !r.authenticated,
      e => e instanceof ApiError && e.kind === 'unauthorized',
    );
    if (dead && get().authed) {
      await get().logout();
    }
  },
}));

export function activeServer(): ServerProfile | undefined {
  const {servers, activeId} = useServerStore.getState();
  return servers.find(s => s.id === activeId);
}

/** Whether the active server is the kernel embedded in this app, which lacks some server features. */
export function useLocalServer(): boolean {
  return useServerStore(s => !!s.servers.find(x => x.id === s.activeId)?.local);
}
