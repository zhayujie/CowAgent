import { app, ipcMain, dialog, BrowserWindow } from 'electron'
import path from 'path'
import fs from 'fs'
import os from 'os'
import zlib from 'zlib'

// Themes come from two sources and are merged at load time:
//
//   1. Bundled themes — resources/themes/ shipped inside the app package
//      (read-only). Present only in builds produced from a flavor; absent
//      in the standard build.
//   2. User themes — <workspace>/system/themes/ (~/cow by default), which
//      users can add to by hand, via the in-app import, or through the
//      agent. Each theme is its own folder:
//
//        <id>/
//          ├── theme.json      (required)
//          ├── wallpaper.jpg   (optional; used even if theme.json omits it)
//          └── logo.png        (optional; used even if theme.json omits it)
//
// An optional app config (resources/app-config.json) can set a first-run
// default theme and a display name. When it's absent the app behaves exactly
// as the standard build (default theme, free switching).

const THEMES_DIRNAME = 'themes'
// Max bytes for an inlined image (mirrors the theme spec limit).
const MAX_IMAGE_BYTES = 16 * 1024 * 1024
const IMAGE_MIME: Record<string, string> = {
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.png': 'image/png',
  '.webp': 'image/webp',
  '.svg': 'image/svg+xml',
  '.gif': 'image/gif',
}
// Images picked up from a theme folder when theme.json doesn't name them.
const WALLPAPER_FILES = ['wallpaper.jpg', 'wallpaper.jpeg', 'wallpaper.png', 'wallpaper.webp']
const LOGO_FILES = ['logo.png', 'logo.svg', 'logo.webp', 'logo.jpg', 'logo.jpeg']

// The backend's data dir (holds config.json); set by setupThemeIPC.
let getDataDir: () => string = () => ''

// The Agent workspace, resolved like the backend does: config.json's
// agent_workspace, else ~/cow.
function workspaceDir(): string {
  let workspace = '~/cow'
  try {
    const dataDir = getDataDir() || path.join(os.homedir(), '.cow')
    const cfg = JSON.parse(fs.readFileSync(path.join(dataDir, 'config.json'), 'utf8'))
    const value = cfg && cfg.agent_workspace
    if (typeof value === 'string' && value.trim()) workspace = value.trim()
  } catch {
    // No or unreadable config: the backend falls back to ~/cow as well.
  }
  if (workspace === '~' || /^~[\\/]/.test(workspace)) workspace = path.join(os.homedir(), workspace.slice(1))
  return path.resolve(workspace)
}

// <workspace>/system/themes, beside the console menu (common/state_dir.py),
// so the web console and the Agent see the same themes.
export function themesDir(): string {
  return path.join(workspaceDir(), 'system', THEMES_DIRNAME)
}

// Directory holding themes bundled inside the app package (read-only). In dev
// it maps to the repo's resources/; in a packaged app to process.resourcesPath.
// Returns null when that folder doesn't exist (the standard build).
function bundledThemesDir(): string | null {
  const base = app.isPackaged
    ? path.join(process.resourcesPath, THEMES_DIRNAME)
    : path.resolve(__dirname, '../../resources', THEMES_DIRNAME)
  try {
    return fs.statSync(base).isDirectory() ? base : null
  } catch {
    return null
  }
}

// Optional app config bundled with the app. Absent in the standard build.
export interface AppConfig {
  defaultTheme?: string
  // Built-in theme ids to leave out of the theme list.
  hiddenThemes?: string[]
  appName?: string
  // Optional runtime-origin tag forwarded to the backend for stats.
  clientSource?: string
  // Optional override for the auto-update feed base URL. When set, the updater
  // uses it as-is instead of the default build's feed.
  updateFeedUrl?: string
  // false: ignore runtime icon/title overrides (set-app-icon / set-app-title)
  // and their cache, for a build that ships its own fixed name and icon.
  runtimeIconTitle?: boolean
  // false: hide the skill hub entry points.
  skillHub?: boolean
  // Help > Documentation target; an empty string hides the item.
  docsUrl?: string
  // Name of the built-in default agent (the backend's default_agent_name).
  agentName?: string
  // Windows AppUserModelID; must equal the build's appId.
  appUserModelId?: string
}

function appConfigPath(): string {
  return app.isPackaged
    ? path.join(process.resourcesPath, 'app-config.json')
    : path.resolve(__dirname, '../../resources', 'app-config.json')
}

