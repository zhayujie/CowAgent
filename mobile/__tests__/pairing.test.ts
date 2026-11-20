import {ApiError, http} from '../src/api/http';
import {addressCandidates, parsePairLink} from '../src/api/pairing';
import {secureStore} from '../src/storage/secureStore';
import {describePairError, useServerStore, type ServerProfile} from '../src/store/serverStore';

jest.mock('react-native-keychain', () => ({}));

const home: ServerProfile = {id: 'https://home.example', name: 'Home', baseUrl: 'https://home.example', wsUrl: null};

type Route = (init: RequestInit) => {status?: number; body?: unknown} | 'offline';

function mockFetch(routes: Record<string, Route>) {
  const calls: {url: string; init: RequestInit}[] = [];
  globalThis.fetch = jest.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const url = String(input);
    calls.push({url, init});
    const route = routes[url];
    const res = route ? route(init) : {status: 404, body: {}};
    if (res === 'offline') {
      throw new TypeError('Network request failed');
    }
    return {
      ok: (res.status ?? 200) < 400,
      status: res.status ?? 200,
      json: async () => res.body,
    } as Response;
  }) as typeof fetch;
  return calls;
}

const discovery = () => ({body: {type: 'instance', protocol: 1, auth: {required: true, methods: ['pairing']}}});

beforeEach(async () => {
  await secureStore.set(`token:${home.id}`, 'home-token');
  http.setBaseUrl(home.baseUrl);
  http.setToken('home-token');
  http.setIdentityCheck(null);
  useServerStore.setState({servers: [home], activeId: home.id, authed: true, returnTo: null, problem: null});
});

describe('parsePairLink', () => {
  it('reads the secret and the addresses in order', () => {
    const link =
      'cowagent://pair?v=1&c=abc_DEF-123&u=https%3A%2F%2Fagent.example.com&u=http%3A%2F%2F192.168.1.20%3A9899%2F';
    expect(parsePairLink(link)).toEqual({
      code: 'abc_DEF-123',
      urls: ['https://agent.example.com', 'http://192.168.1.20:9899'],
    });
  });

  it('ignores anything that is not a pairing link', () => {
    expect(parsePairLink('https://example.com/?c=1&u=http://x')).toBeNull();
    expect(parsePairLink('cowagent://pair?v=1&c=abc')).toBeNull();
    expect(parsePairLink('cowagent://pair?v=1&u=http%3A%2F%2Fx')).toBeNull();
  });

  it('drops addresses that are not http(s)', () => {
    expect(parsePairLink('cowagent://pair?c=s&u=javascript%3Aalert(1)&u=http%3A%2F%2Fok')?.urls).toEqual(['http://ok']);
  });
});

describe('addressCandidates', () => {
  it('tries http first for a local network address typed without a scheme', () => {
    expect(addressCandidates('192.168.1.20:9899')).toEqual(['http://192.168.1.20:9899', 'https://192.168.1.20:9899']);
  });

  it('keeps public hosts on https and leaves explicit schemes alone', () => {
    expect(addressCandidates('agent.example.com')).toEqual(['https://agent.example.com']);
    expect(addressCandidates('http://agent.example.com/')).toEqual(['http://agent.example.com']);
  });
});

it('pairs at the first address that answers and switches to it with the device token', async () => {
  const calls = mockFetch({
    'http://10.0.0.5:9899/.well-known/cowagent': () => 'offline',
    'http://192.168.1.20:9899/.well-known/cowagent': discovery,
    'http://192.168.1.20:9899/auth/pair': () => ({
      body: {status: 'success', token: 'cowd.d_1.secret', instance: {id: 'dev_mac', name: 'MacBook'}},
    }),
  });

  await useServerStore.getState().pair({code: 'ABCD-EFGH', urls: ['http://10.0.0.5:9899', 'http://192.168.1.20:9899']});

  const {servers, activeId, authed} = useServerStore.getState();
  expect({activeId, authed}).toEqual({activeId: 'http://192.168.1.20:9899', authed: true});
  expect(servers[0]).toMatchObject({name: 'MacBook', baseUrl: 'http://192.168.1.20:9899', instanceId: 'dev_mac'});
  expect(http.getToken()).toBe('cowd.d_1.secret');
  expect(await secureStore.get('token:http://192.168.1.20:9899')).toBe('cowd.d_1.secret');
  const pair = calls.find(c => c.url.endsWith('/auth/pair'))!;
  expect(JSON.parse(String(pair.init.body))).toMatchObject({code: 'ABCD-EFGH', device: {platform: 'ios'}});
  expect((pair.init.headers as Record<string, string>).Authorization).toBeUndefined();
});

it('keeps the current server when the code is refused', async () => {
  mockFetch({
    'http://192.168.1.20:9899/.well-known/cowagent': discovery,
    'http://192.168.1.20:9899/auth/pair': () => ({body: {status: 'error', reason: 'invalid_code', message: 'x'}}),
  });

  const err = await useServerStore
    .getState()
    .pair({code: 'WRONG', urls: ['http://192.168.1.20:9899']})
    .catch(e => e);

  expect(describePairError(err)).toBe('配对码错误或已失效，请在电脑上重新生成');
  expect(useServerStore.getState()).toMatchObject({activeId: home.id, authed: true});
  expect(http.getToken()).toBe('home-token');
});

