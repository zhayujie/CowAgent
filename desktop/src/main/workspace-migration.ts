import { app, BrowserWindow, dialog, ipcMain } from 'electron'
import fs from 'fs'
import path from 'path'
import {
  defaultWorkspace,
  expandHome,
  isWithin,
  samePath,
  workspaceForParent,
  workspaceLocation,
  writePointer,
} from './workspace-location'

// Settings > Workspace location: inspect the workspace, check a new place and
// move it there. The move runs with the backend stopped and only switches over once every file is
// verified at the destination, so a failure leaves the old workspace exactly as
// it was. Applying a new location always ends in a relaunch.
//
// Only the workspace moves. Config and credentials stay in their fixed folder,
// which a target may neither sit in nor contain.

const fsp = fs.promises
const isWin = process.platform === 'win32'

export interface WorkspaceInfo {
  /** The workspace actually in use. */
  workspace: string
  /**
   * Where its files are. A move made from the web console leaves `workspace`
   * as a link to the new place; this is what the user is shown.
   */
  realWorkspace: string
  /** config.json sets agent_workspace, which wins over the pointer. */
  pinnedByConfig: boolean
  managedByEnv: boolean
}

export type WorkspaceErrorCode =
  | 'busy'
  | 'managed_by_env'
  | 'same_location'
  | 'not_absolute'
  | 'inside_install_dir'
  | 'protected_dir'
  | 'nested'
  | 'not_writable'
  | 'insufficient_space'
  | 'target_has_data'
  | 'copy_failed'
  | 'verify_failed'
  | 'finalize_failed'

export interface CheckResult {
  ok: boolean
  code?: WorkspaceErrorCode
  detail?: string
  /** The workspace folder the picked folder leads to. */
  target: string
  requiredBytes: number
  freeBytes: number | null
}

export interface ApplyOptions {
  /** The folder the user picked; the workspace goes into a subfolder of it. */
  parent: string
  /** Leave a link at the old path so absolute paths in history keep working. */
  keepLink: boolean
}

export interface ApplyResult {
  ok: boolean
  code?: WorkspaceErrorCode
  detail?: string
  /** Non-fatal leftovers, as "<kind>:<path>" (kind: cleanup | link). */
  warnings: string[]
}

export interface MigrationProgress {
  phase: 'stopping' | 'scanning' | 'copying' | 'finishing'
  doneBytes: number
  totalBytes: number
  doneFiles: number
  totalFiles: number
}

export interface WorkspaceMigrationDeps {
  getWindow: () => BrowserWindow | null
  /** The config.json the backend reads. */
  configPath: () => string
  /** Folders holding config and credentials, which must stay out of the workspace. */
  protectedDirs: () => string[]
  /** Stop the backend and wait until its process (and its file handles) are gone. */
  stopBackend: () => Promise<void>
  startBackend: () => Promise<void>
}

class WorkspaceError extends Error {
  constructor(
    readonly code: WorkspaceErrorCode,
    detail = '',
  ) {
    super(detail)
  }
}

// --------------------------------------------------------------- filesystem

// Files the OS drops into any folder; they don't make a folder "used".
const NOISE_FILES = new Set(['.DS_Store', 'Thumbs.db', 'desktop.ini'])

function readJson(file: string): Record<string, unknown> | null {
  try {
    const value = JSON.parse(fs.readFileSync(file, 'utf8').replace(/^\uFEFF/, ''))
    return value && typeof value === 'object' && !Array.isArray(value) ? value : null
  } catch {
    return null
  }
}

function writeFileAtomic(file: string, text: string): void {
  const tmp = `${file}.${process.pid}.tmp`
  fs.writeFileSync(tmp, text, 'utf8')
  fs.renameSync(tmp, file)
}

function lstatOrNull(p: string): fs.Stats | null {
  try {
    return fs.lstatSync(p)
  } catch {
    return null
  }
}

/** Remove the link itself, never what it points to. rmSync rejects junctions with EISDIR. */
function removeLink(p: string): void {
  try {
    fs.unlinkSync(p)
  } catch (err) {
    if ((err as NodeJS.ErrnoException).code === 'ENOENT') return
    fs.rmdirSync(p)
  }
}

function hasData(dir: string): boolean {
  const st = lstatOrNull(dir)
  if (!st) return false
  if (!st.isDirectory() && !st.isSymbolicLink()) return true
  try {
    return fs.readdirSync(dir).some((name) => !NOISE_FILES.has(name))
  } catch {
    return false
  }
}

/** A link at `p` that resolves to `target`, i.e. one this feature left behind. */
function isLinkTo(p: string, target: string): boolean {
  const st = lstatOrNull(p)
  if (!st?.isSymbolicLink()) return false
  try {
    return samePath(fs.realpathSync(p), fs.realpathSync(target))
  } catch {
    return false
  }
}

