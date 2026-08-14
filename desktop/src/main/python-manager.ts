import { ChildProcess, spawn, execFileSync } from 'child_process'
import { EventEmitter } from 'events'
import path from 'path'
import os from 'os'
import fs from 'fs'
import http from 'http'
import net from 'net'

// Writable data dir for the packaged app (config.json, run.log, user data).
// Lives in the user's home so it survives app updates and avoids writing into
// the read-only app bundle. Source/dev runs keep using the repo CWD instead.
const COW_DATA_DIR = path.join(os.homedir(), '.cow')

// Preferred port for the desktop backend. Deliberately not 9899 (the web
// console's default) so a source-run `python app.py` never collides with the
// packaged app. The renderer starts by probing this port, but it is only a
// PREFERENCE, not a guarantee — see pickPort() for why, and note that the real
// port is always published to the renderer via the 'port' event / whenPortReady.
export const DESKTOP_BACKEND_PORT = 9876

// Tried in order when the preferred port can't be bound. Windows reserves
// pseudo-random port ranges for Hyper-V/WSL2/Docker (netsh "excluded port
// range"): binding one fails with WinError 10013 even though nothing is
// listening, so freePort() has nothing to kill and the old fixed-port design
// left those users permanently stuck on "initializing". The candidates are
// spread far apart so a single reserved block can't swallow all of them.
const FALLBACK_PORTS = [19876, 29876, 39876, 49876, 55876]

// How long the renderer may wait for the port decision before falling back to
// the preferred port. Picking a port only involves local bind probes, so this
// is a safety net against a hung probe, not a normal code path.
const PORT_READY_TIMEOUT_MS = 15_000

// Liveness supervision, active only AFTER the backend has been ready once.
// Without it a backend that died or wedged hours later went unnoticed: the
// shell kept reporting 'ready', the window looked fine, and every renderer
// request failed with a bare "Failed to fetch".
const HEALTH_PROBE_INTERVAL_MS = 15_000
const HEALTH_PROBE_TIMEOUT_MS = 4_000
// A miss must persist this long before we call the backend dead. Waking from
// sleep loses the first probe (and stretches the interval), which must not be
// mistaken for a crash.
const HEALTH_GRACE_MS = 45_000
// Restarts are bounded so a backend that dies immediately after every launch
// becomes a reported error with a retry button, not an endless respawn loop.
const MAX_RECOVERIES = 3
const RECOVERY_WINDOW_MS = 10 * 60_000

export class PythonBackend extends EventEmitter {
  private process: ChildProcess | null = null
  private backendPath: string
  private port: number = DESKTOP_BACKEND_PORT
  private status: 'stopped' | 'starting' | 'ready' | 'error' = 'stopped'
  // Resolves once start() has settled on a port. The renderer awaits this
  // instead of assuming DESKTOP_BACKEND_PORT, so a fallback port is never a
  // guess it has to make.
  private portReady: Promise<number>
  private markPortReady!: (port: number) => void
  // Rolling tail of backend output. A startup that never reaches "ready" is
  // otherwise reported as a bare timeout, and the actual cause (a bind error, a
  // config exception) is only visible in run.log — which the user can't open
  // from the UI, because the UI is exactly what failed to come up.
  private recentLogs: string[] = []
  // Post-ready liveness supervision. See startHealthMonitor().
  private healthTimer: ReturnType<typeof setInterval> | null = null
  private consecutiveHealthMisses = 0
  private lastHealthyAt = 0
  // True while we are deliberately tearing the process down (quit or restart),
  // so neither the exit handler nor an in-flight probe treats it as a crash.
  private shuttingDown = false
  // True while a recovery restart is in progress, to keep it single-flight.
  private recovering = false
  private recoveryAttempts = 0
  private recoveryWindowStart = 0
  // Append stream to run.log so the backend's OWN stdout/stderr is persisted by
  // the shell too. The backend writes run.log itself once its Python logging is
  // up — but a bootstrap crash (missing DLL, broken onedir after an update,
  // antivirus block) dies BEFORE that, spilling the real cause only to stderr.
  // We captured that stderr already, but never wrote it anywhere durable, so the
  // "open log folder" button showed a stale run.log with no trace of the crash.
  // Mirroring here closes that gap without touching the Python side.
  private logStream: fs.WriteStream | null = null

