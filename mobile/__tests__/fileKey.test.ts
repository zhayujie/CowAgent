import {fileKeyOf} from '../src/files/chatFile';

const file = (rawUrl: string, extra: {name?: string; size?: number; relPath?: string} = {}) => ({
  name: extra.name ?? '报告.docx',
  kind: 'office',
  rawUrl,
  size: extra.size ?? 12000,
  relPath: extra.relPath,
});

const served = (host: string, version: string, token: string, path = '/cow/out/报告.docx') =>
  `http://${host}/api/file?path=${encodeURIComponent(path)}&v=${version}&token=${token}`;

it('ignores the rotating login token and the address the probe settled on', () => {
  const a = fileKeyOf(file(served('192.168.1.9:8080', '1763800000', 'aaa')));
  const b = fileKeyOf(file(served('tunnel.example.com', '1763800000', 'bbb')));
  expect(a).toBe(b);
});

it('separates the same path downloaded under another name', () => {
  const a = fileKeyOf(file(served('h', '1', 't'), {relPath: 'out/a.docx'}));
  const b = fileKeyOf(file(served('h', '1', 't'), {relPath: 'out/b.docx'}));
  expect(a).not.toBe(b);
});

it('treats a regenerated file as a different download', () => {
  const before = fileKeyOf(file(served('h', '1763800000', 't')));
  const after = fileKeyOf(file(served('h', '1763800001', 't')));
  expect(before).not.toBe(after);
});

it('falls back to the URL itself for a link that carries no path', () => {
  expect(fileKeyOf(file('https://example.com/f/a.docx?token=aaa'))).toBe(
    fileKeyOf(file('https://example.com/f/a.docx?token=bbb')),
  );
});
