/* Capabilities view: built-in tools, MCP tools, and installed skills.
   Split out of console.js. These are classic scripts sharing one global
   scope; see channel/web/README.md before changing the load order. */

// =====================================================================
// Capabilities View
// =====================================================================
let toolsLoaded = false;
let toolsExpanded = false;
const TOOLS_COLLAPSED_COUNT = 4;

const TOOL_ICONS = {
    bash: 'fa-terminal',
    edit: 'fa-pen-to-square',
    read: 'fa-file-lines',
    write: 'fa-file-pen',
    ls: 'fa-folder-open',
    send: 'fa-paper-plane',
    web_search: 'fa-magnifying-glass',
    browser: 'fa-globe',
    env_config: 'fa-key',
    scheduler: 'fa-clock',
    time: 'fa-calendar-day',
    memory_get: 'fa-brain',
    memory_search: 'fa-brain',
};

function getToolIcon(name) {
    return TOOL_ICONS[name] || 'fa-wrench';
}

function loadSkillsView() {
    bindSkillsConfigUi();
    loadToolsSection();
    loadMcpSection();
    loadSkillsSection();
}

let skillsConfigUiBound = false;

function bindSkillsConfigUi() {
    if (skillsConfigUiBound) return;
    skillsConfigUiBound = true;
    const on = (id, evt, fn) => document.getElementById(id)?.addEventListener(evt, fn);

    on('tools-toggle-btn', 'click', () => { toolsExpanded = !toolsExpanded; applyToolsCollapse(); });

    on('mcp-add-btn', 'click', () => openMcpEditor());
    on('mcp-editor-cancel', 'click', closeMcpEditor);
    on('mcp-editor-test', 'click', testMcpEditor);
    on('mcp-editor-save', 'click', saveMcpEditor);
    on('mcp-advanced-toggle', 'click', () => setMcpAdvancedOpen(
        document.getElementById('mcp-advanced-fields').classList.contains('hidden')));
    on('mcp-editor-overlay', 'click', (e) => { if (e.target.id === 'mcp-editor-overlay') closeMcpEditor(); });
    on('mcp-editor-overlay', 'input', () => setMcpSaveAnyway(false));
    on('mcp-editor-overlay', 'change', () => setMcpSaveAnyway(false));
    document.querySelectorAll('[data-mcp-tab]').forEach(btn => {
        btn.addEventListener('click', () => switchMcpTab(btn.dataset.mcpTab));
    });
    const jsonEl = document.getElementById('mcp-field-json');
    if (jsonEl) jsonEl.placeholder = MCP_JSON_PLACEHOLDER;

    bindSkillAddUi();

    document.addEventListener('keydown', (e) => {
        if (e.key !== 'Escape') return;
        if (!document.getElementById('mcp-editor-overlay')?.classList.contains('hidden')) closeMcpEditor();
        else if (!document.getElementById('skill-add-overlay')?.classList.contains('hidden')) closeSkillAdd();
    });
}

function setButtonBusy(btn, busy) {
    if (!btn) return;
    btn.disabled = !!busy;
}

async function postJson(url, body, method) {
    const res = await fetch(url, {
        method: method || 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
    });
    return res.json();
}

// ---------------------------------------------------------------------
// Built-in tools
// ---------------------------------------------------------------------

function applyToolsCollapse() {
    const listEl = document.getElementById('tools-list');
    const btn = document.getElementById('tools-toggle-btn');
    if (!listEl || !btn) return;
    const cards = Array.from(listEl.children);
    cards.forEach((card, i) => {
        card.classList.toggle('hidden', !toolsExpanded && i >= TOOLS_COLLAPSED_COUNT);
    });
    const collapsible = cards.length > TOOLS_COLLAPSED_COUNT;
    btn.classList.toggle('hidden', !collapsible);
    const label = document.getElementById('tools-toggle-label');
    if (label) {
        const key = toolsExpanded ? 'tools_collapse' : 'tools_show_all';
        label.dataset.i18n = key;
        label.textContent = t(key);
    }
    const icon = document.getElementById('tools-toggle-icon');
    if (icon) icon.style.transform = toolsExpanded ? 'rotate(180deg)' : '';
}

function loadToolsSection() {
    if (toolsLoaded) return;
    const emptyEl = document.getElementById('tools-empty');
    const listEl = document.getElementById('tools-list');
    const badge = document.getElementById('tools-count-badge');
    const showEmpty = (key) => {
        emptyEl.classList.remove('hidden');
        emptyEl.innerHTML = `<span class="text-sm text-slate-400 dark:text-slate-500">${escapeHtml(t(key))}</span>`;
    };

    fetch('/api/tools').then(r => r.json()).then(data => {
        if (data.status !== 'success') { showEmpty('tools_load_failed'); return; }
        const tools = data.tools || [];
        emptyEl.classList.add('hidden');
        if (tools.length === 0) { showEmpty('tools_empty'); return; }
        badge.textContent = tools.length;
        badge.classList.remove('hidden');
        listEl.innerHTML = '';
        tools.forEach(tool => {
            const card = document.createElement('div');
            card.className = 'bg-white dark:bg-[#1A1A1A] rounded-xl border border-slate-200 dark:border-white/10 p-4 flex items-start gap-3';
            card.innerHTML = `
                <div class="w-9 h-9 rounded-lg bg-blue-50 dark:bg-blue-900/20 flex items-center justify-center flex-shrink-0">
                    <i class="fas ${getToolIcon(tool.name)} text-blue-500 dark:text-blue-400 text-sm"></i>
                </div>
                <div class="flex-1 min-w-0">
                    <span class="block font-medium text-sm text-slate-700 dark:text-slate-200 font-mono truncate">${escapeHtml(tool.name)}</span>
                    <p class="text-xs text-slate-400 dark:text-slate-500 mt-1 line-clamp-2">${escapeHtml(tool.description || '--')}</p>
                </div>`;
            listEl.appendChild(card);
        });
        listEl.classList.remove('hidden');
        applyToolsCollapse();
        toolsLoaded = true;
    }).catch(() => showEmpty('tools_load_failed'));
}

// ---------------------------------------------------------------------
// MCP tools
// ---------------------------------------------------------------------

let mcpServersCache = [];
let mcpEditorOriginalName = null;
let mcpEditorTab = 'form';
let mcpSaveAnyway = false;
let mcpPollTimer = null;
let mcpPollDeadline = 0;
const MCP_POLL_INTERVAL_MS = 1500;
const MCP_POLL_MAX_MS = 120000;

const MCP_JSON_PLACEHOLDER = JSON.stringify(
    { mcpServers: { fetch: { command: 'uvx', args: ['mcp-server-fetch'] } } }, null, 2);

const MCP_TRANSPORT_LABELS = { stdio: 'stdio', sse: 'SSE', 'streamable-http': 'HTTP' };

function kvToObject(text) {
    const out = {};
    String(text || '').split(/\r?\n/).forEach((line) => {
        const trimmed = line.trim();
        if (!trimmed) return;
        const idx = trimmed.indexOf('=');
        if (idx <= 0) return;
        out[trimmed.slice(0, idx).trim()] = trimmed.slice(idx + 1);
    });
    return out;
}

function objectToKv(obj) {
    if (!obj || typeof obj !== 'object') return '';
    return Object.entries(obj).map(([k, v]) => `${k}=${v}`).join('\n');
}

function mcpStatusLabel(status) {
    const key = {
        ready: 'mcp_status_ready',
        pending: 'mcp_status_pending',
        failed: 'mcp_status_failed',
        needs_auth: 'mcp_status_needs_auth',
        disabled: 'mcp_status_disabled',
        idle: 'mcp_status_idle',
    }[status] || 'mcp_status_idle';
    return t(key);
}

function mcpStatusClass(status) {
    if (status === 'ready') return 'bg-emerald-50 text-emerald-600 dark:bg-emerald-900/20 dark:text-emerald-400';
    if (status === 'failed') return 'bg-red-50 text-red-600 dark:bg-red-900/20 dark:text-red-400';
    if (status === 'needs_auth') return 'bg-amber-50 text-amber-600 dark:bg-amber-900/20 dark:text-amber-400';
    if (status === 'disabled') return 'bg-slate-100 text-slate-500 dark:bg-white/10 dark:text-slate-400';
    return 'bg-blue-50 text-blue-600 dark:bg-blue-900/20 dark:text-blue-400';
}

function loadMcpSection() {
    const emptyEl = document.getElementById('mcp-empty');
    const listEl = document.getElementById('mcp-list');
    const badge = document.getElementById('mcp-count-badge');
    if (!listEl) return;
    const errorEl = () => {
        let el = document.getElementById('mcp-load-error');
        if (!el) {
            el = document.createElement('p');
            el.id = 'mcp-load-error';
            el.className = 'text-sm text-red-500 py-2';
            listEl.parentNode.insertBefore(el, listEl);
        }
        return el;
    };
    const showError = (msg) => {
        listEl.classList.add('hidden');
        emptyEl?.classList.add('hidden');
        const el = errorEl();
        el.textContent = msg;
        el.classList.remove('hidden');
    };
    fetch('/api/mcp/servers').then(r => r.json()).then(data => {
        if (data.status !== 'success') {
            showError(`${t('mcp_load_failed')}: ${data.message || ''}`);
            return;
        }
        document.getElementById('mcp-load-error')?.classList.add('hidden');
        mcpServersCache = data.servers || [];
        if (badge) {
            badge.textContent = mcpServersCache.length;
            badge.classList.toggle('hidden', mcpServersCache.length === 0);
        }
        emptyEl?.classList.toggle('hidden', mcpServersCache.length > 0);
        listEl.innerHTML = '';
        mcpServersCache.forEach(server => listEl.appendChild(renderMcpCard(server)));
        listEl.classList.toggle('hidden', mcpServersCache.length === 0);
        scheduleMcpStatusPoll();
    }).catch(() => showError(t('mcp_load_failed')));
}

/** Saved servers start in the background, so keep refreshing while any is still loading. */
function scheduleMcpStatusPoll() {
    clearTimeout(mcpPollTimer);
    if (!mcpServersCache.some(s => s.status === 'pending')) {
        mcpPollDeadline = 0;
        return;
    }
    if (!mcpPollDeadline) mcpPollDeadline = Date.now() + MCP_POLL_MAX_MS;
    if (Date.now() > mcpPollDeadline) return;
    mcpPollTimer = setTimeout(() => {
        // Stop once the view is no longer on screen; opening it again reloads the list.
        if (document.getElementById('mcp-list')?.offsetParent === null) {
            mcpPollDeadline = 0;
            return;
        }
        loadMcpSection();
    }, MCP_POLL_INTERVAL_MS);
}

