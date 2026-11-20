import {tr, type MessageKey} from '../i18n';
import type {Skill} from '../protocol/resources';

/** Built-in skills, in the order they lead the list. */
export const BUILTIN_SKILLS = ['skill-creator', 'knowledge-wiki', 'image-generation'] as const;

export const SKILL_SOURCE_LABEL: Record<string, string> = {
  get builtin() {
    return tr('skill_src_builtin');
  },
  get custom() {
    return tr('skill_src_custom');
  },
  get local() {
    return tr('skill_src_local');
  },
  get linkai() {
    return tr('skill_src_market');
  },
  get market() {
    return tr('skill_src_market');
  },
  cowhub: 'Cow Skill Hub',
  hub: 'Cow Skill Hub',
  github: 'GitHub',
  clawhub: 'ClawHub',
  get url() {
    return tr('skill_src_url');
  },
};

export function skillName(s: Pick<Skill, 'name' | 'display_name'>): string {
  return s.display_name || s.name;
}

export function skillDescription(s: Pick<Skill, 'description' | 'display_description'>): string {
  return s.display_description || s.description || '';
}

/** The server's refusals are fixed English phrases; these are the ones a person can act on. */
export function skillRefusal(message: string): string | null {
  const rules: [RegExp, MessageKey][] = [
    [/no skills found/i, 'skill_err_no_skills'],
    [/latin letters or digits/i, 'skill_err_latin_name'],
    [/already exists/i, 'skill_err_exists'],
    [/description is required/i, 'skill_err_desc_required'],
    [/invalid skill name/i, 'skill_err_invalid_name'],
    [/invalid ClawHub/i, 'skill_err_invalid_clawhub'],
    [/GitHub URL or owner\/repo/i, 'skill_err_github_url'],
    [/too large/i, 'skill_err_too_large'],
    [/preview expired/i, 'skill_err_preview_expired'],
    [/cannot be deleted|read-only/i, 'skill_err_readonly'],
    [/not found/i, 'skill_err_not_found'],
  ];
  const key = rules.find(([re]) => re.test(message))?.[1];
  return key ? tr(key) : null;
}

function builtinRank(s: Skill): number {
  if (!s.ships_with_install) {
    return -1;
  }
  const i = (BUILTIN_SKILLS as readonly string[]).indexOf(s.name);
  return i < 0 ? BUILTIN_SKILLS.length : i;
}

/** Built-in skills first in a fixed order, then the rest newest first, so an install lands on top. */
export function compareSkills(a: Skill, b: Skill): number {
  const ra = builtinRank(a);
  const rb = builtinRank(b);
  if (ra >= 0 || rb >= 0) {
    if (ra < 0) {
      return 1;
    }
    if (rb < 0) {
      return -1;
    }
    return ra - rb;
  }
  return (b.installed_at || 0) - (a.installed_at || 0);
}

function yamlScalar(raw: string): string {
  return raw.trim().replace(/^(['"])(.*)\1$/, '$2');
}

/**
 * Splits a SKILL.md into its YAML frontmatter fields and the markdown body.
 *
 * Nested maps become one row per leaf keyed by its dotted path; a list or a block
 * scalar becomes one row with its lines joined. Only leaves are rows.
 */
export function parseFrontmatter(content: string): {fields: [string, string][]; body: string} {
  const text = content || '';
  const match = text.match(/^---\s*\r?\n([\s\S]*?)\r?\n---\s*\r?\n?/);
  if (!match) {
    return {fields: [], body: text};
  }
  const fields: [string, string][] = [];
  const path: {indent: number; key: string}[] = [];
  let open: {key: string; indent: number; items: string[]; block: boolean} | null = null;

  const flush = () => {
    if (open) {
      fields.push([open.key, open.block ? open.items.join(' ').trim() : open.items.join(', ')]);
      open = null;
    }
  };

  for (const raw of match[1].split(/\r?\n/)) {
    const line = raw.trim();
    if (!line) {
      continue;
    }
    const indent = raw.length - raw.trimStart().length;
    if (open && open.block && indent > open.indent) {
      open.items.push(line);
      continue;
    }
    if (line.startsWith('#')) {
      continue;
    }
    if (open && !open.block && indent >= open.indent && line.startsWith('- ')) {
      open.items.push(yamlScalar(line.slice(2)));
      continue;
    }
    flush();
    while (path.length && path[path.length - 1].indent >= indent) {
      path.pop();
    }
    const idx = line.indexOf(':');
    if (idx === -1) {
      continue;
    }
    const key = yamlScalar(line.slice(0, idx));
    if (!key) {
      continue;
    }
    const dotted = [...path.map(p => p.key), key].join('.');
    const rest = line.slice(idx + 1).trim();
    if (!rest) {
      path.push({indent, key});
      open = {key: dotted, indent, items: [], block: false};
    } else if (/^[|>][-+0-9]*$/.test(rest)) {
      open = {key: dotted, indent, items: [], block: true};
    } else {
      fields.push([dotted, yamlScalar(rest)]);
    }
  }
  flush();
  return {fields: fields.filter(([, v]) => v !== ''), body: text.slice(match[0].length)};
}

/** A fence longer than any run of backticks inside, so a code sample in the file cannot end it early. */
export function codeFence(path: string, content: string): string {
  const filename = path.split('/').pop() || '';
  const lang = filename.includes('.') ? (filename.split('.').pop() || '').toLowerCase() : '';
  const longest = (content.match(/`+/g) || []).reduce((n, run) => Math.max(n, run.length), 2);
  const fence = '`'.repeat(longest + 1);
  return `${fence}${lang}\n${content}\n${fence}`;
}

const escapeCell = (s: string) => s.replace(/\|/g, '\\|').replace(/\r?\n/g, ' ');

/**
 * How a skill file reads: markdown as prose with the frontmatter lifted into a table
 * (rendered raw, the `---` block becomes a giant heading), anything else as code.
 */
export function skillFileForReading(path: string, content: string): string {
  if (!/\.(md|markdown)$/i.test(path)) {
    return codeFence(path, content);
  }
  const {fields, body} = parseFrontmatter(content);
  if (!fields.length) {
    return body;
  }
  const table = [
    `| ${tr('skill_fm_field')} | ${tr('skill_fm_value')} |`,
    '| --- | --- |',
    ...fields.map(([k, v]) => `| \`${escapeCell(k)}\` | ${escapeCell(v)} |`),
  ];
  return `${table.join('\n')}\n\n${body}`;
}
