import {Platform, type TurboModule} from 'react-native';

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
  /** Saves into Downloads/<app name>; resolves with the name used, which avoids overwriting. */
  saveDownload(url: string, fileName: string): Promise<string>;
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
 * HarmonyOS-only system pickers (harmony/entry/src/main/ets/native). Null on other
 * platforms and on HarmonyOS builds that predate the module. Looked up lazily because
 * react-native-web has no TurboModuleRegistry, and this file is part of the web preview.
 */
export const cowNative: CowNativeModule | null =
  (Platform.OS as string) === 'harmony'
    ? (require('react-native') as typeof import('react-native')).TurboModuleRegistry.get<CowNativeModule>('CowNative')
    : null;