export function loadAppConfig(): AppConfig | null {
  try {
    const raw = fs.readFileSync(appConfigPath(), 'utf8')
    const parsed = JSON.parse(raw) as AppConfig
    if (!parsed || typeof parsed !== 'object') return null
    return parsed
  } catch {
    return null // no app config → standard behavior
  }
}

function ensureThemesDir(): string {
  const dir = themesDir()
  try {
    fs.mkdirSync(dir, { recursive: true })
  } catch {
    // Non-fatal: scanning will simply return no themes.
  }
  return dir
}

// Inlined images keyed by absolute path, reused while the file is unchanged
// so re-listing themes doesn't re-read every wallpaper from disk.
const imageCache = new Map<string, { mtimeMs: number; size: number; url: string }>()
// Paths referenced during the current loadThemes() pass, used to prune the
// cache of themes that were removed.
let imagesSeen = new Set<string>()

// Read an image inside a theme folder and return a data: URL, or null. The
// path is constrained to the theme folder to avoid escaping via '..'.
function inlineImage(themeFolder: string, rel: string): string | null {
  if (!rel || typeof rel !== 'string') return null
  const resolved = path.resolve(themeFolder, rel)
  if (resolved !== themeFolder && !resolved.startsWith(themeFolder + path.sep)) return null
  let stat: fs.Stats
  try {
    stat = fs.statSync(resolved)
  } catch {
    return null
  }
  if (!stat.isFile() || stat.size === 0 || stat.size > MAX_IMAGE_BYTES) return null
  const ext = path.extname(resolved).toLowerCase()
  const mime = IMAGE_MIME[ext]
  if (!mime) return null
  imagesSeen.add(resolved)
  const cached = imageCache.get(resolved)
  if (cached && cached.mtimeMs === stat.mtimeMs && cached.size === stat.size) return cached.url
  try {
    const buf = fs.readFileSync(resolved)
    const url = `data:${mime};base64,${buf.toString('base64')}`
    imageCache.set(resolved, { mtimeMs: stat.mtimeMs, size: stat.size, url })
    return url
  } catch {
    return null
  }
}

// Walk a theme object and replace any wallpaper/logo image *file references*
// with inlined data URLs so the renderer can use them directly.
function inlineThemeAssets(theme: Record<string, unknown>, themeFolder: string) {
  // A wallpaper may sit at the top level (shared by both appearances) or
  // under light / dark.
  let hasWallpaper = false
  for (const holder of [theme, theme.light, theme.dark]) {
    const wp = (holder as Record<string, unknown> | undefined)?.wallpaper as Record<string, unknown> | undefined
    if (wp && typeof wp.image === 'string') {
      hasWallpaper = true
      const url = inlineImage(themeFolder, wp.image)
      if (url) wp.image = url
      else delete wp.image
    }
  }
  if (!hasWallpaper) {
    // None declared: pick up a conventionally named one in the folder.
    const url = firstImage(themeFolder, WALLPAPER_FILES)
    if (url) theme.wallpaper = { image: url, glass: true }
  }
  const identity = theme.identity as Record<string, unknown> | undefined
  if (identity && typeof identity.logo === 'string') {
    const url = inlineImage(themeFolder, identity.logo)
    if (url) identity.logo = url
    else delete identity.logo
  } else {
    const url = firstImage(themeFolder, LOGO_FILES)
    if (url) theme.identity = { ...(identity ?? {}), logo: url }
  }
}

function firstImage(themeFolder: string, names: string[]): string | null {
  for (const name of names) {
    const url = inlineImage(themeFolder, name)
    if (url) return url
  }
  return null
}

// Scan one directory for theme folders and return validated, asset-inlined themes.
function scanDir(dir: string): Record<string, unknown>[] {
  let entries: fs.Dirent[]
  try {
    entries = fs.readdirSync(dir, { withFileTypes: true })
  } catch {
    return []
  }
  const themes: Record<string, unknown>[] = []
  for (const entry of entries) {
    // Hidden folders are never themes (e.g. an in-progress import).
    if (!entry.isDirectory() || entry.name.startsWith('.')) continue
    const folder = path.join(dir, entry.name)
    const jsonPath = path.join(folder, 'theme.json')
    let raw: string
    try {
      raw = fs.readFileSync(jsonPath, 'utf8')
    } catch {
      continue // no theme.json in this folder
    }
    let theme: Record<string, unknown>
    try {
      theme = JSON.parse(raw)
    } catch (e) {
      console.warn(`[themes] invalid theme.json in ${entry.name}:`, (e as Error).message)
      continue
    }
    // Default the id to the folder name so it's always stable/unique.
    if (!theme.id || typeof theme.id !== 'string') theme.id = entry.name
    if (!theme.name || typeof theme.name !== 'string') theme.name = String(theme.id)
    inlineThemeAssets(theme, folder)
    themes.push(theme)
  }
  return themes
}

