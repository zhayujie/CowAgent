import { app, BrowserWindow, session, shell, ipcMain, dialog, nativeImage, Notification, systemPreferences, crashReporter } from 'electron'
import path from 'path'
import fs from 'fs'
import os from 'os'
import http from 'http'
import { PythonBackend, BackendError } from './python-manager'
import { buildAppMenu } from './menu'
import { createTray, destroyTray, getTray } from './tray'
import { initUpdater, checkForUpdates, startDownload, quitAndInstall, setUpdateLanguage } from './updater'
import { setupThemeIPC, loadAppConfig } from './themes'
import { setupHttpRelayIPC } from './http-relay'
import {
  setupAppIconIPC,
  applyCachedAppIcon,
  applyCachedAppName,
  repairWindowsShortcuts,
  getRuntimeAppIcon,
} from './app-icon'

// Where the packaged backend keeps its writable data (config.json, run.log).
// Kept in sync with COW_DATA_DIR in python-manager.ts so the desktop shell
// writes its own diagnostics into the SAME run.log the "open log folder" button
// reveals and the in-app Logs page tails — one place to look for both layers.
const COW_DATA_DIR = path.join(os.homedir(), '.cow')

// Mirror the main process's console output and any uncaught crash to run.log.
// Packaged builds have no terminal, so every console.log/error and every
// Electron-layer crash (renderer/GPU gone, main-process exception) used to
// vanish: the backend's run.log covered Python failures, but a white screen or
// a silent app quit left nothing behind. This closes that gap without a crash
// server — the evidence lands locally where the user can already find it.
function initDesktopLogging(): void {
  let stream: fs.WriteStream | null = null
  try {
    fs.mkdirSync(COW_DATA_DIR, { recursive: true })
    // Append so we never clobber the backend's own run.log history; both sides
    // are line-based, so interleaving is fine.
    stream = fs.createWriteStream(path.join(COW_DATA_DIR, 'run.log'), { flags: 'a' })
    stream.on('error', () => { stream = null })
  } catch {
    stream = null
  }

  const write = (level: string, args: unknown[]) => {
    if (!stream) return
    const text = args
      .map((a) => (typeof a === 'string' ? a : a instanceof Error ? a.stack || a.message : JSON.stringify(a)))
      .join(' ')
    try {
      stream.write(`[MAIN][${new Date().toISOString()}] [${level}] ${text}\n`)
    } catch {
      // logging must never break the app
    }
  }

  // Wrap console so existing console.* calls throughout main also persist,
  // while still printing to stdout for `npm run dev`.
  const patch = (name: 'log' | 'warn' | 'error') => {
    const original = console[name].bind(console)
    console[name] = (...args: unknown[]) => {
      write(name.toUpperCase(), args)
      original(...args)
    }
  }
  patch('log')
  patch('warn')
  patch('error')

  // Native minidumps for hard crashes (segfaults in Electron/Chromium). Stored
  // locally under userData/Crashpad; no upload server is configured.
  try {
    crashReporter.start({ uploadToServer: false })
  } catch {
    // crashReporter is best-effort; never let it block startup
  }

  // Main-process JS errors that would otherwise kill the app silently.
  process.on('uncaughtException', (err) => {
    console.error('[crash] uncaughtException:', err?.stack || err)
  })
  process.on('unhandledRejection', (reason) => {
    console.error('[crash] unhandledRejection:', reason instanceof Error ? reason.stack : reason)
  })

  // Renderer/GPU/utility process crashes. These are the "white screen" and
  // "window vanished" cases the user sees but that leave no trace by default.
  app.on('render-process-gone', (_e, _wc, details) => {
    console.error(`[crash] render-process-gone: reason=${details.reason} exitCode=${details.exitCode}`)
  })
  app.on('child-process-gone', (_e, details) => {
    console.error(`[crash] child-process-gone: type=${details.type} reason=${details.reason} exitCode=${details.exitCode}`)
  })

  app.on('before-quit', () => {
    try {
      stream?.end()
    } catch {
      // ignore
    }
  })
}

// Set up main-process logging + crash capture before anything else runs, so the
// earliest console output and any startup crash are already being persisted.
initDesktopLogging()