function realpathOr(p: string): string {
  try {
    return fs.realpathSync(p)
  } catch {
    return p
  }
}

interface TreeStats {
  files: number
  bytes: number
}

async function scanTree(root: string): Promise<TreeStats> {
  const stats: TreeStats = { files: 0, bytes: 0 }
  const walk = async (p: string): Promise<void> => {
    let st: fs.Stats
    try {
      st = await fsp.lstat(p)
    } catch {
      return
    }
    if (st.isDirectory()) {
      let names: string[] = []
      try {
        names = await fsp.readdir(p)
      } catch {
        return
      }
      for (const name of names) await walk(path.join(p, name))
      return
    }
    stats.files += 1
    if (!st.isSymbolicLink()) stats.bytes += st.size
  }
  await walk(root)
  return stats
}

async function copyTree(src: string, dst: string, onFile: (bytes: number) => void): Promise<void> {
  const st = await fsp.lstat(src)
  if (st.isSymbolicLink()) {
    const target = await fsp.readlink(src)
    let isDir = false
    try {
      isDir = (await fsp.stat(src)).isDirectory()
    } catch {
      // dangling link: recreate it as-is
    }
    try {
      await fsp.symlink(target, dst, isDir ? (isWin ? 'junction' : 'dir') : 'file')
    } catch (err) {
      // File symlinks need a privilege on Windows; keep the content instead.
      if (isDir) throw new Error(`${src}: ${(err as Error).message}`)
      await fsp.copyFile(src, dst)
    }
    onFile(0)
    return
  }
  if (st.isDirectory()) {
    await fsp.mkdir(dst, { recursive: true })
    for (const name of await fsp.readdir(src)) {
      await copyTree(path.join(src, name), path.join(dst, name), onFile)
    }
    return
  }
  try {
    await fsp.copyFile(src, dst, fs.constants.COPYFILE_EXCL)
  } catch (err) {
    throw new Error(`${src}: ${(err as Error).message}`)
  }
  try {
    await fsp.utimes(dst, st.atime, st.mtime)
  } catch {
    // timestamps are a nicety
  }
  onFile(st.size)
}

async function freeBytes(dir: string): Promise<number | null> {
  // statfs arrived in Node 18.15; the Win7 build's Electron predates it.
  const statfs = (fsp as unknown as { statfs?: (p: string) => Promise<{ bavail: number; bsize: number }> }).statfs
  if (typeof statfs !== 'function') return null
  try {
    const s = await statfs(dir)
    return s.bavail * s.bsize
  } catch {
    return null
  }
}

function sameDevice(a: string, b: string): boolean {
  try {
    return fs.statSync(a).dev === fs.statSync(b).dev
  } catch {
    return false
  }
}

function installDirs(): string[] {
  if (!app.isPackaged) return []
  const dirs = [path.dirname(app.getPath('exe'))]
  if (process.platform === 'darwin') dirs.push(path.resolve(process.resourcesPath, '..', '..'))
  return dirs
}

// ------------------------------------------------------------------ location

function configuredWorkspace(configPath: string): string | null {
  const value = readJson(configPath)?.agent_workspace
  if (typeof value !== 'string' || !value.trim()) return null
  return path.resolve(path.dirname(configPath), expandHome(value.trim()))
}

export function currentWorkspaceInfo(deps: WorkspaceMigrationDeps): WorkspaceInfo {
  const loc = workspaceLocation()
  const configured = configuredWorkspace(deps.configPath())
  const workspace = configured ?? loc.workspace
  return {
    workspace,
    realWorkspace: lstatOrNull(workspace)?.isSymbolicLink() ? realpathOr(workspace) : workspace,
    pinnedByConfig: configured !== null,
    managedByEnv: loc.source === 'env',
  }
}

