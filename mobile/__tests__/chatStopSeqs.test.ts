import {getHistory, sendMessage} from '../src/api/cowApi';
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
  jest.mocked(sendMessage).mockResolvedValue({request_id: 'r1'} as never);
});

const asked = (text: string) => useChatStore.getState().messages.s1.find(m => m.role === 'user' && m.content === text)!;
const reply = () => useChatStore.getState().messages.s1.find(m => m.role === 'assistant')!;

/**
 * The stream closes on a stop, before the `done` that reports the seq; the seq
 * announced when the question was stored is what keeps retry and edit.
 */
it('keeps the seq of a stopped turn', async () => {
  await useChatStore.getState().send('s1', '今天天气怎么样');
  handlers.onEvent({type: 'user_stored', user_seq: 7} as never);

  await useChatStore.getState().cancel('s1');

  expect(reply().userSeq).toBe(7);
  expect(asked('今天天气怎么样').seq).toBe(7);
  expect(getHistory).not.toHaveBeenCalled();
});

it('keeps the seq of a turn whose stream failed', async () => {
  await useChatStore.getState().send('s1', 'hi');
  handlers.onEvent({type: 'user_stored', user_seq: 5} as never);

  handlers.onEnd({kind: 'failed', error: 'Stream closed'});

  expect(reply().userSeq).toBe(5);
  expect(asked('hi').seq).toBe(5);
});

it('keeps a done that reports its seq', async () => {
  await useChatStore.getState().send('s1', 'hi');

  handlers.onEvent({type: 'done', content: 'hello', user_seq: 3, bot_seq: 4} as never);

  expect(reply().userSeq).toBe(3);
  expect(asked('hi').seq).toBe(3);
});

it('a done without a seq leaves the announced one', async () => {
  await useChatStore.getState().send('s1', 'hi');
  handlers.onEvent({type: 'user_stored', user_seq: 5} as never);

  handlers.onEvent({type: 'done', content: '❌ failed'} as never);

  expect(reply().userSeq).toBe(5);
});
