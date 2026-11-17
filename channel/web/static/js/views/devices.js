/* Settings > Devices, all about the instance the console drives: a line
   naming it, connecting one more device to it (the one-time code), and the
   devices that may reach it. Which instance this browser drives is the
   switcher's business (core/instances.js). Classic script sharing the global
   scope. */

const DEVICE_ICONS = {
    ios: 'fab fa-apple', android: 'fab fa-android', harmony: 'fas fa-mobile-screen-button',
    desktop: 'fas fa-desktop', web: 'fas fa-globe', other: 'fas fa-circle-nodes',
};
const DEVICES_REFRESH_MS = 30000;

let devicesList = [];
let devicesCurrent = '';
let devicesInstance = null;  // { name, version }
let devicesNet = null;       // /api/integrations: public_url, lan_urls, password_set
let devicesLoadFailed = false;
let devicePairing = null;    // { pairing_id, code, link, urls, qr_image, expiresAt, expired }
let devicePairTimer = null;
let devicesRefreshTimer = null;
let devicesRenaming = '';

function loadDevicesView() {
    _loadDevices();
    fetch('/api/integrations').then(r => r.json()).then(data => {
        if (data.status === 'success') devicesNet = data;
        renderDevicesInstance();
    }).catch(() => {});
    renderDevicesInstance();
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
    }).catch(() => {
        devicesLoadFailed = true;
    }).finally(() => {
        renderDevicesInstance();
        renderDevicesList();
    });
}

// ---------------------------------------------------------------------------
// This instance
// ---------------------------------------------------------------------------

/** Host of the instance the console drives, as _isLoopback expects it. */
function _devicesHost() {
    return new URL(instanceOrigin()).hostname.replace(/^\[|\]$/g, '');
}

/** Why another device can't join yet, or that it could but without a password. */
function _devicesNotice() {
    const net = devicesNet;
    if (!net) return '';
    if (!_devicesReachable()) return _devicesHint('fa-circle-info', 'text-slate-500 dark:text-slate-400', t('devices_local_only'));
    if (!net.password_set) return _devicesHint('fa-triangle-exclamation', 'text-amber-600 dark:text-amber-400', t('devices_no_password'), true);
    return '';
}

function _devicesReachable() {
    const net = devicesNet;
    if (!net) return true;
    return !!(net.public_url || (net.lan_urls || []).length || !_isLoopback(_devicesHost()));
}

function _devicesHint(icon, tone, text, passwordLink) {
    return `<div class="flex items-start gap-2 text-xs ${tone} bg-slate-50 dark:bg-white/5 rounded-lg px-3 py-2.5">`
        + `<i class="fas ${icon} mt-0.5"></i><span>${escapeHtml(text)}`
        + (passwordLink ? ` <button class="ml-1 text-primary-500 hover:underline cursor-pointer" onclick="goToConsolePassword()">${escapeHtml(t('shares_go_settings'))}</button>` : '')
        + '</span></div>';
}

/** What the instance the console drives calls itself. */
function _devicesName() {
    const remote = instanceActive();
    return (devicesInstance && devicesInstance.name) || (remote ? remote.name : instanceLocalName());
}

function renderDevicesInstance() {
    renderDevicesScope();
    renderDevicesConnect();
    const desc = document.getElementById('devices-connected-desc');
    if (desc) desc.textContent = t('devices_connected_desc').replace('{name}', _devicesName());
}

