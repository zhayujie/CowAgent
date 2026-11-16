import {authedUrl, resolveWorkspacePath, serverFileUrl, serverUrl} from '../api/cowApi';
import {tr, trf} from '../i18n';
import type {FilePayload, StreamEvent} from '../protocol/events';
import {FILE_EXTENSIONS, kindFromName} from '../utils/format';

/** A file a reply wrote or sent, however the server first described it. */
export interface ChatFile {
  name: string;
  /** Artifact kind: image, video, audio, html, markdown, pdf, office, text, csv, code, file. */
  kind: string;
  /** Absolute path on the server's disk, when the file lives there. */
  path?: string;
  /** Workspace-relative path, when it differs from the name. */
  relPath?: string;
  size?: number;
  /** The bytes: `/api/file?…` (behind auth) or a remote URL. */
  rawUrl?: string;
  /** HMAC-signed `/preview/…`; relative assets of an HTML page resolve against it. */
  previewUrl?: string;
}

const baseName = (path: string) => path.split(/[\\/]/).filter(Boolean).pop() || path;

export function fileFromPayload(p: FilePayload | null | undefined): ChatFile | null {
  if (!p) {
    return null;
  }
  const path = p.abs_path || undefined;
  const name = p.file_name || (path ? baseName(path) : '') || p.rel_path || '';
  if (!name) {
    return null;
  }
  return {
    name,
    kind: p.kind || kindFromName(name),
    path,
    relPath: p.rel_path && p.rel_path !== name ? p.rel_path : undefined,
    size: p.size || undefined,
    rawUrl: p.raw_url || undefined,
    previewUrl: p.preview_url || undefined,
  };
}

/** The file a live `image` / `file` / `video` / `artifact` event announced. */
export function fileFromEvent(e: StreamEvent): ChatFile | null {
  if (e.type === 'artifact') {
    return fileFromPayload(e);
  }
  const url = e.content || e.raw_url || '';
  const name = e.file_name || (e.abs_path ? baseName(e.abs_path) : url ? baseName(url.split('?')[0]) : '');
  if (!name) {
    return null;
  }
  const media = e.type === 'image' ? 'image' : e.file_type === 'image' || e.file_type === 'video' ? e.file_type : '';
  return {
    name,
    kind: media || e.kind || kindFromName(name),
    path: e.abs_path || undefined,
    relPath: e.rel_path && e.rel_path !== name ? e.rel_path : undefined,
    size: e.size || undefined,
    rawUrl: url || undefined,
    previewUrl: e.preview_url || undefined,
  };
}

/** What a `send` tool call delivered, read back from its result. */
export function fileFromSendResult(result: string | undefined): ChatFile | null {
  if (!result || !result.trimStart().startsWith('{')) {
    return null;
  }
  try {
    const p = JSON.parse(result) as {
      type?: string;
      path?: string;
      url?: string;
      file_name?: string;
      file_type?: string;
      size?: number;
    };
    if (p?.type !== 'file_to_send' || !(p.path || p.url)) {
      return null;
    }
    const remote = p.url && /^https?:\/\//i.test(p.url) ? p.url : undefined;
    const name = p.file_name || baseName((p.path || remote || '').split('?')[0]);
    const media = p.file_type === 'image' || p.file_type === 'video' ? p.file_type : '';
    return {
      name,
      kind: media || kindFromName(name),
      path: remote ? undefined : p.path,
      size: p.size || undefined,
      rawUrl: remote,
    };
  } catch {
    return null;
  }
}

/** Same file, by where it sits; names alone collide across folders. */
export const sameFile = (a: ChatFile, b: ChatFile) =>
  a.path && b.path ? a.path === b.path : a.name === b.name && (a.rawUrl ?? '') === (b.rawUrl ?? '');

/** A later report of the same file fills in what the earlier one lacked. */
export function mergeFile(a: ChatFile, b: ChatFile): ChatFile {
  const out: ChatFile = {...a};
  (Object.keys(b) as (keyof ChatFile)[]).forEach(k => {
    if (b[k] !== undefined) {
      (out as unknown as Record<string, unknown>)[k] = b[k];
    }
  });
  return out;
}

/** The bytes, fetchable by an image view or the system browser. */
export function rawUrlOf(f: ChatFile): string {
  if (f.rawUrl) {
    if (/^(https?:|data:|blob:)/i.test(f.rawUrl)) {
      return f.rawUrl;
    }
    return f.rawUrl.startsWith('/api/') ? authedUrl(f.rawUrl) : serverUrl(f.rawUrl);
  }
  return f.path ? serverFileUrl(f.path) : '';
}

/**
 * A page from the server's disk that has no sandboxed `/preview/` link yet.
 * Rendered from `/api/file` its scripts could read the login token in the URL.
 */
export const isUnsandboxedPage = (f: ChatFile) =>
  f.kind === 'html' && !f.previewUrl && !/^https?:\/\//i.test(f.rawUrl ?? '');

/** A link that opens without the app: the signed preview when there is one. */
export function viewUrlOf(f: ChatFile): string {
  if (f.previewUrl) {
    return serverUrl(f.previewUrl);
  }
  return isUnsandboxedPage(f) ? '' : rawUrlOf(f);
}

/** What a failed file request means to the reader. */
export function fileHttpError(status: number): string {
  if (status === 404) {
    return tr('file_http_gone');
  }
  if (status === 401 || status === 403) {
    return tr('file_http_denied');
  }
  return trf('file_http_other', {status});
}

