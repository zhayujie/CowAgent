import {newAgentId} from '../src/utils/agentId';

describe('newAgentId', () => {
  it('slugs the name', () => {
    expect(newAgentId('  Code Reviewer! ', [])).toBe('code-reviewer');
  });

  it('falls back to a time-based id for a name without ASCII letters or digits', () => {
    expect(newAgentId('写作助手', [], 36 ** 3)).toBe('agent-1000');
  });

  it('skips ids already taken', () => {
    expect(newAgentId('Writer', ['writer', 'writer-2'])).toBe('writer-3');
  });

  it('stays within the server id length', () => {
    const id = newAgentId(`${'a'.repeat(47)} b`, []);
    expect(id).toBe('a'.repeat(47));
    expect(id.length).toBeLessThanOrEqual(64);
  });
});
