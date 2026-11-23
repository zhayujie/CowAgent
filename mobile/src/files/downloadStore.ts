import {DeviceEventEmitter, type EmitterSubscription} from 'react-native';
import {create} from 'zustand';
import {omit} from '../utils/object';

export type DownloadStatus = 'downloading' | 'done' | 'failed';

export interface DownloadProgress {
  url: string;
  name: string;
  status: DownloadStatus;
  loaded: number;
  total: number | null;
  /** The size the server reported, for responses that arrive without one (chunked). */
  expected: number | null;
}

interface DownloadState {
  byId: Record<string, DownloadProgress>;
  start: (id: string, url: string, name: string, expected?: number) => void;
  progress: (id: string, loaded: number, total: number) => void;
  finish: (id: string) => void;
  fail: (id: string) => void;
  clear: (id: string) => void;
}

export const useDownloadStore = create<DownloadState>(set => ({
  byId: {},
  start: (id, url, name, expected) =>
    set(s => ({
      byId: {
        ...s.byId,
        [id]: {url, name, status: 'downloading', loaded: 0, total: null, expected: expected || null},
      },
    })),
  progress: (id, loaded, total) =>
    set(s => {
      const current = s.byId[id];
      // An event in flight when the download settles must not bring the bar back.
      if (!current || current.status === 'done') {
        return s;
      }
      const nextTotal = total > 0 ? total : current.total;
      if (current.loaded === loaded && current.total === nextTotal) {
        return s;
      }
      return {
        byId: {
          ...s.byId,
          [id]: {...current, status: 'downloading', loaded, total: nextTotal},
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
  clear: id => set(s => (s.byId[id] ? {byId: omit(s.byId, [id])} : s)),
}));

/**
 * A key for a URL that is not a known file (a link inside a page, the server log). The login
 * token rotates on every refresh, so it is stripped; dropping it must not merge two files.
 */
const withoutToken = (url: string) => {
  const [base, query] = url.split('?');
  if (!query) {
    return url;
  }
  const kept = query.split('&').filter(part => !/^token=/i.test(part));
  return kept.length ? `${base}?${kept.join('&')}` : base;
};

/** One identity for a remote file, shared by save, open-with, cards and the preview page. */
export const downloadKey = (url: string, name: string) => JSON.stringify([withoutToken(url), name]);

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
