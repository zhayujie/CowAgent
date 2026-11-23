import AsyncStorage from '@react-native-async-storage/async-storage';

const dropUpdate = jest.fn(() => Promise.resolve());

/** The module reads the platform and native modules once, at import. */
const openMarket = jest.fn(() => Promise.resolve());

function load(os: 'android' | 'ios' = 'android', testFlight = false, installer = ''): typeof import('../src/update/appUpdate') {
  jest.resetModules();
  // A reload is an app restart: what the app stored stays.
  jest.doMock('@react-native-async-storage/async-storage', () => AsyncStorage);
  const RN = require('react-native');
  RN.Platform.OS = os;
  RN.NativeModules.CowDownloads = {installUpdate: jest.fn(), allowInstalls: jest.fn(), dropUpdate, openMarket};
  RN.NativeModules.CowDevice = {appVersion: '2.2.2', testFlight, installer};
  require('../src/i18n').useLangStore.getState().setLang('zh');
  return require('../src/update/appUpdate');
}

const feed = (version: string) =>
  ({ok: true, status: 200, json: async () => ({version, file: `CowAgent-${version}.apk`, size: 10, sha512: 'x'})}) as Response;

const STORE = 'https://apps.apple.com/app/id1';
const storeFeed = (version: string) => ({ok: true, status: 200, json: async () => ({version, url: STORE})}) as Response;

beforeEach(async () => {
  await AsyncStorage.clear();
  dropUpdate.mockClear();
});

it('orders versions as semver, pre-releases first', () => {
  const {compareVersions} = load();
  expect(compareVersions('2.2.3', '2.2.2')).toBe(1);
  expect(compareVersions('2.10.0', '2.9.9')).toBe(1);
  expect(compareVersions('v2.2.2', '2.2.2')).toBe(0);
  expect(compareVersions('2.3.0-test', '2.3.0')).toBe(-1);
  expect(compareVersions('2.3.0-test', '2.2.9')).toBe(1);
});

it('asks the site in China first for Chinese users and falls back to the other', async () => {
  const {checkAppUpdate, useAppUpdate} = load();
  const fetchMock = jest
    .fn()
    .mockRejectedValueOnce(new Error('unreachable'))
    .mockResolvedValueOnce(feed('2.2.3'));
  globalThis.fetch = fetchMock;

  const release = await checkAppUpdate();
  expect(fetchMock.mock.calls[0][0]).toBe('https://cowagent.cn/update/android.json?lang=zh');
  expect(fetchMock.mock.calls[1][0]).toBe('https://cowagent.ai/update/android.json?lang=zh');
  expect(release).toMatchObject({version: '2.2.3', host: 'https://cowagent.ai'});
  expect(useAppUpdate.getState().release?.version).toBe('2.2.3');
});

it('offers nothing and clears the cached APK when this version is the newest', async () => {
  const {checkAppUpdate, useAppUpdate} = load();
  globalThis.fetch = jest.fn().mockResolvedValue(feed('2.2.2'));
  expect(await checkAppUpdate()).toBeNull();
  expect(useAppUpdate.getState().release).toBeNull();
  expect(dropUpdate).toHaveBeenCalled();
});

it('checks on every launch and prompts once per version', async () => {
  let app = load();
  globalThis.fetch = jest.fn().mockResolvedValue(feed('2.2.3'));
  await app.checkAppUpdateQuietly();
  expect(app.useAppUpdate.getState().prompt).toBe(true);
  app.postponeAppUpdate();

  app = load();
  const fetchMock = jest.fn().mockResolvedValue(feed('2.2.3'));
  globalThis.fetch = fetchMock;
  await app.checkAppUpdateQuietly();
  expect(fetchMock).toHaveBeenCalled();
  expect(app.useAppUpdate.getState().prompt).toBe(false);
});

