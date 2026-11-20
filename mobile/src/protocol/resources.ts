/** Read models of the console endpoints the drawer pages show. */
import type {Artifact} from './events';

export interface AgentProfile {
  id: string;
  name: string;
  avatar?: string;
  avatar_rev?: string;
  workspace?: string;
  enabled?: boolean;
  description?: string;
  /** Unset means the Agent follows the global model. */
  model?: string | null;
  bot_type?: string | null;
  knowledge_mode?: 'shared' | 'own' | (string & {});
  skills?: string[] | null;
}

export interface AgentsResponse {
  default_agent_id: string;
  agents: AgentProfile[];
  /** Optimistic-lock token every roster edit must echo back. */
  revision?: string;
}

export const AGENT_CORE_FILES = ['AGENT.md', 'USER.md', 'RULE.md', 'MEMORY.md', 'BOOTSTRAP.md'] as const;
export type AgentCoreFile = (typeof AGENT_CORE_FILES)[number];

export interface AgentCoreFileContent {
  content: string;
  revision: string;
}

export interface ArtifactsPage {
  items: Artifact[];
  has_more: boolean;
}

export interface Skill {
  name: string;
  display_name?: string;
  description?: string;
  /** Shown in place of `description`, which stays what the Agent reads. */
  display_description?: string;
  source?: string;
  category?: string;
  enabled: boolean;
  icon?: string;
  version?: string;
  /** Epoch seconds the skill first showed up in the library. */
  installed_at?: number;
  /** Replaced from the installation on every start, so it reads as built-in and cannot be edited. */
  ships_with_install?: boolean;
  deletable?: boolean;
}

export interface ToolInfo {
  name: string;
  description?: string;
}

/** One entry of a skill's directory, listed depth first in the order a tree draws them. */
export interface SkillFile {
  /** Relative to the skill's own directory. */
  path: string;
  name: string;
  depth: number;
  is_dir: boolean;
  kind: string;
  /** False for a bundled asset that would only print as mojibake. */
  text: boolean;
  size: number;
  mtime: number;
}

export interface SkillContent extends WorkspaceText {
  name: string;
  filename: string;
  ships_with_install: boolean;
}

/** A skill found in a fetched or uploaded package, shown before it is installed. */
export interface SkillPreviewItem {
  name: string;
  display_name?: string;
  description?: string;
  source?: string;
  file_count?: number;
  size?: number;
  /** A skill of this name is installed already and would be replaced. */
  exists?: boolean;
}

export interface SkillPreview {
  token: string;
  skills: SkillPreviewItem[];
}

export type SkillMarketSource = 'hub' | 'github' | 'clawhub';

export type ScheduleType = 'cron' | 'interval' | 'once';
export type TaskActionType = 'send_message' | 'agent_task';

export interface TaskSchedule {
  type?: ScheduleType | (string & {});
  expression?: string;
  seconds?: number;
  /** ISO instant when `timezone` is set, else the server's naive local wall clock. */
  run_at?: string;
  timezone?: string;
}

export interface TaskAction {
  type?: TaskActionType | (string & {});
  content?: string;
  task_description?: string;
  channel_type?: string;
  instance_id?: string;
  receiver?: string;
  receiver_name?: string;
  is_group?: boolean;
  notify_session_id?: string;
}

export interface ScheduledTask {
  id: string;
  name?: string;
  enabled: boolean;
  agent_id?: string;
  next_run_at?: string | number | null;
  schedule?: TaskSchedule;
  action?: TaskAction;
}

/** `GET /api/scheduler/instances`: a channel login a task can deliver through. */
export interface TaskInstance {
  instance_id: string;
  channel_type: string;
  name: string;
  channel_label?: string;
  agent_id?: string;
  recipient_count?: number;
}

