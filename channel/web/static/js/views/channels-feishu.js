/* Feishu one-click app registration.
   Split out of console.js. These are classic scripts sharing one global
   scope; see channel/web/README.md before changing the load order. */

// =====================================================================
// Feishu One-click App Registration (lark-oapi register_app)
// =====================================================================
let _feishuRegisterPollTimer = null;
let _feishuRegisterFlow = null;

function _feishuHasCreds(ch) {
    if (!ch || !ch.fields) return false;
    const idField = ch.fields.find(f => f.key === 'feishu_app_id');
    const secretField = ch.fields.find(f => f.key === 'feishu_app_secret');
    return !!(idField && idField.value && secretField && secretField.value);
}

function buildFeishuPanel(ch, isActive) {
    const scanLabel = t('feishu_mode_scan');
    const manualLabel = t('feishu_mode_manual');
    // 已有凭据时默认进入手动 Tab，方便修改；否则推荐扫码
    const defaultMode = _feishuHasCreds(ch) ? 'manual' : 'scan';
    const activeAttr = isActive ? 'data-active="1"' : '';
    // Every DOM id in the panel is suffixed with the instance id so two feishu
    // cards on screen at once never collide: without this, getElementById()
    // always resolves to the first card, so the second card is dead and its tab
    // clicks drive the first one. The Add panel (no instance yet) uses the bare
    // "feishu" suffix; an active instance card uses its real instance id.
    const iid = (isActive && ch && ch.iid) ? ch.iid : 'feishu';
    return `
        <div id="feishu-panel-${iid}" class="feishu-panel" data-default-mode="${defaultMode}" data-instance-id="${escapeHtml(ch?.instance_id || '')}" ${activeAttr}>
            <div class="flex items-center justify-center gap-1 mb-5 bg-slate-100 dark:bg-white/5 rounded-lg p-1">
                <button id="feishu-tab-scan-${iid}" onclick="switchFeishuMode('${iid}', 'scan')"
                    class="flex-1 px-3 py-1.5 rounded-md text-xs font-medium transition-colors
                           bg-white dark:bg-slate-700 text-slate-800 dark:text-slate-100 shadow-sm">
                    ${scanLabel}
                </button>
                <button id="feishu-tab-manual-${iid}" onclick="switchFeishuMode('${iid}', 'manual')"
                    class="flex-1 px-3 py-1.5 rounded-md text-xs font-medium transition-colors
                           text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:hover:text-slate-200">
                    ${manualLabel}
                </button>
            </div>
            <div id="feishu-mode-content-${iid}"></div>
        </div>`;
}

