import { contextBridge, ipcRenderer } from 'electron'

contextBridge.exposeInMainWorld('electronAPI', {
  getBackendPort: () => ipcRenderer.invoke('get-backend-port'),
  getBackendStatus: () => ipcRenderer.invoke('get-backend-status'),
  getBackendError: () => ipcRenderer.invoke('get-backend-error'),
  getDataDir: () => ipcRenderer.invoke('get-data-dir') as Promise<string>,
  restartBackend: () => ipcRenderer.invoke('restart-backend'),
  selectDirectory: () => ipcRenderer.invoke('select-directory'),
  selectFile: (filters?: Electron.FileFilter[]) => ipcRenderer.invoke('select-file', filters),
  openPath: (targetPath: string) => ipcRenderer.invoke('open-path', targetPath) as Promise<string>,

  // Each listener registrar returns an unsubscribe fn so renderers can clean
  // up on unmount / effect re-run and avoid accumulating duplicate handlers.
  onBackendStatus: (
    callback: (data: { status: string; port?: number; error?: string; code?: string; path?: string }) => void,
  ) => {
    const handler = (
      _event: unknown,
      data: { status: string; port?: number; error?: string; code?: string; path?: string },
    ) => callback(data)
    ipcRenderer.on('backend-status', handler)
    return () => ipcRenderer.removeListener('backend-status', handler)
  },

  onBackendLog: (callback: (line: string) => void) => {
    const handler = (_event: unknown, line: string) => callback(line)
    ipcRenderer.on('backend-log', handler)
    return () => ipcRenderer.removeListener('backend-log', handler)
  },

  // Window controls (custom titlebar on Windows)
  windowMinimize: () => ipcRenderer.invoke('window-minimize'),
  windowMaximize: () => ipcRenderer.invoke('window-maximize'),
  windowClose: () => ipcRenderer.invoke('window-close'),
  windowIsMaximized: () => ipcRenderer.invoke('window-is-maximized'),
  onMaximizeChange: (callback: (maximized: boolean) => void) => {
    const handler = (_event: unknown, max: boolean) => callback(max)
    ipcRenderer.on('window-maximize-changed', handler)
    return () => ipcRenderer.removeListener('window-maximize-changed', handler)
  },

  // App menu / shortcut actions forwarded from the main process.
  onMenuAction: (callback: (action: string) => void) => {
    const handler = (_event: unknown, action: string) => callback(action)
    ipcRenderer.on('menu-action', handler)
    return () => ipcRenderer.removeListener('menu-action', handler)
  },

  // Current app version (e.g. "0.0.5"), shown in the NavRail footer.
  getAppVersion: () => ipcRenderer.invoke('get-app-version'),

  // Launch-at-login toggle (macOS + Windows). get returns the effective state;
  // set returns the real outcome so the UI can surface refusals/errors.
  getLoginItemEnabled: () => ipcRenderer.invoke('get-login-item') as Promise<boolean>,
  setLoginItemEnabled: (enabled: boolean) =>
    ipcRenderer.invoke('set-login-item', enabled) as Promise<{
      ok: boolean
      enabled: boolean
      error: string
    }>,

  // Themes (bundled + user themes from ~/.cow/themes), assets inlined.
  listThemes: () => ipcRenderer.invoke('themes-list') as Promise<Record<string, unknown>[]>,
  getThemesDir: () => ipcRenderer.invoke('themes-dir') as Promise<string>,
  // Optional app config (first-run default theme + display name). Null in
  // the standard build.
  getAppConfig: () =>
    ipcRenderer.invoke('app-config-get') as Promise<{ defaultTheme?: string; appName?: string } | null>,

  // Generic HTTPS relay via the main process (bypasses the renderer's CORS
  // restrictions for external endpoints). Optional extensions may use it.
  httpRelay: (req: {
    url: string
    method?: string
    headers?: Record<string, string>
    body?: string
  }) =>
    ipcRenderer.invoke('http-relay', req) as Promise<{
      ok: boolean
      status: number
      headers: Record<string, string>
      body: string
    }>,

  // Auto-update: trigger checks/download/install and subscribe to status. The
  // optional lang routes installer downloads to the China CDN mirror (zh) or R2.
  checkForUpdate: (lang?: string) => ipcRenderer.invoke('update-check', lang),
  downloadUpdate: (lang?: string) => ipcRenderer.invoke('update-download', lang),
  installUpdate: () => ipcRenderer.invoke('update-install'),
  onUpdateStatus: (callback: (status: unknown) => void) => {
    const handler = (_event: unknown, status: unknown) => callback(status)
    ipcRenderer.on('update-status', handler)
    return () => ipcRenderer.removeListener('update-status', handler)
  },

  setAppIcon: (iconUrl: string, icoUrl?: string) =>
    ipcRenderer.invoke('set-app-icon', iconUrl, icoUrl) as Promise<boolean>,
  setAppTitle: (title: string) => ipcRenderer.invoke('set-app-title', title) as Promise<boolean>,

  // Show a native OS notification; clicking it focuses the window and asks the
  // renderer (via onOpenSession) to open the given session.
  notify: (payload: { title?: string; body?: string; sessionId?: string; silent?: boolean }) =>
    ipcRenderer.invoke('notify', payload) as Promise<boolean>,
  onOpenSession: (callback: (sessionId: string) => void) => {
    const handler = (_event: unknown, sessionId: string) => callback(sessionId)
    ipcRenderer.on('open-session', handler)
    return () => ipcRenderer.removeListener('open-session', handler)
  },

  platform: process.platform,
  // OS UI language (e.g. "zh-CN"), read synchronously so the renderer can pick
  // a default language on first run. Falls back to '' if unavailable.
  systemLocale: (() => {
    try {
      return ipcRenderer.sendSync('get-system-locale') as string
    } catch {
      return ''
    }
  })(),
})
