// ============================================================
// Electron bridge
// ============================================================

export interface ElectronAPI {
  getBackendPort: () => Promise<number | null>
  getBackendStatus: () => Promise<string>
  /** The last backend failure, queryable so it can't be missed by timing. */
  getBackendError: () => Promise<BackendFailure | null>
  /** Data dir holding config.json and run.log (~/.cow in packaged builds). */
  getDataDir: () => Promise<string>
  /** Per-launch secret shared with the spawned backend (desktop-only requests). */
  getDesktopToken?: () => Promise<string>
  /** On-disk path of a picked/dropped File; '' when it has none (pasted image). */
  getPathForFile?: (file: File) => string
  restartBackend: () => Promise<boolean>
  selectDirectory: () => Promise<string | null>
  selectFile: (filters?: { name: string; extensions: string[] }[]) => Promise<string | null>
  /** Open a local file with the OS default app. Resolves to '' on success. */
  openPath: (targetPath: string) => Promise<string>
  // Listener registrars return an unsubscribe fn for cleanup.
  onBackendStatus: (callback: (data: BackendStatusEvent) => void) => () => void
  onBackendLog: (callback: (line: string) => void) => () => void
  windowMinimize: () => Promise<void>
  windowMaximize: () => Promise<boolean>
  windowClose: () => Promise<void>
  windowIsMaximized: () => Promise<boolean>
  onMaximizeChange: (callback: (maximized: boolean) => void) => () => void
  onMenuAction?: (callback: (action: string) => void) => () => void
  // Current app version string (e.g. "0.0.5").
  getAppVersion?: () => Promise<string>
  // Launch-at-login toggle (macOS + Windows). get returns the effective state;
  // set returns the real outcome so the UI can surface refusals/errors.
  getLoginItemEnabled?: () => Promise<boolean>
  setLoginItemEnabled?: (
    enabled: boolean
  ) => Promise<{ ok: boolean; enabled: boolean; error: string }>
  // Themes (bundled + user themes from ~/.cow/themes), images inlined.
  listThemes?: () => Promise<Record<string, unknown>[]>
  getThemesDir?: () => Promise<string>
  // Optional app config: first-run default theme + display name. Null when
  // the build ships no app config (standard build).
  getAppConfig?: () => Promise<{ defaultTheme?: string; appName?: string } | null>
  // Generic HTTPS relay via the main process (bypasses renderer CORS).
  httpRelay?: (req: {
    url: string
    method?: string
    headers?: Record<string, string>
    body?: string
  }) => Promise<{ ok: boolean; status: number; headers: Record<string, string>; body: string }>
  // Auto-update. lang (e.g. "zh") routes installer downloads to the China CDN.
  checkForUpdate?: (lang?: string) => Promise<void>
  downloadUpdate?: (lang?: string) => Promise<void>
  installUpdate?: () => Promise<void>
  onUpdateStatus?: (callback: (status: UpdateStatus) => void) => () => void
  // Override the window/Dock/taskbar icon and title at runtime (cached across
  // launches). Used by product extensions; unused by the standard build.
  setAppIcon?: (iconUrl: string, icoUrl?: string) => Promise<boolean>
  setAppTitle?: (title: string) => Promise<boolean>
  // Show a native OS notification; clicking it focuses the window and fires
  // onOpenSession with the session id.
  notify?: (payload: { title?: string; body?: string; sessionId?: string; silent?: boolean; force?: boolean }) => Promise<boolean>
  onOpenSession?: (callback: (sessionId: string) => void) => () => void
  platform: string
  // OS UI language (e.g. "zh-CN"); used to default the language on first run.
  systemLocale?: string
}

// Mirrors UpdateStatus in src/main/updater.ts.
export type UpdateStatus =
  | { state: 'checking' }
  // userInitiated: true when the check came from an explicit "check for update"
  // click; drives whether a dismissed version re-opens the panel (see store).
  | { state: 'available'; version: string; notes?: string; userInitiated?: boolean }
  | { state: 'not-available' }
  | { state: 'downloading'; percent: number }
  | { state: 'downloaded'; version: string }
  | { state: 'error'; message: string }

/** Why the backend failed. Mirrors BackendErrorCode in main/python-manager.ts. */
export type BackendErrorCode =
  | 'backend_removed'
  | 'backend_missing'
  | 'backend_blocked'
  | 'backend_crashed'
  | 'backend_timeout'
  | 'backend_unresponsive'

