import hljs from 'highlight.js/lib/core';
import bash from 'highlight.js/lib/languages/bash';
import c from 'highlight.js/lib/languages/c';
import cpp from 'highlight.js/lib/languages/cpp';
import css from 'highlight.js/lib/languages/css';
import diff from 'highlight.js/lib/languages/diff';
import go from 'highlight.js/lib/languages/go';
import ini from 'highlight.js/lib/languages/ini';
import java from 'highlight.js/lib/languages/java';
import javascript from 'highlight.js/lib/languages/javascript';
import json from 'highlight.js/lib/languages/json';
import kotlin from 'highlight.js/lib/languages/kotlin';
import markdown from 'highlight.js/lib/languages/markdown';
import php from 'highlight.js/lib/languages/php';
import python from 'highlight.js/lib/languages/python';
import ruby from 'highlight.js/lib/languages/ruby';
import rust from 'highlight.js/lib/languages/rust';
import shell from 'highlight.js/lib/languages/shell';
import sql from 'highlight.js/lib/languages/sql';
import swift from 'highlight.js/lib/languages/swift';
import typescript from 'highlight.js/lib/languages/typescript';
import xml from 'highlight.js/lib/languages/xml';
import yaml from 'highlight.js/lib/languages/yaml';

const LANGUAGES = {
  bash, c, cpp, css, diff, go, ini, java, javascript, json, kotlin, markdown,
  php, python, ruby, rust, shell, sql, swift, typescript, xml, yaml,
};
Object.entries(LANGUAGES).forEach(([name, lang]) => hljs.registerLanguage(name, lang));

/** File extensions hljs does not already know as aliases. */
const EXT_LANG: Record<string, string> = {
  htm: 'xml',
  html: 'xml',
  svg: 'xml',
  vue: 'xml',
  toml: 'ini',
  conf: 'ini',
  yml: 'yaml',
  mjs: 'javascript',
  cjs: 'javascript',
  zsh: 'bash',
};

/** The hljs language for a fence tag or a file name, if one is registered. */
export function languageOf(tagOrName: string | undefined): string | undefined {
  if (!tagOrName) {
    return undefined;
  }
  const key = tagOrName.trim().toLowerCase().split(/\s+/)[0];
  const ext = key.includes('.') ? key.split('.').pop() ?? '' : key;
  const lang = EXT_LANG[ext] ?? ext;
  return hljs.getLanguage(lang) ? lang : undefined;
}

export interface CodeToken {
  text: string;
  /** Innermost hljs scope, e.g. `keyword`, `title`, `string`. */
  scope?: string;
}

/** Highlighting a huge file would freeze the JS thread; past this (cut at a line) the rest stays plain. */
const MAX_HIGHLIGHT = 60_000;
/** Guessing the language runs every grammar, so only short snippets get a guess. */
const MAX_AUTO_DETECT = 4_000;

const ENTITIES: Record<string, string> = {'&amp;': '&', '&lt;': '<', '&gt;': '>', '&quot;': '"', '&#x27;': "'", '&#39;': "'"};
const decode = (s: string) => s.replace(/&(?:amp|lt|gt|quot|#x27|#39);/g, m => ENTITIES[m]);

export function highlightCode(code: string, lang?: string): CodeToken[] {
  if (code.length > MAX_HIGHLIGHT) {
    const cut = code.lastIndexOf('\n', MAX_HIGHLIGHT);
    if (cut <= 0) {
      return [{text: code}];
    }
    return [...highlightCode(code.slice(0, cut), lang), {text: code.slice(cut)}];
  }
  if (!code) {
    return [{text: code}];
  }
  let html: string;
  try {
    if (lang && hljs.getLanguage(lang)) {
      html = hljs.highlight(code, {language: lang, ignoreIllegals: true}).value;
    } else if (code.length <= MAX_AUTO_DETECT) {
      html = hljs.highlightAuto(code).value;
    } else {
      return [{text: code}];
    }
  } catch {
    return [{text: code}];
  }
  const tokens: CodeToken[] = [];
  const scopes: (string | undefined)[] = [];
  const re = /<span class="([^"]*)">|<\/span>|[^<]+/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(html))) {
    if (m[1] !== undefined) {
      const scope = /hljs-([\w-]+)/.exec(m[1])?.[1];
      scopes.push(scope ?? scopes[scopes.length - 1]);
    } else if (m[0] === '</span>') {
      scopes.pop();
    } else {
      tokens.push({text: decode(m[0]), scope: scopes[scopes.length - 1]});
    }
  }
  return tokens;
}

type Theme = {base: string; scopes: Record<string, string>};

function theme(p: {
  base: string;
  keyword: string;
  title: string;
  constant: string;
  string: string;
  builtIn: string;
  comment: string;
  tag: string;
  section: string;
  bullet: string;
  addition: string;
  deletion: string;
}): Theme {
  const scopes: Record<string, string> = {};
  const set = (color: string, names: string) => names.split(' ').forEach(n => (scopes[n] = color));
  set(p.keyword, 'doctag keyword template-tag template-variable type');
  set(p.title, 'title');
  set(p.constant, 'attr attribute literal meta number operator selector-attr selector-class selector-id variable');
  set(p.string, 'string regexp');
  set(p.builtIn, 'built_in symbol');
  set(p.comment, 'code comment formula');
  set(p.tag, 'name quote selector-pseudo selector-tag');
  set(p.section, 'section');
  set(p.bullet, 'bullet');
  set(p.addition, 'addition');
  set(p.deletion, 'deletion');
  return {base: p.base, scopes};
}

/** GitHub's light and dark syntax colours, as the web console uses. */
export const CODE_THEMES = {
  light: theme({
    base: '#24292e',
    keyword: '#d73a49',
    title: '#6f42c1',
    constant: '#005cc5',
    string: '#032f62',
    builtIn: '#e36209',
    comment: '#6a737d',
    tag: '#22863a',
    section: '#005cc5',
    bullet: '#735c0f',
    addition: '#22863a',
    deletion: '#b31d28',
  }),
  dark: theme({
    base: '#c9d1d9',
    keyword: '#ff7b72',
    title: '#d2a8ff',
    constant: '#79c0ff',
    string: '#a5d6ff',
    builtIn: '#ffa657',
    comment: '#8b949e',
    tag: '#7ee787',
    section: '#1f6feb',
    bullet: '#f2cc60',
    addition: '#aff5b4',
    deletion: '#ffdcd7',
  }),
};