function renderMcpCard(server) {
    const card = document.createElement('div');
    card.className = 'group bg-white dark:bg-[#1A1A1A] rounded-xl border border-slate-200 dark:border-white/10 p-4 flex items-start gap-3 '
        + 'cursor-pointer hover:border-slate-300 dark:hover:border-white/20 transition-colors';
    const type = server.type || (server.url ? 'sse' : 'stdio');
    const summary = type === 'stdio'
        ? [server.command, ...(server.args || [])].filter(Boolean).join(' ')
        : (server.url || '');
    const disabled = server.status === 'disabled';
    card.innerHTML = `
        <div class="w-9 h-9 rounded-lg bg-amber-50 dark:bg-amber-900/20 flex items-center justify-center flex-shrink-0">
            <i class="fas fa-plug ${disabled ? 'text-slate-300 dark:text-slate-600' : 'text-amber-500'} text-sm"></i>
        </div>
        <div class="flex-1 min-w-0">
            <div class="flex items-center gap-2 mb-1">
                <span class="font-medium text-sm text-slate-700 dark:text-slate-200 truncate font-mono">${escapeHtml(server.name)}</span>
                <span class="flex-shrink-0 px-1.5 py-0.5 rounded text-[10px] font-medium bg-slate-100 text-slate-500 dark:bg-white/10 dark:text-slate-400">${escapeHtml(MCP_TRANSPORT_LABELS[type] || type)}</span>
                <span class="flex-shrink-0 px-1.5 py-0.5 rounded-full text-[10px] ${mcpStatusClass(server.status)}">${escapeHtml(mcpStatusLabel(server.status))}</span>
                <span class="flex-1"></span>
                <button type="button" data-mcp-edit title="${escapeHtml(t('mcp_edit'))}"
                        class="flex-shrink-0 p-1 -my-1 rounded text-slate-300 dark:text-slate-600 hover:text-slate-500 dark:hover:text-slate-300 transition-colors">
                    <i class="fas fa-pen text-[10px]"></i>
                </button>
                <button type="button" data-mcp-delete title="${escapeHtml(t('mcp_delete'))}"
                        class="flex-shrink-0 p-1 -my-1 rounded text-slate-300 dark:text-slate-600 hover:text-red-500 dark:hover:text-red-400 transition-colors">
                    <i class="fas fa-trash text-[10px]"></i>
                </button>
            </div>
            <p class="text-xs text-slate-400 dark:text-slate-500 truncate font-mono" title="${escapeHtml(summary)}">${escapeHtml(summary || '--')}</p>
        </div>`;
    card.onclick = () => openMcpEditor(server);
    card.querySelector('[data-mcp-edit]').onclick = (e) => { e.stopPropagation(); openMcpEditor(server); };
    card.querySelector('[data-mcp-delete]').onclick = (e) => { e.stopPropagation(); deleteMcpServer(server.name); };
    return card;
}

function mcpTransportOptions() {
    return [
        { value: 'stdio', label: 'stdio', hint: t('mcp_transport_stdio_hint') },
        { value: 'sse', label: 'SSE', hint: t('mcp_transport_remote_hint') },
        { value: 'streamable-http', label: 'Streamable HTTP', hint: t('mcp_transport_remote_hint') },
    ];
}

function mcpEditorTransport() {
    return getDropdownValue(document.getElementById('mcp-field-type')) || 'stdio';
}

function syncMcpEditorTransport() {
    setMcpSaveAnyway(false);
    const stdio = mcpEditorTransport() === 'stdio';
    document.getElementById('mcp-stdio-fields')?.classList.toggle('hidden', !stdio);
    document.getElementById('mcp-url-fields')?.classList.toggle('hidden', stdio);
    document.getElementById('mcp-scope-field')?.classList.toggle('hidden', stdio);
}

function setMcpAdvancedOpen(open) {
    document.getElementById('mcp-advanced-fields')?.classList.toggle('hidden', !open);
    const icon = document.getElementById('mcp-advanced-icon');
    if (icon) icon.style.transform = open ? 'rotate(90deg)' : '';
}

function clearMcpResult() {
    setMcpSaveAnyway(false);
    const result = document.getElementById('mcp-test-result');
    if (!result) return;
    result.className = 'cap-result hidden mt-4';
    result.innerHTML = '';
}

function showMcpResult(kind, html) {
    const result = document.getElementById('mcp-test-result');
    result.className = `cap-result ${kind} mt-4`;
    result.innerHTML = html;
    result.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
}

function showMcpError(message) {
    showMcpResult('fail', `
        <div class="flex items-start gap-2">
            <i class="fas fa-circle-exclamation mt-0.5"></i>
            <span class="flex-1 min-w-0 break-words">${escapeHtml(message)}</span>
        </div>`);
}

function fillMcpEditor(server) {
    const s = server || {};
    const nameEl = document.getElementById('mcp-field-name');
    nameEl.value = s.name || '';
    nameEl.disabled = !!s.name;
    const type = s.type || (s.url ? 'sse' : 'stdio');
    initDropdown(document.getElementById('mcp-field-type'), mcpTransportOptions(), type, syncMcpEditorTransport);
    document.getElementById('mcp-field-command').value = s.command || '';
    document.getElementById('mcp-field-args').value = (s.args || []).join('\n');
    document.getElementById('mcp-field-env').value = objectToKv(s.env);
    document.getElementById('mcp-field-url').value = s.url || '';
    document.getElementById('mcp-field-headers').value = objectToKv(s.headers);
    document.getElementById('mcp-field-scope').value = s.scope || '';
    document.getElementById('mcp-field-prefix').value = s.tool_name_prefix || '';
    document.getElementById('mcp-field-timeout').value = s.timeout || '';
    document.getElementById('mcp-field-disabled').checked = !!s.disabled || s.status === 'disabled';
    setMcpAdvancedOpen(!!(s.tool_name_prefix || s.timeout || s.scope));
    syncMcpEditorTransport();
}

function readMcpEditor() {
    const type = mcpEditorTransport();
    const cfg = {
        name: document.getElementById('mcp-field-name').value.trim(),
        type,
    };
    const prefix = document.getElementById('mcp-field-prefix').value;
    if (prefix) cfg.tool_name_prefix = prefix;
    if (document.getElementById('mcp-field-disabled').checked) cfg.disabled = true;
    const timeout = document.getElementById('mcp-field-timeout').value.trim();
    if (timeout) cfg.timeout = Number(timeout);
    if (type === 'stdio') {
        cfg.command = document.getElementById('mcp-field-command').value.trim();
        const args = document.getElementById('mcp-field-args').value.split(/\r?\n/).map(s => s.trim()).filter(Boolean);
        if (args.length) cfg.args = args;
        const env = kvToObject(document.getElementById('mcp-field-env').value);
        if (Object.keys(env).length) cfg.env = env;
    } else {
        cfg.url = document.getElementById('mcp-field-url').value.trim();
        const headers = kvToObject(document.getElementById('mcp-field-headers').value);
        if (Object.keys(headers).length) cfg.headers = headers;
        const scope = document.getElementById('mcp-field-scope').value.trim();
        if (scope) cfg.scope = scope;
    }
    return cfg;
}

/** A server as it is written in mcp.json: no name, no runtime fields, no empty values. */
function mcpConfigForJson(cfg) {
    const out = {};
    Object.entries(cfg || {}).forEach(([key, value]) => {
        if (key === 'name' || key === 'status') return;
        if (key === 'type' && value === 'stdio') return;
        if (value === '' || value === null || value === undefined || value === false) return;
        if (Array.isArray(value) && !value.length) return;
        if (typeof value === 'object' && !Array.isArray(value) && !Object.keys(value).length) return;
        out[key] = value;
    });
    return out;
}

function mcpServersToJson(servers) {
    const map = {};
    servers.forEach(s => { map[s.name || 'my-server'] = mcpConfigForJson(s); });
    return JSON.stringify({ mcpServers: map }, null, 2);
}

/**
 * Read the JSON pane. Accepts the {"mcpServers": {...}} file format that MCP
 * directories publish, a bare {name: config} map, a list, or one config that
 * carries its own "name".
 */
function parseMcpJson(text) {
    const raw = String(text || '').trim();
    if (!raw) throw new Error(t('mcp_json_empty'));
    let obj;
    try {
        obj = JSON.parse(raw);
    } catch (err) {
        throw new Error(`${t('mcp_json_invalid')}: ${err.message}`);
    }
    const fromMap = (map) => Object.entries(map).map(([name, cfg]) => {
        if (!cfg || typeof cfg !== 'object' || Array.isArray(cfg)) {
            throw new Error(`${t('mcp_json_invalid')}: ${name}`);
        }
        return { ...cfg, name };
    });
    let servers;
    if (Array.isArray(obj)) {
        servers = obj;
    } else if (obj && typeof obj === 'object') {
        if (obj.mcpServers && typeof obj.mcpServers === 'object') {
            servers = fromMap(obj.mcpServers);
        } else if ('command' in obj || 'url' in obj || 'serverUrl' in obj) {
            if (!obj.name) throw new Error(t('mcp_json_need_name'));
            servers = [obj];
        } else {
            servers = fromMap(obj);
        }
    } else {
        throw new Error(t('mcp_json_invalid'));
    }
    servers = servers.map(s => {
        const cfg = { ...s };
        if (!cfg.url && cfg.serverUrl) cfg.url = cfg.serverUrl;
        delete cfg.serverUrl;
        delete cfg.status;
        return cfg;
    });
    if (!servers.length) throw new Error(t('mcp_json_empty'));
    return servers;
}

function switchMcpTab(tab) {
    if (tab === mcpEditorTab) return;
    const jsonEl = document.getElementById('mcp-field-json');
    if (tab === 'json') {
        const cfg = readMcpEditor();
        const touched = cfg.name || cfg.command || cfg.url;
        if (touched) jsonEl.value = mcpServersToJson([cfg]);
    } else if (jsonEl.value.trim()) {
        let servers;
        try {
            servers = parseMcpJson(jsonEl.value);
        } catch (err) {
            showMcpError(err.message);
            return;
        }
        if (servers.length > 1) {
            showMcpError(t('mcp_json_multi_to_form'));
            return;
        }
        const next = { ...servers[0] };
        if (mcpEditorOriginalName) next.name = mcpEditorOriginalName;
        fillMcpEditor(next);
        document.getElementById('mcp-field-name').disabled = !!mcpEditorOriginalName;
    }
    clearMcpResult();
    showMcpTab(tab);
    if (tab === 'json') jsonEl.focus();
}

