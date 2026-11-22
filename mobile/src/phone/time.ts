/** Wall-clock times on this phone, the way the calendar tool writes them: YYYY-MM-DD[THH:MM[:SS]]. */

const LOCAL_TIME = /^(\d{4})-(\d{2})-(\d{2})(?:T(\d{2}):(\d{2})(?::(\d{2}))?)?$/;

export const DAY_MS = 24 * 60 * 60 * 1000;

/** Milliseconds for a local time, and whether it named a whole day; null when it is no such time. */
export function parseLocal(text: string): {ms: number; dateOnly: boolean} | null {
  const m = LOCAL_TIME.exec(text.trim());
  if (!m) {
    return null;
  }
  const [y, mo, d, h, mi, s] = m.slice(1).map(v => (v === undefined ? 0 : Number(v)));
  const date = new Date(y, mo - 1, d, h, mi, s);
  // new Date rolls 2026-02-30 over into March rather than refusing it.
  if (date.getFullYear() !== y || date.getMonth() !== mo - 1 || date.getDate() !== d || h > 23 || mi > 59 || s > 59) {
    return null;
  }
  return {ms: date.getTime(), dateOnly: m[4] === undefined};
}

/** The next local midnight after the day `ms` falls on, which a day's span ends at. */
export function nextDay(ms: number): number {
  const d = new Date(ms);
  return new Date(d.getFullYear(), d.getMonth(), d.getDate() + 1).getTime();
}

const pad = (n: number) => String(n).padStart(2, '0');

export function formatLocal(ms: number, dateOnly = false): string {
  const d = new Date(ms);
  const date = `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
  return dateOnly ? date : `${date}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/** "2026-11-25 15:00 – 16:00", or a day or a run of days, as the user is asked to allow it. */
export function describeSpan(start: number, end: number, allDay: boolean): string {
  if (allDay) {
    const first = formatLocal(start, true);
    const last = formatLocal(end - 1, true);
    return first === last ? first : `${first} – ${last}`;
  }
  const [startDate, startTime] = formatLocal(start).split('T');
  const [endDate, endTime] = formatLocal(end).split('T');
  return `${startDate} ${startTime} – ${endDate === startDate ? endTime : `${endDate} ${endTime}`}`;
}
