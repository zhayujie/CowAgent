/**
 * Other CowAgent devices this app can drive besides the one it starts itself,
 * joined with a one-time pairing code made on that device.
 *
 * Plain storage helpers with no app imports, so the API client can read the
 * active instance at startup. Switching reloads the window, which makes every
 * store start over against the new instance.
 */

export interface Instance {
  id: string
  name: string
  /** Origin only, e.g. http://192.168.1.10:9899 */
  url: string
  /** Device token issued by the instance; empty once it stops working. */
  token: string
  /** The id the device answers discovery with; its token goes nowhere else. */
  instance_id?: string
  version: string
  /** Named by whoever runs it, so clients don't offer a rename. */
  managed?: boolean
  added_at: number
}

/** What /.well-known/cowagent says, without credentials. */
export interface Discovery {
  type: 'instance'
  id?: string
  version?: string
  auth?: { required?: boolean; methods?: string[] }
}

interface InstancesDoc {
  active: string
  items: Instance[]
}

const INSTANCES_KEY = 'cow_instances'
const STATE_PREFIX = 'cow_instance_state:'

// Remembered per instance: they point at sessions, Agents and menus that only
// exist on the instance they came from.
const SCOPED_KEYS = [
  'cow_active_agent',
  'cow_memory_agent',
  'cow_knowledge_agent',
  'cow_menu_cache',
  'cow_collapsed_projects',
  'cow_session_owners',
  'cow_artifacts_scope',
]
const SCOPED_PREFIXES = ['cow_session_id']

export class InstanceError extends Error {
  constructor(
    readonly reason: string,
    readonly retryAfter = 0,
    readonly host = '',
    readonly status = 0,
  ) {
    super(reason)
  }
}

function fetchWithin(url: string, init: RequestInit, timeout: number): Promise<Response> {
  const ctrl = new AbortController()
  const timer = setTimeout(() => ctrl.abort(), timeout)
  return fetch(url, { cache: 'no-store', credentials: 'omit', ...init, signal: ctrl.signal }).finally(() =>
    clearTimeout(timer),
  )
}

/**
 * Discovery at `base`, or an InstanceError saying why there is none:
 * unreachable / timeout / blocked (answers, but not to this app) / login (a
 * sign-in gateway) / outdated (CowAgent from before devices) / not_cowagent.
 */
export async function diagnoseInstance(base: string, timeout = 6000): Promise<Discovery> {
  const host = instanceHost(base)
  let res: Response
  try {
    res = await fetchWithin(`${base}/.well-known/cowagent`, {}, timeout)
  } catch (e) {
    if ((e as Error)?.name === 'AbortError') throw new InstanceError('timeout', 0, host)
    // An answer withheld for lack of CORS only shows as an opaque response.
    const answered = await fetchWithin(`${base}/`, { mode: 'no-cors' }, 4000).then(
      () => true,
      () => false,
    )
    throw new InstanceError(answered ? 'blocked' : 'unreachable', 0, host)
  }
  const body = await res.json().catch(() => null)
  if (body && body.type === 'instance') return body as Discovery
  if (res.status === 401 || res.status === 403 || body?.error === 'unauthorized') {
    throw new InstanceError('login', 0, host)
  }
  if (res.status === 404) {
    const old = await fetchWithin(`${base}/auth/check`, {}, 4000)
      .then((r) => r.json())
      .then((b) => !!b && 'auth_required' in b)
      .catch(() => false)
    if (old) throw new InstanceError('outdated', 0, host)
  }
  throw new InstanceError('not_cowagent', 0, host, res.status)
}

/** Whether discovery came from the device that issued `item`'s token.
 *  Pairings from before devices had ids carry none and are taken on trust. */
export function sameDevice(item: Pick<Instance, 'instance_id'>, info: Discovery | null): boolean {
  return !item.instance_id || (!!info && info.id === item.instance_id)
}

/** How this app introduces itself when signing in to an instance. */
export async function deviceInfo(): Promise<{ name: string; platform: string; app_version: string }> {
  const api = window.electronAPI
  const [host, version] = await Promise.all([
    api?.getHostName?.().catch(() => '') ?? '',
    api?.getAppVersion?.().catch(() => '') ?? '',
  ])
  const ua = navigator.userAgent
  const system = /Mac/.test(ua) ? 'macOS' : /Windows/.test(ua) ? 'Windows' : /Linux/.test(ua) ? 'Linux' : ''
  const name = host || (system ? `CowAgent Desktop · ${system}` : 'CowAgent Desktop')
  return { name: name.slice(0, 60), platform: 'desktop', app_version: version || '' }
}

