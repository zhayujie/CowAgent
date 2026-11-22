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