export interface BackendFailure {
  code: BackendErrorCode
  message: string
  path?: string
}

export interface BackendStatusEvent {
  // 'lost' means a previously-ready backend stopped answering and the main
  // process is restarting it.
  status: 'ready' | 'error' | 'starting' | 'lost'
  port?: number
  error?: string
  // Present on 'error': lets the UI explain the specific failure and what to
  // do about it, rather than falling back to one generic sentence.
  code?: BackendErrorCode
  path?: string
}

// ============================================================
// Chat / messages / streaming
// ============================================================

export type Role = 'user' | 'assistant' | 'system'

/** One tool call made inside a sub agent, shown under that sub agent's step. */
export interface SubStep {
  id: string
  name: string
  args?: string
  status?: string
  execution_time?: number
  error?: string
}

export interface ToolRetrievalMetadata {
  mode: 'retrieved' | 'fallback'
  total_mcp_tools: number
  selected_mcp_tools: number
  builtin_tools: number
  top_k: number
  candidate_count: number
  selected_tools: string[]
  ranked_tools: Array<{ name: string; score: number }>
  fallback_reason?: string | null
}

/** A single ordered step inside an assistant turn (matches backend history). */
export interface MessageStep {
  type: 'thinking' | 'content' | 'tool' | 'retrieval'
  content?: string
  retrieval?: ToolRetrievalMetadata
  // tool step fields
  id?: string
  name?: string
  arguments?: Record<string, unknown>
  result?: string
  is_error?: boolean
  status?: string
  execution_time?: number
  /** The outcome written for a person. Rendered instead of `result`, which is
   * the form the model was handed. */
  display?: string
  /** Work done inside this step, for a tool that drives sub agents. */
  substeps?: SubStep[]
  /** Set when the tool was refused by the session's permission mode, so the UI
   * can render an actionable "adjust permissions" hint rather than a plain error. */
  permission_denied?: boolean
  /** The mode that refused the call (read-only / workspace-write / full-access). */
  permission_mode?: string
}

/** Local UI message model (superset of backend history message). */
export interface ChatMessage {
  id: string
  role: Role
  content: string
  /** Unix seconds. Backend history uses `created_at`; we normalize to `timestamp`. */
  timestamp: number
  attachments?: Attachment[]
  /** User-facing files the agent wrote during this turn, shown as file cards. */
  artifacts?: Artifact[]
  /** Ordered steps (thinking / content / tool). Preferred over legacy toolCalls. */
  steps?: MessageStep[]
  /** Legacy live-stream tool events (kept for backward compat during streaming). */
  toolCalls?: ToolCall[]
  /** Reasoning text streamed via `reasoning` SSE events. */
  reasoning?: string
  /** Sequence numbers from backend (for delete/regenerate). */
  userSeq?: number
  botSeq?: number
  /** Self-evolution bubble flag; 'divider' renders a context-cleared separator. */
  kind?: 'evolution' | 'divider'
  extras?: Record<string, unknown>
  isStreaming?: boolean
  isCancelled?: boolean
  error?: string
  /** request_id of a server-pushed (scheduler) message, used to dedupe polls. */
  pushRequestId?: string
}

export interface Attachment {
  file_path: string
  file_name: string
  /** `workspace_ref` points at an existing workspace file (dragged from the
   *  file panel or picked with `@`) and is referenced in place, not uploaded. */
  file_type: 'image' | 'video' | 'file' | 'directory' | 'workspace_ref'
  /** For `workspace_ref`: whether the reference points at a folder. */
  is_dir?: boolean
  preview_url?: string
  /** Local absolute path (set for files sent via the `send` tool) so the
   *  desktop client can open them directly with the OS default app. */
  abs_path?: string
}

// ============================================================
// Workspace files / artifacts
// ============================================================

/** Coarse file classes the preview panel knows how to render. */
export type FileKind =
  | 'directory'
  | 'html'
  | 'markdown'
  | 'image'
  | 'video'
  | 'audio'
  | 'pdf'
  | 'csv'
  | 'code'
  | 'office'
  | 'text'
  | 'file'

