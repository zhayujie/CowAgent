/* Channel list, binding and configuration.
   Split out of console.js. These are classic scripts sharing one global
   scope; see channel/web/README.md before changing the load order. */

// =====================================================================
// Channels View
// =====================================================================
let channelsData = [];
// Multi-Agent mode: the multi-instance-ready types (feishu) render one card per
// channel_instances record. These mirror the extra fields the API returns.
let channelInstancesView = [];
let multiInstanceTypes = [];
let channelsMultiAgent = false;

function isMultiInstanceType(name) {
    return channelsMultiAgent && multiInstanceTypes.indexOf(name) !== -1;
}

function loadChannelsView() {
    const container = document.getElementById('channels-content');
    if (!container) return Promise.resolve();
    container.innerHTML = `<div class="flex items-center gap-2 py-8 justify-center text-slate-400 dark:text-slate-500 text-sm">
        <i class="fas fa-spinner fa-spin text-xs"></i><span>Loading...</span></div>`;

    const roster = agentCatalog.length ? Promise.resolve() : loadAgentCatalog();
    return roster.then(() => fetch('/api/channels').then(r => r.json()).then(data => {
        if (data.status !== 'success') return;
        channelsData = data.channels || [];
        channelsMultiAgent = !!data.multi_agent;
        multiInstanceTypes = data.multi_instance_types || [];
        channelInstancesView = data.instances || [];
        renderActiveChannels();
    }).catch(() => {
        container.innerHTML = '<p class="text-sm text-red-400 py-8 text-center">Failed to load channels</p>';
    }));
}

// Build the list of cards to render. In multi-Agent mode the multi-instance
// types (feishu) contribute one card per channel_instances record (from
// data.instances); everything else contributes its single per-type card. Each
// item carries an `iid` (instance id) that keys its DOM and actions: for legacy
// per-type cards it is just the channel name.
function channelRenderList() {
    const list = [];
    channelsData.forEach(ch => {
        if (isMultiInstanceType(ch.name)) return;  // rendered from instances
        if (ch.active) list.push(Object.assign({}, ch, { iid: ch.name }));
    });
    if (channelsMultiAgent) {
        channelInstancesView.forEach(inst => {
            list.push(Object.assign({}, inst, { iid: inst.instance_id }));
        });
    }
    // Show WeChat cards first; keep every other card in its existing relative
    // order (stable sort: weixin -> 0, everything else -> 1).
    list.sort((a, b) => (a.name === 'weixin' ? 0 : 1) - (b.name === 'weixin' ? 0 : 1));
    return list;
}

