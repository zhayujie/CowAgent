import { app, Menu, BrowserWindow, shell } from 'electron'
import type { MenuItemConstructorOptions } from 'electron'
import { loadAppConfig } from './themes'

const isMac = process.platform === 'darwin'
const SKILL_HUB_URL = 'https://skills.cowagent.ai/'
const DEFAULT_DOCS_URL = 'https://docs.cowagent.ai'

// Send a menu-triggered action to the renderer (e.g. new chat, open settings).
function emit(win: BrowserWindow | null, action: string) {
  win?.webContents.send('menu-action', action)
}

/**
 * Build a minimal, purpose-built application menu. We intentionally drop most of
 * Electron's verbose defaults and keep only items that are actually useful for
 * this app, plus the shortcuts users expect (New Chat, Settings, Reload, etc).
 */
export function buildAppMenu(getWindow: () => BrowserWindow | null) {
  const win = () => getWindow()

  const appMenu: MenuItemConstructorOptions[] = isMac
    ? [
        {
          label: app.name,
          submenu: [
            { role: 'about' },
            { type: 'separator' },
            { label: 'Settings…', accelerator: 'Cmd+,', click: () => emit(win(), 'open-settings') },
            { type: 'separator' },
            { role: 'hide' },
            { role: 'hideOthers' },
            { role: 'unhide' },
            { type: 'separator' },
            { role: 'quit' },
          ],
        },
      ]
    : []

  const fileMenu: MenuItemConstructorOptions = {
    label: 'File',
    submenu: [
      { label: 'New Chat', accelerator: 'CmdOrCtrl+N', click: () => emit(win(), 'new-chat') },
      ...(!isMac
        ? ([
            { label: 'Settings', accelerator: 'Ctrl+,', click: () => emit(win(), 'open-settings') },
            { type: 'separator' },
            { role: 'quit' },
          ] as MenuItemConstructorOptions[])
        : []),
    ],
  }

  const editMenu: MenuItemConstructorOptions = {
    label: 'Edit',
    submenu: [
      { role: 'undo' },
      { role: 'redo' },
      { type: 'separator' },
      { role: 'cut' },
      { role: 'copy' },
      { role: 'paste' },
      { role: 'selectAll' },
    ],
  }

  const viewMenu: MenuItemConstructorOptions = {
    label: 'View',
    submenu: [
      { role: 'reload' },
      { role: 'toggleDevTools' },
      { type: 'separator' },
      { role: 'resetZoom' },
      { role: 'zoomIn' },
      { role: 'zoomOut' },
      { type: 'separator' },
      { role: 'togglefullscreen' },
    ],
  }

  const windowMenu: MenuItemConstructorOptions = {
    label: 'Window',
    submenu: [
      { role: 'minimize' },
      ...(isMac ? ([{ role: 'zoom' }] as MenuItemConstructorOptions[]) : []),
      { type: 'separator' },
      // Explicit Close so Cmd/Ctrl+W reliably triggers our close-to-tray hide.
      { label: 'Close Window', accelerator: 'CmdOrCtrl+W', click: () => win()?.close() },
    ],
  }

  const appConfig = loadAppConfig()
  const docsUrl = typeof appConfig?.docsUrl === 'string' ? appConfig.docsUrl.trim() : DEFAULT_DOCS_URL
  const linkItems: MenuItemConstructorOptions[] = [
    ...(docsUrl ? [{ label: 'Documentation', click: () => shell.openExternal(docsUrl) }] : []),
    ...(appConfig?.skillHub !== false
      ? [{ label: 'Skill Hub', click: () => shell.openExternal(SKILL_HUB_URL) }]
      : []),
  ]
  const helpMenu: MenuItemConstructorOptions = {
    label: 'Help',
    submenu: [
      { label: 'View Logs', click: () => emit(win(), 'view-logs') },
      ...(linkItems.length ? [{ type: 'separator' } as MenuItemConstructorOptions, ...linkItems] : []),
    ],
  }

  const template: MenuItemConstructorOptions[] = [
    ...appMenu,
    fileMenu,
    editMenu,
    viewMenu,
    windowMenu,
    helpMenu,
  ]

  Menu.setApplicationMenu(Menu.buildFromTemplate(template))
}
