import AsyncStorage from '@react-native-async-storage/async-storage';

let onAppState: (state: string) => void = () => undefined;

/** A reload is an app restart: what the app stored stays. */
function load(): typeof import('../src/store/chatResume') {
  jest.resetModules();
  jest.doMock('@react-native-async-storage/async-storage', () => AsyncStorage);
  const RN = require('react-native');
  RN.AppState.addEventListener = jest.fn((_type: string, listener: (state: string) => void) => {
    onAppState = listener;
    return {remove: () => undefined};
  });
  return require('../src/store/chatResume');
}

const chat = {serverId: 'local', sessionId: 's1', isNew: false, draft: 'half a thought'};

async function leaveWith(open: typeof chat) {
  load().trackOpenChat(open);
  onAppState('background');
  await new Promise(resolve => setTimeout(resolve, 0));
}

beforeEach(async () => {
  await AsyncStorage.clear();
  jest.useRealTimers();
});

it('reopens the chat left open, draft and all, when back soon after', async () => {
  await leaveWith(chat);
  const resume = load();
  await resume.loadChatResume();
  expect(resume.chatToResume('local')).toMatchObject(chat);
  expect(resume.chatToResume('other')).toBeNull();
});

it('starts a new chat when back after a long while', async () => {
  await leaveWith(chat);
  const later = Date.now() + 31 * 60 * 1000;
  jest.spyOn(Date, 'now').mockReturnValue(later);
  const resume = load();
  await resume.loadChatResume();
  expect(resume.chatToResume('local')).toBeNull();
  jest.restoreAllMocks();
});

it('offers the chat only until a chat screen has opened', async () => {
  await leaveWith(chat);
  const resume = load();
  await resume.loadChatResume();
  resume.trackOpenChat({...chat, sessionId: 's2', draft: ''});
  expect(resume.chatToResume('local')).toBeNull();
});