function renderActiveChannels() {
    stopWeixinQrPoll();
    stopWeixinStatusPoll();
    const container = document.getElementById('channels-content');
    container.innerHTML = '';
    closeAddChannelPanel();

    const activeChannels = channelRenderList();

    if (activeChannels.length === 0) {
        container.innerHTML = `
            <div class="flex flex-col items-center justify-center py-20">
                <div class="w-16 h-16 rounded-2xl bg-blue-50 dark:bg-blue-900/20 flex items-center justify-center mb-4">
                    <i class="fas fa-tower-broadcast text-blue-400 text-xl"></i>
                </div>
                <p class="text-slate-500 dark:text-slate-400 font-medium">${t('channels_empty')}</p>
                <p class="text-sm text-slate-400 dark:text-slate-500 mt-1">${t('channels_empty_desc')}</p>
            </div>`;
        return;
    }

    activeChannels.forEach(ch => {
        const iid = ch.iid;
        const label = (typeof ch.label === 'object') ? (ch.label[currentLang] || ch.label.en) : ch.label;
        const card = document.createElement('div');
        card.className = 'bg-white dark:bg-[#1A1A1A] rounded-xl border border-slate-200 dark:border-white/10 p-6';
        card.id = `channel-card-${iid}`;

        const fieldsHtml = buildChannelFieldsHtml(iid, ch.fields || []);
        const hasFields = (ch.fields || []).length > 0;

        const weixinWaiting = ch.name === 'weixin' && ch.login_status && ch.login_status !== 'logged_in';
        // 飞书 / 企微机器人 active 卡片渲染带 Tab 的 panel：手动填写 + 扫码重建（覆盖现有配置）
        const isFeishu = ch.name === 'feishu';
        const isWecomBot = ch.name === 'wecom_bot';
        // An instance card (multi-Agent feishu) shows the bound agent inline and
        // uses the instance id as its subtitle instead of the bare type name.
        const isInstance = isMultiInstanceType(ch.name) && !!ch.instance_id;
        let statusDot, statusText;
        if (weixinWaiting) {
            statusDot = 'bg-amber-400 animate-pulse';
            statusText = ch.login_status === 'scanned'
                ? `<span class="text-xs text-primary-500">${t('weixin_scan_scanned')}</span>`
                : `<span class="text-xs text-amber-500">${t('weixin_scan_waiting')}</span>`;
        } else {
            statusDot = 'bg-primary-400';
            statusText = `<span class="text-xs text-primary-500">${t('channels_connected')}</span>`;
        }

        card.innerHTML = `
            <div class="flex items-center gap-4${hasFields || weixinWaiting || isFeishu || isWecomBot || multiAgentMode() ? ' mb-5' : ''}">
                <div class="w-10 h-10 rounded-xl bg-${ch.color}-50 dark:bg-${ch.color}-900/20 flex items-center justify-center flex-shrink-0">
                    <i class="fas ${ch.icon} text-${ch.color}-500 text-base"></i>
                </div>
                <div class="flex-1 min-w-0">
                    <div class="flex items-center gap-2">
                        <span class="font-semibold text-slate-800 dark:text-slate-100">${escapeHtml(isInstance ? (ch.instance_name || label) : label)}</span>
                        ${isInstance ? `<button onclick="renameChannelInstance('${ch.name}', '${escapeHtml(iid)}')" title="${escapeHtml(t('channel_rename'))}"
                            class="text-slate-400 hover:text-primary-500 cursor-pointer transition-colors flex-shrink-0">
                            <i class="fas fa-pen text-xs"></i>
                        </button>` : ''}
                        <span class="w-2 h-2 rounded-full ${statusDot}"></span>
                        ${statusText}
                    </div>
                    <p class="text-xs text-slate-500 dark:text-slate-400 mt-0.5 font-mono">${escapeHtml(isInstance ? `${label} · ${iid}` : iid)}</p>
                </div>
                <button onclick="disconnectChannel('${ch.name}', '${isInstance ? iid : ''}')"
                    class="px-3 py-1.5 rounded-lg text-xs font-medium
                           bg-red-50 dark:bg-red-900/20 text-red-500 dark:text-red-400
                           hover:bg-red-100 dark:hover:bg-red-900/40
                           cursor-pointer transition-colors flex-shrink-0">
                    ${t('channels_disconnect')}
                </button>
            </div>
            ${multiAgentMode() ? `<div class="channel-agent-bind">
                <span class="text-xs text-slate-500 whitespace-nowrap" title="${escapeHtml(t('channel_bound_agent_hint'))}">${escapeHtml(t('channel_bound_agent'))}</span>
                <div id="ch-members-${iid}" class="cfg-dropdown cfg-dropdown-avatar cfg-dropdown-sm cfg-dropdown-multi" tabindex="0" style="width: 200px;">
                    <div class="cfg-dropdown-selected">
                        <span class="cfg-dropdown-faces"></span>
                        <span class="cfg-dropdown-text">--</span>
                        <i class="fas fa-chevron-down cfg-dropdown-arrow"></i>
                    </div>
                    <div class="cfg-dropdown-menu"></div>
                </div>
            </div>` : ''}
            ${weixinWaiting ? `<div id="weixin-active-qr-${escapeHtml(iid)}" class="flex flex-col items-center py-2">
                <button onclick="showWeixinActiveQr('${escapeHtml(iid)}')"
                    class="px-4 py-2 rounded-lg bg-primary-500 hover:bg-primary-600 text-white text-sm font-medium
                           cursor-pointer transition-colors duration-150">
                    ${t('weixin_scan_title')}
                </button>
            </div>` : ''}
            ${isFeishu ? buildFeishuPanel(ch, true) : (isWecomBot ? buildWecomBotPanel(ch, true) : (hasFields ? `<div class="space-y-4">
                ${fieldsHtml}
                <div class="flex items-center justify-end gap-3 pt-1">
                    <span id="ch-status-${iid}" class="text-xs text-primary-500 opacity-0 transition-opacity duration-300"></span>
                    <button onclick="saveChannelConfig('${ch.name}', '${isInstance ? iid : ''}')"
                        class="px-4 py-2 rounded-lg bg-primary-500 hover:bg-primary-600 text-white text-sm font-medium
                               cursor-pointer transition-colors duration-150 disabled:opacity-50 disabled:cursor-not-allowed"
                        id="ch-save-${iid}">${t('channels_save')}</button>
                </div>
            </div>` : ''))}`;

        container.appendChild(card);
        bindSecretFieldEvents(card);
        initChannelTeam(ch);

        if (weixinWaiting) {
            startWeixinActiveStatusPoll(iid);
        }
    });
}

