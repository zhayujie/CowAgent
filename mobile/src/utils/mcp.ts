import {tr, trf} from '../i18n';
import type {McpServer} from '../protocol/resources';

export const MCP_JSON_PLACEHOLDER = JSON.stringify(
  {mcpServers: {fetch: {command: 'uvx', args: ['mcp-server-fetch']}}},
  null,
  2,
);

/** `KEY=value` per line; a line without `=`, or with nothing before it, is skipped. */
export function kvToObject(text: string): Record<string, string> {
  const out: Record<string, string> = {};
  for (const line of (text || '').split(/\r?\n/)) {
    const trimmed = line.trim();
    const idx = trimmed.indexOf('=');
    if (idx > 0) {
      out[trimmed.slice(0, idx).trim()] = trimmed.slice(idx + 1);
    }
  }
  return out;
}

export function objectToKv(obj?: Record<string, string>): string {
  return Object.entries(obj ?? {})
    .map(([key, value]) => `${key}=${value}`)
    .join('\n');
}

/**
 * Reads pasted JSON: the {"mcpServers": {...}} file format MCP directories publish,
 * a bare {name: config} map, a list, or one config that carries its own "name".
 */
export function parseMcpJson(text: string): McpServer[] {
  const raw = (text || '').trim();
  if (!raw) {
    throw new Error(tr('mcp_json_empty'));
  }
  let obj: unknown;
  try {
    obj = JSON.parse(raw);
  } catch (e) {
    throw new Error(trf('mcp_json_invalid_detail', {error: e instanceof Error ? e.message : ''}));
  }
  const fromMap = (map: Record<string, unknown>) =>
    Object.entries(map).map(([name, cfg]) => {
      if (!cfg || typeof cfg !== 'object' || Array.isArray(cfg)) {
        throw new Error(trf('mcp_json_not_server', {name}));
      }
      return {...(cfg as Record<string, unknown>), name};
    });

  let servers: Record<string, unknown>[];
  if (Array.isArray(obj)) {
    servers = obj as Record<string, unknown>[];
  } else if (obj && typeof obj === 'object') {
    const record = obj as Record<string, unknown>;
    if (record.mcpServers && typeof record.mcpServers === 'object') {
      servers = fromMap(record.mcpServers as Record<string, unknown>);
    } else if ('command' in record || 'url' in record || 'serverUrl' in record) {
      if (!record.name) {
        throw new Error(tr('mcp_json_need_name'));
      }
      servers = [record];
    } else {
      servers = fromMap(record);
    }
  } else {
    throw new Error(tr('mcp_json_invalid'));
  }
  if (!servers.length) {
    throw new Error(tr('mcp_json_no_servers'));
  }
  return servers.map(server => {
    const cfg: Record<string, unknown> = {...server};
    if (!cfg.url && cfg.serverUrl) {
      cfg.url = cfg.serverUrl;
    }
    delete cfg.serverUrl;
    delete cfg.status;
    if (!cfg.type) {
      cfg.type = cfg.url ? 'sse' : 'stdio';
    }
    return cfg as unknown as McpServer;
  });
}

/** A server as mcp.json stores it: no name, no runtime fields, no empty values. */
function configForJson(server: McpServer): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(server)) {
    if (key === 'name' || key === 'status' || (key === 'type' && value === 'stdio')) {
      continue;
    }
    if (value === '' || value === null || value === undefined || value === false) {
      continue;
    }
    if (Array.isArray(value) ? !value.length : typeof value === 'object' && !Object.keys(value as object).length) {
      continue;
    }
    out[key] = value;
  }
  return out;
}

export function mcpServersToJson(servers: McpServer[]): string {
  const map: Record<string, unknown> = {};
  for (const server of servers) {
    map[server.name || 'my-server'] = configForJson(server);
  }
  return JSON.stringify({mcpServers: map}, null, 2);
}
