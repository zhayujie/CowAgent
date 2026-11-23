import {useOverviewStore} from '../store/overviewStore';
import {useLocalServer} from '../store/serverStore';
import {appUpdatesSupported, appVersion} from './appUpdate';

/** The version to show for the agent: the app's own when it runs inside the app, else the server's. */
export function useAgentVersion(): string | null {
  const local = useLocalServer();
  const server = useOverviewStore(s => s.version);
  return local && appUpdatesSupported() ? appVersion : server;
}
