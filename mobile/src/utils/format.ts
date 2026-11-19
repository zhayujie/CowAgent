import {tr, trf} from '../i18n';

export const pad = (n: number) => String(n).padStart(2, '0');

export const startOfDay = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();

/** Accepts unix seconds, milliseconds or a date string. */
export function toDate(value: number | string | null | undefined): Date | null {
  if (value === null || value === undefined || value === '') {
    return null;
  }
  if (typeof value === 'number') {
    return new Date(value < 1e12 ? value * 1000 : value);
  }
  const d = new Date(value.replace(' ', 'T'));
  return isNaN(d.getTime()) ? null : d;
}

/** Calendar-day distance from today: 0 today, 1 yesterday, ... */
export function daysAgo(d: Date, now = new Date()): number {
  return Math.round((startOfDay(now) - startOfDay(d)) / 86_400_000);
}

const MONTH_NAMES = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

/** Date parts for the `{year}` `{month}` `{monthName}` `{day}` placeholders of the date keys. */
export const dateVars = (d: Date) => ({
  year: d.getFullYear(),
  month: d.getMonth() + 1,
  monthName: MONTH_NAMES[d.getMonth()],
  day: d.getDate(),
});

export function dayLabel(d: Date, now = new Date()): string {
  const diff = daysAgo(d, now);
  if (diff === 0) {
    return tr('common_today');
  }
  if (diff === 1) {
    return tr('common_yesterday');
  }
  if (diff < 7) {
    return tr('common_this_week');
  }
  if (d.getFullYear() === now.getFullYear()) {
    return trf('common_month_label', dateVars(d));
  }
  return trf('common_year_label', dateVars(d));
}

export function clockTime(value: number | string | null | undefined): string {
  const d = toDate(value);
  return d ? `${pad(d.getHours())}:${pad(d.getMinutes())}` : '';
}

/** Short stamp for list rows: 14:20 / 昨天 / 10/21 / 2025/10/21. */
export function shortTime(value: number | string | null | undefined, now = new Date()): string {
  const d = toDate(value);
  if (!d) {
    return '';
  }
  const diff = daysAgo(d, now);
  if (diff === 0) {
    return `${pad(d.getHours())}:${pad(d.getMinutes())}`;
  }
  if (diff === 1) {
    return tr('common_yesterday');
  }
  if (d.getFullYear() === now.getFullYear()) {
    return `${d.getMonth() + 1}/${d.getDate()}`;
  }
  return `${d.getFullYear()}/${d.getMonth() + 1}/${d.getDate()}`;
}

/** Full stamp for details: 今天 14:20 / 10月21日 09:00 (Today 14:20 / Oct 21 09:00). */
export function fullTime(value: number | string | null | undefined, now = new Date()): string {
  const d = toDate(value);
  if (!d) {
    return '';
  }
  const hm = `${pad(d.getHours())}:${pad(d.getMinutes())}`;
  const diff = daysAgo(d, now);
  if (diff === 0) {
    return trf('common_today_at', {time: hm});
  }
  if (diff === -1) {
    return trf('common_tomorrow_at', {time: hm});
  }
  if (diff === 1) {
    return trf('common_yesterday_at', {time: hm});
  }
  return d.getFullYear() === now.getFullYear()
    ? `${trf('common_month_day', dateVars(d))} ${hm}`
    : trf('common_year_month_day', dateVars(d));
}

export function formatBytes(size: number | undefined): string {
  if (!size || size < 0) {
    return '';
  }
  if (size < 1024) {
    return `${size} B`;
  }
  if (size < 1024 * 1024) {
    return `${Math.round(size / 1024)} KB`;
  }
  return `${(size / 1024 / 1024).toFixed(1)} MB`;
}

const EXT_KIND: Record<string, string> = {
  html: 'html',
  htm: 'html',
  png: 'image',
  jpg: 'image',
  jpeg: 'image',
  gif: 'image',
  webp: 'image',
  svg: 'image',
  mp4: 'video',
  mov: 'video',
  webm: 'video',
  mp3: 'audio',
  m4a: 'audio',
  wav: 'audio',
  md: 'markdown',
  pdf: 'pdf',
  doc: 'office',
  docx: 'office',
  xls: 'office',
  xlsx: 'office',
  ppt: 'office',
  pptx: 'office',
  txt: 'text',
  log: 'text',
  csv: 'csv',
  json: 'code',
  js: 'code',
  ts: 'code',
  tsx: 'code',
  jsx: 'code',
  py: 'code',
  java: 'code',
  go: 'code',
  rs: 'code',
  sh: 'code',
  css: 'code',
  xml: 'code',
  yaml: 'code',
  yml: 'code',
  sql: 'code',
};

export const FILE_EXTENSIONS = Object.keys(EXT_KIND);

/** Artifact-style kind guessed from a file name, for picking an icon. */
export function kindFromName(name: string): string {
  return EXT_KIND[name.split('.').pop()?.toLowerCase() ?? ''] ?? 'file';
}

/** 0:07 style clock for recordings. */
export function formatClock(ms: number): string {
  const s = Math.floor(ms / 1000);
  return `${Math.floor(s / 60)}:${pad(s % 60)}`;
}

export function formatCount(n: number): string {
  return n.toLocaleString('en-US');
}

/** 1M / 200K / 512 for context windows and budgets. */
export function formatTokens(n: number): string {
  if (n >= 1_000_000) {
    return `${Number((n / 1_000_000).toFixed(1))}M`;
  }
  if (n >= 1000) {
    return `${Number((n / 1000).toFixed(n >= 100_000 ? 0 : 1))}K`;
  }
  return String(n);
}

/** Elapsed time for runs and probes: 820ms / 1.8s / 2m 05s. */
export function formatDuration(ms: number): string {
  if (ms < 1000) {
    return `${Math.round(ms)}ms`;
  }
  if (ms < 60_000) {
    return `${(ms / 1000).toFixed(ms < 10_000 ? 1 : 0)}s`;
  }
  const s = Math.round(ms / 1000);
  return `${Math.floor(s / 60)}m ${pad(s % 60)}s`;
}

export function formatSeconds(seconds: number): string {
  return seconds < 10 ? `${seconds.toFixed(1)}s` : `${Math.round(seconds)}s`;
}

export function greeting(now = new Date()): string {
  const h = now.getHours();
  if (h < 5) {
    return tr('common_greeting_night');
  }
  if (h < 11) {
    return tr('common_greeting_morning');
  }
  if (h < 13) {
    return tr('common_greeting_noon');
  }
  if (h < 18) {
    return tr('common_greeting_afternoon');
  }
  return tr('common_greeting_evening');
}
