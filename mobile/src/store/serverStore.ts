import {create} from 'zustand';
import {checkAuth, login, probeServer, updateConfig} from '../api/cowApi';
import {ApiError, http, normalizeBaseUrl} from '../api/http';
import {
  discover,
  isDeviceToken,
  MIN_SERVER_VERSION,
  redeem,
  revokeToken,
  sameDevice,
  type DiscoverFailure,
  type PairTarget,
} from '../api/pairing';
import {DEFAULT_SERVER_NAME, DEFAULT_SERVER_URL} from '../config/defaults';
import {getLang, tr, trf, useLangStore, type MessageKey} from '../i18n';
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
  /** How this device signed in; profiles saved before pairing existed have none. */
  via?: 'pairing' | 'password';
  /** The id the server answers discovery with; its token goes nowhere else. */
  instanceId?: string;
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
  /** Why the login screen took over from a signed-in server, shown there once. */
  problem: string | null;
  hydrate: () => Promise<void>;
  /** Redeem a pairing code for a token of this device's own and switch to that server. */
  pair: (target: PairTarget) => Promise<void>;
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
  /** Whether the login screen opens on the address form rather than the welcome step. */
  loginForm: boolean;
  /** Open the login screen for another server, keeping the current one's token. */
  addServer: (form?: boolean) => void;
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

const DISCOVER_FAILURES: Record<DiscoverFailure, MessageKey> = {
  unreachable: 'connect_err_unreachable_host',
  timeout: 'connect_err_timeout',
  login: 'connect_err_login',
  outdated: 'connect_err_outdated',
  not_cowagent: 'connect_err_not_cowagent',
};

export function describePairError(e: unknown): string {
  if (e instanceof ApiError) {
    const reason = String(e.body?.reason ?? '');
    if (reason === 'invalid_code') {
      return tr('connect_err_invalid_code');
    }
    if (reason === 'locked') {
      return trf('connect_err_locked', {s: Number(e.body?.retry_after) || 60});
    }
    const key = DISCOVER_FAILURES[reason as DiscoverFailure];
    if (key) {
      return trf(key, {host: String(e.body?.host ?? ''), status: e.status ?? '?', min: MIN_SERVER_VERSION});
    }
    if (e.kind === 'network' || e.kind === 'timeout') {
      return tr('connect_err_unreachable');
    }
  }
  return describeConnectError(e);
}

async function persist(servers: ServerProfile[], activeId: string | null) {
  await writeJSON(SERVERS_KEY, {servers, activeId} satisfies PersistedServers);
}

/**
 * Hold the token back unless the server's address still leads to the device
 * that issued it. Pairings from before devices had ids take the first id seen.
 */
function guardIdentity(profile: ServerProfile, confirmed = false) {
  if (profile.local) {
    http.setIdentityCheck(null);
    return;
  }
  http.setIdentityCheck(async () => {
    let info;
    try {
      info = await discover(profile.baseUrl, 8000);
    } catch (e) {
      const reason = e instanceof ApiError ? e.body?.reason : undefined;
      if (reason === 'unreachable' || reason === 'timeout') {
        return 'unreachable';
      }
      // Something answers there, but not as a CowAgent this app works with.
      onWrongDevice(profile, reason === 'outdated' ? describePairError(e) : undefined);
      return 'wrong_device';
    }
    const known = currentProfile(profile.id)?.instanceId ?? profile.instanceId;
    if (!sameDevice(known, info)) {
      onWrongDevice(profile);
      return 'wrong_device';
    }
    if (!known && info.id) {
      adoptInstanceId(profile.id, info.id);
    }
    return 'ok';
  }, confirmed);
}

function currentProfile(id: string): ServerProfile | undefined {
  return useServerStore.getState().servers.find(s => s.id === id);
}

function adoptInstanceId(id: string, instanceId: string) {
  const {servers, activeId} = useServerStore.getState();
  const next = servers.map(s => (s.id === id ? {...s, instanceId} : s));
  useServerStore.setState({servers: next});
  persist(next, activeId).catch(() => undefined);
}

/** The active server's address now answers as another machine: step out to the login screen. */
function onWrongDevice(profile: ServerProfile, problem?: string) {
  const {activeId, authed} = useServerStore.getState();
  if (activeId !== profile.id || !authed) {
    return;
  }
  leaveActive();
  useServerStore.setState({
    authed: false,
    returnTo: null,
    loginForm: false,
    problem: problem ?? trf('connect_err_wrong_device', {name: profile.name}),
  });
}

/**
 * An older CowAgent accepts the password but has no discovery, so the identity
 * check would sign the app out a minute later: refuse it up front instead.
 */
