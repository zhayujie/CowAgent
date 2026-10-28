import path from 'path'
import os from 'os'
import fs from 'fs'

// The Windows installer lets the user pick a data root (default %USERPROFILE%)
// and records it here. The file lives at a fixed path, independent of the app
// name, because every desktop build on the machine shares the same data dir.
// build/installer.nsh writes it as UTF-16LE with a BOM so non-ASCII user
// folders survive the trip.
function dataRootPointerPath(): string | null {
  const appData = process.env.APPDATA
  return appData ? path.join(appData, 'CowAgent', 'data-root') : null
}

function readDataRootPointer(): string | null {
  if (process.platform !== 'win32') return null
  const pointer = dataRootPointerPath()
  if (!pointer) return null
  try {
    const buf = fs.readFileSync(pointer)
    const text = buf[0] === 0xff && buf[1] === 0xfe ? buf.subarray(2).toString('utf16le') : buf.toString('utf8')
    const root = text.trim()
    if (!root || !path.isAbsolute(root)) return null
    // Keeping the default on the installer page is the same as no choice.
    const home = os.homedir()
    return path.resolve(root).toLowerCase() === path.resolve(home).toLowerCase() ? null : root
  } catch {
    return null
  }
}

// Installs without a recorded choice (every install before the picker existed,
// macOS, dev runs) keep the home directory, so nothing moves on upgrade.
const chosenRoot = readDataRootPointer()

// Writable data for the packaged app: config.json, run.log, themes, caches.
export const COW_DATA_DIR = path.join(chosenRoot || os.homedir(), '.cow')

// Agent workspace under the chosen root, matching the backend's ~/cow default.
// Null when the user kept the default root, so the backend default applies.
export const COW_WORKSPACE_DIR = chosenRoot ? path.join(chosenRoot, 'cow') : null
