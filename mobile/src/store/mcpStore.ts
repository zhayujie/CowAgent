import {create} from 'zustand';
import {getMcpServers, saveMcpServers} from '../api/cowApi';
import {tr} from '../i18n';
import type {McpServer} from '../protocol/resources';
import {resetOnSignOut} from './reset';

interface McpState {
  /** The shared mcp.json every Agent reads, as on the consoles' Capabilities page. */
  servers: McpServer[] | null;
  load: () => Promise<void>;
  /** Writes the whole list, which is how mcp.json is stored. */
  save: (servers: McpServer[]) => Promise<void>;
  upsert: (server: McpServer, previousName?: string) => Promise<void>;
  /** Adds several at once, as a pasted mcp.json does; same-named ones are replaced. */
  merge: (servers: McpServer[]) => Promise<void>;
  remove: (name: string) => Promise<void>;
}

export const useMcpStore = create<McpState>((set, get) => ({
  servers: null,

  load: async () => {
    set({servers: (await getMcpServers()).servers});
  },

  save: async servers => {
    set({servers: (await saveMcpServers(servers)).servers});
  },

  upsert: async (server, previousName) => {
    const current = get().servers ?? [];
    const key = previousName ?? server.name;
    const exists = current.some(s => s.name === key);
    const next = exists ? current.map(s => (s.name === key ? server : s)) : [...current, server];
    await get().save(next);
  },

  merge: async servers => {
    const incoming = new Set(servers.map(s => s.name));
    const kept = (get().servers ?? []).filter(s => !incoming.has(s.name));
    await get().save([...kept, ...servers]);
  },

  remove: async name => {
    await get().save((get().servers ?? []).filter(s => s.name !== name));
  },
}));

resetOnSignOut(useMcpStore);

export const MCP_STATUS: Record<string, {label: string; on?: boolean}> = {
  ready: {
    get label() {
      return tr('mcp_status_ready');
    },
    on: true,
  },
  pending: {
    get label() {
      return tr('mcp_status_pending');
    },
  },
  failed: {
    get label() {
      return tr('mcp_status_failed');
    },
  },
  needs_auth: {
    get label() {
      return tr('mcp_status_needs_auth');
    },
  },
  disabled: {
    get label() {
      return tr('mcp_status_disabled');
    },
  },
  idle: {
    get label() {
      return tr('mcp_status_idle');
    },
  },
};

export const MCP_TRANSPORT_LABEL: Record<string, string> = {
  get stdio() {
    return tr('mcp_transport_stdio');
  },
  sse: 'SSE',
  'streamable-http': 'Streamable HTTP',
};

export function mcpTransport(s: Pick<McpServer, 'type' | 'url'>): string {
  return s.type || (s.url ? 'sse' : 'stdio');
}

export function mcpTarget(s: McpServer): string {
  if (mcpTransport(s) === 'stdio') {
    return [s.command, ...(s.args ?? [])].filter(Boolean).join(' ');
  }
  return (s.url ?? '').replace(/^https?:\/\//, '');
}
