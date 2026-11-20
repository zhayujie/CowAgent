import {cancelRequest, sendMessage} from '../src/api/cowApi';
import {subscribeChat, type ChatStreamHandlers} from '../src/realtime/chatStream';
import {useChatStore} from '../src/store/chatStore';

jest.mock('@react-native-async-storage/async-storage', () =>
  require('@react-native-async-storage/async-storage/jest/async-storage-mock'),
);
jest.mock('react-native-keychain', () => ({}));
jest.mock('../src/api/cowApi', () => ({
  getHistory: jest.fn(),
  cancelRequest: jest.fn(() => Promise.resolve({status: 'success'})),
  sendMessage: jest.fn(),
  serverFileUrl: jest.fn(),
}));
jest.mock('../src/realtime/chatStream', () => ({subscribeChat: jest.fn()}));

let handlers: ChatStreamHandlers;
const unsubscribe = jest.fn();

beforeEach(() => {
  jest.clearAllMocks();
  useChatStore.setState({messages: {}, active: {}});
  jest.mocked(subscribeChat).mockImplementation((_id, h) => {
    handlers = h;
    return unsubscribe;
  });
});

const reply = () => useChatStore.getState().messages.s1.find(m => m.role === 'assistant')!;

it('stops the reply on screen at once and frees the composer', async () => {
  jest.mocked(sendMessage).mockResolvedValue({request_id: 'r1'} as never);
  await useChatStore.getState().send('s1', 'hi');
  handlers.onEvent({type: 'tool_start', tool: 'read', tool_call_id: 't1'} as never);

  await useChatStore.getState().cancel('s1');

  expect(cancelRequest).toHaveBeenCalledWith('r1', 's1');
  expect(unsubscribe).toHaveBeenCalledTimes(1);
  expect(useChatStore.getState().active).toEqual({});
  expect(reply()).toMatchObject({cancelled: true, streaming: false});
  expect(reply().steps).toEqual([expect.objectContaining({id: 't1', status: 'stopped'})]);
});

it('cancels a request stopped before the server named it', async () => {
  let resolve!: (v: unknown) => void;
  jest.mocked(sendMessage).mockReturnValue(new Promise(r => (resolve = r)) as never);
  const sending = useChatStore.getState().send('s1', 'hi');

  await useChatStore.getState().cancel('s1');
  expect(useChatStore.getState().active).toEqual({});
  expect(cancelRequest).not.toHaveBeenCalled();

  resolve({request_id: 'r2'});
  await sending;
  expect(cancelRequest).toHaveBeenCalledWith('r2', 's1');
  expect(subscribeChat).not.toHaveBeenCalled();
  expect(reply()).toMatchObject({cancelled: true});
});
