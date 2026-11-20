import { create } from 'zustand'
import apiClient from '../api/client'
import {
  InstanceError,
  activateInstance,
  deviceInfo,
  diagnoseInstance,
  instanceHost,
  newInstanceId,
  readInstances,
  removeInstance,
  sameDevice,
  updateInstance,
  writeInstances,
  type Discovery,
  type Instance,
} from '../api/instances'
import { guardDocEditors } from './docEditorStore'

/** `other`: the address answers, but as a different CowAgent device. */
export type InstanceStatus = 'online' | 'offline' | 'checking' | 'other'

export type RemoteProblemReason = 'unreachable' | 'auth_lost' | 'wrong_device' | 'not_cowagent' | 'outdated'

export interface AddInstanceRequest {
  /** Prefilled address, e.g. when pairing again with a device already listed. */
  url?: string
  /** The listed device a new pairing replaces. */
  replaceId?: string
}

const LOCAL_KEY = 'cow_local_device'
const SWITCHER_KEY = 'cow_device_switcher'

function readLocalName(): string {
  try {
    return JSON.parse(localStorage.getItem(LOCAL_KEY) || '{}').name || ''
  } catch {
    return ''
  }
}

function readSwitcherHidden(): boolean {
  try {
    return localStorage.getItem(SWITCHER_KEY) === 'hidden'
  } catch {
    return false
  }
}

interface InstanceState {
  items: Instance[]
  /** Empty while this app drives its own backend. */
  activeId: string
  status: Record<string, InstanceStatus>
  /** The name this computer's CowAgent goes by; empty until it has told us. */
  localName: string
  /** Kept on this computer only; never hides while another device is active. */
  switcherHidden: boolean
  addRequest: AddInstanceRequest | null
  refreshStatus: () => Promise<void>
  openAdd: (request?: AddInstanceRequest) => void
  closeAdd: () => void
  /** Takes in what the device this app talks to says about itself. */
  noteDevice: (device?: { id?: string; name?: string; managed?: boolean } | null) => void
  setSwitcherHidden: (hidden: boolean) => void
  /** Renames another device on that device, so every client sees the new name. */
  renameRemote: (id: string, name: string) => Promise<void>
  pair: (typed: string[], code: string, replaceId?: string) => Promise<Instance>
  switchTo: (id: string) => void
  /** Gives the device up on the other side (best effort) and drops it here. */
  forget: (id: string) => Promise<void>
}

