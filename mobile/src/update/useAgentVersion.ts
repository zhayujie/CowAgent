import {useOverviewStore} from '../store/overviewStore';
import {useLocalServer} from '../store/serverStore';
import {appVersion} from './appUpdate';

/**
 * This phone's version: the app and the agent inside it ship together. A remote agent's version
 * belongs to its device entry, not here. Builds that can't tell their own version fall back to
 * the agent on this phone.
 */
export function useAgentVersion(): string | null {
  const local = useLocalServer();
  const server = useOverviewStore(s => s.version);
  return appVersion || (local ? server : null);
}
