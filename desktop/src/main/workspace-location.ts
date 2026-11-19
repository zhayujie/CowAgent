import fs from 'fs'
import os from 'os'
import path from 'path'

// Where the Agent workspace (conversations, memory, knowledge, skills) lives.
//
// It defaults to ~/cow. Any other place is recorded in a small pointer file in
// the OS app-data folder, written by the Windows installer's workspace page
// (build/installer.nsh) or by Settings when the user moves the workspace, and
// reaches the backend as COW_DEFAULT_WORKSPACE. An explicit agent_workspace in
// config.json still wins over it, as it always has.
//
// Config and credentials (~/.cow) are deliberately not relocatable.
//
// The pointer's folder name is fixed rather than derived from the app name,
// which a build may rename at runtime. COW_DEFAULT_WORKSPACE set in the
// environment overrides the pointer, for users who manage it themselves.

export const WORKSPACE_DIRNAME = 'cow'
const POINTER_DIRNAME = 'CowAgent'
const POINTER_FILENAME = 'workspace-location.json'

export interface WorkspaceLocation {
  /** Workspace used while config.json doesn't set agent_workspace. */
  workspace: string
  source: 'default' | 'custom' | 'env'
}

function appDataBase(): string {
  const home = os.homedir()
  if (process.platform === 'win32') return process.env.APPDATA || path.join(home, 'AppData', 'Roaming')
  if (process.platform === 'darwin') return path.join(home, 'Library', 'Application Support')
  return process.env.XDG_CONFIG_HOME || path.join(home, '.config')
}

export function pointerFile(): string {
  return path.join(appDataBase(), POINTER_DIRNAME, POINTER_FILENAME)
}

export function expandHome(value: string): string {
  if (value === '~' || /^~[\\/]/.test(value)) return path.join(os.homedir(), value.slice(1))
  return value
}

export function defaultWorkspace(): string {
  return path.join(os.homedir(), WORKSPACE_DIRNAME)
}

/** The workspace folder created inside a folder the user picked. */
export function workspaceForParent(parent: string): string {
  let root = expandHome(parent.trim())
  // "D:" alone means the current directory of drive D, not its root.
  if (/^[a-zA-Z]:$/.test(root)) root += path.sep
  return path.join(path.resolve(root), WORKSPACE_DIRNAME)
}

export function samePath(a: string, b: string): boolean {
  const norm = (p: string) => {
    const resolved = path.resolve(p)
    return process.platform === 'win32' || process.platform === 'darwin' ? resolved.toLowerCase() : resolved
  }
  return norm(a) === norm(b)
}

/** True when `child` is `parent` itself or lies inside it. */
export function isWithin(child: string, parent: string): boolean {
  if (samePath(child, parent)) return true
  const rel = path.relative(path.resolve(parent), path.resolve(child))
  return !!rel && !rel.startsWith('..') && !path.isAbsolute(rel)
}

// The installer writes UTF-16LE with a BOM (NSIS can't write UTF-8); the app
// writes UTF-8. Accept both.
function readPointer(): string | null {
  try {
    const buf = fs.readFileSync(pointerFile())
    const text =
      buf.length >= 2 && buf[0] === 0xff && buf[1] === 0xfe
        ? buf.toString('utf16le', 2)
        : buf.toString('utf8').replace(/^\uFEFF/, '')
    const workspace = JSON.parse(text)?.workspace
    if (typeof workspace === 'string' && workspace.trim()) {
      const resolved = expandHome(workspace.trim())
      if (path.isAbsolute(resolved)) return path.resolve(resolved)
    }
  } catch {
    // No pointer, or an unreadable one: use the default location.
  }
  return null
}

function resolveLocation(): WorkspaceLocation {
  const fromEnv = (process.env.COW_DEFAULT_WORKSPACE || '').trim()
  if (fromEnv) return { workspace: path.resolve(expandHome(fromEnv)), source: 'env' }
  const custom = readPointer()
  return custom ? { workspace: custom, source: 'custom' } : { workspace: defaultWorkspace(), source: 'default' }
}

let current: WorkspaceLocation | null = null

/**
 * The location in effect for this process. Fixed once read: changing it
 * relaunches the app, so nothing derived from it goes stale.
 */
export function workspaceLocation(): WorkspaceLocation {
  if (!current) current = resolveLocation()
  return current
}

/** Environment that points a spawned backend at this workspace. */
export function workspaceLocationEnv(): Record<string, string> {
  return { COW_DEFAULT_WORKSPACE: workspaceLocation().workspace }
}

/**
 * Record `workspace` for the next launch. ~/cow is the default, so choosing it
 * removes the pointer instead.
 */
export function writePointer(workspace: string): void {
  const file = pointerFile()
  if (samePath(workspace, defaultWorkspace())) {
    fs.rmSync(file, { force: true })
    return
  }
  fs.mkdirSync(path.dirname(file), { recursive: true })
  const tmp = `${file}.${process.pid}.tmp`
  fs.writeFileSync(tmp, JSON.stringify({ workspace: path.resolve(workspace) }, null, 2), 'utf8')
  fs.renameSync(tmp, file)
}
