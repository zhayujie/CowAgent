import { app, BrowserWindow, session, shell, ipcMain, dialog, nativeImage, Notification } from 'electron'
import path from 'path'
import fs from 'fs'
import http from 'http'
import { PythonBackend } from './python-manager'
import { buildAppMenu } from './menu'
import { createTray, destroyTray, getTray } from './tray'
import { initUpdater, checkForUpdates, startDownload, quitAndInstall, setUpdateLanguage } from './updater'
import { setupThemeIPC, loadAppConfig } from './themes'
import { setupHttpRelayIPC } from './http-relay'
import { setupAppIconIPC, applyCachedAppIcon } from './app-icon'

// Force the product name so the Dock/menu shows the app name even in dev mode,
// where the default Electron binary would otherwise report "Electron". The name
// can be overridden by the bundled app-config (appName); defaults to CowAgent.
app.setName(loadAppConfig()?.appName || 'CowAgent')

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

  mainWindow.once('ready-to-show', () => {
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

async function startBackend() {
  const backendPath = getBackendPath()
  pythonBackend = new PythonBackend(backendPath)

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

  pythonBackend.on('error', (error: string) => {
    // Mirror to the main-process stdout too: otherwise backend startup errors
    // are only visible in the renderer devtools, making `npm run dev` hangs
    // impossible to diagnose from the terminal.
    console.error(`[backend] error: ${error}`)
    mainWindow?.webContents.send('backend-status', { status: 'error', error })
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
    quitAndInstall()
  })

  // Synchronous OS locale lookup (e.g. "zh-CN", "en-US"). Used by the renderer
  // to pick a sensible default UI language on first run before any paint.
  ipcMain.on('get-system-locale', (event) => {
    event.returnValue = app.getLocale() || app.getSystemLocale?.() || ''
  })

  // Show a native OS notification (e.g. a scheduler reminder). Clicking it
  // brings the window forward and asks the renderer to open the given session.
  ipcMain.handle('notify', (_event, payload: { title?: string; body?: string; sessionId?: string }) => {
    if (!Notification.isSupported() || !payload?.body) return false
    const n = new Notification({ title: payload.title || app.name, body: payload.body })
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
