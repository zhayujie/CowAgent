/* Settings > Devices. A CowAgent device connects to other devices, and other
   devices connect to it; the page shows both, around the device the console
   drives:
   - this device: its name, which every client shows, and changing it;
   - devices this browser connects to (core/instances.js keeps that list);
   - devices that connect to this one: the one-time code that lets one more
     in, and the ones already allowed.
   A pairing code is always made on the device being connected to and
   entered on the one connecting. Classic script sharing the global scope. */

const DEVICE_ICONS = {
    ios: 'fab fa-apple', android: 'fab fa-android', harmony: 'fas fa-mobile-screen-button',
    desktop: 'fas fa-desktop', web: 'fas fa-globe', other: 'fas fa-circle-nodes',
};
// Off until the mobile app is published: hides the QR code and the app step.
const DEVICES_MOBILE_PAIRING = false;
const DEVICES_REFRESH_MS = 30000;
const DEVICES_SEP = '<span class="mx-1.5 text-slate-300 dark:text-slate-600">·</span>';
const DEVICES_BTN = 'px-3 py-1.5 rounded-lg border border-slate-200 dark:border-white/10 text-xs font-medium text-slate-600 dark:text-slate-300 cursor-pointer transition-colors';

let devicesList = [];
let devicesCurrent = '';
let devicesInstance = null;  // { id, name, version, managed }
let devicesNet = null;       // /api/integrations: public_url, lan_urls, password_set
let devicesLoadFailed = false;
let devicePairing = null;    // { pairing_id, code, link, urls, qr_image, expiresAt, expired }
let devicePairTimer = null;
let devicesRefreshTimer = null;
let devicesRenaming = '';    // 'self', an outgoing item id, or an incoming device id

function loadDevicesView() {
    _loadDevices();
    fetch('/api/integrations').then(r => r.json()).then(data => {
        if (data.status === 'success') devicesNet = data;
        renderDevicesPage();
    }).catch(() => {});
    renderDevicesPage();
    refreshInstanceStatus();
    clearInterval(devicesRefreshTimer);
    devicesRefreshTimer = setInterval(() => {
        if (document.getElementById('config-panel-devices')?.offsetParent === null) return stopDevicesView();
        if (!devicesRenaming) _loadDevices();
    }, DEVICES_REFRESH_MS);
}

function stopDevicesView() {
    clearInterval(devicesRefreshTimer);
    devicesRefreshTimer = null;
}

function _loadDevices() {
    return fetch('/api/devices').then(r => r.json()).then(data => {
        if (data.status !== 'success') throw new Error(data.message || '');
        devicesList = data.devices || [];
        devicesCurrent = data.current || '';
        devicesInstance = data.instance || null;
        devicesLoadFailed = false;
        if (devicesInstance) instanceNoteDevice(devicesInstance);
    }).catch(() => {
        devicesLoadFailed = true;
    }).finally(renderDevicesPage);
}

function renderDevicesPage() {
    if (!document.getElementById('config-panel-devices')) return;
    renderDevicesSelf();
    renderDevicesOut();
    renderDevicesIn();
}

/** What the device the console drives calls itself. */
function _devicesName() {
    const remote = instanceActive();
    return (devicesInstance && devicesInstance.name) || (remote ? remote.name : instanceLocalName());
}

function _devicesFocusRename(id) {
    if (devicesRenaming !== id) return;
    const input = document.getElementById('device-rename-input');
    if (input) { input.focus(); input.select(); }
}

function _devicesNameInput(value, onKey, onBlur) {
    return `<input id="device-rename-input" class="dev-name-input text-slate-800 dark:text-slate-100" maxlength="60" value="${escapeHtml(value)}"
                   onkeydown="${onKey}" onblur="${onBlur}">`;
}

function _devicesRenameKey(e, cancel) {
    if (e.key === 'Enter') { e.preventDefault(); e.target.blur(); }
    if (e.key === 'Escape') { e.stopPropagation(); devicesRenaming = ''; cancel(); }
}

function _devicesIconBtn(icon, tipKey, onclick) {
    return `<button class="dev-icon-btn" onclick="${onclick}" data-tooltip="${escapeHtml(t(tipKey))}" data-tip-float><i class="${icon}"></i></button>`;
}

// ---------------------------------------------------------------------------
// This device
// ---------------------------------------------------------------------------

