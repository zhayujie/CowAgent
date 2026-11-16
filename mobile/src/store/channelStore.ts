import {create} from 'zustand';
import {getChannels} from '../api/cowApi';
import type {ChannelsResponse} from '../protocol/resources';
import {resetOnSignOut} from './reset';
import {describeConnectError} from './serverStore';

interface ChannelState {
  data: ChannelsResponse | null;
  error: string | null;
  /** A failed reload keeps the last good list on screen. */
  load: () => Promise<void>;
}

export const useChannelStore = create<ChannelState>(set => ({
  data: null,
  error: null,
  load: async () => {
    try {
      set({data: await getChannels(), error: null});
    } catch (e) {
      set({error: describeConnectError(e)});
    }
  },
}));

resetOnSignOut(useChannelStore);
