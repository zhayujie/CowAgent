import {create} from 'zustand';
import {createProject, getProjects, selectProject} from '../api/cowApi';
import type {ProjectState} from '../protocol/resources';
import {agentParam} from './agentStore';
import {resetOnSignOut} from './reset';

/** Project bindings are scoped by both Agent and session on the server. */
export const workspaceKey = (sessionId: string, agentId: string | null) => JSON.stringify([agentId, sessionId]);

interface WorkspaceState {
  byChat: Record<string, ProjectState>;
  load: (sessionId: string, agentId: string | null) => Promise<void>;
  select: (sessionId: string, agentId: string | null, projectDir: string | null) => Promise<void>;
  create: (sessionId: string, agentId: string | null, name: string) => Promise<void>;
}

let generation = 0;

export const useWorkspaceStore = create<WorkspaceState>(set => {
  // A slow response must not overwrite a newer load or selection for the same chat.
  const requests = new Map<string, number>();

  const apply = async (key: string, request: () => Promise<ProjectState>) => {
    const id = (requests.get(key) ?? 0) + 1;
    requests.set(key, id);
    const atGeneration = generation;
    const state = await request();
    if (generation === atGeneration && requests.get(key) === id) {
      set(s => ({byChat: {...s.byChat, [key]: state}}));
    }
  };

  return {
    byChat: {},

    load: (sessionId, agentId) =>
      apply(workspaceKey(sessionId, agentId), () => getProjects(sessionId, agentParam(agentId))),

    select: (sessionId, agentId, projectDir) =>
      apply(workspaceKey(sessionId, agentId), () => selectProject(sessionId, projectDir, agentParam(agentId))),

    create: (sessionId, agentId, name) =>
      apply(workspaceKey(sessionId, agentId), () => createProject(sessionId, name.trim(), agentParam(agentId))),
  };
});

resetOnSignOut(useWorkspaceStore, () => {
  // Invalidate requests that were still running for the previous server.
  generation += 1;
});
