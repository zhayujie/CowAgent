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
}

/** Answer of `GET /.well-known/cowagent`. */
export interface Discovery {
  type: string;
  protocol: number;
  version?: string;
  auth?: {required: boolean; methods: string[]};
}

export const DEVICE_TOKEN_PREFIX = 'cowd.';
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

export async function discover(baseUrl: string): Promise<Discovery> {
  const client = new HttpClient();
  client.setBaseUrl(baseUrl);
  const info = await client.request<Discovery>('/.well-known/cowagent', {
    anonymous: true,
    timeoutMs: DISCOVER_TIMEOUT_MS,
  });
  if (info?.type !== 'instance') {
    throw new ApiError('invalid_response', 'Not a CowAgent server');
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
    try {
      await discover(baseUrl);
    } catch (e) {
      // A server from before pairing answers, just not at the discovery path.
      const tooOld = e instanceof ApiError && e.status === 404;
      lastError = tooOld ? new ApiError('server', 'Pairing unsupported', 404, {reason: 'pairing_unsupported'}) : e;
      continue;
    }
    const client = new HttpClient();
    client.setBaseUrl(baseUrl);
    const res = await client.request<{token: string; instance?: {name?: string}}>('/auth/pair', {
      body: {code: target.code, device: deviceInfo()},
      anonymous: true,
    });
    if (!res.token) {
      throw new ApiError('invalid_response', 'The server returned no token');
    }
    return {baseUrl, token: res.token, name: res.instance?.name || baseUrl.replace(/^https?:\/\//, '')};
  }
  throw lastError;
}

/** Tell a server this device is signing out, so a device token is revoked there. Best effort. */
export async function revokeToken(baseUrl: string, token: string): Promise<void> {
  const client = new HttpClient();
  client.setBaseUrl(baseUrl);
  client.setToken(token);
  await client.request('/auth/logout', {body: {}, timeoutMs: DISCOVER_TIMEOUT_MS}).catch(() => undefined);
}