// Force the product name so the Dock/menu shows the app name even in dev mode,
// where the default Electron binary would otherwise report "Electron". The name
// can be overridden by the bundled app-config (appName); defaults to CowAgent.
app.setName(loadAppConfig()?.appName || 'CowAgent')
  // The web layer may have overridden the name at runtime. Re-apply it here,
  // before app.getPath('userData') is read anywhere, since setName moves it.
applyCachedAppName()

// Windows shows notifications only when an AppUserModelID is set; without it
// they are silently dropped. Harmless on macOS/Linux.
if (process.platform === 'win32') {
  app.setAppUserModelId('com.cowagent.desktop')
}

let mainWindow: BrowserWindow | null = null
let pythonBackend: PythonBackend | null = null
// True once the user explicitly quits (menu/tray), so close-to-tray is bypassed.
let isQuitting = false

const isDev = !app.isPackaged
const VITE_DEV_PORTS = [5173, 5174, 5175, 5176]

// Launched by the OS at login (Windows passes --hidden; macOS reports it via
// getLoginItemSettings().wasOpenedAsHidden). Start minimized to the tray so
// autostart is unobtrusive.
function launchedHidden(): boolean {
  if (process.argv.includes('--hidden')) return true
  try {
    return app.getLoginItemSettings().wasOpenedAsHidden === true
  } catch {
    return false
  }
}

function probePort(port: number): Promise<boolean> {
  return new Promise((resolve) => {
    const req = http.get(`http://localhost:${port}`, (res) => {
      resolve(res.statusCode !== undefined)
    })
    req.on('error', () => resolve(false))
    req.setTimeout(500, () => { req.destroy(); resolve(false) })
  })
}

async function findViteDevServer(): Promise<string | null> {
  for (const port of VITE_DEV_PORTS) {
    if (await probePort(port)) {
      return `http://localhost:${port}`
    }
  }
  return null
}

function getIconPath(ext: string = 'png'): string | undefined {
  const iconFile = `icon.${ext}`
  const iconPath = isDev
    ? path.resolve(__dirname, '../../resources', iconFile)
    : path.join(process.resourcesPath, iconFile)
  if (fs.existsSync(iconPath)) return iconPath
  return undefined
}

const isMac = process.platform === 'darwin'
const isWin = process.platform === 'win32'

// Persisted window bounds
const windowStateFile = () => path.join(app.getPath('userData'), 'window-state.json')

function loadWindowState(): { width: number; height: number; x?: number; y?: number } {
  try {
    const raw = fs.readFileSync(windowStateFile(), 'utf-8')
    const s = JSON.parse(raw)
    if (typeof s.width === 'number' && typeof s.height === 'number') return s
  } catch {
    /* first run or unreadable */
  }
  return { width: 1280, height: 800 }
}

function saveWindowState() {
  if (!mainWindow || mainWindow.isDestroyed()) return
  if (mainWindow.isMinimized() || mainWindow.isFullScreen()) return
  const b = mainWindow.getBounds()
  try {
    fs.writeFileSync(windowStateFile(), JSON.stringify(b))
  } catch {
    /* ignore */
  }
}

