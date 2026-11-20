import {getHistory} from '../src/api/cowApi';
import type {HistoryMessage} from '../src/protocol/events';
import {useChatStore} from '../src/store/chatStore';

jest.mock('@react-native-async-storage/async-storage', () =>
  require('@react-native-async-storage/async-storage/jest/async-storage-mock'),
);
jest.mock('react-native-keychain', () => ({}));
jest.mock('../src/api/cowApi', () => ({
  getHistory: jest.fn(),
  cancelRequest: jest.fn(),
  sendMessage: jest.fn(),
  serverFileUrl: jest.fn(),
}));

async function replay(messages: HistoryMessage[]) {
  jest.mocked(getHistory).mockResolvedValue({messages, total: messages.length, page: 1, page_size: 50, has_more: false});
  useChatStore.setState({messages: {}, active: {}});
  await useChatStore.getState().loadHistory('s1');
  return useChatStore.getState().messages.s1;
}

it('marks a failed reply as interrupted instead of an empty bubble', async () => {
  const [user, reply] = await replay([
    {role: 'user', content: 'hi', created_at: 1, _seq: 0},
    {role: 'assistant', content: '', created_at: 1, run_state: 'interrupted'},
  ]);
  expect(user).toMatchObject({role: 'user', content: 'hi'});
  expect(reply).toMatchObject({role: 'assistant', content: '', runState: 'interrupted'});
});

it('keeps a reply cut off before storing anything under its own message', async () => {
  const at = 1_790_000_000;
  const list = await replay([
    {role: 'user', content: 'first', created_at: at, _seq: 10},
    {role: 'assistant', content: '', created_at: at, run_state: 'interrupted'},
    {role: 'user', content: 'second', created_at: at + 60, _seq: 11},
    {role: 'assistant', content: 'answer', created_at: at + 61, _seq: 12},
  ]);
  expect(list.map(m => m.content || m.runState)).toEqual(['first', 'interrupted', 'second', 'answer']);
});

it('keeps what an interrupted reply wrote as steps, not as its answer', async () => {
  const [reply] = await replay([
    {
      role: 'assistant',
      content: 'half an answer',
      created_at: 1,
      run_state: 'interrupted',
      steps: [
        {type: 'content', content: 'Let me check.'},
        {type: 'tool', id: 't1', name: 'read', arguments: {}, result: 'ok'},
        {type: 'content', content: 'half an answer'},
      ],
    } as HistoryMessage,
  ]);
  expect(reply.content).toBe('');
  expect(reply.steps?.map(s => s.kind)).toEqual(['text', 'tool', 'text']);
});

it('leaves finished replies without a run state', async () => {
  const [reply] = await replay([{role: 'assistant', content: 'done', created_at: 1}]);
  expect(reply).toMatchObject({content: 'done'});
  expect(reply.runState).toBeUndefined();
});
