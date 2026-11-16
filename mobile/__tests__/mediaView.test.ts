import {pdfPage} from '../src/components/MediaView';

jest.mock('react-native-webview', () => ({WebView: 'WebView'}));
jest.mock('@react-native-async-storage/async-storage', () =>
  require('@react-native-async-storage/async-storage/jest/async-storage-mock'),
);

describe('pdfPage', () => {
  const page = pdfPage('https://cow.example.com/api/file?path=%2Fa.pdf&token=t');

  it('loads pdf.js only with pinned hashes', () => {
    const tags = page.match(/<script\b[^>]*\bsrc=/g) ?? [];
    expect(tags).toEqual([]);
    expect(page).toContain("s.integrity=sri;s.crossOrigin='anonymous'");
    expect(page.match(/"sri":"sha384-[A-Za-z0-9+/=]{64}"/g)).toHaveLength(2);
  });

  it('keeps eval off and the server address out of CDN requests', () => {
    expect(page).toContain('isEvalSupported:false');
    expect(page).toContain('<meta name="referrer" content="no-referrer">');
  });

  it('cannot be broken out of by the file address', () => {
    const evil = pdfPage('https://h/api/file?path=</script><script>alert(1)</script>');
    expect(evil).not.toContain('</script><script>alert(1)');
  });
});