/** The line naming the instance everything on this page applies to. */
function renderDevicesScope() {
    const box = document.getElementById('devices-scope');
    if (!box) return;
    const remote = instanceActive();
    const info = devicesInstance || {};
    const online = devicesList.filter(d => d.online).length;
    const chips = [
        remote ? `<span class="dev-chip is-primary">${escapeHtml(t('devices_instance_remote'))}</span>` : '',
        info.version ? `<span class="dev-chip">v${escapeHtml(info.version)}</span>` : '',
        online ? `<span class="dev-chip is-online"><span class="instance-dot is-online" style="width:6px;height:6px"></span>${escapeHtml(t('devices_online_count').replace('{n}', online))}</span>` : '',
    ].join('');
    box.innerHTML = `
        <div class="dev-scope-icon"><i class="fas ${remote ? 'fa-server' : 'fa-house'}"></i></div>
        <div class="min-w-0 flex-1">
            <div class="text-[11px] leading-4 text-slate-400 dark:text-slate-500">${escapeHtml(t('devices_scope_label'))}</div>
            <div class="flex flex-wrap items-center gap-x-2 gap-y-1 min-w-0">
                <span class="text-sm font-semibold text-slate-800 dark:text-slate-100 truncate">${escapeHtml(_devicesName())}</span>
                <span class="font-mono text-xs text-slate-400 dark:text-slate-500 truncate">${escapeHtml(_instanceHost(instanceOrigin()))}</span>
                ${chips}
            </div>
        </div>
        <button onclick="openInstanceManager()"
                class="px-3 py-1.5 rounded-lg border border-slate-200 dark:border-white/10 text-xs font-medium text-slate-600 dark:text-slate-300 flex-shrink-0
                       hover:bg-slate-50 dark:hover:bg-white/5 cursor-pointer transition-colors duration-150">
            <i class="fas fa-arrow-right-arrow-left mr-1.5"></i>${escapeHtml(t('devices_scope_switch'))}
        </button>`;
}

function renderDevicesConnect() {
    const box = document.getElementById('devices-connect-card');
    if (!box) return;
    const notice = _devicesNotice();
    const method = (icon, title, text) => `
        <div class="dev-method">
            <div class="dev-method-icon"><i class="fas ${icon}"></i></div>
            <div class="min-w-0">
                <div class="text-sm font-medium text-slate-700 dark:text-slate-200">${escapeHtml(title)}</div>
                <div class="mt-0.5 text-xs leading-relaxed text-slate-400 dark:text-slate-500">${escapeHtml(text)}</div>
            </div>
        </div>`;
    const cli = escapeHtml(t('devices_cli_hint')).replace('{cmd}', '<code class="dev-cmd">cow pair</code>');
    box.innerHTML = `
        <div class="flex flex-col sm:flex-row sm:items-center gap-3">
            <div class="flex items-center gap-3 min-w-0 flex-1">
                <div class="w-9 h-9 rounded-lg bg-primary-50 dark:bg-primary-900/20 flex items-center justify-center flex-shrink-0">
                    <i class="fas fa-qrcode text-primary-500 text-sm"></i>
                </div>
                <div class="min-w-0">
                    <h3 class="font-semibold text-slate-800 dark:text-slate-100">${escapeHtml(t('devices_connect_title'))}</h3>
                    <p class="text-xs text-slate-400 dark:text-slate-500 mt-0.5">${escapeHtml(t('devices_connect_desc').replace('{name}', _devicesName()))}</p>
                </div>
            </div>
            <button id="devices-pair-btn" onclick="${devicePairing ? 'cancelDevicePairing()' : 'startDevicePairing()'}"
                    ${_devicesReachable() ? '' : 'disabled'}
                    class="self-start sm:self-center px-4 py-2 rounded-lg text-sm font-medium flex-shrink-0 cursor-pointer transition-colors duration-150
                           disabled:opacity-50 disabled:cursor-not-allowed
                           ${devicePairing ? 'border border-slate-200 dark:border-white/10 text-slate-600 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-white/5'
                                           : 'bg-primary-500 hover:bg-primary-600 text-white'}">
                ${devicePairing
                    ? `<i class="fas fa-xmark mr-1.5"></i>${escapeHtml(t('devices_cancel'))}`
                    : `<i class="fas fa-qrcode mr-1.5"></i>${escapeHtml(t('devices_add'))}`}
            </button>
        </div>
        ${notice ? `<div class="mt-4">${notice}</div>` : ''}
        <div id="devices-pairing" class="${devicePairing ? 'mt-5' : 'hidden'}"></div>
        ${devicePairing ? '' : `
        <div class="mt-5 grid sm:grid-cols-2 gap-3">
            ${method('fa-mobile-screen-button', t('devices_method_app_title'), t('devices_method_app'))}
            ${method('fa-desktop', t('devices_method_other_title'), t('devices_method_other'))}
        </div>
        <p class="mt-4 flex items-center gap-2 text-xs text-slate-400 dark:text-slate-500">
            <i class="fas fa-terminal text-[10px]"></i><span>${cli}</span>
        </p>`}`;
    renderDevicePairing();
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
        renderDevicesInstance();
        _pollDevicePairing();
    }).catch(() => {
        if (btn) btn.disabled = false;
        _shareToast(t('devices_pair_failed'));
    });
}

