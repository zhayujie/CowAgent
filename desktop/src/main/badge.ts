import { app, ipcMain, nativeImage, BrowserWindow, NativeImage } from 'electron'

// Unread badge on the app icon: a red dot overlaid on the Windows taskbar
// button, the native count badge on the macOS Dock (and Unity launchers).

const DOT_SIZE = 32 // physical pixels; rendered at 16x16 DIP (scale factor 2)

let dotImage: NativeImage | null = null

// Draw an anti-aliased red dot with a white ring. Bitmap is premultiplied
// BGRA, the native layout nativeImage.createFromBitmap expects on Windows.
function buildDot(): NativeImage {
  const buf = Buffer.alloc(DOT_SIZE * DOT_SIZE * 4)
  const c = DOT_SIZE / 2
  const outer = DOT_SIZE / 2 - 1
  const inner = outer - 3
  const red = { r: 0xf2, g: 0x3f, b: 0x43 }
  for (let y = 0; y < DOT_SIZE; y++) {
    for (let x = 0; x < DOT_SIZE; x++) {
      const d = Math.hypot(x + 0.5 - c, y + 0.5 - c)
      const alpha = Math.max(0, Math.min(1, outer - d + 0.5))
      if (alpha <= 0) continue
      // Blend from the red core into the white ring across one pixel.
      const t = Math.max(0, Math.min(1, d - inner + 0.5))
      const r = red.r + (255 - red.r) * t
      const g = red.g + (255 - red.g) * t
      const b = red.b + (255 - red.b) * t
      const i = (y * DOT_SIZE + x) * 4
      buf[i] = Math.round(b * alpha)
      buf[i + 1] = Math.round(g * alpha)
      buf[i + 2] = Math.round(r * alpha)
      buf[i + 3] = Math.round(alpha * 255)
    }
  }
  return nativeImage.createFromBitmap(buf, { width: DOT_SIZE, height: DOT_SIZE, scaleFactor: 2 })
}

function applyBadge(win: BrowserWindow | null, count: number): void {
  if (process.platform === 'win32') {
    if (!win || win.isDestroyed()) return
    if (count > 0) {
      dotImage = dotImage || buildDot()
      win.setOverlayIcon(dotImage, `${count}`)
    } else {
      win.setOverlayIcon(null, '')
    }
    return
  }
  app.setBadgeCount(Math.max(0, count))
}

export function setupUnreadBadgeIPC({ getWindow }: { getWindow: () => BrowserWindow | null }): void {
  ipcMain.on('set-unread-badge', (_event, count: unknown) => {
    const n = typeof count === 'number' && Number.isFinite(count) ? Math.floor(count) : 0
    applyBadge(getWindow(), n)
  })
}
