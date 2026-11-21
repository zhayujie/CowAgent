import { TurboModule } from '@rnoh/react-native-openharmony/ts';
import { preferences } from '@kit.ArkData';
import { zlib } from '@kit.BasicServicesKit';
import { fileIo } from '@kit.CoreFileKit';
import { cryptoFramework } from '@kit.CryptoArchitectureKit';
import { i18n } from '@kit.LocalizationKit';
import { hilog } from '@kit.PerformanceAnalysisKit';
import { util } from '@kit.ArkTS';
import kernel from 'libcowkernel.so';

export const COW_KERNEL_MODULE = 'CowKernel';

const LOG_DOMAIN = 0x0C0E;
const LOG_TAG = 'CowKernel';
const PREFS = 'cow_kernel';
const PASSWORD_KEY = 'password';
const PORT_KEY = 'port';
const STAMP_KEY = 'sources_stamp';
// rawfile/cow-kernel, written by mobile/kernel/harmony_assets.py.
const ASSETS = 'cow-kernel';

export interface KernelEndpoint {
  port: number;
  password: string;
}

/** Shared by every React instance, like the kernel itself. */
let starting: Promise<KernelEndpoint> | null = null;

function newSecret(): string {
  const bytes = cryptoFramework.createRandom().generateRandomSync(24).data;
  let hex = '';
  for (let i = 0; i < bytes.length; i++) {
    hex += bytes[i].toString(16).padStart(2, '0');
  }
  return hex;
}

function removePath(path: string): void {
  if (!fileIo.accessSync(path)) {
    return;
  }
  if (fileIo.statSync(path).isDirectory()) {
    fileIo.rmdirSync(path);
  } else {
    fileIo.unlinkSync(path);
  }
}

/**
 * The agent kernel running inside this app: the CowAgent Python backend in its
 * `mobile` deployment, serving the usual web console API on loopback. The same
 * interface as CowKernel on Android and iOS.
 */
export class CowKernelModule extends TurboModule {
  static isAvailable(): boolean {
    return kernel.available();
  }

  /** Resolves with `{port, password}` once the kernel thread is started; it binds shortly after. */
  start(): Promise<KernelEndpoint> {
    if (starting === null) {
      starting = this.startKernel().finally(() => {
        starting = null;
      });
    }
    return starting;
  }

  private async startKernel(): Promise<KernelEndpoint> {
    const context = this.ctx.uiAbilityContext;
    const prefs = preferences.getPreferencesSync(context, { name: PREFS });
    // The console password guards the port against other apps on this device,
    // which can reach loopback too. It never leaves the app.
    let password = prefs.getSync(PASSWORD_KEY, '') as string;
    if (!password) {
      password = newSecret();
      prefs.putSync(PASSWORD_KEY, password);
    }
    if (kernel.isRunning()) {
      return { port: prefs.getSync(PORT_KEY, 0) as number, password };
    }
    const port = kernel.pickPort(prefs.getSync(PORT_KEY, 0) as number);
    if (port <= 0) {
      throw new Error('No free loopback port');
    }
    prefs.putSync(PORT_KEY, port);
    await prefs.flush();

    // The kernel keeps its workspace under ~/cow, like on a desktop.
    const home = context.filesDir;
    const python = `${home}/python`;
    const sources = `${home}/cow-kernel`;
    await this.installAssets(prefs, python, sources);

    // First launch only: later the app's Settings owns cow_lang via the API.
    // Blank (ignored by the kernel) otherwise, as a restart keeps os.environ.
    const firstRun = !fileIo.accessSync(`${home}/.cow/config.json`);
    const language = i18n.System.getSystemLanguage().toLowerCase();
    const started = kernel.start({
      pythonHome: python,
      pythonPath: [`${python}/stdlib.zip`, `${python}/site-packages.zip`],
      pycache: `${context.cacheDir}/cow-pycache`,
      sources,
      home,
      env: {
        'HOME': home,
        'TMPDIR': context.cacheDir,
        // OpenSSL finds no CA store on HarmonyOS; urllib-based HTTPS needs one.
        'SSL_CERT_FILE': `${python}/cacert.pem`,
        'COW_DEPLOYMENT': 'mobile',
        'COW_DATA_DIR': `${home}/.cow`,
        'COW_WEB_PORT': `${port}`,
        'WEB_PASSWORD': password,
        'COW_LANG': !firstRun ? '' : language.startsWith('zh') ? 'zh' : 'en',
      },
    });
    if (!started) {
      // Another React instance won the race; it bound the port saved above.
      return { port: prefs.getSync(PORT_KEY, port) as number, password };
    }
    hilog.info(LOG_DOMAIN, LOG_TAG, 'kernel starting on port %{public}d', port);
    return { port, password };
  }

  /**
   * Copy the runtime and kernel sources out of the read-only HAP once per
   * install or update, so the kernel runs from a writable tree as it does
   * everywhere else.
   */
  private async installAssets(prefs: preferences.Preferences, python: string, sources: string): Promise<void> {
    const resources = this.ctx.uiAbilityContext.resourceManager;
    const stamp = util.TextDecoder.create('utf-8').decodeToString(
      await resources.getRawFileContent(`${ASSETS}/STAMP`)).trim();
    if (prefs.getSync(STAMP_KEY, '') === stamp && fileIo.accessSync(`${sources}/app.py`) &&
      fileIo.accessSync(`${python}/stdlib.zip`)) {
      return;
    }
    hilog.info(LOG_DOMAIN, LOG_TAG, 'installing kernel %{public}s', stamp);
    removePath(python);
    fileIo.mkdirSync(python, true);
    for (const name of ['stdlib.zip', 'site-packages.zip', 'cacert.pem']) {
      await this.copyRawFile(`${ASSETS}/${name}`, `${python}/${name}`);
    }

    const archive = `${this.ctx.uiAbilityContext.cacheDir}/cow-kernel-sources.zip`;
    const staging = `${sources}.tmp`;
    await this.copyRawFile(`${ASSETS}/sources.zip`, archive);
    removePath(staging);
    fileIo.mkdirSync(staging, true);
    try {
      await zlib.decompressFile(archive, staging);
    } finally {
      fileIo.unlinkSync(archive);
    }
    removePath(sources);
    fileIo.renameSync(staging, sources);
    prefs.putSync(STAMP_KEY, stamp);
    await prefs.flush();
  }

  private async copyRawFile(name: string, dest: string): Promise<void> {
    const data = await this.ctx.uiAbilityContext.resourceManager.getRawFileContent(name);
    const file = fileIo.openSync(dest, fileIo.OpenMode.CREATE | fileIo.OpenMode.WRITE_ONLY | fileIo.OpenMode.TRUNC);
    try {
      await fileIo.write(file.fd, data.buffer.slice(data.byteOffset, data.byteOffset + data.byteLength));
    } finally {
      fileIo.closeSync(file);
    }
  }
}
