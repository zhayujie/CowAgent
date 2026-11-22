import {AppState, type AppStateStatus, type NativeEventSubscription} from 'react-native';
import {isLocalAddress, normalizeBaseUrl} from './http';
import {discover, sameDevice} from './pairing';

/**
 * One server usually answers at several addresses: a local one at home and a
 * relayed one out on the internet. The router keeps the fastest that works in
 * use, switches away as soon as it stops answering, and goes back to the local
 * one whenever it returns.
 */
export type EndpointKind = 'lan' | 'wan';

export interface RouterEndpoint {
  url: string;
  kind: EndpointKind;
}

export function endpointKind(url: string): EndpointKind {
  return isLocalAddress(url) ? 'lan' : 'wan';
}

/** Local addresses answer in milliseconds when they answer at all. */
const LAN_TIMEOUT_MS = 2_000;
const WAN_TIMEOUT_MS = 4_000;
/** Let the near address leave first, so a tie goes to the local network. */
const WAN_HEAD_START_MS = 120;

const HEARTBEAT_MS = 6_000;
/** When nothing answers, try again soon rather than at the heartbeat. */
const RETRY_UNREACHABLE_MS = 2_500;
const LAN_RECHECK_MS = 20_000;
/** After the local network keeps missing, stop asking so often. */
const LAN_RECHECK_IDLE_MS = 60_000;
const LAN_MISSES_BEFORE_SLOWING = 5;
/** A burst of failures from one action moves the endpoint once, not per request. */
const FAILOVER_COOLDOWN_MS = 3_000;

export interface RouterConfig {
  endpoints: RouterEndpoint[];
  /** The server must answer as this instance; pairings from before ids trust any. */
  instanceId?: string;
  /** Point the HTTP client at a new address; called before listeners hear about it. */
  apply: (endpoint: RouterEndpoint) => void;
}

/** Local addresses first, then the rest, without duplicates. */
export function sortEndpoints(list: RouterEndpoint[]): RouterEndpoint[] {
  const seen = new Set<string>();
  const out: RouterEndpoint[] = [];
  for (const ep of list) {
    const url = normalizeBaseUrl(ep.url);
    if (!url || seen.has(url)) {
      continue;
    }
    seen.add(url);
    out.push({url, kind: ep.kind});
  }
  return [...out.filter(e => e.kind === 'lan'), ...out.filter(e => e.kind !== 'lan')];
}

async function reachable(ep: RouterEndpoint, instanceId: string | undefined): Promise<boolean> {
  try {
    const info = await discover(ep.url, ep.kind === 'lan' ? LAN_TIMEOUT_MS : WAN_TIMEOUT_MS);
    return sameDevice(instanceId, info);
  } catch {
    return false;
  }
}

/** The first endpoint to answer, or null when none does. Local probes leave first. */
function firstReachable(
  endpoints: RouterEndpoint[],
  instanceId: string | undefined,
): Promise<RouterEndpoint | null> {
  if (endpoints.length === 0) {
    return Promise.resolve(null);
  }
  return new Promise(resolve => {
    let remaining = endpoints.length;
    let settled = false;
    const settle = (endpoint: RouterEndpoint | null) => {
      if (!settled) {
        settled = true;
        resolve(endpoint);
      }
    };
    for (const ep of endpoints) {
      const probe = () => {
        reachable(ep, instanceId)
          .then(ok => {
            if (ok) {
              settle(ep);
            }
          })
          .finally(() => {
            remaining -= 1;
            if (remaining === 0) {
              settle(null);
            }
          });
      };
      if (ep.kind === 'wan') {
        setTimeout(probe, WAN_HEAD_START_MS);
      } else {
        probe();
      }
    }
  });
}

class EndpointRouter {
  private config: RouterConfig | null = null;
  private active: RouterEndpoint | null = null;
  private running = false;
  private timer: ReturnType<typeof setTimeout> | null = null;
  private working = false;
  private lastFailoverAt = 0;
  private lastLanCheckAt = 0;
  private lanMisses = 0;
  /** Bumped whenever a pending selection would no longer be wanted. */
  private generation = 0;
  private appStateSub: NativeEventSubscription | null = null;
  private listeners = new Set<(endpoint: RouterEndpoint) => void>();

  /** The address in use now; null before the first choice. */
  current(): RouterEndpoint | null {
    return this.active;
  }

  /** Called after `apply`, so listeners can rebuild whatever was tied to the old address. */
  subscribe(listener: (endpoint: RouterEndpoint) => void): () => void {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  }

