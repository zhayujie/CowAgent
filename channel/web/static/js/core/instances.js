/* Other CowAgent devices this browser can switch the console to.

   The console page always comes from the device that served it; switching to
   another device routes its backend calls there through /instance-sw.js,
   with the token that device issued when this browser was paired. Before the
   token goes anywhere, the address has to answer with the id of the device
   that issued it. The list lives in this browser only; names come from the
   devices themselves. Classic script sharing the global scope; only
   declarations run at load time. boot.js calls instanceBoot() before
   anything talks to the backend. */

const INSTANCES_KEY = 'cow_instances';
const INSTANCE_LOCAL_KEY = 'cow_local_device';
const INSTANCE_SWITCHER_KEY = 'cow_device_switcher';
const INSTANCE_WORKER = '/instance-sw.js';
const INSTANCE_CACHE = 'cow-instance';
const INSTANCE_CACHE_KEY = '/__cow_instance__';
const INSTANCE_RELOAD_FLAG = 'cow_instance_reload';
// What the console remembers about the data of the device it talks to.
// Each device keeps its own copy, so switching back lands where it was.
const INSTANCE_SCOPED_KEYS = ['cow_active_agent', 'cow_default_agent', 'cow_memory_agent', 'cow_knowledge_agent',
    'cow_menu_cache', 'cow_collapsed_projects', 'cow_notified_run_ids', 'cow_manual_run_origin'];
const INSTANCE_SCOPED_PREFIXES = ['cow_session_id'];

const instanceStatus = {};   // id -> 'checking' | 'online' | 'offline' | 'other'
let instanceMenuOpen = false;
let instanceAddState = null; // { phase, error, instance }

// ---------------------------------------------------------------------------
// Stored list
// ---------------------------------------------------------------------------

function _instancesRead() {
    try {
        const raw = JSON.parse(localStorage.getItem(INSTANCES_KEY) || '{}');
        const items = Array.isArray(raw.items) ? raw.items.filter(i => i && i.id && i.url) : [];
        const active = items.some(i => i.id === raw.active) ? raw.active : '';
        return { active, items };
    } catch (_) {
        return { active: '', items: [] };
    }
}

function _instancesWrite(state) {
    localStorage.setItem(INSTANCES_KEY, JSON.stringify(state));
}

function instanceList() {
    return _instancesRead().items;
}

/** The remote device the console is switched to, or null on the one that served it. */
function instanceActive() {
    const state = _instancesRead();
    return state.items.find(i => i.id === state.active) || null;
}

/** Origin of the device answering the console's backend calls. */
function instanceOrigin() {
    const active = instanceActive();
    return active ? active.url : location.origin;
}

/** A backend path as an address frames and new tabs can open directly. */
function instanceUrl(path) {
    const active = instanceActive();
    return active && typeof path === 'string' && path.startsWith('/') ? active.url + path : path;
}

/** Service workers, and so switching, need a secure page: https or localhost. */
function instanceSupported() {
    return !!(window.isSecureContext && 'serviceWorker' in navigator && 'caches' in window);
}

/** Name of the device that served this page, as it last told us. */
function instanceLocalName() {
    try {
        const saved = JSON.parse(localStorage.getItem(INSTANCE_LOCAL_KEY) || '{}');
        if (saved.name) return saved.name;
    } catch (_) {}
    return location.host;
}

/** /config's `device` for the device the console drives: the name every client shows. */
function instanceNoteDevice(device) {
    if (!device || !device.name) return;
    const active = instanceActive();
    if (active) {
        const managed = !!device.managed;
        if (active.name !== device.name || !!active.managed !== managed) {
            _instanceUpdate(active.id, { name: device.name, managed });
        }
    } else {
        localStorage.setItem(INSTANCE_LOCAL_KEY, JSON.stringify({ name: device.name, id: device.id || '' }));
    }
    _instancesChanged();
}

