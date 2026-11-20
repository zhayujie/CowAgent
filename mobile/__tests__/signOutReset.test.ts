import {useAgentStore} from '../src/store/agentStore';
import {useChatStore} from '../src/store/chatStore';
import {useComposerStore} from '../src/store/composerStore';
import {resetServerData} from '../src/store/reset';
import {useSessionStore} from '../src/store/sessionStore';

jest.mock('@react-native-async-storage/async-storage', () =>
  require('@react-native-async-storage/async-storage/jest/async-storage-mock'),
);
jest.mock('react-native-keychain', () => ({}));

it("drops the last server's data and stops its stream", () => {
  const unsubscribe = jest.fn();
  useChatStore.setState({
    currentSessionId: 's1',
    messages: {s1: [{id: 'm1', role: 'user', content: 'hi'}]},
    active: {
      s1: {requestId: 'r1', unsubscribe},
      s2: {requestId: 'r2', unsubscribe},
    },
  });
  useAgentStore.setState({currentId: 'a1', defaultId: 'a1'});
  useSessionStore.setState({sessions: [{session_id: 's1'}] as never});
  useComposerStore.setState({items: [{id: 'f1'}] as never});

  resetServerData();

  expect(unsubscribe).toHaveBeenCalledTimes(2);
  expect(useChatStore.getState()).toMatchObject({currentSessionId: null, messages: {}, active: {}});
  expect(useAgentStore.getState()).toMatchObject({currentId: null, defaultId: null, agents: []});
  expect(useSessionStore.getState().sessions).toEqual([]);
  expect(useComposerStore.getState().items).toEqual([]);
  expect(typeof useChatStore.getState().send).toBe('function');
});
