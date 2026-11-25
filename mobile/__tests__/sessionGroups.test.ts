import {tr} from '../src/i18n';
import type {SessionItem} from '../src/protocol/events';
import {DEFAULT_SPACE, groupSessions} from '../src/utils/sessionGroups';

jest.mock('@react-native-async-storage/async-storage', () =>
  require('@react-native-async-storage/async-storage/jest/async-storage-mock'),
);

const session = (id: string, created: number, project?: string, pinned = false): SessionItem => ({
  session_id: id,
  title: id,
  created_at: created,
  last_active: created,
  msg_count: 1,
  pinned,
  project: project ? {path: `/p/${project}`, name: project} : null,
});

const keys = (groups: ReturnType<typeof groupSessions>) => groups.map(g => g.key);

it('groups by the folder each chat works in', () => {
  const groups = groupSessions([session('a', 3, 'app'), session('b', 2), session('c', 1, 'app')], 'project');

  expect(keys(groups)).toEqual(['/p/app', DEFAULT_SPACE]);
  expect(groups[0].data.map(s => s.session_id)).toEqual(['a', 'c']);
  expect(groups[0].space).toEqual({path: '/p/app', name: 'app'});
  expect(groups[1].title).toBe(tr('composer_ws_default'));
  expect(groups[1].space?.path).toBeNull();
});

it('keeps spaces put as their chats move, oldest first after the saved order', () => {
  // `docs` holds the newest chat, but began after `app`.
  const sessions = [session('new', 9, 'docs'), session('old', 5, 'app'), session('older', 4, 'docs'), session('d', 1)];

  expect(keys(groupSessions(sessions, 'project'))).toEqual([DEFAULT_SPACE, '/p/docs', '/p/app']);
  expect(keys(groupSessions(sessions, 'project', ['/p/app']))).toEqual(['/p/app', DEFAULT_SPACE, '/p/docs']);
});

it('floats pinned chats to the top of their space', () => {
  const groups = groupSessions([session('a', 3, 'app'), session('b', 2, 'app', true)], 'project');

  expect(groups[0].data.map(s => s.session_id)).toEqual(['b', 'a']);
});

it('ignores projects in time mode', () => {
  const groups = groupSessions([session('a', 3, 'app', true), session('b', 2)]);

  expect(groups[0].key).toBe('pinned');
  expect(groups.every(g => !g.space)).toBe(true);
});
