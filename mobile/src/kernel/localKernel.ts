import {NativeModules} from 'react-native';
import {tr} from '../i18n';

/**
 * The agent kernel embedded in the app: the same CowAgent backend a server
 * runs, serving the usual console API on loopback. Builds without it (web
 * preview, platforms not wired up yet) only connect to remote servers.
 */
interface NativeKernel {
  start(): Promise<{port: number; password: string}>;
}

const native: NativeKernel | undefined = NativeModules.CowKernel;

export const LOCAL_SERVER_ID = 'local';

/** First launch unpacks the sources and compiles them, which takes a while on slow phones. */
const READY_TIMEOUT_MS = 90_000;

export function isLocalKernelAvailable(): boolean {
  return !!native;
}

export interface LocalKernel {
  baseUrl: string;
  password: string;
}

/** Start the kernel if it isn't running and wait until its API answers. */
export async function startLocalKernel(): Promise<LocalKernel> {
  if (!native) {
    throw new Error('This build has no embedded kernel');
  }
  const {port, password} = await native.start();
  const baseUrl = `http://127.0.0.1:${port}`;
  await waitUntilReady(baseUrl);
  return {baseUrl, password};
}

async function waitUntilReady(baseUrl: string) {
  const deadline = Date.now() + READY_TIMEOUT_MS;
  while (Date.now() < deadline) {
    try {
      const res = await fetch(`${baseUrl}/api/health`);
      if (res.ok) {
        return;
      }
    } catch {
      // Not listening yet.
    }
    await new Promise<void>(resolve => setTimeout(resolve, 300));
  }
  throw new Error(tr('server_local_timeout'));
}
