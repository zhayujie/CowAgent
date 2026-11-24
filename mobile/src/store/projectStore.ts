import {create} from 'zustand';
import {createProject, getProjects, selectProject} from '../api/cowApi';
import type {ProjectState} from '../protocol/resources';
import type {Space} from '../utils/sessionGroups';
import {agentParam} from './agentStore';
import {resetOnSignOut} from './reset';

interface ProjectStoreState {
  /** Only sessions whose server answered; a server without projects never gets an entry. */
  bySession: Record<string, ProjectState>;
  load: (sessionId: string, agentId: string | null) => Promise<void>;
  /** null sends the session back to the Agent's own workspace. */
  select: (sessionId: string, agentId: string | null, projectDir: string | null) => Promise<void>;
  create: (sessionId: string, agentId: string | null, name: string) => Promise<void>;
  /** Files a chat not yet sent under a space, showing it there before the server answers. */
  startIn: (sessionId: string, agentId: string | null, space: Space) => Promise<void>;
}

// Per session, only the request sent last may write: a slow read must not undo a later switch,
// and nothing sent before a sign-out may land after it.
let latest: Record<string, number> = {};
// A read sent while a switch is in flight could be answered first, with the folder before it.
let writing: Record<string, Promise<unknown>> = {};

export const useProjectStore = create<ProjectStoreState>((set, get) => {
  const put = async (sessionId: string, request: () => Promise<ProjectState>) => {
    const id = (latest[sessionId] ?? 0) + 1;
    latest[sessionId] = id;
    const value = await request();
    if (latest[sessionId] === id) {
      set(s => ({bySession: {...s.bySession, [sessionId]: value}}));
    }
  };

  const write = (sessionId: string, request: () => Promise<ProjectState>) => {
    const done = put(sessionId, request);
    writing[sessionId] = done;
    return done.finally(() => {
      if (writing[sessionId] === done) {
        delete writing[sessionId];
      }
    });
  };

  return {
    bySession: {},

    load: (sessionId, agentId) => {
      const pending = writing[sessionId];
      return put(sessionId, async () => {
        await pending?.catch(() => undefined);
        return getProjects(sessionId, agentParam(agentId));
      });
    },

    select: (sessionId, agentId, projectDir) =>
      write(sessionId, () => selectProject(sessionId, projectDir, agentParam(agentId))),

    create: (sessionId, agentId, name) =>
      write(sessionId, () => createProject(sessionId, name, agentParam(agentId))),

    startIn: (sessionId, agentId, space) => {
      const current = space.path ? {path: space.path, name: space.name} : null;
      // Any session's answer has the server-wide parts: the default workspace, projects root, recents.
      const known = Object.values(get().bySession)[0];
      if (known) {
        set(s => ({bySession: {...s.bySession, [sessionId]: {...known, current}}}));
      }
      return get().select(sessionId, agentId, space.path);
    },
  };
});

resetOnSignOut(useProjectStore, () => {
  latest = {};
  writing = {};
});
