import {DeviceEventEmitter, type EmitterSubscription} from 'react-native';
import {create} from 'zustand';

export type DownloadStatus = 'downloading' | 'done' | 'failed';

export interface DownloadProgress {
  url: string;
  name: string;
  status: DownloadStatus;
  loaded: number;
  total: number | null;
}

interface DownloadState {
  byId: Record<string, DownloadProgress>;
  start: (id: string, url: string, name: string) => void;
  progress: (id: string, loaded: number, total: number) => void;
  finish: (id: string) => void;
  fail: (id: string) => void;
}

export const useDownloadStore = create<DownloadState>(set => ({
  byId: {},
  start: (id, url, name) =>
    set(s => ({
      byId: {
        ...s.byId,
        [id]: {url, name, status: 'downloading', loaded: 0, total: null},
      },
    })),
  progress: (id, loaded, total) =>
    set(s => {
      const current = s.byId[id];
      if (!current) {
        return s;
      }
      return {
        byId: {
          ...s.byId,
          [id]: {...current, status: 'downloading', loaded, total: total > 0 ? total : null},
        },
      };
    }),
  finish: id =>
    set(s => {
      const current = s.byId[id];
      return current ? {byId: {...s.byId, [id]: {...current, status: 'done'}}} : s;
    }),
  fail: id =>
    set(s => {
      const current = s.byId[id];
      return current ? {byId: {...s.byId, [id]: {...current, status: 'failed'}}} : s;
    }),
}));

/** One identity for a remote file, shared by save, open-with, cards and the preview page. */
export const downloadKey = (url: string, name: string) => JSON.stringify([url, name]);

let nativeProgress: EmitterSubscription | null = null;

/** Register lazily only once Android's native downloader is actually used. */
export function listenForDownloadProgress() {
  if (nativeProgress) {
    return;
  }
  nativeProgress = DeviceEventEmitter.addListener('cowDownloadProgress', event => {
    const {id, loaded, total} = event as {id: string; loaded: number; total: number};
    useDownloadStore.getState().progress(id, loaded, total);
  });
}
