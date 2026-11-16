import {tr, trf} from '../i18n';
import type {KnowledgeDir, KnowledgeFile, KnowledgeTree} from '../protocol/resources';

/** index.md is regenerated from the tree and log.md is the Agent's journal; the server refuses edits to both. */
export const PROTECTED_PAGES = ['index.md', 'log.md'];

export const isProtectedPage = (path: string) => PROTECTED_PAGES.includes(path);

export interface KnowledgeCategory {
  path: string;
  /** Last segment, what the list shows. */
  name: string;
  depth: number;
  files: KnowledgeFile[];
  /** Documents here and in every sub-category. */
  total: number;
}

/** Every category depth-first, empty ones included so they can still be filled. */
export function flattenCategories(tree: KnowledgeDir[] | undefined): KnowledgeCategory[] {
  const out: KnowledgeCategory[] = [];
  const walk = (nodes: KnowledgeDir[], prefix: string, depth: number): number => {
    let sum = 0;
    for (const node of nodes) {
      const path = prefix ? `${prefix}/${node.dir}` : node.dir;
      const entry: KnowledgeCategory = {path, name: node.dir, depth, files: node.files, total: 0};
      out.push(entry);
      entry.total = node.files.length + walk(node.children ?? [], path, depth + 1);
      sum += entry.total;
    }
    return sum;
  };
  walk(tree ?? [], '', 0);
  return out;
}

export const docPath = (category: string, file: KnowledgeFile) => (category ? `${category}/${file.name}` : file.name);

export const docTitle = (file: KnowledgeFile) => file.title || file.name.replace(/\.md$/i, '');

/** Title of the page at `path`, or its file stem when the tree does not have it. */
export function findTitle(tree: KnowledgeTree | null, path: string): string {
  const stem = path.split('/').pop()?.replace(/\.md$/i, '') || path;
  if (!tree) {
    return stem;
  }
  const root = tree.root_files?.find(f => f.name === path);
  if (root) {
    return docTitle(root);
  }
  for (const cat of flattenCategories(tree.tree)) {
    const hit = cat.files.find(f => docPath(cat.path, f) === path);
    if (hit) {
      return docTitle(hit);
    }
  }
  return stem;
}

function normalize(path: string): string | null {
  const parts: string[] = [];
  for (const seg of path.split('/')) {
    if (!seg || seg === '.') {
      continue;
    }
    if (seg === '..') {
      if (!parts.length) {
        return null;
      }
      parts.pop();
    } else {
      parts.push(seg);
    }
  }
  return parts.length ? parts.join('/') : null;
}

/**
 * Pages a `.md` link written in `fromPath` may name, most likely first: relative
 * to the page, then relative to the knowledge root (optionally `/` or
 * `knowledge/` prefixed). The same forms the server's graph builder accepts.
 * Empty for anything that is not a knowledge link.
 */
export function linkCandidates(fromPath: string, href: string): string[] {
  if (/^[a-z][a-z0-9+.-]*:/i.test(href) || href.startsWith('#')) {
    return [];
  }
  let target = href.split('#')[0].split('?')[0].replace(/\\/g, '/').trim();
  try {
    target = decodeURIComponent(target);
  } catch {
    // Kept as written; a stray % is still a valid file name.
  }
  if (!/\.md$/i.test(target)) {
    return [];
  }
  const out: string[] = [];
  const push = (p: string | null) => p && !out.includes(p) && out.push(p);
  if (!target.startsWith('/')) {
    const dir = fromPath.includes('/') ? fromPath.slice(0, fromPath.lastIndexOf('/')) : '';
    push(normalize(dir ? `${dir}/${target}` : target));
  }
  push(normalize(target.replace(/^\/+/, '').replace(/^knowledge\//, '')));
  return out;
}

/** The page header already shows the title, so a leading H1 repeating it is dropped from the body. */
export function stripDuplicateH1(content: string, title: string): string {
  const m = content.match(/^\s*#\s+(.+?)\s*(?:\r?\n|$)/);
  if (!m || m[1].trim().toLowerCase() !== title.trim().toLowerCase()) {
    return content;
  }
  return content.slice(m[0].length).replace(/^\s*\r?\n/, '');
}

export function docTemplate(name: string): string {
  const title = name.replace(/\.md$/i, '') || tr('common_untitled');
  return trf('knowledge_doc_template', {title});
}

/** A file name for a new page: `.md` added when missing, anything else refused. */
export function pageFileName(input: string): string {
  const name = input.trim().replace(/[\\/]/g, '-');
  if (!name) {
    throw new Error(tr('knowledge_filename_required'));
  }
  if (/\.[^.]+$/.test(name) && !/\.md$/i.test(name)) {
    throw new Error(tr('knowledge_md_only'));
  }
  return /\.md$/i.test(name) ? name : `${name}.md`;
}

export const isImportable = (name: string) => /\.(md|txt)$/i.test(name);