function renderDevicesSelf() {
    const box = document.getElementById('devices-self');
    if (!box) return;
    const remote = instanceActive();
    const info = devicesInstance || {};
    const name = devicesRenaming === 'self'
        ? _devicesNameInput(_devicesName(), "onSelfRenameKey(event)", 'commitSelfRename()')
        : `<span class="truncate">${escapeHtml(_devicesName())}</span>`
            + (info.managed ? '' : _devicesIconBtn('fas fa-pen', 'devices_rename_device', 'startSelfRename()'));
    const sub = [
        t(remote ? 'devices_operating_remote' : 'devices_this_device'),
        remote ? _instanceHost(remote.url) : '',
        info.version ? `v${info.version}` : '',
    ].filter(Boolean).map(escapeHtml).join(DEVICES_SEP);
    box.classList.toggle('is-remote', !!remote);
    box.innerHTML = `
        <div class="dev-self-icon"><i class="fas ${remote ? 'fa-server' : 'fa-laptop'}"></i></div>
        <div class="min-w-0 flex-1">
            <div class="flex items-center gap-1 min-w-0 text-base font-semibold text-slate-800 dark:text-slate-100">${name}</div>
            <div class="mt-0.5 text-xs text-slate-400 dark:text-slate-500 truncate">${sub}</div>
        </div>
        ${remote ? `<button onclick="switchInstance('')" class="${DEVICES_BTN} flex-shrink-0 hover:bg-slate-50 dark:hover:bg-white/5">
            <i class="fas fa-laptop mr-1.5"></i>${escapeHtml(t('devices_back_local'))}</button>` : ''}`;
    _devicesFocusRename('self');
}

function startSelfRename() {
    devicesRenaming = 'self';
    renderDevicesSelf();
}

function onSelfRenameKey(e) {
    _devicesRenameKey(e, renderDevicesSelf);
}

function commitSelfRename() {
    if (devicesRenaming !== 'self') return;
    const input = document.getElementById('device-rename-input');
    const name = (input ? input.value : '').trim();
    devicesRenaming = '';
    if (!name || name === _devicesName()) return renderDevicesSelf();
    _renameSelf(name);
}

/** Rename the device the console drives, on that device. */
function _renameSelf(name) {
    if (devicesInstance) devicesInstance.name = name;
    renderDevicesSelf();
    fetch('/api/device', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name }),
    }).then(r => r.json()).then(data => {
        if (data.status !== 'success') throw new Error(data.message || '');
        devicesInstance = data.instance;
        instanceNoteDevice(data.instance);
    }).catch(() => _shareToast(t('devices_rename_failed').replace('{name}', name)))
        .finally(_loadDevices);
}

// ---------------------------------------------------------------------------
// Devices this browser connects to
// ---------------------------------------------------------------------------

function renderDevicesOut() {
    const box = document.getElementById('devices-out-list');
    if (!box) return;
    const items = instanceList();
    const active = instanceActive();
    const insecure = instanceSupported() ? ''
        : _devicesHint('fa-shield-halved', 'text-amber-600 dark:text-amber-400', t('devices_problem_insecure'));
    if (!items.length) {
        box.innerHTML = `${insecure}
            <div class="py-6 text-center text-sm text-slate-400 dark:text-slate-500">${escapeHtml(t('devices_out_empty'))}</div>`;
        return;
    }
    const row = (item) => {
        const id = item.id;
        const on = !!active && active.id === id;
        const st = instanceStatus[id] || 'checking';
        const status = !item.token ? 'offline' : on ? 'online' : st === 'other' ? 'offline' : st;
        const statusText = !item.token ? t('devices_needs_pairing') : t(`devices_status_${on ? 'online' : st}`);
        const sub = [_instanceHost(item.url), item.version ? `v${item.version}` : '', statusText]
            .filter(Boolean).map(escapeHtml).join(DEVICES_SEP);
        const name = devicesRenaming === id
            ? _devicesNameInput(item.name, `onOutRenameKey(event, '${id}')`, `commitOutRename('${id}')`)
            : `<span class="truncate">${escapeHtml(item.name)}</span>`;
        const needsPairing = !item.token || st === 'other';
        const action = on
            ? `<span class="dev-chip is-primary"><i class="fas fa-check text-[9px]"></i>${escapeHtml(t('devices_current'))}</span>`
            : needsPairing
                ? `<button onclick="openInstanceAdd({url: '${escapeHtml(item.url)}', replaceId: '${id}'})" class="${DEVICES_BTN} hover:bg-slate-50 dark:hover:bg-white/5">${escapeHtml(t('devices_repair'))}</button>`
                : `<button onclick="switchInstance('${id}')" class="${DEVICES_BTN} hover:border-primary-500 hover:text-primary-600 dark:hover:text-primary-400">${escapeHtml(t('devices_switch'))}</button>`;
        const tools = (item.token && !needsPairing && !item.managed ? _devicesIconBtn('fas fa-pen', 'devices_rename_device', `startOutRename('${id}')`) : '')
            + _devicesIconBtn('far fa-trash-can', 'devices_forget', `confirmForgetInstance('${id}')`);
        return `
            <div class="dev-row">
                <div class="dev-row-icon"><i class="fas fa-server"></i><span class="instance-dot is-${status}"></span></div>
                <div class="min-w-0 flex-1">
                    <div class="flex items-center gap-2 text-sm font-medium text-slate-700 dark:text-slate-200 min-w-0">${name}</div>
                    <div class="mt-0.5 text-xs ${st === 'other' && item.token ? 'text-amber-600 dark:text-amber-400' : 'text-slate-400 dark:text-slate-500'} truncate">${sub}</div>
                </div>
                <div class="dev-row-actions">${tools}</div>
                <div class="flex-shrink-0">${action}</div>
            </div>`;
    };
    box.innerHTML = `${insecure}<div class="divide-y divide-slate-100 dark:divide-white/5">${items.map(row).join('')}</div>`;
    _devicesFocusRename(devicesRenaming);
}

