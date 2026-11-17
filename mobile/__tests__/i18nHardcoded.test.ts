// The app has no @types/node; declare the little this test uses.
declare const __dirname: string;
const fs: {
  readdirSync(dir: string, opts: {withFileTypes: true}): {name: string; isDirectory(): boolean}[];
  readFileSync(file: string, encoding: 'utf8'): string;
} = require('fs');
const path: {
  join(...parts: string[]): string;
  relative(from: string, to: string): string;
  sep: string;
} = require('path');

const SRC = path.join(__dirname, '..', 'src');

/** Chinese that must stay as is: language names, and markers or release text the server sends. */
const ALLOWED: Record<string, string[]> = {
  'screens/SettingsScreen.tsx': ['简体中文'],
  'screens/LoginScreen.tsx': ['中文'],
  'utils/guestShares.ts': ['简体中文', '繁體中文'],
  'screens/VersionScreen.tsx': ['中文'],
  'store/chatStore.ts': [
    '工作空间文件', '工作空间檔案', '工作空间目录', '工作空间目錄',
    '图片', '圖片', '视频', '影片', '目录', '目錄', '文件', '檔案',
  ],
};

function sourceFiles(dir: string): string[] {
  return fs.readdirSync(dir, {withFileTypes: true}).flatMap(entry => {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      return entry.name === 'i18n' ? [] : sourceFiles(full);
    }
    return /\.tsx?$/.test(entry.name) ? [full] : [];
  });
}

/** Blank out comments but keep their newlines, so reported line numbers stay right. */
const stripComments = (code: string) =>
  code.replace(/\/\*[\s\S]*?\*\//g, m => m.replace(/[^\n]/g, '')).replace(/(^|\s)\/\/.*$/gm, '$1');

it('keeps user-facing copy in src/i18n', () => {
  const offenders: string[] = [];
  for (const file of sourceFiles(SRC)) {
    const rel = path.relative(SRC, file).split(path.sep).join('/');
    const allowed = ALLOWED[rel] ?? [];
    stripComments(fs.readFileSync(file, 'utf8'))
      .split('\n')
      .forEach((line, i) => {
        const rest = allowed.reduce((s, word) => s.split(word).join(''), line);
        if (/\p{Script=Han}/u.test(rest)) {
          offenders.push(`${rel}:${i + 1}: ${line.trim()}`);
        }
      });
  }
  expect(offenders).toEqual([]);
});
