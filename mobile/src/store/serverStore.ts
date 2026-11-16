import {create} from 'zustand';
import {checkAuth, login, probeServer} from '../api/cowApi';
import {ApiError, http, normalizeBaseUrl} from '../api/http';
import {DEFAULT_SERVER_NAME, DEFAULT_SERVER_URL} from '../config/defaults';
import {tr, trf} from '../i18n';
import type {ServerEnvelope, ServerInfo} from '../protocol/envelope';
import {realtime, type RealtimeStatus} from '../realtime/RealtimeClient';
import {readJSON, writeJSON} from '../storage/kv';
import {secureStore} from '../storage/secureStore';
import {resetServerData} from './reset';

export interface ServerProfile {
  id: string;
  name: string;
  baseUrl: string;
  wsUrl: string | null;
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

export const useServerStore = create<ServerState>((set, get) => ({
  hydrated: false,
  servers: [],
  activeId: null,
  authed: false,
  realtimeStatus: 'idle',

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
    const info: ServerInfo = await probeServer(baseUrl);
    if (!info.auth_required) {
      throw new ApiError('server', tr('login_err_no_password'));
    }
    http.setBaseUrl(baseUrl);
    const token = await login(password);
    if (!token) {
      throw new ApiError('server', tr('login_err_no_token'));
    }
    const id = serverIdFor(baseUrl);
    const existing = get().servers.find(s => s.id === id);
    const profile: ServerProfile = {
      id,
      name: existing?.name ?? info.name ?? baseUrl,
      baseUrl,
      wsUrl: info.ws_url ?? null,
    };
    const servers = [profile, ...get().servers.filter(s => s.id !== id)];
    await secureStore.set(tokenKey(id), token);
    await persist(servers, id);
    http.setToken(token);
    set({servers, activeId: id, authed: true});
    await startRealtime(profile, token, s => set({realtimeStatus: s}));
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

  logout: async () => {
    const {activeId} = get();
    realtime.stop();
    if (activeId) {
      await secureStore.remove(tokenKey(activeId));
    }
    http.setToken(null);
    set({authed: false, realtimeStatus: 'idle'});
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