export interface WorkspaceEntry {
  name: string
  /** Workspace-relative path. */
  path: string
  is_dir: boolean
  kind: FileKind
  previewable: boolean
  size: number
  mtime: number
  abs_path?: string
  raw_url?: string
  preview_url?: string
}

/** Response of GET /api/workspace/read: the editor's initial content. */
export interface WorkspaceReadResult {
  path: string
  content: string
  /** The read stopped at the size cap, so the tail is missing. */
  truncated: boolean
  /** Bytes had to be replaced to decode as UTF-8. */
  lossy: boolean
  size: number
  /** Baseline passed back on save so the backend can detect a mid-edit rewrite. */
  mtime: number
  /** False when saving would be refused: wrong kind, truncated or lossy. */
  editable: boolean
}

/** Response of POST /api/workspace/write. */
export interface WorkspaceWriteResult {
  path?: string
  size?: number
  mtime?: number
  /** `"conflict"` when the file changed on disk since `expected_mtime`. */
  code?: string
}

export interface WorkspaceTree {
  path: string
  root: string
  entries: WorkspaceEntry[]
  truncated: boolean
}

// ============================================================
// Project workspace (per-session working directory)
// ============================================================

/** A project directory the user can point a session at. */
export interface ProjectRef {
  path: string
  name: string
  /** Unix seconds of last use; present on recents. */
  ts?: number
}

/** Project picker state for a session (from /api/projects). */
export interface ProjectState {
  /** null when the session uses the default workspace (~/cow). */
  current: ProjectRef | null
  default_workspace: string
  projects_root?: string
  recents: ProjectRef[]
}

/** A user-facing file the agent wrote during a turn. */
export interface Artifact {
  abs_path: string
  rel_path: string
  file_name: string
  kind: FileKind
  previewable: boolean
  size: number
  raw_url: string
  preview_url: string
}

/** Live tool event during SSE streaming. */
export interface ToolCall {
  type: 'tool_start' | 'tool_end' | 'tool_progress'
  tool: string
  tool_call_id?: string
  arguments?: Record<string, unknown>
  result?: string
  status?: string
  execution_time?: number
}

/** All SSE event types emitted on /stream. */
export type StreamEventType =
  | 'delta'
  | 'reasoning'
  | 'tool_retrieval'
  | 'tool_start'
  | 'tool_progress'
  | 'tool_end'
  | 'subagent_step'
  | 'peer_start'
  | 'peer_end'
  | 'message_end'
  | 'phase'
  | 'file_to_send'
  | 'artifact'
  | 'image'
  | 'video'
  | 'file'
  | 'text'
  | 'done'
  | 'cancelled'
  | 'voice_attach'
  | 'error'

export interface StreamEvent {
  type: StreamEventType
  content?: string
  tool?: string
  tool_call_id?: string
  arguments?: Record<string, unknown>
  status?: string
  result?: string
  /** `tool_end`: the outcome written for a person, when the tool wrote one. */
  display?: string
  execution_time?: number
  has_tool_calls?: boolean
  /** `tool_retrieval`: sanitized MCP retrieval decision metadata. */
  mode?: 'retrieved' | 'fallback'
  total_mcp_tools?: number
  selected_mcp_tools?: number
  builtin_tools?: number
  top_k?: number
  candidate_count?: number
  selected_tools?: string[]
  ranked_tools?: Array<{ name: string; score: number }>
  fallback_reason?: string | null
  /** `tool_end`: true when the call was refused by the session permission mode. */
  permission_denied?: boolean
  /** `tool_end`: the mode that refused the call. */
  permission_mode?: string
  /** `subagent_step` event fields: which step of which card, and how it went. */
  card_id?: string
  step_id?: string
  phase?: 'start' | 'end'
  /** `peer_start` / `peer_end`: the teammate whose turn this is. */
  agent_id?: string
  agent_name?: string
  error?: string
  path?: string
  abs_path?: string
  file_name?: string
  file_type?: string
  web_url?: string
  audio_url?: string
  /** `artifact` event fields. */
  rel_path?: string
  kind?: FileKind
  previewable?: boolean
  size?: number
  raw_url?: string
  preview_url?: string
  request_id?: string
  timestamp?: number
  user_seq?: number
  bot_seq?: number
  message?: string
}

// ============================================================
// Sessions / history
// ============================================================

