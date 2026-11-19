import {Platform} from 'react-native';
import {ApiError, HttpClient, isPublicCleartext, normalizeBaseUrl} from './http';

/**
 * A pairing offer: the one-time code and the addresses the instance said it
 * can be reached at, most likely first. Comes from a scanned QR code, a
 * `cowagent://pair` link, or an address and short code typed by hand.
 */
export interface PairTarget {
  code: string;
  urls: string[];
}

export interface PairResult {
  baseUrl: string;
  token: string;
  name: string;
  /** The id the device answers discovery with; its token goes nowhere else. */
  instanceId: string;
}

/** Answer of `GET /.well-known/cowagent`. */
export interface Discovery {
  type: string;
  protocol: number;
  id?: string;
  version?: string;
  auth?: {required: boolean; methods: string[]};
}

/**
 * Why an address isn't a CowAgent this app can pair with, as `body.reason`
 * of the ApiError thrown: unreachable / timeout / login (a sign-in gateway in
 * front) / outdated (CowAgent from before pairing) / not_cowagent.
 */
export type DiscoverFailure = 'unreachable' | 'timeout' | 'login' | 'outdated' | 'not_cowagent';

function failure(reason: DiscoverFailure, baseUrl: string, status?: number): ApiError {
  const kind = reason === 'unreachable' ? 'network' : reason === 'timeout' ? 'timeout' : 'server';
  return new ApiError(kind, reason, status, {reason, host: baseUrl.replace(/^https?:\/\//, '')});
}

// When several addresses fail, report the one that says the most.
const FAILURE_RANK: DiscoverFailure[] = ['not_cowagent', 'outdated', 'login', 'timeout', 'unreachable'];

function rank(e: unknown): number {
  const reason = e instanceof ApiError ? (e.body?.reason as DiscoverFailure) : undefined;
  const i = reason ? FAILURE_RANK.indexOf(reason) : -1;
  return i < 0 ? FAILURE_RANK.length : i;
}

/** Whether discovery came from the device a token was issued by; pairings from before ids are trusted. */
export function sameDevice(instanceId: string | undefined, info: Discovery | null): boolean {
  return !instanceId || (!!info && info.id === instanceId);
}

export const DEVICE_TOKEN_PREFIX = 'cowd.';
/** The oldest CowAgent this app works with: the first to answer discovery. */
export const MIN_SERVER_VERSION = '2.3.0';
const DISCOVER_TIMEOUT_MS = 4000;

export function isDeviceToken(token: string | null | undefined): boolean {
  return !!token && token.startsWith(DEVICE_TOKEN_PREFIX);
}

/** The pairing offer in a scanned or opened `cowagent://pair?...` link, or null. */
export function parsePairLink(raw: string): PairTarget | null {
  const text = raw.trim();
  const m = /^cowagent:\/\/pair\/?\?(.*)$/i.exec(text);
  if (!m) {
    return null;
  }
  let code = '';
  const urls: string[] = [];
  for (const part of m[1].split('&')) {
    const eq = part.indexOf('=');
    const key = eq < 0 ? part : part.slice(0, eq);
    let value = '';
    try {
      value = decodeURIComponent((eq < 0 ? '' : part.slice(eq + 1)).replace(/\+/g, ' '));
    } catch {
      continue;
    }
    if (key === 'c') {
      code = value;
    } else if (key === 'u' && /^https?:\/\//i.test(value) && !urls.includes(value)) {
      urls.push(value.replace(/\/+$/, ''));
    }
  }
  return code && urls.length ? {code, urls} : null;
}

/**
 * Addresses to try for one typed by hand. Without a scheme, a local network
 * address is tried over http first, since that is how a computer at home
 * usually serves; anything else only over https.
 */
export function addressCandidates(raw: string): string[] {
  const text = raw.trim().replace(/\/+$/, '');
  if (!text) {
    return [];
  }
  if (/^https?:\/\//i.test(text)) {
    return [text];
  }
  return isPublicCleartext(`http://${text}`) ? [`https://${text}`] : [`http://${text}`, `https://${text}`];
}

/** How this device introduces itself in the instance's device list. */
export function deviceInfo(): {name: string; platform: string} {
  const c = (Platform.constants ?? {}) as {Brand?: string; Model?: string; interfaceIdiom?: string};
  switch (Platform.OS) {
    case 'ios':
      return {name: c.interfaceIdiom === 'pad' ? 'iPad' : 'iPhone', platform: 'ios'};
    case 'android': {
      const brand = (c.Brand || '').replace(/^\w/, ch => ch.toUpperCase());
      const model = c.Model || '';
      const name = model.toLowerCase().startsWith(brand.toLowerCase()) ? model : `${brand} ${model}`.trim();
      return {name: name || 'Android', platform: 'android'};
    }
    case 'web':
      return {name: 'Browser', platform: 'web'};
    default: {
      const harmony = (Platform.OS as string) === 'harmony';
      return {name: harmony ? 'HarmonyOS' : 'Phone', platform: harmony ? 'harmony' : 'other'};
    }
  }
}

/** What answers at `baseUrl`, or an ApiError whose `body.reason` says why nothing usable does. */
export async function discover(baseUrl: string, timeoutMs = DISCOVER_TIMEOUT_MS): Promise<Discovery> {
  const client = new HttpClient();
  client.setBaseUrl(baseUrl);
  let info: Discovery;
  try {
    info = await client.request<Discovery>('/.well-known/cowagent', {anonymous: true, timeoutMs});
  } catch (e) {
    if (!(e instanceof ApiError)) {
      throw failure('unreachable', baseUrl);
    }
    if (e.kind === 'network') {
      throw failure('unreachable', baseUrl);
    }
    if (e.kind === 'timeout') {
      throw failure('timeout', baseUrl);
    }
    if (e.kind === 'unauthorized') {
      throw failure('login', baseUrl, e.status);
    }
    if (e.status === 404) {
      // A CowAgent from before pairing answers, just not at the discovery path.
      const old = await client
        .request<{auth_required?: boolean}>('/auth/check', {anonymous: true, timeoutMs})
        .then(r => !!r && 'auth_required' in r)
        .catch(() => false);
      throw failure(old ? 'outdated' : 'not_cowagent', baseUrl, 404);
    }
    throw failure('not_cowagent', baseUrl, e.status);
  }
  if (info?.type !== 'instance') {
    throw failure('not_cowagent', baseUrl, 200);
  }
  return info;
}

/**
 * Redeem the code at the first address that answers. A wrong or spent code is
 * final; an address that can't be reached just moves on to the next one.
 */
export async function redeem(target: PairTarget): Promise<PairResult> {
  let lastError: unknown = new ApiError('network', 'No address to try');
  for (const raw of target.urls) {
    const baseUrl = normalizeBaseUrl(raw);
    let info: Discovery;
    try {
      info = await discover(baseUrl);
    } catch (e) {
      if (rank(e) < rank(lastError)) {
        lastError = e;
      }
      continue;
    }
    const client = new HttpClient();
    client.setBaseUrl(baseUrl);
    const res = await client.request<{token: string; instance?: {id?: string; name?: string}}>('/auth/pair', {
      body: {code: target.code, device: deviceInfo()},
      anonymous: true,
    });
    if (!res.token) {
      throw new ApiError('invalid_response', 'The server returned no token');
    }
    return {
      baseUrl,
      token: res.token,
      name: res.instance?.name || baseUrl.replace(/^https?:\/\//, ''),
      instanceId: res.instance?.id || info.id || '',
    };
  }
  throw lastError;
}

/**
 * Tell a server this device is signing out, so a device token is revoked there.
 * Best effort, and only once the address is confirmed to lead to `instanceId`.
 */
export async function revokeToken(baseUrl: string, token: string, instanceId?: string): Promise<void> {
  if (instanceId) {
    const info = await discover(baseUrl).catch(() => null);
    if (!sameDevice(instanceId, info)) {
      return;
    }
  }
  const client = new HttpClient();
  client.setBaseUrl(baseUrl);
  client.setToken(token);
  await client.request('/auth/logout', {body: {}, timeoutMs: DISCOVER_TIMEOUT_MS}).catch(() => undefined);
}
