import {markdownText} from '../src/utils/markdownText';

it('drops the markup and keeps what reads', () => {
  const md = [
    '# Title',
    '',
    'Some **bold**, _italic_, ~~gone~~ and `code` with a [link](https://a.b) & <b>tag</b>.',
    '',
    '> quoted',
  ].join('\n');
  expect(markdownText(md)).toBe('Title\n\nSome bold, italic, gone and code with a link & tag.\n\nquoted');
});

it('keeps list markers, nesting and code as written', () => {
  const md = ['1. one', '2. two', '   - inner', '', '```ts', 'const a = 1 < 2;', '```'].join('\n');
  expect(markdownText(md)).toBe('1. one\n2. two\n   • inner\n\nconst a = 1 < 2;');
});

it('lays a table out one row per line', () => {
  const md = ['| a | b |', '| - | - |', '| 1 | **2** |'].join('\n');
  expect(markdownText(md)).toBe('a\tb\n1\t2');
});

it('keeps snake_case words and plain text untouched', () => {
  expect(markdownText('run file_name_here now\nnext line')).toBe('run file_name_here now\nnext line');
});
