import { app, BrowserWindow, ipcMain, nativeImage, NativeImage, net, shell } from 'electron'
import path from 'path'
import fs from 'fs'
import os from 'os'

// Let the web layer override the window icon/title at runtime and remember it,
// so it also applies on the next launch before the page loads.

const CACHE_DIRNAME = 'app-icon'
const ICON_FILE = 'icon.png'
const ICO_FILE = 'icon.ico'
const META_FILE = 'meta.json'
const MAX_ICON_BYTES = 4 * 1024 * 1024
const DOWNLOAD_TIMEOUT_MS = 10 * 1000

interface CachedMeta {
  title?: string
}

let getMainWindow: (() => BrowserWindow | null) | null = null
let getTrayIcon: (() => Electron.Tray | null) | null = null

function cacheDir(): string {
  const root = process.env.COW_HOME || path.join(os.homedir(), '.cow')
  return path.join(root, CACHE_DIRNAME)
}

function iconCachePath(): string {
  return path.join(cacheDir(), ICON_FILE)
}

function metaCachePath(): string {
  return path.join(cacheDir(), META_FILE)
}

function icoCachePath(): string {
  return path.join(cacheDir(), ICO_FILE)
}

// Download in the main process so the bytes aren't mangled by a text transport.
function downloadBuffer(url: string): Promise<Buffer | null> {
  return new Promise((resolve) => {
    let parsed: URL
    try {
      parsed = new URL(url)
    } catch {
      resolve(null)
      return
    }
    if (parsed.protocol !== 'https:' && parsed.protocol !== 'http:') {
      resolve(null)
      return
    }
    let done = false
    const finish = (buf: Buffer | null) => {
      if (done) return
      done = true
      resolve(buf)
    }
    const request = net.request({ method: 'GET', url })
    const timer = setTimeout(() => {
      request.abort()
      finish(null)
    }, DOWNLOAD_TIMEOUT_MS)
    request.on('response', (response) => {
      const chunks: Buffer[] = []
      let size = 0
      response.on('data', (chunk: Buffer) => {
        size += chunk.length
        if (size > MAX_ICON_BYTES) {
          request.abort()
          clearTimeout(timer)
          finish(null)
          return
        }
        chunks.push(chunk)
      })
      response.on('end', () => {
        clearTimeout(timer)
        finish(Buffer.concat(chunks))
      })
    })
    request.on('error', () => {
      clearTimeout(timer)
      finish(null)
    })
    request.end()
  })
}

async function downloadImage(url: string): Promise<NativeImage | null> {
  const buf = await downloadBuffer(url)
  if (!buf) return null
  const img = nativeImage.createFromBuffer(buf)
  return img.isEmpty() ? null : img
}

// Fetch a ready-made multi-size .ico and cache it verbatim, so Windows
// shortcuts get a crisp icon without a lossy PNG conversion. Rejects payloads
// that aren't real .ico files (magic bytes 00 00 01 00).
async function downloadIco(url: string): Promise<string | null> {
  const buf = await downloadBuffer(url)
  if (!buf || buf.length < 4 || buf.readUInt32LE(0) !== 0x00010000) return null
  try {
    fs.mkdirSync(cacheDir(), { recursive: true })
    fs.writeFileSync(icoCachePath(), buf)
    return icoCachePath()
  } catch (e) {
    console.warn('[app-icon] ico download write failed:', (e as Error).message)
    return null
  }
}

function applyIcon(icon: NativeImage): void {
  if (process.platform === 'darwin') {
    app.dock?.setIcon(icon)
  } else {
    getMainWindow?.()?.setIcon(icon)
  }
  const tray = getTrayIcon?.()
  if (tray) tray.setImage(icon.resize({ width: 18, height: 18 }))
}

function applyTitle(title: string): void {
  const trimmed = title.trim()
  if (!trimmed) return
  app.setName(trimmed)
  getMainWindow?.()?.setTitle(trimmed)
}

function cacheIcon(icon: NativeImage): void {
  try {
    fs.mkdirSync(cacheDir(), { recursive: true })
    fs.writeFileSync(iconCachePath(), icon.toPNG())
  } catch (e) {
    console.warn('[app-icon] icon cache write failed:', (e as Error).message)
  }
}

function cacheMeta(meta: CachedMeta): void {
  try {
    fs.mkdirSync(cacheDir(), { recursive: true })
    let existing: CachedMeta = {}
    try {
      existing = JSON.parse(fs.readFileSync(metaCachePath(), 'utf8')) as CachedMeta
    } catch {
      /* first write or unreadable */
    }
    fs.writeFileSync(metaCachePath(), JSON.stringify({ ...existing, ...meta }))
  } catch (e) {
    console.warn('[app-icon] meta cache write failed:', (e as Error).message)
  }
}

// Apply the cached icon/title before the page loads, so a custom mark shows
// from the first paint instead of flashing the default.
export function applyCachedAppIcon(): void {
  let icon: NativeImage | null = null
  try {
    const buf = fs.readFileSync(iconCachePath())
    if (buf.length && buf.length <= MAX_ICON_BYTES) {
      const img = nativeImage.createFromBuffer(buf)
      if (!img.isEmpty()) icon = img
    }
  } catch {
    /* no cached icon */
  }
  if (icon) applyIcon(icon)

  try {
    const meta = JSON.parse(fs.readFileSync(metaCachePath(), 'utf8')) as CachedMeta
    if (meta.title) applyTitle(meta.title)
  } catch {
    /* no cached title */
  }
}