/** `GET /api/scheduler/recipients`: someone who already messaged the Agent on a channel. */
export interface TaskRecipient {
  channel_type: string;
  instance_id?: string;
  receiver: string;
  name?: string;
  is_group?: boolean;
  session_id?: string;
  instance_name?: string;
}

/** `memory` is MEMORY.md plus the daily notes; `evolution` merges self-evolution logs and dream diaries. */
export type MemoryCategory = 'memory' | 'evolution' | 'dream';

export interface MemoryFile {
  filename: string;
  type: 'global' | 'daily' | 'evolution' | 'dream' | (string & {});
  size: number;
  updated_at: string;
}

/** `GET /api/memory/content`; `rel_path` is how the workspace editor addresses the file. */
export interface MemoryContent {
  filename: string;
  rel_path?: string;
  content: string;
}

/** `GET /api/workspace/read`. */
export interface WorkspaceText {
  path: string;
  content: string;
  mtime: number;
  editable: boolean;
  truncated?: boolean;
  lossy?: boolean;
  size?: number;
}

export interface MemoryPage {
  list: MemoryFile[];
  total: number;
  page: number;
  page_size: number;
}

export interface KnowledgeFile {
  name: string;
  title?: string;
  size?: number;
}

export interface KnowledgeDir {
  dir: string;
  files: KnowledgeFile[];
  children?: KnowledgeDir[];
}

export interface KnowledgeTree {
  /** Missing while the knowledge directory doesn't exist yet. */
  root_files?: KnowledgeFile[];
  tree: KnowledgeDir[];
  /** Root files (index.md, log.md) are not counted. */
  stats?: {pages: number; size: number};
  enabled?: boolean;
}

/** `GET /api/knowledge/read`. index.md and log.md come back with `editable: false`. */
export interface KnowledgeDoc {
  path: string;
  content: string;
  mtime: number;
  editable: boolean;
  /** Absolute directory of the page, for images written relative to it. */
  dir?: string;
}

export interface KnowledgeGraph {
  nodes: {id: string; label: string; category: string}[];
  links: {source: string; target: string}[];
}

export type KnowledgeAction =
  | {action: 'create_category'; payload: {path: string}}
  | {action: 'rename_category'; payload: {path: string; new_path: string}}
  | {action: 'delete_category'; payload: {path: string; confirm: boolean}}
  | {action: 'create_document'; payload: {path: string; content: string; overwrite?: boolean}}
  | {action: 'update_document'; payload: {path: string; content: string; expected_mtime: number | null}}
  | {action: 'delete_documents'; payload: {paths: string[]}}
  | {action: 'move_documents'; payload: {paths: string[]; target_category: string}};

export interface KnowledgeImportResult {
  imported: number;
  skipped: number;
  failed: number;
  results: {path?: string; filename?: string; status: string; reason?: string}[];
}

export interface ChannelField {
  key: string;
  label: {zh?: string; en?: string} | string;
  type: 'text' | 'secret' | 'number' | 'bool';
  /** Secrets come back masked, e.g. `sk-1****abcd`. */
  value?: string | number | boolean | null;
  default?: string | number | boolean;
}

/** WeChat only: where the running channel's scan login stands. */
export type ChannelLoginStatus = 'idle' | 'waiting_scan' | 'scanned' | 'logged_in' | 'unknown' | string;

export interface ChannelInfo {
  /** The channel type, e.g. `feishu`. */
  name: string;
  label?: {zh?: string; en?: string} | string;
  active: boolean;
  fields?: ChannelField[];
  login_status?: ChannelLoginStatus;
  /** Multi-Agent instance cards only. */
  instance_id?: string;
  channel_type?: string;
  instance_name?: string;
  /** Owner Agent; empty follows the default Agent. */
  agent_id?: string;
  /** Teammates the owner may delegate to, in order. */
  members?: string[];
}

