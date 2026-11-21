import {getLang} from '../i18n';
import type {ServerInfo} from '../protocol/envelope';
import type {
  HistoryPage,
  SendMessageResult,
  SessionsPage,
} from '../protocol/events';
import type {
  AgentCoreFile,
  AgentCoreFileContent,
  AgentProfile,
  AgentsResponse,
  ArtifactsPage,
  CapabilityKey,
  CatalogModel,
  ChannelsResponse,
  ConfigUpdates,
  ContextUsage,
  DeviceInstance,
  DeviceList,
  ExternalApiState,
  FallbackLink,
  GlobalConfig,
  GuestShare,
  GuestShareConfig,
  GuestSharesOverview,
  IntegrationsState,
  KnowledgeAction,
  KnowledgeDoc,
  KnowledgeGraph,
  KnowledgeImportResult,
  KnowledgeTree,
  McpProbe,
  McpServer,
  MemoryCategory,
  MemoryContent,
  MemoryPage,
  MenuDoc,
  ModelsState,
  PairedDevice,
  PairingCode,
  QrPayload,
  ScheduledTask,
  SessionSettings,
  Skill,
  SkillContent,
  SkillFile,
  SkillMarketSource,
  SkillPreview,
  TaskAction,
  TaskInstance,
  TaskRecipient,
  TaskRun,
  TaskSchedule,
  ToolInfo,
  UpdateCheck,
  UpdateStatus,
  UploadedFile,
  VersionInfo,
  VoiceReplyMode,
  WorkspaceHit,
  WorkspaceText,
} from '../protocol/resources';
import {appendFile, type PickedFile} from '../media/types';
import {omit} from '../utils/object';
import {ApiError, http, normalizeBaseUrl} from './http';
import {deviceInfo} from './pairing';
import {openEventStream, type EventStreamHandle} from './sse';

interface AuthCheck {
  status: string;
  auth_required: boolean;
  authenticated?: boolean;
}

/**
 * Probe an address before using it. Prefers `/api/info`; servers that predate
 * it are recognised through the public `/api/health`, `/auth/check` and
 * `/api/version` endpoints, and get no WebSocket URL (SSE fallback).
 */
export async function probeServer(rawUrl: string): Promise<ServerInfo> {
  const previous = http.getBaseUrl();
  http.setBaseUrl(normalizeBaseUrl(rawUrl));
  try {
    try {
      return await http.request<ServerInfo>('/api/info', {anonymous: true});
    } catch (e) {
      if (!(e instanceof ApiError) || e.status !== 404) {
        throw e;
      }
    }
    const health = await http.request<{status?: string}>('/api/health', {
      anonymous: true,
    });
    if (health.status !== 'ok') {
      throw new ApiError('invalid_response', 'Not a CowAgent server');
    }
    const auth = await http.request<AuthCheck>('/auth/check', {
      anonymous: true,
    });
    const version = await http
      .request<{version?: string}>('/api/version', {anonymous: true})
      .catch(() => ({version: undefined}));
    return {
      name: 'CowAgent',
      version: version.version ?? 'unknown',
      ws_url: null,
      auth_required: auth.auth_required,
    };
  } finally {
    if (previous) {
      http.setBaseUrl(previous);
    }
  }
}

/** Whether the current token is still accepted. */
export async function checkAuth() {
  return http.request<AuthCheck>('/auth/check');
}

export async function login(password: string): Promise<string | null> {
  const res = await http.request<{status: string; token?: string}>(
    '/auth/login',
    {body: {password, device: deviceInfo()}, anonymous: true},
  );
  return res.token ?? null;
}

const query = (params: Record<string, string | number | undefined | null>) =>
  Object.entries(params)
    .filter(([, v]) => v !== undefined && v !== null && v !== '')
    .map(([k, v]) => `${k}=${encodeURIComponent(String(v))}`)
    .join('&');

export async function getSessions(page = 1, pageSize = 50) {
  return http.request<SessionsPage>(
    `/api/sessions?page=${page}&page_size=${pageSize}&scope=all`,
  );
}

