import {saveMenu} from '../src/api/cowApi';
import type {MenuDoc} from '../src/protocol/resources';
import {menuMerge, newMenuItemId, useMenuStore} from '../src/store/menuStore';

jest.mock('@react-native-async-storage/async-storage', () =>
  require('@react-native-async-storage/async-storage/jest/async-storage-mock'),
);
jest.mock('react-native-keychain', () => ({}));
jest.mock('../src/api/cowApi', () => ({getMenu: jest.fn(), saveMenu: jest.fn()}));

const doc: MenuDoc = {
  groups: [
    {
      id: 'manage',
      title: '',
      items: [
        {id: 'config', type: 'builtin', view: 'config', title: '', icon: ''},
        {id: 'm1', type: 'artifact', title: '运动爽', icon: 'layers', path: '/ws/fitness/index.html'},
        {id: 'u1', type: 'url', title: '看板', icon: '', url: 'https://example.com'},
      ],
    },
  ],
};

beforeEach(() => {
  jest.mocked(saveMenu).mockReset();
  jest.mocked(saveMenu).mockImplementation(async menu => ({menu}));
  useMenuStore.setState({doc, customised: true});
});

const items = () => useMenuStore.getState().doc.groups[0].items;
const saved = () => jest.mocked(saveMenu).mock.calls[0][0]!.groups[0].items;

it('renames a pinned file and saves the menu', async () => {
  await useMenuStore.getState().renameItem('m1', '健身计划');
  expect(saved().find(i => i.id === 'm1')).toMatchObject({title: '健身计划', path: '/ws/fitness/index.html'});
  expect(items().find(i => i.id === 'm1')?.title).toBe('健身计划');
});

it('removes a custom entry but never a built-in page', async () => {
  await useMenuStore.getState().removeItem('u1');
  expect(saved().map(i => i.id)).toEqual(['config', 'm1']);

  const before = items().map(i => i.id);
  jest.mocked(saveMenu).mockClear();
  await useMenuStore.getState().removeItem('config');
  expect(saved().map(i => i.id)).toEqual(before);
  expect(before).toContain('config');
});

it('appends a new link to the chosen group', async () => {
  const id = newMenuItemId();
  expect(id).toMatch(/^m_[a-z0-9]{1,8}$/);
  await useMenuStore.getState().addItem('manage', {id, type: 'url', title: '文档', icon: '', url: 'https://docs.example.com', open: 'tab'});
  expect(saved().map(i => i.id)).toEqual(['config', 'm1', 'u1', id]);
  expect(saved()[3]).toMatchObject({type: 'url', url: 'https://docs.example.com', open: 'tab'});
});

it('puts the menu back when the server refuses the save', async () => {
  jest.mocked(saveMenu).mockRejectedValue(new Error('nope'));
  await expect(useMenuStore.getState().removeItem('m1')).rejects.toThrow('nope');
  expect(items().map(i => i.id)).toEqual(['config', 'm1', 'u1']);
});

it('adds, renames and deletes a group, but keeps one holding a built-in page', async () => {
  useMenuStore.setState({doc: menuMerge(null)});
  await useMenuStore.getState().addGroup('  常用  ');
  const added = jest.mocked(saveMenu).mock.calls[0][0]!.groups.at(-1)!;
  expect(added).toMatchObject({title: '常用', items: []});
  expect(added.id).toMatch(/^g_[a-z0-9]{1,8}$/);

  await useMenuStore.getState().renameGroup('manage', '设置');
  expect(useMenuStore.getState().doc.groups.find(g => g.id === 'manage')?.title).toBe('设置');

  await useMenuStore.getState().removeGroup(added.id);
  await useMenuStore.getState().removeGroup('manage');
  expect(useMenuStore.getState().doc.groups.map(g => g.id)).toEqual(['chat', 'manage', 'monitor']);
});
