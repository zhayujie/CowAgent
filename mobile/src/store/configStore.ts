import {create} from 'zustand';
import {getConfig, getExternalApi, setExternalApi, updateConfig} from '../api/cowApi';
import type {ConfigUpdates, ExternalApiState, GlobalConfig} from '../protocol/resources';
import {resetOnSignOut} from './reset';
import {noteServerName} from './serverStore';

interface ConfigState {
  config: GlobalConfig | null;
  externalApi: ExternalApiState | null;
  error: string | null;
  load: () => Promise<void>;
  /** Optimistic; rolls back and rethrows when the server refuses. */
  update: (updates: ConfigUpdates) => Promise<Awaited<ReturnType<typeof updateConfig>>>;
  setExternalApi: (action: 'enable' | 'disable' | 'regenerate') => Promise<void>;
}

const message = (e: unknown) => (e instanceof Error ? e.message : String(e));

export const useConfigStore = create<ConfigState>((set, get) => ({
  config: null,
  externalApi: null,
  error: null,

  load: async () => {
    const [config, external] = await Promise.allSettled([getConfig(), getExternalApi()]);
    set(s => ({
      config: config.status === 'fulfilled' ? config.value : s.config,
      externalApi: external.status === 'fulfilled' ? external.value : s.externalApi,
      error: config.status === 'rejected' ? message(config.reason) : null,
    }));
    if (config.status === 'fulfilled') {
      noteServerName(config.value.device?.name);
    }
  },

  update: async updates => {
    const previous = get().config;
    if (previous) {
      const {web_password, reasoning_effort_by_model, ...visible} = updates;
      set({
        config: {
          ...previous,
          ...visible,
          reasoning_effort_by_model: {...previous.reasoning_effort_by_model, ...reasoning_effort_by_model},
          ...(web_password === undefined
            ? {}
            : {web_password_masked: web_password ? '*'.repeat(web_password.length) : ''}),
        },
      });
    }
    try {
      return await updateConfig(updates);
    } catch (e) {
      set({config: previous});
      throw e;
    }
  },

  setExternalApi: async action => {
    const next = await setExternalApi(action);
    set({externalApi: next});
  },
}));

resetOnSignOut(useConfigStore);