export async function updateSession(
  sessionId: string,
  patch: {title?: string; pinned?: boolean},
  agentId?: string,
) {
  return http.request<{status: string}>(`/api/sessions/${encodeURIComponent(sessionId)}`, {
    method: 'PUT',
    body: {...patch, agent_id: agentId},
  });
}

export async function deleteSession(sessionId: string, agentId?: string) {
  return http.request<{status: string}>(
    `/api/sessions/${encodeURIComponent(sessionId)}?${query({agent_id: agentId})}`,
    {method: 'DELETE'},
  );
}

export async function getHistory(
  sessionId: string,
  agentId?: string,
  page = 1,
  pageSize = 30,
) {
  return http.request<HistoryPage>(
    `/api/history?${query({
      session_id: sessionId,
      agent_id: agentId,
      page,
      page_size: pageSize,
    })}`,
  );
}

export interface OutgoingAttachment {
  file_path: string;
  file_name: string;
  file_type: string;
}

export async function sendMessage(
  sessionId: string,
  message: string,
  agentId?: string,
  extra: {attachments?: OutgoingAttachment[]; isVoice?: boolean} = {},
) {
  return http.request<SendMessageResult>('/message', {
    body: {
      session_id: sessionId,
      message,
      stream: true,
      agent_id: agentId,
      attachments: extra.attachments?.length ? extra.attachments : undefined,
      is_voice: extra.isVoice || undefined,
    },
  });
}

/** The agent travels in the query string: a form field would break the multipart parser. */
export async function uploadAttachment(file: PickedFile, sessionId: string, agentId?: string) {
  const form = new FormData();
  appendFile(form, 'file', file);
  form.append('session_id', sessionId);
  return http.upload<UploadedFile>(`/upload?${query({agent_id: agentId})}`, form);
}

export async function transcribeVoice(file: PickedFile, agentId?: string) {
  const form = new FormData();
  appendFile(form, 'file', file);
  return http.upload<{text: string; audio_url?: string}>(
    `/api/voice/asr?${query({agent_id: agentId})}`,
    form,
    60_000,
  );
}

export async function optimizePrompt(input: string, context: {role: string; content: string}[]) {
  return http.request<{optimized: string}>('/api/prompt/optimize', {
    body: {input, context_messages: context},
    timeoutMs: 60_000,
  });
}

export async function getSessionSettings(sessionId: string, agentId?: string) {
  return http.request<SessionSettings>(
    `/api/sessions/${encodeURIComponent(sessionId)}/settings?${query({agent_id: agentId})}`,
  );
}

/** Pass null for a field to drop the pin and follow the global setting again. */
export async function updateSessionSettings(
  sessionId: string,
  patch: {
    model?: string | null;
    provider?: string | null;
    permission?: string | null;
    members?: string[] | null;
  },
  agentId?: string,
) {
  return http.request<SessionSettings>(`/api/sessions/${encodeURIComponent(sessionId)}/settings`, {
    body: {...patch, agent_id: agentId},
  });
}

const sessionPath = (sessionId: string, tail: string) =>
  `/api/sessions/${encodeURIComponent(sessionId)}/${tail}`;

export async function getContextUsage(sessionId: string, agentId?: string) {
  return http.request<ContextUsage>(`${sessionPath(sessionId, 'context_usage')}?${query({agent_id: agentId})}`);
}

export async function clearContext(sessionId: string, agentId?: string) {
  return http.request<{context_start_seq: number}>(sessionPath(sessionId, 'clear_context'), {
    body: {agent_id: agentId},
  });
}

export async function compactContext(sessionId: string, agentId?: string) {
  return http.request<{ok: boolean; compacted_turns: number; usage: ContextUsage | null}>(
    sessionPath(sessionId, 'compact_context'),
    {body: {agent_id: agentId}, timeoutMs: 120_000},
  );
}

export async function getAgents() {
  return http.request<AgentsResponse>('/api/agents');
}

export type AgentPatch = Partial<
  Pick<AgentProfile, 'name' | 'description' | 'enabled' | 'skills'> & {
    model: string;
    bot_type: string;
    make_default: boolean;
  }
