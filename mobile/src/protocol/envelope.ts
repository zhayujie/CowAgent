import type {StreamEvent} from './events';

/**
 * Shared WebSocket transport (`/ws`, served by channel/web/ws/ on the
 * server). The server side is not implemented yet; until `/api/info`
 * advertises a `ws_url` the client
 * falls back to SSE over HTTP.
 */
export const ENVELOPE_VERSION = 1;

export interface Envelope<T extends string = string, P = unknown> {
  v: number;
  /** Per-device, monotonically increasing; drives replay after reconnect. */
  seq: number;
  device_id: string;
  type: T;
  request_id?: string | null;
  session_id?: string | null;
  payload: P;
}

export interface PushMessagePayload {
  content: string;
  session_id?: string;
  timestamp?: number;
}

export interface SchedulerRunPayload {
  run_id: string;
  task_name?: string;
  session_id?: string;
  preview?: string;
}

export interface ApprovalRequestPayload {
  approval_id: string;
  tool: string;
  summary: string;
  arguments?: Record<string, unknown>;
}

export interface SystemPayload {
  event: 'hello.ok' | 'resync_required' | 'revoked' | (string & {});
  message?: string;
}

export type ServerEnvelope =
  | Envelope<'chat.event', StreamEvent>
  | Envelope<'push.message', PushMessagePayload>
  | Envelope<'scheduler.run', SchedulerRunPayload>
  | Envelope<'approval.request', ApprovalRequestPayload>
  | Envelope<'tool.invoke', Record<string, unknown>>
  | Envelope<'system', SystemPayload>;

/** Client frames carry transport control only; business requests use HTTP. */
export type ClientFrame =
  | {type: 'hello'; v: number; token: string; last_seq: number}
  | {type: 'ack'; seq: number}
  | {type: 'ping'; ts: number};

/** Response of `GET /api/info`, used to probe an address before saving it. */
export interface ServerInfo {
  name: string;
  version: string;
  protocol_version?: number;
  /** Absolute WebSocket URL, or a path relative to the probed address. */
  ws_url?: string | null;
  auth_required: boolean;
}
