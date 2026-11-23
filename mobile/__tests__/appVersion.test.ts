// The app has no @types/node; declare the little this test uses.
declare const __dirname: string;
const {readFileSync}: {readFileSync(file: string, encoding: 'utf8'): string} = require('fs');
const {join}: {join(...parts: string[]): string} = require('path');

const root = join(__dirname, '..');
export {};

it('gives the iOS app the version Android reads from package.json', () => {
  const {version} = JSON.parse(readFileSync(join(root, 'package.json'), 'utf8'));
  const project = readFileSync(join(root, 'ios/CowAgentMobile.xcodeproj/project.pbxproj'), 'utf8');
  const ios = [...project.matchAll(/MARKETING_VERSION = ([^;]+);/g)].map(m => m[1]);
  expect(ios.length).toBeGreaterThan(0);
  expect(new Set(ios)).toEqual(new Set([version]));
});
