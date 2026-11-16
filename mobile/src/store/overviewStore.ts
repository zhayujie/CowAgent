import {create} from 'zustand';
import {getArtifacts, getChannels, getScheduledTasks, getSkills, getVersion} from '../api/cowApi';
import {resetOnSignOut} from './reset';

export interface OverviewCounts {
  artifacts?: string;
  skills?: number;
  tasks?: number;
  channels?: number;
}

interface OverviewState {
  counts: OverviewCounts;
  version: string | null;
  load: () => Promise<void>;
}

const ARTIFACT_PROBE = 100;

/** Badge numbers for the drawer; each one is optional and fails quietly. */
export const useOverviewStore = create<OverviewState>(set => ({
  counts: {},
  version: null,
  load: async () => {
    const [artifacts, skills, tasks, channels, version] = await Promise.allSettled([
      getArtifacts({limit: ARTIFACT_PROBE}),
      getSkills(),
      getScheduledTasks(),
      getChannels(),
      getVersion(),
    ]);
    const counts: OverviewCounts = {};
    if (artifacts.status === 'fulfilled') {
      const n = artifacts.value.items.length;
      counts.artifacts = artifacts.value.has_more ? `${n}+` : String(n);
    }
    if (skills.status === 'fulfilled') {
      counts.skills = skills.value.skills.filter(s => s.enabled).length;
    }
    if (tasks.status === 'fulfilled') {
      counts.tasks = tasks.value.tasks.length;
    }
    if (channels.status === 'fulfilled') {
      counts.channels = channels.value.channels.filter(c => c.active).length;
    }
    set(s => ({
      counts,
      version: version.status === 'fulfilled' ? version.value.version ?? null : s.version,
    }));
  },
}));

resetOnSignOut(useOverviewStore);
