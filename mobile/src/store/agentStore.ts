import {useCallback, useEffect, useState} from 'react';
import {create} from 'zustand';
import {getAgents, setAgentKnowledgeMode, updateAgent, type AgentPatch} from '../api/cowApi';
import {ApiError} from '../api/http';
import type {AgentProfile} from '../protocol/resources';
import {readJSON, writeJSON} from '../storage/kv';
import {resetOnSignOut} from './reset';

interface AgentState {
  /** Enabled Agents, the ones chats can go to. */
  agents: AgentProfile[];
  /** Every Agent including archived ones, for the management pages. */
  roster: AgentProfile[];
  defaultId: string | null;
  /** The Agent new chats go to; follows whichever session was opened last. */
  currentId: string | null;
  revision?: string;
  load: () => Promise<void>;
  select: (agentId: string) => void;
  /** Applies a roster edit; on a stale revision reloads once and retries. */
  update: (agentId: string, patch: AgentPatch) => Promise<void>;
  /** Shared vs own knowledge directory for a non-default Agent. */
  setKnowledgeMode: (agentId: string, mode: 'shared' | 'own') => Promise<void>;
}

const CURRENT_KEY = 'agent:current';

export const useAgentStore = create<AgentState>((set, get) => ({
  agents: [],
  roster: [],
  defaultId: null,
  currentId: null,

  load: async () => {
    const [res, saved] = await Promise.all([
      getAgents(),
      get().currentId ? Promise.resolve(get().currentId) : readJSON<string | null>(CURRENT_KEY, null),
    ]);
    const agents = res.agents.filter(a => a.enabled !== false);
    const currentId =
      saved && agents.some(a => a.id === saved) ? saved : res.default_agent_id;
    set({agents, roster: res.agents, defaultId: res.default_agent_id, currentId, revision: res.revision});
  },

  select: agentId => {
    if (get().currentId === agentId) {
      return;
    }
    set({currentId: agentId});
    writeJSON(CURRENT_KEY, agentId).catch(() => undefined);
  },

  update: async (agentId, patch) => {
    try {
      await updateAgent(agentId, patch, get().revision);
    } catch (e) {
      if (!(e instanceof ApiError && e.status === 409)) {
        throw e;
      }
      await get().load();
      await updateAgent(agentId, patch, get().revision);
    }
    await get().load();
  },

  setKnowledgeMode: async (agentId, mode) => {
    await setAgentKnowledgeMode(agentId, mode);
    await get().load();
  },
}));

resetOnSignOut(useAgentStore);

export function useCurrentAgent(): AgentProfile | undefined {
  return useAgentStore(s => s.agents.find(a => a.id === s.currentId));
}

/**
 * Which Agent's data a management page shows, remembered per page under `key`.
 * Starts at the Agent new chats go to; a remembered Agent that no longer exists falls back to it.
 */
export function useViewedAgent(key: string) {
  const agents = useAgentStore(s => s.agents);
  const currentId = useAgentStore(s => s.currentId);
  const defaultId = useAgentStore(s => s.defaultId);
  const [picked, setPicked] = useState<string | null>(null);
  const [restored, setRestored] = useState(false);
  const [rosterFailed, setRosterFailed] = useState(false);

  useEffect(() => {
    if (!agents.length) {
      useAgentStore
        .getState()
        .load()
        .catch(() => setRosterFailed(true));
    }
  }, [agents.length]);

  useEffect(() => {
    let alive = true;
    readJSON<string | null>(`view-agent:${key}`, null)
      .then(saved => alive && setPicked(saved))
      .finally(() => alive && setRestored(true));
    return () => {
      alive = false;
    };
  }, [key]);

  const valid = (id: string | null) => !!id && agents.some(a => a.id === id);
  const agentId = valid(picked) ? picked : valid(currentId) ? currentId : defaultId;
  const agent = agents.find(a => a.id === agentId);

  const select = useCallback(
    (id: string) => {
      setPicked(id);
      writeJSON(`view-agent:${key}`, id).catch(() => undefined);
    },
    [key],
  );

  return {
    /** False until the remembered choice is read, so the first request already goes to the right Agent. */
    ready: restored && (agents.length > 0 || rosterFailed),
    /** Null when the roster is unknown, which requests treat as the default Agent. */
    agentId,
    agent,
    /** Only worth a switcher when there is someone to switch to. */
    multi: agents.length > 1,
    isDefault: agentId === defaultId,
    select,
  };
}

/** `undefined` for the default Agent so requests stay identical to the web console's. */
export function agentParam(agentId: string | null | undefined): string | undefined {
  const {defaultId} = useAgentStore.getState();
  return agentId && agentId !== defaultId ? agentId : undefined;
}
