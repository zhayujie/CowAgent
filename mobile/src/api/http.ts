import {HTTP_TIMEOUT_MS} from '../config/defaults';

export type ApiErrorKind =
  | 'network'
  | 'timeout'
  | 'unauthorized'
  | 'http'
  | 'server'
  | 'invalid_response';

export class ApiError extends Error {
  constructor(
    readonly kind: ApiErrorKind,
    message: string,
    readonly status?: number,
    /** The decoded body of a `{status: "error"}` answer, for handlers that put a reason code in it. */
    readonly body?: Record<string, unknown>,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

export function normalizeBaseUrl(raw: string): string {
  let url = raw.trim();
  if (!/^https?:\/\//i.test(url)) {
    url = `https://${url}`;
  }
  return url.replace(/\/+$/, '');
}

const PRIVATE_V4 = [/^10\./, /^127\./, /^192\.168\./, /^172\.(1[6-9]|2\d|3[01])\./, /^169\.254\./, /^100\.(6[4-9]|[7-9]\d|1[01]\d|12[0-7])\./];

/**
 * Plain HTTP to an address outside the local network, where the password and
 * the device token would cross the internet unencrypted. LAN addresses
 * (private, loopback, CGNAT/Tailscale ranges, `.local`, bare host names) are fine.
 */
export function isPublicCleartext(raw: string): boolean {
  const m = /^http:\/\/(\[[^\]]*\]|[^/:?#]+)/i.exec(raw.trim());
  if (!m) {
    return false;
  }
  const host = m[1].toLowerCase();
  if (host.startsWith('[')) {
    return !/^\[(::1|f[cd][0-9a-f]{2}:|fe[89ab][0-9a-f]:)/.test(host);
  }
  if (/^\d+\.\d+\.\d+\.\d+$/.test(host)) {
    return !PRIVATE_V4.some(r => r.test(host));
  }
  return !(host === 'localhost' || !host.includes('.') || /\.(local|lan|home\.arpa|internal)$/.test(host));
}

export interface RequestOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'DELETE';
  body?: unknown;
  timeoutMs?: number;
  /** Skip the Authorization header, e.g. for probing an unknown address. */
  anonymous?: boolean;
}

export class HttpClient {
  private baseUrl = '';
  private token: string | null = null;

  setBaseUrl(url: string) {
    this.baseUrl = normalizeBaseUrl(url);
  }

  getBaseUrl(): string {
    return this.baseUrl;
  }

  setToken(token: string | null) {
    this.token = token;
  }

  getToken(): string | null {
    return this.token;
  }

  authHeaders(): Record<string, string> {
    return this.token ? {Authorization: `Bearer ${this.token}`} : {};
  }

  url(path: string): string {
    return `${this.baseUrl}${path}`;
  }

  async request<T>(path: string, opts: RequestOptions = {}): Promise<T> {
    return this.send<T>(path, opts.timeoutMs, {
      method: opts.method ?? (opts.body === undefined ? 'GET' : 'POST'),
      headers: {
        'Content-Type': 'application/json',
        Accept: 'application/json',
        ...(opts.anonymous ? {} : this.authHeaders()),
      },
      body: opts.body === undefined ? undefined : JSON.stringify(opts.body),
    });
  }

  /** POST a multipart form; fetch sets the boundary, so no Content-Type here. */
  async upload<T>(path: string, form: FormData, timeoutMs = 120_000): Promise<T> {
    return this.send<T>(path, timeoutMs, {
      method: 'POST',
      headers: {Accept: 'application/json', ...this.authHeaders()},
      body: form,
    });
  }

  private async send<T>(path: string, timeoutMs: number | undefined, init: RequestInit): Promise<T> {
    if (!this.baseUrl) {
      throw new ApiError('network', 'Server address is not configured');
    }
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs ?? HTTP_TIMEOUT_MS);
    let res: Response;
    try {
      // The token travels in the header. Letting the login cookie into the native
      // cookie jar would hand it to every page the WebView opens on this server.
      res = await fetch(this.url(path), {...init, credentials: 'omit', signal: controller.signal});
    } catch (e) {
      if (controller.signal.aborted) {
        throw new ApiError('timeout', 'Request timed out');
      }
      throw new ApiError('network', e instanceof Error ? e.message : String(e));
    } finally {
      clearTimeout(timer);
    }

    if (res.status === 401 || res.status === 403) {
      throw new ApiError('unauthorized', 'Authentication required', res.status);
    }
    if (!res.ok) {
      // Some handlers (guest pages) answer errors with a status code and a JSON reason.
      const body = await res.json().catch(() => null);
      const detail = body && typeof body === 'object' ? (body as {message?: string; error?: string}) : null;
      throw new ApiError(
        'http',
        detail?.message || detail?.error || `HTTP ${res.status}`,
        res.status,
        detail ? (body as Record<string, unknown>) : undefined,
      );
    }
    let data: unknown;
    try {
      data = await res.json();
    } catch {
      throw new ApiError('invalid_response', 'Response is not JSON', res.status);
    }
    // web.py handlers answer 200 with {status: "error"} for business failures.
    if (
      data &&
      typeof data === 'object' &&
      (data as {status?: unknown}).status === 'error'
    ) {
      const {message, error} = data as {message?: string; error?: string};
      throw new ApiError('server', message || error || 'Server error', res.status, data as Record<string, unknown>);
    }
    return data as T;
  }
}

export const http = new HttpClient();
