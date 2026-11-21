import {matchMention, matchSlash} from '../src/utils/composerCommands';

describe('matchSlash', () => {
  it('lists every command for a bare slash', () => {
    expect(matchSlash('/').length).toBeGreaterThan(10);
  });

  it('filters by prefix, case-insensitively', () => {
    expect(matchSlash('/SKILL L').map(c => c.cmd)).toEqual(['/skill list', '/skill list --remote']);
  });

  it('closes once the text is a finished command', () => {
    expect(matchSlash('/help')).toEqual([]);
    expect(matchSlash('/skill search ')).toEqual([]);
  });

  it('ignores prose and multi-line text', () => {
    expect(matchSlash('hello /help')).toEqual([]);
    expect(matchSlash('/he\nllo')).toEqual([]);
  });
});

describe('matchMention', () => {
  it('triggers at the start or after whitespace', () => {
    expect(matchMention('@rep', 4)).toEqual({start: 0, query: 'rep'});
    expect(matchMention('look at @', 9)).toEqual({start: 8, query: ''});
  });

  it('does not trigger inside a word such as an email', () => {
    expect(matchMention('me@example', 10)).toBeNull();
  });

  it('only looks before the cursor', () => {
    expect(matchMention('@abc tail', 4)).toEqual({start: 0, query: 'abc'});
    expect(matchMention('@abc tail', 9)).toBeNull();
  });
});