function switchFeishuMode(iid, mode) {
    // Back-compat: old call sites passed only the mode. Treat a bare mode as the
    // Add panel's "feishu" instance.
    if (mode === undefined && (iid === 'scan' || iid === 'manual')) {
        mode = iid;
        iid = 'feishu';
    }
    iid = iid || 'feishu';
    const panel = document.getElementById(`feishu-panel-${iid}`);
    const scanTab = document.getElementById(`feishu-tab-scan-${iid}`);
    const manualTab = document.getElementById(`feishu-tab-manual-${iid}`);
    const content = document.getElementById(`feishu-mode-content-${iid}`);
    if (!scanTab || !manualTab || !content) return;

    // 已激活通道卡片中嵌入此 panel 时，没有 add-channel-actions（保存按钮就近渲染）
    const isActive = panel && panel.dataset.active === '1';
    const instanceId = panel?.dataset.instanceId || '';
    const actions = isActive ? null : document.getElementById('add-channel-actions');
    const scanStatusId = `feishu-scan-status-${iid}`;

    const activeClasses = 'bg-white dark:bg-slate-700 text-slate-800 dark:text-slate-100 shadow-sm';
    const inactiveClasses = 'text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:hover:text-slate-200';

    stopFeishuRegisterPoll();

    if (mode === 'scan') {
        scanTab.className = `flex-1 px-3 py-1.5 rounded-md text-xs font-medium transition-colors ${activeClasses}`;
        manualTab.className = `flex-1 px-3 py-1.5 rounded-md text-xs font-medium transition-colors ${inactiveClasses}`;
        if (actions) actions.classList.add('hidden');
        const desc = isActive ? t('feishu_scan_reconnect') : t('feishu_scan_desc');
        content.innerHTML = `
            <div class="flex flex-col items-center py-4">
                <p class="text-sm text-slate-600 dark:text-slate-300 mb-3 text-center">${desc}</p>
                <button onclick="startFeishuRegister('${scanStatusId}')"
                    class="mt-2 px-6 py-2.5 rounded-lg bg-emerald-500 hover:bg-emerald-600 text-white text-sm font-medium
                           cursor-pointer transition-colors duration-150">
                    <i class="fas fa-qrcode mr-2"></i>${isActive ? t('feishu_scan_reconnect') : t('feishu_scan_btn')}
                </button>
                ${isActive ? `<button class="mt-3 text-sm text-primary-600" title="${escapeHtml(t('feishu_scan_replace_desc'))}"
                    onclick="startFeishuRegister('${scanStatusId}', true)">${t('feishu_scan_replace')}</button>` : ''}
                <div id="${scanStatusId}" class="mt-4 w-full"></div>
            </div>`;
    } else {
        manualTab.className = `flex-1 px-3 py-1.5 rounded-md text-xs font-medium transition-colors ${activeClasses}`;
        scanTab.className = `flex-1 px-3 py-1.5 rounded-md text-xs font-medium transition-colors ${inactiveClasses}`;
        // An active instance card keys its fields by the instance id (so the
        // card's data-ch query and the save target line up); the Add panel keys
        // by the bare type since no instance exists yet.
        const ch = instanceId
            ? channelInstancesView.find(c => c.instance_id === instanceId)
            : channelsData.find(c => c.name === 'feishu');
        const fieldsHtml = buildChannelFieldsHtml(iid, ch ? ch.fields || [] : []);
        if (isActive) {
            // 已接入卡片：内置保存按钮，复用 saveChannelConfig 走 update 流程
            content.innerHTML = `
                <div class="space-y-4">
                    ${fieldsHtml}
                    <div class="flex items-center justify-end gap-3 pt-1">
                        <span id="ch-status-${iid}" class="text-xs text-primary-500 opacity-0 transition-opacity duration-300"></span>
                        <button onclick="saveChannelConfig('feishu', '${instanceId}')"
                            class="px-4 py-2 rounded-lg bg-primary-500 hover:bg-primary-600 text-white text-sm font-medium
                                   cursor-pointer transition-colors duration-150 disabled:opacity-50 disabled:cursor-not-allowed"
                            id="ch-save-${iid}">${t('channels_save')}</button>
                    </div>
                </div>`;
        } else {
            content.innerHTML = `<div class="space-y-4">${fieldsHtml}</div>`;
            if (actions) actions.classList.remove('hidden');
        }
        bindSecretFieldEvents(content);
        const appId = content.querySelector('[data-field="feishu_app_id"]');
        const owners = content.querySelector('[data-field="feishu_owner_open_ids"]');
        const memoryMode = content.querySelector('[data-field="feishu_private_memory_mode"]');
        if (appId && owners && memoryMode) {
            appId.addEventListener('input', () => {
                owners.value = '';
                memoryMode.value = 'owner_workspace';
            });
            bindFeishuOwnerLookup(content, appId, owners, instanceId);
        }
    }
}

function stopFeishuRegisterPoll() {
    const registrationId = _feishuRegisterFlow?.registrationId;
    _feishuRegisterFlow = null;
    if (registrationId) feishuRegistrationAction('cancel', registrationId).catch(() => {});
    if (_feishuRegisterPollTimer) {
        clearTimeout(_feishuRegisterPollTimer);
        _feishuRegisterPollTimer = null;
    }
}

function feishuRegistrationAction(action, registrationId) {
    return fetch('/api/feishu/register', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action, registration_id: registrationId }),
    }).then(response => response.json());
}

