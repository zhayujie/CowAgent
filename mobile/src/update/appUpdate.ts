import {AppState, Linking, NativeModules, Platform} from 'react-native';
import {create} from 'zustand';
import {listenForDownloadProgress, useDownloadStore} from '../files/downloadStore';
import {getLang} from '../i18n';
import {readJSON, writeJSON} from '../storage/kv';

/** The newest release of the app, as the project's site lists it. */
export interface AppRelease {
  version: string;
  /** The APK on Android; iOS has none. */
  file: string;
  size: number;
  /** Base64 SHA-512 of the APK. */
  sha512: string;
  /** The site that answered, which the APK is then fetched from too. */
  host: string;
  /** iOS: the app's App Store page, where the update is installed. */
  storeUrl?: string;
  /** Android, installed from an app market: that market's package, which delivers the update. */
  market?: string;
}

type Phase = 'idle' | 'downloading' | 'blocked' | 'failed';

interface UpdateState {
  release: AppRelease | null;
  /** The update sheet is up. */
  prompt: boolean;
  phase: Phase;
  error: string | null;
}

export const useAppUpdate = create<UpdateState>(() => ({release: null, prompt: false, phase: 'idle', error: null}));

/** Download progress of the APK, in the download store. */
export const UPDATE_ID = 'app-update';

const native:
  | {
      installUpdate(url: string, file: string, sha512: string): Promise<'installing' | 'blocked'>;
      allowInstalls(): Promise<void>;
      dropUpdate(): Promise<void>;
      openMarket(market: string): Promise<void>;
    }
  | undefined = Platform.OS === 'android' ? NativeModules.CowDownloads : undefined;

const device = NativeModules.CowDevice;
const constants: {appVersion?: string; testFlight?: boolean; installer?: string} =
  device?.getConstants?.() ?? device ?? {};
export const appVersion: string = constants.appVersion ?? '';
/** A TestFlight build, which is also offered the App Store release of its own version. */
export const testFlight = Platform.OS === 'ios' && !!constants.testFlight;

// Android app markets by package, under the ids the release feed lists them by. An app one of
// them installed updates there: it may be signed with the market's key, and markets forbid
// updating around them.
const MARKETS: Record<string, string> = {
  'com.android.vending': 'play',
  'com.xiaomi.market': 'xiaomi',
  'com.huawei.appmarket': 'huawei',
  'com.hihonor.appmarket': 'honor',
  'com.heytap.market': 'oppo',
  'com.oppo.market': 'oppo',
  'com.bbk.appstore': 'vivo',
  'com.tencent.android.qqdownloader': 'tencent',
  'com.meizu.mstore': 'meizu',
  'com.sec.android.app.samsungapps': 'samsung',
  'com.coolapk.market': 'coolapk',
};
const installer = Platform.OS === 'android' ? (constants.installer ?? '') : '';
/** The feed id of the app market this app came from, if it came from one. */
export const appMarket: string | undefined = MARKETS[installer];

// Both sites list the same releases; Chinese users try the one in China first.
const HOSTS = ['https://cowagent.ai', 'https://cowagent.cn'];
const CHECK_EVERY_MS = 24 * 60 * 60 * 1000;
const TIMEOUT_MS = 10_000;
const CHECKED_KEY = 'app-update-checked';
const SKIPPED_KEY = 'app-update-skipped';

/** Android installs its own updates; iOS points to the App Store. */
export const appUpdatesSupported = () => (Platform.OS === 'ios' || !!native?.installUpdate) && !!appVersion;

const FEED = Platform.OS === 'ios' ? 'ios.json' : 'android.json';

const parts = (v: string) => {
  const [core, pre = ''] = v.replace(/^v/i, '').split('-', 2);
  return {nums: core.split('.').map(n => parseInt(n, 10) || 0), pre};
};

/** Semver order; a pre-release such as 2.3.0-test comes before 2.3.0. */
export function compareVersions(a: string, b: string): number {
  const x = parts(a);
  const y = parts(b);
  for (let i = 0; i < Math.max(x.nums.length, y.nums.length); i++) {
    const d = (x.nums[i] ?? 0) - (y.nums[i] ?? 0);
    if (d) {
      return Math.sign(d);
    }
  }
  if (x.pre === y.pre) {
    return 0;
  }
  if (!x.pre || !y.pre) {
    return x.pre ? -1 : 1;
  }
  return x.pre < y.pre ? -1 : 1;
}

const langQuery = () => (getLang() === 'zh' ? 'zh' : 'en');