export interface SessionItem {
  session_id: string
  title: string
  created_at: number
  last_active: number
  msg_count: number
  /** User-pinned to the top of its group. */
  pinned?: boolean
  /** Bound project workspace, or null/absent for the default workspace. */
  project?: { path: string; name: string } | null
  /** The Agent whose store holds this conversation (multi-Agent backends). */
  agent?: AgentBadge
  /** Everyone in the conversation (owner first) when more than one Agent is
   *  in it; absent for an ordinary solo chat. */
  participants?: AgentBadge[]
}

/** The compact Agent identity the backend attaches to sessions and teams. */
export interface AgentBadge {
  id: string
  name: string
  avatar?: string
}

export interface SessionsPage {
  sessions: SessionItem[]
  total: number
  page: number
  page_size: number
  has_more: boolean
  /** "project" once more than one distinct workspace is in play, else "time". */
  group_mode?: 'project' | 'time'
  /** Number of distinct project spaces across all sessions (decides group_mode). */
  space_count?: number
  default_workspace?: string
  /** User-defined order of project spaces; "__default__" marks the default one. */
  project_order?: string[]
}

/** Per-session model + permission overrides (from /api/sessions/{id}/settings). */
export interface SessionModelProvider {
  id: string
  label: string | { zh: string; en: string }
  models: string[]
}

export interface SessionSettingsState {
  model: {
    model: string
    provider: string
    // Where the effective model comes from: the conversation's own pin, the
    // owning Agent's default model, or the global config (in that order).
    source: 'session' | 'agent' | 'global'
    global: { model: string; provider: string }
    // The owning Agent's default model, when it has one (never for the default Agent).
    agent?: { model: string; provider: string } | null
    providers: SessionModelProvider[]
  }
  permission: {
    mode: 'read-only' | 'workspace-write' | 'full-access'
    source: 'session' | 'global'
    global: string
    modes: string[]
  }
  /** Who else is on this conversation (multi-Agent backends only). */
  team?: SessionTeam
}

export interface SessionTeam {
  owner: AgentBadge
  /** Invited teammates; `available: false` marks an archived/disabled one. */
  members: (AgentBadge & { available?: boolean })[]
  /** Enabled Agents that could still be invited. */
  candidates: AgentBadge[]
}

/** Backend history message (as returned by /api/history). */
export interface HistoryMessage {
  role: Role
  content: string
  created_at: number
  steps?: MessageStep[]
  tool_calls?: Array<{ id?: string; name: string; arguments?: Record<string, unknown>; result?: string }>
  reasoning?: string
  kind?: 'evolution'
  extras?: Record<string, unknown>
  /** Files written this turn, rebuilt server-side from the write/edit steps. */
  artifacts?: Artifact[]
  /** Per-message sequence number used by delete/regenerate APIs. */
  _seq?: number
}

export interface HistoryPage {
  messages: HistoryMessage[]
  total: number
  page: number
  page_size: number
  has_more: boolean
  context_start_seq?: number
}

/** One entry in the navigation timeline: a user message, by its stored seq. */
export interface UserMessageIndexEntry {
  seq: number
  preview: string
  created_at: number
}

export interface UserMessageIndex {
  messages: UserMessageIndexEntry[]
  total: number
}

/** Heuristic breakdown of what is occupying the session's context window.
 *  `available` is false when the session has no live agent yet (fresh session,
 *  or one just cleared) — the other fields are then absent. */
export interface ContextUsage {
  available: boolean
  estimated?: boolean
  model?: string | null
  /** Model's total context window (input + output). */
  window?: number
  /** Input budget the trimmer targets — the denominator for the chart. */
  limit?: number
  /** system + tools + history. May exceed `limit`: tool schemas are not budgeted. */
  used?: number
  messages?: number
  breakdown?: {
    system: number
    tools: number
    history: number
    free: number
  }
}

// ============================================================
// Config
// ============================================================

/** A label that may be localized (some providers/channels return {zh,en}). */
export type LocalizedLabel = string | { zh: string; en: string }

export interface ReasoningOption {
  value: string
  label: string
}

export interface ReasoningCapability {
  supported: boolean
  param?: string
  default?: string
  thinking_only?: boolean
  options: ReasoningOption[]
}

export interface ProviderMeta {
  label: LocalizedLabel
  models: string[]
  reasoning?: ReasoningCapability
  reasoning_by_model?: Record<string, ReasoningCapability>
  api_base_key?: string | null
  api_base_default?: string | null
  api_base_placeholder?: string
  api_key_field?: string | null
  [k: string]: unknown
}

