import {cancelRequest, getHistory, sendMessage} from '../src/api/cowApi';
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
const byRequest: Record<string, ChatStreamHandlers> = {};

beforeEach(() => {
  jest.useFakeTimers();
  jest.clearAllMocks();
  useChatStore.setState({messages: {}, active: {}});
  jest.mocked(subscribeChat).mockImplementation((id, h) => {
    handlers = h;
    byRequest[id] = h;
    return jest.fn();
  });
  jest.mocked(sendMessage).mockResolvedValue({request_id: 'r1'} as never);
});

afterEach(() => jest.useRealTimers());

const reply = (sid = 'a') => useChatStore.getState().messages[sid].filter(m => m.role === 'assistant').pop()!;

const runningSnapshot = {
  messages: [
    {role: 'user', content: 'hi', created_at: 1},
    {role: 'assistant', content: 'part', created_at: 2, run_state: 'running'},
  ],
};

it('keeps streaming into a session the user left and came back to', async () => {
  jest.mocked(getHistory).mockResolvedValue({messages: []} as never);
  await useChatStore.getState().send('a', 'hi');
  handlers.onEvent({type: 'delta', content: 'part', seq: 1} as never);

  await useChatStore.getState().loadHistory('b', null);
  jest.mocked(getHistory).mockResolvedValue(runningSnapshot as never);
  await useChatStore.getState().loadHistory('a', null);

  handlers.onEvent({type: 'delta', content: ' rest', seq: 2} as never);
  handlers.onEvent({type: 'done', content: 'part rest', seq: 3} as never);
  expect(reply()).toMatchObject({content: 'part rest', streaming: false});
});

it('does not let a history fetched mid-reply overwrite the finished reply', async () => {
  await useChatStore.getState().send('a', 'hi');
  handlers.onEvent({type: 'delta', content: 'part', seq: 1} as never);

  let resolve!: (v: unknown) => void;
  jest.mocked(getHistory).mockReturnValue(new Promise(r => (resolve = r)) as never);
  const loading = useChatStore.getState().loadHistory('a', null);
  handlers.onEvent({type: 'done', content: 'part rest', seq: 2} as never);
  resolve(runningSnapshot);
  await loading;

  expect(reply()).toMatchObject({content: 'part rest'});
  expect(reply().runState).toBeUndefined();
});

it('picks a reply still streaming on the server back up from history', async () => {
  jest.mocked(getHistory).mockResolvedValue({
    ...runningSnapshot,
    active_request: {request_id: 'r9', after_seq: 7},
  } as never);
  await useChatStore.getState().loadHistory('a', null);

  expect(subscribeChat).toHaveBeenCalledWith('r9', expect.anything(), 7);
  expect(useChatStore.getState().active.a).toMatchObject({requestId: 'r9'});
  expect(reply()).toMatchObject({streaming: true, runState: undefined});

  handlers.onEvent({type: 'delta', content: 'the rest', seq: 8} as never);
  handlers.onEvent({type: 'done', content: 'the rest', seq: 9} as never);
  expect(useChatStore.getState().active).toEqual({});
  expect(reply()).toMatchObject({content: 'the rest', streaming: false});
});

it('opens a bubble when nothing of the running reply is stored yet', async () => {
  jest.mocked(getHistory).mockResolvedValue({
    messages: [{role: 'user', content: 'hi', created_at: 1}],
    active_request: {request_id: 'r9', after_seq: null},
  } as never);
  await useChatStore.getState().loadHistory('a', null);

  expect(subscribeChat).toHaveBeenCalledWith('r9', expect.anything(), 0);
  expect(useChatStore.getState().messages.a).toHaveLength(2);
  expect(reply()).toMatchObject({streaming: true, content: ''});
});

it('leaves a reply the user stopped alone', async () => {
  await useChatStore.getState().send('a', 'hi');
  await Promise.resolve();
  await useChatStore.getState().cancel('a');
  jest.mocked(subscribeChat).mockClear();

  jest.mocked(getHistory).mockResolvedValue({
    ...runningSnapshot,
    active_request: {request_id: 'r1', after_seq: 3},
  } as never);
  await useChatStore.getState().loadHistory('a', null);

  expect(subscribeChat).not.toHaveBeenCalled();
  expect(useChatStore.getState().active).toEqual({});
});

it('picks a reply back up while another session is replying', async () => {
  await useChatStore.getState().send('a', 'hi');
  jest.mocked(getHistory).mockResolvedValue({
    ...runningSnapshot,
    active_request: {request_id: 'r9', after_seq: 2},
  } as never);
  await useChatStore.getState().loadHistory('b', null);

  expect(subscribeChat).toHaveBeenCalledWith('r9', expect.anything(), 2);
  expect(Object.keys(useChatStore.getState().active).sort()).toEqual(['a', 'b']);
});

it('leaves the page as stored once every slot is taken', async () => {
  jest.mocked(sendMessage).mockResolvedValueOnce({request_id: 'r1'} as never);
  jest.mocked(sendMessage).mockResolvedValueOnce({request_id: 'r2'} as never);
  await useChatStore.getState().send('a', 'hi');
  await useChatStore.getState().send('b', 'hi');
  jest.mocked(subscribeChat).mockClear();
  jest.mocked(getHistory).mockResolvedValue({
    ...runningSnapshot,
    active_request: {request_id: 'r9', after_seq: 2},
  } as never);
  await useChatStore.getState().loadHistory('c', null);

  expect(subscribeChat).not.toHaveBeenCalled();
  expect(reply('c')).toMatchObject({runState: 'running'});
});

describe('replying in two sessions at once', () => {
  beforeEach(async () => {
    jest.mocked(sendMessage).mockResolvedValueOnce({request_id: 'r1'} as never);
    jest.mocked(sendMessage).mockResolvedValueOnce({request_id: 'r2'} as never);
    await useChatStore.getState().send('a', 'one');
    await useChatStore.getState().send('b', 'two');
  });

  it('keeps each stream in its own session', () => {
    byRequest.r1.onEvent({type: 'delta', content: 'alpha', seq: 1} as never);
    byRequest.r2.onEvent({type: 'delta', content: 'beta', seq: 1} as never);
    jest.runOnlyPendingTimers();
    expect(reply('a').content).toBe('alpha');
    expect(reply('b').content).toBe('beta');

    byRequest.r1.onEvent({type: 'done', content: 'alpha!', seq: 2} as never);
    expect(Object.keys(useChatStore.getState().active)).toEqual(['b']);
    byRequest.r2.onEvent({type: 'delta', content: ' more', seq: 2} as never);
    jest.runOnlyPendingTimers();
    expect(reply('a')).toMatchObject({content: 'alpha!', streaming: false});
    expect(reply('b')).toMatchObject({content: 'beta more', streaming: true});
  });

  it('refuses a third one', async () => {
    await useChatStore.getState().send('c', 'three');
    expect(sendMessage).toHaveBeenCalledTimes(2);
    expect(useChatStore.getState().messages.c).toBeUndefined();
  });

  it('stops only the session asked', async () => {
    await useChatStore.getState().cancel('a');
    expect(cancelRequest).toHaveBeenCalledWith('r1', 'a');
    expect(Object.keys(useChatStore.getState().active)).toEqual(['b']);
    expect(reply('a')).toMatchObject({cancelled: true});
    expect(reply('b')).toMatchObject({streaming: true});
    expect(reply('b').cancelled).toBeFalsy();
  });
});