function createWindow() {
  const state = loadWindowState()

  mainWindow = new BrowserWindow({
    width: state.width,
    height: state.height,
    x: state.x,
    y: state.y,
    minWidth: 900,
    minHeight: 600,
    // macOS: native traffic lights inset into our custom titlebar.
    // Windows: fully frameless; we render custom window controls in-app.
    titleBarStyle: isMac ? 'hiddenInset' : 'hidden',
    trafficLightPosition: isMac ? { x: 14, y: 16 } : undefined,
    frame: isMac ? undefined : false,
    backgroundColor: '#0e0e10',
    icon: getIconPath(),
    show: false,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  })

  const persist = () => saveWindowState()
  mainWindow.on('resize', persist)
  mainWindow.on('move', persist)
  mainWindow.on('maximize', emitMaximizeState)
  mainWindow.on('unmaximize', emitMaximizeState)

  const rendererHtml = path.join(__dirname, '../renderer/index.html')

  if (isDev) {
    findViteDevServer().then((devUrl) => {
      if (devUrl) {
        console.log(`[Electron] Loading Vite dev server: ${devUrl}`)
        mainWindow?.loadURL(devUrl)
        mainWindow?.webContents.openDevTools()
      } else if (fs.existsSync(rendererHtml)) {
        console.log('[Electron] Vite dev server not found, loading built files')
        mainWindow?.loadFile(rendererHtml)
      } else {
        console.error('[Electron] No renderer available. Run "npm run build:renderer" first.')
      }
    })
  } else {
    mainWindow.loadFile(rendererHtml)
  }

  // Surface renderer-side console output and load failures to the main-process
  // stdout. Without this, "stuck on initializing" hangs are invisible from the
  // terminal because all renderer logs stay in the (closed) devtools.
  mainWindow.webContents.on('console-message', (_e, level, message, line, sourceId) => {
    console.log(`[renderer:${level}] ${message} (${sourceId}:${line})`)
  })
  mainWindow.webContents.on('did-fail-load', (_e, code, desc, url) => {
    console.error(`[renderer] did-fail-load ${code} ${desc} ${url}`)
  })

  // Replay the backend's current state to a renderer that has just loaded.
  // Backend events are fire-and-forget sends, but the renderer only subscribes
  // once React has mounted — so a failure detected in the first few hundred
  // milliseconds (a missing executable is detected almost immediately) was
  // announced to nobody, and the user was left staring at the generic
  // "initialization failed" with no reason attached.
  mainWindow.webContents.on('did-finish-load', () => {
    sendBackendState()
  })

  mainWindow.once('ready-to-show', () => {
    // Skip the initial paint when autostarted hidden: the window stays in the
    // tray/Dock until the user opens it, matching the "unobtrusive" intent.
    if (launchedHidden()) return
    mainWindow?.show()
  })

  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url)
    return { action: 'deny' }
  })

  // Last-resort backstop for a stray file drop: Chromium would navigate the
  // renderer to the dropped file and the UI would be gone until restart.
  // Renderer reloads keep the same URL, so they are unaffected.
  mainWindow.webContents.on('will-navigate', (e, url) => {
    if (url.startsWith('file:') && url !== mainWindow?.webContents.getURL()) {
      console.warn(`[Electron] Blocked navigation to dropped file: ${url}`)
      e.preventDefault()
    }
  })

  // Close-to-tray: hide the window instead of destroying it, so the tray's
  // "Show" can bring it back. Only a real Quit (menu/tray/Cmd+Q) destroys it.
  mainWindow.on('close', (e) => {
    if (!isQuitting) {
      e.preventDefault()
      mainWindow?.hide()
    }
  })

  mainWindow.on('closed', () => {
    mainWindow = null
  })
}

function getBackendPath(): string {
  if (isDev) {
    return path.resolve(__dirname, '../../..')
  }
  return path.join(process.resourcesPath, 'backend')
}

/**
 * Push the backend's current state to the renderer. Used both for the initial
 * replay after a page load and as the shape every live status event follows.
 */
function sendBackendState() {
  if (!pythonBackend || !mainWindow || mainWindow.isDestroyed()) return
  const status = pythonBackend.getStatus()
  if (status === 'ready') {
    mainWindow.webContents.send('backend-status', { status: 'ready', port: pythonBackend.getPort() })
    return
  }
  if (status === 'error') {
    const err = pythonBackend.getLastError()
    mainWindow.webContents.send('backend-status', {
      status: 'error',
      error: err?.message,
      code: err?.code,
      path: err?.path,
    })
    return
  }
  mainWindow.webContents.send('backend-status', { status: 'starting', port: pythonBackend.getPort() })
}

