/* Per-session permission mode and model, as composer chips.
   Split out of console.js. These are classic scripts sharing one global
   scope; see channel/web/README.md before changing the load order. */

// =====================================================================
// Per-session settings: permission mode and model
//
// Both live next to the workspace picker under the input, because all three
// answer the same question - what this conversation is allowed to do, and with
// what. Each falls back to the global setting until the user pins one here, so
// a session that was never touched keeps following Settings.
// =====================================================================

// Icons and i18n keys per mode. Ordered most-open first so the menu reads from
// "least restricted" downward, matching how the chip colours escalate.
const PERMISSION_META = {
    'full-access':     { icon: 'fa-lock-open',     key: 'perm_full_access' },
    'workspace-write': { icon: 'fa-shield-halved', key: 'perm_workspace_write' },
    'read-only':       { icon: 'fa-eye',           key: 'perm_read_only' },
};

// Last state from GET /api/sessions/<id>/settings; null until first fetch.
let _sessCfg = null;

function _permBtn() { return document.getElementById('permission-selector-btn'); }
function _permMenu() { return document.getElementById('permission-selector-menu'); }
function _modelBtn() { return document.getElementById('model-selector-btn'); }
function _modelMenu() { return document.getElementById('model-selector-menu'); }

function _permLabel(mode) { return t((PERMISSION_META[mode] || {}).key || 'perm_full_access'); }

/** Close every composer popover except `keep` (so one chip's menu replaces another's). */
function _closeComposerMenus(keep) {
    [[_wsSelMenu(), _wsSelBtn()], [_permMenu(), _permBtn()], [_modelMenu(), _modelBtn()]]
        .forEach(([menu, btn]) => {
            if (!menu || menu === keep) return;
            menu.classList.add('hidden');
            if (btn) btn.classList.remove('open');
        });
    const agentMenu = document.getElementById('composer-agent-menu');
    if (agentMenu && agentMenu !== keep) agentMenu.classList.add('hidden');
}

// Fetch this session's effective model + permission and repaint both chips.
async function refreshSessionSettings() {
    try {
        const res = await fetch(`/api/sessions/${encodeURIComponent(sessionId)}/settings`);
        const data = await res.json();
        if (data.status !== 'success') return;
        _sessCfg = { model: data.model, permission: data.permission, team: data.team };
        // The team panel button follows this session's roster (hidden for solo
        // sessions). team-panel.js may not be present on every page shell.
        if (typeof updateTeamPanelButton === 'function') updateTeamPanelButton();
        // Same signal drives the member pill bar + columns (chat/team-columns.js).
        if (typeof updateTeamColumns === 'function') updateTeamColumns();
    } catch (e) {
        // Keep whatever the chips already show rather than blanking them.
        return;
    }
    _renderPermissionChip();
    _renderModelChip();
    _renderInputPlaceholder();
    renderComposerIdentity();
}

function _renderPermissionChip() {
    const btn = _permBtn();
    if (!btn || !_sessCfg) return;
    const state = _sessCfg.permission || {};
    const mode = state.mode || 'full-access';
    const meta = PERMISSION_META[mode] || PERMISSION_META['full-access'];

    const label = document.getElementById('permission-selector-label');
    if (label) label.textContent = _permLabel(mode);
    const icon = document.getElementById('permission-selector-icon');
    if (icon) icon.className = `fas ${meta.icon}`;

    // One colour per mode, so an unrestricted session is visibly different from
    // a read-only one without having to read the label.
    btn.classList.remove('perm-read-only', 'perm-workspace-write', 'perm-full-access');
    btn.classList.add(`perm-${mode}`);

    const tip = t('perm_tip').replace('{name}', _permLabel(mode))
        + (state.source === 'global' ? ` · ${t('perm_follow_global')}` : '');
    btn.setAttribute('data-tooltip', tip);
    btn.setAttribute('data-tooltip-pos', 'top');
    btn.setAttribute('data-tip-float', '');
}

// The composer placeholder only advertises "@ an Agent" when the conversation
// actually has other members to address. A solo chat can only @ files, so it
// falls back to the file-only hint. Runs whenever the session's team changes.
function _renderInputPlaceholder() {
    const input = document.getElementById('chat-input');
    if (!input) return;
    input.placeholder = t(sharedConversation() ? 'input_placeholder_team' : 'input_placeholder');
}

