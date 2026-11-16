import type {Skill} from '../src/protocol/resources';
import {kvToObject, mcpServersToJson, objectToKv, parseMcpJson} from '../src/utils/mcp';
import {codeFence, compareSkills, parseFrontmatter, skillFileForReading, skillRefusal} from '../src/utils/skills';

describe('parseFrontmatter', () => {
  it('flattens nested maps into dotted keys and joins lists', () => {
    const md = [
      '---',
      'name: weather',
      'description: "Look up the weather"',
      'metadata:',
      '  cowagent:',
      '    requires:',
      '      anyEnv:',
      '        - KEY_A',
      '        - KEY_B',
      '---',
      '# Body',
    ].join('\n');
    const {fields, body} = parseFrontmatter(md);
    expect(fields).toEqual([
      ['name', 'weather'],
      ['description', 'Look up the weather'],
      ['metadata.cowagent.requires.anyEnv', 'KEY_A, KEY_B'],
    ]);
    expect(body).toBe('# Body');
  });

  it('joins block scalars and leaves text without a header alone', () => {
    const {fields} = parseFrontmatter('---\ndescription: |\n  line one\n  line two\n---\n');
    expect(fields).toEqual([['description', 'line one line two']]);
    expect(parseFrontmatter('# Just text')).toEqual({fields: [], body: '# Just text'});
  });
});

describe('skillFileForReading', () => {
  it('lifts the frontmatter of a markdown file into a table', () => {
    const out = skillFileForReading('SKILL.md', '---\nname: a|b\n---\nHello');
    expect(out).toContain('| `name` | a\\|b |');
    expect(out.endsWith('Hello')).toBe(true);
  });

  it('fences other files with a fence longer than any run inside', () => {
    expect(codeFence('scripts/run.py', 'print(1)')).toBe('```py\nprint(1)\n```');
    expect(codeFence('LICENSE', 'a ```` b').startsWith('`````\n')).toBe(true);
  });
});

describe('compareSkills', () => {
  const skill = (name: string, extra: Partial<Skill> = {}): Skill => ({name, enabled: true, ...extra});

  it('puts built-in skills first in their fixed order, then the newest', () => {
    const list = [
      skill('old', {installed_at: 1}),
      skill('knowledge-wiki', {ships_with_install: true}),
      skill('new', {installed_at: 9}),
      skill('skill-creator', {ships_with_install: true}),
    ];
    expect(list.sort(compareSkills).map(s => s.name)).toEqual(['skill-creator', 'knowledge-wiki', 'new', 'old']);
  });
});

describe('skillRefusal', () => {
  it('words the refusals a person can act on', () => {
    expect(skillRefusal('skill already exists: weather')).toBe('已有同名技能');
    expect(skillRefusal('something unexpected')).toBeNull();
  });
});

describe('mcp config', () => {
  it('reads the mcpServers file format and fills the transport', () => {
    const servers = parseMcpJson('{"mcpServers": {"fetch": {"command": "uvx", "args": ["mcp-server-fetch"]}, "remote": {"serverUrl": "https://x.dev/mcp"}}}');
    expect(servers).toEqual([
      {name: 'fetch', command: 'uvx', args: ['mcp-server-fetch'], type: 'stdio'},
      {name: 'remote', url: 'https://x.dev/mcp', type: 'sse'},
    ]);
  });

  it('needs a name on a single bare config and rejects bad JSON', () => {
    expect(() => parseMcpJson('{"command": "npx"}')).toThrow();
    expect(() => parseMcpJson('{oops')).toThrow();
    expect(parseMcpJson('{"name": "one", "command": "npx"}')[0].name).toBe('one');
  });

  it('round-trips through JSON without names, status or empty values', () => {
    const json = mcpServersToJson([{name: 'fs', type: 'stdio', command: 'npx', args: [], env: {}, status: 'ready'}]);
    expect(JSON.parse(json)).toEqual({mcpServers: {fs: {command: 'npx'}}});
  });

  it('converts KEY=value lines both ways', () => {
    expect(kvToObject('A=1\n  B = two=2 \n=skip\nnoeq')).toEqual({A: '1', B: ' two=2'});
    expect(objectToKv({A: '1', B: '2'})).toBe('A=1\nB=2');
  });
});