async function startBackend() {
  const backendPath = getBackendPath()
  // isDev distinguishes a source checkout from an installed app. The backend
  // manager needs to know: an installed app must never fall back to looking
  // for a Python interpreter, and its writable data always lives in ~/.cow.
  pythonBackend = new PythonBackend(backendPath, !isDev)

  pythonBackend.on('ready', (port: number) => {
    console.log(`[backend] ready on port ${port}`)
    mainWindow?.webContents.send('backend-status', { status: 'ready', port })
  })

  // The port isn't a constant: pickPort() may land on a fallback when the
  // preferred one is unbindable (Windows reserved ranges). Tell the renderer as
  // soon as we know, so it probes the right port from the first attempt.
  pythonBackend.on('port', (port: number) => {
    console.log(`[backend] using port ${port}`)
    mainWindow?.webContents.send('backend-status', { status: 'starting', port })
  })

  // The backend went away after having served requests. Tell the renderer so it
  // drops its cached 'ready' — otherwise the window keeps looking healthy while
  // every request fails, which is how a dead backend used to surface as a bare
  // "TypeError: Failed to fetch" in the chat.
  pythonBackend.on('lost', () => {
    console.warn('[backend] stopped responding')
    mainWindow?.webContents.send('backend-status', { status: 'lost' })
  })

  pythonBackend.on('error', (error: BackendError) => {
    // Mirror to the main-process stdout too: otherwise backend startup errors
    // are only visible in the renderer devtools, making `npm run dev` hangs
    // impossible to diagnose from the terminal.
    console.error(`[backend] error: ${error.code} — ${error.message}${error.path ? ` [${error.path}]` : ''}`)
    sendBackendState()
  })

  pythonBackend.on('log', (line: string) => {
    console.log(`[backend] ${line}`)
    mainWindow?.webContents.send('backend-log', line)
  })

  await pythonBackend.start()
}