export async function checkTarget(deps: WorkspaceMigrationDeps, parent: string): Promise<CheckResult> {
  const info = currentWorkspaceInfo(deps)
  const raw = expandHome((parent || '').trim())
  const target = path.isAbsolute(raw) ? workspaceForParent(raw) : raw
  const result: CheckResult = { ok: false, target, requiredBytes: 0, freeBytes: null }
  const fail = (code: WorkspaceErrorCode, detail = ''): CheckResult => ({ ...result, code, detail })

  if (info.managedByEnv) return fail('managed_by_env')
  if (!path.isAbsolute(raw)) return fail('not_absolute')
  if (samePath(target, info.workspace) || samePath(target, info.realWorkspace)) return fail('same_location')

  for (const dir of installDirs()) {
    if (isWithin(target, dir)) return fail('inside_install_dir', dir)
  }
  // The Agent's file tools reach everything in the workspace.
  for (const dir of deps.protectedDirs()) {
    const real = realpathOr(dir)
    if (isWithin(target, dir) || isWithin(dir, target) || isWithin(target, real) || isWithin(real, target)) {
      return fail('protected_dir', dir)
    }
  }

  const source = lstatOrNull(info.workspace) ? realpathOr(info.workspace) : null
  // A link we left at the target that points back here is replaced, not nested.
  const linkBack = source !== null && isLinkTo(target, source)
  if (source && !linkBack) {
    for (const src of [info.workspace, source]) {
      if (isWithin(target, src) || isWithin(src, target)) return fail('nested', src)
    }
  }

  if (hasData(target) && !linkBack) return fail('target_has_data')

  const root = path.dirname(target)
  try {
    fs.mkdirSync(root, { recursive: true })
    const probe = path.join(root, `.cow-write-test-${process.pid}`)
    fs.writeFileSync(probe, '')
    fs.rmSync(probe, { force: true })
  } catch (err) {
    return fail('not_writable', (err as Error).message)
  }

  if (source) {
    // A rename on the same drive needs no room; anything else is a full copy.
    if (!(samePath(source, info.workspace) && sameDevice(source, root))) {
      result.requiredBytes = (await scanTree(source)).bytes
    }
    result.freeBytes = await freeBytes(root)
    if (result.freeBytes !== null && result.requiredBytes > result.freeBytes) return fail('insufficient_space')
  }

  return { ...result, ok: true }
}

// ------------------------------------------------------------------- moving

// Absolute workspace paths that lived under the old workspace move with it.
function rebase(value: unknown, from: string, to: string): unknown {
  if (typeof value !== 'string' || !value.trim()) return value
  const abs = path.resolve(expandHome(value.trim()))
  if (!isWithin(abs, from)) return value
  return path.join(to, path.relative(from, abs))
}

interface Rewrite {
  file: string
  original: string
}

function rewriteJson(file: string, edit: (value: Record<string, unknown>) => boolean, done: Rewrite[]): void {
  const value = readJson(file)
  if (!value || !edit(value)) return
  const original = fs.readFileSync(file, 'utf8')
  writeFileAtomic(file, JSON.stringify(value, null, 2) + '\n')
  done.push({ file, original })
}

/** Point the backend at `target`: the pointer, plus agent_workspace when config.json pins one. */
function applyLocation(deps: WorkspaceMigrationDeps, info: WorkspaceInfo, target: string, rewrites: Rewrite[]): void {
  if (info.pinnedByConfig) {
    rewriteJson(
      deps.configPath(),
      (cfg) => {
        cfg.agent_workspace = target
        return true
      },
      rewrites,
    )
  }
  writePointer(target)
}