// The runtime icon set via set-app-icon (downloaded and cached), for reuse
// elsewhere — e.g. as the image on native notifications so they match the
// current window/Dock icon. Returns null when no custom icon has been applied,
// so callers can fall back to the bundle icon.
export function getRuntimeAppIcon(): NativeImage | null {
  try {
    const buf = fs.readFileSync(iconCachePath())
    if (!buf.length || buf.length > MAX_ICON_BYTES) return null
    const img = nativeImage.createFromBuffer(buf)
    return img.isEmpty() ? null : img
  } catch {
    return null
  }
}

// On Windows, existing shortcuts (Desktop + Start Menu) keep the icon/name they
// were created with at install time. Regenerate a multi-size .ico from the
// current PNG and rewrite every shortcut that points at this executable so its
// icon (and optionally its label) matches the runtime one. No-op elsewhere.
async function writeIcoFromCachedPng(): Promise<string | null> {
  const png = iconCachePath()
  if (!fs.existsSync(png)) return null
  try {
    const { default: pngToIco } = await import('png-to-ico')
    const buf = await pngToIco(png)
    fs.mkdirSync(cacheDir(), { recursive: true })
    fs.writeFileSync(icoCachePath(), buf)
    return icoCachePath()
  } catch (e) {
    console.warn('[app-icon] ico generation failed:', (e as Error).message)
    return null
  }
}

// Directories that may hold a shortcut to this app.
function shortcutDirs(): string[] {
  const home = os.homedir()
  const appData = process.env.APPDATA || path.join(home, 'AppData', 'Roaming')
  return [
    path.join(home, 'Desktop'),
    path.join(appData, 'Microsoft', 'Windows', 'Start Menu', 'Programs'),
  ]
}

// A shortcut belongs to this app when its target is the current executable.
function pointsAtThisApp(target: string | undefined): boolean {
  if (!target) return false
  try {
    return path.resolve(target).toLowerCase() === path.resolve(process.execPath).toLowerCase()
  } catch {
    return false
  }
}

function sanitizeShortcutName(title: string): string {
  return title.replace(/[<>:"/\\|?*\x00-\x1f]/g, '').trim()
}

// Update the icon of every shortcut pointing at this app, and rename the file
// to `title`. Rename is a plain filesystem move (fs.renameSync) so the target
// and cwd are preserved exactly and no duplicate is ever created.
function syncWindowsShortcuts(opts: { icoPath?: string | null; title?: string }): void {
  if (process.platform !== 'win32') return
  const icoPath = opts.icoPath
  const title = opts.title ? sanitizeShortcutName(opts.title) : ''
  for (const dir of shortcutDirs()) {
    let entries: string[]
    try {
      entries = fs.readdirSync(dir).filter((n) => n.toLowerCase().endsWith('.lnk'))
    } catch {
      continue
    }
    for (const name of entries) {
      let linkPath = path.join(dir, name)
      let details: Electron.ShortcutDetails
      try {
        details = shell.readShortcutLink(linkPath)
      } catch {
        continue
      }
      if (!pointsAtThisApp(details.target)) continue

      if (title) {
        const target = path.join(dir, `${title}.lnk`)
        if (path.resolve(target).toLowerCase() !== path.resolve(linkPath).toLowerCase()) {
          try {
            fs.renameSync(linkPath, target)
            linkPath = target
          } catch (e) {
            console.warn('[app-icon] shortcut rename failed:', (e as Error).message)
          }
        }
      }

      if (!icoPath) continue
      const next: Electron.ShortcutDetails = { ...details, icon: icoPath }
      if (typeof next.iconIndex !== 'number') next.iconIndex = 0
      try {
        shell.writeShortcutLink(linkPath, 'update', next)
      } catch (e) {
        console.warn('[app-icon] shortcut icon update failed:', (e as Error).message)
      }
    }
  }
}

export function setupAppIconIPC(deps: {
  getWindow: () => BrowserWindow | null
  getTray: () => Electron.Tray | null
}): void {
  getMainWindow = deps.getWindow
  getTrayIcon = deps.getTray

  ipcMain.handle('set-app-icon', async (_event, iconUrl: unknown, icoUrl: unknown) => {
    if (typeof iconUrl !== 'string' || !iconUrl) return false
    const icon = await downloadImage(iconUrl)
    if (!icon) return false
    applyIcon(icon)
    cacheIcon(icon)
    if (process.platform === 'win32') {
      let icoPath: string | null = null
      if (typeof icoUrl === 'string' && icoUrl) icoPath = await downloadIco(icoUrl)
      if (!icoPath) icoPath = await writeIcoFromCachedPng()
      syncWindowsShortcuts({ icoPath })
    }
    return true
  })

  ipcMain.handle('set-app-title', (_event, title: unknown) => {
    if (typeof title !== 'string' || !title.trim()) return false
    applyTitle(title)
    cacheMeta({ title })
    // Reuse the cached icon (if any) so the renamed shortcut keeps it.
    const ico = fs.existsSync(icoCachePath()) ? icoCachePath() : null
    syncWindowsShortcuts({ title, icoPath: ico })
    return true
  })
}