export interface ChannelsResponse {
  channels: ChannelInfo[];
  multi_agent?: boolean;
  /** Types that can run several bots at once in multi-Agent mode. */
  multi_instance_types?: string[];
  /** Multi-Agent mode: one card per running bot of a multi-instance type. */
  instances?: ChannelInfo[];
}

export interface QrPayload {
  status: string;
  qrcode_url?: string;
  /** A data URI, ready for an Image. */
  qr_image?: string;
  /** `channel`: the running WeChat channel owns the QR and logs itself in. */
  source?: string;
  message?: string;
}

export type PermissionMode = 'read-only' | 'workspace-write' | 'full-access';

/** Where a session's effective value comes from: its own pin, its Agent, or global config. */
export type SettingSource = 'session' | 'agent' | 'global';

export interface ModelProvider {
  id: string;
  label: string | {zh?: string; en?: string};
  models: string[];
}

export interface SessionSettings {
  model: {
    model: string;
    provider: string;
    source: SettingSource;
    global?: {model: string; provider: string};
    agent?: {model: string; provider: string} | null;
    providers: ModelProvider[];
  };
  permission: {
    mode: PermissionMode;
    source: SettingSource;
    global: PermissionMode;
    modes: PermissionMode[];
  };
  team?: SessionTeam;
}

/** What `/upload` answers for a single file. */
export interface UploadedFile {
  file_path: string;
  file_name: string;
  file_type: 'image' | 'video' | 'file' | (string & {});
  preview_url?: string;
}

export interface AgentBadge {
  id: string;
  name: string;
  avatar?: string;
  avatar_rev?: string;
  available?: boolean;
}

/** The owner answers by default and can hand work to the members. */
export interface SessionTeam {
  owner: AgentBadge;
  members: AgentBadge[];
  candidates: AgentBadge[];
}

export interface ContextUsage {
  available: boolean;
  estimated?: boolean;
  restored?: boolean;
  model?: string | null;
  window?: number;
  limit?: number;
  used?: number;
  messages?: number;
  breakdown?: {system: number; tools: number; history: number; free: number};
}

export interface ReasoningMeta {
  supported: boolean;
  param?: string;
  default?: string;
  options?: {value: string; label: string}[];
}

/** `GET /config`: the console's basic settings tab. */
export interface GlobalConfig {
  /** The server as a device: its id and the name every client shows for it. */
  device?: {id: string; name: string};
  model: string;
  bot_type: string;
  use_linkai: boolean;
  agent_max_context_tokens: number;
  agent_max_context_turns: number;
  agent_max_steps: number;
  enable_thinking: boolean;
  reasoning_effort: string;
  /** Keyed `${provider}:${model.toLowerCase()}`, as the console writes it. */
  reasoning_effort_by_model?: Record<string, string>;
  self_evolution_enabled: boolean;
  subagent_enabled: boolean;
  agent_permission_mode: PermissionMode;
  permission_modes: PermissionMode[];
  web_password_masked?: string;
  providers: Record<
    string,
    {
      label: string | {zh?: string; en?: string};
      models: string[];
      reasoning?: ReasoningMeta;
      reasoning_by_model?: Record<string, ReasoningMeta>;
    }
  >;
}

export type ConfigUpdates = Partial<{
  agent_max_context_tokens: number;
  agent_max_context_turns: number;
  agent_max_steps: number;
  enable_thinking: boolean;
  reasoning_effort: string;
  /** Merged into the stored map server-side. */
  reasoning_effort_by_model: Record<string, string>;
  self_evolution_enabled: boolean;
  subagent_enabled: boolean;
  agent_permission_mode: PermissionMode;
  web_password: string;
  /** Server-side language for agent replies, logs and the CLI. */
  cow_lang: 'zh' | 'en';
}>;

export interface CatalogModel {
  name: string;
  capabilities?: string[];
  context_window?: number;
  max_output_tokens?: number;
}

