import {deleteMessages, sendMessage} from '../src/api/cowApi';
import {subscribeChat} from '../src/realtime/chatStream';
import {useChatStore, type ChatMessage} from '../src/store/chatStore';

jest.mock('@react-native-async-storage/async-storage', () =>
  require('@react-native-async-storage/async-storage/jest/async-storage-mock'),
);
jest.mock('react-native-keychain', () => ({}));
jest.mock('../src/api/cowApi', () => ({
  getHistory: jest.fn(),
  cancelRequest: jest.fn(),
  deleteMessages: jest.fn(() => Promise.resolve({status: 'success'})),
  sendMessage: jest.fn(() => Promise.resolve({request_id: 'r1'})),
  serverFileUrl: jest.fn(),
}));
jest.mock('../src/realtime/chatStream', () => ({subscribeChat: jest.fn(() => jest.fn())}));

const photo = {name: 'a.png', path: '/tmp/a.png', kind: 'image' as const};
const history: ChatMessage[] = [
  {id: 'u1', role: 'user', content: 'first', seq: 1, attachments: [photo]},
  {id: 'a1', role: 'assistant', content: 'one', userSeq: 1},
  {id: 'u2', role: 'user', content: 'second', seq: 3},
  {id: 'a2', role: 'assistant', content: 'two', userSeq: 3},
];

beforeEach(() => {
  jest.clearAllMocks();
  useChatStore.setState({messages: {s1: history}, active: {}});
});

const contents = () => useChatStore.getState().messages.s1.map(m => m.content);

it('retries a reply by dropping its turn and every later one, then asking again', async () => {
  await expect(useChatStore.getState().retry('s1', 'a1')).resolves.toBe('ok');

  expect(deleteMessages).toHaveBeenCalledWith('s1', 1, {deleteUser: true, cascade: true}, undefined);
  expect(sendMessage).toHaveBeenCalledTimes(1);
  expect(contents()).toEqual(['first', '']);
  expect(useChatStore.getState().messages.s1[0].attachments).toEqual([photo]);
});

it('deletes nothing while the reply limit is reached elsewhere', async () => {
  useChatStore.setState({active: {s2: {} as never, s3: {} as never}});

  await expect(useChatStore.getState().retry('s1', 'a2')).resolves.toBe('busy');

  expect(deleteMessages).not.toHaveBeenCalled();
  expect(contents()).toEqual(['first', 'one', 'second', 'two']);
});

it('hands an edited question back with its files', async () => {
  const res = await useChatStore.getState().editMessage('s1', 'u1');

  expect(res).toEqual({result: 'ok', text: 'first', attachments: [photo]});
  expect(deleteMessages).toHaveBeenCalledWith('s1', 1, {deleteUser: true, cascade: true}, undefined);
  expect(useChatStore.getState().messages.s1).toEqual([]);
  expect(subscribeChat).not.toHaveBeenCalled();
});