// One multi-select per channel card, same idea as creating a team in the chat
// history: pick a set of Agents; the first pick is the owner (receives every
// message and can delegate), the rest are teammates. An ordered list, so the
// first checked stays the owner. Empty = follow the default Agent, solo.
let _channelTeam = {};  // iid -> ordered [ownerId, ...memberIds]

function initChannelTeam(ch) {
    const iid = ch.iid || ch.name;
    if (!multiAgentMode()) return;
    const box = document.getElementById(`ch-members-${iid}`);
    if (!box) return;
    // Seed the ordered team: owner first, then its members. A legacy per-type
    // card has no instance fields, so fall back to its channel-type binding.
    const owner = ch.instance_id ? (ch.agent_id || '') : (channelBoundAgentId(ch.name) || '');
    const members = Array.isArray(ch.members) ? ch.members : [];
    _channelTeam[iid] = [owner, ...members].filter((id, i, arr) => id && arr.indexOf(id) === i);
    box.dataset.channelName = ch.name;
    renderChannelTeam(iid);
    if (!box._ddBound) {
        box.querySelector('.cfg-dropdown-selected').addEventListener('click', (e) => {
            e.stopPropagation();
            document.querySelectorAll('.cfg-dropdown.open').forEach(d => { if (d !== box) d.classList.remove('open'); });
            box.classList.toggle('open');
        });
        box._ddBound = true;
    }
}

function renderChannelTeam(iid) {
    const box = document.getElementById(`ch-members-${iid}`);
    if (!box) return;
    const team = _channelTeam[iid] || [];
    const ownerId = team[0] || '';
    const agents = enabledAgents();
    const chosen = team.map(id => findAgent(id)).filter(Boolean);

    const faces = box.querySelector('.cfg-dropdown-faces');
    const textEl = box.querySelector('.cfg-dropdown-text');
    const MAX_FACES = 3;
    if (chosen.length) {
        // Trigger: up to MAX_FACES avatars; any beyond that become a "+N" pill
        // so the count always matches how many are hidden, never the total.
        const shown = chosen.slice(0, MAX_FACES);
        const extra = chosen.length - shown.length;
        faces.innerHTML = shown.map(a => agentAvatarHTML(a, 18)).join('')
            + (extra > 0 ? `<span class="cfg-dropdown-more">+${extra}</span>` : '');
        textEl.textContent = chosen[0].name || chosen[0].id;
        textEl.classList.remove('text-slate-400', 'dark:text-slate-500');
    } else {
        // Nothing picked: this channel follows the default Agent. Show it
        // (dim) rather than an empty "none", so the receiver is always clear.
        const def = findAgent(defaultAgentId);
        faces.innerHTML = def ? agentAvatarHTML(def, 18) : '';
        textEl.textContent = def ? (def.name || def.id) : t('channel_team_none');
        textEl.classList.add('text-slate-400', 'dark:text-slate-500');
    }

    // Menu: a checklist. The first-picked carries a small "default" badge so it
    // is clear which Agent receives and delegates. The selected tick is the
    // dropdown's global .active::after, so no per-row tick element is needed.
    const menu = box.querySelector('.cfg-dropdown-menu');
    if (!agents.length) {
        menu.innerHTML = `<div class="cfg-dropdown-item cfg-dropdown-empty">${escapeHtml(t('channel_team_no_candidates'))}</div>`;
        return;
    }
    menu.innerHTML = agents.map(a => {
        const on = team.includes(a.id);
        const isOwner = a.id === ownerId;
        return `<div class="cfg-dropdown-item cfg-dropdown-check${on ? ' active' : ''}"
            onclick="event.stopPropagation(); toggleChannelTeam('${iid}','${a.id}')">
            <span class="cfg-dropdown-item-face">${agentAvatarHTML(a, 20)}</span>
            <span class="cfg-dropdown-label">${escapeHtml(a.name || a.id)}</span>
            ${isOwner ? `<span class="cfg-dropdown-badge">${escapeHtml(t('channel_bound_default'))}</span>` : ''}
        </div>`;
    }).join('');
}