function startFeishuRegister(targetStatusId, replace = false) {
    const statusId = targetStatusId || 'feishu-scan-status';
    const statusEl = document.getElementById(statusId);
    if (statusEl) {
        statusEl.innerHTML = `<p class="text-sm text-slate-500 dark:text-slate-400 text-center">${t('feishu_scan_loading')}</p>`;
    }
    stopFeishuRegisterPoll();
    const instanceId = statusEl?.closest('.feishu-panel')?.dataset.instanceId || '';
    const flow = { replace };
    _feishuRegisterFlow = flow;
    const query = new URLSearchParams({ instance_id: instanceId, replace: replace ? '1' : '0' });
    fetch(`/api/feishu/register?${query}`)
        .then(r => r.json())
        .then(data => {
            if (_feishuRegisterFlow !== flow) {
                if (data.registration_id) feishuRegistrationAction('cancel', data.registration_id).catch(() => {});
                return;
            }
            if (data.status !== 'success') {
                renderFeishuRegisterError(statusId, data.message || t('feishu_scan_fail'));
                return;
            }
            if (data.register_status === 'downloading') {
                // Desktop first run: the SDK bundle lands before the QR exists.
                renderFeishuSdkDownloading(statusId);
            } else {
                renderFeishuQr(statusId, data.qr_image, data.qrcode_url);
            }
            flow.registrationId = data.registration_id;
            pollFeishuRegisterStatus(statusId, flow);
        })
        .catch(err => {
            if (_feishuRegisterFlow === flow) renderFeishuRegisterError(statusId, err.message || t('feishu_scan_fail'));
        });
}

function renderFeishuQr(statusId, qrImage, qrUrl) {
    const statusEl = document.getElementById(statusId);
    if (!statusEl) return;
    const imgHtml = qrImage
        ? `<img src="${qrImage}" alt="QR" class="w-44 h-44 rounded-lg border border-slate-200 dark:border-white/10 bg-white p-2"/>`
        : `<div class="w-44 h-44 rounded-lg border border-dashed border-slate-300 flex items-center justify-center text-xs text-slate-400">QR</div>`;
    statusEl.innerHTML = `
        <div class="flex flex-col items-center gap-3">
            ${imgHtml}
            <p class="text-xs text-amber-500">${t('feishu_scan_waiting')}</p>
            <p class="text-xs text-slate-400 dark:text-slate-500">${t('feishu_scan_tip')}</p>
            ${qrUrl ? `<a href="${qrUrl}" target="_blank" rel="noopener"
                class="text-xs text-blue-500 hover:text-blue-600 underline">${t('feishu_scan_open_link')}</a>` : ''}
        </div>`;
}

function renderFeishuSdkDownloading(statusId) {
    const statusEl = document.getElementById(statusId);
    if (!statusEl) return;
    statusEl.innerHTML = `
        <div class="flex flex-col items-center gap-2 py-6">
            <i class="fas fa-spinner fa-spin text-slate-400"></i>
            <p class="text-sm text-slate-500 dark:text-slate-400">${t('feishu_sdk_downloading')}</p>
            <p class="text-xs text-slate-400 dark:text-slate-500">${t('feishu_sdk_downloading_tip')}</p>
        </div>`;
}

function renderFeishuRegisterError(statusId, message) {
    const statusEl = document.getElementById(statusId);
    if (!statusEl) return;
    statusEl.innerHTML = `
        <div class="flex flex-col items-center gap-2 py-2">
            <p class="text-sm text-red-500 text-center">${escapeHtml(message)}</p>
            <button onclick="startFeishuRegister('${statusId}', ${!!_feishuRegisterFlow?.replace})"
                class="mt-1 px-4 py-1.5 rounded-md text-xs font-medium
                       bg-slate-100 dark:bg-white/10 text-slate-700 dark:text-slate-200
                       hover:bg-slate-200 dark:hover:bg-white/20 cursor-pointer">
                <i class="fas fa-rotate-right mr-1"></i>${t('feishu_scan_retry')}
            </button>
        </div>`;
}