function setupIPC() {
  // Await the port decision rather than reading the current guess: the renderer
  // usually asks before startBackend() has probed anything, and a wrong answer
  // here means it polls a port nothing will ever listen on.
  ipcMain.handle('get-backend-port', async () => {
    return pythonBackend ? pythonBackend.whenPortReady() : null
  })

  ipcMain.handle('get-backend-status', () => {
    return pythonBackend?.getStatus() ?? 'stopped'
  })

  // Pull-based access to the last failure, so the renderer can always ask why
  // startup failed instead of depending on having been subscribed at the exact
  // moment the event fired.
  ipcMain.handle('get-backend-error', () => {
    return pythonBackend?.getLastError() ?? null
  })

  // Where config.json and run.log live, so the error screen can open the folder
  // for a user whose UI never came up.
  ipcMain.handle('get-data-dir', () => {
    return pythonBackend?.getDataDir() ?? ''
  })

  ipcMain.handle('restart-backend', async () => {
    await pythonBackend?.restart()
    return true
  })

  ipcMain.handle('select-directory', async () => {
    const result = await dialog.showOpenDialog({
      properties: ['openDirectory'],
    })
    return result.canceled ? null : result.filePaths[0]
  })

  ipcMain.handle('select-file', async (_event, filters?: Electron.FileFilter[]) => {
    const result = await dialog.showOpenDialog({
      properties: ['openFile'],
      filters: filters || [{ name: 'All Files', extensions: ['*'] }],
    })
    return result.canceled ? null : result.filePaths[0]
  })

  // Open a local file with the OS default app; falls back to revealing it in
  // the file manager when no handler exists. Returns '' on success.
  ipcMain.handle('open-path', async (_event, targetPath: string) => {
    if (!targetPath) return 'empty path'
    const err = await shell.openPath(targetPath)
    if (err) shell.showItemInFolder(targetPath)
    return err
  })

  // Custom window controls (used by Windows frameless titlebar)
  ipcMain.handle('window-minimize', () => mainWindow?.minimize())
  ipcMain.handle('window-maximize', () => {
    if (!mainWindow) return false
    if (mainWindow.isMaximized()) mainWindow.unmaximize()
    else mainWindow.maximize()
    return mainWindow.isMaximized()
  })
  ipcMain.handle('window-close', () => mainWindow?.close())
  ipcMain.handle('window-is-maximized', () => mainWindow?.isMaximized() ?? false)

  // Current app version, shown in the NavRail footer.
  ipcMain.handle('get-app-version', () => app.getVersion())

  // Launch-at-login: backed by the OS login-item registry on macOS and the
  // Run registry key on Windows (both handled natively by Electron). Linux has
  // no reliable cross-desktop mechanism, so it reports/accepts nothing there.
  //
  // Windows caveat: we register our Run key WITH `args: ['--hidden']`. Per the
  // Electron docs, `openAtLogin` only reports true when getLoginItemSettings()
  // is called with the SAME `args` — so we MUST pass them here to match, or the
  // toggle "snaps back" to off (a false readback overwrites the flip). We do NOT
  // use `executableWillLaunchAtLogin`: it ignores args and reports true for ANY
  // startup entry for this exe (e.g. one added by an installer / Startup-folder
  // shortcut), which made the toggle appear ON by default. Matching args keeps
  // the default OFF and only reflects the entry this app actually created.
  const WIN_LOGIN_ARGS = ['--hidden']
  const isLaunchAtLoginEnabled = (): boolean => {
    if (isWin) return app.getLoginItemSettings({ args: WIN_LOGIN_ARGS }).openAtLogin === true
    if (isMac) return app.getLoginItemSettings().openAtLogin
    return false
  }
  ipcMain.handle('get-login-item', () => isLaunchAtLoginEnabled())
  // Returns the real outcome so the UI never lies: { ok, enabled, error }.
  // - ok=false + error: writing the login item threw (surface it, don't swallow).
  // - ok=true but enabled!=requested: the OS/policy silently refused the change.
  // The renderer shows the reason instead of just snapping the toggle back.
  ipcMain.handle('set-login-item', (_event, enabled: boolean) => {
    if (!isMac && !isWin) {
      return { ok: false, enabled: false, error: 'unsupported-platform' }
    }
    try {
      app.setLoginItemSettings({
        openAtLogin: !!enabled,
        // Start hidden/minimized so autostart is unobtrusive; the window can
        // still be brought up from the Dock/tray.
        openAsHidden: isMac ? true : undefined,
        args: isWin ? WIN_LOGIN_ARGS : undefined,
      })
    } catch (err) {
      const error = err instanceof Error ? err.message : String(err)
      console.error('[login-item] setLoginItemSettings failed:', error)
      return { ok: false, enabled: isLaunchAtLoginEnabled(), error }
    }
    const effective = isLaunchAtLoginEnabled()
    return { ok: effective === !!enabled, enabled: effective, error: '' }
  })

  // Auto-update controls (renderer-driven: check, then opt-in download/install).
  // The renderer passes its current UI language so downloads can be routed to
  // the China CDN mirror (zh) or R2 (others).
  ipcMain.handle('update-check', (_event, lang?: string) => {
    setUpdateLanguage(lang)
    // This channel is only hit by an explicit "check for update" click, so the
    // panel should re-open even if the version was previously dismissed.
    checkForUpdates(true)
  })
  ipcMain.handle('update-download', (_event, lang?: string) => {
    setUpdateLanguage(lang)
    startDownload()
  })
  ipcMain.handle('update-install', () => {
    // Let the window actually close so the app can fully quit — otherwise the
    // close-to-tray handler preventDefault()s it, the process stays alive, and
    // Squirrel.Mac can't swap the app bundle (the update silently no-ops and
    // relaunching still shows the old version).
    isQuitting = true
    // Kill the backend SYNCHRONOUSLY before handing off to the installer. On
    // Windows the NSIS silent updater deletes the old install right away, and a
    // still-running cowagent-backend.exe locks those files, aborting the update
    // with "卸载旧应用程序文件失败:2". before-quit's async stop() sends SIGTERM
    // and returns immediately (a no-op for a native Windows exe), so it loses
    // the race. stopSync() blocks until the process tree is gone. Best-effort:
    // never let a teardown hiccup block the update.
    try {
      pythonBackend?.stopSync()
    } catch {
      // ignore — proceed with the install regardless
    }
    quitAndInstall()
  })

  // Synchronous OS locale lookup (e.g. "zh-CN", "en-US"). Used by the renderer
  // to pick a sensible default UI language on first run before any paint.
  ipcMain.on('get-system-locale', (event) => {
    event.returnValue = app.getLocale() || app.getSystemLocale?.() || ''
  })

  // Show a native OS notification (e.g. a scheduler reminder or a finished
  // task). Clicking it brings the window forward and asks the renderer to open
  // the given session.
  ipcMain.handle('notify', (_event, payload: { title?: string; body?: string; sessionId?: string; silent?: boolean }) => {
    if (!Notification.isSupported() || !payload?.body) return false
    // Skip when the window is focused: the user is already watching, so a
    // notification (and sound) would just be noise, especially for short tasks.
    if (mainWindow?.isFocused()) return false
    // Use the runtime app icon if one was set (via set-app-icon), so the
    // notification matches the current window/Dock icon. Falls back to the
    // packaged icon.
    const iconOpt = getRuntimeAppIcon() || getIconPath('png')
    const n = new Notification({
      title: payload.title || app.name,
      body: payload.body,
      silent: !!payload.silent,
      ...(iconOpt ? { icon: iconOpt } : {}),
    })
    n.on('click', () => {
      if (mainWindow) {
        if (mainWindow.isMinimized()) mainWindow.restore()
        mainWindow.show()
        mainWindow.focus()
      }
      if (payload.sessionId) {
        mainWindow?.webContents.send('open-session', payload.sessionId)
      }
    })
    n.show()
    return true
  })
}

