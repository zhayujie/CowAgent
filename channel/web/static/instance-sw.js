/* Sends the console's backend calls to the instance it is switched to.

   The console page and its assets always come from the server that served
   them; only backend paths are routed, with the device token that instance
   issued to this browser. The other side answers only this page's origin and
   only with that token (see request_guard.cors_origin), so nothing here
   relies on the browser sending cookies across sites.

   Registered by core/instances.js while another instance is active; the
   target lives in CacheStorage so a restarted worker finds it again. Served
   from the site root so its scope covers every backend path. */

const CONFIG_CACHE = 'cow-instance';
const CONFIG_KEY = '/__cow_instance__';
const BACKEND_PREFIXES = ['/api/', '/auth/', '/.well-known/', '/uploads/', '/preview/', '/share/', '/v1/'];
const BACKEND_PATHS = new Set(['/message', '/upload', '/poll', '/stream', '/cancel', '/config']);
// Capability links carry their own credential in the path; opened as a page
// or a sandboxed frame, they go to the instance itself, which serves their
// relative assets too.
const CAPABILITY_PREFIXES = ['/preview/', '/share/'];
// A remote file opened as a page must not run as the console's origin, where
// it could read the tokens this browser holds.
const DOCUMENT_CSP = 'sandbox allow-scripts allow-popups allow-forms allow-modals allow-downloads';
const DOCUMENT_HEADERS = ['Content-Type', 'Content-Disposition', 'Content-Length', 'Last-Modified', 'Cache-Control'];

let target;   // { url, token } | null once read; undefined until then

self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (event) => event.waitUntil(self.clients.claim()));

self.addEventListener('message', (event) => {
    const type = event.data && event.data.type;
    if (type === 'config') {
        target = undefined;
        event.waitUntil(readTarget().then(() => reply(event, { type: 'config-ok' })));
    }
});

function reply(event, message) {
    if (event.ports && event.ports[0]) event.ports[0].postMessage(message);
}

async function readTarget() {
    if (target !== undefined) return target;
    try {
        const cache = await caches.open(CONFIG_CACHE);
        const res = await cache.match(CONFIG_KEY);
        const value = res ? await res.json() : null;
        target = value && value.url && value.token ? value : null;
    } catch (_) {
        target = null;
    }
    return target;
}

function isBackend(path) {
    return BACKEND_PATHS.has(path) || BACKEND_PREFIXES.some((p) => path.startsWith(p));
}

self.addEventListener('fetch', (event) => {
    const req = event.request;
    const url = new URL(req.url);
    if (url.origin !== self.location.origin || !isBackend(url.pathname)) return;
    if (target === null) return;
    event.respondWith(route(req, url));
});

async function route(req, url) {
    const to = await readTarget();
    if (!to) return fetch(req);
    const remote = to.url + url.pathname + url.search;
    if (req.mode === 'navigate') {
        const capability = CAPABILITY_PREFIXES.some((p) => url.pathname.startsWith(p));
        return capability ? Response.redirect(remote, 302) : openDocument(remote, to.token);
    }
    // The instance only answers this origin when the device token comes
    // along, capability links included.
    return forward(req, remote, to.token);
}

async function forward(req, remote, token) {
    const headers = new Headers(req.headers);
    headers.set('Authorization', `Bearer ${token}`);
    const init = {
        method: req.method,
        headers,
        mode: 'cors',
        credentials: 'omit',
        redirect: 'follow',
        signal: req.signal,
    };
    if (req.method !== 'GET' && req.method !== 'HEAD') init.body = await req.arrayBuffer();
    try {
        return await fetch(remote, init);
    } catch (err) {
        if (req.signal && req.signal.aborted) throw err;
        return (await tokenRefused(token)) ? refused() : unreachable();
    }
}

// A revoked token gets no CORS headers, which the browser reports exactly
// like a dead network. Tell them apart: the instance still answers the open
// discovery path, but not an authenticated call with this token.
async function tokenRefused(token) {
    const base = target && target.url;
    if (!base) return false;
    try {
        const res = await fetch(`${base}/.well-known/cowagent`, { mode: 'cors', credentials: 'omit', cache: 'no-store' });
        if (!res.ok) return false;
    } catch (_) {
        return false;
    }
    try {
        await fetch(`${base}/auth/check`, {
            headers: { Authorization: `Bearer ${token}` }, mode: 'cors', credentials: 'omit', cache: 'no-store',
        });
        return false;
    } catch (_) {
        return true;
    }
}

async function openDocument(remote, token) {
    let res;
    try {
        res = await fetch(remote, { headers: { Authorization: `Bearer ${token}` }, mode: 'cors', credentials: 'omit' });
    } catch (_) {
        return (await tokenRefused(token)) ? refused() : unreachable();
    }
    const headers = new Headers({ 'Content-Security-Policy': DOCUMENT_CSP, 'X-Content-Type-Options': 'nosniff' });
    for (const name of DOCUMENT_HEADERS) {
        const value = res.headers.get(name);
        if (value) headers.set(name, value);
    }
    return new Response(res.body, { status: res.status, statusText: res.statusText, headers });
}

// Shaped like /auth/check's answer so the boot path reads it as signed out.
function refused() {
    const body = JSON.stringify({
        status: 'error',
        reason: 'device_revoked',
        auth_required: true,
        authenticated: false,
        message: 'The instance no longer accepts this device.',
    });
    return new Response(body, { status: 401, headers: { 'Content-Type': 'application/json' } });
}

function unreachable() {
    const body = JSON.stringify({
        status: 'error',
        reason: 'instance_unreachable',
        message: 'The instance this console is switched to did not answer.',
    });
    return new Response(body, { status: 502, headers: { 'Content-Type': 'application/json' } });
}