export interface ConfigData {
  use_agent: boolean
  title: string
  model: string
  bot_type: string
  use_linkai: boolean
  channel_type: string
  /** Optional manual override for the input budget; 0 = derive from the model. */
  agent_max_context_tokens: number
  agent_max_context_turns: number
  agent_max_steps: number
  /** Global default permission for sessions that have not picked one. */
  agent_permission_mode?: string
  permission_modes?: string[]
  enable_thinking?: boolean
  reasoning_effort?: string
  reasoning_effort_by_model?: Record<string, string>
  subagent_enabled?: boolean
  self_evolution_enabled?: boolean
  api_bases: Record<string, string>
  api_keys: Record<string, string>
  providers: Record<string, ProviderMeta>
  web_password_masked?: string
  // Real password, only returned to the desktop app (trusted local machine) so
  // it can be edited in place. Undefined for browser access.
  web_password?: string
}

// ============================================================
// Models console (/api/models)
// ============================================================

// A model/voice entry can be a bare id or an annotated {value, hint} object.
export interface ModelOption {
  value: string
  hint?: string
}
export type ModelEntry = string | ModelOption

// Capability tags a catalog model carries: which tool positions it appears
// in. "text" marks a conversational model (main-model / switcher candidate).
export type ModelCapability = 'text' | 'vision' | 'video' | 'image' | 'embedding' | 'asr' | 'tts'

// One user-managed entry in a provider's model catalog.
export interface ModelCatalogEntry {
  name: string
  capabilities: ModelCapability[]
  context_window?: number
  max_output_tokens?: number
}

export interface ModelProvider {
  id: string
  label: LocalizedLabel
  configured: boolean
  is_custom: boolean
  custom_id?: string
  custom_name?: string
  active?: boolean
  api_key_field?: string | null
  api_base_field?: string | null
  api_key_masked?: string
  api_base?: string
  api_base_default?: string
  api_base_placeholder?: string
  // The model catalog is an OVERLAY on the presets, not a replacement:
  // - `catalog` is the user's raw overrides (edited/added entries),
  // - `hidden` is the preset names the user removed (tombstones),
  // - `seed` is the preset base (typed with real capabilities),
  // - `effective` is the merged list (presets − hidden + overrides) the editor
  //   loads and the chat switcher offers.
  // A custom provider has no presets, so `catalog` is simply its whole list and
  // `effective` equals it.
  catalog?: ModelCatalogEntry[]
  hidden?: string[]
  /** Preset models pre-typed with their real capabilities (built-in vendors). */
  seed?: ModelCatalogEntry[]
  /** The merged list the editor prefills (presets − hidden + overrides). */
  effective?: ModelCatalogEntry[]
  models: ModelEntry[]
}

export type CapabilityKey = 'chat' | 'vision' | 'asr' | 'tts' | 'embedding' | 'image' | 'search'

// Search providers are described as objects (unlike other capabilities which
// list provider ids only).
export interface SearchProviderMeta {
  id: string
  label: LocalizedLabel
  configured: boolean
  needs_dedicated_key: boolean
  api_key_masked?: string
  // AnySearch can be "configured" via anonymous mode (no key). The backend
  // sets this flag so the UI can badge it and offer the anonymous opt-in.
  anonymous?: boolean
  // SearXNG holds a self-hosted instance URL instead of an API key. When
  // needs_url is set the editor shows a URL field; url_masked echoes the saved
  // URL (not a secret, so returned verbatim) for prefill/edit.
  needs_url?: boolean
  url_masked?: string
}

export interface CapabilityState {
  editable?: boolean
  current_provider?: string
  current_model?: string
  current_voice?: string
  current_dim?: number | null
  suggested_provider?: string
  providers?: string[]
  // provider_models entries are string | {value,hint}
  provider_models?: Record<string, ModelEntry[]>
  // tts only: voices keyed by provider; linkai keyed further by model id
  provider_voices?: Record<string, ModelEntry[] | Record<string, ModelEntry[]>>
  // vision/image
  strategy?: string
  user_specified_model?: string
  fallback_provider?: string
  fallback_model?: string
  // tts
  reply_mode?: 'off' | 'voice_if_voice' | 'always'
  use_linkai?: boolean
  // image
  runtime_active?: boolean
  note?: string
  // search
  fixed_provider?: string
  configured_providers?: string[]
  available?: boolean
  [k: string]: unknown
}