function startOutRename(id) {
    devicesRenaming = id;
    renderDevicesOut();
}

function onOutRenameKey(e, id) {
    _devicesRenameKey(e, renderDevicesOut);
}

function commitOutRename(id) {
    if (devicesRenaming !== id) return;
    const input = document.getElementById('device-rename-input');
    const name = (input ? input.value : '').trim();
    devicesRenaming = '';
    renderDevicesOut();
    const active = instanceActive();
    // The active device is the one this page talks to anyway.
    if (active && active.id === id) {
        if (name && name !== active.name) _renameSelf(name);
        return;
    }
    renameInstance(id, name);
}

// ---------------------------------------------------------------------------
// Devices that connect to this one
// ---------------------------------------------------------------------------

/** Host of the device the console drives, as _isLoopback expects it. */
function _devicesHost() {
    return new URL(instanceOrigin()).hostname.replace(/^\[|\]$/g, '');
}

function _devicesReachable() {
    const net = devicesNet;
    if (!net || (devicesInstance && devicesInstance.managed)) return true;
    let publicHost = '';
    try { publicHost = net.public_url ? new URL(net.public_url).hostname.replace(/^\[|\]$/g, '') : ''; } catch (e) {}
    return !!((publicHost && !_isLoopback(publicHost)) || (net.lan_urls || []).length || !_isLoopback(_devicesHost()));
}

function _devicesHint(icon, tone, text, extra) {
    return `<div class="mb-3 flex items-start gap-2 text-xs leading-relaxed ${tone} bg-slate-50 dark:bg-white/5 rounded-lg px-3 py-2">`
        + `<i class="fas ${icon} mt-0.5"></i><span>${escapeHtml(text)}${extra || ''}</span></div>`;
}

function _devicesHintAction(label, onclick) {
    return ` <button class="ml-1 text-primary-500 hover:underline cursor-pointer" onclick="${onclick}">${escapeHtml(label)}</button>`;
}

/** Why another device can't connect yet, or that it could but without a password. */
function _devicesNotice() {
    const muted = 'text-slate-500 dark:text-slate-400';
    const net = devicesNet;
    // Whoever runs a managed instance controls how it is reached.
    if (!net || (devicesInstance && devicesInstance.managed)) return '';
    if (!_devicesReachable()) {
        return _devicesHint('fa-circle-info', muted, t('devices_local_only'),
            _devicesHintAction(t('shares_go_settings'), "switchConfigTab('integrations')"));
    }
    if (!net.password_set) {
        return _devicesHint('fa-triangle-exclamation', 'text-amber-600 dark:text-amber-400', t('devices_no_password'),
            _devicesHintAction(t('shares_go_settings'), 'goToConsolePassword()'));
    }
    return '';
}

