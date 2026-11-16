import {create} from 'zustand';
import {getSessionSettings, updateSessionSettings} from '../api/cowApi';
import type {PermissionMode, SessionSettings} from '../protocol/resources';
import {agentParam} from './agentStore';
import {resetOnSignOut} from './reset';

interface SessionSettingsState {
  bySession: Record<string, SessionSettings>;
  load: (sessionId: string, agentId: string | null) => Promise<void>;
  /** null drops the session pin and follows the Agent / global model again. */
  setModel: (
    sessionId: string,
    agentId: string | null,
    pick: {provider: string; model: string} | null,
  ) => Promise<void>;
  setPermission: (
    sessionId: string,
    agentId: string | null,
    mode: PermissionMode | null,
  ) => Promise<void>;
  /** Teammates besides the owner; an empty list turns the chat back into a solo one. */
  setMembers: (sessionId: string, agentId: string | null, members: string[]) => Promise<void>;
}

export const useSessionSettingsStore = create<SessionSettingsState>((set, get) => {
  const put = (sessionId: string, value: SessionSettings) =>
    set(s => ({bySession: {...s.bySession, [sessionId]: value}}));

  /** Show the choice right away; the server's answer (or the old state on failure) wins. */
  const apply = async (
    sessionId: string,
    agentId: string | null,
    optimistic: (cur: SessionSettings) => SessionSettings,
    body: Parameters<typeof updateSessionSettings>[1],
  ) => {
    const before = get().bySession[sessionId];
    if (before) {
      put(sessionId, optimistic(before));
    }
    try {
      put(sessionId, await updateSessionSettings(sessionId, body, agentParam(agentId)));
    } catch (e) {
      if (before) {
        put(sessionId, before);
      }
      throw e;
    }
  };

  return {
    bySession: {},

    load: async (sessionId, agentId) => {
      put(sessionId, await getSessionSettings(sessionId, agentParam(agentId)));
    },

    setModel: (sessionId, agentId, pick) =>
      apply(
        sessionId,
        agentId,
        cur => ({
          ...cur,
          model: pick
            ? {...cur.model, ...pick, source: 'session'}
            : {
                ...cur.model,
                model: cur.model.agent?.model ?? cur.model.global?.model ?? cur.model.model,
                provider:
                  cur.model.agent?.provider ?? cur.model.global?.provider ?? cur.model.provider,
                source: cur.model.agent ? 'agent' : 'global',
              },
        }),
        pick ? {model: pick.model, provider: pick.provider} : {model: null, provider: null},
      ),

    setPermission: (sessionId, agentId, mode) =>
      apply(
        sessionId,
        agentId,
        cur => ({
          ...cur,
          permission: {
            ...cur.permission,
            mode: mode ?? cur.permission.global,
            source: mode ? 'session' : 'global',
          },
        }),
        {permission: mode},
      ),

    setMembers: (sessionId, agentId, members) =>
      apply(
        sessionId,
        agentId,
        cur => {
          if (!cur.team) {
            return cur;
          }
          const known = [...cur.team.members, ...cur.team.candidates];
          return {
            ...cur,
            team: {
              ...cur.team,
              members: members.map(id => known.find(a => a.id === id) ?? {id, name: id, available: true}),
            },
          };
        },
        {members: members.length ? members : null},
      ),
  };
});

resetOnSignOut(useSessionSettingsStore);