function _instanceNormalizeUrl(value, scheme) {
    let text = String(value || '').trim();
    if (!text) return '';
    if (!/^https?:\/\//i.test(text)) text = `${scheme || 'http'}://${text}`;
    try {
        const url = new URL(text);
        return `${url.protocol}//${url.host}`;
    } catch (_) {
        return '';
    }
}

function _instanceHost(url) {
    try { return new URL(url).host; } catch (_) { return url || ''; }
}

function _instanceId() {
    const bytes = new Uint8Array(6);
    crypto.getRandomValues(bytes);
    return 'i_' + Array.from(bytes, b => b.toString(16).padStart(2, '0')).join('');
}

// ---------------------------------------------------------------------------
// What answers at an address
// ---------------------------------------------------------------------------

function _instanceFetch(url, init, timeout) {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), timeout);
    return fetch(url, { cache: 'no-store', credentials: 'omit', ...init, signal: ctrl.signal })
        .finally(() => clearTimeout(timer));
}

function _instanceLoopback(url) {
    const host = (() => { try { return new URL(url).hostname; } catch (_) { return ''; } })();
    return host === 'localhost' || host === '[::1]' || host.startsWith('127.');
}

/** Discovery at `base` ('' for the device the console is routed to), or
    throws { reason, host, status } saying why there is none:
    unreachable / timeout / blocked / login / outdated / not_cowagent /
    mixed / wrong_device. */
async function instanceDiagnose(base, timeout) {
    const host = base ? _instanceHost(base) : '';
    if (base && location.protocol === 'https:' && base.startsWith('http:') && !_instanceLoopback(base)) {
        throw { reason: 'mixed', host };
    }
    let res;
    try {
        res = await _instanceFetch(`${base}/.well-known/cowagent`, {}, timeout || 6000);
    } catch (err) {
        if (err && err.name === 'AbortError') throw { reason: 'timeout', host };
        if (!base) throw { reason: 'unreachable', host };
        // An answer the browser withholds (no CORS) only shows as an opaque response.
        const answered = await _instanceFetch(`${base}/`, { mode: 'no-cors' }, 4000).then(() => true, () => false);
        throw { reason: answered ? 'blocked' : 'unreachable', host };
    }
    const body = await res.json().catch(() => null);
    if (body && body.type === 'instance') return body;
    if (body && body.reason === 'instance_unreachable') throw { reason: 'unreachable', host };
    if (body && body.reason === 'wrong_device') throw { reason: 'wrong_device', host };
    if (res.status === 401 || res.status === 403 || (body && body.error === 'unauthorized')) throw { reason: 'login', host };
    if (res.status === 404 && base) {
        const old = await _instanceFetch(`${base}/auth/check`, {}, 4000)
            .then(r => r.json()).then(b => !!b && 'auth_required' in b).catch(() => false);
        if (old) throw { reason: 'outdated', host };
    }
    throw { reason: 'not_cowagent', host, status: res.status };
}

/** One sentence for a failed connection, from instanceDiagnose's reason. */
function instanceErrorText(err) {
    const reason = (err && err.reason) || 'unreachable';
    const key = `devices_err_${reason}`;
    const text = t(key) === key ? t('devices_err_unreachable') : t(key);
    return text.replace('{host}', (err && err.host) || '').replace('{status}', (err && err.status) || '');
}

/** True when the device at item.url is still the one that issued its token.
    Pairings from before devices had ids carry none and are taken on trust. */
function _instanceSameDevice(item, info) {
    return !item.instance_id || (!!info && info.id === item.instance_id);
}

// ---------------------------------------------------------------------------
// Routing worker
// ---------------------------------------------------------------------------

function _instanceTell(worker, message, timeout) {
    return new Promise(resolve => {
        if (!worker) return resolve(false);
        const channel = new MessageChannel();
        const timer = setTimeout(() => resolve(false), timeout || 2000);
        channel.port1.onmessage = () => { clearTimeout(timer); resolve(true); };
        worker.postMessage(message, [channel.port2]);
    });
}