// Merge bundled themes (read-only, shipped in the package) with user themes
// (<workspace>/system/themes). Bundled themes take precedence on id conflicts
// so a shipped theme can't be shadowed by a user folder of the same id.
export function loadThemes(): Record<string, unknown>[] {
  ensureThemesDir()
  imagesSeen = new Set()
  const byId = new Map<string, Record<string, unknown>>()
  for (const theme of scanDir(themesDir())) byId.set(String(theme.id), theme)
  const bundled = bundledThemesDir()
  if (bundled) {
    for (const theme of scanDir(bundled)) byId.set(String(theme.id), theme)
  }
  for (const key of imageCache.keys()) {
    if (!imagesSeen.has(key)) imageCache.delete(key)
  }
  return [...byId.values()]
}

// ---- Import ---------------------------------------------------------------
// A theme can be imported from a .zip, a theme folder, or its theme.json. The
// package must hold theme.json at its root or inside a single top-level
// folder. Only theme.json and images are copied; anything else (including
// hidden files and macOS __MACOSX metadata) is skipped.

const MAX_IMPORT_BYTES = 64 * 1024 * 1024
const MAX_IMPORT_FILES = 200

export type ThemeImportResult =
  | { status: 'ok'; id: string; name: string }
  | { status: 'exists'; id: string; name: string; path: string }
  | { status: 'canceled' }
  | { status: 'error'; code: ThemeImportErrorCode }

type ThemeImportErrorCode = 'no_theme' | 'bad_json' | 'bad_zip' | 'too_large' | 'failed'

class ThemeImportError extends Error {
  constructor(public code: ThemeImportErrorCode) {
    super(code)
  }
}

// Normalize a package-relative path; null when it's unsafe (absolute, '..',
// drive or stream specifiers) or hidden.
function safeRelPath(raw: string): string | null {
  const normalized = raw.replace(/\\/g, '/')
  if (normalized.startsWith('/')) return null
  const parts = normalized.split('/').filter((p) => p && p !== '.')
  if (!parts.length) return null
  if (parts.some((p) => p === '..' || p.startsWith('.') || p === '__MACOSX' || p.includes(':'))) return null
  return parts.join('/')
}

function isThemeFile(rel: string): boolean {
  return path.posix.basename(rel) === 'theme.json' || path.posix.extname(rel).toLowerCase() in IMAGE_MIME
}

// Running byte/file budget shared by both import sources.
function makeBudget() {
  let bytes = 0
  let files = 0
  return (size: number) => {
    bytes += size
    files += 1
    if (size > MAX_IMAGE_BYTES || bytes > MAX_IMPORT_BYTES || files > MAX_IMPORT_FILES) {
      throw new ThemeImportError('too_large')
    }
  }
}

// Minimal zip reader (stored + deflate, no zip64/encryption) on top of zlib,
// enough for theme packages without pulling in a dependency.
function readZip(file: string): Map<string, Buffer> {
  if (fs.statSync(file).size > MAX_IMPORT_BYTES) throw new ThemeImportError('too_large')
  const buf = fs.readFileSync(file)
  let eocd = -1
  for (let i = buf.length - 22; i >= Math.max(0, buf.length - 22 - 0xffff); i--) {
    if (buf.readUInt32LE(i) === 0x06054b50) {
      eocd = i
      break
    }
  }
  if (eocd < 0) throw new ThemeImportError('bad_zip')
  const count = buf.readUInt16LE(eocd + 10)
  let p = buf.readUInt32LE(eocd + 16)
  const charge = makeBudget()
  const files = new Map<string, Buffer>()
  for (let n = 0; n < count; n++) {
    if (p + 46 > buf.length || buf.readUInt32LE(p) !== 0x02014b50) throw new ThemeImportError('bad_zip')
    const flags = buf.readUInt16LE(p + 8)
    const method = buf.readUInt16LE(p + 10)
    const compSize = buf.readUInt32LE(p + 20)
    const size = buf.readUInt32LE(p + 24)
    const nameLen = buf.readUInt16LE(p + 28)
    const local = buf.readUInt32LE(p + 42)
    const name = buf.toString('utf8', p + 46, p + 46 + nameLen)
    p += 46 + nameLen + buf.readUInt16LE(p + 30) + buf.readUInt16LE(p + 32)

    const rel = safeRelPath(name)
    if (!rel || name.endsWith('/') || !isThemeFile(rel)) continue
    if (flags & 0x1) throw new ThemeImportError('bad_zip')
    charge(size)
    if (local + 30 > buf.length || buf.readUInt32LE(local) !== 0x04034b50) throw new ThemeImportError('bad_zip')
    const start = local + 30 + buf.readUInt16LE(local + 26) + buf.readUInt16LE(local + 28)
    const raw = buf.subarray(start, start + compSize)
    let data: Buffer
    if (method === 0) data = Buffer.from(raw)
    else if (method === 8) data = zlib.inflateRawSync(raw, { maxOutputLength: Math.max(size, 1) })
    else throw new ThemeImportError('bad_zip')
    if (data.length !== size) throw new ThemeImportError('bad_zip')
    files.set(rel, data)
  }
  return files
}