>;

export async function updateAgent(agentId: string, patch: AgentPatch, revision?: string) {
  return http.request<{revision?: string}>('/api/agents', {
    body: {action: 'update', id: agentId, revision, ...patch},
  });
}

/** Symlink vs own knowledge directory; not a roster revision edit. */
export async function setAgentKnowledgeMode(agentId: string, mode: 'shared' | 'own') {
  return http.request<{status?: string}>('/api/agents', {
    body: {action: 'set_knowledge_mode', id: agentId, mode},
  });
}

/** A blank `cloneFrom` starts from scratch; otherwise persona, skills and knowledge are copied. */
export async function createAgent(fields: {id: string; name: string; description: string; cloneFrom?: string}) {
  return http.request<{revision?: string}>('/api/agents', {
    body: {
      action: 'create',
      id: fields.id,
      name: fields.name,
      description: fields.description,
      clone_from: fields.cloneFrom || null,
    },
  });
}

export async function uploadAgentAvatar(agentId: string, file: PickedFile) {
  const form = new FormData();
  appendFile(form, 'avatar', file);
  return http.upload<{revision?: string}>(`/api/agents/${encodeURIComponent(agentId)}/avatar`, form);
}

const agentFilePath = (agentId: string, name: AgentCoreFile) =>
  `/api/agents/${encodeURIComponent(agentId)}/files/${encodeURIComponent(name)}`;

export async function getAgentFile(agentId: string, name: AgentCoreFile) {
  return http.request<AgentCoreFileContent & {exists?: boolean}>(agentFilePath(agentId, name));
}

export async function saveAgentFile(agentId: string, name: AgentCoreFile, content: string, revision: string) {
  return http.request<AgentCoreFileContent>(agentFilePath(agentId, name), {
    method: 'PUT',
    body: {content, revision},
  });
}

/** Uploaded avatars are served behind auth, so the token rides in the query. */
export function agentAvatarUrl(agent: {id: string; avatar_rev?: string}): string {
  return http.url(
    `/api/agents/${encodeURIComponent(agent.id)}/avatar?${query({v: agent.avatar_rev, token: http.confirmedToken()})}`,
  );
}

export async function getVersion() {
  return http.request<VersionInfo>('/api/version');
}

export async function checkForUpdate() {
  return http.request<UpdateCheck>('/api/update/check', {body: {}, timeoutMs: 30_000});
}

export async function startUpdate() {
  return http.request<{update: UpdateStatus}>('/api/update/start', {body: {}});
}

export async function getUpdateStatus() {
  return http.request<UpdateStatus>('/api/update/status');
}

export async function getConfig() {
  return http.request<GlobalConfig>('/config');
}

/** Setting `web_password` voids every token; newer servers hand back `auth_token` signed with the new one. */
export async function updateConfig(updates: ConfigUpdates) {
  return http.request<{applied: ConfigUpdates; warning?: string | null; auth_token?: string}>('/config', {
    body: {updates},
  });
}

export async function getModels() {
  return http.request<ModelsState>('/api/models');
}

export async function setChatModel(providerId: string, model: string) {
  return http.request<{applied: Record<string, unknown>}>('/api/models', {
    body: {action: 'set_capability', capability: 'chat', provider_id: providerId, model},
  });
}

export async function setChatFallback(enabled: boolean, chain: FallbackLink[]) {
  return http.request<{applied: {enabled: boolean; chain: FallbackLink[]}}>('/api/models', {
    body: {action: 'set_capability', capability: 'chat_fallback', enabled, chain},
  });
}

/** An empty key leaves the stored one untouched; the server never returns it unmasked. */
export async function setProviderCredential(providerId: string, apiKey: string, apiBase?: string) {
  return http.request<{status: string}>('/api/models', {
    body: {
      action: 'set_provider',
      provider_id: providerId,
      api_key: apiKey,
      ...(apiBase === undefined ? {} : {api_base: apiBase}),
    },
  });
}

/** Forgets a built-in vendor's key and base. */
export async function clearProviderCredential(providerId: string) {
  return http.request<{status: string}>('/api/models', {body: {action: 'delete_provider', provider_id: providerId}});
}

