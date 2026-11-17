/* Instances this browser can switch the console to.

   The console page always comes from the server that served it; switching to
   another instance routes its backend calls there through /instance-sw.js,
   with the device token that instance issued when this browser was paired.
   The list lives in this browser only. Classic script sharing the global
   scope; only declarations run at load time. boot.js calls instanceBoot()
   before anything talks to the backend. */

const INSTANCES_KEY = 'cow_instances';
const INSTANCE_WORKER = '/instance-sw.js';
const INSTANCE_CACHE = 'cow-instance';
const INSTANCE_CACHE_KEY = '/__cow_instance__';
const INSTANCE_RELOAD_FLAG = 'cow_instance_reload';
// What the console remembers about the data of the instance it talks to.
// Each instance keeps its own copy, so switching back lands where it was.
const INSTANCE_SCOPED_KEYS = ['cow_active_agent', 'cow_default_agent', 'cow_memory_agent', 'cow_knowledge_agent',
    'cow_menu_cache', 'cow_collapsed_projects', 'cow_notified_run_ids', 'cow_manual_run_origin'];
const INSTANCE_SCOPED_PREFIXES = ['cow_session_id'];

const instanceStatus = {};   // id -> 'checking' | 'online' | 'offline'
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

/** The remote instance the console is switched to, or null on this one. */
function instanceActive() {
    const state = _instancesRead();
    return state.items.find(i => i.id === state.active) || null;
}

/** Origin of the instance answering the console's backend calls. */
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

/** The instance that served this page goes by its address: the browser has no other name for it. */
function instanceLocalName() {
    return location.host;
}

