import {
  codeFilePath,
  fileFromImageRef,
  isUnsandboxedPage,
  serverFileRef,
  splitFilePaths,
} from '../src/files/chatFile';

describe('splitFilePaths', () => {
  it('cuts out absolute, home and workspace-relative paths', () => {
    expect(splitFilePaths('网页：C:\\Users\\me\\cow\\websites\\a-v3.html，长图在 websites/a.png')).toEqual([
      '网页：',
      {path: 'C:\\Users\\me\\cow\\websites\\a-v3.html'},
      '，长图在 ',
      {path: 'websites/a.png'},
    ]);
    expect(splitFilePaths('see ~/cow/报告.md')).toEqual(['see ', {path: '~/cow/报告.md'}]);
  });

  it('leaves prose, bare names and URLs alone', () => {
    expect(splitFilePaths('打开 report.html 看看')).toBeNull();
    expect(splitFilePaths('https://example.com/docs/page.html')).toBeNull();
    expect(splitFilePaths('版本 v1.2 发布了')).toBeNull();
  });
});

describe('codeFilePath', () => {
  it('only matches code that is a path and nothing else', () => {
    expect(codeFilePath('websites/a.html')).toBe('websites/a.html');
    expect(codeFilePath('cat websites/a.html')).toBeNull();
    expect(codeFilePath('websites/')).toBeNull();
  });
});

describe('serverFileRef', () => {
  it('routes server files and keeps web links out', () => {
    expect(serverFileRef('/api/file?path=C%3A%5Cx%5Ca.png&token=t')).toBe('C:\\x\\a.png');
    expect(serverFileRef('knowledge/x.md')).toBe('knowledge/x.md');
    expect(serverFileRef('https://example.com/a.md')).toBeNull();
    expect(serverFileRef('#top')).toBeNull();
    expect(serverFileRef('docs/page')).toBeNull();
  });

  it('ignores a malformed file:// link instead of throwing', () => {
    expect(serverFileRef('file:///%E0%A4%A')).toBeNull();
    expect(serverFileRef('file:///C:/x/a.md')).toBe('C:/x/a.md');
  });
});

describe('isUnsandboxedPage', () => {
  it('flags server HTML until it has a signed preview', () => {
    expect(isUnsandboxedPage({name: 'a.html', kind: 'html', path: '/w/a.html'})).toBe(true);
    expect(isUnsandboxedPage({name: 'a.html', kind: 'html', rawUrl: '/api/file?path=%2Fw%2Fa.html'})).toBe(true);
    expect(isUnsandboxedPage({name: 'a.html', kind: 'html', path: '/w/a.html', previewUrl: '/preview/t/a.html'})).toBe(
      false,
    );
    expect(isUnsandboxedPage({name: 'a.html', kind: 'html', rawUrl: 'https://example.com/a.html'})).toBe(false);
    expect(isUnsandboxedPage({name: 'a.md', kind: 'markdown', path: '/w/a.md'})).toBe(false);
  });
});

describe('fileFromImageRef', () => {
  it('does not fetch a workspace-relative source', () => {
    expect(fileFromImageRef('websites/chart.png').rawUrl).toBeUndefined();
    expect(fileFromImageRef('/w/chart.png').path).toBe('/w/chart.png');
    expect(fileFromImageRef('https://x.com/a.png').rawUrl).toBe('https://x.com/a.png');
  });
});