export interface CapabilityChoice {
  capability: CapabilityKey;
  /** Empty means automatic (vision, image, asr) or switched off (embedding). */
  provider_id: string;
  model?: string;
  voice?: string;
}

export async function setCapability(choice: CapabilityChoice) {
  return http.request<{applied: Record<string, unknown>}>('/api/models', {
    body: {action: 'set_capability', ...choice},
  });
}

export async function setVoiceReplyMode(mode: VoiceReplyMode) {
  return http.request<{status: string}>('/api/models', {body: {action: 'set_voice_reply_mode', mode}});
}

export async function setSearchStrategy(strategy: 'auto' | 'fixed', provider?: string) {
  return http.request<{status: string}>('/api/models', {
    body: {action: 'set_capability', capability: 'search', strategy, ...(provider ? {provider} : {})},
  });
}

/** `anonymous` keyless mode exists for AnySearch and Keenable; SearXNG takes a URL instead of a key. */
export async function setSearchCredential(provider: string, cred: {api_key?: string; url?: string; anonymous?: boolean}) {
  return http.request<{status: string}>('/api/models', {
    body: {action: 'set_search_credential', provider, ...cred},
  });
}

/** Creates when `id` is absent; an omitted `api_key` keeps the stored one. */
export async function setCustomProvider(fields: {id?: string; name: string; api_base: string; api_key?: string; model?: string}) {
  return http.request<{status: string; id?: string}>('/api/models', {
    body: {action: 'set_custom_provider', ...fields},
  });
}

export async function deleteCustomProvider(id: string) {
  return http.request<{status: string}>('/api/models', {body: {action: 'delete_custom_provider', id}});
}

/** A custom vendor has no presets, so its catalog is the whole model list. */
export async function saveCustomCatalog(providerId: string, models: CatalogModel[]) {
  return http.request<{status: string}>('/api/models', {
    body: {action: 'save_catalog', provider_id: providerId, models, hidden: []},
  });
}

export async function getIntegrations() {
  return http.request<IntegrationsState>('/api/integrations');
}

/** Empty restores automatic detection. */
export async function savePublicUrl(publicUrl: string) {
  return http.request<{status: string; public_url: string}>('/api/integrations', {
    method: 'PUT',
    body: {public_url: publicUrl},
  });
}

const SHARES = '/api/guest-shares';
const shareSlug = (slug: string) => `${SHARES}/${encodeURIComponent(slug)}`;

export type GuestShareAction = 'confirm' | 'reset-link' | 'disable' | 'enable';

export async function getGuestShares() {
  return http.request<GuestSharesOverview>(SHARES);
}

export async function setGuestSharesEnabled(enabled: boolean) {
  return http.request<{feature: GuestSharesOverview['feature']}>(SHARES, {method: 'PUT', body: {enabled}});
}

export async function getGuestShare(slug: string) {
  return http.request<{share: GuestShare}>(shareSlug(slug));
}

export async function createGuestShare(config: GuestShareConfig, guestMd: string) {
  return http.request<{share: GuestShare}>(SHARES, {body: {config, guest_md: guestMd}});
}

export async function updateGuestShare(slug: string, config: GuestShareConfig, guestMd?: string) {
  return http.request<{share: GuestShare}>(shareSlug(slug), {
    method: 'PUT',
    body: {config, ...(guestMd === undefined ? {} : {guest_md: guestMd})},
  });
}

export async function deleteGuestShare(slug: string) {
  return http.request<{status: string}>(shareSlug(slug), {method: 'DELETE'});
}

export async function guestShareAction(slug: string, action: GuestShareAction) {
  return http.request<{share: GuestShare}>(`${shareSlug(slug)}/${action}`, {method: 'POST', body: {}});
}

export async function setGuestSharePassword(slug: string, password: string) {
  return http.request<{share: GuestShare}>(`${shareSlug(slug)}/password`, {body: {password}});
}

export async function getExternalApi() {
  return http.request<ExternalApiState>('/api/external_api');
}