  constructor(backendPath: string) {
    super()
    this.backendPath = backendPath
    this.portReady = new Promise<number>((resolve) => {
      this.markPortReady = resolve
    })
  }

  getPort(): number {
    return this.port
  }

  /**
   * The port the backend will actually use, once known. Times out to the
   * current best guess so a stalled startup can never leave the renderer
   * waiting forever on a promise that never settles.
   */
  whenPortReady(): Promise<number> {
    return Promise.race([
      this.portReady,
      new Promise<number>((resolve) => setTimeout(() => resolve(this.port), PORT_READY_TIMEOUT_MS)),
    ])
  }

  /** Writable data dir the backend runs against (holds config.json + run.log). */
  getDataDir(): string {
    return this.findBundledBackend() ? COW_DATA_DIR : this.backendPath
  }

  getStatus(): string {
    return this.status
  }

  private recordLog(line: string) {
    this.recentLogs.push(line)
    if (this.recentLogs.length > 80) {
      this.recentLogs.shift()
    }
  }

  /**
   * Open an append stream to <dataDir>/run.log so we can persist the backend's
   * stdout/stderr from the shell side. This is the same file the backend writes
   * once its Python logging initializes, and the same file the "open log folder"
   * button reveals — so a bootstrap crash's stderr lands exactly where the user
   * (and we) already look. Best-effort: any failure just disables mirroring.
   */
  private openLogStream(dataDir: string): void {
    this.closeLogStream()
    try {
      fs.mkdirSync(dataDir, { recursive: true })
      const logPath = path.join(dataDir, 'run.log')
      // Append (not truncate): the backend appends to this same file, so we must
      // not clobber its history, and interleaving is fine — both are line-based.
      this.logStream = fs.createWriteStream(logPath, { flags: 'a' })
      // A logging error must never crash the app; drop the stream instead.
      this.logStream.on('error', () => {
        this.logStream = null
      })
      const stamp = new Date().toISOString()
      this.logStream.write(`\n[SHELL][${stamp}] --- launching backend (stdout/stderr mirrored below) ---\n`)
    } catch {
      this.logStream = null
    }
  }

  private closeLogStream(): void {
    if (this.logStream) {
      try {
        this.logStream.end()
      } catch {
        // ignore
      }
      this.logStream = null
    }
  }

  /**
   * Append the most recent backend error line to a message, so the UI can show
   * what actually went wrong instead of just "startup timed out".
   */
  private withLastError(message: string): string {
    for (let i = this.recentLogs.length - 1; i >= 0; i--) {
      const line = this.recentLogs[i]
      if (/\[ERROR\]|Error:|OSError|Traceback/.test(line)) {
        return `${message}: ${line.trim().slice(0, 300)}`
      }
    }
    return message
  }

  // Cache the resolved PATH so we only spawn a login shell once per process.
  private resolvedPath: string | null = null