function showMcpTab(tab) {
    mcpEditorTab = tab;
    document.querySelectorAll('[data-mcp-tab]').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.mcpTab === tab);
    });
    document.getElementById('mcp-pane-form').classList.toggle('hidden', tab !== 'form');
    document.getElementById('mcp-pane-json').classList.toggle('hidden', tab !== 'json');
}

/** The servers the editor currently describes, whichever tab is showing. */
function readMcpEditorServers() {
    if (mcpEditorTab === 'json') {
        const servers = parseMcpJson(document.getElementById('mcp-field-json').value);
        if (mcpEditorOriginalName && servers.length > 1) throw new Error(t('mcp_json_edit_single'));
        return servers;
    }
    const cfg = readMcpEditor();
    if (!cfg.name) throw new Error(t('mcp_name_required'));
    return [cfg];
}

function openMcpEditor(server) {
    mcpEditorOriginalName = server ? server.name : null;
    showMcpTab('form');
    fillMcpEditor(server);
    document.getElementById('mcp-field-json').value = server ? mcpServersToJson([server]) : '';
    clearMcpResult();
    const title = document.getElementById('mcp-editor-title');
    const key = server ? 'mcp_edit' : 'mcp_add_title';
    title.dataset.i18n = key;
    title.textContent = t(key);
    document.getElementById('mcp-editor-overlay').classList.remove('hidden');
    if (!server) setTimeout(() => document.getElementById('mcp-field-name')?.focus(), 30);
}

function closeMcpEditor() {
    document.getElementById('mcp-editor-overlay').classList.add('hidden');
    document.getElementById('mcp-field-type')?.classList.remove('open');
    mcpEditorOriginalName = null;
}

async function persistMcpServers(servers) {
    const data = await postJson('/api/mcp/servers', { servers }, 'PUT');
    if (data.status !== 'success') throw new Error(data.message || t('mcp_save_error'));
    mcpServersCache = data.servers || servers;
    mcpPollDeadline = 0;
    loadMcpSection();
    return data;
}

/** After a failed check, the next save skips it: the user has seen why and chose to keep the config. */
function setMcpSaveAnyway(on) {
    if (mcpSaveAnyway === on) return;
    mcpSaveAnyway = on;
    const btn = document.getElementById('mcp-editor-save');
    if (!btn) return;
    const key = on ? 'mcp_save_anyway' : 'mcp_save';
    btn.dataset.i18n = key;
    btn.textContent = t(key);
}

async function saveMcpEditor() {
    const btn = document.getElementById('mcp-editor-save');
    const testBtn = document.getElementById('mcp-editor-test');
    if (btn.disabled) return;
    let servers;
    try {
        servers = readMcpEditorServers();
    } catch (err) {
        showMcpError(err.message);
        return;
    }
    const incoming = new Set(servers.map(s => s.name));
    if (!mcpEditorOriginalName) {
        const clash = mcpServersCache.filter(s => incoming.has(s.name)).map(s => s.name);
        if (clash.length) {
            showMcpError(t('mcp_name_exists').replace('{name}', clash.join(', ')));
            return;
        }
    }
    setButtonBusy(btn, true);
    setButtonBusy(testBtn, true);
    try {
        let notice = t('mcp_saved');
        const active = servers.filter(s => !s.disabled);
        if (!mcpSaveAnyway && active.length) {
            const probes = await runMcpCheck(active);
            // A server waiting for authorization can only be authorized once saved.
            if (!probes.every(p => p.ok || p.needs_auth)) {
                appendMcpResultNote(t('mcp_check_failed'));
                setMcpSaveAnyway(true);
                return;
            }
            const toolCount = probes.reduce((sum, p) => sum + (p.tools || []).length, 0);
            if (toolCount) notice = t('mcp_saved_tools').replace('{n}', toolCount);
        }
        const next = mcpServersCache.filter(s => s.name !== mcpEditorOriginalName && !incoming.has(s.name));
        await persistMcpServers(next.concat(servers));
        closeMcpEditor();
        _wsToast(notice);
    } catch (err) {
        showMcpError(err.message || t('mcp_save_error'));
    } finally {
        setButtonBusy(btn, false);
        setButtonBusy(testBtn, false);
    }
}

function renderMcpToolList(tools) {
    if (!tools.length) {
        return `<p class="mt-2 text-xs opacity-80">${escapeHtml(t('mcp_test_no_tools'))}</p>`;
    }
    const chips = tools.map(tool => `<span class="cap-chip" title="${escapeHtml(tool.description || tool.name)}">${escapeHtml(tool.name)}</span>`).join('');
    return `
        <p class="mt-2.5 mb-1.5 text-xs font-medium opacity-80">${escapeHtml(t('mcp_test_tools'))} (${tools.length})</p>
        <div class="flex flex-wrap gap-1.5 max-h-40 overflow-y-auto">${chips}</div>`;
}

/** One probe's outcome. In a mixed batch the box is neutral, so each icon carries its own color. */
function renderMcpProbe(probe, withName, mixed) {
    const tools = (probe.tools || []).filter(x => x && x.name);
    const name = withName ? `<span class="font-mono">${escapeHtml(probe.name)}</span><span class="opacity-50">·</span>` : '';
    if (probe.ok) {
        const color = mixed ? 'text-emerald-500' : '';
        return `
            <div class="flex items-center gap-2 font-medium">
                <i class="fas fa-circle-check ${color}"></i>${name}<span>${escapeHtml(t('mcp_test_ok'))}</span>
            </div>
            ${renderMcpToolList(tools)}`;
    }
    const color = mixed ? 'text-red-500' : '';
    const detail = probe.needs_auth ? t('mcp_test_needs_auth') : (probe.error || '');
    return `
        <div class="flex items-center gap-2 font-medium">
            <i class="fas fa-circle-xmark ${color}"></i>${name}<span>${escapeHtml(t('mcp_test_fail'))}</span>
        </div>
        ${detail ? `<p class="mt-1.5 text-xs break-words opacity-90">${escapeHtml(detail)}</p>` : ''}`;
}

async function probeMcpServer(cfg) {
    try {
        const data = await postJson('/api/mcp/servers/test', { server: { ...cfg, disabled: false } });
        return { name: cfg.name, ...data };
    } catch (err) {
        return { name: cfg.name, ok: false, error: err.message || '' };
    }
}

/** Probe every server and show the outcome in the result box. */
async function runMcpCheck(servers) {
    showMcpResult('info', `
        <div class="flex items-center gap-2">
            <i class="fas fa-spinner fa-spin text-xs"></i><span>${escapeHtml(t('mcp_testing'))}</span>
        </div>`);
    const probes = await Promise.all(servers.map(probeMcpServer));
    const okCount = probes.filter(p => p.ok).length;
    const mixed = okCount > 0 && okCount < probes.length;
    const multi = probes.length > 1;
    const html = probes.map(p => `<div class="${multi ? 'py-2 first:pt-0 last:pb-0' : ''}">${renderMcpProbe(p, multi, mixed)}</div>`).join(
        multi ? '<div class="border-t border-current opacity-10"></div>' : '');
    showMcpResult(mixed ? 'info' : (okCount ? 'ok' : 'fail'), html);
    return probes;
}

function appendMcpResultNote(message) {
    const result = document.getElementById('mcp-test-result');
    if (!result) return;
    result.insertAdjacentHTML('beforeend',
        `<div class="mt-2.5 mb-2 border-t border-current opacity-10"></div><p class="text-xs font-medium">${escapeHtml(message)}</p>`);
    result.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
}

async function testMcpEditor() {
    const btn = document.getElementById('mcp-editor-test');
    if (btn.disabled) return;
    let servers;
    try {
        servers = readMcpEditorServers();
    } catch (err) {
        showMcpError(err.message);
        return;
    }
    setButtonBusy(btn, true);
    const icon = document.getElementById('mcp-editor-test-icon');
    icon.className = 'fas fa-spinner fa-spin text-xs';
    try {
        await runMcpCheck(servers);
    } finally {
        setButtonBusy(btn, false);
        icon.className = 'fas fa-plug-circle-check text-xs';
    }
}

function deleteMcpServer(name) {
    showConfirmDialog({
        title: t('mcp_delete'),
        message: t('mcp_delete_confirm'),
        okText: t('mcp_delete'),
        onConfirm: async () => {
            try {
                await persistMcpServers(mcpServersCache.filter(s => s.name !== name));
            } catch (err) {
                _wsToast(err.message || t('mcp_save_error'));
            }
        },
    });
}

// ---------------------------------------------------------------------
// Add skill: fetch from a market or upload, preview, then install
// ---------------------------------------------------------------------

const SKILL_SOURCES = {
    hub: { labelKey: 'skill_value_hub', placeholder: 'skill-name', hintKey: 'skill_hint_hub', link: 'https://skills.cowagent.ai/' },
    github: { labelKey: 'skill_value_github', placeholder: 'https://github.com/owner/repo/tree/main/skills/my-skill', hintKey: 'skill_hint_github' },
    clawhub: { labelKey: 'skill_value_clawhub', placeholder: 'skill-name', hintKey: 'skill_hint_clawhub', link: 'https://clawhub.ai/skills' },
};

const SKILL_SOURCE_LABELS = {
    cowhub: 'Cow Skill Hub', github: 'GitHub', clawhub: 'ClawHub', url: 'URL',
};

const SKILL_UPLOAD_MAX_BYTES = 50 * 1024 * 1024;

const skillAdd = {
    tab: 'market',
    source: 'hub',
    step: 'input',
    token: null,
    skills: [],
    selected: new Set(),
    busy: false,
};