async function migrate(
  deps: WorkspaceMigrationDeps,
  info: WorkspaceInfo,
  target: string,
  keepLink: boolean,
  report: (p: MigrationProgress) => void,
): Promise<string[]> {
  const from = info.workspace
  const exists = lstatOrNull(from) !== null
  const realFrom = exists ? realpathOr(from) : from
  // A link an earlier move left at ~/cow dangles once the workspace moves on,
  // so it is re-pointed (or dropped) afterwards.
  const home = defaultWorkspace()
  const homeLink = !samePath(home, from) && exists && isLinkTo(home, realFrom) ? home : null

  const progress: MigrationProgress = { phase: 'stopping', doneBytes: 0, totalBytes: 0, doneFiles: 0, totalFiles: 0 }
  report(progress)
  await deps.stopBackend()

  progress.phase = 'scanning'
  report(progress)
  const stats = exists ? await scanTree(realFrom) : { files: 0, bytes: 0 }
  progress.totalBytes = stats.bytes
  progress.totalFiles = stats.files

  let method: 'rename' | 'copy' | null = null
  const rewrites: Rewrite[] = []
  let partial = false
  try {
    progress.phase = 'copying'
    report(progress)
    fs.mkdirSync(path.dirname(target), { recursive: true })
    // Only a link back here or OS noise files can be in the way: checkTarget
    // refuses a target that holds anything else.
    const st = lstatOrNull(target)
    if (st?.isSymbolicLink()) removeLink(target)
    else if (st) fs.rmSync(target, { recursive: true, force: true })

    if (exists) {
      if (samePath(realFrom, from) && sameDevice(from, path.dirname(target))) {
        try {
          fs.renameSync(from, target)
          method = 'rename'
          progress.doneBytes = stats.bytes
          progress.doneFiles = stats.files
          report(progress)
        } catch {
          // Something still holds a file: fall back to copying.
        }
      }
      if (!method) {
        partial = true
        try {
          await copyTree(realFrom, target, (bytes) => {
            progress.doneBytes += bytes
            progress.doneFiles += 1
            report(progress)
          })
        } catch (err) {
          throw new WorkspaceError('copy_failed', (err as Error).message)
        }
        const copied = await scanTree(target)
        if (copied.files !== stats.files || copied.bytes !== stats.bytes) {
          throw new WorkspaceError(
            'verify_failed',
            `${realFrom}: ${stats.files} files / ${stats.bytes} bytes, copied ${copied.files} / ${copied.bytes}`,
          )
        }
        method = 'copy'
        partial = false
      }
    }

    progress.phase = 'finishing'
    report(progress)
    try {
      rewriteJson(
        path.join(target, 'agents', 'team.json'),
        (team) => {
          if (!Array.isArray(team.agents)) return false
          let changed = false
          for (const agent of team.agents as Record<string, unknown>[]) {
            if (!agent || typeof agent !== 'object' || !('workspace' in agent)) continue
            const next = rebase(agent.workspace, from, target)
            if (next !== agent.workspace) {
              agent.workspace = next
              changed = true
            }
          }
          return changed
        },
        rewrites,
      )
      applyLocation(deps, info, target, rewrites)
    } catch (err) {
      throw new WorkspaceError('finalize_failed', (err as Error).message)
    }
  } catch (err) {
    for (const r of rewrites.reverse()) {
      try {
        writeFileAtomic(r.file, r.original)
      } catch {
        // best effort; the move below is what matters
      }
    }
    try {
      if (method === 'rename') fs.renameSync(target, from)
      else if (method === 'copy' || partial) fs.rmSync(target, { recursive: true, force: true })
    } catch {
      // leave it; the source is untouched for copies
    }
    throw err
  }

  // The new location is live from here on; what follows only tidies up.
  const warnings: string[] = []
  if (method === 'copy') {
    try {
      await fsp.rm(realFrom, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 })
      if (!samePath(realFrom, from)) removeLink(from)
    } catch {
      warnings.push(`cleanup:${realFrom}`)
      return warnings
    }
  }
  if (!method) return warnings
  const linkPaths = keepLink ? [from, ...(homeLink ? [homeLink] : [])] : homeLink ? [homeLink] : []
  for (const linkPath of linkPaths) {
    try {
      if (lstatOrNull(linkPath)?.isSymbolicLink()) removeLink(linkPath)
      if (!keepLink || lstatOrNull(linkPath)) continue
      fs.symlinkSync(target, linkPath, isWin ? 'junction' : 'dir')
    } catch {
      warnings.push(`link:${linkPath}`)
    }
  }
  return warnings
}

// ---------------------------------------------------------------------- IPC

export function setupWorkspaceMigrationIPC(deps: WorkspaceMigrationDeps): void {
  let busy = false

  ipcMain.handle('workspace-location-info', () => currentWorkspaceInfo(deps))

  ipcMain.handle('workspace-location-usage', async () => (await scanTree(currentWorkspaceInfo(deps).realWorkspace)).bytes)

  ipcMain.handle('workspace-location-pick', async (_event, title?: string) => {
    const win = deps.getWindow()
    const opts: Electron.OpenDialogOptions = {
      title,
      defaultPath: path.dirname(currentWorkspaceInfo(deps).realWorkspace),
      properties: ['openDirectory', 'createDirectory'],
    }
    const result = win ? await dialog.showOpenDialog(win, opts) : await dialog.showOpenDialog(opts)
    return result.canceled ? null : result.filePaths[0] || null
  })

  ipcMain.handle('workspace-location-check', (_event, parent: string) => checkTarget(deps, parent))

  ipcMain.handle('workspace-location-apply', async (_event, opts: ApplyOptions): Promise<ApplyResult> => {
    if (busy) return { ok: false, code: 'busy', warnings: [] }
    busy = true
    try {
      const check = await checkTarget(deps, opts.parent)
      if (!check.ok) return { ok: false, code: check.code, detail: check.detail, warnings: [] }
      const info = currentWorkspaceInfo(deps)

      let last = 0
      const report = (p: MigrationProgress) => {
        const now = Date.now()
        if (p.phase === 'copying' && p.doneBytes < p.totalBytes && now - last < 100) return
        last = now
        deps.getWindow()?.webContents.send('workspace-location-progress', { ...p })
      }
      try {
        const warnings = await migrate(deps, info, check.target, opts.keepLink, report)
        return { ok: true, warnings }
      } catch (err) {
        console.error('[workspace-location] migration failed:', err)
        await deps.startBackend().catch(() => {})
        const code = err instanceof WorkspaceError ? err.code : 'copy_failed'
        return { ok: false, code, detail: (err as Error).message, warnings: [] }
      }
    } finally {
      busy = false
    }
  })

  // app.exit skips before-quit, which is what normally stops the backend.
  ipcMain.handle('workspace-location-relaunch', async () => {
    await deps.stopBackend().catch(() => {})
    app.relaunch({ args: process.argv.slice(1).filter((arg) => arg !== '--hidden') })
    app.exit(0)
  })
}
