import {useUnreadStore} from '../src/store/unreadStore';

beforeEach(() => useUnreadStore.setState({unread: {}}));

it('keeps a mark until the conversation is opened', () => {
  const store = useUnreadStore.getState();
  store.mark('s1');
  store.mark('s2');
  expect(Object.keys(useUnreadStore.getState().unread).sort()).toEqual(['s1', 's2']);

  store.clear('s1');
  expect(Object.keys(useUnreadStore.getState().unread)).toEqual(['s2']);
});

it('ignores a repeat mark and a clear that has nothing to clear', () => {
  useUnreadStore.getState().mark('s1');
  const before = useUnreadStore.getState().unread;
  useUnreadStore.getState().mark('s1');
  expect(useUnreadStore.getState().unread).toBe(before);

  const afterMark = useUnreadStore.getState().unread;
  useUnreadStore.getState().clear('nope');
  expect(useUnreadStore.getState().unread).toBe(afterMark);
});