function emitMaximizeState() {
  const max = mainWindow?.isMaximized() ?? false
  mainWindow?.webContents.send('window-maximize-changed', max)
}

// Single-instance lock: focus the existing window instead of opening a second app.
const gotTheLock = app.requestSingleInstanceLock()
if (!gotTheLock) {
  app.quit()
} else {
  app.on('second-instance', () => {
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore()
      mainWindow.show()
      mainWindow.focus()
    }
  })
}

app.whenReady().then(async () => {
  // Set Dock icon on macOS (PNG is most reliable for nativeImage)
  if (process.platform === 'darwin') {
    const pngPath = getIconPath('png')
    if (pngPath) {
      const icon = nativeImage.createFromPath(pngPath)
      if (!icon.isEmpty()) {
        app.dock.setIcon(icon)
        console.log('[Electron] Dock icon set:', pngPath)
      } else {
        console.warn('[Electron] Dock icon loaded but empty:', pngPath)
      }
    } else {
      console.warn('[Electron] Dock icon not found in resources/')
    }
  }

  // The chat input's voice recording uses getUserMedia. Approval of media
  // permission requests isn't guaranteed without an explicit handler across
  // Electron versions/platforms, so allow them; other permission types keep
  // the same default allow behavior the app had without a handler.
  session.defaultSession.setPermissionRequestHandler((_wc, _permission, callback) => callback(true))

  // On macOS the Chromium-layer handler above isn't enough: getUserMedia also
  // needs system-level (TCC) microphone authorization, which only the native
  // askForMediaAccess prompt can grant. Request it up front so the first mic
  // click surfaces the system dialog instead of failing with a denied error.
  if (process.platform === 'darwin') {
    const micStatus = systemPreferences.getMediaAccessStatus('microphone')
    if (micStatus === 'not-determined') {
      systemPreferences.askForMediaAccess('microphone').catch(() => {})
    }
  }

  setupIPC()
  setupThemeIPC()
  setupHttpRelayIPC()
  setupAppIconIPC({ getWindow: () => mainWindow, getTray })
  createWindow()
  buildAppMenu(() => mainWindow)
  // No menu-bar tray on macOS — the Dock + window controls are enough there.
  // Keep the tray on Windows/Linux where minimizing to a tray icon is expected.
  if (!isMac) {
    createTray({
      getWindow: () => mainWindow,
      iconPath: getIconPath('png'),
      onQuit: () => {
        isQuitting = true
        app.quit()
      },
    })
  }
  // Re-apply a previously set icon/title before the page loads.
  applyCachedAppIcon()
  // Undo any damage the last update did to this app's shortcuts.
  repairWindowsShortcuts()
  await startBackend()

  // Wire auto-update: a first silent check a few seconds after launch (so it
  // doesn't compete with backend startup), then poll every 4 hours so a
  // long-running window still surfaces new releases. Both are automatic checks
  // (userInitiated=false): the panel auto-opens once per new version, and once
  // the user dismisses it these polls only keep the footer/menu dot lit rather
  // than re-popping the panel. autoDownload is off, so any update is opt-in.
  initUpdater(() => mainWindow)
  setTimeout(() => checkForUpdates(), 5000)
  const UPDATE_POLL_MS = 4 * 60 * 60 * 1000
  setInterval(() => checkForUpdates(), UPDATE_POLL_MS)

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow()
    } else {
      mainWindow?.show()
    }
  })
})

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit()
  }
})

app.on('before-quit', () => {
  isQuitting = true
  saveWindowState()
  destroyTray()
  pythonBackend?.stop()
})