  /**
   * Build the PATH the backend should run with.
   *
   * When launched from Finder/Dock, a GUI app inherits launchd's minimal PATH
   * (/usr/bin:/bin:...) and never loads ~/.zshrc, so user-installed CLIs like
   * `linkai`, `node`, or Homebrew tools are invisible to the agent's bash tool.
   * We recover the real login-shell PATH (macOS/Linux) and merge in common bin
   * dirs, so the agent can find these commands regardless of how the app started.
   */
  private resolveEnvPath(): string {
    if (this.resolvedPath !== null) {
      return this.resolvedPath
    }

    const sep = path.delimiter
    const existing = process.env.PATH || ''
    const parts: string[] = existing ? existing.split(sep) : []

    // Prepend the bundled ripgrep dir (if shipped) so the search_files tool's
    // shutil.which("rg") finds our copy and uses the fast rg backend instead of
    // the slow PowerShell fallback. Only Windows ships rg today (macOS relies on
    // its system grep); the existsSync guard keeps this a no-op everywhere else.
    // backendPath is <resources>/backend, so rg lives one level up at
    // <resources>/bin. First entry wins after de-dup below.
    const rgDir = path.join(path.dirname(this.backendPath), 'bin')
    const rgExe = process.platform === 'win32' ? 'rg.exe' : 'rg'
    if (fs.existsSync(path.join(rgDir, rgExe))) {
      parts.unshift(rgDir)
    }

    // Windows GUI apps already inherit the full system PATH; nothing to fix.
    if (process.platform !== 'win32') {
      // Ask the user's login shell for its PATH. `-ilc` runs an interactive
      // login shell so it sources ~/.zshrc / ~/.zprofile etc.
      try {
        const shell = process.env.SHELL || '/bin/zsh'
        const out = execFileSync(shell, ['-ilc', 'echo -n "__PATH__$PATH"'], {
          encoding: 'utf8',
          timeout: 5000,
          stdio: ['ignore', 'pipe', 'ignore'],
        })
        const marker = out.lastIndexOf('__PATH__')
        if (marker !== -1) {
          const shellPath = out.slice(marker + '__PATH__'.length).trim()
          if (shellPath) {
            parts.push(...shellPath.split(sep))
          }
        }
      } catch {
        // Shell probe failed (unusual shell, timeout). Fall back to the
        // common dirs below so at least the typical install paths work.
      }

      const home = os.homedir()
      parts.push(
        path.join(home, '.local/bin'),
        '/usr/local/bin',
        '/opt/homebrew/bin',
        '/usr/bin',
        '/bin',
        '/usr/sbin',
        '/sbin',
      )
    }

    // De-duplicate while preserving order (first occurrence wins).
    const seen = new Set<string>()
    const merged: string[] = []
    for (const p of parts) {
      const dir = p.trim()
      if (dir && !seen.has(dir)) {
        seen.add(dir)
        merged.push(dir)
      }
    }

    this.resolvedPath = merged.join(sep)
    return this.resolvedPath
  }

  /**
   * Locate the packaged onedir backend executable shipped with the app.
   * Returns null when not present (e.g. during local development), so we can
   * fall back to running app.py with a system/venv Python.
   */
  private findBundledBackend(): string | null {
    const exeName = process.platform === 'win32' ? 'cowagent-backend.exe' : 'cowagent-backend'
    const candidates = [
      path.join(this.backendPath, 'cowagent-backend', exeName),
      path.join(this.backendPath, exeName),
    ]
    for (const p of candidates) {
      if (fs.existsSync(p)) {
        return p
      }
    }
    return null
  }

  private findPython(): string {
    const venvPaths = [
      path.join(this.backendPath, '.venv', 'bin', 'python'),
      path.join(this.backendPath, '.venv', 'Scripts', 'python.exe'),
      path.join(this.backendPath, 'venv', 'bin', 'python'),
      path.join(this.backendPath, 'venv', 'Scripts', 'python.exe'),
    ]

    for (const p of venvPaths) {
      if (fs.existsSync(p)) {
        return p
      }
    }

    return process.platform === 'win32' ? 'python' : 'python3'
  }

  /**
   * Read an explicit `web_port` from config.json, if the user pinned one. The
   * packaged build keeps config in COW_DATA_DIR (~/.cow); dev reads it from the
   * repo path. Returns null when unset, so the caller can auto-pick a free port
   * instead of fighting over a fixed one.
   */
  private readConfiguredPort(dataDir: string): number | null {
    try {
      const configPath = path.join(dataDir, 'config.json')
      if (fs.existsSync(configPath)) {
        const config = JSON.parse(fs.readFileSync(configPath, 'utf-8'))
        const p = Number(config.web_port)
        if (Number.isInteger(p) && p > 0 && p < 65536) {
          return p
        }
      }
    } catch {
      // ignore — fall through to auto-selection
    }
    return null
  }

