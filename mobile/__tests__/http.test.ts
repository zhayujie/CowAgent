import {isPublicCleartext, normalizeBaseUrl} from '../src/api/http';

test('normalizeBaseUrl defaults to https and strips trailing slashes', () => {
  expect(normalizeBaseUrl(' cow.example.com/ ')).toBe('https://cow.example.com');
  expect(normalizeBaseUrl('http://10.0.0.2:9899//')).toBe('http://10.0.0.2:9899');
});

test('isPublicCleartext flags plain http only off the local network', () => {
  for (const url of ['http://cow.example.com', 'http://8.8.8.8:9899', 'HTTP://Cow.Example.com/', 'http://[2001:db8::1]:9899']) {
    expect(isPublicCleartext(url)).toBe(true);
  }
  for (const url of [
    'https://cow.example.com',
    'cow.example.com',
    'http://192.168.1.10:9899',
    'http://10.0.0.2',
    'http://172.20.3.4',
    'http://127.0.0.1:9899',
    'http://100.101.1.2',
    'http://localhost:9899',
    'http://my-pc:9899',
    'http://nas.local',
    'http://[::1]:9899',
    'http://[fd12:3456::1]',
  ]) {
    expect(isPublicCleartext(url)).toBe(false);
  }
  expect(isPublicCleartext('http://172.32.0.1')).toBe(true);
});