function bindSkillAddUi() {
    const on = (id, evt, fn) => document.getElementById(id)?.addEventListener(evt, fn);
    on('skill-add-btn', 'click', openSkillAdd);
    on('skill-add-close', 'click', closeSkillAdd);
    on('skill-add-cancel', 'click', closeSkillAdd);
    on('skill-add-back', 'click', backToSkillInput);
    on('skill-add-primary', 'click', onSkillAddPrimary);
    on('skill-add-overlay', 'click', (e) => { if (e.target.id === 'skill-add-overlay') closeSkillAdd(); });
    document.querySelectorAll('[data-skill-tab]').forEach(btn => {
        btn.addEventListener('click', () => switchSkillTab(btn.dataset.skillTab));
    });
    document.querySelectorAll('.skill-source-opt').forEach(btn => {
        btn.addEventListener('click', () => setSkillSource(btn.dataset.source));
    });
    on('skill-value-input', 'input', () => { hideSkillInputError(); syncSkillAddFooter(); });
    on('skill-value-input', 'keydown', (e) => {
        if (e.key === 'Enter') { e.preventDefault(); fetchSkillPreview(); }
    });
    on('skill-preview-all', 'change', (e) => {
        skillAdd.selected = e.target.checked ? new Set(skillAdd.skills.map(s => s.name)) : new Set();
        renderSkillPreviewList();
    });

    on('skill-pick-file', 'click', () => document.getElementById('skill-file-input').click());
    on('skill-pick-folder', 'click', () => document.getElementById('skill-folder-input').click());
    on('skill-file-input', 'change', (e) => {
        const files = Array.from(e.target.files || []).map(f => ({ file: f, path: f.name }));
        e.target.value = '';
        uploadSkillFiles(files);
    });
    on('skill-folder-input', 'change', (e) => {
        const files = Array.from(e.target.files || []).map(f => ({ file: f, path: f.webkitRelativePath || f.name }));
        e.target.value = '';
        uploadSkillFiles(files);
    });

    const zone = document.getElementById('skill-dropzone');
    if (zone) {
        ['dragenter', 'dragover'].forEach(evt => zone.addEventListener(evt, (e) => {
            e.preventDefault();
            if (!skillAdd.busy) zone.classList.add('dragover');
        }));
        ['dragleave', 'drop'].forEach(evt => zone.addEventListener(evt, (e) => {
            e.preventDefault();
            zone.classList.remove('dragover');
        }));
        zone.addEventListener('drop', async (e) => {
            if (skillAdd.busy) return;
            const files = await collectDroppedFiles(e.dataTransfer);
            uploadSkillFiles(files);
        });
    }
}

function openSkillAdd() {
    skillAdd.tab = 'market';
    skillAdd.step = 'input';
    skillAdd.token = null;
    skillAdd.skills = [];
    skillAdd.selected = new Set();
    skillAdd.busy = false;
    document.getElementById('skill-value-input').value = '';
    switchSkillTab('market');
    setSkillSource('hub');
    showSkillStep('input');
    document.getElementById('skill-add-overlay').classList.remove('hidden');
    setTimeout(() => document.getElementById('skill-value-input')?.focus(), 30);
}

function closeSkillAdd() {
    if (skillAdd.busy) return;
    discardSkillPreview();
    document.getElementById('skill-add-overlay').classList.add('hidden');
}

function discardSkillPreview() {
    if (!skillAdd.token) return;
    const token = skillAdd.token;
    skillAdd.token = null;
    postJson('/api/skills', { action: 'discard', token }).catch(() => {});
}

function switchSkillTab(tab) {
    if (skillAdd.busy) return;
    skillAdd.tab = tab;
    document.querySelectorAll('[data-skill-tab]').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.skillTab === tab);
    });
    document.getElementById('skill-pane-market').classList.toggle('hidden', tab !== 'market');
    document.getElementById('skill-pane-upload').classList.toggle('hidden', tab !== 'upload');
    hideSkillInputError();
    syncSkillAddFooter();
}

function setSkillSource(source) {
    const meta = SKILL_SOURCES[source];
    if (!meta) return;
    skillAdd.source = source;
    document.querySelectorAll('.skill-source-opt').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.source === source);
    });
    const label = document.getElementById('skill-value-label');
    label.dataset.i18n = meta.labelKey;
    label.textContent = t(meta.labelKey);
    const input = document.getElementById('skill-value-input');
    input.placeholder = meta.placeholder;
    const hint = document.getElementById('skill-source-hint');
    const link = meta.link
        ? ` <a href="${meta.link}" target="_blank" rel="noopener noreferrer" class="text-primary-500 hover:text-primary-600">${escapeHtml(meta.link.replace(/^https:\/\/|\/$/g, ''))}</a>`
        : '';
    hint.innerHTML = escapeHtml(t(meta.hintKey)) + link;
    hideSkillInputError();
    input.focus();
}

function showSkillInputError(msg) {
    const el = document.getElementById('skill-input-error');
    el.textContent = msg;
    el.classList.remove('hidden');
}

function hideSkillInputError() {
    document.getElementById('skill-input-error')?.classList.add('hidden');
}

function showSkillStep(step) {
    skillAdd.step = step;
    ['input', 'preview', 'done'].forEach(name => {
        document.getElementById(`skill-step-${name}`).classList.toggle('hidden', name !== step);
    });
    const subtitle = document.getElementById('skill-add-subtitle');
    if (step === 'preview') {
        subtitle.textContent = t('skill_preview_title');
        subtitle.classList.remove('hidden');
    } else {
        subtitle.classList.add('hidden');
    }
    syncSkillAddFooter();
}

function setSkillAddBusy(busy) {
    skillAdd.busy = busy;
    document.getElementById('skill-add-primary-spin').classList.toggle('hidden', !busy);
    const zoneIcon = document.getElementById('skill-dropzone-icon');
    if (zoneIcon) {
        zoneIcon.className = busy && skillAdd.tab === 'upload' && skillAdd.step === 'input'
            ? 'fas fa-spinner fa-spin text-primary-500'
            : 'fas fa-file-arrow-up text-slate-400';
    }
    syncSkillAddFooter();
}

function syncSkillAddFooter() {
    const primary = document.getElementById('skill-add-primary');
    const label = document.getElementById('skill-add-primary-label');
    const cancel = document.getElementById('skill-add-cancel');
    const back = document.getElementById('skill-add-back');
    back.classList.toggle('hidden', skillAdd.step !== 'preview');
    back.disabled = skillAdd.busy;
    cancel.classList.toggle('hidden', skillAdd.step === 'done');
    cancel.disabled = skillAdd.busy;

    let text = '';
    let show = true;
    let enabled = !skillAdd.busy;
    if (skillAdd.step === 'input') {
        if (skillAdd.tab === 'upload') {
            show = skillAdd.busy;
            text = t('skill_uploading');
        } else {
            text = t(skillAdd.busy ? 'skill_fetching' : 'skill_fetch');
            enabled = enabled && !!document.getElementById('skill-value-input').value.trim();
        }
    } else if (skillAdd.step === 'preview') {
        const n = skillAdd.selected.size;
        text = skillAdd.busy ? t('skill_installing') : t('skill_confirm_install_n').replace('{n}', n);
        enabled = enabled && n > 0;
    } else {
        text = t('skill_done');
    }
    primary.classList.toggle('hidden', !show);
    primary.disabled = !enabled;
    label.textContent = text;
}

function onSkillAddPrimary() {
    if (skillAdd.step === 'input') fetchSkillPreview();
    else if (skillAdd.step === 'preview') confirmSkillInstall();
    else finishSkillAdd();
}

async function fetchSkillPreview() {
    if (skillAdd.busy || skillAdd.tab !== 'market') return;
    const value = document.getElementById('skill-value-input').value.trim();
    if (!value) return;
    hideSkillInputError();
    setSkillAddBusy(true);
    try {
        const data = await postJson('/api/skills', { action: 'preview', source: skillAdd.source, value });
        if (data.status !== 'success') throw new Error(data.message || t('skill_install_error'));
        showSkillPreview(data);
    } catch (err) {
        showSkillInputError(err.message || t('skill_install_error'));
    } finally {
        setSkillAddBusy(false);
    }
}

/** Walk a drop: plain files, or folders read through the entries API. */
async function collectDroppedFiles(dataTransfer) {
    const items = Array.from(dataTransfer?.items || []);
    const entries = items.map(item => item.webkitGetAsEntry && item.webkitGetAsEntry()).filter(Boolean);
    if (!entries.length) {
        return Array.from(dataTransfer?.files || []).map(f => ({ file: f, path: f.name }));
    }
    const out = [];
    const readAll = (reader) => new Promise((resolve) => {
        const acc = [];
        const next = () => reader.readEntries((batch) => {
            if (!batch.length) { resolve(acc); return; }
            acc.push(...batch);
            next();
        }, () => resolve(acc));
        next();
    });
    const walk = async (entry, prefix) => {
        if (entry.isFile) {
            const file = await new Promise((resolve) => entry.file(resolve, () => resolve(null)));
            if (file) out.push({ file, path: prefix + file.name });
        } else if (entry.isDirectory) {
            const children = await readAll(entry.createReader());
            for (const child of children) await walk(child, `${prefix}${entry.name}/`);
        }
    };
    for (const entry of entries) await walk(entry, '');
    return out;
}

async function uploadSkillFiles(files) {
    if (skillAdd.busy || !files.length) return;
    hideSkillInputError();
    const total = files.reduce((sum, f) => sum + (f.file.size || 0), 0);
    if (total > SKILL_UPLOAD_MAX_BYTES) {
        showSkillInputError(t('skill_upload_too_large'));
        return;
    }
    const form = new FormData();
    files.forEach(({ file, path }) => {
        form.append('files', file, file.name);
        form.append('paths', path);
    });
    setSkillAddBusy(true);
    try {
        const res = await fetch('/api/skills/upload', { method: 'POST', body: form });
        const data = await res.json();
        if (data.status !== 'success') throw new Error(data.message || t('skill_install_error'));
        showSkillPreview(data);
    } catch (err) {
        showSkillInputError(err.message || t('skill_install_error'));
    } finally {
        setSkillAddBusy(false);
    }
}

function showSkillPreview(data) {
    discardSkillPreview();
    skillAdd.token = data.token;
    skillAdd.skills = data.skills || [];
    skillAdd.selected = new Set(skillAdd.skills.map(s => s.name));
    const multi = skillAdd.skills.length > 1;
    document.getElementById('skill-preview-count').textContent =
        t('skill_preview_found').replace('{n}', skillAdd.skills.length);
    const allWrap = document.getElementById('skill-preview-all-wrap');
    allWrap.classList.toggle('hidden', !multi);
    allWrap.classList.toggle('flex', multi);
    document.getElementById('skill-preview-error').classList.add('hidden');
    renderSkillPreviewList();
    showSkillStep('preview');
}

function formatBytes(bytes) {
    if (!bytes) return '0 B';
    const units = ['B', 'KB', 'MB', 'GB'];
    let n = bytes;
    let i = 0;
    while (n >= 1024 && i < units.length - 1) { n /= 1024; i++; }
    return `${n >= 10 || i === 0 ? Math.round(n) : n.toFixed(1)} ${units[i]}`;
}

function skillSourceLabel(source) {
    if (!source) return '';
    if (source === 'local') return t('skill_source_local');
    return SKILL_SOURCE_LABELS[source] || source;
}