  /**
   * Pick a port the backend can actually bind, preferring the pinned/default
   * one. Each candidate is probed for real (bind + close); a busy one gets a
   * freePort() pass first, since the usual cause is a stale backend from a
   * previous run. Anything still unusable is skipped rather than fought over:
   * on Windows a port can be permanently unbindable (reserved by Hyper-V/WSL2)
   * with no process to kill, which used to strand the app on "initializing".
   *
   * The result is the single source of truth handed to both the backend
   * (COW_WEB_PORT) and the renderer (whenPortReady / the 'port' event).
   */
  private async pickPort(dataDir: string): Promise<number> {
    const pinned = this.readConfiguredPort(dataDir)
    const preferred = pinned !== null ? pinned : DESKTOP_BACKEND_PORT
    const candidates = [preferred, ...FALLBACK_PORTS.filter((p) => p !== preferred)]

    for (const port of candidates) {
      if (await this.isPortFree(port)) {
        return port
      }
      await this.freePort(port)
      if (await this.isPortFree(port)) {
        return port
      }
      this.emit('log', `Port ${port} is unusable — trying the next candidate`)
    }

    // Every candidate refused. Let the OS name a free port: it's less stable
    // across restarts, but the renderer is told which one, so it still works.
    const ephemeral = await this.findEphemeralPort()
    if (ephemeral) {
      this.emit('log', `All candidate ports refused — using OS-assigned port ${ephemeral}`)
      return ephemeral
    }
    // Nothing bindable at all. Return the preferred port anyway so the backend
    // runs and logs a real bind error instead of us failing silently here.
    return preferred
  }

  /** Ask the OS for any free loopback port. Null if even that fails. */
  private findEphemeralPort(): Promise<number | null> {
    return new Promise((resolve) => {
      const tester = net
        .createServer()
        .once('error', () => resolve(null))
        .once('listening', () => {
          const addr = tester.address()
          const port = addr && typeof addr === 'object' ? addr.port : null
          tester.close(() => resolve(port))
        })
        .listen(0, '127.0.0.1')
    })
  }

  /** True if we can bind 127.0.0.1:port right now (i.e. it's free). */
  private isPortFree(port: number): Promise<boolean> {
    return new Promise((resolve) => {
      const tester = net
        .createServer()
        .once('error', () => resolve(false))
        .once('listening', () => {
          tester.close(() => resolve(true))
        })
        .listen(port, '127.0.0.1')
    })
  }

  /**
   * Make sure our fixed port is usable before launch by killing whatever is
   * holding it (almost always a stale backend from a previous run that didn't
   * shut down cleanly). We only ever target a process actually listening on
   * 127.0.0.1:<port>, so we won't touch unrelated apps. Best-effort: if we
   * can't free it we still try to bind and let the backend surface EADDRINUSE.
   */
  private async freePort(port: number): Promise<void> {
    if (await this.isPortFree(port)) {
      return
    }
    this.emit('log', `Port ${port} is busy — clearing stale process before launch`)
    const pids = await this.findListenerPids(port)
    for (const pid of pids) {
      // Never signal ourselves (Electron could, in theory, be the listener).
      if (pid === process.pid) continue
      try {
        process.kill(pid, 'SIGTERM')
      } catch {
        // already gone / no permission — ignore
      }
    }
    // Give the OS a beat to release the socket, then force-kill leftovers.
    await new Promise((r) => setTimeout(r, 600))
    if (!(await this.isPortFree(port))) {
      for (const pid of await this.findListenerPids(port)) {
        if (pid === process.pid) continue
        try {
          process.kill(pid, 'SIGKILL')
        } catch {
          // ignore
        }
      }
      await new Promise((r) => setTimeout(r, 400))
    }
  }

