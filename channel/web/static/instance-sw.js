/* Sends the console's backend calls to the instance it is switched to.

   The console page and its assets always come from the server that served
   them; only backend paths are routed, with the device token that instance
   issued to this browser. The other side answers only this page's origin and
   only with that token (see request_guard.cors_origin), so nothing here
   relies on the browser sending cookies across sites.

   Before the token goes anywhere, the open discovery path has to answer with
   the id of the device this browser paired with: an address can be handed
   to another machine, and a token sent there is a token given away. A check
   holds for a minute, and until the address stops answering: a device that
   goes away and comes back, or another that takes its address, is checked
   again before the next request.

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

const VERIFY_TTL_MS = 60 * 1000;

let target;   // { url, token, id } | null once read; undefined until then
let verified = null;  // { at, state } of the last check against the current target
let verifying = null; // the check in flight, shared by concurrent requests

self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (event) => event.waitUntil(self.clients.claim()));

self.addEventListener('message', (event) => {
    const type = event.data && event.data.type;
    if (type === 'config') {
        target = undefined;
        verified = null;
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
    const check = await verify(to);
    if (check === 'unreachable') return unreachable();
    if (check !== 'ok') return wrongDevice(check);
    // Discovery is open; no reason to send the token there.
    if (url.pathname.startsWith('/.well-known/')) return forward(req, remote, '');
    if (req.mode === 'navigate') {
        const capability = CAPABILITY_PREFIXES.some((p) => url.pathname.startsWith(p));
        return capability ? Response.redirect(remote, 302) : openDocument(remote, to.token);
    }
    // The instance only answers this origin when the device token comes
    // along, capability links included.
    return forward(req, remote, to.token);
}

// 'ok', 'unreachable', or what answered instead of the paired device. A
// pairing made before devices had ids carries none and is let through; the
// page records the id on its first visit.
async function verify(to) {
    if (!to.id) return 'ok';
    if (verified && Date.now() - verified.at < VERIFY_TTL_MS) return verified.state;
    if (!verifying) verifying = check(to).finally(() => { verifying = null; });
    return verifying;
}

async function check(to) {
    let body;
    try {
        const res = await fetch(`${to.url}/.well-known/cowagent`, { mode: 'cors', credentials: 'omit', cache: 'no-store' });
        body = await res.json().catch(() => null);
    } catch (_) {
        return 'unreachable';
    }
    const state = body && body.type === 'instance' && body.id === to.id ? 'ok'
        : { reason: 'wrong_device', found: body && body.type === 'instance' ? 'instance' : 'other' };
    if (target === to) verified = { at: Date.now(), state };
    return state;
}

async function forward(req, remote, token) {
    const headers = new Headers(req.headers);
    if (token) headers.set('Authorization', `Bearer ${token}`);
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
        verified = null;
        return token && (await tokenRefused(token)) ? refused() : unreachable();
    }
}

// A revoked token gets no CORS headers, which the browser reports exactly
// like a dead network. Tell them apart: the instance still answers the open
// discovery path, but not an authenticated call with this token.
async function tokenRefused(token) {
    const to = target;
    if (!to) return false;
    try {
        const res = await fetch(`${to.url}/.well-known/cowagent`, { mode: 'cors', credentials: 'omit', cache: 'no-store' });
        const body = await res.json().catch(() => null);
        // Only ask the device that issued the token.
        if (!body || body.type !== 'instance' || (to.id && body.id !== to.id)) return false;
    } catch (_) {
        return false;
    }
    try {
        await fetch(`${to.url}/auth/check`, {
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
        verified = null;
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

function wrongDevice(found) {
    const body = JSON.stringify({
        status: 'error',
        reason: 'wrong_device',
        found: found.found,
        message: 'A different device now answers at this address; the token was not sent.',
    });
    return new Response(body, { status: 409, headers: { 'Content-Type': 'application/json', 'X-Cow-Device-Problem': 'wrong_device' } });
}

function unreachable() {
    const body = JSON.stringify({
        status: 'error',
        reason: 'instance_unreachable',
        message: 'The instance this console is switched to did not answer.',
    });
    return new Response(body, { status: 502, headers: { 'Content-Type': 'application/json' } });
}
