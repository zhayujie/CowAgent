import {AppState, type AppStateStatus, type NativeEventSubscription} from 'react-native';
import {
  ENVELOPE_VERSION,
  type ClientFrame,
  type ServerEnvelope,
} from '../protocol/envelope';

export type RealtimeStatus = 'idle' | 'connecting' | 'open' | 'closed' | 'revoked';

export interface RealtimeConfig {
  url: string;
  token: string;
  /** Whether the token may go to this address right now; checked before every hello. */
  confirm?: () => Promise<boolean>;
  /** Highest envelope seq already handled; the server replays anything newer. */
  lastSeq: number;
  onEnvelope: (envelope: ServerEnvelope) => void;
  onSeqCommitted: (seq: number) => void;
  onStatus: (status: RealtimeStatus) => void;
}

/** React Native's WebSocket takes request headers; the DOM typings in scope don't know that. */
type NativeWebSocket = new (
  url: string,
  protocols: string | string[] | null,
  options: {headers: Record<string, string>},
) => WebSocket;

const PING_INTERVAL_MS = 25_000;
const IDLE_TIMEOUT_MS = 60_000;
const ACK_DELAY_MS = 500;
const BACKOFF_BASE_MS = 1_000;
const BACKOFF_MAX_MS = 30_000;

/**
 * One WebSocket per device, carrying everything the server pushes. Business
 * requests stay on HTTP; this client only sends hello / ack / ping.
 */
export class RealtimeClient {
  private config: RealtimeConfig | null = null;
  private socket: WebSocket | null = null;
  private status: RealtimeStatus = 'idle';
  private lastSeq = 0;
  private pendingAck = 0;
  private attempts = 0;
  private connectSeq = 0;
  private lastMessageAt = 0;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private ackTimer: ReturnType<typeof setTimeout> | null = null;
  private pingTimer: ReturnType<typeof setInterval> | null = null;
  private appStateSub: NativeEventSubscription | null = null;
  private listeners = new Set<(envelope: ServerEnvelope) => void>();

  start(config: RealtimeConfig) {
    this.stop();
    this.config = config;
    this.lastSeq = config.lastSeq;
    this.appStateSub = AppState.addEventListener('change', this.onAppState);
    this.open();
  }

  stop() {
    this.appStateSub?.remove();
    this.appStateSub = null;
    this.clearTimers();
    this.closeSocket();
    this.config = null;
    this.setStatus('idle');
  }

  isOpen(): boolean {
    return this.status === 'open';
  }

  subscribe(listener: (envelope: ServerEnvelope) => void): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  private onAppState = (state: AppStateStatus) => {
    if (!this.config) {
      return;
    }
    if (state === 'active') {
      // The OS suspends sockets in the background; reconnect right away.
      if (this.status !== 'open' && this.status !== 'connecting') {
        this.attempts = 0;
        this.open();
      }
    } else if (state === 'background') {
      this.flushAck();
      this.clearTimers();
      this.closeSocket();
      this.setStatus('closed');
    }
  };

  private open() {
    const config = this.config;
    if (!config) {
      return;
    }
    this.clearReconnect();
    this.closeSocket();
    this.setStatus('connecting');
    // The token also goes on the upgrade request, where a proxy in front can check it, so the
    // address is confirmed before connecting rather than once the socket is open.
    const seq = this.connectSeq;
    const confirmed = config.confirm ? config.confirm().catch(() => false) : Promise.resolve(true);
    confirmed.then(ok => {
      if (seq !== this.connectSeq || this.config !== config) {
        return;
      }
      if (ok) {
        this.connect(config);
      } else {
        this.setStatus('closed');
        this.scheduleReconnect();
      }
    });
  }

