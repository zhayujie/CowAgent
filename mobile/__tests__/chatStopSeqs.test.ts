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
});

const asked = (text: string) => useChatStore.getState().messages.s1.find(m => m.role === 'user' && m.content === text)!;
const reply = () => useChatStore.getState().messages.s1.find(m => m.role === 'assistant')!;
const settle = async () => {
  for (let i = 0; i < 8; i++) {
    await Promise.resolve();
  }
};

const page = (question: string, seq: number) => ({
  messages: [
    {role: 'user', content: question, created_at: 0, _seq: seq},
    {role: 'assistant', content: '', created_at: 0, _seq: seq + 1},
  ],
  total: 2,
  page: 1,
  page_size: 6,
  has_more: false,
});

/**
 * The stream closes on a stop, before the `done` that reports the seq, so the
 * buttons that address the turn have nothing to point at until the conversation
 * is loaded again.
 */
it('learns the seq of a stopped turn from what was stored', async () => {
  jest.mocked(sendMessage).mockResolvedValue({request_id: 'r1'} as never);
  jest.mocked(getHistory).mockResolvedValue(page('今天天气怎么样', 7) as never);
  await useChatStore.getState().send('s1', '今天天气怎么样');

  await useChatStore.getState().cancel('s1');
  await settle();

  expect(getHistory).toHaveBeenCalledWith('s1', undefined, 1, 6);
  expect(reply().userSeq).toBe(7);
  expect(asked('今天天气怎么样').seq).toBe(7);
});

it('keeps a done that already reported its seq', async () => {
  jest.mocked(sendMessage).mockResolvedValue({request_id: 'r1'} as never);
  await useChatStore.getState().send('s1', 'hi');

  handlers.onEvent({type: 'done', content: 'hello', user_seq: 3, bot_seq: 4} as never);
  await settle();

  expect(getHistory).not.toHaveBeenCalled();
  expect(reply().userSeq).toBe(3);
});

it('reads the seq back when a done carries none', async () => {
  jest.mocked(sendMessage).mockResolvedValue({request_id: 'r1'} as never);
  jest.mocked(getHistory).mockResolvedValue(page('hi', 5) as never);
  await useChatStore.getState().send('s1', 'hi');

  handlers.onEvent({type: 'done', content: '❌ failed'} as never);
  await settle();

  expect(reply().userSeq).toBe(5);
  expect(asked('hi').seq).toBe(5);
});

/** Retry removes the turn it addresses, so a seq of another question is worse than none. */
it('never takes a newer question for the stopped one', async () => {
  jest.mocked(sendMessage).mockResolvedValue({request_id: 'r1'} as never);
  jest.mocked(getHistory).mockResolvedValue(page('另一件事', 9) as never);
  await useChatStore.getState().send('s1', '今天天气怎么样');

  await useChatStore.getState().cancel('s1');
  await settle();

  expect(reply().userSeq).toBeUndefined();
  expect(asked('今天天气怎么样').seq).toBeUndefined();
});