function toggleChannelTeam(iid, agentId) {
    const box = document.getElementById(`ch-members-${iid}`);
    const chName = box ? (box.dataset.channelName || '') : '';
    const team = _channelTeam[iid] || [];
    const i = team.indexOf(agentId);
    if (i === -1) team.push(agentId);       // append: order = pick order
    else team.splice(i, 1);                 // remove; if it was owner, next becomes owner
    _channelTeam[iid] = team;
    renderChannelTeam(iid);
    // Persist: first pick is the owner (empty -> default Agent), rest members.
    const ownerId = team[0] || '';
    const members = team.slice(1);
    bindChannelAgent(chName, ownerId, iid, members);
}

function buildChannelFieldsHtml(chName, fields) {
    let html = '';
    fields.forEach(f => {
        const inputId = `ch-${chName}-${f.key}`;
        let inputHtml = '';
        if (f.type === 'bool') {
            const checked = f.value ? 'checked' : '';
            inputHtml = `<label class="relative inline-flex items-center cursor-pointer">
                <input id="${inputId}" type="checkbox" ${checked} class="sr-only peer" data-field="${f.key}" data-ch="${chName}">
                <div class="w-9 h-5 bg-slate-200 dark:bg-slate-700 peer-checked:bg-primary-400 rounded-full
                            after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white
                            after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:after:translate-x-full"></div>
            </label>`;
        } else if (f.type === 'secret') {
            inputHtml = `<input id="${inputId}" type="text" value="${escapeHtml(String(f.value || ''))}"
                data-field="${f.key}" data-ch="${chName}" data-masked="${f.value ? '1' : ''}"
                class="w-full px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-600
                       bg-slate-50 dark:bg-white/5 text-sm text-slate-800 dark:text-slate-100
                       focus:outline-none focus:border-primary-500 font-mono transition-colors
                       ${f.value ? 'cfg-key-masked' : ''}"
                placeholder="${escapeHtml(f.label)}">`;
        } else {
            const inputType = f.type === 'number' ? 'number' : 'text';
            inputHtml = `<input id="${inputId}" type="${inputType}" value="${escapeHtml(String(f.value ?? f.default ?? ''))}"
                data-field="${f.key}" data-ch="${chName}"
                class="w-full px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-600
                       bg-slate-50 dark:bg-white/5 text-sm text-slate-800 dark:text-slate-100
                       focus:outline-none focus:border-primary-500 font-mono transition-colors"
                placeholder="${escapeHtml(f.label)}">`;
        }
        html += `<div>
            <label class="block text-sm font-medium text-slate-600 dark:text-slate-400 mb-1.5">${escapeHtml(f.label)}</label>
            ${inputHtml}
        </div>`;
    });
    return html;
}

function bindSecretFieldEvents(container) {
    container.querySelectorAll('input[data-masked="1"]').forEach(inp => {
        inp.addEventListener('focus', function() {
            if (this.dataset.masked === '1') {
                this.value = '';
                this.dataset.masked = '';
                this.classList.remove('cfg-key-masked');
            }
        });
    });
}

