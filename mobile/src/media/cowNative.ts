import {NativeModules, Platform, type TurboModule} from 'react-native';
import type {PickedFile} from './types';

/** A file the HarmonyOS module copied into the app sandbox; `path` has no scheme. */
export interface NativeFile {
  path: string;
  name: string;
  size: number;
}

interface CowNativeModule extends TurboModule {
  /** QR text, or null when the user backs out of the scanner. */
  scan(): Promise<string | null>;
  takePhoto(): Promise<NativeFile | null>;
  pickPhotos(max: number): Promise<NativeFile[]>;
  /** Saves into Downloads/<app name>; resolves with the name used, which avoids overwriting. With an id, reports progress. */
  saveDownload(url: string, fileName: string, id?: string): Promise<string>;
  /** The share panel with the file itself, from a link or a path on the phone. */
  share(source: string, fileName: string, mime: string): Promise<boolean>;
  /** What another app shared here, or null when nothing is waiting. */
  takeShared(): Promise<{files: PickedFile[]; text?: string} | null>;
}

/**
 * ArkTS rejects with the system's plain `{code, message}` object, which would print as
 * "[object Object]"; this turns it into an Error that reads.
 */
export function nativeError(e: unknown): Error {
  if (e instanceof Error) {
    return e;
  }
  const {code, message} = (e ?? {}) as {code?: unknown; message?: unknown};
  const text = typeof message === 'string' && message ? message : typeof e === 'string' ? e : '';
  return new Error([text, code != null ? `(${String(code)})` : ''].filter(Boolean).join(' ') || 'native error');
}

/**
 * A HarmonyOS ArkTS TurboModule (harmony/entry/src/main/ets/native), null elsewhere and on
 * builds that predate it. Looked up lazily because react-native-web has no TurboModuleRegistry,
 * and this file is part of the web preview.
 */
function harmonyModule<T extends TurboModule>(name: string): T | null {
  return (Platform.OS as string) === 'harmony'
    ? (require('react-native') as typeof import('react-native')).TurboModuleRegistry.get<T>(name)
    : null;
}

/** HarmonyOS-only system pickers, saving to Downloads and the share panel. */
export const cowNative = harmonyModule<CowNativeModule>('CowNative');

/** CowDevice: a native module on Android and iOS, an ArkTS TurboModule on HarmonyOS. */
export function deviceModule<T>(): T | undefined {
  return ((Platform.OS as string) === 'harmony' ? harmonyModule('CowDevice') : NativeModules.CowDevice) ?? undefined;
}
