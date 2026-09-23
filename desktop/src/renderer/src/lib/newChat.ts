import apiClient from '../api/client'
import { useSessionStore } from '../store/sessionStore'
import { useChatStore } from '../store/chatStore'
import { useUIStore } from '../store/uiStore'
import { useAgentStore } from '../store/agentStore'
import { useSessionSettingsStore } from '../store/sessionSettingsStore'
import { useWorkspaceStore } from '../store/workspaceStore'
import { useTeamStore, teamSessionOf } from '../store/teamStore'

/**
 * Start a fresh conversation. One code path for every "new chat" entry point
 * (session list, composer, app menu, Agent switch), so they all behave alike.
 *
 * `ownerId` picks the Agent the conversation belongs to (multi-Agent mode);
 * omitted, it's the active Agent. `inheritProject` keeps the new chat in the
 * current session's workspace, which is what a plain "+" should do — but a
 * chat opened for a *different* Agent starts on that Agent's own root, like the
 * web console, since the project record belongs to the previous owner.
 */
export function startNewChat(opts?: { ownerId?: string; inheritProject?: boolean }): string {
  const inheritProject = opts?.inheritProject ?? true
  const sessions = useSessionStore.getState()
  const inherited = inheritProject ? sessions.currentProject() : null
  const id = sessions.newSession(opts?.ownerId)
  const chat = useChatStore.getState()
  chat.ensureSession(id)
  void chat.loadHistory(id, 1)
  // Show the fresh chat in the list immediately (under the inherited space),
  // and expand the session list so the user sees the new session.
  useSessionStore.getState().addOptimistic(id, inherited)
  useUIStore.getState().setSessionsCollapsed(false)
  if (inherited) apiClient.selectProject(id, inherited.path).catch(() => {})
  return id
}

/**
 * Open a new conversation as a group: `ownerId` owns it and `guestIds` are
 * invited before the first message, so the very first turn already goes to a
 * team. Returns the new session id.
 */
export async function startTeamChat(ownerId: string, guestIds: string[]): Promise<string> {
  useAgentStore.getState().setActive(ownerId)
  const id = startNewChat({ ownerId, inheritProject: false })
  const guests = Array.from(new Set(guestIds.filter((g) => g && g !== ownerId)))
  if (guests.length) {
    await useSessionSettingsStore.getState().apply(id, { members: guests })
  }
  return id
}

/**
 * Open a named team from the sidebar's "Teams" section. Enters the
 * conversation that already carries the team when that session still exists;
 * otherwise starts a fresh group chat owned by the team's leader with the
 * roster seeded from the team — mirroring the web console's openNamedTeam().
 * Returns the opened session id, or '' when the team is gone.
 */
export async function openNamedTeam(teamId: string): Promise<string> {
  const teamStore = useTeamStore.getState()
  const team = teamStore.teams.find((tm) => tm.id === teamId) || (await teamStore.fetchOne(teamId))
  if (!team) return ''

  // Reattach: the session recorded last time, when it still exists, already
  // carries the roster — opening it is just switching to it.
  const saved = teamSessionOf(teamId)
  if (saved) {
    const exists = useSessionStore.getState().sessions.some((s) => s.session_id === saved)
    if (exists) {
      await useSessionStore.getState().setActive(saved)
      useTeamStore.getState().rememberSession(teamId, saved)
      return saved
    }
  }

  // Fresh: a new chat re-scopes the workspace panel, closing any open editor.
  if (!(await useWorkspaceStore.getState().guardUnsavedEdit())) return ''
  const guests = (team.members || [])
    .map((m) => m.id)
    .filter((id) => id && id !== team.leader)
  const id = await startTeamChat(team.leader, guests)
  useTeamStore.getState().rememberSession(teamId, id)
  return id
}
