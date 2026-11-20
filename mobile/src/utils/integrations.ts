import type {IntegrationsState} from '../protocol/resources';

export const isLoopback = (host: string) => host === 'localhost' || host === '::1' || host.startsWith('127.');

export function hostOf(url: string): string {
  const m = /^[a-z]+:\/\/(\[[^\]]+\]|[^/:?#]+)/i.exec(url);
  return m ? m[1].replace(/^\[|\]$/g, '') : '';
}

/**
 * The address callers elsewhere should use in API examples and share links, as the web console
 * picks it: the configured public URL, else the address this app connects with, unless that is
 * loopback and only works on this device, in which case a LAN address.
 */
export function integrationBase(access: Pick<IntegrationsState, 'public_url' | 'lan_urls'> | null, connected: string): string {
  const base = access?.public_url || (isLoopback(hostOf(connected)) && access?.lan_urls[0]) || connected;
  return base.replace(/\/+$/, '');
}
