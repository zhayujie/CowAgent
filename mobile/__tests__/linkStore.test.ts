import {AppState} from 'react-native';
import {http} from '../src/api/http';
import {LOCAL_SERVER_ID} from '../src/kernel/localKernel';
import {checkLinkNow, useLinkStore} from '../src/store/linkStore';
import {useServerStore, type ServerProfile} from '../src/store/serverStore';

jest.mock('@react-native-async-storage/async-storage', () =>
  require('@react-native-async-storage/async-storage/jest/async-storage-mock'),
);
jest.mock('react-native-keychain', () => ({}));

const home: ServerProfile = {id: 'https://home.example', name: 'Home', baseUrl: 'https://home.example', wsUrl: null};
const local: ServerProfile = {id: LOCAL_SERVER_ID, name: '', baseUrl: 'http://127.0.0.1:9900', wsUrl: null, local: true};

const fetchMock = jest.fn();
let reachable = true;

beforeAll(() => {
  Object.defineProperty(AppState, 'currentState', {value: 'active', configurable: true});
  globalThis.fetch = fetchMock;
});

beforeEach(async () => {
  jest.useFakeTimers();
  reachable = true;
  fetchMock.mockReset();
  fetchMock.mockImplementation(async () => {
    if (!reachable) {
      throw new TypeError('Network request failed');
    }
    return {ok: true, status: 200} as Response;
  });
  useServerStore.setState({servers: [home, local], activeId: home.id, authed: true});
  await flush();
});

afterEach(() => {
  useServerStore.setState({authed: false});
  jest.useRealTimers();
});

async function flush() {
  for (let i = 0; i < 5; i++) {
    await Promise.resolve();
  }
}

async function advance(ms: number) {
  jest.advanceTimersByTime(ms);
  await flush();
}

it('calls the device unreachable only after a second failed check', async () => {
  reachable = false;
  http.onReach?.(home.baseUrl, false);
  expect(useLinkStore.getState().down).toBe(false);
  await advance(2000);
  expect(useLinkStore.getState().down).toBe(true);
});

it('clears once the device answers, so screens reload', async () => {
  reachable = false;
  http.onReach?.(home.baseUrl, false);
  await advance(2000);
  const before = useLinkStore.getState().recovered;
  reachable = true;
  await checkLinkNow();
  expect(useLinkStore.getState()).toMatchObject({down: false, checking: false, recovered: before + 1});
});

it('ignores answers from other addresses and never watches this phone', async () => {
  http.onReach?.('https://other.example', false);
  http.onReach?.('https://other.example', false);
  expect(useLinkStore.getState().down).toBe(false);

  useServerStore.setState({activeId: LOCAL_SERVER_ID});
  await flush();
  fetchMock.mockClear();
  http.onReach?.(local.baseUrl, false);
  await advance(60_000);
  expect(fetchMock).not.toHaveBeenCalled();
  expect(useLinkStore.getState().down).toBe(false);
});
