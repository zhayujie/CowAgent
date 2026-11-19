/**
 * Chat stream events, identical to what the web channel publishes on
 * `/stream` (see channel/web/core/channel.py). Over WebSocket they arrive
 * unchanged as the payload of a `chat.event` envelope.
 *
 * Mirrors the subset of desktop/src/renderer/src/types.ts the mobile client
 * consumes; unknown event types must be ignored, not treated as errors.
 */
export type StreamEventType =
  | 'delta'
  | 'reasoning'
  | 'tool_start'
  | 'tool_progress'
  | 'tool_end'
  | 'message_end'
  | 'phase'
  | 'image'
  | 'video'
  | 'file'
  | 'artifact'
  | 'peer_start'
  | 'peer_end'
  | 'subagent_step'
  | 'text'
  | 'done'
  | 'cancelled'
  | 'stream_end'
  | 'resync_required'
  | 'error';

export interface StreamEvent {
  type: StreamEventType | (string & {});
  /** Per-request sequence number; resume with `/stream?after_seq=`. */
  seq?: number;
  content?: string;
  tool?: string;
  tool_call_id?: string;
  arguments?: Record<string, unknown>;
  status?: string;
  result?: string;
  display?: string;
  execution_time?: number;
  file_name?: string;
  file_type?: string;
  preview_url?: string;
  /** `artifact` / `file`: where the file sits on the server, and what it is. */
  abs_path?: string;
  rel_path?: string;
  kind?: string;
  size?: number;
  raw_url?: string;
  request_id?: string;
  user_seq?: number;
  bot_seq?: number;
  reason?: string;
  message?: string;
  after_seq?: number;
  usage?: Usage | null;
  /** `peer_start`/`subagent_step`: the tool call (card) the teammate or sub agent works under. */
  card_id?: string;
  agent_id?: string;
  agent_name?: string;
  /** `subagent_step` only. */
  step_id?: string;
  phase?: 'start' | 'end' | (string & {});
  error?: string;
}

export type Role = 'user' | 'assistant';

export interface Usage {
  prompt_tokens?: number;
  completion_tokens?: number;
  total_tokens?: number;
  prompt_cache_hit_tokens?: number;
  calls?: number;
}

/** One persisted step of an assistant turn, in the order it happened. */
export type HistoryStep =
  | {type: 'thinking'; content: string}
  | {type: 'content'; content: string}
  | {
      type: 'tool';
      id?: string;
      name?: string;
      arguments?: Record<string, unknown>;
      result?: string;
      /** The outcome written for a person, when the tool produced one. */
      display?: string;
      is_error?: boolean;
    };

export type ArtifactKind =
  | 'html'
  | 'image'
  | 'video'
  | 'audio'
  | 'markdown'
  | 'pdf'
  | 'office'
  | 'text'
  | 'csv'
  | 'code'
  | 'file'
  | (string & {});

/** A user-facing file a conversation produced (see channel/web/api/artifacts.py). */
export interface Artifact {
  id: number;
  agent_id: string;
  agent_name?: string;
  session_id: string;
  session_title?: string;
  can_jump?: boolean;
  file_name: string;
  rel_path?: string;
  kind: ArtifactKind;
  previewable?: boolean;
  size?: number;
  created_at: number;
  pinned_at?: number;
  title?: string;
  exists?: boolean;
  abs_path?: string;
  /** `/api/file?path=…`, behind auth. */
  raw_url?: string;
  /** HMAC-signed, so it opens without the auth header. */
  preview_url?: string;
}

/** A file a reply wrote or sent, as history and the live `artifact` event describe it. */
export interface FilePayload {
  abs_path?: string;
  rel_path?: string;
  file_name?: string;
  kind?: string;
  previewable?: boolean;
  size?: number;
  /** `/api/file?path=…`, behind auth. */
  raw_url?: string;
  /** HMAC-signed, so it opens without the auth header. */
  preview_url?: string;
}

export interface HistoryMessage {
  role: Role;
  content: string;
  created_at: number;
  reasoning?: string;
  steps?: HistoryStep[];
  usage?: Usage;
  artifacts?: FilePayload[];
  /** `agent_id` names the Agent that answered, which matters in a shared conversation. */
  extras?: {agent_id?: string};
  /** Set on an assistant turn without a final answer: still running, or failed / cut off. */
  run_state?: RunState;
  _seq?: number;
}

export type RunState = 'running' | 'interrupted';

export interface HistoryPage {
  messages: HistoryMessage[];
  total: number;
  page: number;
  page_size: number;
  has_more: boolean;
  /** A reply still streaming on the server: the page stops where it was stored, the stream continues after `after_seq`. */
  active_request?: {request_id: string; after_seq: number | null};
}

export interface SessionItem {
  session_id: string;
  title: string;
  created_at: number;
  last_active: number;
  msg_count: number;
  pinned?: boolean;
  agent?: {id: string; name: string; avatar?: string};
}

export interface SessionsPage {
  sessions: SessionItem[];
  total: number;
  page: number;
  page_size: number;
  has_more: boolean;
}

export interface SendMessageResult {
  status: string;
  request_id: string;
  stream: boolean;
  message?: string;
  /** The teammate addressed by name, when the message named one; empty otherwise. */
  speaker?: string;
  /** `/cancel` and `/steer` answer here, with no `request_id` to stream. */
  inline_reply?: string;
}