export async function setExternalApi(action: 'enable' | 'disable' | 'regenerate') {
  return http.request<ExternalApiState>('/api/external_api', {body: {action}});
}

/** mcp.json is shared unless an Agent has its own; `agentId` undefined reads the default Agent's. */
export async function getMcpServers(agentId?: string) {
  return http.request<{servers: McpServer[]; path?: string}>(`/api/mcp/servers?${query({agent_id: agentId})}`);
}

/** The whole list is written back; fields the editor never saw are kept by the server. */
export async function saveMcpServers(servers: McpServer[], agentId?: string) {
  return http.request<{servers: McpServer[]}>('/api/mcp/servers', {
    method: 'PUT',
    body: {servers: servers.map(s => omit(s, ['status'])), agent_id: agentId},
  });
}

/** A failed probe comes back as {status: "error", ok: false}, which is a result, not a fault. */
export async function testMcpServer(server: McpServer): Promise<McpProbe> {
  // A stopped server is still worth probing: that is how one checks it before turning it on.
  const cfg = {...omit(server, ['status']), disabled: false};
  try {
    return await http.request<McpProbe>('/api/mcp/servers/test', {body: {server: cfg}, timeoutMs: 45_000});
  } catch (e) {
    if (e instanceof ApiError && e.kind === 'server') {
      // The probe's own failures are fixed English phrases; screens word those themselves.
      if (e.message === 'needs authorization') {
        return {ok: false, needs_auth: true, tools: []};
      }
      return {ok: false, error: e.message === 'initialization failed' ? undefined : e.message, tools: []};
    }
    throw e;
  }
}

export type LogEvent =
  | {type: 'init'; content: string}
  | {type: 'line'; content: string}
  | {type: 'error'; message: string};

/** Replays the tail of run.log, then follows it; the server closes after ten minutes. */
export function openLogStream(onEvent: (event: LogEvent) => void, onClose: (error?: Error) => void): EventStreamHandle {
  return openEventStream<LogEvent>({
    url: http.url('/api/logs'),
    headers: http.authHeaders(),
    onEvent,
    onClose,
  });
}

export function logDownloadUrl(): string {
  return http.url(`/api/logs/download?${query({token: http.confirmedToken()})}`);
}

export async function getTaskRuns(opts: {taskId?: string; limit?: number; offset?: number} = {}) {
  return http.request<{runs: TaskRun[]}>(
    `/api/scheduler/runs?${query({task_id: opts.taskId, limit: opts.limit ?? 50, offset: opts.offset})}`,
  );
}

export async function getTaskRun(runId: string) {
  return http.request<{run: TaskRun}>(`/api/scheduler/runs/detail?${query({run_id: runId})}`);
}

export async function deleteTaskRun(runId: string) {
  return http.request<{status: string}>('/api/scheduler/runs/delete', {body: {run_id: runId}});
}

export async function runTaskNow(taskId: string, agentId?: string) {
  return http.request<{message?: string}>('/api/scheduler/run', {body: {task_id: taskId, agent_id: agentId}});
}

export async function getMenu() {
  return http.request<{menu: MenuDoc | null}>('/api/menu');
}

export async function saveMenu(menu: MenuDoc | null) {
  return http.request<{menu: MenuDoc | null}>('/api/menu', {body: {menu}});
}

export async function getArtifacts(opts: {
  kind?: string;
  q?: string;
  path?: string;
  offset?: number;
  limit?: number;
}) {
  return http.request<ArtifactsPage>(
    `/api/artifacts?${query({scope: 'all', limit: 60, ...opts})}`,
  );
}

export async function pinArtifact(id: number, agentId: string, pinned: boolean) {
  return http.request<{status: string}>('/api/artifacts/pin', {
    body: {id, agent_id: agentId, pinned},
  });
}

export async function getSkills(agentId?: string) {
  return http.request<{skills: Skill[]}>(`/api/skills?${query({agent_id: agentId})}`);
}

export async function getTools() {
  return http.request<{tools: ToolInfo[]}>('/api/tools');
}

