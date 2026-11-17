/**
 * Instances this app can drive besides the one it starts itself: CowAgent
 * running on another computer or server, joined with a one-time pairing code.
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
  device_id: string
  version: string
  added_at: number
  custom_name?: boolean
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
  ) {
    super(reason)
  }
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

export function normalizeInstanceUrl(value: string): string {
  let text = (value || '').trim()
  if (!text) return ''
  if (!/^https?:\/\//i.test(text)) text = `http://${text}`
  try {
    const url = new URL(text)
    return `${url.protocol}//${url.host}`
  } catch {
    return ''
  }
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
  const urls = params.getAll('u').map(normalizeInstanceUrl).filter(Boolean)
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