  /** PIDs listening on 127.0.0.1:<port>, via lsof (POSIX) / netstat (Windows). */
  private findListenerPids(port: number): Promise<number[]> {
    return new Promise((resolve) => {
      const isWin = process.platform === 'win32'
      const cmd = isWin ? 'netstat' : 'lsof'
      const args = isWin
        ? ['-ano', '-p', 'tcp']
        : ['-nP', `-iTCP:${port}`, '-sTCP:LISTEN', '-t']
      let out = ''
      try {
        const child = spawn(cmd, args)
        child.stdout?.on('data', (d: Buffer) => (out += d.toString()))
        child.on('error', () => resolve([]))
        child.on('close', () => {
          const pids = new Set<number>()
          if (isWin) {
            // Match lines like: TCP 127.0.0.1:9876 ... LISTENING  12345
            for (const line of out.split('\n')) {
              if (!/LISTENING/i.test(line)) continue
              if (!new RegExp(`[:.]${port}\\b`).test(line)) continue
              const pid = Number(line.trim().split(/\s+/).pop())
              if (Number.isInteger(pid) && pid > 0) pids.add(pid)
            }
          } else {
            for (const tok of out.split(/\s+/)) {
              const pid = Number(tok)
              if (Number.isInteger(pid) && pid > 0) pids.add(pid)
            }
          }
          resolve([...pids])
        })
      } catch {
        resolve([])
      }
    })
  }

  /** One-shot /api/health probe. Never throws; false means "unreachable". */
  private probeHealth(): Promise<boolean> {
    return new Promise((resolve) => {
      let settled = false
      const done = (ok: boolean) => {
        if (settled) return
        settled = true
        resolve(ok)
      }
      const req = http.get(`http://127.0.0.1:${this.port}/api/health`, (res) => {
        // Drain the body: an unread response keeps its socket checked out of
        // the keep-alive pool, so repeated probes would leak sockets.
        res.resume()
        done(res.statusCode === 200)
      })
      req.on('error', () => done(false))
      req.setTimeout(HEALTH_PROBE_TIMEOUT_MS, () => {
        req.destroy()
        done(false)
      })
    })
  }

  /**
   * Start watching a backend that has reached 'ready'. The renderer trusts
   * 'ready' for the rest of the session, so this is the only thing that can
   * notice a backend which dies or stops answering later on.
   */
  private startHealthMonitor(): void {
    this.stopHealthMonitor()
    this.lastHealthyAt = Date.now()
    this.consecutiveHealthMisses = 0
    this.healthTimer = setInterval(() => {
      void this.checkHealth()
    }, HEALTH_PROBE_INTERVAL_MS)
  }

  private stopHealthMonitor(): void {
    if (this.healthTimer) {
      clearInterval(this.healthTimer)
      this.healthTimer = null
    }
  }

  private async checkHealth(): Promise<void> {
    if (this.shuttingDown || this.recovering) {
      return
    }
    if (await this.probeHealth()) {
      this.consecutiveHealthMisses = 0
      this.lastHealthyAt = Date.now()
      return
    }
    this.consecutiveHealthMisses++
    // Require both repeated misses and real elapsed time: sleep/wake throttles
    // the interval, so a single lost probe says nothing about the backend.
    if (this.consecutiveHealthMisses < 2 || Date.now() - this.lastHealthyAt < HEALTH_GRACE_MS) {
      return
    }
    await this.recover()
  }

  /**
   * Rebuild a backend that stopped answering. Announces 'lost' first so the
   * renderer drops its cached "ready" and shows the reconnect screen instead of
   * failing every request behind an intact-looking UI.
   */
  private async recover(): Promise<void> {
    if (this.recovering) {
      return
    }
    this.recovering = true
    this.stopHealthMonitor()
    try {
      // Announced before the budget check: the backend is gone either way, and
      // the renderer must leave 'ready' even on the attempt where we give up —
      // otherwise it would ignore the error we're about to report.
      this.emit('lost')
      const now = Date.now()
      if (now - this.recoveryWindowStart > RECOVERY_WINDOW_MS) {
        this.recoveryWindowStart = now
        this.recoveryAttempts = 0
      }
      this.recoveryAttempts++
      if (this.recoveryAttempts > MAX_RECOVERIES) {
        this.status = 'error'
        this.emit(
          'error',
          this.withLastError('The app stopped responding and could not be restarted'),
        )
        return
      }
      this.emit(
        'log',
        `Backend stopped responding — restarting (attempt ${this.recoveryAttempts}/${MAX_RECOVERIES})`,
      )
      await this.restart()
    } finally {
      this.recovering = false
    }
  }