function _renderModelChip() {
    const btn = _modelBtn();
    if (!btn || !_sessCfg) return;
    // Once a conversation has more than one Agent there is no single model to
    // show: each answers on its own. Pinning one here would silently apply to
    // whoever happens to own the conversation.
    const shared = sharedConversation();
    btn.classList.toggle('hidden', shared);
    if (shared) {
        _modelMenu()?.classList.add('hidden');
        btn.classList.remove('open');
        return;
    }
    const state = _sessCfg.model || {};
    const model = state.model || '';

    const label = document.getElementById('model-selector-label');
    if (label) label.textContent = model || t('model_unset');

    const tip = t('model_tip').replace('{name}', model || t('model_unset'))
        + (state.source === 'global' ? ` · ${t('model_follow_global')}` : '')
        + (state.source === 'agent' ? ` · ${t('model_follow_agent')}` : '');
    btn.setAttribute('data-tooltip', tip);
    btn.setAttribute('data-tooltip-pos', 'top');
    btn.setAttribute('data-tip-float', '');
}

function togglePermissionSelector(event) {
    if (event) { event.preventDefault(); event.stopPropagation(); }
    const menu = _permMenu();
    if (!menu) return;
    if (!menu.classList.contains('hidden')) {
        _closeComposerMenus();
        return;
    }
    _closeComposerMenus(menu);
    const open = () => { renderPermissionMenu(); menu.classList.remove('hidden'); _permBtn()?.classList.add('open'); };
    if (_sessCfg) open(); else refreshSessionSettings().then(open);
}

function renderPermissionMenu() {
    const menu = _permMenu();
    if (!menu) return;
    const state = (_sessCfg && _sessCfg.permission) || {};
    const modes = state.modes && state.modes.length ? state.modes : Object.keys(PERMISSION_META);
    const current = state.mode || 'full-access';
    const isGlobal = state.source === 'global';

    const parts = [`<div class="composer-menu-title">${escapeHtml(t('perm_menu_title'))}</div>`];
    // Menu order follows PERMISSION_META, not the backend tuple, so the list
    // reads consistently even if the backend reorders its modes. "Follow global"
    // is intentionally not a row of its own: picking a mode simply pins it, and
    // clicking the already-active mode clears the pin (back to global) so the
    // behaviour is still reachable without cluttering the menu.
    Object.keys(PERMISSION_META).filter(m => modes.includes(m)).forEach(mode => {
        const meta = PERMISSION_META[mode];
        const active = mode === current;
        // When this mode is the active one AND it is pinned, clicking it clears
        // the pin; otherwise clicking pins this mode.
        const arg = (active && !isGlobal) ? 'null' : `'${mode}'`;
        parts.push(`
            <button class="composer-menu-item ${active ? 'active' : ''}" onclick="selectSessionPermission(${arg})">
                <i class="fas ${meta.icon}"></i>
                <span class="composer-menu-body">
                    <span class="composer-menu-name">${escapeHtml(t(meta.key))}</span>
                    <span class="composer-menu-desc">${escapeHtml(t(meta.key + '_desc'))}</span>
                </span>
                ${active ? '<i class="fas fa-check composer-menu-check"></i>' : ''}
            </button>`);
    });

    menu.innerHTML = parts.join('');
}

/** Pin this session's permission mode, or pass null to follow the global one. */
async function selectSessionPermission(mode) {
    _closeComposerMenus();
    await _applySessionSettings({ permission: mode });
}