function _instanceNormalizeUrl(value) {
    let text = String(value || '').trim();
    if (!text) return '';
    if (!/^https?:\/\//i.test(text)) text = `http://${text}`;
    try {
        const url = new URL(text);
        return `${url.protocol}//${url.host}`;
    } catch (_) {
        return '';
    }
}

function _instanceId() {
    const bytes = new Uint8Array(6);
    crypto.getRandomValues(bytes);
    return 'i_' + Array.from(bytes, b => b.toString(16).padStart(2, '0')).join('');
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
    await cache.put(INSTANCE_CACHE_KEY, new Response(JSON.stringify({ url: item.url, token: item.token }),
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

/** Point the console at another instance ('' for this one) and reload. */
async function switchInstance(id) {
    const state = _instancesRead();
    id = id || '';
    if (state.active === id) return;
    const item = state.items.find(i => i.id === id);
    if (id && (!item || !item.token)) return openInstanceAdd(item ? { url: item.url } : {});
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
    renderInstanceManager();
    if (typeof renderDevicesScope === 'function') renderDevicesScope();
}

function confirmForgetInstance(id) {
    const item = instanceList().find(i => i.id === id);
    if (!item) return;
    showConfirmDialog({
        title: t('instances_remove'),
        message: t('instances_remove_confirm').replace('{name}', item.name),
        okText: t('instances_remove'),
        tone: 'danger',
        onConfirm: () => {
            // Give the device up on the other side too; it may be gone already.
            if (item.token) {
                fetch(`${item.url}/auth/logout`, { method: 'POST', headers: { Authorization: `Bearer ${item.token}` } })
                    .catch(() => {});
            }
            forgetInstance(id);
        },
    });
}

/** Sign this browser out of the active remote instance and come back here. */
function instanceSignOut() {
    const item = instanceActive();
    if (!item) return;
    showConfirmDialog({
        title: t('instances_sign_out'),
        message: t('instances_sign_out_confirm').replace('{name}', item.name),
        okText: t('instances_sign_out'),
        tone: 'danger',
        onConfirm: () => {
            fetch('/auth/logout', { method: 'POST' }).catch(() => {}).finally(() => forgetInstance(item.id));
        },
    });
}

// ---------------------------------------------------------------------------
// Boot
// ---------------------------------------------------------------------------

/** What answers at an address, without credentials. */
function instanceProbe(base, timeout) {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), timeout || 6000);
    return fetch(`${base || ''}/.well-known/cowagent`, { signal: ctrl.signal, cache: 'no-store' })
        .then(r => r.json().catch(() => ({})))
        .then(body => {
            if (body && body.reason === 'instance_unreachable') throw { reason: 'unreachable' };
            if (!body || body.type !== 'instance') throw { reason: 'not_instance' };
            return body;
        }, () => { throw { reason: 'unreachable' }; })
        .finally(() => clearTimeout(timer));
}

/** Resolves once the console's backend calls reach the active instance. */
function instanceBoot() {
    const item = instanceActive();
    renderInstanceSwitcher();
    window.addEventListener('storage', (e) => {
        if (e.key !== INSTANCES_KEY) return;
        const now = instanceActive();
        if ((now ? now.id : '') !== (item ? item.id : '')) location.reload();
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
        return instanceProbe('', 8000);
    }, () => { throw { reason: 'no_worker' }; }).then(info => {
        if (info.version && info.version !== item.version) {
            item.version = info.version;
            _instanceUpdate(item.id, { version: info.version });
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

/** The active instance no longer accepts this browser's token. */
function instanceAuthLost() {
    const item = instanceActive();
    if (!item) return;
    _instanceUpdate(item.id, { token: '' });
    showInstanceProblem({ reason: 'auth_lost' });
}

function showInstanceProblem(err) {
    const overlay = document.getElementById('instance-overlay');
    if (!overlay) return;
    const item = instanceActive();
    const reason = (err && err.reason) || 'unreachable';
    const name = item ? item.name : '';
    const icons = { auth_lost: 'fa-user-lock', insecure: 'fa-shield-halved', no_worker: 'fa-plug-circle-xmark', not_instance: 'fa-circle-question' };
    document.getElementById('instance-overlay-icon').className = `fas ${icons[reason] || 'fa-plug-circle-exclamation'} text-xl text-amber-500`;
    document.getElementById('instance-overlay-title').textContent = t(`instances_problem_${reason}_title`).replace('{name}', name);
    document.getElementById('instance-overlay-message').textContent = t(`instances_problem_${reason}`).replace('{name}', name);
    document.getElementById('instance-overlay-url').textContent = item ? item.url : '';
    document.getElementById('instance-overlay-retry').classList.toggle('hidden', reason === 'auth_lost' || reason === 'insecure');
    document.getElementById('instance-overlay-repair').classList.toggle('hidden', reason !== 'auth_lost');
    overlay.classList.remove('hidden');
}

function instanceOverlayRetry() {
    sessionStorage.removeItem(INSTANCE_RELOAD_FLAG);
    location.reload();
}

function instanceOverlayRepair() {
    const item = instanceActive();
    document.getElementById('instance-overlay').classList.add('hidden');
    openInstanceAdd(item ? { url: item.url, replaceId: item.id, problem: 'auth_lost' } : {});
}

function instanceOverlayBack() {
    if (instanceActive()) return switchInstance('');
    document.getElementById('instance-overlay').classList.add('hidden');
}

// ---------------------------------------------------------------------------
// Sidebar switcher
// ---------------------------------------------------------------------------

function renderInstanceSwitcher() {
    const label = document.getElementById('instance-switcher-label');
    if (!label) return;
    const active = instanceActive();
    label.textContent = active ? active.name : instanceLocalName();
    document.getElementById('instance-switcher')?.classList.toggle('is-remote', !!active);
    if (instanceMenuOpen) _renderInstanceMenu();
}

function _instanceDot(id) {
    const status = id ? (instanceStatus[id] || 'checking') : 'online';
    return `<span class="instance-dot is-${status}"></span>`;
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
    const remote = instanceList().map(i => row(i.id, i.name, i.token ? _instanceHost(i.url) : t('instances_needs_pairing'), 'fa-server'));
    box.innerHTML = row('', instanceLocalName(), t('instances_this_page'), 'fa-house') + remote.join('');
}

function _instanceHost(url) {
    try { return new URL(url).host; } catch (_) { return url; }
}

/** Check whether each saved instance answers, for the status dots. */
function refreshInstanceStatus() {
    const active = instanceActive();
    instanceList().forEach(item => {
        if (active && item.id === active.id) { instanceStatus[item.id] = 'online'; return; }
        instanceStatus[item.id] = instanceStatus[item.id] || 'checking';
        instanceProbe(item.url, 4000)
            .then(() => { instanceStatus[item.id] = 'online'; })
            .catch(() => { instanceStatus[item.id] = 'offline'; })
            .finally(() => {
                if (instanceMenuOpen) _renderInstanceMenu();
                renderInstanceManager();
            });
    });
}

function toggleInstanceMenu(e) {
    if (e) e.stopPropagation();
    if (instanceMenuOpen) return closeInstanceMenu();
    const menu = document.getElementById('instance-menu');
    const anchor = document.querySelector('#sidebar .sidebar-brand');
    if (!menu || !anchor) return;
    instanceMenuOpen = true;
    _renderInstanceMenu();
    const rect = anchor.getBoundingClientRect();
    menu.style.left = `${rect.left + 8}px`;
    menu.style.top = `${rect.bottom + 4}px`;
    menu.classList.remove('hidden');
    document.getElementById('instance-switcher')?.setAttribute('aria-expanded', 'true');
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

// ---------------------------------------------------------------------------
// Managing the list
// ---------------------------------------------------------------------------

let instanceManageRenaming = '';

function openInstanceManager() {
    closeInstanceMenu();
    instanceManageRenaming = '';
    document.getElementById('instance-manage-overlay')?.classList.remove('hidden');
    renderInstanceManager();
    refreshInstanceStatus();
    document.addEventListener('keydown', _instanceManagerEscape);
}

function closeInstanceManager() {
    instanceManageRenaming = '';
    document.getElementById('instance-manage-overlay')?.classList.add('hidden');
    document.removeEventListener('keydown', _instanceManagerEscape);
}

function _instanceManagerEscape(e) {
    if (e.key === 'Escape' && !instanceManageRenaming) closeInstanceManager();
}

function renderInstanceManager() {
    const overlay = document.getElementById('instance-manage-overlay');
    const box = document.getElementById('instance-manage-list');
    if (!overlay || !box || overlay.classList.contains('hidden')) return;
    const active = instanceActive();
    const items = instanceList();
    const sep = '<span class="mx-1.5 text-slate-300 dark:text-slate-600">·</span>';
    const btn = 'px-3 py-1.5 rounded-lg border border-slate-200 dark:border-white/10 text-xs font-medium text-slate-600 dark:text-slate-300 cursor-pointer transition-colors';
    const row = (item) => {
        const id = item ? item.id : '';
        const on = (active ? active.id : '') === id;
        const status = item ? (item.token ? (instanceStatus[id] || 'checking') : 'offline') : 'online';
        const statusText = !item ? '' : !item.token ? t('instances_needs_pairing')
            : status === 'online' ? t('instances_online') : status === 'offline' ? t('instances_offline') : t('instances_checking');
        const sub = (item ? [_instanceHost(item.url), item.version ? `v${item.version}` : '', statusText] : [t('instances_this_page')])
            .filter(Boolean).map(escapeHtml).join(sep);
        const name = item && instanceManageRenaming === id
            ? `<input id="instance-rename-input" class="dev-name-input text-slate-800 dark:text-slate-100" maxlength="60" value="${escapeHtml(item.name)}"
                      onkeydown="onInstanceRenameKey(event, '${id}')" onblur="commitInstanceRename('${id}')">`
            : `<span class="truncate">${escapeHtml(item ? item.name : instanceLocalName())}</span>`;
        const action = on
            ? `<span class="dev-chip is-primary"><i class="fas fa-check text-[9px]"></i>${escapeHtml(t('instances_current'))}</span>`
            : item && !item.token
                ? `<button onclick="closeInstanceManager(); openInstanceAdd({url: '${escapeHtml(item.url)}', replaceId: '${id}'})" class="${btn} hover:bg-slate-50 dark:hover:bg-white/5">${escapeHtml(t('instances_repair'))}</button>`
                : `<button onclick="switchInstance('${id}')" class="${btn} hover:border-primary-500 hover:text-primary-600 dark:hover:text-primary-400">${escapeHtml(t('instances_switch'))}</button>`;
        const tools = item ? `
                <button class="cfg-api-btn" onclick="startInstanceRename('${id}')" data-tooltip="${escapeHtml(t('instances_rename'))}" data-tip-float><i class="fas fa-pen text-xs"></i></button>
                <button class="cfg-api-btn" onclick="confirmForgetInstance('${id}')" data-tooltip="${escapeHtml(t('instances_remove'))}" data-tip-float><i class="far fa-trash-can text-xs"></i></button>` : '';
        return `
            <div class="dev-row${on ? ' is-active' : ''}">
                <div class="dev-row-icon"><i class="fas ${item ? 'fa-server' : 'fa-house'}"></i><span class="instance-dot is-${status}"></span></div>
                <div class="min-w-0 flex-1">
                    <div class="flex items-center gap-2 text-sm font-medium text-slate-700 dark:text-slate-200 min-w-0">${name}</div>
                    <div class="mt-0.5 text-xs text-slate-400 dark:text-slate-500 truncate">${sub}</div>
                </div>
                <div class="dev-row-actions${item ? '' : ' invisible'}">${tools}</div>
                <div class="flex-shrink-0">${action}</div>
            </div>`;
    };
    const insecure = instanceSupported() ? '' : `
        <div class="mb-3 flex items-start gap-2 text-xs text-amber-600 dark:text-amber-400 bg-amber-50 dark:bg-amber-900/20 rounded-lg px-3 py-2.5">
            <i class="fas fa-shield-halved mt-0.5"></i><span>${escapeHtml(t('instances_problem_insecure'))}</span></div>`;
    const empty = items.length ? '' : `
        <div class="mt-2 mb-3 rounded-xl border border-dashed border-slate-200 dark:border-white/10 px-4 py-5 text-center">
            <div class="text-sm text-slate-500 dark:text-slate-400">${escapeHtml(t('instances_empty_title'))}</div>
            <p class="mt-1 text-xs leading-relaxed text-slate-400 dark:text-slate-500">${escapeHtml(t('instances_empty'))}</p>
        </div>`;
    box.innerHTML = `${insecure}<div class="divide-y divide-slate-100 dark:divide-white/5">${row(null)}${items.map(row).join('')}</div>${empty}`;
    if (instanceManageRenaming) {
        const input = document.getElementById('instance-rename-input');
        if (input) { input.focus(); input.select(); }
    }
}

function startInstanceRename(id) {
    instanceManageRenaming = id;
    renderInstanceManager();
}

function onInstanceRenameKey(e, id) {
    if (e.key === 'Enter') { e.preventDefault(); commitInstanceRename(id); }
    if (e.key === 'Escape') { e.stopPropagation(); instanceManageRenaming = ''; renderInstanceManager(); }
}

function commitInstanceRename(id) {
    if (instanceManageRenaming !== id) return;
    const input = document.getElementById('instance-rename-input');
    const name = (input ? input.value : '').trim();
    instanceManageRenaming = '';
    if (name) _instanceUpdate(id, { name, custom_name: true });
    _instancesChanged();
}

// ---------------------------------------------------------------------------
// Adding an instance
// ---------------------------------------------------------------------------

/** cowagent://pair?v=1&c=<secret>&u=<url>... as { code, urls }, or null. */
function _instanceParseLink(text) {
    const value = String(text || '').trim();
    if (!/^cowagent:\/\/pair\?/i.test(value)) return null;
    const params = new URLSearchParams(value.slice(value.indexOf('?') + 1));
    const code = params.get('c') || '';
    const urls = params.getAll('u').map(_instanceNormalizeUrl).filter(Boolean);
    return code && urls.length ? { code, urls } : null;
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
        ? `<i class="fas fa-spinner fa-spin mr-1.5"></i>${escapeHtml(t('instances_connecting'))}`
        : escapeHtml(t('instances_connect'));
    const linked = !!(s.link && document.getElementById('instance-add-code').value === s.link.code);
    document.getElementById('instance-add-code-row').classList.toggle('hidden', linked);
    document.getElementById('instance-add-linked').classList.toggle('hidden', !linked);
    if (done && s.instance) {
        document.getElementById('instance-add-done-name').textContent = s.instance.name;
        document.getElementById('instance-add-done-url').textContent = s.instance.url;
    }
}

async function submitInstanceAdd(e) {
    if (e) e.preventDefault();
    const s = instanceAddState;
    if (!s || s.phase === 'connecting') return;
    const typedUrl = _instanceNormalizeUrl(document.getElementById('instance-add-url').value);
    const code = document.getElementById('instance-add-code').value.trim();
    const linked = s.link && code === s.link.code;
    const candidates = linked ? [typedUrl, ...s.link.urls.filter(u => u !== typedUrl)] : [typedUrl];
    if (!typedUrl) return _instanceAddFail(t('instances_err_url'));
    if (!code) return _instanceAddFail(t('instances_err_code'));
    if (candidates.some(u => u === location.origin)) return _instanceAddFail(t('instances_err_self'));
    s.phase = 'connecting';
    s.error = '';
    _renderInstanceAdd();

    let url = '';
    let probeError = null;
    for (const candidate of candidates) {
        try {
            await instanceProbe(candidate, 6000);
            url = candidate;
            break;
        } catch (err) {
            probeError = probeError && probeError.reason === 'not_instance' ? probeError : err;
        }
    }
    if (!url) {
        return _instanceAddFail(t(probeError && probeError.reason === 'not_instance'
            ? 'instances_err_not_instance' : 'instances_err_unreachable'));
    }

    let data;
    try {
        const res = await fetch(`${url}/auth/pair`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ code, device: { platform: 'web', app_version: (APP_VERSION || '').replace(/^v/, '') } }),
        });
        data = await res.json();
    } catch (_) {
        return _instanceAddFail(t('instances_err_unreachable'));
    }
    if (data.status !== 'success') {
        if (data.reason === 'locked') {
            const mins = Math.max(1, Math.ceil((data.retry_after || 60) / 60));
            return _instanceAddFail(t('instances_err_locked').replace('{n}', mins));
        }
        return _instanceAddFail(t('instances_err_code_invalid'));
    }

    const info = data.instance || {};
    const state = _instancesRead();
    let item = state.items.find(i => i.id === s.replaceId) || state.items.find(i => i.url === url);
    const patch = {
        url,
        token: data.token,
        name: (item && item.custom_name) ? item.name : (info.name || _instanceHost(url)),
        version: info.version || '',
    };
    if (item) {
        Object.assign(item, patch);
    } else {
        item = { id: _instanceId(), ...patch };
        state.items.push(item);
    }
    _instancesWrite(state);
    instanceStatus[item.id] = 'online';
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
