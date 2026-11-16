import type {SessionItem} from '../protocol/events';
import {daysAgo, toDate} from './format';

export interface SessionGroup {
  title: string;
  data: SessionItem[];
}

const ORDER = ['今天', '昨天', '近七天', '更早'];

export function groupSessions(sessions: SessionItem[]): SessionGroup[] {
  const pinned: SessionItem[] = [];
  const buckets: Record<string, SessionItem[]> = {};
  for (const s of sessions) {
    if (s.pinned) {
      pinned.push(s);
      continue;
    }
    const d = toDate(s.last_active);
    const diff = d ? daysAgo(d) : 99;
    const key = diff <= 0 ? '今天' : diff === 1 ? '昨天' : diff < 7 ? '近七天' : '更早';
    (buckets[key] ??= []).push(s);
  }
  const groups: SessionGroup[] = [];
  if (pinned.length) {
    groups.push({title: '置顶', data: pinned});
  }
  for (const key of ORDER) {
    if (buckets[key]?.length) {
      groups.push({title: key, data: buckets[key]});
    }
  }
  return groups;
}