async function requireCurrentServer(baseUrl: string) {
  try {
    await discover(baseUrl);
  } catch (e) {
    const reason = e instanceof ApiError ? e.body?.reason : undefined;
    if (reason === 'outdated' || reason === 'not_cowagent') {
      throw new ApiError('server', describePairError(e));
    }
  }
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
    confirm: async () => (await http.confirmIdentity()) === 'ok',
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
  if (!identity.local) {
    await requireCurrentServer(baseUrl);
  }
  const info: ServerInfo = await probeServer(baseUrl);
  if (!info.auth_required) {
    throw new ApiError('server', tr('login_err_no_password'));
  }
  http.setBaseUrl(baseUrl);
  const token = await login(password);
  if (!token) {
    throw new ApiError('server', tr('login_err_no_token'));
  }
  await activate(
    {
      id: identity.id,
      name: identity.name ?? info.name ?? baseUrl,
      baseUrl,
      wsUrl: info.ws_url ?? null,
      ...(identity.local ? {local: true} : {via: 'password' as const}),
    },
    token,
  );
}

/** Save a server with the token just issued for it and make it the active one. */
async function activate(profile: ServerProfile, token: string) {
  const servers = [profile, ...useServerStore.getState().servers.filter(s => s.id !== profile.id)];
  await secureStore.set(tokenKey(profile.id), token);
  await persist(servers, profile.id);
  http.setBaseUrl(profile.baseUrl);
  http.setToken(token);
  // Just paired or signed in there.
  guardIdentity(profile, true);
  useServerStore.setState({servers, activeId: profile.id, authed: true, returnTo: null, problem: null});
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
  problem: null,
  returnTo: null,
  loginForm: false,

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
    guardIdentity(active);
    set({hydrated: true, servers, activeId: active.id, authed: !!token});
    if (token) {
      await startRealtime(active, token, s => set({realtimeStatus: s}));
    }
  },

  pair: async target => {
    const result = await redeem(target);
    const id = serverIdFor(result.baseUrl);
    const previous = await secureStore.get(tokenKey(id));
    if (get().authed) {
      leaveActive();
    }
    const wsUrl = get().servers.find(s => s.id === id)?.wsUrl ?? null;
    await activate(
      {id, name: result.name, baseUrl: result.baseUrl, wsUrl, via: 'pairing', instanceId: result.instanceId || undefined},
      result.token,
    );
    // Paired again: the token this device held before is of no use to anyone now.
    if (isDeviceToken(previous) && previous !== result.token) {
      revokeToken(result.baseUrl, previous!, result.instanceId);
    }
  },

  relogin: async (password, issued) => {
    // The server keeps the device token that changed the password; only an
    // older server's password-signed token needs replacing.
    if (isDeviceToken(http.getToken())) {
      return;
    }
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
    guardIdentity(target);
    await persist(servers, id);
    set({activeId: id, authed: !!token, returnTo: null, loginForm: false, problem: null});
    if (token) {
      await startRealtime(target, token, s => set({realtimeStatus: s}));
    }
  },

  addServer: form => {
    const {activeId} = get();
    leaveActive();
    set({authed: false, activeId: null, returnTo: activeId, loginForm: !!form});
  },

  removeServer: async id => {
    const {servers, activeId} = get();
    if (id === activeId) {
      return;
    }
    const rest = servers.filter(s => s.id !== id);
    const target = servers.find(s => s.id === id);
    const token = await secureStore.get(tokenKey(id));
    if (target && token && !target.local) {
      revokeToken(target.baseUrl, token, target.instanceId);
    }
    await secureStore.remove(tokenKey(id));
    await removeKey(seqKey(id));
    await persist(rest, activeId);
    set({servers: rest});
  },

  logout: async () => {
    const {activeId} = get();
    const server = activeServer();
    const token = http.getToken();
    realtime.stop();
    if (activeId) {
      await secureStore.remove(tokenKey(activeId));
    }
    http.setToken(null);
    set({authed: false, realtimeStatus: 'idle', returnTo: null, loginForm: false});
    resetServerData();
    if (server && token && !server.local) {
      revokeToken(server.baseUrl, token, server.instanceId);
    }
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

/** Takes the name the active server goes by now, renamed there or from another client. */
export function noteServerName(name: string | undefined) {
  const profile = activeServer();
  if (!name || !profile || profile.local || profile.name === name) {
    return;
  }
  const {servers, activeId} = useServerStore.getState();
  const next = servers.map(s => (s.id === profile.id ? {...s, name} : s));
  useServerStore.setState({servers: next});
  persist(next, activeId).catch(() => undefined);
}

export function activeServer(): ServerProfile | undefined {
  const {servers, activeId} = useServerStore.getState();
  return servers.find(s => s.id === activeId);
}

/** Whether the active server is the kernel embedded in this app, which lacks some server features. */
export function useLocalServer(): boolean {
  return useServerStore(s => !!s.servers.find(x => x.id === s.activeId)?.local);
}
