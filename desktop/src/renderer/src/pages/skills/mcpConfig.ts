import { t } from '../../i18n'
import type { McpServerConfig } from '../../types'

export const MCP_JSON_PLACEHOLDER = JSON.stringify(
  { mcpServers: { fetch: { command: 'uvx', args: ['mcp-server-fetch'] } } },
  null,
  2
)

export const MCP_TRANSPORT_LABELS: Record<string, string> = {
  stdio: 'stdio',
  sse: 'SSE',
  'streamable-http': 'HTTP',
}

export function mcpTransport(server: McpServerConfig): string {
  return server.type || (server.url ? 'sse' : 'stdio')
}

export function kvToObject(text: string): Record<string, string> {
  const out: Record<string, string> = {}
  for (const line of (text || '').split(/\r?\n/)) {
    const trimmed = line.trim()
    if (!trimmed) continue
    const idx = trimmed.indexOf('=')
    if (idx <= 0) continue
    out[trimmed.slice(0, idx).trim()] = trimmed.slice(idx + 1)
  }
  return out
}

export function objectToKv(obj?: Record<string, string>): string {
  if (!obj) return ''
  return Object.entries(obj)
    .map(([key, value]) => `${key}=${value}`)
    .join('\n')
}

/** A server as it is written in mcp.json: no name, no runtime fields, no empty values. */
function configForJson(cfg: McpServerConfig): Record<string, unknown> {
  const out: Record<string, unknown> = {}
  for (const [key, value] of Object.entries(cfg)) {
    if (key === 'name' || key === 'status') continue
    if (key === 'type' && value === 'stdio') continue
    if (value === '' || value === null || value === undefined || value === false) continue
    if (Array.isArray(value) && !value.length) continue
    if (typeof value === 'object' && !Array.isArray(value) && !Object.keys(value as object).length) continue
    out[key] = value
  }
  return out
}

export function mcpServersToJson(servers: McpServerConfig[]): string {
  const map: Record<string, unknown> = {}
  for (const server of servers) map[server.name || 'my-server'] = configForJson(server)
  return JSON.stringify({ mcpServers: map }, null, 2)
}

/**
 * Read pasted JSON. Accepts the {"mcpServers": {...}} file format that MCP
 * directories publish, a bare {name: config} map, a list, or one config that
 * carries its own "name".
 */
export function parseMcpJson(text: string): McpServerConfig[] {
  const raw = (text || '').trim()
  if (!raw) throw new Error(t('mcp_json_empty'))
  let obj: unknown
  try {
    obj = JSON.parse(raw)
  } catch (err) {
    throw new Error(`${t('mcp_json_invalid')}: ${err instanceof Error ? err.message : ''}`)
  }
  const fromMap = (map: Record<string, unknown>): Record<string, unknown>[] =>
    Object.entries(map).map(([name, cfg]) => {
      if (!cfg || typeof cfg !== 'object' || Array.isArray(cfg)) {
        throw new Error(`${t('mcp_json_invalid')}: ${name}`)
      }
      return { ...(cfg as Record<string, unknown>), name }
    })

  let servers: Record<string, unknown>[]
  if (Array.isArray(obj)) {
    servers = obj as Record<string, unknown>[]
  } else if (obj && typeof obj === 'object') {
    const record = obj as Record<string, unknown>
    if (record.mcpServers && typeof record.mcpServers === 'object') {
      servers = fromMap(record.mcpServers as Record<string, unknown>)
    } else if ('command' in record || 'url' in record || 'serverUrl' in record) {
      if (!record.name) throw new Error(t('mcp_json_need_name'))
      servers = [record]
    } else {
      servers = fromMap(record)
    }
  } else {
    throw new Error(t('mcp_json_invalid'))
  }
  if (!servers.length) throw new Error(t('mcp_json_empty'))
  return servers.map((server) => {
    const cfg = { ...server }
    if (!cfg.url && cfg.serverUrl) cfg.url = cfg.serverUrl
    delete cfg.serverUrl
    delete cfg.status
    return cfg as unknown as McpServerConfig
  })
}
