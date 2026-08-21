import { useState, useEffect, useCallback, useRef } from 'react'
import type { BackendErrorCode } from '../types'

// Preferred port — MUST match DESKTOP_BACKEND_PORT in main/python-manager.ts.
// It is only the starting guess for probing: the main process may fall back to
// another port when this one can't be bound (Windows reserves port ranges for
// Hyper-V/WSL2), and it publishes the real one via getBackendPort / the
// 'starting' backend-status event. Always prefer that over this constant.
const BACKEND_PORT = 9876

// A healthy backend answers in a few seconds; a crash exits immediately and a
// wedged one is killed by the watchdog in app.py, so both real failure modes
// reach us as an error event well before this. It only bounds the case where
// that event never arrives, and a blank spinner soon reads as a broken app.
// Last in the ladder (backend watchdog < main-process probe < this) so the
// most specific error always gets to the screen first.
const GIVE_UP_AFTER_MS = 40_000
// Long enough to not fire on a normal cold start, short enough that a user who
// is about to force-quit sees the app admit something is off.
const SLOW_START_AFTER_MS = 15_000

// Failures of the installation itself. Nothing about them can improve by
// waiting, so they skip the polling deadline entirely: the executable is not
// going to reappear, and 40 seconds of a spinner before saying so is 40
// seconds the user spends assuming the app is merely slow.
const UNRECOVERABLE_CODES: ReadonlySet<string> = new Set<BackendErrorCode>([
  'backend_removed',
  'backend_missing',
  'backend_blocked',
])

interface BackendState {
  status: 'connecting' | 'ready' | 'error'
  port: number
  error?: string
  code?: BackendErrorCode
  path?: string
  slow?: boolean
  // True while we're recovering a backend that had already been ready, so the
  // status screen can say "reconnecting" rather than "starting up".
  reconnecting?: boolean
}