function renderSkillPreviewMd(sk) {
    if (!sk.has_skill_md) {
        return `<p class="text-xs text-slate-400">${escapeHtml(t('skill_preview_no_md'))}</p>`;
    }
    const { fields, body } = parseSkillFrontmatter(sk.skill_md);
    const rows = fields.map(([key, value]) => `
        <div class="flex gap-3 text-xs">
            <span class="flex-shrink-0 w-20 font-medium text-slate-400 dark:text-slate-500">${escapeHtml(key)}</span>
            <span class="flex-1 min-w-0 text-slate-600 dark:text-slate-300 break-words">${escapeHtml(value)}</span>
        </div>`).join('');
    const header = rows ? `<div class="mb-3 pb-3 border-b border-slate-200/70 dark:border-white/10 space-y-1">${rows}</div>` : '';
    const truncated = sk.skill_md_truncated
        ? `<p class="mt-3 text-xs text-slate-400">${escapeHtml(t('skill_preview_truncated'))}</p>` : '';
    return `${header}<div class="msg-content">${renderMarkdown(body || '')}</div>${truncated}`;
}

function renderSkillPreviewList() {
    const listEl = document.getElementById('skill-preview-list');
    const multi = skillAdd.skills.length > 1;
    listEl.innerHTML = '';
    skillAdd.skills.forEach(sk => {
        const selected = skillAdd.selected.has(sk.name);
        const card = document.createElement('div');
        card.className = 'skill-preview-card' + (selected ? '' : ' unselected');
        const title = sk.display_name || sk.name;
        const extra = [
            `<span><i class="far fa-file mr-1"></i>${escapeHtml(t('skill_preview_files').replace('{n}', sk.file_count))}</span>`,
            `<span>${escapeHtml(formatBytes(sk.size))}</span>`,
        ];
        const source = skillSourceLabel(sk.source);
        if (source) extra.push(`<span>${escapeHtml(source)}</span>`);
        card.innerHTML = `
            <div class="flex items-start gap-3 p-4">
                ${multi ? `<input type="checkbox" data-select class="mt-2.5 rounded accent-primary-500 cursor-pointer" ${selected ? 'checked' : ''}>` : ''}
                <div class="w-9 h-9 rounded-lg bg-primary-50 dark:bg-primary-900/20 flex items-center justify-center flex-shrink-0">
                    <i class="fas fa-bolt text-primary-500 text-sm"></i>
                </div>
                <div class="flex-1 min-w-0">
                    <div class="flex items-center gap-2 flex-wrap">
                        <span class="font-medium text-sm text-slate-800 dark:text-slate-100">${escapeHtml(title)}</span>
                        ${title !== sk.name ? `<span class="text-xs font-mono text-slate-400">${escapeHtml(sk.name)}</span>` : ''}
                        ${sk.exists ? `<span class="px-1.5 py-0.5 rounded text-[10px] font-medium bg-amber-50 text-amber-600 dark:bg-amber-900/20 dark:text-amber-400">${escapeHtml(t('skill_preview_exists'))}</span>` : ''}
                    </div>
                    <p class="text-xs text-slate-500 dark:text-slate-400 mt-1 line-clamp-3">${escapeHtml(sk.description || '--')}</p>
                    <div class="flex items-center gap-2.5 mt-2 text-[11px] text-slate-400 dark:text-slate-500">${extra.join('<span class="opacity-40">·</span>')}</div>
                    <div class="flex items-center gap-1 mt-2 -ml-2">
                        <button type="button" data-toggle="md" class="cap-link-btn">
                            <i class="fas fa-chevron-right text-[9px] transition-transform"></i><span>SKILL.md</span>
                        </button>
                        <button type="button" data-toggle="files" class="cap-link-btn">
                            <i class="fas fa-chevron-right text-[9px] transition-transform"></i><span>${escapeHtml(t('skill_preview_show_files'))}</span>
                        </button>
                    </div>
                </div>
            </div>
            <div data-pane="md" class="skill-preview-md hidden"></div>
            <div data-pane="files" class="skill-preview-files hidden"></div>`;

        const panes = {
            md: card.querySelector('[data-pane="md"]'),
            files: card.querySelector('[data-pane="files"]'),
        };
        const toggle = (which, open) => {
            const pane = panes[which];
            const isOpen = open !== undefined ? open : pane.classList.contains('hidden');
            if (isOpen && !pane.dataset.rendered) {
                if (which === 'md') {
                    pane.innerHTML = renderSkillPreviewMd(sk);
                    applyHighlighting(pane);
                } else {
                    const more = sk.file_count > sk.files.length
                        ? `<div class="opacity-60">… +${sk.file_count - sk.files.length}</div>` : '';
                    pane.innerHTML = sk.files.map(f => `<div class="truncate">${escapeHtml(f)}</div>`).join('') + more;
                }
                pane.dataset.rendered = '1';
            }
            pane.classList.toggle('hidden', !isOpen);
            const icon = card.querySelector(`[data-toggle="${which}"] i`);
            if (icon) icon.style.transform = isOpen ? 'rotate(90deg)' : '';
        };
        card.querySelectorAll('[data-toggle]').forEach(btn => {
            btn.addEventListener('click', () => toggle(btn.dataset.toggle));
        });
        const checkbox = card.querySelector('[data-select]');
        if (checkbox) {
            checkbox.addEventListener('change', () => {
                if (checkbox.checked) skillAdd.selected.add(sk.name);
                else skillAdd.selected.delete(sk.name);
                card.classList.toggle('unselected', !checkbox.checked);
                document.getElementById('skill-preview-all').checked =
                    skillAdd.selected.size === skillAdd.skills.length;
                syncSkillAddFooter();
            });
        }
        if (!multi) toggle('md', true);
        listEl.appendChild(card);
    });
    document.getElementById('skill-preview-all').checked = skillAdd.selected.size === skillAdd.skills.length;
    syncSkillAddFooter();
}

function backToSkillInput() {
    if (skillAdd.busy) return;
    discardSkillPreview();
    skillAdd.skills = [];
    skillAdd.selected = new Set();
    showSkillStep('input');
}

async function confirmSkillInstall() {
    if (skillAdd.busy || !skillAdd.token || !skillAdd.selected.size) return;
    const errorEl = document.getElementById('skill-preview-error');
    errorEl.classList.add('hidden');
    setSkillAddBusy(true);
    try {
        const data = await postJson('/api/skills', {
            action: 'confirm',
            token: skillAdd.token,
            names: Array.from(skillAdd.selected),
        });
        if (data.status !== 'success') throw new Error(data.message || t('skill_install_error'));
        skillAdd.token = null;
        showSkillDone(data.installed || []);
    } catch (err) {
        errorEl.textContent = err.message || t('skill_install_error');
        errorEl.classList.remove('hidden');
    } finally {
        setSkillAddBusy(false);
    }
}

function showSkillDone(installed) {
    skillAdd.installed = installed;
    const byName = Object.fromEntries(skillAdd.skills.map(s => [s.name, s]));
    document.getElementById('skill-done-desc').textContent =
        t('skill_installed_desc').replace('{n}', installed.length);
    document.getElementById('skill-done-names').innerHTML = installed.map(name => {
        const sk = byName[name] || {};
        return `<span class="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs bg-slate-100 dark:bg-white/10 text-slate-700 dark:text-slate-200">
            <i class="fas fa-bolt text-primary-500 text-[10px]"></i>${escapeHtml(sk.display_name || name)}</span>`;
    }).join('');
    showSkillStep('done');
    loadSkillsSection(installed);
}

function finishSkillAdd() {
    document.getElementById('skill-add-overlay').classList.add('hidden');
    const first = (skillAdd.installed || [])[0];
    const card = first && document.querySelector(`#skills-list [data-skill-name="${CSS.escape(first)}"]`);
    if (card) card.scrollIntoView({ behavior: 'smooth', block: 'center' });
}

// ---------------------------------------------------------------------
// Installed skills
// ---------------------------------------------------------------------

function deleteSkill(name) {
    showConfirmDialog({
        title: t('skill_delete'),
        message: t('skill_delete_confirm'),
        okText: t('skill_delete'),
        onConfirm: async () => {
            try {
                const data = await postJson('/api/skills', { action: 'delete', name });
                if (data.status !== 'success') throw new Error(data.message || t('skill_delete_error'));
                loadSkillsSection();
            } catch (err) {
                _wsToast(err.message || t('skill_delete_error'));
            }
        },
    });
}

/** Reload the skill cards; `highlight` names get a brief ring so a fresh install is easy to spot. */
function loadSkillsSection(highlight) {
    const emptyEl = document.getElementById('skills-empty');
    const listEl = document.getElementById('skills-list');
    const badge = document.getElementById('skills-count-badge');
    const fresh = new Set(highlight || []);

    return fetch('/api/skills').then(r => r.json()).then(data => {
        if (data.status !== 'success') return;
        const skills = data.skills || [];
        badge.textContent = skills.length;
        badge.classList.toggle('hidden', skills.length === 0);
        listEl.innerHTML = '';
        if (skills.length === 0) {
            emptyEl.classList.remove('hidden');
            const title = emptyEl.querySelector('p');
            if (title) { title.dataset.i18n = 'skills_empty'; title.textContent = t('skills_empty'); }
            const desc = emptyEl.querySelectorAll('p')[1];
            if (desc) { desc.dataset.i18n = 'skills_empty_hint'; desc.textContent = t('skills_empty_hint'); }
            return;
        }
        emptyEl.classList.add('hidden');

        skills.forEach(sk => {
            const card = document.createElement('div');
            card.className = 'bg-white dark:bg-[#1A1A1A] rounded-xl border border-slate-200 dark:border-white/10 '
                + 'p-4 flex items-start gap-3 transition-opacity cursor-pointer '
                + 'hover:border-slate-300 dark:hover:border-white/20';
            card.dataset.skillName = sk.name;
            card.dataset.skillDesc = sk.description || '';
            card.dataset.skillDisplayName = sk.display_name || '';
            card.dataset.enabled = sk.enabled ? '1' : '0';
            card.dataset.deletable = sk.deletable ? '1' : '0';
            renderSkillCard(card, sk);
            if (fresh.has(sk.name)) {
                card.classList.add('cap-flash');
                setTimeout(() => card.classList.remove('cap-flash'), 2600);
            }
            listEl.appendChild(card);
        });
    }).catch(() => {});
}