async function fetchFeed(host: string): Promise<AppRelease | null> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
  try {
    const res = await fetch(`${host}/update/${FEED}?lang=${langQuery()}`, {signal: controller.signal});
    if (res.status === 404) {
      return null;
    }
    if (!res.ok) {
      throw new Error(`HTTP ${res.status}`);
    }
    const body = await res.json();
    if (!body || typeof body !== 'object') {
      throw new Error('Unexpected release feed');
    }
    if (appMarket) {
      // Only what this market already carries; until then there is nothing to update to.
      const version = body.markets?.[appMarket];
      return typeof version === 'string' ? {version, file: '', size: 0, sha512: '', host, market: installer} : null;
    }
    if (typeof body.version !== 'string') {
      // Markets carry the app, but no APK is listed for direct installs.
      return null;
    }
    if (Platform.OS === 'ios') {
      if (typeof body.url !== 'string' || !/^https:\/\//.test(body.url)) {
        throw new Error('Unexpected release feed');
      }
      return {version: body.version, file: '', size: 0, sha512: '', host, storeUrl: body.url};
    }
    if (typeof body.file !== 'string' || typeof body.sha512 !== 'string') {
      throw new Error('Unexpected release feed');
    }
    return {version: body.version, file: body.file, size: Number(body.size) || 0, sha512: body.sha512, host};
  } finally {
    clearTimeout(timer);
  }
}

/** The newest release if it is newer than this app; throws when neither site answers. */
export async function checkAppUpdate(): Promise<AppRelease | null> {
  if (!appUpdatesSupported()) {
    return null;
  }
  const hosts = getLang() === 'zh' ? [...HOSTS].reverse() : HOSTS;
  let latest: AppRelease | null = null;
  let failure: unknown = null;
  for (const host of hosts) {
    try {
      latest = await fetchFeed(host);
      failure = null;
      break;
    } catch (e) {
      failure = e;
    }
  }
  if (failure) {
    throw failure;
  }
  writeJSON(CHECKED_KEY, Date.now()).catch(() => undefined);
  const order = latest ? compareVersions(latest.version, appVersion) : -1;
  const release = latest && (order > 0 || (order === 0 && testFlight)) ? latest : null;
  if (!release) {
    // Installed, or no longer the newest: the APK left in the cache is dead weight.
    native?.dropUpdate().catch(() => undefined);
  }
  useAppUpdate.setState({release});
  return release;
}

/** At most once a day, quietly; offers each new version once. */
export async function checkAppUpdateDaily(): Promise<void> {
  if (!appUpdatesSupported() || Date.now() - (await readJSON<number>(CHECKED_KEY, 0)) < CHECK_EVERY_MS) {
    return;
  }
  const release = await checkAppUpdate().catch(() => null);
  if (release && release.version !== (await readJSON<string>(SKIPPED_KEY, ''))) {
    useAppUpdate.setState({prompt: true});
  }
}

/** "Later": the daily check stays quiet until a newer version than this one. */
export function postponeAppUpdate(): void {
  const {release, phase} = useAppUpdate.getState();
  useAppUpdate.setState({prompt: false});
  if (release && phase !== 'downloading') {
    writeJSON(SKIPPED_KEY, release.version).catch(() => undefined);
  }
}

/**
 * Android: downloads the release, with its progress in the update sheet, and opens the system
 * installer, which asks the user to confirm. iOS, and apps from an app market: opens the app's
 * page there.
 */
export async function installAppUpdate(): Promise<void> {
  const {release, phase} = useAppUpdate.getState();
  if (release?.storeUrl) {
    useAppUpdate.setState({prompt: false});
    Linking.openURL(release.storeUrl).catch(() => undefined);
    return;
  }
  if (release?.market) {
    useAppUpdate.setState({prompt: false});
    native?.openMarket(release.market).catch(() => undefined);
    return;
  }
  if (!release || !native || phase === 'downloading') {
    return;
  }
  const url = `${release.host}/update/${encodeURIComponent(release.file)}?lang=${langQuery()}`;
  listenForDownloadProgress();
  useDownloadStore.getState().start(UPDATE_ID, url, release.file, release.size);
  useAppUpdate.setState({prompt: true, phase: 'downloading', error: null});
  try {
    const result = await native.installUpdate(url, release.file, release.sha512);
    useDownloadStore.getState().clear(UPDATE_ID);
    useAppUpdate.setState({phase: result === 'blocked' ? 'blocked' : 'idle'});
  } catch (e) {
    useDownloadStore.getState().fail(UPDATE_ID);
    const err = e as {code?: string; message?: string};
    useAppUpdate.setState({phase: 'failed', error: err.code === 'corrupt' ? 'corrupt' : err.message || String(e)});
  }
}

/** The system page for installing apps; the install goes on once the user comes back. */
export async function allowAppInstalls(): Promise<void> {
  await native?.allowInstalls();
  const sub = AppState.addEventListener('change', state => {
    if (state === 'active') {
      sub.remove();
      installAppUpdate();
    }
  });
}