function pollFeishuRegisterStatus(statusId, flow) {
    if (_feishuRegisterFlow !== flow) return;
    if (_feishuRegisterPollTimer) clearTimeout(_feishuRegisterPollTimer);
    _feishuRegisterPollTimer = setTimeout(() => {
        fetch('/api/feishu/register', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ action: 'poll', registration_id: flow.registrationId })
        })
        .then(r => r.json())
        .then(data => {
            if (_feishuRegisterFlow !== flow) return;
            if (data.status !== 'success') {
                renderFeishuRegisterError(statusId, data.message || t('feishu_scan_fail'));
                return;
            }
            const rs = data.register_status;
            if (rs === 'downloading') {
                renderFeishuSdkDownloading(statusId);
                pollFeishuRegisterStatus(statusId, flow);
                return;
            }
            // The QR may only be generated after the bundle downloaded, in
            // which case the initial GET could not carry it. Render it once;
            // repainting on every poll would make it flicker.
            const shown = document.getElementById(statusId);
            if ((data.qr_image || data.qrcode_url) && shown && !shown.querySelector('img')) {
                renderFeishuQr(statusId, data.qr_image, data.qrcode_url);
            }
            if (rs === 'done') {
                flow.registrationId = null;
                if (data.owner_bound) loadChannelsView();
                else renderFeishuScanResult(statusId, flow, data);
            } else if (rs === 'save_failed') {
                renderFeishuScanResult(statusId, flow, data);
            } else if (rs === 'expired') {
                renderFeishuRegisterError(statusId, t('feishu_scan_expired'));
            } else if (rs === 'denied') {
                renderFeishuRegisterError(statusId, t('feishu_scan_denied'));
            } else if (rs === 'error') {
                renderFeishuRegisterError(statusId, data.message || t('feishu_scan_fail'));
            } else {
                pollFeishuRegisterStatus(statusId, flow);
            }
        })
        .catch(() => {
            if (_feishuRegisterFlow === flow) pollFeishuRegisterStatus(statusId, flow);
        });
    }, 2000);
}

function renderFeishuScanResult(statusId, flow, result) {
    const status = document.getElementById(statusId);
    if (!status) return;
    const failed = result.register_status === 'save_failed';
    const label = failed ? 'feishu_save_scan_retry' : 'feishu_scan_done';
    const message = failed ? 'feishu_save_scan_failed' : 'feishu_scan_owner_missing';
    status.innerHTML = `<p role="status" class="mb-2 text-sm">${escapeHtml(t(message))}</p>
        <button class="px-4 py-2 rounded-lg bg-primary-500 text-white text-sm">${escapeHtml(t(label))}</button>`;
    status.querySelector('button').onclick = () => {
        if (failed) pollFeishuRegisterStatus(statusId, flow);
        else loadChannelsView();
    };
}

function bindFeishuOwnerLookup(content, appId, owners, instanceId) {
    const secret = content.querySelector('[data-field="feishu_app_secret"]');
    const actions = document.createElement('div');
    actions.className = 'flex flex-wrap items-center gap-2 mt-2 text-xs';
    actions.innerHTML = `<button type="button" class="text-primary-600">${escapeHtml(t('feishu_lookup_owner'))}</button>
        <button type="button" class="text-primary-600 hidden">${escapeHtml(t('feishu_use_owner'))}</button>
        <span role="status"></span>`;
    owners.after(actions);
    const [lookup, adopt] = actions.querySelectorAll('button');
    const status = actions.querySelector('span');
    let candidate = '';
    let revision = 0;
    const clear = () => {
        revision++;
        candidate = '';
        status.textContent = '';
        adopt.classList.add('hidden');
        lookup.disabled = false;
    };
    appId.addEventListener('input', clear);
    secret.addEventListener('input', clear);
    lookup.onclick = async () => {
        clear();
        const request = revision;
        lookup.disabled = true;
        try {
            const response = await fetch('/api/channels', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({action: 'lookup_owner', channel: 'feishu', instance_id: instanceId,
                    config: {feishu_app_id: appId.value, feishu_app_secret: secret.dataset.masked === '1' ? '' : secret.value}}),
            });
            const data = await response.json();
            if (revision !== request || !content.contains(actions)) return;
            candidate = data.status === 'success' && data.app_id === appId.value.trim() ? data.owner_open_id : '';
            status.textContent = candidate || t('feishu_lookup_owner_missing');
            adopt.classList.toggle('hidden', !candidate);
        } catch {
            if (revision === request) status.textContent = t('feishu_lookup_owner_missing');
        } finally {
            if (revision === request) lookup.disabled = false;
        }
    };
    adopt.onclick = () => {
        if (!candidate) return;
        const ids = new Set(owners.value.split(/[,，\s]+/).filter(Boolean));
        ids.add(candidate);
        owners.value = [...ids].join(', ');
        clear();
    };
}