/** One link in the fallback chain: tried after the one before it fails. */
export interface ChatFallbackLink {
  provider: string
  model: string
}

/** Backup chat models, tried in order after the primary one fails a turn. */
export interface ChatFallbackCapabilityState {
  editable?: boolean
  /** Opt-in: when false the fallback never engages. */
  enabled?: boolean
  /** Ordered links; index 0 is tried first. Unbounded by design. */
  chain?: ChatFallbackLink[]
  current_provider?: string
  current_model?: string
  providers?: string[]
  provider_models?: Record<string, ModelEntry[]>
  /** The primary model, shown so the user sees what is being backed up. */
  primary_provider?: string
  primary_model?: string
}

export interface SearchCapabilityState {
  editable?: boolean
  providers: SearchProviderMeta[]
  strategy?: 'auto' | 'fixed' | string
  current_provider?: string
  fixed_provider?: string
  configured_providers?: string[]
  available?: boolean
}

export interface ModelsData {
  status?: string
  providers: ModelProvider[]
  capabilities: {
    chat: CapabilityState
    chat_fallback?: ChatFallbackCapabilityState
    vision: CapabilityState
    asr: CapabilityState
    tts: CapabilityState
    embedding: CapabilityState
    image: CapabilityState
    // search has a richer providers[] shape
    search: SearchCapabilityState
  }
}

export type ModelsAction =
  | { action: 'set_provider'; provider_id: string; api_key?: string; api_base?: string }
  | { action: 'delete_provider'; provider_id: string }
  | { action: 'set_custom_provider'; name: string; id?: string; api_base: string; api_key?: string; model?: string; make_active?: boolean }
  | { action: 'delete_custom_provider'; id: string }
  | { action: 'set_active_custom_provider'; id: string }
  // Persist a provider's model catalog overlay. `models` are the overrides
  // (edited/added entries) and `hidden` the removed preset names; the backend
  // drops the provider's overlay entirely when both are empty (back to presets).
  | { action: 'save_catalog'; provider_id: string; models: ModelCatalogEntry[]; hidden: string[] }
  // `chat_fallback` is not a first-class CapabilityKey (it has no top-level
  // card), but it is persisted through the same set_capability action, so it
  // is accepted here alongside its opt-in fields.
  | { action: 'set_capability'; capability: CapabilityKey | 'chat_fallback'; provider_id?: string; model?: string; voice?: string; strategy?: string; provider?: string; enabled?: boolean; chain?: ChatFallbackLink[] }
  | { action: 'set_voice_reply_mode'; mode: 'off' | 'voice_if_voice' | 'always' }
  // Dedicated search-provider credentials (bocha / anysearch / serply / tavily
  // use api_key; searxng uses url). The provider field defaults to bocha
  // server-side when omitted; anonymous is AnySearch-only (save with an empty
  // key to enable the anonymous tier).
  | { action: 'set_search_credential'; provider?: string; api_key?: string; url?: string; anonymous?: boolean }

// ============================================================
// Channels
// ============================================================

export interface ChannelField {
  key: string
  label: string
  type: 'text' | 'secret' | 'number' | 'bool'
  value?: string | number | boolean
  default?: string | number | boolean
}

export interface ChannelInfo {
  name: string
  label: { zh: string; en: string }
  icon: string
  color: string
  active: boolean
  fields: ChannelField[]
  login_status?: string
  // Multi-instance fields (present only for one-card-per-instance entries the
  // backend returns in `data.instances` when the install is in multi-Agent
  // mode). Absent on legacy per-type cards, keeping single-Agent behavior.
  instance_id?: string
  channel_type?: string
  agent_id?: string
  members?: string[]
  // User-editable display name for this instance (e.g. "微信2"); empty falls back
  // to the instance id. Present only on per-instance cards (multi-Agent mode).
  instance_name?: string
}

// The full /api/channels response. Legacy single-Agent installs only populate
// `channels`; multi-Agent installs additionally set the flags and `instances`.
export interface ChannelsResponse {
  status: string
  channels: ChannelInfo[]
  multi_agent?: boolean
  multi_instance_types?: string[]
  instances?: ChannelInfo[]
}

