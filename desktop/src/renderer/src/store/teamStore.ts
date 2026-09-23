import { create } from 'zustand'
import apiClient from '../api/client'
import type { TeamGroup } from '../types'

/**
 * Named teams: saved, leader-led Agent groups (the sidebar "Teams" section).
 * The rosters live in the backend's team store and are shared with the web
 * console through /api/team-groups; this store only mirrors the list for the
 * session sidebar and its create modal.
 *
 * Which conversation carries which team is a client-side mapping, kept in
 * localStorage under the exact keys the web console uses (`cow_team_session_`
 * keyed by team, `cow_team_of_` keyed by session), so the two clients agree
 * when re-opening a team and a delete on either side cleans both halves.
 */

const teamSessionKey = (teamId: string) => `cow_team_session_${teamId}`
const teamOfKey = (sessionId: string) => `cow_team_of_${sessionId}`

/** The session id a team was last opened into, or '' when none is recorded. */
export function teamSessionOf(teamId: string): string {
  try {
    return localStorage.getItem(teamSessionKey(teamId)) || ''
  } catch {
    return ''
  }
}

/** The team a session was opened from, or '' for plain conversations. */
export function teamOfSession(sessionId: string): string {
  try {
    return localStorage.getItem(teamOfKey(sessionId)) || ''
  } catch {
    return ''
  }
}

interface TeamStoreState {
  teams: TeamGroup[]
  /** True once the list has been fetched at least once. */
  loaded: boolean
  load: () => Promise<void>
  fetchOne: (teamId: string) => Promise<TeamGroup | null>
  create: (name: string, leader: string, members: string[]) => Promise<TeamGroup>
  remove: (teamId: string) => Promise<void>
  rememberSession: (teamId: string, sessionId: string) => void
}

export const useTeamStore = create<TeamStoreState>((set) => ({
  teams: [],
  loaded: false,

  // Best-effort by design (the client swallows transport errors): an old
  // backend without the endpoint just leaves the section empty.
  load: async () => {
    const teams = await apiClient.listTeamGroups()
    set({ teams, loaded: true })
  },

  fetchOne: async (teamId) => {
    const team = await apiClient.getTeamGroup(teamId)
    if (team) {
      set((s) => ({
        teams: s.teams.some((tm) => tm.id === teamId)
          ? s.teams.map((tm) => (tm.id === teamId ? team : tm))
          : [...s.teams, team],
      }))
    }
    return team
  },

  create: async (name, leader, members) => {
    const team = await apiClient.createTeamGroup(name, leader, members)
    set((s) => ({ teams: [...s.teams, team] }))
    return team
  },

  remove: async (teamId) => {
    // Same cleanup as the web console: forget both halves of the mapping
    // (which session carries the team, and which team the session carries).
    // The backend delete is best-effort there too; local state is the part
    // this app owns.
    try {
      const saved = teamSessionOf(teamId)
      if (saved) localStorage.removeItem(teamOfKey(saved))
      localStorage.removeItem(teamSessionKey(teamId))
    } catch {
      /* storage unavailable */
    }
    set((s) => ({ teams: s.teams.filter((tm) => tm.id !== teamId) }))
  },

  rememberSession: (teamId, sessionId) => {
    try {
      const prev = teamSessionOf(teamId)
      if (prev && prev !== sessionId) localStorage.removeItem(teamOfKey(prev))
      localStorage.setItem(teamSessionKey(teamId), sessionId)
      localStorage.setItem(teamOfKey(sessionId), teamId)
    } catch {
      /* storage unavailable */
    }
  },
}))