export function useBackend() {
  const [state, setState] = useState<BackendState>({
    status: 'connecting',
    port: BACKEND_PORT,
  })
  const pollingRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const probeBackend = useCallback(async (port: number): Promise<boolean> => {
    try {
      // Probe the unauthenticated health endpoint, NOT /config: once a
      // web_password is set, /config returns 401 and we'd wrongly treat the
      // (healthy) backend as unreachable, hanging on "connecting".
      const res = await fetch(`http://127.0.0.1:${port}/api/health`, {
        signal: AbortSignal.timeout(3000),
      })
      return res.ok
    } catch {
      return false
    }
  }, [])

  // True once the backend has answered at least once. After this we never flip
  // back to "error" from polling — a hidden/backgrounded window throttles JS
  // timers, so attempt counters are unreliable and would otherwise produce a
  // false "failed to start" even though the backend is alive.
  const readyRef = useRef(false)
  // Holds the latest resolved port so the visibility handler (registered once)
  // always probes the correct port without re-running the effect.
  const portRef = useRef(BACKEND_PORT)

  useEffect(() => {
    let cancelled = false
    let offStatus: (() => void) | undefined
    const api = window.electronAPI

    // Use a wall-clock deadline instead of an attempt counter so timer
    // throttling (when the window is in the background) can't fast-forward us
    // into a false failure. Only give up if we genuinely can't reach the
    // backend for this long.
    // The port we're currently polling, and a generation counter that retires
    // superseded loops. Both the IPC result and the 'starting' event report the
    // port, usually the same one, and the first probe takes seconds — without
    // this, the duplicate call would spawn a second loop against the same port.
    let activePort: number | null = null
    let pollGeneration = 0

    const startPolling = async (port: number) => {
      if (activePort === port) return
      activePort = port
      const generation = ++pollGeneration
      if (pollingRef.current) {
        clearTimeout(pollingRef.current)
        pollingRef.current = null
      }
      portRef.current = port
      setState((prev) => (prev.port === port ? prev : { ...prev, port }))
      const startedAt = Date.now()
      const deadline = startedAt + GIVE_UP_AFTER_MS

      const poll = async () => {
        if (cancelled || generation !== pollGeneration) return

        const ready = await probeBackend(port)
        // The probe is async: a port switch may have landed while it was in
        // flight, in which case this loop is stale and must not report state.
        if (cancelled || generation !== pollGeneration) return

        if (ready) {
          readyRef.current = true
          activePort = null
          setState({ status: 'ready', port })
          return
        }

        // Ask the main process whether it has already given up. This is a pull,
        // so it works no matter when the failure happened relative to our
        // subscription, and it lets a broken installation be reported the
        // moment it's known instead of after the full polling deadline.
        const failure = !readyRef.current ? await api?.getBackendError?.().catch(() => null) : null
        if (cancelled || generation !== pollGeneration) return
        if (failure && UNRECOVERABLE_CODES.has(failure.code)) {
          activePort = null
          setState({ status: 'error', port, error: failure.message, code: failure.code, path: failure.path })
          return
        }

        // Backend already answered before but is briefly unreachable (e.g.
        // window was asleep): keep retrying, never surface an error.
        if (!readyRef.current && Date.now() >= deadline) {
          activePort = null
          // Prefer whatever the main process knows: its diagnosis names the
          // actual cause, while the localized fallback can only say that
          // something went wrong.
          setState((prev) => ({
            ...prev,
            status: 'error',
            port,
            error: failure?.message ?? prev.error,
            code: failure?.code ?? prev.code,
            path: failure?.path ?? prev.path,
          }))
          return
        }

        if (!readyRef.current && Date.now() - startedAt >= SLOW_START_AFTER_MS) {
          setState((prev) => (prev.slow ? prev : { ...prev, slow: true }))
        }

        pollingRef.current = setTimeout(poll, 1000)
      }

      await poll()
    }

    if (api) {
      // Start on the preferred port immediately, without waiting for IPC:
      // probing is the self-sufficient path to "ready" and must never depend on
      // the round trip succeeding (otherwise the app can hang on "connecting").
      // Both the IPC result and the 'starting' event redirect us to the real
      // port if the main process had to fall back to another one.
      startPolling(BACKEND_PORT)

      api
        .getBackendPort()
        .then((port) => {
          if (port) startPolling(port)
        })
        .catch(() => {
          // Preferred-port polling is already running; nothing to recover.
        })

      offStatus = api.onBackendStatus((data) => {
        if (data.status === 'ready' && data.port) {
          readyRef.current = true
          portRef.current = data.port
          setState({ status: 'ready', port: data.port })
          // Retire the poll loop so a later restart can start a fresh one.
          pollGeneration++
          activePort = null
          if (pollingRef.current) {
            clearTimeout(pollingRef.current)
            pollingRef.current = null
          }
        } else if (data.status === 'starting' && data.port) {
          startPolling(data.port)
        } else if (data.status === 'lost') {
          // The main process found a previously-ready backend unreachable and is
          // restarting it. Release the ready latch: holding it would keep the
          // whole UI mounted against a backend that answers nothing, which is
          // how a dead backend used to show up as "Failed to fetch" everywhere.
          readyRef.current = false
          pollGeneration++
          activePort = null
          if (pollingRef.current) {
            clearTimeout(pollingRef.current)
            pollingRef.current = null
          }
          setState((prev) => ({
            ...prev,
            status: 'connecting',
            reconnecting: true,
            error: undefined,
            slow: false,
          }))
        } else if (data.status === 'error' && !readyRef.current) {
          // Ignore late "error" from the main process once we've been ready —
          // it usually means the window was backgrounded, not a real failure.
          // Keep the message and code: together they are the only diagnostic a
          // user has when the UI never came up.
          setState((prev) => ({ ...prev, status: 'error', error: data.error, code: data.code, path: data.path }))
        }
      })
    } else {
      startPolling(BACKEND_PORT)
    }

    // When the window comes back to the foreground, re-probe immediately so a
    // user returning after a while sees the real (ready) state right away
    // instead of waiting for the throttled timer to catch up.
    const onVisible = () => {
      if (cancelled || document.visibilityState !== 'visible') return
      probeBackend(portRef.current).then((ready) => {
        if (cancelled || !ready) return
        readyRef.current = true
        setState((prev) => ({ ...prev, status: 'ready' }))
      })
    }
    document.addEventListener('visibilitychange', onVisible)

    return () => {
      cancelled = true
      if (pollingRef.current) {
        clearTimeout(pollingRef.current)
      }
      offStatus?.()
      document.removeEventListener('visibilitychange', onVisible)
    }
  }, [probeBackend])

  const restart = useCallback(async () => {
    setState((prev) => ({ ...prev, status: 'connecting', error: undefined, code: undefined, path: undefined, slow: false }))
    if (window.electronAPI) {
      await window.electronAPI.restartBackend()
    }
  }, [])

  const baseUrl = `http://127.0.0.1:${state.port}`

  return { ...state, baseUrl, restart }
}