export type ChannelAction = 'save' | 'connect' | 'disconnect' | 'rename'

// ============================================================
// Agents / team roster (multi-Agent mode)
// ============================================================

// One Agent in the roster, mirroring the backend AgentProfile.to_dict().
export interface AgentProfile {
  id: string
  name: string
  workspace?: string
  enabled: boolean
  description?: string
  model?: string
  bot_type?: string
  avatar?: string
  // Cache-busting token from the avatar file's mtime; changes on every upload
  // so the <img> refetches even when the roster revision hasn't moved.
  avatar_rev?: string
  skills?: string[]
  knowledge?: string[]
  // "shared" (reads the default Agent's knowledge base) or "own" (private dir).
  knowledge_mode?: 'shared' | 'own'
}

// A stored channel_instances record from the roster (team.json).
export interface ChannelInstanceRecord {
  instance_id: string
  channel_type: string
  agent_id?: string
  members?: string[]
  credentials?: Record<string, unknown>
}

// The /api/agents GET snapshot.
export interface RosterSnapshot {
  status?: string
  default_agent_id: string
  agents: AgentProfile[]
  channel_instances: ChannelInstanceRecord[]
  revision: string
}

export type AgentAction =
  | 'create'
  | 'update'
  | 'archive'
  | 'delete'
  | 'set_knowledge_mode'
  | 'bind_channel_instance'

// A saved named team (GET/POST /api/team-groups): a leader-led Agent group the
// sidebar's "Teams" section opens as a group conversation. The backend resolves
// each member to an {id, name} profile view before returning it.
export interface TeamGroup {
  id: string
  name: string
  leader: string
  members?: Array<{ id: string; name?: string }>
  created_at?: string
  updated_at?: string
}

// ============================================================
// Tools / skills
// ============================================================

export interface ToolInfo {
  name: string
  description: string
}

export interface SkillInfo {
  name: string
  display_name?: string
  description: string
  source?: string
  enabled: boolean
  category?: string
}

/** Response of GET /api/skills/content: a skill's definition file. */
export interface SkillContent extends WorkspaceReadResult {
  name: string
  /** `builtin` or `custom`, by where the loader resolved the skill. */
  source: string
  /** File being shown, relative to the skill's own directory. */
  filename: string
  /**
   * True when the file is replaced from the installation on startup, so an edit
   * would not survive. Reported apart from `source`, which reads `custom` for
   * the workspace copy of a builtin skill and so cannot answer this.
   */
  ships_with_install: boolean
}

// ============================================================
// Memory
// ============================================================

export type MemoryCategory = 'memory' | 'dream' | 'evolution'

export interface MemoryItem {
  filename: string
  type: string // global | daily | dream | evolution
  size: number
  updated_at: string
}

export interface MemoryPage {
  list: MemoryItem[]
  total: number
  page: number
  page_size: number
}

/** Response of GET /api/memory/content. */
export interface MemoryDoc {
  filename: string
  /**
   * Path relative to the agent's state root, which is what the workspace read
   * and write endpoints take. Resolved by the backend because a memory file is
   * addressed by name and category, not by path.
   */
  rel_path: string
  content: string
}

// ============================================================
// Knowledge
// ============================================================

export interface KnowledgeFile {
  name: string
  title: string
  size: number
}

// A directory node in the knowledge tree (recursive).
export interface KnowledgeDir {
  dir: string
  files: KnowledgeFile[]
  children: KnowledgeDir[]
}

export interface KnowledgeList {
  root_files?: KnowledgeFile[]
  tree: KnowledgeDir[]
  stats: { pages: number; size: number }
  enabled: boolean
}

export interface KnowledgeGraph {
  nodes: Array<{ id: string; label: string; category?: string }>
  links: Array<{ source: string; target: string }>
}

// An optional `agent_id` scopes the write to a specific Agent's knowledge base
// (used by the Knowledge page's per-Agent view). Omitted in single-Agent mode.
export type KnowledgeAction = { agent_id?: string } & (
  | { action: 'create_category'; payload: { path: string } }
  | { action: 'create_document'; payload: { path: string; content: string; overwrite?: boolean } }
  | { action: 'rename_category'; payload: { path: string; new_path: string } }
  | { action: 'delete_category'; payload: { path: string; confirm?: boolean } }
  | { action: 'delete_documents'; payload: { paths: string[] } }
  | { action: 'move_documents'; payload: { paths: string[]; target_category: string } }
)

