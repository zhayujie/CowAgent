import {PermissionsAndroid, Platform} from 'react-native';
import {tr} from '../i18n';
import {cowNative, nativeError, type NativeFile} from './cowNative';
import type {PickedFile} from './types';

type ImagePickerModule = typeof import('react-native-image-picker');
type DocumentPickerModule = typeof import('react-native-document-picker');

// Required lazily: the image picker has no HarmonyOS build, and touching its
// TurboModule there would throw at import time.
const imagePicker = (): ImagePickerModule | null =>
  Platform.OS === 'ios' || Platform.OS === 'android' ? require('react-native-image-picker') : null;
const documentPicker = (): DocumentPickerModule => require('react-native-document-picker');

const isHarmony = (Platform.OS as string) === 'harmony';

/** HarmonyOS goes through the system camera and photo pickers in our own native module. */
export const canTakePhoto = Platform.OS === 'ios' || Platform.OS === 'android' || cowNative != null;

const MAX_PICK = 9;

const extOf = (name: string) => name.split('.').pop()?.toLowerCase() ?? '';
/** HarmonyOS pickers return bare sandbox paths; <Image> needs a file:// URI. */
const toFileUri = (path: string) => (path.startsWith('/') ? `file://${path}` : path);
const IMAGE_MIME: Record<string, string> = {
  jpg: 'image/jpeg',
  jpeg: 'image/jpeg',
  png: 'image/png',
  gif: 'image/gif',
  webp: 'image/webp',
  heic: 'image/heic',
};

function fromAssets(
  assets: {uri?: string; fileName?: string; type?: string; fileSize?: number}[] | undefined,
): PickedFile[] {
  return (assets ?? [])
    .filter(a => !!a.uri)
    .map((a, i) => {
      const name = a.fileName || `photo_${Date.now()}_${i}.jpg`;
      return {
        uri: a.uri as string,
        name,
        type: a.type || IMAGE_MIME[extOf(name)] || 'image/jpeg',
        size: a.fileSize,
      };
    });
}

const rethrowNative = (e: unknown): never => {
  throw nativeError(e);
};

function fromNative(files: NativeFile[]): PickedFile[] {
  return files.map(f => ({
    uri: toFileUri(f.path),
    name: f.name,
    type: IMAGE_MIME[extOf(f.name)] || 'image/jpeg',
    size: f.size,
  }));
}

function ensureOk(res: {errorCode?: string; errorMessage?: string}) {
  if (res.errorCode === 'permission') {
    throw new Error(tr('media_permission_denied'));
  }
  if (res.errorCode === 'camera_unavailable') {
    throw new Error(tr('media_no_camera'));
  }
  if (res.errorCode) {
    throw new Error(res.errorMessage || tr('media_cannot_open'));
  }
}

export async function pickPhotos(limit = MAX_PICK): Promise<PickedFile[]> {
  if (cowNative) {
    return fromNative(await cowNative.pickPhotos(limit).catch(rethrowNative));
  }
  const picker = imagePicker();
  if (!picker) {
    return pickDocuments(true);
  }
  const res = await picker.launchImageLibrary({
    mediaType: 'photo',
    selectionLimit: limit,
    quality: 0.8,
    maxWidth: 2560,
    maxHeight: 2560,
  });
  ensureOk(res);
  return res.didCancel ? [] : fromAssets(res.assets);
}

/** One image, scaled down to stay well under the server's 2 MiB avatar limit. */
export async function pickAvatar(): Promise<PickedFile | null> {
  if (cowNative) {
    return fromNative(await cowNative.pickPhotos(1).catch(rethrowNative))[0] ?? null;
  }
  const picker = imagePicker();
  if (!picker) {
    return (await pickDocuments(true))[0] ?? null;
  }
  const res = await picker.launchImageLibrary({
    mediaType: 'photo',
    selectionLimit: 1,
    quality: 0.8,
    maxWidth: 512,
    maxHeight: 512,
  });
  ensureOk(res);
  return res.didCancel ? null : fromAssets(res.assets)[0] ?? null;
}

export async function takePhoto(): Promise<PickedFile[]> {
  if (cowNative) {
    // The camera picker fails outright where there is no camera, the emulator included.
    const photo = await cowNative.takePhoto().catch((e: unknown) => {
      throw new Error(`${tr('media_no_camera')}: ${nativeError(e).message}`);
    });
    return photo ? fromNative([photo]) : [];
  }
  const picker = imagePicker();
  if (!picker) {
    return [];
  }
  // The manifest declares CAMERA (for scanning pairing codes), and then the
  // system camera intent also requires the permission to be granted.
  if (Platform.OS === 'android') {
    const granted = await PermissionsAndroid.request(PermissionsAndroid.PERMISSIONS.CAMERA);
    if (granted !== PermissionsAndroid.RESULTS.GRANTED) {
      throw new Error(tr('media_permission_denied'));
    }
  }
  const res = await picker.launchCamera({
    mediaType: 'photo',
    quality: 0.8,
    maxWidth: 2560,
    maxHeight: 2560,
    saveToPhotos: false,
  });
  ensureOk(res);
  return res.didCancel ? [] : fromAssets(res.assets);
}

export async function pickDocuments(imagesOnly = false): Promise<PickedFile[]> {
  const picker = documentPicker();
  try {
    const res = await picker.pick({
      type: [imagesOnly ? picker.types.images : picker.types.allFiles],
      allowMultiSelection: true,
      // Android hands back content:// URIs that can expire, and HarmonyOS paths outside the
      // sandbox that uploads can't read; a cache copy works for both. The HarmonyOS build
      // rejects the key when it is present but undefined.
      ...(Platform.OS === 'android' || isHarmony ? {copyTo: 'cachesDirectory' as const} : {}),
    });
    return res.slice(0, MAX_PICK).map((d, i) => {
      const name = d.name || `file_${Date.now()}_${i}`;
      return {
        uri: toFileUri(d.fileCopyUri || d.uri),
        name,
        type: d.type || IMAGE_MIME[extOf(name)] || 'application/octet-stream',
        size: d.size ?? undefined,
      };
    });
  } catch (e) {
    if (picker.isCancel(e)) {
      return [];
    }
    throw e;
  }
}
