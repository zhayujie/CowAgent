import type {StreamEvent} from '../protocol/events';

/**
 * Incremental parser for a `text/event-stream` body. Fed with the newly
 * received suffix of the response text; keeps partial lines between calls.
 */
export class SSEParser {
  private buffer = '';
  private data: string[] = [];
  private lastId: string | null = null;

  constructor(private readonly onMessage: (data: string, id: string | null) => void) {}

  push(chunk: string) {
    this.buffer += chunk;
    let newline = this.buffer.search(/\r\n|\r|\n/);
    while (newline >= 0) {
      const line = this.buffer.slice(0, newline);
      const sepLength = this.buffer.startsWith('\r\n', newline) ? 2 : 1;
      this.buffer = this.buffer.slice(newline + sepLength);
      this.processLine(line);
      newline = this.buffer.search(/\r\n|\r|\n/);
    }
  }

  private processLine(line: string) {
    if (line === '') {
      if (this.data.length > 0) {
        this.onMessage(this.data.join('\n'), this.lastId);
        this.data = [];
      }
      return;
    }
    if (line.startsWith(':')) {
      return;
    }
    const colon = line.indexOf(':');
    const field = colon < 0 ? line : line.slice(0, colon);
    let value = colon < 0 ? '' : line.slice(colon + 1);
    if (value.startsWith(' ')) {
      value = value.slice(1);
    }
    if (field === 'data') {
      this.data.push(value);
    } else if (field === 'id') {
      this.lastId = value;
    }
  }
}

export interface EventStreamHandle {
  close(): void;
}

export interface EventStreamOptions<T = StreamEvent> {
  url: string;
  headers: Record<string, string>;
  onEvent: (event: T) => void;
  /** Called once when the connection ends; `error` is set on failure. */
  onClose: (error?: Error) => void;
}

/**
 * The server sends `: keepalive` every second while idle. A connection left
 * half-open by a network switch never errors (Android's OkHttp has no read
 * timeout), so silence this long is treated as a dropped stream.
 */
const IDLE_TIMEOUT_MS = 30_000;

/**
 * Read a server-sent event stream over XMLHttpRequest. React Native has no
 * EventSource and its fetch does not expose a streaming body, but XHR reports
 * progressive `responseText` on iOS, Android and RNOH.
 */
export function openEventStream<T = StreamEvent>(opts: EventStreamOptions<T>): EventStreamHandle {
  const xhr = new XMLHttpRequest();
  let offset = 0;
  let finished = false;
  let idleTimer: ReturnType<typeof setTimeout> | null = null;
  const parser = new SSEParser(data => {
    let event: T;
    try {
      event = JSON.parse(data) as T;
    } catch {
      // Ignore malformed frames; the server only emits JSON payloads.
      return;
    }
    try {
      opts.onEvent(event);
    } catch (e) {
      // A throw here would escape into the native XHR callback and be fatal
      // in release builds; one bad event must not take the app down.
      console.error('[sse] event handler failed', e);
    }
  });

  const finish = (error?: Error) => {
    if (idleTimer) {
      clearTimeout(idleTimer);
      idleTimer = null;
    }
    if (finished) {
      return;
    }
    finished = true;
    opts.onClose(error);
  };

  const armIdleTimer = () => {
    if (idleTimer) {
      clearTimeout(idleTimer);
    }
    if (finished) {
      idleTimer = null;
      return;
    }
    idleTimer = setTimeout(() => {
      finish(new Error('Stream stalled'));
      xhr.abort();
    }, IDLE_TIMEOUT_MS);
  };

  const drain = () => {
    const text = xhr.responseText || '';
    if (text.length > offset) {
      armIdleTimer();
      parser.push(text.slice(offset));
      offset = text.length;
    }
  };

  xhr.open('GET', opts.url);
  xhr.withCredentials = false;
  xhr.setRequestHeader('Accept', 'text/event-stream');
  xhr.setRequestHeader('Cache-Control', 'no-cache');
  for (const [key, value] of Object.entries(opts.headers)) {
    xhr.setRequestHeader(key, value);
  }
  xhr.onprogress = drain;
  xhr.onreadystatechange = () => {
    if (xhr.readyState !== XMLHttpRequest.DONE) {
      return;
    }
    drain();
    if (xhr.status === 200) {
      finish();
    } else {
      finish(new Error(xhr.status ? `HTTP ${xhr.status}` : 'Network error'));
    }
  };
  xhr.onerror = () => finish(new Error('Network error'));
  xhr.send();
  armIdleTimer();

  return {
    close() {
      if (idleTimer) {
        clearTimeout(idleTimer);
        idleTimer = null;
      }
      finished = true;
      xhr.abort();
    },
  };
}
