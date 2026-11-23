import {DeviceEventEmitter} from 'react-native';
import {downloadKey, listenForDownloadProgress, useDownloadStore} from '../src/files/downloadStore';

beforeEach(() => {
  useDownloadStore.setState({byId: {}});
});

it('keeps progress and retained bytes for a later resume', () => {
  const id = downloadKey('https://example.com/a.docx', 'a.docx');
  const store = useDownloadStore.getState();
  store.start(id, 'https://example.com/a.docx', 'a.docx');
  store.progress(id, 50, 200);
  expect(useDownloadStore.getState().byId[id]).toMatchObject({loaded: 50, total: 200, status: 'downloading'});

  store.fail(id);
  expect(useDownloadStore.getState().byId[id]).toMatchObject({loaded: 50, total: 200, status: 'failed'});

  store.start(id, 'https://example.com/a.docx', 'a.docx');
  store.progress(id, 75, 200);
  store.finish(id);
  expect(useDownloadStore.getState().byId[id]?.status).toBe('done');
});

it('routes native progress events into the matching download', () => {
  const id = downloadKey('https://example.com/b.apk', 'b.apk');
  useDownloadStore.getState().start(id, 'https://example.com/b.apk', 'b.apk');
  listenForDownloadProgress();

  DeviceEventEmitter.emit('cowDownloadProgress', {id, loaded: 25, total: 100});

  expect(useDownloadStore.getState().byId[id]).toMatchObject({loaded: 25, total: 100});
});

it('does not confuse names or urls with the same prefix', () => {
  expect(downloadKey('https://a/x', 'f')).not.toBe(downloadKey('https://a', 'x/f'));
});

it('keeps one key across a token refresh', () => {
  expect(downloadKey('https://h/api/file?path=%2Fa&token=old', 'a')).toBe(
    downloadKey('https://h/api/file?path=%2Fa&token=new', 'a'),
  );
});

it('falls back to the reported size when the response has no length', () => {
  const id = downloadKey('https://h/a.bin', 'a.bin');
  useDownloadStore.getState().start(id, 'https://h/a.bin', 'a.bin', 500);
  useDownloadStore.getState().progress(id, 125, -1);
  expect(useDownloadStore.getState().byId[id]).toMatchObject({loaded: 125, total: null, expected: 500});
});

it('does not let a late event reopen a finished download', () => {
  const id = downloadKey('https://h/late.bin', 'late.bin');
  const store = useDownloadStore.getState();
  store.start(id, 'https://h/late.bin', 'late.bin');
  store.progress(id, 10, 100);
  store.finish(id);
  useDownloadStore.getState().progress(id, 20, 100);
  expect(useDownloadStore.getState().byId[id]).toMatchObject({status: 'done', loaded: 10});
});

it('forgets a download the user backed out of', () => {
  const id = downloadKey('https://h/c.pdf', 'c.pdf');
  const store = useDownloadStore.getState();
  store.start(id, 'https://h/c.pdf', 'c.pdf');
  store.clear(id);
  expect(useDownloadStore.getState().byId[id]).toBeUndefined();
});
