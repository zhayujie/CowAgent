import {create} from 'zustand';
import {getMcpServers, saveMcpServers} from '../api/cowApi';
import type {McpServer} from '../protocol/resources';
import {resetOnSignOut} from './reset';

interface McpState {
  servers: McpServer[] | null;
  /** Whose mcp.json the list is; undefined for the default Agent. Saves go back to the same one. */
  agentId?: string;
  /** Switching Agents clears the list first, so one Agent's servers never show under another. */
  load: (agentId?: string) => Promise<void>;
  /** Writes the whole list, which is how mcp.json is stored. */
  save: (servers: McpServer[]) => Promise<void>;
  upsert: (server: McpServer, previousName?: string) => Promise<void>;
  /** Adds several at once, as a pasted mcp.json does; same-named ones are replaced. */
  merge: (servers: McpServer[]) => Promise<void>;
  remove: (name: string) => Promise<void>;
}

export const useMcpStore = create<McpState>((set, get) => ({
  servers: null,
  agentId: undefined,

  load: async agentId => {
    if (agentId !== get().agentId) {
      set({servers: null, agentId});
    }
    const res = await getMcpServers(agentId);
    if (get().agentId === agentId) {
      set({servers: res.servers});
    }
  },

  save: async servers => {
    const agentId = get().agentId;
    const res = await saveMcpServers(servers, agentId);
    if (get().agentId === agentId) {
      set({servers: res.servers});
    }
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
  ready: {label: '在线', on: true},
  pending: {label: '连接中'},
  failed: {label: '连接失败'},
  needs_auth: {label: '需要授权'},
  disabled: {label: '已停用'},
  idle: {label: '未启动'},
};

export const MCP_TRANSPORT_LABEL: Record<string, string> = {
  stdio: '本地命令',
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