export async function setSkillEnabled(name: string, enabled: boolean, agentId?: string) {
  return http.request<{status: string}>('/api/skills', {
    body: {action: enabled ? 'open' : 'close', name, agent_id: agentId},
  });
}

export async function deleteSkill(name: string, agentId?: string) {
  return http.request<{status: string}>('/api/skills', {body: {action: 'delete', name, agent_id: agentId}});
}

export async function getSkillFiles(name: string, agentId?: string) {
  return http.request<{files: SkillFile[]; truncated?: boolean}>(
    `/api/skills/files?${query({name, agent_id: agentId})}`,
  );
}

/** `path` is a file inside the skill's directory; omitted, its SKILL.md. */
export async function readSkillFile(name: string, path?: string, agentId?: string) {
  return http.request<SkillContent>(`/api/skills/content?${query({name, path, agent_id: agentId})}`);
}

/** A stale `expectedMtime` fails with an ApiError whose body carries `code: "conflict"`. */
export async function writeSkillFile(
  name: string,
  path: string | undefined,
  content: string,
  expectedMtime: number | null,
  agentId?: string,
) {
  return http.request<{path: string; size: number; mtime: number}>('/api/skills/content', {
    body: {name, path: path ?? '', content, expected_mtime: expectedMtime, agent_id: agentId},
  });
}

/** `name` is a title; the server reduces it to the hyphen-case name the directory uses. */
export async function createSkill(fields: {name: string; description: string; body: string}, agentId?: string) {
  const form = new FormData();
  form.append('name', fields.name);
  form.append('description', fields.description);
  form.append('body', fields.body);
  // In the query, not the form: web.py merges the two, and a field in both arrives as a list.
  return http.upload<{name: string; files: string[]}>(`/api/skills/create?${query({agent_id: agentId})}`, form);
}

/** Fetches a skill into a staging area so it can be reviewed before it is installed. */
export async function previewSkill(source: SkillMarketSource, value: string, agentId?: string) {
  return http.request<SkillPreview>('/api/skills', {
    body: {action: 'preview', source, value, agent_id: agentId},
    timeoutMs: 120_000,
  });
}

/** Stages an uploaded archive or SKILL.md for preview. */
export async function uploadSkill(files: PickedFile[], agentId?: string) {
  const form = new FormData();
  files.forEach(f => {
    appendFile(form, 'files', f);
    form.append('paths', f.name);
  });
  return http.upload<SkillPreview>(`/api/skills/upload?${query({agent_id: agentId})}`, form);
}

export async function confirmSkillInstall(token: string, names: string[], agentId?: string) {
  return http.request<{installed: string[]}>('/api/skills', {
    body: {action: 'confirm', token, names, agent_id: agentId},
    timeoutMs: 120_000,
  });
}

export async function discardSkillPreview(token: string) {
  return http.request<{status: string}>('/api/skills', {body: {action: 'discard', token}}).catch(() => undefined);
}

export async function getScheduledTasks() {
  return http.request<{tasks: ScheduledTask[]}>('/api/scheduler');
}

export async function toggleScheduledTask(taskId: string, enabled: boolean) {
  return http.request<{status: string}>('/api/scheduler/toggle', {
    body: {task_id: taskId, enabled},
  });
}

export interface TaskDraft {
  name: string;
  enabled: boolean;
  schedule: TaskSchedule;
  action: TaskAction;
}

/** The recipient must already be in the trusted directory; the server fills in who they are. */
export async function createScheduledTask(draft: TaskDraft) {
  return http.request<{task?: ScheduledTask}>('/api/scheduler/create', {body: draft});
}

export async function updateScheduledTask(task: ScheduledTask, draft: TaskDraft) {
  return http.request<{task?: ScheduledTask}>('/api/scheduler/update', {
    body: {task_id: task.id, agent_id: task.agent_id || '', ...draft},
  });
}

export async function deleteScheduledTask(task: ScheduledTask) {
  return http.request<{status: string}>('/api/scheduler/delete', {
    body: {task_id: task.id, agent_id: task.agent_id || ''},
  });
}

export async function getTaskInstances() {
  return http.request<{instances: TaskInstance[]}>('/api/scheduler/instances');
}