function renderDevicesIn() {
    const remote = instanceActive();
    const title = document.getElementById('devices-in-title');
    if (title) title.textContent = remote ? t('devices_in_title_remote').replace('{name}', _devicesName()) : t('devices_in_title');
    const btn = document.getElementById('devices-pair-btn');
    if (btn) {
        btn.disabled = !_devicesReachable();
        btn.onclick = devicePairing ? cancelDevicePairing : startDevicePairing;
        btn.className = `px-4 py-2 rounded-lg text-sm font-medium cursor-pointer transition-colors duration-150 disabled:opacity-50 disabled:cursor-not-allowed ${
            devicePairing ? 'border border-slate-200 dark:border-white/10 text-slate-600 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-white/5'
                          : 'bg-primary-500 hover:bg-primary-600 text-white'}`;
        btn.innerHTML = devicePairing
            ? `<i class="fas fa-xmark mr-1.5"></i>${escapeHtml(t('devices_cancel'))}`
            : `<i class="fas fa-qrcode mr-1.5"></i>${escapeHtml(t('devices_let_connect'))}`;
    }
    const notice = document.getElementById('devices-in-notice');
    if (notice) notice.innerHTML = _devicesNotice();
    renderDevicePairing();
    renderDevicesList();
}

// ---------------------------------------------------------------------------
// Pairing
// ---------------------------------------------------------------------------

function startDevicePairing() {
    const btn = document.getElementById('devices-pair-btn');
    if (btn) btn.disabled = true;
    const baseUrl = _isLoopback(_devicesHost()) ? '' : instanceOrigin();
    fetch('/api/pairing', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ base_url: baseUrl }),
    }).then(r => r.json()).then(data => {
        if (data.status !== 'success') {
            if (btn) btn.disabled = false;
            _shareToast(data.reason === 'local_only' ? t('devices_local_only') : (data.message || t('devices_pair_failed')));
            return;
        }
        devicePairing = { ...data, expiresAt: Date.now() + data.expires_in * 1000 };
        renderDevicesIn();
        _pollDevicePairing();
    }).catch(() => {
        if (btn) btn.disabled = false;
        _shareToast(t('devices_pair_failed'));
    });
}

function cancelDevicePairing() {
    devicePairing = null;
    clearTimeout(devicePairTimer);
    renderDevicesIn();
}

function _pollDevicePairing() {
    clearTimeout(devicePairTimer);
    if (!devicePairing) return;
    const id = devicePairing.pairing_id;
    devicePairTimer = setTimeout(() => {
        if (!devicePairing || devicePairing.pairing_id !== id) return;
        if (Date.now() >= devicePairing.expiresAt) {
            devicePairing.expired = true;
            return renderDevicePairing();
        }
        fetch(`/api/pairing/${id}`).then(r => r.json()).then(data => {
            if (!devicePairing || devicePairing.pairing_id !== id) return;
            if (data.state === 'paired') {
                const name = (data.device && data.device.name) || '';
                devicePairing = null;
                _shareToast(t('devices_paired').replace('{name}', name));
                renderDevicesIn();
                _loadDevices();
                return;
            }
            if (data.state === 'expired') {
                devicePairing.expired = true;
                return renderDevicePairing();
            }
            renderDevicePairing();
            _pollDevicePairing();
        }).catch(() => _pollDevicePairing());
    }, 2000);
}

function copyDevicePairLink() {
    if (!devicePairing || devicePairing.expired) return;
    copyToClipboard(devicePairing.link).then(() => _shareToast(t('devices_link_copied'))).catch(() => {});
}