/** A path or link a reply mentions, resolved into something the app can open. */
export async function resolveFile(
  ref: string,
  sessionId?: string,
  agentId?: string,
): Promise<ChatFile | null> {
  const res = await resolveWorkspacePath(ref, sessionId, agentId);
  if (res.status !== 'success' || !res.file || res.file.is_dir) {
    return null;
  }
  return fileFromPayload({
    abs_path: res.file.abs_path,
    rel_path: res.file.path,
    file_name: res.file.name,
    kind: res.file.kind,
    size: res.file.size,
    raw_url: res.file.raw_url,
    preview_url: res.file.preview_url,
  });
}

/** The same page with its sandboxed preview link filled in, or null when the server has none. */
export async function withPreview(f: ChatFile): Promise<ChatFile | null> {
  if (!isUnsandboxedPage(f)) {
    return f;
  }
  const path = f.path ?? (f.rawUrl ? pathOfFileUrl(f.rawUrl) : null);
  const resolved = path ? await resolveFile(path).catch(() => null) : null;
  return resolved?.previewUrl ? {...f, previewUrl: resolved.previewUrl} : null;
}

/** `/api/file?path=…` back to the path it serves, so a link can be resolved like any other. */
function pathOfFileUrl(url: string): string | null {
  const match = /^\/api\/file\?(.*)$/.exec(url);
  if (!match) {
    return null;
  }
  for (const part of match[1].split('&')) {
    const [k, v] = part.split('=');
    if (k === 'path' && v) {
      try {
        return decodeURIComponent(v);
      } catch {
        return null;
      }
    }
  }
  return null;
}

const ABSOLUTE_PATH = /^(?:[A-Za-z]:[\\/]|\/(?!\/)|~\/)/;
const SCHEME = /^[a-zA-Z][\w+.-]*:/;

/** A link in a reply that points at a file on the server rather than the web. */
export function serverFileRef(href: string): string | null {
  const fromApi = pathOfFileUrl(href);
  if (fromApi) {
    return fromApi;
  }
  if (href.startsWith('/preview/') || href.startsWith('/api/')) {
    return null;
  }
  if (/^file:\/\//i.test(href)) {
    let p: string;
    try {
      p = decodeURIComponent(href.replace(/^file:\/\/\/?/i, ''));
    } catch {
      return null;
    }
    return /^[A-Za-z]:[\\/]/.test(p) ? p : `/${p}`;
  }
  if (ABSOLUTE_PATH.test(href)) {
    return href;
  }
  if (SCHEME.test(href) || href.startsWith('#') || href.startsWith('//')) {
    return null;
  }
  // Workspace-relative, as Agents cite their own files: `[report](websites/report.html)`.
  // A known extension keeps ordinary relative links out.
  let path = href.split('#')[0].split('?')[0].trim();
  try {
    path = decodeURI(path);
  } catch {}
  return KNOWN_EXT.test(path) ? path : null;
}

const KNOWN_EXT = new RegExp(`\\.(?:${FILE_EXTENSIONS.join('|')})$`, 'i');
const SEGMENT = '[\\w.\\-\\u4e00-\\u9fa5]+';
// At least one separator and a known extension, so prose like "see report.html"
// stays text; nothing path-like may precede it, which keeps URL tails out.
const PATH_IN_TEXT = new RegExp(
  `(^|[^\\w/\\\\.~:-])((?:~/|/|[A-Za-z]:[\\\\/])?(?:${SEGMENT}[\\\\/])+${SEGMENT}\\.(?:${FILE_EXTENSIONS.join('|')}))(?![\\w.\\-\\u4e00-\\u9fa5])`,
  'gi',
);

/** Text with the file paths it mentions cut out, so each can be made tappable. */
export function splitFilePaths(text: string): (string | {path: string})[] | null {
  if (!text.includes('.')) {
    return null;
  }
  const parts: (string | {path: string})[] = [];
  let last = 0;
  for (const m of text.matchAll(PATH_IN_TEXT)) {
    const start = (m.index ?? 0) + m[1].length;
    if (start > last) {
      parts.push(text.slice(last, start));
    }
    parts.push({path: m[2]});
    last = start + m[2].length;
  }
  if (!parts.length) {
    return null;
  }
  if (last < text.length) {
    parts.push(text.slice(last));
  }
  return parts;
}

/** Inline code that is nothing but a file path. */
export function codeFilePath(code: string): string | null {
  const parts = splitFilePaths(code.trim());
  return parts?.length === 1 && typeof parts[0] !== 'string' ? parts[0].path : null;
}

export const fileBaseName = baseName;

/** An image a reply embeds, as a file the viewer can show and save. */
export function fileFromImageRef(uri: string, alt?: string): ChatFile {
  const fromApi = pathOfFileUrl(uri);
  const path = fromApi ?? (ABSOLUTE_PATH.test(uri) ? uri : undefined);
  // Workspace-relative sources are only seen mid-stream; `done` and history
  // carry them rewritten to `/api/file`, so there is nothing to fetch yet.
  const relative = !path && !SCHEME.test(uri) && !uri.startsWith('/');
  return {
    name: alt?.trim() || baseName(path ?? uri.split('?')[0]),
    kind: 'image',
    path,
    rawUrl: path || relative ? undefined : uri,
  };
}