export function readInstances(): InstancesDoc {
  try {
    const doc = JSON.parse(localStorage.getItem(INSTANCES_KEY) || 'null')
    if (doc && Array.isArray(doc.items)) {
      const items = (doc.items as Instance[]).filter((i) => i && i.id && i.url)
      return { active: items.some((i) => i.id === doc.active) ? doc.active : '', items }
    }
  } catch {
    // unreadable: start over
  }
  return { active: '', items: [] }
}

export function writeInstances(doc: InstancesDoc) {
  try {
    localStorage.setItem(INSTANCES_KEY, JSON.stringify(doc))
  } catch {
    // storage full or unavailable
  }
}

export function activeInstance(): Instance | null {
  if (typeof localStorage === 'undefined') return null
  const doc = readInstances()
  return doc.items.find((i) => i.id === doc.active) || null
}

export function updateInstance(id: string, patch: Partial<Instance>) {
  const doc = readInstances()
  const item = doc.items.find((i) => i.id === id)
  if (!item) return
  Object.assign(item, patch)
  writeInstances(doc)
}

export function newInstanceId(): string {
  const bytes = new Uint8Array(6)
  crypto.getRandomValues(bytes)
  return 'i_' + Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('')
}

export function normalizeInstanceUrl(value: string, scheme = 'http'): string {
  let text = (value || '').trim()
  if (!text) return ''
  if (!/^https?:\/\//i.test(text)) text = `${scheme}://${text}`
  try {
    const url = new URL(text)
    return `${url.protocol}//${url.host}`
  } catch {
    return ''
  }
}

/** Addresses to try for what was typed: as given, or http then https without a scheme. */
export function addressCandidates(typed: string): string[] {
  const text = (typed || '').trim()
  if (/^https?:\/\//i.test(text)) return [normalizeInstanceUrl(text)].filter(Boolean)
  return [normalizeInstanceUrl(text, 'http'), normalizeInstanceUrl(text, 'https')].filter(Boolean)
}

export function instanceHost(url: string): string {
  try {
    return new URL(url).host
  } catch {
    return url
  }
}

/** A `cowagent://pair?c=CODE&u=URL...` link copied from the other side. */
export function parsePairLink(text: string): { code: string; urls: string[] } | null {
  const value = (text || '').trim()
  if (!/^cowagent:\/\/pair\?/i.test(value)) return null
  const params = new URLSearchParams(value.slice(value.indexOf('?') + 1))
  const code = params.get('c') || ''
  const urls = params.getAll('u').map((u) => normalizeInstanceUrl(u)).filter(Boolean)
  return code && urls.length ? { code, urls } : null
}

/** Moves the per-instance keys of `from` aside and brings back those of `to`. */
function swapScopedState(from: string, to: string) {
  const saved: Record<string, string> = {}
  const keys: string[] = []
  for (let i = 0; i < localStorage.length; i++) {
    const key = localStorage.key(i)
    if (key && (SCOPED_KEYS.includes(key) || SCOPED_PREFIXES.some((p) => key.startsWith(p)))) keys.push(key)
  }
  for (const key of keys) {
    saved[key] = localStorage.getItem(key) || ''
    localStorage.removeItem(key)
  }
  try {
    localStorage.setItem(STATE_PREFIX + (from || 'local'), JSON.stringify(saved))
    const restored = JSON.parse(localStorage.getItem(STATE_PREFIX + (to || 'local')) || '{}')
    for (const [key, value] of Object.entries(restored)) localStorage.setItem(key, String(value))
  } catch {
    // a fresh start on the other side is fine
  }
}

/** Makes `id` (empty for this computer) the active instance and reloads. */
export function activateInstance(id: string) {
  const doc = readInstances()
  if (id && !doc.items.some((i) => i.id === id)) return
  if (doc.active !== id) {
    swapScopedState(doc.active, id)
    doc.active = id
    writeInstances(doc)
  }
  window.location.reload()
}

/** Drops an instance from the list; returns whether it was the active one. */
export function removeInstance(id: string): boolean {
  const doc = readInstances()
  const wasActive = doc.active === id
  if (wasActive) {
    swapScopedState(id, '')
    doc.active = ''
  }
  doc.items = doc.items.filter((i) => i.id !== id)
  writeInstances(doc)
  try {
    localStorage.removeItem(STATE_PREFIX + id)
  } catch {
    // nothing to clean
  }
  return wasActive
}