  /** Replace the addresses; the one in use is kept if it is still among them. */
  configure(config: RouterConfig) {
    const endpoints = sortEndpoints(config.endpoints);
    const previous = this.config?.endpoints ?? [];
    this.config = {...config, endpoints};
    if (!this.active) {
      if (this.running) {
        this.reselect().catch(() => undefined);
      }
      return;
    }
    const kept = endpoints.find(e => e.url === this.active!.url);
    if (kept) {
      this.active = kept;
      // A local address just showed up: look at it on the next heartbeat.
      if (kept.kind === 'wan' && endpoints.some(e => e.kind === 'lan' && !previous.some(p => p.url === e.url))) {
        this.lastLanCheckAt = 0;
      }
      return;
    }
    if (this.running) {
      this.reselect().catch(() => undefined);
    }
  }

  start() {
    if (this.running) {
      return;
    }
    this.running = true;
    this.appStateSub = AppState.addEventListener('change', this.onAppState);
    this.reselect().catch(() => undefined);
  }

  stop() {
    this.running = false;
    this.generation += 1;
    this.active = null;
    this.config = null;
    this.lanMisses = 0;
    this.clearTimer();
    this.appStateSub?.remove();
    this.appStateSub = null;
  }

  /**
   * The address in use failed before answering: move to another one right away
   * and report whether that happened, so a GET can be repeated.
   */
  reportFailure(kind: 'network' | 'timeout', url: string): Promise<boolean> {
    const cfg = this.config;
    if (!this.running || !cfg || !this.active || this.working) {
      return Promise.resolve(false);
    }
    if (!url.startsWith(this.active.url)) {
      return Promise.resolve(false);
    }
    if (Date.now() - this.lastFailoverAt < FAILOVER_COOLDOWN_MS) {
      return Promise.resolve(false);
    }
    const before = this.active.url;
    return this.failover(this.generation).then(
      () => !!this.active && this.active.url !== before,
      () => false,
    );
  }

  private onAppState = (state: AppStateStatus) => {
    if (!this.running) {
      return;
    }
    if (state === 'active') {
      // Back from the background, the addresses may be different: check now.
      this.schedule(0);
    } else if (state === 'background') {
      this.clearTimer();
    }
  };

  private clearTimer() {
    if (this.timer) {
      clearTimeout(this.timer);
      this.timer = null;
    }
  }

  private schedule(delay: number) {
    this.clearTimer();
    if (!this.running) {
      return;
    }
    this.timer = setTimeout(() => {
      this.tick().catch(() => undefined);
    }, delay);
  }

  private async reselect() {
    const cfg = this.config;
    if (!cfg) {
      return;
    }
    const generation = ++this.generation;
    const winner = await firstReachable(cfg.endpoints, cfg.instanceId);
    if (!this.running || generation !== this.generation) {
      return;
    }
    if (winner) {
      this.activate(winner);
    }
    this.schedule(winner ? HEARTBEAT_MS : RETRY_UNREACHABLE_MS);
  }

  private async tick() {
    const cfg = this.config;
    if (!this.running || !cfg) {
      return;
    }
    const active = this.active;
    if (!active) {
      await this.reselect();
      return;
    }
    const generation = this.generation;
    const ok = await reachable(active, cfg.instanceId);
    if (!this.running || generation !== this.generation) {
      return;
    }
    if (!ok) {
      const moved = await this.failover(generation);
      this.schedule(moved ? HEARTBEAT_MS : RETRY_UNREACHABLE_MS);
      return;
    }
    if (active.kind === 'wan') {
      // The local network may have come back since; it is always preferable.
      const locals = cfg.endpoints.filter(e => e.kind === 'lan' && e.url !== active.url);
      const idle = this.lanMisses >= LAN_MISSES_BEFORE_SLOWING ? LAN_RECHECK_IDLE_MS : LAN_RECHECK_MS;
      if (locals.length && Date.now() - this.lastLanCheckAt >= idle) {
        this.lastLanCheckAt = Date.now();
        const winner = await firstReachable(locals, cfg.instanceId);
        if (!this.running || generation !== this.generation) {
          return;
        }
        if (winner) {
          this.lanMisses = 0;
          this.activate(winner);
        } else {
          this.lanMisses += 1;
        }
      }
    } else {
      this.lanMisses = 0;
    }
    this.schedule(HEARTBEAT_MS);
  }

  private async failover(generation: number): Promise<boolean> {
    const cfg = this.config;
    if (!cfg || this.working) {
      return false;
    }
    this.working = true;
    this.lastFailoverAt = Date.now();
    try {
      const others = cfg.endpoints.filter(e => e.url !== this.active?.url);
      const winner = await firstReachable(others, cfg.instanceId);
      if (!this.running || generation !== this.generation || !winner) {
        return false;
      }
      this.activate(winner);
      return true;
    } finally {
      this.working = false;
    }
  }

  private activate(endpoint: RouterEndpoint) {
    const changed = this.active?.url !== endpoint.url;
    this.active = endpoint;
    this.lastLanCheckAt = Date.now();
    if (!changed) {
      return;
    }
    try {
      this.config?.apply(endpoint);
    } catch {
      // A listener failing must not stop the router.
    }
    this.listeners.forEach(listener => listener(endpoint));
  }
}

export const endpointRouter = new EndpointRouter();
