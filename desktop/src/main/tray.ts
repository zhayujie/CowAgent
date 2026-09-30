import { app, Tray, Menu, BrowserWindow, nativeImage } from 'electron'

let tray: Tray | null = null

interface TrayDeps {
  getWindow: () => BrowserWindow | null
  // Colored icon used on Windows/Linux trays.
  iconPath?: string
  // Called when the user picks "Quit" so the app can fully exit.
  onQuit: () => void
}

// Build a system tray icon with a minimal menu (Windows/Linux only — macOS
// uses the Dock instead). Lets users restore the window after closing it to the
// background and start a new chat quickly.
export function createTray({ getWindow, iconPath, onQuit }: TrayDeps): Tray | null {
  if (tray) return tray
  if (!iconPath) return null

  let image = nativeImage.createFromPath(iconPath)
  if (image.isEmpty()) return null
  // Tray icons render small; resize to avoid an oversized image on some platforms.
  image = image.resize({ width: 18, height: 18 })

  tray = new Tray(image)
  tray.setToolTip(app.name)

  const showWindow = () => {
    const win = getWindow()
    if (!win) return
    if (win.isMinimized()) win.restore()
    win.show()
    win.focus()
  }

  const contextMenu = Menu.buildFromTemplate([
    { label: `Show ${app.name}`, click: showWindow },
    {
      label: 'New Chat',
      click: () => {
        showWindow()
        getWindow()?.webContents.send('menu-action', 'new-chat')
      },
    },
    { type: 'separator' },
    { label: 'Quit', click: onQuit },
  ])
  tray.setContextMenu(contextMenu)

  // Single click restores the window (common Windows/Linux behavior).
  tray.on('click', showWindow)

  return tray
}

// Live tray instance (Windows/Linux only), so its icon can be updated at
// runtime. Null on macOS or before createTray().
export function getTray(): Tray | null {
  return tray
}

export function destroyTray() {
  tray?.destroy()
  tray = null
}
