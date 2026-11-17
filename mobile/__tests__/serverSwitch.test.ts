import AsyncStorage from '@react-native-async-storage/async-storage';
import {updateConfig} from '../src/api/cowApi';
import {http} from '../src/api/http';
import {useLangStore} from '../src/i18n';
import {startLocalKernel} from '../src/kernel/localKernel';
import {secureStore} from '../src/storage/secureStore';
import {useChatStore} from '../src/store/chatStore';
import {useServerStore, type ServerProfile} from '../src/store/serverStore';

jest.mock('@react-native-async-storage/async-storage', () =>
  require('@react-native-async-storage/async-storage/jest/async-storage-mock'),
);
jest.mock('react-native-keychain', () => ({}));

jest.mock('../src/kernel/localKernel', () => ({
  ...jest.requireActual('../src/kernel/localKernel'),
  startLocalKernel: jest.fn(),
}));

jest.mock('../src/api/cowApi', () => ({
  ...jest.requireActual('../src/api/cowApi'),
  probeServer: jest.fn(async () => ({auth_required: true, name: 'CowAgent'})),
  login: jest.fn(async () => 'local-token'),
  updateConfig: jest.fn(async () => ({applied: {}})),
}));

const home: ServerProfile = {id: 'https://home.example', name: 'CowAgent', baseUrl: 'https://home.example', wsUrl: null};
const office: ServerProfile = {
  id: 'https://office.example',
  name: 'CowAgent',
  baseUrl: 'https://office.example',
  wsUrl: null,
};

beforeEach(async () => {
  jest.mocked(startLocalKernel).mockReset();
  await secureStore.set(`token:${home.id}`, 'home-token');
  await secureStore.remove(`token:${office.id}`);
  http.setBaseUrl(home.baseUrl);
  http.setToken('home-token');
  useServerStore.setState({servers: [home, office], activeId: home.id, authed: true, returnTo: null});
});

it('switches to a saved server with its stored token and drops the old data', async () => {
  await secureStore.set(`token:${office.id}`, 'office-token');
  useChatStore.setState({currentSessionId: 's1'});

  await useServerStore.getState().switchTo(office.id);

  expect(useServerStore.getState()).toMatchObject({activeId: office.id, authed: true});
  expect(http.getBaseUrl()).toBe(office.baseUrl);
  expect(http.getToken()).toBe('office-token');
  expect(useChatStore.getState().currentSessionId).toBeNull();
  expect(await secureStore.get(`token:${home.id}`)).toBe('home-token');
});

it('lands on the login screen for a saved server without a token', async () => {
  await useServerStore.getState().switchTo(office.id);

  expect(useServerStore.getState()).toMatchObject({activeId: office.id, authed: false});
  expect(http.getToken()).toBeNull();
});

it('stays on the current server when the built-in agent fails to start', async () => {
  jest.mocked(startLocalKernel).mockRejectedValue(new Error('boom'));

  await expect(useServerStore.getState().switchTo('local')).rejects.toThrow('boom');

  expect(useServerStore.getState()).toMatchObject({activeId: home.id, authed: true});
  expect(http.getToken()).toBe('home-token');
});

it('signs in to the built-in agent and gives it the app language', async () => {
  jest.mocked(startLocalKernel).mockResolvedValue({baseUrl: 'http://127.0.0.1:4000', password: 'pw'});
  useLangStore.getState().setLang('zh');

  await useServerStore.getState().switchTo('local');

  const {servers, activeId, authed} = useServerStore.getState();
  expect({activeId, authed}).toEqual({activeId: 'local', authed: true});
  expect(servers.find(s => s.id === 'local')).toMatchObject({local: true, baseUrl: 'http://127.0.0.1:4000'});
  expect(http.getToken()).toBe('local-token');
  expect(updateConfig).toHaveBeenCalledWith({cow_lang: 'zh'});
});

it('signs in to the built-in agent afresh on launch instead of reusing an old token', async () => {
  const local: ServerProfile = {id: 'local', name: 'Phone', baseUrl: 'http://127.0.0.1:3000', wsUrl: null, local: true};
  await AsyncStorage.setItem('cow:servers', JSON.stringify({servers: [local, home], activeId: 'local'}));
  await secureStore.set('token:local', 'stale-token');
  jest.mocked(startLocalKernel).mockResolvedValue({baseUrl: 'http://127.0.0.1:4000', password: 'pw'});
  useServerStore.setState({hydrated: false, servers: [], activeId: null, authed: false});

  await useServerStore.getState().hydrate();

  const {hydrated, activeId, authed, servers} = useServerStore.getState();
  expect({hydrated, activeId, authed}).toEqual({hydrated: true, activeId: 'local', authed: true});
  expect(servers.find(s => s.id === 'local')).toMatchObject({name: 'Phone', baseUrl: 'http://127.0.0.1:4000'});
  expect(http.getToken()).toBe('local-token');
  expect(await secureStore.get('token:local')).toBe('local-token');
});

it('goes back to the server left for the login screen without a password', async () => {
  useServerStore.getState().addServer();
  expect(useServerStore.getState()).toMatchObject({authed: false, activeId: null, returnTo: home.id});

  await useServerStore.getState().switchTo(home.id);

  expect(useServerStore.getState()).toMatchObject({activeId: home.id, authed: true, returnTo: null});
  expect(http.getToken()).toBe('home-token');
});

it('removes a saved server and its token, but never the active one', async () => {
  await secureStore.set(`token:${office.id}`, 'office-token');

  await useServerStore.getState().removeServer(office.id);
  await useServerStore.getState().removeServer(home.id);

  expect(useServerStore.getState().servers.map(s => s.id)).toEqual([home.id]);
  expect(await secureStore.get(`token:${office.id}`)).toBeNull();
});
