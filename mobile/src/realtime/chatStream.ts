import {http} from '../api/http';
import {openEventStream, type EventStreamHandle} from '../api/sse';
import type {StreamEvent} from '../protocol/events';
import {realtime} from './RealtimeClient';

export type ChatStreamEnd =
  | {kind: 'complete'}
  | {kind: 'resync'}
  | {kind: 'failed'; error: string};

export interface ChatStreamHandlers {
  onEvent: (event: StreamEvent) => void;
  onEnd: (end: ChatStreamEnd) => void;
}

const SSE_MAX_RETRIES = 5;

/**
 * Follow one request's events. Uses the shared WebSocket when it is up and
 * falls back to `/stream` over HTTP otherwise, resuming with `after_seq` so a
 * dropped connection never duplicates or loses events.
 */
export function subscribeChat(
  requestId: string,
  handlers: ChatStreamHandlers,
  afterSeq = 0,
): () => void {
  let cursor = afterSeq;
  let ended = false;
  let sawDone = false;
  let retries = 0;
  let sse: EventStreamHandle | null = null;
  let retryTimer: ReturnType<typeof setTimeout> | null = null;
  let unsubscribeWs: (() => void) | null = null;

  const end = (result: ChatStreamEnd) => {
    if (ended) {
      return;
    }
    ended = true;
    cleanup();
    handlers.onEnd(result);
  };

  const handle = (event: StreamEvent) => {
    if (ended) {
      return;
    }
    if (typeof event.seq === 'number') {
      if (event.seq <= cursor) {
        return;
      }
      cursor = event.seq;
    }
    // The budget is for consecutive failures, not for a whole long reply.
    retries = 0;
    if (event.type === 'resync_required') {
      end({kind: 'resync'});
      return;
    }
    if (event.type === 'error' && event.reason === 'unknown_request') {
      // The server restarted and forgot this request; reload history instead.
      end({kind: 'resync'});
      return;
    }
    if (event.type === 'done') {
      sawDone = true;
    }
    handlers.onEvent(event);
    if (event.type === 'stream_end') {
      end({kind: 'complete'});
    }
  };

  const startSse = () => {
    const query = `request_id=${encodeURIComponent(requestId)}&after_seq=${cursor}`;
    sse = openEventStream({
      url: http.url(`/stream?${query}`),
      headers: http.authHeaders(),
      onEvent: handle,
      onClose: error => {
        sse = null;
        if (ended) {
          return;
        }
        if (!error && sawDone) {
          end({kind: 'complete'});
          return;
        }
        if (retries >= SSE_MAX_RETRIES) {
          end({kind: 'failed', error: error?.message ?? 'Stream closed'});
          return;
        }
        retries += 1;
        retryTimer = setTimeout(startSse, Math.min(8_000, 500 * 2 ** retries));
      },
    });
  };

  const cleanup = () => {
    unsubscribeWs?.();
    unsubscribeWs = null;
    sse?.close();
    sse = null;
    if (retryTimer) {
      clearTimeout(retryTimer);
      retryTimer = null;
    }
  };

  if (realtime.isOpen()) {
    unsubscribeWs = realtime.subscribe(envelope => {
      if (envelope.type === 'chat.event' && envelope.request_id === requestId) {
        handle(envelope.payload);
      }
    });
  } else {
    startSse();
  }

  return () => {
    ended = true;
    cleanup();
  };
}
