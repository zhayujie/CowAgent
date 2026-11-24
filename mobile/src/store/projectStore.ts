import {create} from 'zustand';
import {createProject, getProjects, selectProject} from '../api/cowApi';
import type {ProjectState} from '../protocol/resources';
import {agentParam} from './agentStore';
import {resetOnSignOut} from './reset';

interface ProjectStoreState {
  /** Only sessions whose server answered; a server without projects never gets an entry. */
  bySession: Record<string, ProjectState>;
  load: (sessionId: string, agentId: string | null) => Promise<void>;
  /** null sends the session back to the Agent's own workspace. */
  select: (sessionId: string, agentId: string | null, projectDir: string | null) => Promise<void>;
  create: (sessionId: string, agentId: string | null, name: string) => Promise<void>;
}

// Per session, only the request sent last may write: a slow read must not undo a later switch,
// and nothing sent before a sign-out may land after it.
let latest: Record<string, number> = {};

export const useProjectStore = create<ProjectStoreState>(set => {
  const put = async (sessionId: string, request: Promise<ProjectState>) => {
    const id = (latest[sessionId] ?? 0) + 1;
    latest[sessionId] = id;
    const value = await request;
    if (latest[sessionId] === id) {
      set(s => ({bySession: {...s.bySession, [sessionId]: value}}));
    }
  };

  return {
    bySession: {},

    load: (sessionId, agentId) => put(sessionId, getProjects(sessionId, agentParam(agentId))),

    select: (sessionId, agentId, projectDir) =>
      put(sessionId, selectProject(sessionId, projectDir, agentParam(agentId))),

    create: (sessionId, agentId, name) => put(sessionId, createProject(sessionId, name, agentParam(agentId))),
  };
});

resetOnSignOut(useProjectStore, () => {
  latest = {};
});