function renderSkillCard(card, sk) {
    const enabled = sk.enabled;
    const iconColor = enabled ? 'text-primary-500' : 'text-slate-300 dark:text-slate-600';
    const trackClass = enabled
        ? 'bg-primary-400'
        : 'bg-slate-200 dark:bg-slate-700';
    const thumbTranslate = enabled ? 'translate-x-3' : 'translate-x-0.5';
    card.innerHTML = `
        <div class="w-9 h-9 rounded-lg bg-primary-50 dark:bg-primary-900/20 flex items-center justify-center flex-shrink-0">
            <i class="fas fa-bolt ${iconColor} text-sm"></i>
        </div>
        <div class="flex-1 min-w-0">
            <div class="flex items-center gap-2 mb-1">
                <span class="font-medium text-sm text-slate-700 dark:text-slate-200 truncate flex-1">${escapeHtml(sk.display_name || sk.name)}</span>
                <button
                    data-skill-edit
                    class="flex-shrink-0 p-1 -mx-1 -mt-1.5 -mb-1 rounded text-slate-300 dark:text-slate-600 hover:text-slate-500 dark:hover:text-slate-300 transition-colors"
                    title="${t('skill_edit_hint')}"
                >
                    <i class="fas fa-pen text-[10px]"></i>
                </button>
                ${sk.deletable ? `
                <button
                    data-skill-delete
                    class="flex-shrink-0 p-1 -mx-1 -mt-1.5 -mb-1 rounded text-slate-300 dark:text-slate-600 hover:text-red-500 dark:hover:text-red-400 transition-colors"
                    title="${t('skill_delete')}"
                >
                    <i class="fas fa-trash text-[10px]"></i>
                </button>` : ''}
                <button
                    role="switch"
                    data-skill-switch
                    aria-checked="${enabled}"
                    class="relative inline-flex h-4 w-7 flex-shrink-0 cursor-pointer rounded-full transition-colors duration-200 ease-in-out focus:outline-none ${trackClass}"
                    title="${t(enabled ? 'skill_click_disable' : 'skill_click_enable')}"
                >
                    <span class="inline-block h-3 w-3 mt-0.5 rounded-full bg-white shadow transform transition-transform duration-200 ease-in-out ${thumbTranslate}"></span>
                </button>
            </div>
            <p class="text-xs text-slate-400 dark:text-slate-500 line-clamp-2">${escapeHtml(sk.description || '--')}</p>
        </div>`;

    // Bound here rather than written into the markup above: a skill name comes
    // from its own frontmatter, and one containing a quote would break out of
    // an inline onclick attribute.
    card.title = t('skill_open_hint');
    card.onclick = () => openSkillFile(sk.name);
    const editBtn = card.querySelector('[data-skill-edit]');
    if (editBtn) {
        editBtn.onclick = (e) => {
            e.stopPropagation();
            openSkillFile(sk.name, { edit: true });
        };
    }
    const deleteBtn = card.querySelector('[data-skill-delete]');
    if (deleteBtn) {
        deleteBtn.onclick = (e) => {
            e.stopPropagation();
            deleteSkill(sk.name);
        };
    }
    const sw = card.querySelector('[data-skill-switch]');
    if (sw) {
        sw.onclick = (e) => {
            e.stopPropagation();
            toggleSkill(sk.name, enabled);
        };
    }
}

function toggleSkill(name, currentlyEnabled) {
    const action = currentlyEnabled ? 'close' : 'open';
    const card = document.querySelector(`[data-skill-name="${CSS.escape(name)}"]`);
    if (card) card.style.opacity = '0.5';

    postJson('/api/skills', { action, name })
    .then(data => {
        if (card) card.style.opacity = '1';
        if (data.status !== 'success') {
            _wsToast(t('skill_toggle_error'));
            return;
        }
        if (card) {
            card.dataset.enabled = currentlyEnabled ? '0' : '1';
            renderSkillCard(card, {
                name: name,
                description: card.dataset.skillDesc || '',
                display_name: card.dataset.skillDisplayName || '',
                enabled: !currentlyEnabled,
                deletable: card.dataset.deletable === '1',
            });
        }
    })
    .catch(() => {
        if (card) card.style.opacity = '1';
        _wsToast(t('skill_toggle_error'));
    });
}

// ---------------------------------------------------------------------
// Skill viewer / editor
// ---------------------------------------------------------------------

/** The files of the skill the viewer has open, as `/api/skills/files` listed them. */
let _skillFiles = [];
/** Directories the reader has folded away, by path. Empty means all open. */
let _skillFoldedDirs = new Set();
// Counts the reads the viewer has asked for, so a slow one that lands after the
// reader has already moved on to another file is dropped instead of replacing
// what they are looking at now.
let _skillReadSeq = 0;
// Whether the file list is showing at all. Remembered across sessions: someone
// who reads skills on a narrow window should not have to fold it away again on
// every visit.
const SKILL_FILES_PANEL_KEY = 'cow_skill_files_panel';
let _skillFilesPanelOpen = localStorage.getItem(SKILL_FILES_PANEL_KEY) !== '0';

/**
 * A skill is addressed by name, not by path: which directory a name resolves to
 * is the loader's business, and a builtin skill lives outside the workspace
 * that the file APIs are confined to. `path` then names one file inside that
 * directory, and defaults to the skill's own SKILL.md.
 */
async function skillReadContent(name, path) {
    const query = `name=${encodeURIComponent(name)}`
        + (path ? `&path=${encodeURIComponent(path)}` : '');
    const res = await fetch(`/api/skills/content?${query}`);
    const data = await res.json();
    if (data.status !== 'success') throw new Error(data.message || 'read failed');
    return data;
}

/** Save one of a skill's files. Returns the raw response, a conflict included. */
async function skillWriteContent(name, path, content, expectedMtime) {
    const res = await fetch('/api/skills/content', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            name: name, path: path || '', content: content, expected_mtime: expectedMtime,
        }),
    });
    return res.json();
}

/** The files a skill is made of. Empty on failure: the tree is not the point. */
async function skillListFiles(name) {
    try {
        const res = await fetch(`/api/skills/files?name=${encodeURIComponent(name)}`);
        const data = await res.json();
        return data.status === 'success' ? (data.files || []) : [];
    } catch (e) {
        return [];
    }
}

/** The i18n key explaining why a skill cannot be edited, or null if it can. */
function skillReadonlyReason(data) {
    if (data.editable) return null;
    // Not `source === 'builtin'`: the workspace copy of a builtin skill reads
    // back as `custom` and is refused all the same, so the server says so.
    if (data.ships_with_install) return 'skill_builtin_readonly';
    return docUneditableReason(data);
}