/** Why the active device can't be used right now, or null when it can. */
export async function checkRemote(item: Instance): Promise<RemoteProblemReason | null> {
  if (!item.token) return 'auth_lost'
  let info: Discovery
  try {
    info = await diagnoseInstance(item.url, 8000)
  } catch (e) {
    const reason = (e as InstanceError).reason
    return reason === 'not_cowagent' || reason === 'outdated' ? reason : 'unreachable'
  }
  if (!sameDevice(item, info)) return 'wrong_device'
  if (!item.instance_id && info.id) apiClient.adoptInstanceId(info.id)
  if ((await apiClient.confirmInstance(true)) !== 'ok') return 'unreachable'
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

// When several addresses fail, report the one that says the most.
const FAILURE_RANK = ['not_cowagent', 'outdated', 'login', 'blocked', 'timeout', 'unreachable']

function moreTelling(a: InstanceError | null, b: InstanceError): InstanceError {
  if (!a) return b
  const rank = (e: InstanceError) => {
    const i = FAILURE_RANK.indexOf(e.reason)
    return i < 0 ? FAILURE_RANK.length : i
  }
  return rank(b) < rank(a) ? b : a
}

/** Gives a token up on its device, only once that device is confirmed at the address. */
async function release(item: Instance): Promise<void> {
  if (!item.token) return
  try {
    const info = await diagnoseInstance(item.url, 4000)
    if (!sameDevice(item, info)) return
    const ctrl = new AbortController()
    const timer = setTimeout(() => ctrl.abort(), 3000)
    await fetch(`${item.url}/auth/logout`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${item.token}` },
      signal: ctrl.signal,
    }).finally(() => clearTimeout(timer))
  } catch {
    // it may be gone already
  }
}

export const useInstanceStore = create<InstanceState>((set, get) => {
  const initial = readInstances()
  return {
    items: initial.items,
    activeId: apiClient.getInstance()?.id || '',
    status: {},
    localName: readLocalName(),
    switcherHidden: readSwitcherHidden(),
    addRequest: null,

    refreshStatus: async () => {
      const items = readInstances().items
      const activeId = get().activeId
      set({ items, status: Object.fromEntries(items.map((i) => [i.id, get().status[i.id] || 'checking'])) })
      await Promise.all(
        items.map(async (item) => {
          let state: InstanceStatus = 'offline'
          if (item.id === activeId) state = 'online'
          else {
            try {
              state = sameDevice(item, await diagnoseInstance(item.url, 5000)) ? 'online' : 'other'
            } catch {
              // stays offline
            }
          }
          set((s) => ({ status: { ...s.status, [item.id]: state } }))
        }),
      )
    },

    openAdd: (request) => set({ addRequest: request || {} }),
    closeAdd: () => set({ addRequest: null }),

    noteDevice: (device) => {
      if (!device?.name) return
      const active = apiClient.getInstance()
      if (active) {
        const managed = !!device.managed
        if (active.name !== device.name || !!active.managed !== managed) {
          active.name = device.name
          active.managed = managed
          updateInstance(active.id, { name: device.name, managed })
          set({ items: readInstances().items })
        }
        return
      }
      try {
        localStorage.setItem(LOCAL_KEY, JSON.stringify({ id: device.id || '', name: device.name }))
      } catch {
        // the name still shows this session
      }
      set({ localName: device.name })
    },

    setSwitcherHidden: (hidden) => {
      try {
        if (hidden) localStorage.setItem(SWITCHER_KEY, 'hidden')
        else localStorage.removeItem(SWITCHER_KEY)
      } catch {
        // applies this session
      }
      set({ switcherHidden: hidden })
    },

    renameRemote: async (id, name) => {
      const item = readInstances().items.find((i) => i.id === id)
      const next = name.trim()
      if (!item || !next || next === item.name) return
      const info = await diagnoseInstance(item.url, 5000)
      if (!sameDevice(item, info)) throw new InstanceError('wrong_device', 0, instanceHost(item.url))
      const res = await fetch(`${item.url}/api/device`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${item.token}` },
        body: JSON.stringify({ name: next }),
      })
      const data = await res.json().catch(() => null)
      if (data?.status !== 'success' || !data.instance?.name) throw new InstanceError('refused')
      updateInstance(id, { name: data.instance.name })
      set({ items: readInstances().items })
    },

    pair: async (typed, code, replaceId) => {
      const local = apiClient.isRemote() ? '' : apiClient.getBaseUrl()
      if (local && typed.some((u) => sameOrigin(u, local))) throw new InstanceError('self')

      let url = ''
      let found: Discovery | null = null
      let failure: InstanceError | null = null
      for (const candidate of typed) {
        try {
          found = await diagnoseInstance(candidate)
          url = candidate
          break
        } catch (e) {
          failure = moreTelling(failure, e as InstanceError)
        }
      }
      if (!url || !found) throw failure || new InstanceError('unreachable')

      let data: {
        status?: string
        reason?: string
        retry_after?: number
        token?: string
        instance?: { id?: string; name?: string; version?: string; managed?: boolean }
      }
      try {
        const res = await fetch(`${url}/auth/pair`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ code, device: await deviceInfo() }),
        })
        data = await res.json()
      } catch {
        throw new InstanceError('unreachable', 0, instanceHost(url))
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
        instance_id: info.id || found.id || '',
        managed: !!info.managed,
        name: info.name || instanceHost(url),
        version: info.version || found.version || '',
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
      // Forgetting the active device reloads the window.
      if (id === get().activeId && !(await guardDocEditors())) return
      await release(item)
      if (removeInstance(id)) {
        window.location.reload()
        return
      }
      set({ items: readInstances().items })
    },
  }
})