  async start(): Promise<void> {
    if (this.status === 'ready' || this.status === 'starting') {
      return
    }

    this.shuttingDown = false
    this.status = 'starting'
    // Drop the previous run's output so a retry can't report a stale error.
    this.recentLogs = []

    // Prefer the packaged self-contained backend (production); fall back to
    // running app.py with a Python interpreter (local development).
    const bundled = this.findBundledBackend()
    // Packaged app stores writable data in ~/.cow; dev keeps it in the repo.
    const dataDir = bundled ? COW_DATA_DIR : this.backendPath

    // Start mirroring backend output to run.log before we spawn, so even an
    // instant bootstrap crash (before Python logging is up) leaves its stderr
    // in the file the user can open from the failure screen.
    this.openLogStream(dataDir)

    // Always launch our OWN backend (re-entrancy is guarded above by the status
    // check, so we never double-spawn for this instance). We don't reuse
    // whatever happens to be on the port: that's how the app previously attached
    // to a source-run web console and read the wrong config. pickPort() frees
    // stale listeners and skips ports the OS refuses, then publishes the result
    // so the renderer never has to guess which port we settled on.
    this.port = await this.pickPort(dataDir)
    this.markPortReady(this.port)
    this.emit('port', this.port)

    let command: string
    let args: string[]
    let cwd: string

    if (bundled) {
      command = bundled
      args = []
      // Run from the writable data dir (~/.cow), NOT the install dir. When the
      // app is installed under Program Files, a non-admin user has no write
      // permission to the executable's folder, so any relative-path write
      // during startup would crash the backend (works only as admin). The
      // bundle reads its read-only resources via sys._MEIPASS, so cwd is free
      // to point elsewhere.
      try {
        fs.mkdirSync(COW_DATA_DIR, { recursive: true })
      } catch {
        // ignore — get_data_root() also ensures the dir on the Python side
      }
      cwd = COW_DATA_DIR
      this.emit('log', `Starting bundled backend: ${bundled} (cwd=${cwd})`)
    } else {
      const pythonPath = this.findPython()
      const appPath = path.join(this.backendPath, 'app.py')
      if (!fs.existsSync(appPath)) {
        this.status = 'error'
        this.emit('error', `app.py not found at ${appPath}`)
        return
      }
      command = pythonPath
      args = [appPath]
      cwd = this.backendPath
      this.emit('log', `Starting Python backend: ${pythonPath} ${appPath}`)
    }

    this.process = spawn(command, args, {
      cwd,
      // COW_DESKTOP enables the lighter desktop runtime (no plugins, no MCP).
      // COW_DATA_DIR (packaged only) redirects writable data to ~/.cow so the
      // app bundle stays read-only; dev runs omit it and keep using the repo.
      env: {
        ...process.env,
        // Recover the user's real PATH (login shell + common bin dirs) so the
        // agent's bash tool can find CLIs like `linkai`/`node` even when the
        // app is launched from Finder/Dock with launchd's minimal PATH.
        PATH: this.resolveEnvPath(),
        PYTHONUNBUFFERED: '1',
        COW_DESKTOP: '1',
        // The shell owns the port: tell the backend to bind exactly here so the
        // two sides can never disagree (and we avoid the 9899 web-console clash).
        COW_WEB_PORT: String(this.port),
        ...(bundled ? { COW_DATA_DIR } : {}),
      },
      stdio: ['pipe', 'pipe', 'pipe'],
    })

    const onOutput = (data: Buffer) => {
      const text = data.toString()
      // Persist raw output to run.log first, so nothing is lost even if the
      // per-line handling below throws. The backend already writes its own
      // structured lines here once up; this captures the pre-logging bootstrap
      // output (and anything it prints straight to stdout/stderr) as well.
      if (this.logStream) {
        try {
          this.logStream.write(text)
        } catch {
          // ignore — logging must never break startup
        }
      }
      const lines = text.split('\n').filter(Boolean)
      for (const line of lines) {
        this.recordLog(line)
        this.emit('log', line)
      }
    }
    this.process.stdout?.on('data', onOutput)
    this.process.stderr?.on('data', onOutput)

    this.process.on('exit', (code) => {
      // If the backend dies before it ever became ready, surface an error now
      // instead of letting waitForReady spin for the full timeout. A clean exit
      // (code 0/null, e.g. our own stop()) just marks stopped.
      const wasReady = this.status === 'ready'
      this.status = 'stopped'
      if (this.logStream) {
        try {
          this.logStream.write(`[SHELL][${new Date().toISOString()}] backend process exited with code ${code}\n`)
        } catch {
          // ignore
        }
      }
      this.emit('log', `Python process exited with code ${code}`)
      if (!wasReady && code !== 0 && code !== null) {
        this.status = 'error'
        this.emit('error', this.withLastError(`The app exited during startup (code ${code})`))
        return
      }
      // Died after serving requests (a late crash, or app.py's own os._exit).
      // Nothing else would notice, so recover here rather than waiting out the
      // next health probe.
      if (wasReady && !this.shuttingDown) {
        this.stopHealthMonitor()
        void this.recover()
      }
    })

    this.process.on('error', (err) => {
      this.status = 'error'
      this.emit('error', `Failed to start Python: ${err.message}`)
    })

    await this.waitForReady()
  }