// Insert an actionable hint after a tool card whose call was refused by the
// permission gate. Clicking it opens the permission selector under the input so
// the user can raise the mode without hunting for the chip.
function _appendPermissionDeniedHint(toolEl, mode) {
    if (!toolEl || !toolEl.parentElement) return;
    // Avoid stacking duplicate hints if the model retries the same blocked call.
    if (toolEl.nextElementSibling
        && toolEl.nextElementSibling.classList
        && toolEl.nextElementSibling.classList.contains('perm-denied-hint')) {
        return;
    }
    const label = _permLabel(mode || (_sessCfg && _sessCfg.permission && _sessCfg.permission.mode) || 'workspace-write');
    const hint = document.createElement('div');
    hint.className = 'perm-denied-hint';
    hint.innerHTML = `
        <i class="fas fa-shield-halved"></i>
        <span class="perm-denied-text">${escapeHtml(t('perm_denied_hint').replace('{name}', label))}</span>
        <button type="button" class="perm-denied-btn">${escapeHtml(t('perm_denied_action'))}</button>`;
    hint.querySelector('.perm-denied-btn').addEventListener('click', (e) => {
        e.stopPropagation();
        const btn = _permBtn();
        if (btn) { btn.scrollIntoView({ block: 'nearest' }); }
        togglePermissionSelector();
    });
    toolEl.parentElement.insertBefore(hint, toolEl.nextElementSibling);
}

function toggleModelSelector(event) {
    if (event) { event.preventDefault(); event.stopPropagation(); }
    const menu = _modelMenu();
    if (!menu) return;
    if (!menu.classList.contains('hidden')) {
        _closeComposerMenus();
        return;
    }
    _closeComposerMenus(menu);
    const open = () => { renderModelMenu(); menu.classList.remove('hidden'); _modelBtn()?.classList.add('open'); };
    // Always re-fetch: the catalog depends on which providers have keys, which
    // may have changed in Settings since this page loaded.
    refreshSessionSettings().then(() => { if (_sessCfg) open(); });
}

function renderModelMenu() {
    const menu = _modelMenu();
    if (!menu) return;
    const state = (_sessCfg && _sessCfg.model) || {};
    const providers = state.providers || [];
    const pinned = state.source === 'session';

    // Which model is currently effective (pinned or inherited from global), so
    // the check mark shows on it even when the session follows the global model.
    const activeModel = state.model || (state.global && state.global.model) || '';
    const activeProvider = state.provider || (state.global && state.global.provider) || '';

    const parts = [`<div class="composer-menu-title">${escapeHtml(t('model_menu_title'))}</div>`];
    providers.forEach((p, idx) => {
        if (idx > 0) parts.push('<div class="composer-menu-divider"></div>');
        parts.push(`<div class="composer-menu-title">${escapeHtml(localizedLabel(p.label))}</div>`);
        (p.models || []).forEach(m => {
            const active = m === activeModel && p.id === activeProvider;
            // Clicking the already-pinned model clears the pin (back to global);
            // "follow global" is no longer a separate row.
            const arg = (active && pinned)
                ? 'null, null'
                : `'${_wsAttr(p.id)}','${_wsAttr(m)}'`;
            parts.push(`
                <button class="composer-menu-item ${active ? 'active' : ''}"
                        onclick="selectSessionModel(${arg})">
                    <i class="fas fa-microchip"></i>
                    <span class="composer-menu-body">
                        <span class="composer-menu-name">${escapeHtml(m)}</span>
                    </span>
                    ${active ? '<i class="fas fa-check composer-menu-check"></i>' : ''}
                </button>`);
        });
    });

    menu.innerHTML = parts.join('');
}

/** Pin a model for this session; pass nulls to follow the global model again. */
async function selectSessionModel(provider, model) {
    _closeComposerMenus();
    await _applySessionSettings({ provider: provider, model: model });
}

// Single writer for both chips: POST the change, then repaint from the state the
// backend echoes back so the UI can never disagree with what was stored.
async function _applySessionSettings(body) {
    try {
        const res = await fetch(`/api/sessions/${encodeURIComponent(sessionId)}/settings`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        const data = await res.json();
        if (data.status !== 'success') { _wsToast(data.message || t('session_settings_failed')); return; }
        _sessCfg = { model: data.model, permission: data.permission };
        _renderPermissionChip();
        _renderModelChip();
    } catch (e) {
        _wsToast(t('session_settings_failed'));
    }
}

document.addEventListener('click', (e) => {
    [[_permMenu(), _permBtn()], [_modelMenu(), _modelBtn()]].forEach(([menu, btn]) => {
        if (!menu || menu.classList.contains('hidden')) return;
        if (menu.contains(e.target) || (btn && btn.contains(e.target))) return;
        menu.classList.add('hidden');
        if (btn) btn.classList.remove('open');
    });
});