function cancelDevicePairing() {
    devicePairing = null;
    clearTimeout(devicePairTimer);
    renderDevicesInstance();
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
                renderDevicesInstance();
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
    box.innerHTML = `
        <div class="flex flex-col md:flex-row gap-6 p-5 rounded-xl border border-slate-200 dark:border-white/10 bg-slate-50/70 dark:bg-white/[0.03]">
            <div class="dev-pair-ring self-center md:self-start">
                ${qr}
                ${p.expired ? `<button onclick="startDevicePairing()" class="absolute inset-0 m-auto w-28 h-9 rounded-lg bg-primary-500 hover:bg-primary-600 text-white text-xs font-medium cursor-pointer shadow">${escapeHtml(t('devices_regenerate'))}</button>` : ''}
            </div>
            <div class="min-w-0 flex-1 grid gap-4 content-start">
                <ol class="grid gap-2 text-sm text-slate-600 dark:text-slate-300">
                    ${step(1, t('devices_step_app'))}
                    ${step(2, t('devices_step_other'))}
                </ol>
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
                    ${p.expired ? '' : `<button onclick="copyDevicePairLink()" class="inline-flex items-center gap-1.5 text-primary-500 hover:text-primary-600 cursor-pointer">
                        <i class="fas fa-link"></i>${escapeHtml(t('devices_copy_link'))}</button>`}
                    ${p.expired ? '' : `<span class="inline-flex items-center gap-1.5 text-slate-400 dark:text-slate-500"><i class="fas fa-spinner fa-spin text-[10px]"></i>${escapeHtml(t('devices_waiting'))}</span>`}
                </div>
            </div>
        </div>`;
    box.classList.remove('hidden');
}

// ---------------------------------------------------------------------------
// Signed-in devices
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