async function _instanceRoute(item) {
    const cache = await caches.open(INSTANCE_CACHE);
    await cache.put(INSTANCE_CACHE_KEY, new Response(
        JSON.stringify({ url: item.url, token: item.token, id: item.instance_id || '' }),
        { headers: { 'Content-Type': 'application/json' } }));
    const reg = await navigator.serviceWorker.register(INSTANCE_WORKER, { scope: '/' });
    await navigator.serviceWorker.ready;
    await _instanceTell(reg.active || navigator.serviceWorker.controller, { type: 'config' });
}

async function _instanceUnroute() {
    if (!('serviceWorker' in navigator)) return;
    try { await caches.delete(INSTANCE_CACHE); } catch (_) {}
    const regs = await navigator.serviceWorker.getRegistrations().catch(() => []);
    for (const reg of regs) {
        const script = (reg.active || reg.waiting || reg.installing || {}).scriptURL || '';
        if (!script.endsWith(INSTANCE_WORKER)) continue;
        await _instanceTell(reg.active, { type: 'config' }, 1000);
        await reg.unregister().catch(() => {});
    }
}

function _instanceSwapScoped(fromId, toId) {
    const keys = [];
    for (let i = 0; i < localStorage.length; i++) {
        const key = localStorage.key(i);
        if (INSTANCE_SCOPED_KEYS.includes(key) || INSTANCE_SCOPED_PREFIXES.some(p => key.startsWith(p))) keys.push(key);
    }
    const saved = {};
    keys.forEach(key => { saved[key] = localStorage.getItem(key); localStorage.removeItem(key); });
    localStorage.setItem(`cow_instance_state:${fromId || 'local'}`, JSON.stringify(saved));
    const stash = `cow_instance_state:${toId || 'local'}`;
    try {
        const restore = JSON.parse(localStorage.getItem(stash) || '{}');
        Object.keys(restore).forEach(key => localStorage.setItem(key, restore[key]));
    } catch (_) {}
    localStorage.removeItem(stash);
}

/** Point the console at another device ('' for the one that served it) and reload. */
async function switchInstance(id) {
    closeInstanceMenu();
    const state = _instancesRead();
    id = id || '';
    if (state.active === id) return;
    const item = state.items.find(i => i.id === id);
    if (id && (!item || !item.token)) return openInstanceAdd(item ? { url: item.url, replaceId: item.id } : {});
    if (id && !instanceSupported()) return showInstanceProblem({ reason: 'insecure' });
    _instanceSwapScoped(state.active, id);
    state.active = id;
    _instancesWrite(state);
    try {
        if (item) await _instanceRoute(item);
        else await _instanceUnroute();
    } catch (_) {}
    sessionStorage.removeItem(INSTANCE_RELOAD_FLAG);
    location.reload();
}

function forgetInstance(id) {
    const state = _instancesRead();
    const item = state.items.find(i => i.id === id);
    if (!item) return;
    localStorage.removeItem(`cow_instance_state:${id}`);
    state.items = state.items.filter(i => i.id !== id);
    delete instanceStatus[id];
    if (state.active === id) {
        _instanceSwapScoped(id, '');
        localStorage.removeItem(`cow_instance_state:${id}`);
        state.active = '';
        _instancesWrite(state);
        _instanceUnroute().finally(() => location.reload());
        return;
    }
    _instancesWrite(state);
    _instancesChanged();
}

function _instancesChanged() {
    renderInstanceSwitcher();
    if (typeof renderDevicesPage === 'function') renderDevicesPage();
}

/** Give this browser's token back to the device, if the address still leads to it. */
async function _instanceRelease(item) {
    if (!item.token) return;
    try {
        const info = await instanceDiagnose(item.url, 4000);
        if (!_instanceSameDevice(item, info)) return;
        await fetch(`${item.url}/auth/logout`, { method: 'POST', headers: { Authorization: `Bearer ${item.token}` } });
    } catch (_) {}
}