export async function getTaskRecipients() {
  return http.request<{recipients: TaskRecipient[]}>('/api/scheduler/recipients');
}

export async function getMemoryFiles(opts: {
  category?: MemoryCategory;
  agentId?: string;
  page?: number;
  pageSize?: number;
} = {}) {
  return http.request<MemoryPage>(
    `/api/memory?${query({
      page: opts.page ?? 1,
      page_size: opts.pageSize ?? 50,
      category: opts.category ?? 'memory',
      agent_id: opts.agentId,
    })}`,
  );
}

export async function getMemoryContent(filename: string, category: MemoryCategory, agentId?: string) {
  return http.request<MemoryContent>(`/api/memory/content?${query({filename, category, agent_id: agentId})}`);
}

/** No session: memory lives in the Agent's state root, not in whatever project a session has open. */
export async function readWorkspaceText(path: string, agentId?: string) {
  return http.request<WorkspaceText>(`/api/workspace/read?${query({path, agent_id: agentId})}`);
}

/** Files and folders whose name matches `q`, rooted where the session works. */
export async function searchWorkspace(q: string, sessionId?: string, agentId?: string, limit = 12) {
  return http.request<{results: WorkspaceHit[]}>(
    `/api/workspace/search?${query({q, limit, session: sessionId, agent_id: agentId})}`,
  );
}

/** A stale `expectedMtime` fails with an ApiError whose body carries `code: "conflict"`. */
export async function writeWorkspaceText(path: string, content: string, expectedMtime: number | null, agentId?: string) {
  return http.request<{path: string; size: number; mtime: number}>('/api/workspace/write', {
    body: {path, content, expected_mtime: expectedMtime, agent_id: agentId},
  });
}

export async function getKnowledgeTree(agentId?: string) {
  return http.request<KnowledgeTree>(`/api/knowledge/list?${query({agent_id: agentId})}`);
}

export async function getKnowledgeDoc(path: string, agentId?: string) {
  return http.request<KnowledgeDoc>(`/api/knowledge/read?${query({path, agent_id: agentId})}`);
}

export async function getKnowledgeGraph(agentId?: string) {
  return http.request<KnowledgeGraph>(`/api/knowledge/graph?${query({agent_id: agentId})}`);
}

/** A stale `update_document` fails with an ApiError whose body carries `payload.conflict`. */
export async function knowledgeAction<P = Record<string, unknown>>(req: KnowledgeAction, agentId?: string) {
  const res = await http.request<{payload: P}>('/api/knowledge/action', {
    body: {...req, agent_id: agentId},
    timeoutMs: 60_000,
  });
  return res.payload;
}

/** Same-named files are kept side by side rather than skipped or overwritten. */
export async function importKnowledge(files: PickedFile[], targetCategory: string, agentId?: string) {
  const form = new FormData();
  form.append('target_category', targetCategory);
  form.append('conflict_strategy', 'rename');
  files.forEach(f => appendFile(form, 'files', f));
  const res = await http.upload<{payload: KnowledgeImportResult}>(
    `/api/knowledge/import?${query({agent_id: agentId})}`,
    form,
  );
  return res.payload;
}

export async function getChannels() {
  return http.request<ChannelsResponse>(`/api/channels?lang=${getLang()}`);
}

export type ChannelAction = 'save' | 'connect' | 'disconnect';

/**
 * `instanceId` matters only in multi-Agent mode: an empty string creates a new
 * bot, a real id edits that one, and leaving it out takes the per-type path.
 */
export async function channelAction(
  action: ChannelAction,
  channel: string,
  config?: Record<string, unknown>,
  instanceId?: string,
) {
  const body: Record<string, unknown> = {action, channel, config};
  if (instanceId !== undefined) {
    body.instance_id = instanceId;
  }
  return http.request<{status: string; instance_id?: string; downloading?: boolean}>('/api/channels', {body});
}

export async function renameChannelInstance(channel: string, instanceId: string, name: string) {
  return http.request<{instance_id?: string; name?: string}>('/api/channels', {
    body: {action: 'rename', channel, instance_id: instanceId, name},
  });
}