  private waitForReady(): Promise<void> {
    return new Promise((resolve) => {
      // Wall-clock deadline rather than an attempt counter: if the machine
      // sleeps/suspends, the 1s timers stretch out and a counter would give up
      // far too early. Time-based bounding tracks real elapsed time instead.
      // Only reachable when the process is alive yet never answers /api/health:
      // a crash exits immediately and a wedged startup is killed by the
      // backend's own watchdog, and both paths report a real cause. So this is
      // a backstop, kept just above that watchdog so its message wins the race.
      const timeoutMs = 30_000
      const startedAt = Date.now()

      const check = () => {
        // Probe the unauthenticated health endpoint, NOT /config: /config
        // requires auth once a web_password is set, which would make this poll
        // 401 forever and hang startup.
        const req = http.get(`http://127.0.0.1:${this.port}/api/health`, (res) => {
          // Drain the body so the socket isn't held out of the keep-alive pool.
          res.resume()
          if (res.statusCode === 200) {
            this.status = 'ready'
            this.emit('log', `Backend ready on port ${this.port}`)
            this.emit('ready', this.port)
            // From here on the renderer trusts 'ready', so this monitor is the
            // only thing that can notice the backend going away later.
            this.startHealthMonitor()
            resolve()
          } else {
            retry()
          }
        })

        req.on('error', () => retry())
        req.setTimeout(2000, () => {
          req.destroy()
          retry()
        })
      }

      const retry = () => {
        // Backend already settled: ready (done), or stopped/errored by the exit
        // handler (don't keep polling a dead process — the error was emitted).
        if (this.status === 'ready' || this.status === 'stopped' || this.status === 'error') {
          resolve()
          return
        }
        if (Date.now() - startedAt >= timeoutMs) {
          this.status = 'error'
          this.emit(
            'error',
            this.withLastError(`The app failed to start within ${Math.round(timeoutMs / 1000)} seconds`),
          )
          resolve()
          return
        }
        setTimeout(check, 1000)
      }

      setTimeout(check, 2000)
    })
  }

  stop(): void {
    // Set before the kill so the exit handler reads this as a deliberate
    // teardown and doesn't try to "recover" a process we just asked to die.
    this.shuttingDown = true
    this.stopHealthMonitor()
    this.closeLogStream()
    const proc = this.process
    if (proc) {
      proc.kill('SIGTERM')
      // Keep a local ref so the SIGKILL fallback can still reach the process
      // even after we clear `this.process`; otherwise a stuck backend would
      // never be force-killed and leak as a zombie.
      setTimeout(() => {
        if (!proc.killed) {
          proc.kill('SIGKILL')
        }
      }, 5000)
      this.process = null
    }
    this.status = 'stopped'
  }

  async restart(): Promise<void> {
    // A manual retry from the UI earns a fresh recovery budget; a restart that
    // the recovery path itself triggered must keep counting toward the limit.
    if (!this.recovering) {
      this.recoveryAttempts = 0
      this.recoveryWindowStart = Date.now()
    }
    this.stop()
    await new Promise((resolve) => setTimeout(resolve, 2000))
    await this.start()
  }
}