export interface ProviderEntry {
  id: string;
  label: string | {zh?: string; en?: string};
  configured: boolean;
  is_custom?: boolean;
  api_key_field?: string | null;
  api_base_field?: string | null;
  api_key_masked?: string;
  api_base?: string;
  api_base_default?: string;
  api_base_placeholder?: string;
  /** `custom:<custom_id>` vendors carry their own display name. */
  custom_id?: string;
  custom_name?: string;
  catalog?: CatalogModel[];
  effective?: CatalogModel[];
  models: string[];
}

export interface FallbackLink {
  provider: string;
  model: string;
}

/** `GET /api/models`: vendors plus who serves each capability. */
export interface ModelsState {
  providers: ProviderEntry[];
  capabilities: {
    chat: {current_provider: string; current_model: string; use_linkai?: boolean};
    chat_fallback: {enabled: boolean; chain: FallbackLink[]};
    vision?: CapabilityPick;
    asr?: CapabilityPick;
    tts?: CapabilityPick;
    embedding?: CapabilityPick;
    image?: CapabilityPick;
    search?: SearchCapability;
  };
}

/** A model or voice option; the object form adds a short hint such as a voice's gender. */
export type ModelOption = string | {value: string; hint?: string};

export type VoiceReplyMode = 'off' | 'voice_if_voice' | 'always';

export interface CapabilityPick {
  editable?: boolean;
  strategy?: string;
  current_provider?: string;
  current_model?: string;
  current_voice?: string;
  current_dim?: number;
  suggested_provider?: string;
  fallback_provider?: string;
  fallback_model?: string;
  /** Provider ids that can serve this capability, in display order. */
  providers?: string[];
  provider_models?: Record<string, ModelOption[]>;
  /** Voices per provider; some vendors key them by model first. */
  provider_voices?: Record<string, ModelOption[] | Record<string, ModelOption[]>>;
  reply_mode?: VoiceReplyMode;
  note?: string;
}

export interface SearchProviderMeta {
  id: string;
  label: string | {zh?: string; en?: string};
  configured: boolean;
  needs_dedicated_key: boolean;
  api_key_masked?: string;
  anonymous?: boolean;
  needs_url?: boolean;
  url_masked?: string;
  api_base?: string;
}

export interface SearchCapability {
  providers: SearchProviderMeta[];
  strategy: 'auto' | 'fixed';
  current_provider?: string;
  fixed_provider?: string;
  configured_providers?: string[];
  available?: boolean;
}

export type CapabilityKey = 'vision' | 'image' | 'asr' | 'tts' | 'embedding';

/** `GET /api/integrations`: how this server is reached. */
export interface IntegrationsState {
  public_url: string;
  lan_urls: string[];
  listen: {host: string; port: number};
  /** The desktop client owns the port. */
  port_fixed?: boolean;
  local_only: boolean;
  password_set: boolean;
}

export type GuestShareStatus = 'active' | 'unconfirmed' | 'password_missing' | 'disabled' | 'expired';

export interface GuestShareConfig {
  name?: string;
  language?: string;
  welcome?: string;
  suggested_questions?: string[];
  provider?: string;
  model?: string;
  tools?: string[];
  skills?: string[];
  references?: {path: string; note?: string}[];
  expires_at?: string;
  limits?: {daily_messages?: number};
  /** `allowed_origins` are the sites allowed to embed the page. */
  access?: {password_required?: boolean; allowed_origins?: string[]};
  network?: {enabled?: boolean};
  branding?: {color?: string; footer_text?: string; footer_url?: string};
  [key: string]: unknown;
}

export interface GuestShare {
  slug: string;
  name: string;
  status: GuestShareStatus;
  share_token: string;
  password_set: boolean;
  disabled: boolean;
  pending: string[];
  notices: string[];
  file_config: GuestShareConfig;
  effective_config: GuestShareConfig;
  logo_version?: string;
  raw_config?: GuestShareConfig;
  guest_md?: string;
}