// Collect theme.json + images under a theme folder (symlinks are skipped).
function readFolder(root: string): Map<string, Buffer> {
  const charge = makeBudget()
  const files = new Map<string, Buffer>()
  const walk = (dir: string, rel: string, depth: number) => {
    if (depth > 4) return
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      const childRel = rel ? `${rel}/${entry.name}` : entry.name
      if (!safeRelPath(childRel)) continue
      const full = path.join(dir, entry.name)
      if (entry.isDirectory()) walk(full, childRel, depth + 1)
      else if (entry.isFile() && isThemeFile(childRel)) {
        charge(fs.statSync(full).size)
        files.set(childRel, fs.readFileSync(full))
      }
    }
  }
  walk(root, '', 0)
  return files
}

// Resolve the picked path to the theme's files (rooted at theme.json) plus a
// fallback id taken from the package/folder name.
function readImportSource(source: string): { files: Map<string, Buffer>; fallbackId: string } {
  let stat: fs.Stats
  try {
    stat = fs.statSync(source)
  } catch {
    throw new ThemeImportError('no_theme')
  }
  const fromFolder = (dir: string) => {
    let root = dir
    if (!fs.existsSync(path.join(dir, 'theme.json'))) {
      const inner = fs
        .readdirSync(dir, { withFileTypes: true })
        .filter((e) => e.isDirectory() && !e.name.startsWith('.'))
        .filter((e) => fs.existsSync(path.join(dir, e.name, 'theme.json')))
      if (inner.length !== 1) throw new ThemeImportError('no_theme')
      root = path.join(dir, inner[0].name)
    }
    return { files: readFolder(root), fallbackId: path.basename(root) }
  }

  if (stat.isDirectory()) return fromFolder(source)
  if (path.basename(source).toLowerCase() === 'theme.json') return fromFolder(path.dirname(source))
  if (path.extname(source).toLowerCase() !== '.zip') throw new ThemeImportError('no_theme')

  let all: Map<string, Buffer>
  try {
    all = readZip(source)
  } catch (e) {
    throw e instanceof ThemeImportError ? e : new ThemeImportError('bad_zip')
  }
  let prefix = ''
  if (!all.has('theme.json')) {
    const roots = [...all.keys()].filter((k) => /^[^/]+\/theme\.json$/.test(k))
    if (roots.length !== 1) throw new ThemeImportError('no_theme')
    prefix = roots[0].slice(0, -'theme.json'.length)
  }
  const files = new Map<string, Buffer>()
  for (const [rel, data] of all) {
    if (rel.startsWith(prefix)) files.set(rel.slice(prefix.length), data)
  }
  const fallbackId = prefix ? prefix.slice(0, -1) : path.basename(source, path.extname(source))
  return { files, fallbackId }
}