/** Drop the surrounding quotes a YAML scalar may carry. */
function yamlScalar(raw) {
    return raw.trim().replace(/^(['"])(.*)\1$/, '$2');
}

/**
 * Split a skill's SKILL.md into its YAML frontmatter fields and the markdown
 * body. The `---` header is metadata, not prose: fed to the markdown renderer
 * as-is it turns into a giant bold heading and a horizontal rule. Pull it out
 * so the viewer can present name/description as a proper header instead.
 *
 * Frontmatter nests: `metadata.cowagent.requires.anyEnv` is a list four levels
 * down. Read line by line with no regard for indentation, each container key
 * showed up as an empty row and the list under it vanished. So this walks the
 * indentation instead: a nested map becomes one row per leaf, keyed by its
 * dotted path; a list or a block scalar (`|`, `>`) becomes one row with its
 * lines joined. Only leaves are rows - a key that merely holds others has
 * nothing to say on its own. Kept in step with the desktop client's copy.
 *
 * @returns {{fields: Array<[string, string]>, body: string}}
 */
function parseSkillFrontmatter(content) {
    const text = content || '';
    const match = text.match(/^---\s*\r?\n([\s\S]*?)\r?\n---\s*\r?\n?/);
    if (!match) return { fields: [], body: text };

    const fields = [];
    // The key at each indentation level above the current line.
    const path = [];
    // A key whose value is still being collected from the lines below it: the
    // items of a list, or the lines of a block scalar.
    let open = null;

    const flush = () => {
        if (!open) return;
        fields.push([open.key, open.block ? open.items.join(' ').trim() : open.items.join(', ')]);
        open = null;
    };

    for (const raw of match[1].split(/\r?\n/)) {
        const line = raw.trim();
        if (!line) continue;
        const indent = raw.length - raw.trimStart().length;
        // Inside a block scalar a `#` line is text, not a comment.
        if (open && open.block && indent > open.indent) {
            open.items.push(line);
            continue;
        }
        if (line.startsWith('#')) continue;
        // A list's dashes may sit level with their key or under it.
        if (open && !open.block && indent >= open.indent && line.startsWith('- ')) {
            open.items.push(yamlScalar(line.slice(2)));
            continue;
        }
        // Anything else ends an open value: what follows is the next key, or -
        // under a key opened as a possible list - the first key of a map.
        flush();

        while (path.length && path[path.length - 1].indent >= indent) path.pop();
        const idx = line.indexOf(':');
        if (idx === -1) continue;
        const key = yamlScalar(line.slice(0, idx));
        if (!key) continue;
        const dotted = [...path.map(p => p.key), key].join('.');
        const rest = line.slice(idx + 1).trim();

        if (!rest) {
            // A nested map, or a list starting on the next line: the line that
            // follows decides, so open both readings.
            path.push({ indent, key });
            open = { key: dotted, indent, items: [], block: false };
        } else if (/^[|>][-+0-9]*$/.test(rest)) {
            open = { key: dotted, indent, items: [], block: true };
        } else {
            fields.push([dotted, yamlScalar(rest)]);
        }
    }
    flush();

    // A container key opened as a possible list but then held a map instead:
    // its children have their own rows, so drop the empty one it left behind.
    return { fields: fields.filter(([, value]) => value !== ''), body: text.slice(match[0].length) };
}

/** How one of the open skill's files was listed, or null if it is not in the tree. */
function skillFileEntry(path) {
    return _skillFiles.find(file => file.path === path) || null;
}

/**
 * Render one of a skill's files into the viewer.
 *
 * A markdown file - the SKILL.md above all - is rendered as prose, with its
 * frontmatter lifted out into a header: fed to the markdown renderer as-is the
 * `---` block turns into a giant bold heading and a horizontal rule. Anything
 * else is a script or a data file, and reads as code.
 */
function skillRenderBody(doc) {
    const el = document.getElementById('skill-viewer-content');
    if (!el) return;

    const entry = skillFileEntry(doc.path);
    // A bundled asset belongs in the tree - it is part of the skill - but
    // showing it here would only print mojibake. A text file that merely lost a
    // byte to the decoder is still shown, with the read-only badge saying why:
    // partial content beats no content, as it does in the workspace preview.
    if (entry && !entry.text) {
        el.innerHTML = `
            <div class="py-12 flex flex-col items-center gap-2 text-slate-400 dark:text-slate-500">
                <i class="fas fa-file-circle-question text-xl"></i>
                <span class="text-sm">${escapeHtml(t('skill_file_not_text'))}</span>
            </div>`;
        return;
    }

    const isMarkdown = entry ? entry.kind === 'markdown'
                             : /\.(md|markdown)$/i.test(doc.path || '');
    if (!isMarkdown) {
        // Only a real extension names a language: left unguarded a `LICENSE`
        // would be labelled one, and the highlighter asked to find it.
        const filename = (doc.path || '').split('/').pop();
        const ext = filename.includes('.') ? filename.split('.').pop().toLowerCase() : '';
        el.innerHTML = '<div class="msg-content"><pre><code'
            + (ext ? ` class="language-${escapeHtml(ext)}"` : '') + '>'
            + `${escapeHtml(doc.content || '')}</code></pre></div>`;
        applyHighlighting(el);
        return;
    }

    const { fields, body } = parseSkillFrontmatter(doc.content);
    let headerHtml = '';
    if (fields.length) {
        // A dotted path may wrap, but only at its dots. escapeHtml leaves `"`
        // alone, and a third-party SKILL.md picks these keys.
        const rows = fields.map(([key, value]) => `
            <dt title="${escapeHtml(key).replace(/"/g, '&quot;')}">${key.split('.').map(escapeHtml).join('.<wbr>')}</dt>
            <dd>${escapeHtml(value)}</dd>`).join('');
        headerHtml = `<dl class="skill-frontmatter">${rows}</dl>`;
    }

    el.innerHTML = headerHtml + `<div class="msg-content">${renderMarkdown(body || '')}</div>`;
    applyHighlighting(el);
}

const skillEditor = createDocEditor({
    body: () => document.getElementById('skill-viewer-content'),
    buttons: () => ({
        edit: document.getElementById('skill-btn-edit'),
        save: document.getElementById('skill-btn-save'),
        cancel: document.getElementById('skill-btn-cancel'),
    }),
    read: (doc) => skillReadContent(doc.name, doc.path),
    write: (doc, content, mtime) => skillWriteContent(doc.name, doc.path, content, mtime),
    render: (doc) => skillRenderBody(doc),
    canEdit: (doc) => !doc.readonlyKey,
    refusal: skillReadonlyReason,
    onState: (state) => docRenderTitle('skill-viewer-title', skillViewerTitle(), state),
});

/**
 * Say in the header why the file on screen cannot be edited, or say nothing.
 *
 * Per file rather than per skill: the reason a bundled PNG is read-only is not
 * the reason a builtin's SKILL.md is, and the edit button is hidden either way.
 */
function skillShowReadonlyBadge(readonlyKey) {
    const badge = document.getElementById('skill-viewer-readonly');
    if (!badge) return;
    badge.classList.toggle('hidden', !readonlyKey);
    if (!readonlyKey) return;
    // Keep data-i18n in step so a language switch re-translates it.
    badge.dataset.i18n = readonlyKey;
    badge.textContent = t(readonlyKey);
    badge.title = t(readonlyKey);
}

/** What the viewer's header reads: the skill, and which of its files is open. */
function skillViewerTitle() {
    const doc = skillEditor.current();
    if (!doc) return '';
    return doc.path ? `${doc.name}/${doc.path}` : doc.name;
}

/**
 * Open a skill in the viewer: its file tree, and one of its files.
 *
 * @param opts.edit - jump straight into editing, as the pencil on a card does.
 * @param opts.path - which file to show; the skill's SKILL.md by default.
 */
function openSkillFile(name, opts) {
    const startEditing = !!(opts && opts.edit);
    const path = (opts && opts.path) || '';
    const mine = ++_skillReadSeq;
    // The tree is fetched alongside the file rather than after it, so opening a
    // skill is one round trip either way.
    Promise.all([skillReadContent(name, path), skillListFiles(name)]).then(([data, files]) => {
        if (mine !== _skillReadSeq) return;
        const readonlyKey = skillReadonlyReason(data);
        skillShowReadonlyBadge(readonlyKey);
        document.getElementById('skills-panel-list').classList.add('hidden');
        document.getElementById('skills-panel-viewer').classList.remove('hidden');
        _skillFiles = files;
        // Another skill's tree: the folds belonged to the previous one.
        _skillFoldedDirs = new Set();
        skillEditor.open({
            name: data.name || name,
            // As the server resolved it, so the tree's highlight matches the
            // file on screen even when the caller passed no path at all.
            path: data.filename || path,
            content: data.content || '',
            readonlyKey: readonlyKey,
        });
        renderSkillFilesTree();
        // The pencil on a card jumps straight into editing, skipping the
        // read-only view - but only where the skill is actually editable.
        if (startEditing && !readonlyKey) skillEditor.start();
    }).catch(e => {
        if (mine === _skillReadSeq) _wsToast(`${t('skill_load_failed')}: ${e.message}`);
    });
}

/**
 * Draw the open skill's files, indented by the depth the server listed them at.
 *
 * Shown even for a skill that is only its SKILL.md: the panel is what says what
 * a skill is made of, and "one file, this big" is an answer to that. It only
 * goes away when the listing could not be fetched at all, where an empty tree
 * beside the file on screen would just look broken.
 */
function renderSkillFilesTree() {
    const panel = document.getElementById('skill-files-panel');
    const tree = document.getElementById('skill-files-tree');
    if (!panel || !tree) return;

    // One switch for both states, riding the border the list would sit
    // against: the divider while the list is out, the card's own edge once it
    // is folded away. Gone where there is no listing - with nothing to show, a
    // switch that folds nothing away is just a dead button.
    const listed = _skillFiles.length > 0;
    const show = listed && _skillFilesPanelOpen;
    const toggle = document.getElementById('skill-files-toggle');
    if (toggle) {
        toggle.classList.toggle('hidden', !listed);
        toggle.classList.toggle('is-open', show);
        toggle.setAttribute('aria-expanded', String(show));
        // Keep the data-i18n keys in step so a language switch re-translates
        // the tip for the state on screen, not the one the markup started in.
        const tipKey = show ? 'skill_files_collapse' : 'skill_files_expand';
        toggle.dataset.i18nTitle = tipKey;
        toggle.dataset.i18nAriaLabel = tipKey;
        toggle.title = t(tipKey);
        toggle.setAttribute('aria-label', t(tipKey));
        const icon = toggle.querySelector('i');
        if (icon) icon.className = `fas fa-chevron-${show ? 'left' : 'right'}`;
    }
    panel.classList.toggle('hidden', !show);
    if (!show) {
        tree.innerHTML = '';
        return;
    }

    const current = skillEditor.current()?.path;
    tree.innerHTML = '';
    _skillFiles.forEach(file => {
        if (skillPathIsFolded(file.path)) return;
        const folded = _skillFoldedDirs.has(file.path);
        const row = document.createElement('button');
        row.className = 'skill-file-row' + (file.path === current ? ' active' : '')
            + (file.is_dir ? ' skill-file-dir' : '');
        // 6 + the row's 6px inset puts depth 0 under the panel title.
        row.style.paddingLeft = `${6 + file.depth * 13}px`;
        row.title = file.path;
        // A caret only where there is something to fold; the others keep its
        // width so every name in one directory still starts at one column.
        row.innerHTML = (file.is_dir
            ? `<i class="fas fa-chevron-${folded ? 'right' : 'down'} skill-file-caret"></i>`
            : '<span class="skill-file-caret"></span>')
            + `<i class="fas ${file.is_dir ? (folded ? 'fa-folder' : 'fa-folder-open') : 'fa-file-lines'} skill-file-icon"></i>`
            + `<span class="flex-1 min-w-0 truncate">${escapeHtml(file.name)}</span>`
            // Only for files: a directory's own size says nothing about what
            // the tree shows inside it.
            + (file.is_dir ? ''
                : `<span class="skill-file-size">${formatSkillFileSize(file.size)}</span>`);
        // Bound rather than written into an onclick attribute: these names come
        // off disk and may hold a quote.
        row.onclick = file.is_dir
            ? () => toggleSkillDir(file.path)
            : () => selectSkillFile(file.path);
        tree.appendChild(row);
    });
}

/** Whether a folded directory somewhere above this path hides it. */
function skillPathIsFolded(path) {
    for (const dir of _skillFoldedDirs) {
        if (path.startsWith(`${dir}/`)) return true;
    }
    return false;
}

/** Fold a directory away, or open it again. */
function toggleSkillDir(path) {
    if (!_skillFoldedDirs.delete(path)) _skillFoldedDirs.add(path);
    renderSkillFilesTree();
}

/** Show or hide the file list, giving the document the full width. */
function toggleSkillFilesPanel() {
    _skillFilesPanelOpen = !_skillFilesPanelOpen;
    localStorage.setItem(SKILL_FILES_PANEL_KEY, _skillFilesPanelOpen ? '1' : '0');
    renderSkillFilesTree();
}

/** Show another of the open skill's files. */
function selectSkillFile(path) {
    const doc = skillEditor.current();
    if (!doc || doc.path === path) return;
    // The text area is about to be replaced by another file's contents.
    if (!skillEditor.guard(() => selectSkillFile(path))) return;

    const mine = ++_skillReadSeq;
    skillReadContent(doc.name, path).then(data => {
        if (mine !== _skillReadSeq) return;
        const readonlyKey = skillReadonlyReason(data);
        skillShowReadonlyBadge(readonlyKey);
        skillEditor.open({
            name: doc.name,
            path: data.filename || path,
            content: data.content || '',
            readonlyKey: readonlyKey,
        });
        renderSkillFilesTree();
    }).catch(e => {
        if (mine === _skillReadSeq) _wsToast(`${t('skill_load_failed')}: ${e.message}`);
    });
}

function closeSkillViewer() {
    if (!skillEditor.guard(closeSkillViewer)) return;
    resetSkillViewer();
    // A saved edit can change the name and description in the frontmatter, so
    // the cards behind this panel may be out of date.
    loadSkillsSection();
}

/** Drop the viewer and show the list, without asking about unsaved edits. */
function resetSkillViewer() {
    skillEditor.forget();
    _skillFiles = [];
    _skillFoldedDirs = new Set();
    document.getElementById('skill-files-panel')?.classList.add('hidden');
    document.getElementById('skill-files-toggle')?.classList.add('hidden');
    document.getElementById('skills-panel-viewer')?.classList.add('hidden');
    document.getElementById('skills-panel-list')?.classList.remove('hidden');
}

// ---------------------------------------------------------------------
// Creating a skill from a form. Installing an existing one - from the hub,
// GitHub or an upload - is the Add dialog's, with a preview before install.
// ---------------------------------------------------------------------

// The server's own ceilings for a form's attachments, mirrored so a 50 MB
// folder is refused here rather than after being uploaded. See
// SkillService.MAX_UPLOAD_*.
const SKILL_UPLOAD_MAX_FILES = 500;
const SKILL_UPLOAD_MAX_FILE_SIZE = 10 * 1024 * 1024;
const SKILL_UPLOAD_MAX_TOTAL_SIZE = 50 * 1024 * 1024;

let _skillCreateFiles = [];
let _skillCreateBusy = false;
let _skillAttachMenuReady = false;

function openSkillCreateDialog() {
    resetSkillCreateDialog();
    document.getElementById('skill-create-overlay')?.classList.remove('hidden');
    initSkillAttachMenu();
    // A folder picker is Chromium/WebKit only; without it the menu would offer
    // an entry that does nothing.
    const folderOption = document.getElementById('skill-create-folder-option');
    const folderInput = document.getElementById('skill-create-folder');
    folderOption?.classList.toggle('hidden', !(folderInput && 'webkitdirectory' in folderInput));
    document.getElementById('skill-create-name')?.focus();
}

function closeSkillCreateDialog() {
    if (_skillCreateBusy) return;
    document.getElementById('skill-create-overlay')?.classList.add('hidden');
    resetSkillCreateDialog();
}

function resetSkillCreateDialog() {
    ['skill-create-name', 'skill-create-desc', 'skill-create-body'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.value = '';
    });
    _skillCreateFiles = [];
    renderSkillCreateFiles();
    renderSkillNamePreview();
    hideSkillAttachMenu();
    setSkillCreateError('');
}

function setSkillCreateError(message) {
    const el = document.getElementById('skill-create-error');
    if (!el) return;
    el.textContent = message || '';
    el.classList.toggle('hidden', !message);
}

function setSkillCreateBusy(busy) {
    _skillCreateBusy = busy;
    const submit = document.getElementById('skill-create-submit');
    if (submit) submit.disabled = busy;
}

/**
 * The directory name a title reduces to. Mirrors `normalize_skill_name` on the
 * server, so the preview under the field is what actually gets created.
 */
function skillNameSlug(raw) {
    return (raw || '').trim().toLowerCase()
        .replace(/[^a-z0-9]+/g, '-')
        .replace(/^-+|-+$/g, '')
        .slice(0, 64)
        .replace(/-+$/, '');
}

function renderSkillNamePreview() {
    const el = document.getElementById('skill-create-name-preview');
    if (!el) return;
    const typed = (document.getElementById('skill-create-name')?.value || '').trim();
    const slug = skillNameSlug(typed);

    const hint = (key) => {
        el.dataset.i18n = key;
        el.textContent = t(key);
        el.classList.remove('text-red-500');
    };
    if (!typed) return hint('skill_new_name_hint');
    if (!slug) {
        hint('skill_new_name_invalid');
        el.classList.add('text-red-500');
        return;
    }
    if (slug === typed) return hint('skill_new_name_hint');
    // A composed line, so it must not be re-translated over on a language switch.
    el.removeAttribute('data-i18n');
    el.classList.remove('text-red-500');
    el.textContent = `${t('skill_new_name_dir')}: ${slug}`;
}

/**
 * Where an attachment lands inside the skill directory.
 *
 * A folder pick carries the path the file sat at under the chosen folder, so
 * `scripts/` picked as a folder installs as `scripts/`. A loose file has only
 * its own name, and lands beside SKILL.md.
 */
function skillAttachmentPath(file) {
    return file.webkitRelativePath || file.name;
}

/**
 * The files of a picked folder that are worth installing.
 *
 * A directory on disk carries more than what someone wrote: caches, a virtualenv,
 * an editor's dotfiles. Bundling those would install megabytes the skill never
 * uses, and the console's file tree hides them anyway - so the tree would not
 * even show what had been added.
 */
function skillUploadCandidates(files) {
    const noise = ['__pycache__', 'node_modules', 'venv'];
    return files.filter(file => skillAttachmentPath(file).split('/')
        .every(part => !part.startsWith('.') && !noise.includes(part)));
}

/**
 * Open or close the menu behind the attachments button.
 *
 * Two picks behind one button: a native file dialog browses for files or for a
 * directory, never both, so the choice is made before it opens.
 */
function toggleSkillAttachMenu(event) {
    // Or the click would reach the document listener that closes it again.
    event?.stopPropagation();
    document.getElementById('skill-create-attach-menu')?.classList.toggle('hidden');
}

function hideSkillAttachMenu() {
    document.getElementById('skill-create-attach-menu')?.classList.add('hidden');
}

/** Close the attach menu on a click anywhere else. Bound once. */
function initSkillAttachMenu() {
    if (_skillAttachMenuReady) return;
    const menu = document.getElementById('skill-create-attach-menu');
    const btn = document.getElementById('skill-create-attach-btn');
    if (!menu || !btn) return;
    _skillAttachMenuReady = true;
    document.addEventListener('click', event => {
        if (menu.classList.contains('hidden')) return;
        if (menu.contains(event.target) || btn.contains(event.target)) return;
        hideSkillAttachMenu();
    });
}

function selectSkillCreateFiles() {
    pickSkillCreateAttachments('skill-create-files', false);
}

function selectSkillCreateFolder() {
    pickSkillCreateAttachments('skill-create-folder', true);
}

/**
 * Add what one of the attachment inputs picked to the list under the field.
 *
 * @param asFolder - a folder pick, whose noise is left out and whose paths are
 *   kept; a loose pick is taken as chosen, dotfile or not.
 */
function pickSkillCreateAttachments(inputId, asFolder) {
    hideSkillAttachMenu();
    const input = document.getElementById(inputId);
    if (!input) return;
    input.value = '';
    input.onchange = () => {
        const picked = Array.from(input.files || []);
        (asFolder ? skillUploadCandidates(picked) : picked).forEach(file => {
            // One path is one attachment: the same file picked twice does not
            // become two, and two files of that name in different folders stay
            // two.
            const path = skillAttachmentPath(file);
            if (!_skillCreateFiles.some(f => skillAttachmentPath(f) === path)) {
                _skillCreateFiles.push(file);
            }
        });
        renderSkillCreateFiles();
    };
    input.click();
}

function removeSkillCreateFile(index) {
    _skillCreateFiles.splice(index, 1);
    renderSkillCreateFiles();
}

function renderSkillCreateFiles() {
    const list = document.getElementById('skill-create-files-list');
    const empty = document.getElementById('skill-create-files-empty');
    if (!list) return;
    empty?.classList.toggle('hidden', _skillCreateFiles.length > 0);
    list.innerHTML = _skillCreateFiles.map((file, index) => `
        <div class="flex items-center gap-2 rounded-lg bg-slate-50 dark:bg-white/5 border border-slate-200 dark:border-white/10 px-2.5 py-1.5">
            <i class="fas fa-file text-slate-400 text-[10px]"></i>
            <span class="flex-1 min-w-0 text-xs font-mono text-slate-700 dark:text-slate-200 truncate"
                  title="${escapeHtml(skillAttachmentPath(file))}">${escapeHtml(skillAttachmentPath(file))}</span>
            <span class="text-[11px] text-slate-400">${formatSkillFileSize(file.size)}</span>
            <button type="button" onclick="removeSkillCreateFile(${index})"
                    class="text-slate-400 hover:text-red-500 cursor-pointer">
                <i class="fas fa-xmark text-[10px]"></i>
            </button>
        </div>`).join('');
}

function formatSkillFileSize(bytes) {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

/** Check a batch of picked files against the server's caps. '' when they pass. */
function validateSkillUploadFiles(files) {
    if (files.length > SKILL_UPLOAD_MAX_FILES) {
        return t('skill_upload_too_many').replace('{max}', SKILL_UPLOAD_MAX_FILES);
    }
    let total = 0;
    for (const file of files) {
        total += file.size || 0;
        if ((file.size || 0) > SKILL_UPLOAD_MAX_FILE_SIZE) {
            return t('skill_upload_file_too_large')
                .replace('{name}', file.name)
                .replace('{max}', SKILL_UPLOAD_MAX_FILE_SIZE / 1024 / 1024);
        }
    }
    if (total > SKILL_UPLOAD_MAX_TOTAL_SIZE) {
        return t('skill_upload_total_too_large')
            .replace('{max}', SKILL_UPLOAD_MAX_TOTAL_SIZE / 1024 / 1024);
    }
    return '';
}

function submitSkillCreate() {
    if (_skillCreateBusy) return;
    const name = (document.getElementById('skill-create-name')?.value || '').trim();
    const description = (document.getElementById('skill-create-desc')?.value || '').trim();
    const body = document.getElementById('skill-create-body')?.value || '';
    if (!skillNameSlug(name)) return setSkillCreateError(t('skill_new_name_invalid'));
    // The loader drops a skill with no description, so it is required here too.
    if (!description) return setSkillCreateError(t('skill_new_desc_required'));
    if (_skillCreateFiles.length) {
        const error = validateSkillUploadFiles(_skillCreateFiles);
        if (error) return setSkillCreateError(error);
    }

    const form = new FormData();
    form.append('name', name);
    form.append('description', description);
    form.append('body', body);
    // Paired field by field, the way a picked folder is uploaded: an attachment
    // that came from a folder keeps the path it sat at, and a file's own name
    // says nothing about that.
    _skillCreateFiles.forEach(file => {
        form.append('files', file);
        form.append('relative_paths', skillAttachmentPath(file));
    });
    return postSkillCreate(form);
}

async function postSkillCreate(formData) {
    setSkillCreateBusy(true);
    setSkillCreateError('');
    let data = null;
    try {
        const res = await fetch('/api/skills/create', { method: 'POST', body: formData });
        data = await res.json();
    } catch (e) {
        data = null;
    } finally {
        setSkillCreateBusy(false);
    }

    if (!data) return setSkillCreateError(t('skill_new_failed'));
    if (data.status !== 'success') return setSkillCreateError(data.message || t('skill_new_failed'));

    closeSkillCreateDialog();
    _wsToast(`${t('skill_new_created')}: ${data.name}`);
    loadSkillsSection();
}

