import { app, BrowserWindow, ipcMain, nativeImage, NativeImage, net, shell } from 'electron'
import { execFile } from 'child_process'
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
  // App version the desktop shortcut was last restored for, so a shortcut the
  // user deleted on purpose doesn't keep coming back on every launch.
  shortcutRestoredFor?: string
  // "<version>:<name>" of the last shortcut name written to the NSIS registry
  // value. Version-scoped because each installer run resets that value, so the
  // sync has to happen again after every update.
  shortcutNameSyncedFor?: string
  // App version the shortcuts were last swept for. A change means this is the
  // first launch after an update, which is the only point where they can have
  // been damaged.
  shortcutsCheckedFor?: string
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

// Window title only. app.setName is deliberately NOT called here: it also moves
// app.getPath('userData'), and by the time this runs the session/window have
// already opened files under the old path — the two would end up split across
// directories. The name is applied from the cache at startup instead (see
// applyCachedAppName), so it takes effect from the next launch.
function applyTitle(title: string): void {
  const trimmed = title.trim()
  if (!trimmed) return
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

// Apply a previously set app name. MUST be called before anything touches
// app.getPath('userData') (i.e. before app.whenReady / window creation), because
// app.setName changes where that path points: calling it later would strand the
// data written under the previous name.
export function applyCachedAppName(): void {
  try {
    const meta = JSON.parse(fs.readFileSync(metaCachePath(), 'utf8')) as CachedMeta
    const trimmed = meta.title?.trim()
    if (trimmed) app.setName(trimmed)
  } catch {
    /* no cached title */
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

// Windows shortcuts need an .ico, so derive a multi-size one from the cached
// PNG when no ready-made .ico was supplied.
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

// Resolved through Electron rather than assembled from the home dir: with
// OneDrive folder backup enabled the real Desktop lives under the OneDrive
// folder and ~/Desktop may not exist at all.
function desktopDir(): string {
  try {
    return app.getPath('desktop')
  } catch {
    return path.join(os.homedir(), 'Desktop')
  }
}

// Directories that may hold a shortcut to this app.
function shortcutDirs(): string[] {
  const home = os.homedir()
  const appData = process.env.APPDATA || path.join(home, 'AppData', 'Roaming')
  const dirs = [
    desktopDir(),
    path.join(home, 'Desktop'),
    path.join(appData, 'Microsoft', 'Windows', 'Start Menu', 'Programs'),
  ]
  const seen = new Set<string>()
  return dirs.filter((dir) => {
    const key = path.resolve(dir).toLowerCase()
    if (seen.has(key)) return false
    seen.add(key)
    return true
  })
}

function sanitizeShortcutName(title: string): string {
  return title.replace(/[<>:"/\\|?*\x00-\x1f]/g, '').trim()
}

// electron-builder's NSIS uninstaller stages an update by MOVING every file out
// of the install dir into "$PLUGINSDIR\old-install" (a folder under %TEMP%),
// wiping the install dir, then notifying the shell. A shortcut whose target got
// re-resolved during that window ends up pointing into that staging folder,
// which the installer deletes when it exits — leaving a shortcut that fails with
// "the item has been moved or renamed".
const NSIS_UPDATE_STAGING_DIR = 'old-install'

type ShortcutKind =
  // Points at the running executable — nothing to repair.
  | 'current'
  // Ours, but the target no longer resolves (typically the NSIS staging path
  // above). Safe to re-point at the running executable.
  | 'stale'
  // Someone else's shortcut, or a second install that still exists.
  | 'foreign'

function classifyShortcut(target: string | undefined): ShortcutKind {
  if (!target) return 'foreign'
  let resolved: string
  try {
    resolved = path.resolve(target)
  } catch {
    return 'foreign'
  }
  if (resolved.toLowerCase() === path.resolve(process.execPath).toLowerCase()) return 'current'
  // Only ever adopt a link that names our own executable, so a shortcut to some
  // other app is never rewritten.
  if (path.basename(resolved).toLowerCase() !== path.basename(process.execPath).toLowerCase()) {
    return 'foreign'
  }
  const inStagingDir = resolved
    .toLowerCase()
    .split(path.sep)
    .includes(NSIS_UPDATE_STAGING_DIR)
  if (inStagingDir || !fs.existsSync(resolved)) return 'stale'
  // A different install of this app that is still present — leave it alone.
  return 'foreign'
}

// On Windows, existing shortcuts (Desktop + Start Menu) keep the icon and name
// they were created with at install time. Bring every shortcut belonging to this
// app in line with the runtime icon/label, re-pointing any that a previous
// update left dangling and restoring the desktop one if it went missing
// entirely. No-op elsewhere.
function syncWindowsShortcuts(opts: {
  icoPath?: string | null
  title?: string
  // Rewrite every shortcut even when nothing visibly changed. Used on the first
  // launch after an update: a link can carry a valid-looking target while its
  // shell link-tracking data already points into the staging dir, and the only
  // way to clear that is to write the link again.
  force?: boolean
}): void {
  if (process.platform !== 'win32') return
  const icoPath = opts.icoPath
  const title = opts.title ? sanitizeShortcutName(opts.title) : ''
  const desktops = new Set(
    [desktopDir(), path.join(os.homedir(), 'Desktop')].map((d) => path.resolve(d).toLowerCase()),
  )
  let desktopLinks = 0
  let renamedTo = ''
  let template: Electron.ShortcutDetails | null = null

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
      const kind = classifyShortcut(details.target)
      if (kind === 'foreign') continue
      if (desktops.has(path.resolve(dir).toLowerCase())) desktopLinks++

      // Fix the dangling target BEFORE the rename, so renaming can never carry a
      // dead path over to the new filename.
      if (kind === 'stale') {
        details = { ...details, target: process.execPath, cwd: path.dirname(process.execPath) }
      }

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
        // Only claim the name once a file actually carries it, so a failed
        // rename can't point the installer at something that isn't there.
        if (path.basename(linkPath) === `${title}.lnk`) renamedTo = title
      }

      const next: Electron.ShortcutDetails = { ...details }
      if (icoPath) next.icon = icoPath
      if (typeof next.iconIndex !== 'number') next.iconIndex = 0
      template = next
      // Rewriting a .lnk re-stamps its shell link-tracking data, which is what
      // lets the shell follow the executable into the update staging dir in the
      // first place. So only write when something actually changed.
      const iconChanged = !!next.icon && next.icon !== details.icon
      if (kind === 'stale' || iconChanged || opts.force) {
        try {
          shell.writeShortcutLink(linkPath, 'update', next)
        } catch (e) {
          console.warn('[app-icon] shortcut update failed:', (e as Error).message)
        }
      }
    }
  }

  // An update that renamed the shortcut out from under NSIS can leave the
  // desktop with nothing usable at all: the installer only refreshes the link
  // whose name it recorded, and never recreates one while updating. Put a
  // working one back rather than leaving the user with no way in.
  if (desktopLinks === 0) {
    restoreDesktopShortcut(desktopDir(), title, icoPath, template)
  }
  if (renamedTo) void recordShortcutName(renamedTo)
}

function restoreDesktopShortcut(
  desktop: string,
  title: string,
  icoPath: string | null | undefined,
  template: Electron.ShortcutDetails | null,
): void {
  if (!app.isPackaged) return
  const name = sanitizeShortcutName(title || app.getName())
  if (!name || !fs.existsSync(desktop)) return
  // Once per version: enough to undo the damage an update did, without
  // resurrecting a shortcut the user removed deliberately.
  let meta: CachedMeta = {}
  try {
    meta = JSON.parse(fs.readFileSync(metaCachePath(), 'utf8')) as CachedMeta
  } catch {
    /* first run */
  }
  if (meta.shortcutRestoredFor === app.getVersion()) return

  const details: Electron.ShortcutDetails = {
    ...(template || {}),
    target: process.execPath,
    cwd: path.dirname(process.execPath),
  }
  if (icoPath) details.icon = icoPath
  if (details.icon && typeof details.iconIndex !== 'number') details.iconIndex = 0
  try {
    shell.writeShortcutLink(path.join(desktop, `${name}.lnk`), 'create', details)
    cacheMeta({ shortcutRestoredFor: app.getVersion() })
    console.log('[app-icon] restored missing desktop shortcut')
  } catch (e) {
    console.warn('[app-icon] desktop shortcut restore failed:', (e as Error).message)
  }
}

function reg(args: string[]): Promise<string> {
  return new Promise((resolve, reject) => {
    execFile('reg.exe', args, { windowsHide: true }, (err, stdout) => {
      if (err) reject(err)
      else resolve(stdout)
    })
  })
}

const UNINSTALL_KEY = 'Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall'

// electron-builder's NSIS scripts locate the existing shortcuts through the
// ShortcutName value under this app's uninstall key (see setLinkVars in
// common.nsh). Renaming the .lnk without updating that value makes the file
// invisible to the next installer/uninstaller: it can neither refresh nor clean
// up the shortcut, which is how a dangling one survives an update. Keep the two
// in sync so the shortcut stays under NSIS's management.
//
// The key name is a generated GUID, so find it by install location instead of
// guessing. Best-effort: a per-machine install lives under HKLM and needs
// elevation we don't have, in which case this simply does nothing.
async function recordShortcutName(name: string): Promise<void> {
  const installDir = path.dirname(process.execPath)
  // Scanning the whole uninstall tree isn't free, so skip it once the value is
  // known to be in place for this version.
  const stamp = `${app.getVersion()}:${name}`
  try {
    const meta = JSON.parse(fs.readFileSync(metaCachePath(), 'utf8')) as CachedMeta
    if (meta.shortcutNameSyncedFor === stamp) return
  } catch {
    /* no cache yet */
  }
  try {
    const out = await reg(['query', `HKCU\\${UNINSTALL_KEY}`, '/s', '/v', 'InstallLocation'])
    let currentKey = ''
    for (const line of out.split(/\r?\n/)) {
      const key = line.match(/^(HKEY_CURRENT_USER\\.+)$/)
      if (key) {
        currentKey = key[1]
        continue
      }
      const value = line.match(/^\s+InstallLocation\s+REG_SZ\s+(.+?)\s*$/)
      if (!value || !currentKey) continue
      if (path.resolve(value[1]).toLowerCase() !== installDir.toLowerCase()) continue
      await reg(['add', currentKey, '/v', 'ShortcutName', '/t', 'REG_SZ', '/d', name, '/f'])
      cacheMeta({ shortcutNameSyncedFor: stamp })
      return
    }
  } catch (e) {
    console.warn('[app-icon] shortcut name registry sync failed:', (e as Error).message)
  }
}

// Repair pass for shortcuts left dangling by a previous update. Runs on every
// Windows launch whether or not the icon/title were ever overridden: the
// staging-dir problem comes from the NSIS update flow, so any install can hit
// it — and an unusable desktop shortcut is not something the user can be
// expected to fix by hand.
export function repairWindowsShortcuts(): void {
  if (process.platform !== 'win32') return
  let title = ''
  let checkedFor = ''
  try {
    const meta = JSON.parse(fs.readFileSync(metaCachePath(), 'utf8')) as CachedMeta
    title = meta.title?.trim() || ''
    checkedFor = meta.shortcutsCheckedFor || ''
  } catch {
    /* first run */
  }
  const ico = fs.existsSync(icoCachePath()) ? icoCachePath() : null
  syncWindowsShortcuts({ title, icoPath: ico, force: checkedFor !== app.getVersion() })
  cacheMeta({ shortcutsCheckedFor: app.getVersion() })
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