function showChannelStatus(chName, msgKey, isError) {
    const el = document.getElementById(`ch-status-${chName}`);
    if (!el) return;
    el.textContent = t(msgKey);
    el.classList.toggle('text-red-500', !!isError);
    el.classList.toggle('text-primary-500', !isError);
    el.classList.remove('opacity-0');
    setTimeout(() => el.classList.add('opacity-0'), 2500);
}

function saveChannelConfig(chName, instanceId) {
    // instanceId keys the DOM (per-instance cards); falls back to the channel
    // name for legacy single-instance cards.
    const iid = instanceId || chName;
    const card = document.getElementById(`channel-card-${iid}`);
    if (!card) return;

    const updates = {};
    card.querySelectorAll('input[data-ch="' + iid + '"]').forEach(inp => {
        const key = inp.dataset.field;
        if (inp.type === 'checkbox') {
            updates[key] = inp.checked;
        } else {
            if (inp.dataset.masked === '1') return;
            updates[key] = inp.value;
        }
    });

    const btn = document.getElementById(`ch-save-${iid}`);
    if (btn) btn.disabled = true;

    fetch('/api/channels', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: 'save', channel: chName, instance_id: instanceId || '', config: updates })
    })
    .then(r => r.json())
    .then(data => {
        if (data.status === 'success') {
            showChannelStatus(iid, data.restarted ? 'channels_restarted' : 'channels_saved', false);
        } else {
            showChannelStatus(iid, 'channels_save_error', true);
        }
    })
    .catch(() => showChannelStatus(iid, 'channels_save_error', true))
    .finally(() => { if (btn) btn.disabled = false; });
}

// A minimal single-input dialog, used for renaming a channel instance. Mirrors
// showConfirmDialog's lifecycle so it themes and closes the same way.
function showRenameDialog({ title, value, okText, cancelText, onConfirm }) {
    const overlay = document.getElementById('rename-dialog-overlay');
    if (!overlay) return;
    const titleEl = overlay.querySelector('h3');
    const input = document.getElementById('rename-dialog-input');
    const okBtn = document.getElementById('rename-dialog-ok');
    const cancelBtn = document.getElementById('rename-dialog-cancel');
    if (titleEl && title) titleEl.textContent = title;
    if (okText) okBtn.textContent = okText;
    if (cancelText) cancelBtn.textContent = cancelText;
    input.value = value || '';

    function cleanup() {
        overlay.classList.add('hidden');
        okBtn.removeEventListener('click', onOk);
        cancelBtn.removeEventListener('click', onCancel);
        overlay.removeEventListener('click', onOverlayClick);
        input.removeEventListener('keydown', onKey);
    }
    function onOk() { const v = input.value.trim(); cleanup(); if (onConfirm) onConfirm(v); }
    function onCancel() { cleanup(); }
    function onOverlayClick(e) { if (e.target === overlay) cleanup(); }
    function onKey(e) {
        // Ignore Enter while an IME is composing (e.g. picking a Chinese
        // candidate), otherwise confirming a candidate would submit the dialog.
        // keyCode 229 is the legacy signal for "still composing".
        if (e.isComposing || e.keyCode === 229) return;
        if (e.key === 'Enter') onOk();
        else if (e.key === 'Escape') onCancel();
    }

    okBtn.addEventListener('click', onOk);
    cancelBtn.addEventListener('click', onCancel);
    overlay.addEventListener('click', onOverlayClick);
    input.addEventListener('keydown', onKey);
    overlay.classList.remove('hidden');
    setTimeout(() => { input.focus(); input.select(); }, 30);
}

function renameChannelInstance(chName, instanceId) {
    const inst = (channelInstancesView || []).find(i => i.instance_id === instanceId);
    const current = inst ? (inst.instance_name || '') : '';
    showRenameDialog({
        title: t('channel_rename'),
        value: current,
        okText: t('channels_save'),
        cancelText: t('channels_cancel'),
        onConfirm: (newName) => {
            fetch('/api/channels', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ action: 'rename', channel: chName, instance_id: instanceId, name: newName })
            })
            .then(r => r.json())
            .then(data => { if (data.status === 'success') loadChannelsView(); })
            .catch(() => {});
        }
    });
}