it('checks again on return to the app only after a while, unless the last check failed', async () => {
  const {checkAppUpdateQuietly} = load();
  const fetchMock = jest.fn().mockRejectedValue(new Error('offline'));
  globalThis.fetch = fetchMock;
  await checkAppUpdateQuietly();
  expect(fetchMock).toHaveBeenCalledTimes(2);

  fetchMock.mockReset().mockResolvedValue(feed('2.2.2'));
  await checkAppUpdateQuietly();
  await checkAppUpdateQuietly();
  expect(fetchMock).toHaveBeenCalledTimes(1);
});

it('goes on with the install after the install permission page, even after a restart', async () => {
  let app = load();
  globalThis.fetch = jest.fn().mockResolvedValue(feed('2.2.3'));
  await app.checkAppUpdateQuietly();
  await app.allowAppInstalls();
  app.useAppUpdate.setState({prompt: false});

  app = load();
  const installUpdate = require('react-native').NativeModules.CowDownloads.installUpdate;
  installUpdate.mockResolvedValue('installing');
  await app.checkAppUpdateQuietly();
  expect(installUpdate).toHaveBeenCalledWith(expect.stringContaining('/update/CowAgent-2.2.3.apk'), 'CowAgent-2.2.3.apk', 'x');
  expect(app.useAppUpdate.getState().prompt).toBe(true);
});

it('points an App Store build to a newer release on the App Store', async () => {
  const {checkAppUpdate, installAppUpdate} = load('ios');
  const fetchMock = jest.fn().mockResolvedValue(storeFeed('2.2.2'));
  globalThis.fetch = fetchMock;
  expect(await checkAppUpdate()).toBeNull();
  expect(fetchMock.mock.calls[0][0]).toBe('https://cowagent.cn/update/ios.json?lang=zh');

  fetchMock.mockResolvedValue(storeFeed('2.2.3'));
  expect(await checkAppUpdate()).toMatchObject({version: '2.2.3', storeUrl: STORE});
  const openURL = jest.spyOn(require('react-native').Linking, 'openURL').mockResolvedValue(true);
  await installAppUpdate();
  expect(openURL).toHaveBeenCalledWith(STORE);
});

it('sends an app from a market back there, once that market carries the new version', async () => {
  const {checkAppUpdate, installAppUpdate} = load('android', false, 'com.xiaomi.market');
  const markets = (m: Record<string, string>) =>
    ({ok: true, status: 200, json: async () => ({...(await feed('2.2.4').json()), markets: m})}) as Response;
  globalThis.fetch = jest.fn().mockResolvedValue(markets({huawei: '2.2.3'}));
  expect(await checkAppUpdate()).toBeNull();

  globalThis.fetch = jest.fn().mockResolvedValue(markets({xiaomi: '2.2.3'}));
  expect(await checkAppUpdate()).toMatchObject({version: '2.2.3', market: 'com.xiaomi.market'});
  await installAppUpdate();
  expect(openMarket).toHaveBeenCalledWith('com.xiaomi.market');
});

it('updates a sideloaded app from the APK even when markets are listed', async () => {
  const {checkAppUpdate} = load('android', false, 'com.google.android.packageinstaller');
  globalThis.fetch = jest
    .fn()
    .mockResolvedValue({ok: true, status: 200, json: async () => ({markets: {xiaomi: '2.2.3'}})} as Response);
  expect(await checkAppUpdate()).toBeNull();
  globalThis.fetch = jest.fn().mockResolvedValue(feed('2.2.3'));
  expect(await checkAppUpdate()).toMatchObject({version: '2.2.3', file: 'CowAgent-2.2.3.apk'});
});

it('moves a TestFlight build to the App Store once its own version is live there', async () => {
  const {checkAppUpdate} = load('ios', true);
  globalThis.fetch = jest.fn().mockResolvedValue(storeFeed('2.2.2'));
  expect(await checkAppUpdate()).toMatchObject({version: '2.2.2'});
  globalThis.fetch = jest.fn().mockResolvedValue(storeFeed('2.2.1'));
  expect(await checkAppUpdate()).toBeNull();
});