// Result row from a bulk import (one per uploaded file).
export interface KnowledgeImportResult {
  status: 'imported' | 'skipped' | 'failed'
  path?: string
  name?: string
  message?: string
}

export interface KnowledgeImportPayload {
  imported: number
  skipped: number
  failed: number
  results: KnowledgeImportResult[]
}

// ============================================================
// Scheduler
// ============================================================

export interface TaskSchedule {
  type: 'cron' | 'interval' | 'once'
  expression?: string
  seconds?: number
  run_at?: string
}

export interface TaskAction {
  type: 'send_message' | 'agent_task'
  content?: string
  task_description?: string
  receiver?: string
  receiver_name?: string
  is_group?: boolean
  channel_type?: string
  // The exact channel login this task delivers through. For a legacy
  // single-instance channel it equals channel_type. Ownership derives from this.
  instance_id?: string
  // Session the push/notification is threaded into; preserved across edits.
  notify_session_id?: string
  // Channel-specific delivery hints preserved across edits when the target is
  // unchanged (e.g. DingTalk needs the sender staff id to reply).
  dingtalk_sender_staff_id?: string
  silent?: boolean
}

export interface SchedulerTask {
  id: string
  name: string
  enabled: boolean
  created_at: string
  updated_at: string
  schedule: TaskSchedule
  action: TaskAction
  next_run_at?: string
  // The Agent that owns this task. Present only in multi-Agent installs; used to
  // route mutations to the right store and to show the owner badge on the card.
  // For an IM task this is the *effective* owner the backend derives from the
  // delivery instance's current binding, so it stays honest after a re-bind.
  agent_id?: string
}

// One recorded execution of a scheduled task, read from the global runs ledger
// (task_source='scheduler'). Mirrors GET /api/scheduler/runs.
export interface SchedulerRun {
  run_id: string
  // The Agent that ran it. Present in multi-Agent installs; '' is the default.
  agent_id?: string
  session_id: string
  task_id: string
  // 'running' | 'done' | 'error'. Open runs (still executing) show 'running'.
  status: string
  // Unix seconds. ended_at is null while a run is still in flight.
  started_at: number
  ended_at?: number | null
  error?: string
  // Snapshot fields lifted from the run's extras index at record time, so
  // history stays readable even after the task is renamed or deleted.
  task_name?: string
  action_type?: string
  channel_type?: string
  // The delivery channel instance that ran it; resolved to a friendly name
  // client-side against the instance directory.
  instance_id?: string
  // How the tick fired: 'scheduled' (timer) or 'manual' (run-now).
  trigger?: string
  // Short, length-capped peek at what was delivered.
  output_preview?: string
}

// One run plus the full delivered body, for the history detail dialog. Mirrors
// GET /api/scheduler/runs/detail. full_output is the complete message recovered
// from the receiver's session; null when it was pruned or never injected, in
// which case the UI falls back to output_preview.
export interface SchedulerRunDetail extends SchedulerRun {
  full_output?: string | null
}

// A channel instance the console can deliver a scheduled task through. The
// task-create flow picks one of these first, then a recipient within it.
// Mirrors GET /api/scheduler/instances.
export interface SchedulerInstance {
  instance_id: string
  channel_type: string
  // User-friendly instance name (falls back to a bot name / type label / id).
  name: string
  // Friendly channel-type label (e.g. "微信"), shown on the right of the picker.
  channel_label: string
  // The Agent this instance is bound to (""/absent -> default Agent).
  agent_id?: string
  recipient_count: number
}

// A trusted recipient learned from an inbound message on some instance. Mirrors
// GET /api/scheduler/recipients.
export interface TaskRecipient {
  channel_type: string
  instance_id: string
  receiver: string
  name: string
  is_group: boolean
  session_id: string
  // Friendly name of the instance that saw this recipient.
  instance_name?: string
  last_seen_at?: string
}

// ============================================================
// Logs
// ============================================================

export interface LogEvent {
  type: 'init' | 'line' | 'error'
  content?: string
  message?: string
}

declare global {
  interface Window {
    electronAPI?: ElectronAPI
  }
}