function confirmForgetInstance(id) {
    const item = instanceList().find(i => i.id === id);
    if (!item) return;
    showConfirmDialog({
        title: t('devices_forget'),
        message: t('devices_forget_confirm').replace('{name}', item.name),
        okText: t('devices_forget'),
        tone: 'danger',
        onConfirm: () => {
            // Give the token up on the other side too; it may be gone already.
            _instanceRelease(item);
            forgetInstance(id);
        },
    });
}

/** Sign this browser out of the active remote device and come back here. */
function instanceSignOut() {
    const item = instanceActive();
    if (!item) return;
    showConfirmDialog({
        title: t('devices_disconnect'),
        message: t('devices_disconnect_confirm').replace('{name}', item.name).replace('{local}', instanceLocalName()),
        okText: t('devices_disconnect'),
        tone: 'danger',
        onConfirm: () => {
            fetch('/auth/logout', { method: 'POST' }).catch(() => {}).finally(() => forgetInstance(item.id));
        },
    });
}

/** Rename a device this browser connects to, on that device itself. */
async function renameInstance(id, name) {
    const item = instanceList().find(i => i.id === id);
    name = String(name || '').trim();
    if (!item || !name || name === item.name) return;
    try {
        const info = await instanceDiagnose(item.url, 5000);
        if (!_instanceSameDevice(item, info)) throw { reason: 'wrong_device', host: _instanceHost(item.url) };
        const res = await fetch(`${item.url}/api/device`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${item.token}` },
            body: JSON.stringify({ name }),
        });
        const data = await res.json();
        if (data.status !== 'success') throw { reason: 'refused' };
        _instanceUpdate(id, { name: data.instance.name });
    } catch (err) {
        const reason = err && err.reason;
        _shareToast(reason && reason !== 'refused' ? instanceErrorText(err)
            : t('devices_rename_failed').replace('{name}', item.name));
    }
    _instancesChanged();
}

// ---------------------------------------------------------------------------
// Boot
// ---------------------------------------------------------------------------

/** Resolves once the console's backend calls reach the active device. */
function instanceBoot() {
    const item = instanceActive();
    renderInstanceSwitcher();
    window.addEventListener('storage', (e) => {
        if (e.key !== INSTANCES_KEY) return;
        const now = instanceActive();
        if ((now ? now.id : '') !== (item ? item.id : '')) location.reload();
        else renderInstanceSwitcher();
    });
    if (!item) {
        // A worker left routing (another tab switched back, storage cleared)
        // must be gone before the first backend call.
        let routed = false;
        try { routed = !!(navigator.serviceWorker && navigator.serviceWorker.controller); } catch (_) {}
        return routed ? _instanceUnroute().catch(() => {}).then(() => null) : Promise.resolve(null);
    }
    if (!instanceSupported()) return Promise.reject({ reason: 'insecure' });
    if (!item.token) return Promise.reject({ reason: 'auth_lost' });
    return _instanceRoute(item).then(() => {
        if (!navigator.serviceWorker.controller) {
            // A hard reload bypasses the worker for the whole page.
            if (!sessionStorage.getItem(INSTANCE_RELOAD_FLAG)) {
                sessionStorage.setItem(INSTANCE_RELOAD_FLAG, '1');
                location.reload();
                return new Promise(() => {});
            }
            throw { reason: 'no_worker' };
        }
        sessionStorage.removeItem(INSTANCE_RELOAD_FLAG);
        return instanceDiagnose('', 8000);
    }, () => { throw { reason: 'no_worker' }; }).then(info => {
        const patch = {};
        if (info.version && info.version !== item.version) patch.version = info.version;
        // Paired before devices had ids: remember this one from now on.
        if (!item.instance_id && info.id) patch.instance_id = info.id;
        if (Object.keys(patch).length) {
            Object.assign(item, patch);
            _instanceUpdate(item.id, patch);
            if (patch.instance_id) _instanceRoute(item).catch(() => {});
        }
        instanceStatus[item.id] = 'online';
        return item;
    });
}

function _instanceUpdate(id, patch) {
    const state = _instancesRead();
    const found = state.items.find(i => i.id === id);
    if (!found) return;
    Object.assign(found, patch);
    _instancesWrite(state);
}

/** The active device no longer accepts this browser's token. */
function instanceAuthLost() {
    const item = instanceActive();
    if (!item) return;
    _instanceUpdate(item.id, { token: '' });
    showInstanceProblem({ reason: 'auth_lost' });
}

const INSTANCE_PROBLEMS = ['unreachable', 'auth_lost', 'insecure', 'no_worker', 'wrong_device'];

function showInstanceProblem(err) {
    const overlay = document.getElementById('instance-overlay');
    if (!overlay) return;
    const item = instanceActive();
    let reason = (err && err.reason) || 'unreachable';
    if (reason === 'timeout') reason = 'unreachable';
    const name = item ? item.name : '';
    const own = INSTANCE_PROBLEMS.includes(reason);
    const icons = { auth_lost: 'fa-user-lock', insecure: 'fa-shield-halved', no_worker: 'fa-plug-circle-xmark', wrong_device: 'fa-user-secret' };
    document.getElementById('instance-overlay-icon').className = `fas ${icons[reason] || (own ? 'fa-plug-circle-exclamation' : 'fa-circle-question')} text-xl text-amber-500`;
    document.getElementById('instance-overlay-title').textContent = t(`devices_problem_${own ? reason : 'other'}_title`).replace('{name}', name);
    document.getElementById('instance-overlay-message').textContent = own
        ? t(`devices_problem_${reason}`).replace('{name}', name)
        : instanceErrorText({ ...err, host: item ? _instanceHost(item.url) : '' });
    document.getElementById('instance-overlay-url').textContent = item ? item.url : '';
    document.getElementById('instance-overlay-retry').classList.toggle('hidden', ['auth_lost', 'insecure', 'wrong_device'].includes(reason));
    document.getElementById('instance-overlay-repair').classList.toggle('hidden', !['auth_lost', 'wrong_device'].includes(reason));
    overlay.dataset.reason = reason;
    overlay.classList.remove('hidden');
}

function instanceOverlayRetry() {
    sessionStorage.removeItem(INSTANCE_RELOAD_FLAG);
    location.reload();
}

function instanceOverlayRepair() {
    const item = instanceActive();
    const overlay = document.getElementById('instance-overlay');
    overlay.classList.add('hidden');
    openInstanceAdd(item ? { url: item.url, replaceId: item.id, problem: overlay.dataset.reason || 'auth_lost' } : {});
}

function instanceOverlayBack() {
    if (instanceActive()) return switchInstance('');
    document.getElementById('instance-overlay').classList.add('hidden');
}

// ---------------------------------------------------------------------------
// Sidebar switcher
// ---------------------------------------------------------------------------

/** Hidden from the menu editor; never while the console drives another device. */
function instanceSwitcherHidden() {
    return localStorage.getItem(INSTANCE_SWITCHER_KEY) === 'hidden';
}

function setInstanceSwitcherHidden(hidden) {
    if (hidden) localStorage.setItem(INSTANCE_SWITCHER_KEY, 'hidden');
    else localStorage.removeItem(INSTANCE_SWITCHER_KEY);
    document.documentElement.classList.toggle('device-switcher-off', hidden);
}

function renderInstanceSwitcher() {
    const label = document.getElementById('instance-switcher-label');
    if (!label) return;
    const active = instanceActive();
    const name = active ? active.name : instanceLocalName();
    label.textContent = name;
    document.getElementById('instance-switcher-sub').textContent = active
        ? t('devices_operating_remote') : t('devices_this_device');
    document.getElementById('instance-switcher-icon').className = `fas ${active ? 'fa-server' : 'fa-laptop'}`;
    const button = document.getElementById('instance-switcher');
    button.classList.toggle('is-remote', !!active);
    // A hover tip only on the rail, where the name itself is hidden.
    if (typeof isSidebarCollapsed === 'function' && isSidebarCollapsed()) button.setAttribute('data-tooltip', name);
    else button.removeAttribute('data-tooltip');
    document.documentElement.classList.toggle('device-remote', !!active);
    if (instanceMenuOpen) _renderInstanceMenu();
}

function _instanceDot(id) {
    const status = id ? (instanceStatus[id] || 'checking') : 'online';
    return `<span class="instance-dot is-${status === 'other' ? 'offline' : status}"></span>`;
}

/** Second line for a device this browser connects to. */
function _instanceSub(item) {
    if (!item.token) return t('devices_needs_pairing');
    if (instanceStatus[item.id] === 'other') return t('devices_status_other');
    return _instanceHost(item.url);
}

function _renderInstanceMenu() {
    const box = document.getElementById('instance-menu-list');
    if (!box) return;
    const active = instanceActive();
    const row = (id, name, sub, icon) => {
        const on = (active ? active.id : '') === id;
        return `<button type="button" class="instance-menu-item${on ? ' is-active' : ''}" role="menuitemradio" aria-checked="${on}"
                    onclick="switchInstance('${id}')">
                    <span class="instance-menu-icon"><i class="fas ${icon}"></i>${_instanceDot(id)}</span>
                    <span class="instance-menu-text"><span class="instance-menu-name">${escapeHtml(name)}</span>
                        <span class="instance-menu-sub">${escapeHtml(sub)}</span></span>
                    ${on ? '<i class="fas fa-check instance-menu-check"></i>' : ''}
                </button>`;
    };
    const remote = instanceList().map(i => row(i.id, i.name, _instanceSub(i), 'fa-server'));
    box.innerHTML = row('', instanceLocalName(), t('devices_this_device'), 'fa-laptop') + remote.join('');
}

/** Check whether each saved device answers, and is still the same device. */
function refreshInstanceStatus() {
    const active = instanceActive();
    instanceList().forEach(item => {
        if (active && item.id === active.id) { instanceStatus[item.id] = 'online'; return; }
        instanceStatus[item.id] = instanceStatus[item.id] || 'checking';
        instanceDiagnose(item.url, 4000)
            .then(info => { instanceStatus[item.id] = _instanceSameDevice(item, info) ? 'online' : 'other'; })
            .catch(() => { instanceStatus[item.id] = 'offline'; })
            .finally(() => {
                if (instanceMenuOpen) _renderInstanceMenu();
                if (typeof renderDevicesPage === 'function') renderDevicesPage();
            });
    });
}

function toggleInstanceMenu(e) {
    if (e) e.stopPropagation();
    if (instanceMenuOpen) return closeInstanceMenu();
    const menu = document.getElementById('instance-menu');
    const anchor = document.getElementById('instance-switcher');
    if (!menu || !anchor) return;
    instanceMenuOpen = true;
    _renderInstanceMenu();
    const rect = anchor.getBoundingClientRect();
    const rail = typeof isSidebarCollapsed === 'function' && isSidebarCollapsed() && window.innerWidth >= 1024;
    menu.style.left = `${rail ? rect.right + 8 : rect.left}px`;
    menu.style.top = `${rail ? rect.top : rect.bottom + 4}px`;
    menu.style.width = `${Math.max(rail ? 0 : rect.width, 248)}px`;
    menu.classList.remove('hidden');
    anchor.setAttribute('aria-expanded', 'true');
    refreshInstanceStatus();
    setTimeout(() => {
        document.addEventListener('click', _instanceMenuOutside);
        document.addEventListener('keydown', _instanceMenuEscape);
    });
}

function closeInstanceMenu() {
    instanceMenuOpen = false;
    document.getElementById('instance-menu')?.classList.add('hidden');
    document.getElementById('instance-switcher')?.setAttribute('aria-expanded', 'false');
    document.removeEventListener('click', _instanceMenuOutside);
    document.removeEventListener('keydown', _instanceMenuEscape);
}

function _instanceMenuOutside(e) {
    if (!document.getElementById('instance-menu')?.contains(e.target)) closeInstanceMenu();
}

function _instanceMenuEscape(e) {
    if (e.key === 'Escape') closeInstanceMenu();
}

function openDevicesSettings() {
    closeInstanceMenu();
    navigateTo('config', 'devices');
}

// ---------------------------------------------------------------------------
// Connecting to another device
// ---------------------------------------------------------------------------

/** cowagent://pair?v=1&c=<secret>&u=<url>... as { code, urls }, or null. */
function _instanceParseLink(text) {
    const value = String(text || '').trim();
    if (!/^cowagent:\/\/pair\?/i.test(value)) return null;
    const params = new URLSearchParams(value.slice(value.indexOf('?') + 1));
    const code = params.get('c') || '';
    const urls = params.getAll('u').map(u => _instanceNormalizeUrl(u)).filter(Boolean);
    return code && urls.length ? { code, urls } : null;
}

/** Addresses to try for what the user typed: as given, or http then https without a scheme. */
function _instanceCandidates(typed) {
    const text = String(typed || '').trim();
    if (/^https?:\/\//i.test(text)) return [_instanceNormalizeUrl(text)].filter(Boolean);
    return [_instanceNormalizeUrl(text, 'http'), _instanceNormalizeUrl(text, 'https')].filter(Boolean);
}

function openInstanceAdd(opts) {
    closeInstanceMenu();
    opts = opts || {};
    instanceAddState = { phase: 'form', error: '', replaceId: opts.replaceId || '', problem: opts.problem || '' };
    document.getElementById('instance-add-url').value = opts.url || '';
    document.getElementById('instance-add-code').value = '';
    document.getElementById('instance-add-insecure').classList.toggle('hidden', instanceSupported());
    _renderInstanceAdd();
    document.getElementById('instance-add-overlay').classList.remove('hidden');
    setTimeout(() => document.getElementById(opts.url ? 'instance-add-code' : 'instance-add-url').focus(), 50);
}

function closeInstanceAdd() {
    const s = instanceAddState;
    instanceAddState = null;
    document.getElementById('instance-add-overlay').classList.add('hidden');
    // Opened over a console that never finished starting: there is nothing
    // behind the dialog to go back to.
    if (s && s.problem) {
        if (s.phase === 'done') location.reload();
        else showInstanceProblem({ reason: s.problem });
    }
}

function onInstanceAddInput(e) {
    const link = _instanceParseLink(e.target.value);
    if (!link) return;
    document.getElementById('instance-add-url').value = link.urls[0];
    document.getElementById('instance-add-code').value = link.code;
    instanceAddState.link = link;
    _renderInstanceAdd();
}

function _renderInstanceAdd() {
    const s = instanceAddState;
    if (!s) return;
    const done = s.phase === 'done';
    document.getElementById('instance-add-form').classList.toggle('hidden', done);
    document.getElementById('instance-add-done').classList.toggle('hidden', !done);
    document.getElementById('instance-add-actions').classList.toggle('hidden', done);
    document.getElementById('instance-add-done-actions').classList.toggle('hidden', !done);
    const err = document.getElementById('instance-add-error');
    err.textContent = s.error || '';
    err.classList.toggle('hidden', !s.error);
    const btn = document.getElementById('instance-add-submit');
    const busy = s.phase === 'connecting';
    btn.disabled = busy || !instanceSupported();
    btn.innerHTML = busy
        ? `<i class="fas fa-spinner fa-spin mr-1.5"></i>${escapeHtml(t('devices_connecting'))}`
        : escapeHtml(t('devices_connect'));
    const linked = !!(s.link && document.getElementById('instance-add-code').value === s.link.code);
    document.getElementById('instance-add-code-row').classList.toggle('hidden', linked);
    document.getElementById('instance-add-linked').classList.toggle('hidden', !linked);
    if (done && s.instance) {
        document.getElementById('instance-add-done-name').textContent = s.instance.name;
        document.getElementById('instance-add-done-url').textContent = s.instance.url;
    }
}

// Which failure says the most about an address list: one that reached
// something beats one that reached nothing.
const INSTANCE_ERROR_RANK = ['unreachable', 'timeout', 'mixed', 'blocked', 'not_cowagent', 'login', 'outdated'];

async function submitInstanceAdd(e) {
    if (e) e.preventDefault();
    const s = instanceAddState;
    if (!s || s.phase === 'connecting') return;
    const typed = document.getElementById('instance-add-url').value;
    const code = document.getElementById('instance-add-code').value.trim();
    const linked = s.link && code === s.link.code;
    const own = _instanceCandidates(typed);
    const candidates = linked ? [...own, ...s.link.urls.filter(u => !own.includes(u))] : own;
    if (!candidates.length) return _instanceAddFail(t('devices_err_url'));
    if (!code) return _instanceAddFail(t('devices_err_code'));
    if (candidates.some(u => u === location.origin)) return _instanceAddFail(t('devices_err_self'));
    s.phase = 'connecting';
    s.error = '';
    _renderInstanceAdd();

    let url = '';
    let found = null;
    let failure = null;
    for (const candidate of candidates) {
        try {
            const info = await instanceDiagnose(candidate, 6000);
            url = candidate;
            found = info;
            break;
        } catch (err) {
            if (!failure || INSTANCE_ERROR_RANK.indexOf(err.reason) > INSTANCE_ERROR_RANK.indexOf(failure.reason)) failure = err;
        }
    }
    if (!url) return _instanceAddFail(instanceErrorText(failure));

    let data;
    try {
        const res = await fetch(`${url}/auth/pair`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ code, device: { platform: 'web', app_version: (APP_VERSION || '').replace(/^v/, '') } }),
        });
        data = await res.json();
    } catch (_) {
        return _instanceAddFail(instanceErrorText({ reason: 'unreachable', host: _instanceHost(url) }));
    }
    if (data.status !== 'success') {
        if (data.reason === 'locked') {
            const mins = Math.max(1, Math.ceil((data.retry_after || 60) / 60));
            return _instanceAddFail(t('devices_err_locked').replace('{n}', mins));
        }
        return _instanceAddFail(t('devices_err_code_invalid'));
    }

    const info = data.instance || {};
    const state = _instancesRead();
    let item = state.items.find(i => i.id === s.replaceId) || state.items.find(i => i.url === url);
    const patch = {
        url,
        token: data.token,
        name: info.name || _instanceHost(url),
        version: info.version || '',
        instance_id: info.id || found.id || '',
        managed: !!info.managed,
    };
    if (item) {
        delete item.custom_name;
        Object.assign(item, patch);
    } else {
        item = { id: _instanceId(), ...patch };
        state.items.push(item);
    }
    _instancesWrite(state);
    instanceStatus[item.id] = 'online';
    // The worker may still hold the old id for this device.
    if (state.active === item.id) await _instanceRoute(item).catch(() => {});
    s.phase = 'done';
    s.instance = item;
    _renderInstanceAdd();
    _instancesChanged();
}

function _instanceAddFail(message) {
    if (!instanceAddState) return;
    instanceAddState.phase = 'form';
    instanceAddState.error = message;
    _renderInstanceAdd();
}

function instanceAddSwitch() {
    const item = instanceAddState && instanceAddState.instance;
    instanceAddState = null;
    closeInstanceAdd();
    if (!item) return;
    const active = instanceActive();
    if (active && active.id === item.id) location.reload();
    else switchInstance(item.id);
}
