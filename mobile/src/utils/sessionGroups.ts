import {tr} from '../i18n';
import type {SessionItem} from '../protocol/events';
import {daysAgo, toDate} from './format';

type Bucket = 'today' | 'yesterday' | 'week' | 'earlier';

export interface SessionGroup {
  key: Bucket | 'pinned';
  title: string;
  data: SessionItem[];
}

const ORDER: Bucket[] = ['today', 'yesterday', 'week', 'earlier'];

const bucketTitle = (bucket: Bucket) =>
  ({
    today: tr('common_today'),
    yesterday: tr('common_yesterday'),
    week: tr('session_group_last7'),
    earlier: tr('session_group_earlier'),
  })[bucket];

export function groupSessions(sessions: SessionItem[]): SessionGroup[] {
  const pinned: SessionItem[] = [];
  const buckets: Partial<Record<Bucket, SessionItem[]>> = {};
  for (const s of sessions) {
    if (s.pinned) {
      pinned.push(s);
      continue;
    }
    const d = toDate(s.last_active);
    const diff = d ? daysAgo(d) : 99;
    const key: Bucket = diff <= 0 ? 'today' : diff === 1 ? 'yesterday' : diff < 7 ? 'week' : 'earlier';
    (buckets[key] ??= []).push(s);
  }
  const groups: SessionGroup[] = [];
  if (pinned.length) {
    groups.push({key: 'pinned', title: tr('session_group_pinned'), data: pinned});
  }
  for (const key of ORDER) {
    const data = buckets[key];
    if (data?.length) {
      groups.push({key, title: bucketTitle(key), data});
    }
  }
  return groups;
}
