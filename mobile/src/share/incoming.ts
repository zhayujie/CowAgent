import {DeviceEventEmitter, Linking, NativeModules, Platform} from 'react-native';
import {create} from 'zustand';
import type {PickedFile} from '../media/types';

/**
 * Files, pictures and text shared into the app from another one, such as a chat
 * app's "share" or "open with": Android hands them over as a share, iOS opens the
 * app with a copy of the file. They wait here until the chat composer takes them.
 */
export const useIncomingShare = create<{files: PickedFile[]; text: string}>(() => ({files: [], text: ''}));

export function takeIncomingShare(): {files: PickedFile[]; text: string} {
  const got = useIncomingShare.getState();
  useIncomingShare.setState({files: [], text: ''});
  return got;
}

const native: {takeShared?(): Promise<{files: PickedFile[]; text?: string} | null>} | undefined =
  NativeModules.CowDownloads;

const MIME: Record<string, string> = {
  jpg: 'image/jpeg',
  jpeg: 'image/jpeg',
  png: 'image/png',
  gif: 'image/gif',
  webp: 'image/webp',
  heic: 'image/heic',
  mp4: 'video/mp4',
  mov: 'video/quicktime',
  pdf: 'application/pdf',
  txt: 'text/plain',
  md: 'text/markdown',
  csv: 'text/csv',
  doc: 'application/msword',
  docx: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  xls: 'application/vnd.ms-excel',
  xlsx: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  ppt: 'application/vnd.ms-powerpoint',
  pptx: 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
  zip: 'application/zip',
};

function fromFileUrl(url: string): PickedFile {
  const last = url.split(/[?#]/)[0].split('/').pop() || 'file';
  let name = last;
  try {
    name = decodeURIComponent(last);
  } catch {
    // Kept as it came.
  }
  const ext = name.includes('.') ? name.split('.').pop()!.toLowerCase() : '';
  return {uri: url, name, type: MIME[ext] ?? 'application/octet-stream'};
}

const arrive = (files: PickedFile[], text = '') =>
  (files.length || text) &&
  useIncomingShare.setState(s => ({files: [...s.files, ...files], text: [s.text, text].filter(Boolean).join('\n')}));

const takeFromAndroid = () =>
  native?.takeShared?.().then(
    got => got && arrive(got.files ?? [], got.text ?? ''),
    () => undefined,
  );

let listening = false;

/** Started once for the life of the app; what was shared at launch is picked up too. */
export function listenForShares(): void {
  if (listening) {
    return;
  }
  listening = true;
  if (Platform.OS === 'android') {
    takeFromAndroid();
    DeviceEventEmitter.addListener('cowShared', takeFromAndroid);
  } else if (Platform.OS === 'ios') {
    const take = (url: string | null) => url?.startsWith('file:') && arrive([fromFileUrl(url)]);
    Linking.getInitialURL().then(take, () => undefined);
    Linking.addEventListener('url', e => take(e.url));
  }
}