it('tells a server from before pairing apart from a wrong address', async () => {
  mockFetch({'http://192.168.1.20:9899/auth/check': () => ({body: {auth_required: true}})});

  const err = await useServerStore
    .getState()
    .pair({code: 'ABCD-EFGH', urls: ['http://192.168.1.20:9899']})
    .catch(e => e);

  expect(describePairError(err)).toContain('需要 2.3.0 或更高版本');
  expect(useServerStore.getState()).toMatchObject({activeId: home.id, authed: true});

  mockFetch({});
  const other = await useServerStore
    .getState()
    .pair({code: 'ABCD-EFGH', urls: ['http://192.168.1.20:9899']})
    .catch(e => e);
  expect(describePairError(other)).toBe('192.168.1.20:9899 上有服务在响应（HTTP 404），但不是 CowAgent。请检查端口是否填对');
});

it('says why an address is no CowAgent to pair with', async () => {
  const pairAt = async (route: Route) => {
    mockFetch({'http://192.168.1.20:9899/.well-known/cowagent': route});
    const err = await useServerStore
      .getState()
      .pair({code: 'ABCD-EFGH', urls: ['http://192.168.1.20:9899']})
      .catch(e => e);
    return describePairError(err);
  };
  expect(await pairAt(() => 'offline')).toContain('连不上 192.168.1.20:9899');
  expect(await pairAt(() => ({status: 401, body: {}}))).toContain('需要先登录');
  expect(await pairAt(() => ({body: {hello: 'world'}}))).toContain('不是 CowAgent');
});

it('reports the most telling failure among the addresses tried', async () => {
  mockFetch({
    'http://192.168.1.20:9899/.well-known/cowagent': () => ({body: {hello: 'world'}}),
    'https://192.168.1.20:9899/.well-known/cowagent': () => 'offline',
  });
  const err = await useServerStore
    .getState()
    .pair({code: 'ABCD-EFGH', urls: addressCandidates('192.168.1.20:9899')})
    .catch(e => e);
  expect(describePairError(err)).toContain('不是 CowAgent');
});

it('explains an address that never answered', () => {
  expect(describePairError(new ApiError('network', 'x'))).toContain('同一网络');
});

describe('a token goes only to the device that issued it', () => {
  const office: ServerProfile = {
    id: 'http://192.168.1.30:9899',
    name: 'Office',
    baseUrl: 'http://192.168.1.30:9899',
    wsUrl: null,
    via: 'pairing',
    instanceId: 'dev_office',
  };
  const answer = (id: string) => () => ({body: {type: 'instance', protocol: 1, id}});

  beforeEach(async () => {
    await secureStore.set(`token:${office.id}`, 'cowd.d_9.office');
    useServerStore.setState({servers: [home, office]});
  });

  it('sends it once the address answers with the same id', async () => {
    const calls = mockFetch({
      'http://192.168.1.30:9899/.well-known/cowagent': answer('dev_office'),
      'http://192.168.1.30:9899/api/ping': () => ({body: {status: 'success'}}),
    });
    await useServerStore.getState().switchTo(office.id);
    await http.request('/api/ping');

    const ping = calls.find(c => c.url.endsWith('/api/ping'))!;
    expect((ping.init.headers as Record<string, string>).Authorization).toBe('Bearer cowd.d_9.office');
    expect((calls.find(c => c.url.endsWith('/.well-known/cowagent'))!.init.headers as Record<string, string>).Authorization).toBeUndefined();
  });

  it('holds it back from another device at the same address and leaves', async () => {
    const calls = mockFetch({
      'http://192.168.1.30:9899/.well-known/cowagent': answer('dev_stranger'),
      'http://192.168.1.30:9899/api/ping': () => ({status: 401, body: {}}),
    });
    await useServerStore.getState().switchTo(office.id);
    await http.request('/api/ping').catch(() => undefined);

    expect(calls.some(c => JSON.stringify(c.init.headers ?? {}).includes('cowd.d_9.office'))).toBe(false);
    expect(useServerStore.getState()).toMatchObject({authed: false, activeId: office.id});
    expect(useServerStore.getState().problem).toContain('Office');
    expect(await secureStore.get(`token:${office.id}`)).toBe('cowd.d_9.office');
  });

  it('takes the first id seen for a pairing from before ids', async () => {
    useServerStore.setState({servers: [home, {...office, instanceId: undefined}]});
    mockFetch({
      'http://192.168.1.30:9899/.well-known/cowagent': answer('dev_office'),
      'http://192.168.1.30:9899/api/ping': () => ({body: {status: 'success'}}),
    });
    await useServerStore.getState().switchTo(office.id);
    await http.request('/api/ping');

    expect(useServerStore.getState().servers.find(s => s.id === office.id)?.instanceId).toBe('dev_office');
  });

  it('does not sign out at an address now held by another device', async () => {
    const calls = mockFetch({'http://192.168.1.30:9899/.well-known/cowagent': answer('dev_stranger')});
    await useServerStore.getState().removeServer(office.id);
    await new Promise(r => setTimeout(r, 0));

    expect(calls.some(c => c.url.endsWith('/auth/logout'))).toBe(false);
  });
});

it('revokes a device token on sign out', async () => {
  http.setToken('cowd.d_1.secret');
  const calls = mockFetch({'https://home.example/auth/logout': () => ({body: {status: 'success'}})});

  await useServerStore.getState().logout();
  await new Promise(r => setTimeout(r, 0));

  const logout = calls.find(c => c.url === 'https://home.example/auth/logout');
  expect((logout?.init.headers as Record<string, string>).Authorization).toBe('Bearer cowd.d_1.secret');
  expect(await secureStore.get(`token:${home.id}`)).toBeNull();
});

it('keeps a device token when the password changes', async () => {
  http.setToken('cowd.d_1.secret');
  await useServerStore.getState().relogin('new-password', 'session-token');
  expect(http.getToken()).toBe('cowd.d_1.secret');
});