function renderDevicePairing() {
    const box = document.getElementById('devices-pairing');
    if (!box) return;
    const p = devicePairing;
    if (!p) {
        box.innerHTML = '';
        box.classList.add('hidden');
        return;
    }
    const left = Math.max(0, Math.round((p.expiresAt - Date.now()) / 1000));
    const clock = `${Math.floor(left / 60)}:${String(left % 60).padStart(2, '0')}`;
    const qr = p.qr_image
        ? `<img src="${p.qr_image}" alt="QR" class="${p.expired ? 'opacity-20' : ''}">`
        : `<div class="w-full h-full rounded-xl bg-slate-100 dark:bg-white/5 flex items-center justify-center text-xs text-slate-400">${escapeHtml(t('devices_no_qr'))}</div>`;
    const urls = (p.urls || []).map(u => `<div class="font-mono text-xs text-slate-600 dark:text-slate-300 break-all">${escapeHtml(u)}</div>`).join('');
    const step = (n, text) => `<li class="flex gap-2.5"><span class="w-5 h-5 rounded-full bg-primary-500/10 text-primary-600 dark:text-primary-400 text-[11px] font-semibold flex items-center justify-center flex-shrink-0">${n}</span><span>${escapeHtml(text)}</span></li>`;
    const steps = DEVICES_MOBILE_PAIRING
        ? `<ol class="grid gap-2 text-sm text-slate-600 dark:text-slate-300">${step(1, t('devices_step_app'))}${step(2, t('devices_step_other'))}</ol>`
        : `<p class="text-sm text-slate-600 dark:text-slate-300">${escapeHtml(t('devices_step_other'))}</p>`;
    box.innerHTML = `
        <div class="flex flex-col md:flex-row gap-6 p-5 mb-3 rounded-xl border border-slate-200 dark:border-white/10 bg-slate-50/70 dark:bg-white/[0.03]">
            ${DEVICES_MOBILE_PAIRING ? `<div class="dev-pair-ring self-center md:self-start">
                ${qr}
                ${p.expired ? `<button onclick="startDevicePairing()" class="absolute inset-0 m-auto w-28 h-9 rounded-lg bg-primary-500 hover:bg-primary-600 text-white text-xs font-medium cursor-pointer shadow">${escapeHtml(t('devices_regenerate'))}</button>` : ''}
            </div>` : ''}
            <div class="min-w-0 flex-1 grid gap-4 content-start">
                ${steps}
                <div class="grid sm:grid-cols-2 gap-4">
                    <div>
                        <div class="text-xs text-slate-400 dark:text-slate-500 mb-1">${escapeHtml(t('devices_code'))}</div>
                        <div class="dev-code text-slate-800 dark:text-slate-100 ${p.expired ? 'line-through opacity-40' : ''}">${escapeHtml(p.code)}</div>
                    </div>
                    <div>
                        <div class="text-xs text-slate-400 dark:text-slate-500 mb-1">${escapeHtml(t('devices_address'))}</div>
                        <div class="grid gap-0.5">${urls}</div>
                    </div>
                </div>
                <div class="flex flex-wrap items-center gap-x-4 gap-y-2 text-xs">
                    <span class="inline-flex items-center gap-1.5 ${p.expired ? 'text-red-500' : 'text-slate-400 dark:text-slate-500'}">
                        <i class="far fa-clock"></i>${escapeHtml(p.expired ? t('devices_expired') : t('devices_expires_in').replace('{t}', clock))}
                    </span>
                    ${p.expired && !DEVICES_MOBILE_PAIRING ? `<button onclick="startDevicePairing()" class="inline-flex items-center gap-1.5 text-primary-500 hover:text-primary-600 cursor-pointer">
                        <i class="fas fa-rotate-right"></i>${escapeHtml(t('devices_regenerate'))}</button>` : ''}
                    ${p.expired ? '' : `<button onclick="copyDevicePairLink()" class="inline-flex items-center gap-1.5 text-primary-500 hover:text-primary-600 cursor-pointer">
                        <i class="fas fa-link"></i>${escapeHtml(t('devices_copy_link'))}</button>`}
                    ${p.expired ? '' : `<span class="inline-flex items-center gap-1.5 text-slate-400 dark:text-slate-500"><i class="fas fa-spinner fa-spin text-[10px]"></i>${escapeHtml(t('devices_waiting'))}</span>`}
                </div>
            </div>
        </div>`;
    box.classList.remove('hidden');
}

// ---------------------------------------------------------------------------
// Devices allowed in
// ---------------------------------------------------------------------------

function _deviceSeen(d) {
    if (d.online) return t('devices_online');
    const ts = d.last_seen_at || d.created_at;
    if (!ts) return '';
    const mins = Math.floor((Date.now() / 1000 - ts) / 60);
    if (mins < 10) return t('devices_seen_now');
    if (mins < 60) return t('devices_seen_minutes').replace('{n}', mins);
    if (mins < 60 * 24) return t('devices_seen_hours').replace('{n}', Math.floor(mins / 60));
    return t('devices_seen_days').replace('{n}', Math.floor(mins / 1440));
}

/** This browser is listed only on a remote device, where it can disconnect;
    on the device serving the page it signs out from the header. */
function _devicesShown() {
    return instanceActive() ? devicesList : devicesList.filter(d => d.id !== devicesCurrent);
}