  private connect(config: RealtimeConfig) {
    const socket = new (WebSocket as unknown as NativeWebSocket)(config.url, null, {
      headers: {Authorization: `Bearer ${config.token}`},
    });
    this.socket = socket;

    socket.onopen = () => {
      if (this.socket !== socket) {
        return;
      }
      this.lastMessageAt = Date.now();
      this.send({
        type: 'hello',
        v: ENVELOPE_VERSION,
        token: config.token,
        last_seq: this.lastSeq,
      });
      this.startPing();
    };
    socket.onmessage = event => {
      this.lastMessageAt = Date.now();
      this.handleFrame(String(event.data));
    };
    socket.onerror = () => {
      // onclose follows and schedules the reconnect.
    };
    socket.onclose = () => {
      if (this.socket !== socket) {
        return;
      }
      this.socket = null;
      this.stopPing();
      this.flushAck();
      if (this.status === 'revoked' || !this.config) {
        return;
      }
      this.setStatus('closed');
      this.scheduleReconnect();
    };
  }

  private handleFrame(raw: string) {
    let envelope: ServerEnvelope;
    try {
      envelope = JSON.parse(raw) as ServerEnvelope;
    } catch {
      return;
    }
    if (envelope.type === 'system') {
      if (envelope.payload.event === 'hello.ok') {
        this.attempts = 0;
        this.setStatus('open');
      } else if (envelope.payload.event === 'revoked') {
        this.setStatus('revoked');
        this.closeSocket();
      }
    }
    if (typeof envelope.seq === 'number' && envelope.seq > 0) {
      if (envelope.seq <= this.lastSeq) {
        return;
      }
      this.lastSeq = envelope.seq;
      this.scheduleAck(envelope.seq);
    }
    for (const listener of this.listeners) {
      listener(envelope);
    }
    this.config?.onEnvelope(envelope);
  }

  private scheduleAck(seq: number) {
    this.pendingAck = Math.max(this.pendingAck, seq);
    if (!this.ackTimer) {
      this.ackTimer = setTimeout(() => this.flushAck(), ACK_DELAY_MS);
    }
  }

  private flushAck() {
    if (this.ackTimer) {
      clearTimeout(this.ackTimer);
      this.ackTimer = null;
    }
    if (this.pendingAck > 0) {
      const seq = this.pendingAck;
      this.pendingAck = 0;
      this.send({type: 'ack', seq});
      this.config?.onSeqCommitted(seq);
    }
  }

  private startPing() {
    this.stopPing();
    this.pingTimer = setInterval(() => {
      if (Date.now() - this.lastMessageAt > IDLE_TIMEOUT_MS) {
        // Half-open connection (e.g. network switch): force a reconnect.
        this.socket?.close();
        return;
      }
      this.send({type: 'ping', ts: Date.now()});
    }, PING_INTERVAL_MS);
  }

  private stopPing() {
    if (this.pingTimer) {
      clearInterval(this.pingTimer);
      this.pingTimer = null;
    }
  }

  private scheduleReconnect() {
    this.clearReconnect();
    const exp = Math.min(BACKOFF_MAX_MS, BACKOFF_BASE_MS * 2 ** this.attempts);
    const delay = exp / 2 + Math.random() * (exp / 2);
    this.attempts += 1;
    this.reconnectTimer = setTimeout(() => this.open(), delay);
  }

  private clearReconnect() {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
  }

  private clearTimers() {
    this.clearReconnect();
    this.stopPing();
    if (this.ackTimer) {
      clearTimeout(this.ackTimer);
      this.ackTimer = null;
    }
  }

  private send(frame: ClientFrame) {
    if (this.socket?.readyState === WebSocket.OPEN) {
      this.socket.send(JSON.stringify(frame));
    }
  }

  private closeSocket() {
    // Drops a connect still waiting on its confirmation.
    this.connectSeq += 1;
    const socket = this.socket;
    this.socket = null;
    if (socket) {
      socket.onopen = null;
      socket.onmessage = null;
      socket.onclose = null;
      socket.onerror = null;
      socket.close();
    }
  }

  private setStatus(status: RealtimeStatus) {
    if (this.status === status) {
      return;
    }
    this.status = status;
    this.config?.onStatus(status);
  }
}

export const realtime = new RealtimeClient();
