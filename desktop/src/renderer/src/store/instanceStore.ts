import { create } from 'zustand'
import apiClient from '../api/client'
import {
  InstanceError,
  activateInstance,
  deviceInfo,
  instanceHost,
  newInstanceId,
  readInstances,
  removeInstance,
  updateInstance,
  writeInstances,
  type Instance,
} from '../api/instances'
import { guardDocEditors } from './docEditorStore'

export type InstanceStatus = 'online' | 'offline' | 'checking'

export interface AddInstanceRequest {
  /** Prefilled address, e.g. when pairing again with an instance already listed. */
  url?: string
  /** The listed instance a new pairing replaces. */
  replaceId?: string
}

interface InstanceState {
  items: Instance[]
  /** Empty while this app drives its own backend. */
  activeId: string
  status: Record<string, InstanceStatus>
  addRequest: AddInstanceRequest | null
  manageOpen: boolean
  refreshStatus: () => Promise<void>
  openAdd: (request?: AddInstanceRequest) => void
  closeAdd: () => void
  openManage: () => void
  closeManage: () => void
  rename: (id: string, name: string) => void
  pair: (urls: string[], code: string, replaceId?: string) => Promise<Instance>
  switchTo: (id: string) => void
  /** Gives the device up on the other side (best effort) and drops it here. */
  forget: (id: string) => Promise<void>
}

/** What answers at an address, without credentials. */
export async function probeInstance(base: string, timeout = 6000): Promise<{ version?: string }> {
  const ctrl = new AbortController()
  const timer = setTimeout(() => ctrl.abort(), timeout)
  try {
    const res = await fetch(`${base}/.well-known/cowagent`, { signal: ctrl.signal, cache: 'no-store' })
    const body = await res.json().catch(() => null)
    if (!body || body.type !== 'instance') throw new InstanceError('not_instance')
    return body
  } catch (e) {
    throw e instanceof InstanceError ? e : new InstanceError('unreachable')
  } finally {
    clearTimeout(timer)
  }
}

/** Why the active instance can't be used right now, or null when it can. */
export async function checkRemote(item: Instance): Promise<'unreachable' | 'auth_lost' | 'not_instance' | null> {
  if (!item.token) return 'auth_lost'
  try {
    await probeInstance(item.url, 8000)
  } catch (e) {
    return (e as InstanceError).reason === 'not_instance' ? 'not_instance' : 'unreachable'
  }
  try {
    const res = await apiClient.authCheck()
    if (res.auth_required && !res.authenticated) {
      apiClient.setAuthToken(null)
      return 'auth_lost'
    }
  } catch {
    return 'unreachable'
  }
  return null
}

function sameOrigin(a: string, b: string): boolean {
  try {
    const x = new URL(a)
    const y = new URL(b)
    const loop = (h: string) => (['localhost', '127.0.0.1', '[::1]'].includes(h) ? 'localhost' : h)
    return x.protocol === y.protocol && loop(x.hostname) === loop(y.hostname) && x.port === y.port
  } catch {
    return false
  }
}

export const useInstanceStore = create<InstanceState>((set, get) => {
  const initial = readInstances()
  return {
    items: initial.items,
    activeId: apiClient.getInstance()?.id || '',
    status: {},
    addRequest: null,
    manageOpen: false,

    refreshStatus: async () => {
      const items = readInstances().items
      set({ items, status: Object.fromEntries(items.map((i) => [i.id, get().status[i.id] || 'checking'])) })
      await Promise.all(
        items.map(async (item) => {
          let state: InstanceStatus = 'offline'
          try {
            await probeInstance(item.url, 5000)
            state = 'online'
          } catch {
            // stays offline
          }
          set((s) => ({ status: { ...s.status, [item.id]: state } }))
        }),
      )
    },

    openAdd: (request) => set({ addRequest: request || {}, manageOpen: false }),
    closeAdd: () => set({ addRequest: null }),
    openManage: () => set({ manageOpen: true }),
    closeManage: () => set({ manageOpen: false }),

    rename: (id, name) => {
      const next = name.trim()
      if (!next) return
      updateInstance(id, { name: next, custom_name: true })
      set({ items: readInstances().items })
    },

    pair: async (urls, code, replaceId) => {
      const local = apiClient.isRemote() ? '' : apiClient.getBaseUrl()
      if (local && urls.some((u) => sameOrigin(u, local))) throw new InstanceError('self')

      let url = ''
      let failure: InstanceError | null = null
      for (const candidate of urls) {
        try {
          await probeInstance(candidate)
          url = candidate
          break
        } catch (e) {
          if (failure?.reason !== 'not_instance') failure = e as InstanceError
        }
      }
      if (!url) throw failure || new InstanceError('unreachable')

      let data: {
        status?: string
        reason?: string
        retry_after?: number
        token?: string
        device?: { id?: string }
        instance?: { name?: string; version?: string }
      }
      try {
        const res = await fetch(`${url}/auth/pair`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ code, device: await deviceInfo() }),
        })
        data = await res.json()
      } catch {
        throw new InstanceError('unreachable')
      }
      if (data.status !== 'success' || !data.token) {
        if (data.reason === 'locked') throw new InstanceError('locked', data.retry_after || 60)
        throw new InstanceError('code_invalid')
      }

      const doc = readInstances()
      const info = data.instance || {}
      let item = doc.items.find((i) => i.id === replaceId) || doc.items.find((i) => i.url === url)
      const patch = {
        url,
        token: data.token,
        device_id: data.device?.id || '',
        name: item?.custom_name ? item.name : info.name || instanceHost(url),
        version: info.version || '',
      }
      if (item) Object.assign(item, patch)
      else {
        item = { id: newInstanceId(), added_at: Date.now(), ...patch }
        doc.items.push(item)
      }
      writeInstances(doc)
      set((s) => ({ items: doc.items, status: { ...s.status, [item!.id]: 'online' } }))
      return item
    },

    switchTo: (id) => {
      if (id === get().activeId) return
      activateInstance(id)
    },

    forget: async (id) => {
      const item = readInstances().items.find((i) => i.id === id)
      if (!item) return
      // Forgetting the active instance reloads the window.
      if (id === get().activeId && !(await guardDocEditors())) return
      if (item.token) {
        const ctrl = new AbortController()
        const timer = setTimeout(() => ctrl.abort(), 3000)
        await fetch(`${item.url}/auth/logout`, {
          method: 'POST',
          headers: { Authorization: `Bearer ${item.token}` },
          signal: ctrl.signal,
        })
          .catch(() => {})
          .finally(() => clearTimeout(timer))
      }
      if (removeInstance(id)) {
        window.location.reload()
        return
      }
      set({ items: readInstances().items })
    },
  }
})
