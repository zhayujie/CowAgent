import { app, ipcMain } from 'electron'
import path from 'path'
import fs from 'fs'
import os from 'os'

// Themes come from two sources and are merged at load time:
//
//   1. Bundled themes — resources/themes/ shipped inside the app package
//      (read-only). Present only in builds produced from a flavor; absent
//      in the standard build.
//   2. User themes — ~/.cow/themes/, the shared data dir users can add to
//      (via a future in-app store/import). Each theme is its own folder:
//
//        <id>/
//          ├── theme.json      (required)
//          ├── wallpaper.jpg   (optional)
//          └── logo.svg        (optional)
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

function cowRoot(): string {
  // Honor an explicit override, else default to ~/.cow to match the backend.
  return process.env.COW_HOME || path.join(os.homedir(), '.cow')
}

export function themesDir(): string {
  return path.join(cowRoot(), THEMES_DIRNAME)
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
  appName?: string
  // Optional runtime-origin tag forwarded to the backend for stats.
  clientSource?: string
  // Optional override for the auto-update feed base URL. When set, the updater
  // uses it as-is instead of the default build's feed.
  updateFeedUrl?: string
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
  try {
    const buf = fs.readFileSync(resolved)
    return `data:${mime};base64,${buf.toString('base64')}`
  } catch {
    return null
  }
}

// Walk a theme object and replace any wallpaper/logo image *file references*
// with inlined data URLs so the renderer can use them directly.
function inlineThemeAssets(theme: Record<string, unknown>, themeFolder: string) {
  for (const appearance of ['light', 'dark'] as const) {
    const app_ = theme[appearance] as Record<string, unknown> | undefined
    const wp = app_?.wallpaper as Record<string, unknown> | undefined
    if (wp && typeof wp.image === 'string') {
      const url = inlineImage(themeFolder, wp.image)
      if (url) wp.image = url
      else delete wp.image
    }
  }
  const identity = theme.identity as Record<string, unknown> | undefined
  if (identity && typeof identity.logo === 'string') {
    const url = inlineImage(themeFolder, identity.logo)
    if (url) identity.logo = url
    else delete identity.logo
  }
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
    if (!entry.isDirectory()) continue
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
// (~/.cow/themes). Bundled themes take precedence on id conflicts so a shipped
// theme can't be shadowed by a user folder of the same id.
export function loadThemes(): Record<string, unknown>[] {
  ensureThemesDir()
  const byId = new Map<string, Record<string, unknown>>()
  for (const theme of scanDir(themesDir())) byId.set(String(theme.id), theme)
  const bundled = bundledThemesDir()
  if (bundled) {
    for (const theme of scanDir(bundled)) byId.set(String(theme.id), theme)
  }
  return [...byId.values()]
}

export function setupThemeIPC() {
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
}
