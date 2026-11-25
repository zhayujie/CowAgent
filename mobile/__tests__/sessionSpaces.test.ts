import {setProjectOrder} from '../src/api/cowApi';
import {resetServerData} from '../src/store/reset';
import {useSessionStore} from '../src/store/sessionStore';

jest.mock('@react-native-async-storage/async-storage', () =>
  require('@react-native-async-storage/async-storage/jest/async-storage-mock'),
);
jest.mock('react-native-keychain', () => ({}));
jest.mock('../src/api/cowApi', () => ({
  setProjectOrder: jest.fn(),
}));

beforeEach(() => {
  jest.resetAllMocks();
  resetServerData();
});

it('keeps the places of spaces the list does not show', async () => {
  jest.mocked(setProjectOrder).mockResolvedValue({order: []});
  useSessionStore.setState({projectOrder: ['/p/a', '/p/hidden', '__default__']});

  await useSessionStore.getState().moveSpace('__default__', -1, ['/p/a', '__default__']);

  const order = ['__default__', '/p/a', '/p/hidden'];
  expect(setProjectOrder).toHaveBeenCalledWith(order);
  expect(useSessionStore.getState().projectOrder).toEqual(order);
});

it('puts the order back when the server refuses it', async () => {
  jest.mocked(setProjectOrder).mockRejectedValue(new Error('offline'));
  useSessionStore.setState({projectOrder: ['/p/a', '/p/b']});

  await expect(useSessionStore.getState().moveSpace('/p/b', -1, ['/p/a', '/p/b'])).rejects.toThrow('offline');

  expect(useSessionStore.getState().projectOrder).toEqual(['/p/a', '/p/b']);
});