/** Owner first, then teammates; an empty owner follows the default Agent. Applies without a restart. */
export async function bindChannelInstance(channelType: string, instanceId: string, ownerId: string, members: string[]) {
  return http.request('/api/agents', {
    body: {action: 'bind_channel_instance', channel_type: channelType, instance_id: instanceId, agent_id: ownerId, members},
  });
}

export async function getWeixinQr(instanceId?: string) {
  return http.request<QrPayload>(`/api/weixin/qrlogin?${query({instance_id: instanceId})}`, {timeoutMs: 30_000});
}

/** The server long-polls WeChat for about ten seconds. */
export async function pollWeixinQr() {
  return http.request<QrPayload & {qr_status?: string}>('/api/weixin/qrlogin', {
    body: {action: 'poll'},
    timeoutMs: 30_000,
  });
}

export async function getFeishuRegister() {
  return http.request<QrPayload & {register_status?: string}>('/api/feishu/register', {timeoutMs: 30_000});
}

export async function pollFeishuRegister() {
  return http.request<QrPayload & {register_status?: string; app_id?: string; app_secret?: string}>(
    '/api/feishu/register',
    {body: {action: 'poll'}, timeoutMs: 30_000},
  );
}

export async function listDevices() {
  return http.request<DeviceList>('/api/devices');
}

/** Renames the server itself; an empty name goes back to the computer's. */
export async function renameInstance(name: string) {
  return http.request<{instance: DeviceInstance}>('/api/device', {method: 'PATCH', body: {name}});
}

export async function renameDevice(id: string, name: string) {
  return http.request<{device: PairedDevice}>(`/api/devices/${encodeURIComponent(id)}`, {
    method: 'PATCH',
    body: {name},
  });
}

export async function removeDevice(id: string) {
  return http.request(`/api/devices/${encodeURIComponent(id)}`, {method: 'DELETE'});
}

/** `baseUrl` is the address this app reaches the server at, offered to the other device among the LAN ones. */
export async function createPairing(baseUrl: string) {
  return http.request<PairingCode>('/api/pairing', {body: {base_url: baseUrl}});
}

export async function getPairing(id: string) {
  return http.request<{state: 'pending' | 'paired' | 'expired'; device?: PairedDevice}>(
    `/api/pairing/${encodeURIComponent(id)}`,
  );
}

/** Absolute URL for a server-relative path such as an artifact preview. */
export function serverUrl(path: string): string {
  return /^https?:\/\//i.test(path) ? path : http.url(path);
}

/**
 * URL for a file on the server's disk. Image views cannot send headers on every
 * platform, so the token rides in the query string, which the server accepts.
 */
export function serverFileUrl(filePath: string): string {
  const token = http.confirmedToken();
  return http.url(`/api/file?${query({path: filePath, token})}`);
}

/** A server-relative link that sits behind auth, with the token added for the same reason. */
export function authedUrl(path: string): string {
  if (/^https?:\/\//i.test(path)) {
    return path;
  }
  const token = http.confirmedToken();
  if (!token) {
    return http.url(path);
  }
  return http.url(`${path}${path.includes('?') ? '&' : '?'}${query({token})}`);
}

export interface WorkspaceEntry {
  name: string;
  path?: string;
  abs_path?: string;
  is_dir?: boolean;
  kind?: string;
  previewable?: boolean;
  size?: number;
  raw_url?: string;
  preview_url?: string;
}

/** Preview and download links for a workspace-relative or absolute path. */
export async function resolveWorkspacePath(path: string, sessionId?: string, agentId?: string) {
  return http.request<{status: string; file?: WorkspaceEntry; message?: string}>(
    `/api/workspace/resolve?${query({path, session: sessionId, agent: agentId})}`,
  );
}

export async function cancelRequest(requestId: string, sessionId: string) {
  return http.request<{status: string}>('/cancel', {
    body: {request_id: requestId, session_id: sessionId},
  });
}

export function newSessionId(): string {
  return `session_${Date.now().toString(36)}${Math.random()
    .toString(36)
    .slice(2, 6)}`;
}