// Theme ids double as folder names, so strip characters no OS accepts there.
function sanitizeId(raw: string): string {
  return raw
    .replace(/[\\/:*?"<>|\x00-\x1f]+/g, '-')
    .replace(/^[\s.-]+/, '')
    .slice(0, 64)
    .trim()
}

function themeIdOf(folder: string): string | null {
  try {
    const parsed = JSON.parse(fs.readFileSync(path.join(folder, 'theme.json'), 'utf8'))
    return typeof parsed?.id === 'string' && parsed.id ? parsed.id : path.basename(folder)
  } catch {
    return null
  }
}

// Folder of the user theme with this id, if any (ids may differ from names).
function findUserTheme(id: string): string | null {
  const dir = themesDir()
  let entries: fs.Dirent[]
  try {
    entries = fs.readdirSync(dir, { withFileTypes: true })
  } catch {
    return null
  }
  for (const entry of entries) {
    if (!entry.isDirectory() || entry.name.startsWith('.')) continue
    const folder = path.join(dir, entry.name)
    if (themeIdOf(folder) === id) return folder
  }
  return null
}

// Validate and install a theme into the user themes folder. Ids taken by built-in or
// bundled themes get a numeric suffix; an existing user theme with the same
// id is only replaced when `overwrite` is set (else 'exists' is returned so
// the UI can ask first).
function importTheme(source: string, overwrite: boolean, reserved: Set<string>): ThemeImportResult {
  const { files, fallbackId } = readImportSource(source)
  const jsonBuf = files.get('theme.json')
  if (!jsonBuf) throw new ThemeImportError('no_theme')
  let theme: Record<string, unknown>
  try {
    theme = JSON.parse(jsonBuf.toString('utf8').replace(/^\uFEFF/, ''))
  } catch {
    throw new ThemeImportError('bad_json')
  }
  if (!theme || typeof theme !== 'object' || Array.isArray(theme)) throw new ThemeImportError('bad_json')

  const rawId = typeof theme.id === 'string' && theme.id.trim() ? theme.id : fallbackId
  const baseId = sanitizeId(rawId) || `theme-${Date.now().toString(36)}`
  let id = baseId
  for (let n = 2; reserved.has(id); n++) id = `${baseId}-${n}`
  const name = typeof theme.name === 'string' && theme.name.trim() ? theme.name : id

  const existing = findUserTheme(id)
  if (existing && !overwrite) return { status: 'exists', id, name, path: source }

  const dir = ensureThemesDir()
  const staging = path.join(dir, `.import-${process.pid}-${Date.now()}`)
  try {
    for (const [rel, data] of files) {
      const out = path.join(staging, ...rel.split('/'))
      fs.mkdirSync(path.dirname(out), { recursive: true })
      // Keep the author's file as-is unless the id had to change.
      const body = rel === 'theme.json' && theme.id !== id ? JSON.stringify({ ...theme, id }, null, 2) : data
      fs.writeFileSync(out, body)
    }
    if (existing) fs.rmSync(existing, { recursive: true, force: true })
    let target = path.join(dir, id)
    if (fs.existsSync(target)) target = path.join(dir, `${id}-${Date.now().toString(36)}`)
    fs.renameSync(staging, target)
  } catch (e) {
    fs.rmSync(staging, { recursive: true, force: true })
    throw e
  }
  return { status: 'ok', id, name }
}

export function setupThemeIPC(dataDir: () => string) {
  getDataDir = dataDir
  ipcMain.handle('themes-list', () => {
    try {
      return loadThemes()
    } catch (e) {
      console.warn('[themes] load failed:', (e as Error).message)
      return []
    }
  })
  ipcMain.handle('themes-dir', () => themesDir())
  ipcMain.handle('app-config-get', () => loadAppConfig())
  // Import a theme package. Without `path` a picker is shown first; the
  // renderer passes the ids of its built-in themes so they can't be shadowed.
  ipcMain.handle(
    'themes-import',
    async (
      event,
      opts: { path?: string; title?: string; overwrite?: boolean; reserved?: string[] } = {},
    ): Promise<ThemeImportResult> => {
      try {
        let source = typeof opts.path === 'string' ? opts.path : ''
        if (!source) {
          // Windows/Linux can't pick files and folders in one dialog, so a
          // folder is imported there by picking its theme.json.
          const options: Electron.OpenDialogOptions = {
            title: opts.title,
            properties: process.platform === 'darwin' ? ['openFile', 'openDirectory'] : ['openFile'],
            filters: [{ name: 'Theme', extensions: ['zip', 'json'] }],
          }
          const win = BrowserWindow.fromWebContents(event.sender)
          const picked = win ? await dialog.showOpenDialog(win, options) : await dialog.showOpenDialog(options)
          if (picked.canceled || !picked.filePaths[0]) return { status: 'canceled' }
          source = picked.filePaths[0]
        }
        const reserved = new Set(['default', ...(Array.isArray(opts.reserved) ? opts.reserved : [])])
        const bundled = bundledThemesDir()
        if (bundled) {
          for (const entry of fs.readdirSync(bundled, { withFileTypes: true })) {
            const id = entry.isDirectory() ? themeIdOf(path.join(bundled, entry.name)) : null
            if (id) reserved.add(id)
          }
        }
        return importTheme(source, !!opts.overwrite, reserved)
      } catch (e) {
        if (e instanceof ThemeImportError) return { status: 'error', code: e.code }
        console.warn('[themes] import failed:', (e as Error).message)
        return { status: 'error', code: 'failed' }
      }
    },
  )
}