export interface GuestSharesOverview {
  feature: {enabled: boolean; web_password_set: boolean; serving: boolean; reason?: string};
  shares: GuestShare[];
  skills: {name: string; description?: string; needs_shell?: boolean}[];
  references: {path: string; agent: string; category: string}[];
  models: {id: string; label: string | {zh?: string; en?: string}; models: string[]}[];
}

export interface ExternalApiState {
  enabled: boolean;
  api_key: string;
}

export type McpTransport = 'stdio' | 'sse' | 'streamable-http';
export type McpStatus = 'ready' | 'pending' | 'failed' | 'needs_auth' | 'disabled' | 'idle';

export interface McpServer {
  name: string;
  type: McpTransport;
  command?: string;
  args?: string[];
  env?: Record<string, string>;
  url?: string;
  headers?: Record<string, string>;
  timeout?: number;
  disabled?: boolean;
  status?: McpStatus;
  [extra: string]: unknown;
}

export interface McpProbe {
  ok: boolean;
  error?: string | null;
  needs_auth?: boolean;
  tools: {name: string; description?: string}[];
}

export interface TaskRun {
  run_id: string;
  agent_id: string;
  session_id?: string;
  task_id: string;
  status: 'running' | 'success' | 'failed' | 'error' | 'cancelled' | (string & {});
  started_at: number;
  ended_at?: number | null;
  error?: string;
  task_name?: string;
  action_type?: string;
  channel_type?: string;
  trigger?: string;
  output_preview?: string;
  full_output?: string | null;
}

export interface VersionInfo {
  version?: string;
  install_kind?: string;
  update_supported?: boolean;
  unsupported_reason?: string;
  platform?: string;
}

export interface ReleaseBrief {
  tag: string;
  name?: string;
  body?: string;
  html_url?: string;
  published_at?: string;
}

export interface UpdateCheck {
  current_version: string;
  up_to_date: boolean;
  latest: ReleaseBrief | null;
  newer_releases?: ReleaseBrief[];
  update_supported?: boolean;
  unsupported_reason?: string;
}

export interface UpdateStatus {
  state: 'idle' | 'running' | 'restarting' | 'success' | 'failed' | (string & {});
  step?: string;
  message?: string;
}

export type MenuItem =
  | {id: string; type: 'builtin'; view: string; title: string; icon: string; hidden?: boolean}
  | {
      id: string;
      type: 'artifact';
      title: string;
      icon: string;
      path: string;
      file?: {file_name: string; kind: string; exists: boolean; preview_url: string; raw_url: string};
    }
  | {id: string; type: 'url'; title: string; icon: string; url: string; open?: 'embed' | 'tab'};

export interface MenuGroup {
  id: string;
  title: string;
  items: MenuItem[];
}

export interface MenuDoc {
  version?: number;
  groups: MenuGroup[];
}

/** A client signed in to the server, with a pairing code or the password. Times are epoch seconds. */
export interface PairedDevice {
  id: string;
  name: string;
  platform: string;
  app_version: string;
  created_at: number;
  last_seen_at: number;
  via?: 'pairing' | 'password';
  /** The web page that paired it from another origin. */
  origin?: string;
  last_ip?: string;
  online?: boolean;
}

/** The server as a device. */
export interface DeviceInstance {
  id: string;
  name: string;
  version: string;
  /** Run and named by whoever hosts it: no rename here. */
  managed?: boolean;
}

/** `GET /api/devices`. */
export interface DeviceList {
  devices: PairedDevice[];
  /** This app's own entry; empty when signed in some other way. */
  current: string;
  instance: DeviceInstance;
  password_set: boolean;
}

/** `POST /api/pairing`: a code another device can redeem for its own token. */
export interface PairingCode {
  pairing_id: string;
  code: string;
  expires_in: number;
  urls: string[];
  link: string;
  qr_image?: string;
  password_set: boolean;
  instance: DeviceInstance;
}
