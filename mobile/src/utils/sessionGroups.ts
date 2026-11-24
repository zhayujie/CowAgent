import {tr} from '../i18n';
import type {SessionItem} from '../protocol/events';
import {daysAgo, toDate} from './format';

type Bucket = 'today' | 'yesterday' | 'week' | 'earlier';

/** The order key the server uses for the Agent's own workspace. */
export const DEFAULT_SPACE = '__default__';

/** Where a chat works: a project folder, or the default workspace when the path is null. */
export interface Space {
  path: string | null;
  name: string;
}

export interface SessionGroup {
  /** A time bucket, `pinned`, or in project mode the space's path or DEFAULT_SPACE. */
  key: string;
  title: string;
  data: SessionItem[];
  /** Set in project mode only. */
  space?: Space;
}

const ORDER: Bucket[] = ['today', 'yesterday', 'week', 'earlier'];

const bucketTitle = (bucket: Bucket) =>
  ({
    today: tr('common_today'),
    yesterday: tr('common_yesterday'),
    week: tr('session_group_last7'),
    earlier: tr('session_group_earlier'),
  })[bucket];

/** `project` mode groups by the folder each chat works in, in the user's saved order. */
export function groupSessions(
  sessions: SessionItem[],
  mode: 'project' | 'time' = 'time',
  order: string[] = [],
): SessionGroup[] {
  return mode === 'project' ? bySpace(sessions, order) : byTime(sessions);
}

function byTime(sessions: SessionItem[]): SessionGroup[] {
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

function bySpace(sessions: SessionItem[], order: string[]): SessionGroup[] {
  const groups = new Map<string, SessionGroup & {born: number}>();
  for (const s of sessions) {
    const key = s.project?.path ?? DEFAULT_SPACE;
    let group = groups.get(key);
    if (!group) {
      const space: Space = s.project
        ? {path: s.project.path, name: s.project.name}
        : {path: null, name: tr('composer_ws_default')};
      group = {key, title: space.name, data: [], space, born: Infinity};
      groups.set(key, group);
    }
    group.data.push(s);
    // A space keeps its place as chats in it move: unranked ones follow the order they began in.
    const created = toDate(s.created_at || s.last_active)?.getTime();
    if (created !== undefined && created < group.born) {
      group.born = created;
    }
  }
  const rank = (key: string) => {
    const i = order.indexOf(key);
    return i < 0 ? Infinity : i;
  };
  return [...groups.values()]
    .sort((a, b) => (rank(a.key) !== rank(b.key) ? rank(a.key) - rank(b.key) : a.born - b.born))
    .map(({born: _born, ...group}) => ({
      ...group,
      data: [...group.data.filter(s => s.pinned), ...group.data.filter(s => !s.pinned)],
    }));
}