function renderDevicesList() {
    const box = document.getElementById('devices-list');
    if (!box) return;
    const count = document.getElementById('devices-count');
    if (count) count.textContent = devicesList.length ? `(${devicesList.length})` : '';
    document.getElementById('devices-revoke-others')?.classList.toggle('hidden',
        !(devicesCurrent && devicesList.some(d => d.id !== devicesCurrent)));
    if (devicesLoadFailed && !devicesList.length) {
        box.innerHTML = `<div class="py-6 text-center text-sm text-slate-400 dark:text-slate-500">${escapeHtml(t('devices_load_failed'))}</div>`;
        return;
    }
    if (!devicesList.length) {
        box.innerHTML = `
            <div class="py-8 text-center">
                <div class="w-11 h-11 mx-auto rounded-xl bg-slate-100 dark:bg-white/5 flex items-center justify-center mb-3">
                    <i class="fas fa-mobile-screen-button text-slate-400"></i>
                </div>
                <p class="text-sm text-slate-500 dark:text-slate-400">${escapeHtml(t('devices_empty'))}</p>
                <p class="text-xs text-slate-400 dark:text-slate-500 mt-1">${escapeHtml(t('devices_empty_hint'))}</p>
            </div>`;
        return;
    }
    const sorted = [...devicesList].sort((a, b) =>
        (b.id === devicesCurrent) - (a.id === devicesCurrent)
        || (b.online - a.online)
        || ((b.last_seen_at || b.created_at || 0) - (a.last_seen_at || a.created_at || 0)));
    box.innerHTML = `<div class="divide-y divide-slate-100 dark:divide-white/5">${sorted.map(_deviceRow).join('')}</div>`;
    if (devicesRenaming) {
        const input = document.getElementById('device-rename-input');
        if (input) { input.focus(); input.select(); }
    }
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
    ].filter(Boolean).map(escapeHtml).join('<span class="mx-1.5 text-slate-300 dark:text-slate-600">·</span>');
    const seen = _deviceSeen(d);
    const name = devicesRenaming === d.id
        ? `<input id="device-rename-input" class="dev-name-input text-slate-800 dark:text-slate-100" maxlength="60" value="${escapeHtml(d.name)}"
                  onkeydown="onDeviceRenameKey(event, '${d.id}')" onblur="commitDeviceRename('${d.id}')">`
        : `<span class="truncate">${escapeHtml(d.name)}</span>`;
    const badges = (current ? `<span class="dev-chip is-primary">${escapeHtml(t('devices_this'))}</span>` : '')
        + (d.online && !current ? `<span class="dev-chip is-online">${escapeHtml(t('devices_online'))}</span>` : '');
    return `
        <div class="dev-row${current ? ' is-current' : ''}">
            <div class="dev-row-icon"><i class="${icon}"></i>${d.online ? '<span class="instance-dot is-online"></span>' : ''}</div>
            <div class="min-w-0 flex-1">
                <div class="flex items-center gap-2 text-sm font-medium text-slate-700 dark:text-slate-200 min-w-0">${name}${badges}</div>
                <div class="mt-0.5 text-xs text-slate-400 dark:text-slate-500 truncate">${meta}</div>
            </div>
            <div class="hidden sm:block text-xs ${d.online ? 'text-emerald-600 dark:text-emerald-400' : 'text-slate-400 dark:text-slate-500'} whitespace-nowrap">${escapeHtml(seen)}</div>
            <div class="dev-row-actions">
                <button class="cfg-api-btn" onclick="startDeviceRename('${d.id}')" data-tooltip="${escapeHtml(t('devices_rename'))}" data-tip-float><i class="fas fa-pen text-xs"></i></button>
                <button class="cfg-api-btn" onclick="removeDevice('${d.id}')" data-tooltip="${escapeHtml(t(current ? 'devices_sign_out_here' : 'devices_remove'))}" data-tip-float>
                    <i class="${current ? 'fas fa-right-from-bracket' : 'far fa-trash-can'} text-xs"></i></button>
            </div>
        </div>`;
}

function startDeviceRename(id) {
    devicesRenaming = id;
    renderDevicesList();
}

function onDeviceRenameKey(e, id) {
    if (e.key === 'Enter') { e.preventDefault(); e.target.blur(); }
    if (e.key === 'Escape') { devicesRenaming = ''; renderDevicesList(); }
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
    const current = id === devicesCurrent;
    showConfirmDialog({
        title: t(current ? 'devices_sign_out_here' : 'devices_remove'),
        message: t(current ? 'devices_sign_out_here_confirm' : 'devices_remove_confirm').replace('{name}', device.name),
        okText: t(current ? 'devices_sign_out_here' : 'devices_remove'),
        tone: 'danger',
        onConfirm: () => {
            if (current) return handleLogout();
            fetch(`/api/devices/${id}`, { method: 'DELETE' }).then(r => r.json()).then(data => {
                if (data.status === 'success') _loadDevices();
            }).catch(() => {});
        },
    });
}

function revokeOtherDevices() {
    const others = devicesList.filter(d => d.id !== devicesCurrent).length;
    if (!others) return;
    showConfirmDialog({
        title: t('devices_revoke_others'),
        message: t('devices_revoke_others_confirm').replace('{n}', others),
        okText: t('devices_revoke_others'),
        tone: 'danger',
        onConfirm: () => {
            fetch('/api/devices/revoke_others', { method: 'POST' }).then(r => r.json()).then(data => {
                if (data.status === 'success') _shareToast(t('devices_revoked').replace('{n}', data.removed || 0));
            }).catch(() => {}).finally(() => _loadDevices());
        },
    });
}