function renderDevicesList() {
    const box = document.getElementById('devices-list');
    if (!box) return;
    const shown = _devicesShown();
    const count = document.getElementById('devices-count');
    if (count) count.textContent = shown.length ? `(${shown.length})` : '';
    if (devicesLoadFailed && !shown.length) {
        box.innerHTML = `<div class="py-6 text-center text-sm text-slate-400 dark:text-slate-500">${escapeHtml(t('devices_load_failed'))}</div>`;
        return;
    }
    if (!shown.length) {
        box.innerHTML = `<div class="py-6 text-center text-sm text-slate-400 dark:text-slate-500">${escapeHtml(t('devices_empty'))}</div>`;
        return;
    }
    const sorted = [...shown].sort((a, b) =>
        (b.id === devicesCurrent) - (a.id === devicesCurrent)
        || (b.online - a.online)
        || ((b.last_seen_at || b.created_at || 0) - (a.last_seen_at || a.created_at || 0)));
    box.innerHTML = `<div class="divide-y divide-slate-100 dark:divide-white/5">${sorted.map(_deviceRow).join('')}</div>`;
    _devicesFocusRename(devicesRenaming);
}

function _deviceRow(d) {
    const current = d.id === devicesCurrent;
    const icon = DEVICE_ICONS[d.platform] || DEVICE_ICONS.other;
    const via = d.via === 'password' ? t('devices_via_password') : t('devices_via_pairing');
    const meta = [
        via,
        d.app_version ? `v${d.app_version}` : '',
        d.origin ? t('devices_from_page').replace('{origin}', _instanceHost(d.origin)) : '',
        d.last_ip || '',
    ].filter(Boolean).map(escapeHtml).join(DEVICES_SEP);
    const seen = _deviceSeen(d);
    const name = devicesRenaming === d.id
        ? _devicesNameInput(d.name, `onDeviceRenameKey(event, '${d.id}')`, `commitDeviceRename('${d.id}')`)
        : `<span class="truncate">${escapeHtml(d.name)}</span>`;
    const badges = (current ? `<span class="dev-chip is-primary">${escapeHtml(t('devices_this'))}</span>` : '')
        + (d.online && !current ? `<span class="dev-chip is-online">${escapeHtml(t('devices_online'))}</span>` : '');
    return `
        <div class="dev-row">
            <div class="dev-row-icon"><i class="${icon}"></i>${d.online ? '<span class="instance-dot is-online"></span>' : ''}</div>
            <div class="min-w-0 flex-1">
                <div class="flex items-center gap-2 text-sm font-medium text-slate-700 dark:text-slate-200 min-w-0">${name}${badges}</div>
                <div class="mt-0.5 text-xs text-slate-400 dark:text-slate-500 truncate">${meta}</div>
            </div>
            <div class="hidden sm:block text-xs ${d.online ? 'text-emerald-600 dark:text-emerald-400' : 'text-slate-400 dark:text-slate-500'} whitespace-nowrap">${escapeHtml(seen)}</div>
            <div class="dev-row-actions">
                ${_devicesIconBtn('fas fa-pen', 'devices_rename_device', `startDeviceRename('${d.id}')`)}
                ${_devicesIconBtn(current ? 'fas fa-right-from-bracket' : 'far fa-trash-can',
                    current ? 'devices_disconnect' : 'devices_remove', `removeDevice('${d.id}')`)}
            </div>
        </div>`;
}

function startDeviceRename(id) {
    devicesRenaming = id;
    renderDevicesList();
}

function onDeviceRenameKey(e, id) {
    _devicesRenameKey(e, renderDevicesList);
}

function commitDeviceRename(id) {
    if (devicesRenaming !== id) return;
    const input = document.getElementById('device-rename-input');
    const name = (input ? input.value : '').trim();
    devicesRenaming = '';
    const device = devicesList.find(d => d.id === id);
    if (!device || !name || name === device.name) return renderDevicesList();
    device.name = name;
    renderDevicesList();
    fetch(`/api/devices/${id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name }),
    }).then(r => r.json()).then(data => {
        if (data.status === 'success' && data.device) device.name = data.device.name;
    }).catch(() => {}).finally(() => _loadDevices());
}

function removeDevice(id) {
    const device = devicesList.find(d => d.id === id);
    if (!device) return;
    if (id === devicesCurrent) return instanceSignOut();
    showConfirmDialog({
        title: t('devices_remove'),
        message: t('devices_remove_confirm').replace('{name}', device.name),
        okText: t('devices_remove'),
        tone: 'danger',
        onConfirm: () => {
            fetch(`/api/devices/${id}`, { method: 'DELETE' }).then(r => r.json()).then(data => {
                if (data.status === 'success') _loadDevices();
            }).catch(() => {});
        },
    });
}
