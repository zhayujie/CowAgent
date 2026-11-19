/**
 * Build-time defaults. Each distribution can ship a different default server
 * by replacing this file (or generating it) in its build pipeline; business
 * code must read the value from here and never hard-code an address.
 */
import {Platform} from 'react-native';

const webOrigin = (globalThis as {location?: {origin?: string}}).location?.origin;

// The web preview is served behind a dev proxy, so the page origin is the server.
// Empty means "no bundled server": the login page starts blank instead of
// prefilling an address that cannot resolve.
export const DEFAULT_SERVER_URL = Platform.OS === 'web' && webOrigin ? webOrigin : '';

// Empty means the localized "default server" name.
export const DEFAULT_SERVER_NAME = '';

export const HTTP_TIMEOUT_MS = 15_000;

/** Coalesce streamed deltas before re-rendering the message list. */
export const STREAM_FLUSH_INTERVAL_MS = 80;
