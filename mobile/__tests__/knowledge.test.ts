import {
  findTitle,
  flattenCategories,
  linkCandidates,
  pageFileName,
  stripDuplicateH1,
} from '../src/utils/knowledge';

const tree = {
  root_files: [{name: 'index.md', title: 'index'}],
  tree: [
    {dir: 'concepts', files: [{name: 'moe.md', title: 'MoE'}], children: []},
    {
      dir: 'platform',
      files: [],
      children: [{dir: 'analysis', files: [{name: 'perf.md', title: 'Perf'}], children: []}],
    },
    {dir: 'empty', files: [], children: []},
  ],
};

describe('flattenCategories', () => {
  it('lists nested and empty categories with subtree totals', () => {
    expect(flattenCategories(tree.tree).map(c => [c.path, c.depth, c.total])).toEqual([
      ['concepts', 0, 1],
      ['platform', 0, 1],
      ['platform/analysis', 1, 1],
      ['empty', 0, 0],
    ]);
  });
});

describe('findTitle', () => {
  it('reads titles from the tree and falls back to the stem', () => {
    expect(findTitle(tree, 'platform/analysis/perf.md')).toBe('Perf');
    expect(findTitle(tree, 'index.md')).toBe('index');
    expect(findTitle(tree, 'gone/away.md')).toBe('away');
  });
});

describe('linkCandidates', () => {
  it('tries the page-relative path before the root-relative one', () => {
    expect(linkCandidates('concepts/moe.md', '../platform/analysis/perf.md')).toEqual(['platform/analysis/perf.md']);
    expect(linkCandidates('concepts/moe.md', 'entities/deepseek.md#intro')).toEqual([
      'concepts/entities/deepseek.md',
      'entities/deepseek.md',
    ]);
    expect(linkCandidates('index.md', 'concepts/moe%20v2.md')).toEqual(['concepts/moe v2.md']);
    expect(linkCandidates('concepts/moe.md', '/knowledge/concepts/x.md')).toEqual(['concepts/x.md']);
  });

  it('ignores external links and non-markdown targets', () => {
    expect(linkCandidates('a/b.md', 'https://example.com/x.md')).toEqual([]);
    expect(linkCandidates('a/b.md', 'image.png')).toEqual([]);
    expect(linkCandidates('a/b.md', '#section')).toEqual([]);
  });
});

describe('stripDuplicateH1', () => {
  it('drops a leading H1 only when it repeats the title', () => {
    expect(stripDuplicateH1('# MoE\n\nbody', 'MoE')).toBe('body');
    expect(stripDuplicateH1('# Other\n\nbody', 'MoE')).toBe('# Other\n\nbody');
  });
});

describe('pageFileName', () => {
  it('adds .md and refuses other extensions', () => {
    expect(pageFileName(' note ')).toBe('note.md');
    expect(pageFileName('note.MD')).toBe('note.MD');
    expect(() => pageFileName('note.txt')).toThrow();
    expect(() => pageFileName('  ')).toThrow();
  });
});
