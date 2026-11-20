import {highlightCode, languageOf} from '../src/utils/highlight';

describe('languageOf', () => {
  it('resolves fence tags and file names', () => {
    expect(languageOf('py')).toBeDefined();
    expect(languageOf('main.py')).toBeDefined();
    expect(languageOf('report.html')).toBe('xml');
    expect(languageOf('config.yml')).toBe('yaml');
    expect(languageOf('notes.unknownext')).toBeUndefined();
    expect(languageOf(undefined)).toBeUndefined();
  });
});

describe('highlightCode', () => {
  it('keeps the source text intact and tags tokens with scopes', () => {
    const code = 'def f(x):\n    return "a<b" # done';
    const tokens = highlightCode(code, 'python');
    expect(tokens.map(t => t.text).join('')).toBe(code);
    expect(tokens.find(t => t.text === 'def')?.scope).toBe('keyword');
    expect(tokens.find(t => t.text.includes('"a<b"'))?.scope).toBe('string');
    expect(tokens.find(t => t.text.includes('# done'))?.scope).toBe('comment');
  });

  it('highlights the head of a huge file and leaves the tail plain', () => {
    const line = 'const answer = 42;\n';
    const code = line.repeat(5000);
    const tokens = highlightCode(code, 'javascript');
    expect(tokens.map(t => t.text).join('')).toBe(code);
    expect(tokens[0].scope).toBe('keyword');
    expect(tokens[tokens.length - 1].scope).toBeUndefined();
    expect(tokens[tokens.length - 1].text.length).toBeGreaterThan(1000);
  });

  it('leaves unknown languages plain', () => {
    const tokens = highlightCode('just some words', 'nope');
    expect(tokens.map(t => t.text).join('')).toBe('just some words');
  });
});
