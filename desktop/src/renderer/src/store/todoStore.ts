import { create } from 'zustand'
import type { TodoSnapshot } from '../types'

// JSON tuple keys keep Agent/session pairs distinct even when ids contain separators.
export function todoScope(agentId: string, sessionId: string): string | null {
  return agentId.trim() && sessionId.trim() ? JSON.stringify([agentId, sessionId]) : null
}

export function parseTodoSnapshot(value: unknown, agentId: string, sessionId: string): TodoSnapshot | null {
  if (!todoScope(agentId, sessionId) || !value || typeof value !== 'object') return null
  const v = value as Record<string, unknown>
  if (v.agent_id !== agentId || v.session_id !== sessionId ||
      !Number.isSafeInteger(v.version) || (v.version as number) < 1 || !Array.isArray(v.todos)) return null
  if (!v.todos.every(item => item && typeof item === 'object' &&
      typeof item.content === 'string' && item.content.trim() &&
      ['pending', 'in_progress', 'completed'].includes(item.status))) return null
  return { ...v, todos: v.todos.map(item => ({ content: item.content, status: item.status })) } as unknown as TodoSnapshot
}

interface TodoState {
  snapshots: Record<string, TodoSnapshot>
  applySnapshot: (value: unknown, agentId: string, sessionId: string) => void
  clearSession: (sessionId: string) => void
}

export const useTodoStore = create<TodoState>((set) => ({
  snapshots: {},
  applySnapshot: (value, agentId, sessionId) => {
    const snapshot = parseTodoSnapshot(value, agentId, sessionId)
    const key = todoScope(agentId, sessionId)
    if (!snapshot || !key) return
    set(state => {
      // Equal versions are retries, and older history/SSE may arrive out of order.
      if ((state.snapshots[key]?.version || 0) >= snapshot.version) return state
      return { snapshots: { ...state.snapshots, [key]: snapshot } }
    })
  },
  clearSession: sessionId => set(state => ({
    snapshots: Object.fromEntries(Object.entries(state.snapshots).filter(([, snapshot]) => snapshot.session_id !== sessionId)),
  })),
}))