function disconnectChannel(chName, instanceId) {
    const ch = channelsData.find(c => c.name === chName);
    const label = ch ? ((typeof ch.label === 'object') ? (ch.label[currentLang] || ch.label.en) : ch.label) : chName;

    showConfirmDialog({
        title: t('channels_disconnect'),
        message: t('channels_disconnect_confirm'),
        okText: t('channels_disconnect'),
        cancelText: t('channels_cancel'),
        onConfirm: () => {
            fetch('/api/channels', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ action: 'disconnect', channel: chName, instance_id: instanceId || '' })
            })
            .then(r => r.json())
            .then(data => {
                if (data.status === 'success') {
                    // An instance removal changes the instances list; reload from
                    // the server so the card set is authoritative. Legacy per-type
                    // disconnect can flip the flag locally.
                    if (instanceId) {
                        loadChannelsView();
                    } else {
                    if (ch) ch.active = false;
                    renderActiveChannels();
                    }
                } else {
                    // Surface the failure instead of silently leaving the card in
                    // place — otherwise a rejected disconnect looks like nothing
                    // happened at all.
                    _wsToast(data.message || t('channels_disconnect_error'));
                }
            })
            .catch(() => _wsToast(t('channels_disconnect_error')));
        }
    });
}

// --- Add channel panel ---
function openAddChannelPanel() {
    const panel = document.getElementById('channels-add-panel');
    // A multi-instance-ready type (feishu) can always be added again — each add
    // creates a new instance. Other types disappear once active.
    const activeNames = new Set(
        channelsData.filter(c => c.active && !isMultiInstanceType(c.name)).map(c => c.name)
    );
    const available = channelsData.filter(c => !activeNames.has(c.name));

    const anyCards = channelRenderList().length > 0;
    const content = document.getElementById('channels-content');
    if (!anyCards && content) content.classList.add('hidden');

    if (available.length === 0) {
        panel.innerHTML = `<div class="bg-white dark:bg-[#1A1A1A] rounded-xl border border-slate-200 dark:border-white/10 p-6 text-center">
            <p class="text-sm text-slate-500 dark:text-slate-400">All channels are already connected</p>
            <button onclick="closeAddChannelPanel()" class="mt-3 text-xs text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 cursor-pointer">${t('channels_cancel')}</button>
        </div>`;
        panel.classList.remove('hidden');
        return;
    }

    const ddOptions = [
        { value: '', label: t('channels_select_placeholder') },
        ...available.map(ch => {
            const label = (typeof ch.label === 'object') ? (ch.label[currentLang] || ch.label.en) : ch.label;
            return { value: ch.name, label: `${label} (${ch.name})` };
        })
    ];

    panel.innerHTML = `
        <div class="bg-white dark:bg-[#1A1A1A] rounded-xl border border-primary-200 dark:border-primary-800 p-6">
            <div class="flex items-center gap-3 mb-5">
                <div class="w-9 h-9 rounded-lg bg-primary-50 dark:bg-primary-900/30 flex items-center justify-center">
                    <i class="fas fa-plus text-primary-500 text-sm"></i>
                </div>
                <h3 class="font-semibold text-slate-800 dark:text-slate-100">${t('channels_add')}</h3>
            </div>
            <div class="mb-4">
                <div id="add-channel-select" class="cfg-dropdown" tabindex="0">
                    <div class="cfg-dropdown-selected">
                        <span class="cfg-dropdown-text">--</span>
                        <i class="fas fa-chevron-down cfg-dropdown-arrow"></i>
                    </div>
                    <div class="cfg-dropdown-menu"></div>
                </div>
            </div>
            <div id="add-channel-fields" class="space-y-4"></div>
            <div id="add-channel-actions" class="hidden flex items-center justify-end gap-3 pt-4">
                <button onclick="closeAddChannelPanel()"
                    class="px-4 py-2 rounded-lg border border-slate-200 dark:border-white/10
                           text-slate-600 dark:text-slate-300 text-sm font-medium
                           hover:bg-slate-50 dark:hover:bg-white/5
                           cursor-pointer transition-colors duration-150">${t('channels_cancel')}</button>
                <button id="add-channel-submit" onclick="submitAddChannel()"
                    class="px-4 py-2 rounded-lg bg-primary-500 hover:bg-primary-600 text-white text-sm font-medium
                           cursor-pointer transition-colors duration-150 disabled:opacity-50 disabled:cursor-not-allowed">${t('channels_connect_btn')}</button>
            </div>
        </div>`;
    panel.classList.remove('hidden');
    panel.scrollIntoView({ behavior: 'smooth', block: 'nearest' });

    const ddEl = document.getElementById('add-channel-select');
    initDropdown(ddEl, ddOptions, '', onAddChannelSelect);
}

