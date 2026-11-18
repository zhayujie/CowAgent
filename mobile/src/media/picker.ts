import {PermissionsAndroid, Platform} from 'react-native';
import {tr} from '../i18n';
import type {PickedFile} from './types';

type ImagePickerModule = typeof import('react-native-image-picker');
type DocumentPickerModule = typeof import('react-native-document-picker');

// Required lazily: the image picker has no HarmonyOS build, and touching its
// TurboModule there would throw at import time.
const imagePicker = (): ImagePickerModule | null =>
  Platform.OS === 'ios' || Platform.OS === 'android' ? require('react-native-image-picker') : null;
const documentPicker = (): DocumentPickerModule => require('react-native-document-picker');

/** HarmonyOS has no camera picker wired in yet; photos come from the system file picker. */
export const canTakePhoto = Platform.OS === 'ios' || Platform.OS === 'android';

const MAX_PICK = 9;

const extOf = (name: string) => name.split('.').pop()?.toLowerCase() ?? '';
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

export async function pickPhotos(): Promise<PickedFile[]> {
  const picker = imagePicker();
  if (!picker) {
    return pickDocuments(true);
  }
  const res = await picker.launchImageLibrary({
    mediaType: 'photo',
    selectionLimit: MAX_PICK,
    quality: 0.8,
    maxWidth: 2560,
    maxHeight: 2560,
  });
  ensureOk(res);
  return res.didCancel ? [] : fromAssets(res.assets);
}

/** One image, scaled down to stay well under the server's 2 MiB avatar limit. */
export async function pickAvatar(): Promise<PickedFile | null> {
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
      // Android hands back content:// URIs that can expire; a cache copy can be uploaded later.
      copyTo: Platform.OS === 'android' ? 'cachesDirectory' : undefined,
    });
    return res.slice(0, MAX_PICK).map((d, i) => {
      const name = d.name || `file_${Date.now()}_${i}`;
      return {
        uri: d.fileCopyUri || d.uri,
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
