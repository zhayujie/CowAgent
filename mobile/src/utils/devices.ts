import {tr, trf} from '../i18n';
import type {PairedDevice} from '../protocol/resources';

/** This app's own entry first, then the ones online, then the most recently seen. */
export function sortDevices(devices: PairedDevice[], current: string): PairedDevice[] {
  return [...devices].sort(
    (a, b) =>
      Number(b.id === current) - Number(a.id === current) ||
      Number(!!b.online) - Number(!!a.online) ||
      (b.last_seen_at || b.created_at || 0) - (a.last_seen_at || a.created_at || 0),
  );
}

export function seenLabel(d: PairedDevice, nowMs = Date.now()): string {
  if (d.online) {
    return tr('devices_online');
  }
  const ts = d.last_seen_at || d.created_at;
  if (!ts) {
    return '';
  }
  const mins = Math.floor((nowMs / 1000 - ts) / 60);
  if (mins < 10) {
    return tr('devices_seen_now');
  }
  if (mins < 60) {
    return trf('devices_seen_minutes', {n: mins});
  }
  if (mins < 60 * 24) {
    return trf('devices_seen_hours', {n: Math.floor(mins / 60)});
  }
  return trf('devices_seen_days', {n: Math.floor(mins / 1440)});
}

/** How it signed in, its app version, the page it paired from and its last address. */
export function deviceMeta(d: PairedDevice): string {
  return [
    d.via === 'password' ? tr('devices_via_password') : tr('devices_via_pairing'),
    d.app_version && `v${d.app_version}`,
    d.origin && trf('devices_from_page', {origin: d.origin.replace(/^https?:\/\//i, '')}),
    d.last_ip,
  ]
    .filter(Boolean)
    .join(' · ');
}

/** Seconds left as m:ss. */
export function countdown(leftMs: number): string {
  const left = Math.max(0, Math.round(leftMs / 1000));
  return `${Math.floor(left / 60)}:${String(left % 60).padStart(2, '0')}`;
}