function closeAddChannelPanel() {
    stopWeixinQrPoll();
    stopFeishuRegisterPoll();
    const panel = document.getElementById('channels-add-panel');
    if (panel) {
        panel.classList.add('hidden');
        panel.innerHTML = '';
    }
    const content = document.getElementById('channels-content');
    if (content) content.classList.remove('hidden');
}

function onAddChannelSelect(chName) {
    stopWeixinQrPoll();
    stopFeishuRegisterPoll();
    const fieldsContainer = document.getElementById('add-channel-fields');
    const actions = document.getElementById('add-channel-actions');

    if (!chName) {
        fieldsContainer.innerHTML = '';
        actions.classList.add('hidden');
        return;
    }

    if (chName === 'weixin') {
        actions.classList.add('hidden');
        fieldsContainer.innerHTML = `
            <div id="weixin-qr-panel" class="flex flex-col items-center py-4">
                <p class="text-sm text-slate-500 dark:text-slate-400 mb-4">${t('weixin_scan_loading')}</p>
            </div>`;
        startWeixinQrLogin();
        return;
    }

    if (chName === 'wecom_bot') {
        actions.classList.add('hidden');
        const ch = channelsData.find(c => c.name === chName);
        fieldsContainer.innerHTML = buildWecomBotPanel(ch);
        return;
    }

    if (chName === 'feishu') {
        actions.classList.add('hidden');
        const ch = channelsData.find(c => c.name === chName);
        fieldsContainer.innerHTML = buildFeishuPanel(ch);
        return;
    }

    const ch = channelsData.find(c => c.name === chName);
    if (!ch) return;

    fieldsContainer.innerHTML = buildChannelFieldsHtml(chName, ch.fields || []);
    bindSecretFieldEvents(fieldsContainer);
    actions.classList.remove('hidden');
}

function submitAddChannel() {
    const ddEl = document.getElementById('add-channel-select');
    const chName = getDropdownValue(ddEl);
    if (!chName) return;

    const fieldsContainer = document.getElementById('add-channel-fields');
    const updates = {};
    fieldsContainer.querySelectorAll('input[data-ch="' + chName + '"]').forEach(inp => {
        const key = inp.dataset.field;
        if (inp.type === 'checkbox') {
            updates[key] = inp.checked;
        } else {
            if (inp.dataset.masked === '1') return;
            updates[key] = inp.value;
        }
    });

    const btn = document.getElementById('add-channel-submit');
    if (btn) { btn.disabled = true; btn.textContent = t('channels_connecting'); }

    fetch('/api/channels', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: 'connect', channel: chName, config: updates })
    })
    .then(r => r.json())
    .then(data => {
        if (data.status === 'success') {
            // A new multi-instance record only shows up by reloading the
            // instances list from the server; legacy per-type add can patch
            // local state and re-render.
            if (isMultiInstanceType(chName) || data.instance_id) {
                loadChannelsView();
                return;
            }
            const ch = channelsData.find(c => c.name === chName);
            if (ch) {
                ch.active = true;
                (ch.fields || []).forEach(f => {
                    if (updates[f.key] !== undefined) {
                        f.value = f.type === 'secret' ? ChannelsHandler_maskSecret(updates[f.key]) : updates[f.key];
                    }
                });
            }
            renderActiveChannels();
        } else {
            if (btn) { btn.disabled = false; btn.textContent = t('channels_connect_btn'); }
        }
    })
    .catch(() => {
        if (btn) { btn.disabled = false; btn.textContent = t('channels_connect_btn'); }
    });
}

