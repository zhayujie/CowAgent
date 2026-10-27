/* Integrations tab: the public address shown in links, and guest pages
   (shareable chat pages backed by profiles under guests/). Creates and edits
   them, hands out the link and the embed snippet, and shows what visitors
   asked. These are classic scripts sharing one global scope; see
   channel/web/README.md before changing the load order. */

const SHARE_TOOLS = [
    { id: 'read',         icon: 'fa-file-lines' },
    { id: 'ls',           icon: 'fa-folder-open' },
    { id: 'search_files', icon: 'fa-magnifying-glass' },
    { id: 'write',        icon: 'fa-pen-to-square' },
    { id: 'edit',         icon: 'fa-pen' },
    { id: 'send',         icon: 'fa-paper-plane' },
    { id: 'web_search',   icon: 'fa-globe' },
    { id: 'web_fetch',    icon: 'fa-link' },
    { id: 'vision',       icon: 'fa-eye' },
    { id: 'time',         icon: 'fa-clock' },
];
const SHARE_NETWORK_TOOLS = ['web_search', 'web_fetch'];
const SHARE_DEFAULT_TOOLS = SHARE_TOOLS.map(tool => tool.id);
const SHARE_MAX_QUESTIONS = 6;
const SHARE_DEFAULT_QUOTA = 100;
const SHARE_ORIGIN_RE = /^https?:\/\/[a-z0-9.-]+(:\d{1,5})?$/i;
const SHARE_DEFAULT_COLOR = '#4abe6e';
const SHARE_COLORS = ['#14b8a6', '#3b82f6', '#6366f1', '#8b5cf6', '#ec4899', '#f97316', '#475569'];
const SHARE_LOGO_TYPES = ['image/png', 'image/jpeg', 'image/webp'];
const SHARE_LOGO_MAX = 2 * 1024 * 1024;
const SHARE_FOOTER_TEXT = 'Powered by CowAgent';
const SHARE_FOOTER_URL = 'https://cowagent.ai';

let integrationsPublicUrl = '';
let sharesList = [];
let sharesFeature = null;
let sharesModels = [];
let sharesSkills = [];
let shareEditorSkills = [];
let sharesRefSuggestions = [];
let shareEditorRefs = [];
let shareEditing = null;      // the share being edited, or null when creating
let shareEditorTools = [];
let shareEmbedSlug = '';
let shareEmbedText = '';
let shareLogsSlug = '';
let shareToastTimer = null;
let shareColor = '';
let shareLogoFile = null;     // a picked logo, uploaded once the share is saved
let shareLogoReset = false;
let shareLogoPreview = '';

// =====================================================================
// Public address
// =====================================================================
/** The origin links and examples are shown with: the owner's public address
 *  when set, else the address this console was opened on. */
function integrationBaseUrl() {
    return (integrationsPublicUrl || location.origin).replace(/\/+$/, '');
}

function loadIntegrationsView() {
    fetch('/api/integrations').then(r => r.json()).then(data => {
        if (data.status !== 'success') return;
        integrationsPublicUrl = data.public_url || '';
        _renderPublicUrl();
        renderExternalApi();
        if (sharesFeature) renderSharesView();
    }).catch(() => {});
    loadExternalApi();
    loadSharesView();
}

function _renderPublicUrl() {
    const input = document.getElementById('cfg-public-url');
    if (!input) return;
    input.value = integrationsPublicUrl;
    input.placeholder = location.origin;
}

function _publicUrlStatus(text, isError) {
    const el = document.getElementById('cfg-public-url-status');
    el.textContent = text || '';
    el.classList.toggle('text-red-500', !!isError);
    el.classList.toggle('text-primary-500', !isError && !!text);
}

function savePublicUrl() {
    const input = document.getElementById('cfg-public-url');
    const value = input.value.trim().replace(/\/+$/, '');
    if (value && !/^https?:\/\/[^\s/?#]+(\/[^\s?#]*)?$/i.test(value)) {
        _publicUrlStatus(t('config_public_url_invalid'), true);
        input.focus();
        return;
    }
    const btn = document.getElementById('cfg-public-url-save');
    btn.disabled = true;
    fetch('/api/integrations', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ public_url: value }),
    }).then(r => r.json()).then(data => {
        if (data.status !== 'success') throw new Error(t('config_public_url_invalid'));
        integrationsPublicUrl = data.public_url || '';
        _renderPublicUrl();
        renderExternalApi();
        if (sharesFeature) renderSharesView();
        _publicUrlStatus(t('config_saved'));
        setTimeout(() => _publicUrlStatus(''), 2000);
    }).catch(err => _publicUrlStatus(err.message, true))
      .finally(() => { btn.disabled = false; });
}

// =====================================================================
// Helpers
// =====================================================================
function _shareApi(path, opts = {}) {
    const init = { method: opts.method || 'GET', headers: {} };
    if (opts.json !== undefined) {
        init.headers['Content-Type'] = 'application/json';
        init.body = JSON.stringify(opts.json);
    }
    return fetch('/api/guest-shares' + path, init).then(async r => {
        let data = {};
        try { data = await r.json(); } catch (_) { /* empty body */ }
        if (!r.ok || data.status === 'error') {
            throw Object.assign(new Error(data.message || `HTTP ${r.status}`), { reason: data.reason || '' });
        }
        return data;
    });
}

function _shareUrl(share) {
    return share.share_token ? `${integrationBaseUrl()}/share/${share.share_token}` : '';
}

function _shareLogoSrc(share) {
    return share && share.logo_version
        ? `/api/guest-shares/${encodeURIComponent(share.slug)}/logo?v=${share.logo_version}`
        : '/assets/logo.jpg';
}

function _shareToast(text) {
    let el = document.getElementById('share-toast');
    if (!el) {
        el = document.createElement('div');
        el.id = 'share-toast';
        el.className = 'art-toast';
        document.body.appendChild(el);
    }
    el.textContent = text;
    el.classList.add('show');
    clearTimeout(shareToastTimer);
    shareToastTimer = setTimeout(() => el.classList.remove('show'), 2200);
}

function _shareLines(text) {
    return String(text || '').split('\n').map(s => s.trim()).filter(Boolean);
}

/** The model a share answers on, as a short label for the list. */
function _shareModelLabel(cfg) {
    if (cfg.model) return cfg.model;
    return (typeof appConfig !== 'undefined' && appConfig && appConfig.model) || t('shares_model_default_short');
}

// =====================================================================
// List
// =====================================================================
function loadSharesView() {
    const container = document.getElementById('shares-content');
    if (!container) return Promise.resolve();
    return _shareApi('').then(data => {
        sharesFeature = data.feature || {};
        sharesList = data.shares || [];
        sharesModels = data.models || [];
        sharesSkills = data.skills || [];
        sharesRefSuggestions = data.references || [];
        renderSharesView();
    }).catch(() => {
        document.getElementById('shares-detail').classList.remove('hidden');
        container.innerHTML = `<p class="text-sm text-red-400 py-4 text-center">${escapeHtml(t('shares_load_failed'))}</p>`;
    });
}

function renderSharesView() {
    const feature = sharesFeature || {};
    const banner = document.getElementById('shares-feature');
    const container = document.getElementById('shares-content');
    document.getElementById('shares-switch').checked = !!feature.enabled;
    document.getElementById('shares-detail').classList.toggle('hidden', !feature.enabled);
    banner.innerHTML = '';
    banner.className = '';
    if (!feature.enabled) {
        container.innerHTML = '';
        return;
    }

    if (!feature.web_password_set) {
        banner.className = 'mb-3';
        banner.innerHTML = `
            <div class="share-callout items-center">
                <i class="fas fa-lock" style="margin-top:0"></i>
                <span class="flex-1">${escapeHtml(t('shares_need_console_password'))}</span>
                <button onclick="goToConsolePassword()" class="share-action !text-amber-700 dark:!text-amber-300 hover:!bg-amber-100 dark:hover:!bg-amber-500/10 flex-shrink-0">
                    ${escapeHtml(t('shares_go_settings'))}<i class="fas fa-arrow-right"></i>
                </button>
            </div>`;
    }
    container.innerHTML = sharesList.map(shareCardHtml).join('');
}

function goToConsolePassword() {
    switchConfigTab('basic');
    const input = document.getElementById('cfg-password');
    if (!input) return;
    input.scrollIntoView({ behavior: 'smooth', block: 'center' });
    setTimeout(() => input.focus({ preventScroll: true }), 300);
}

const _SHARE_STATUS = {
    active:           { dot: 'bg-primary-400', text: 'text-primary-500', key: 'shares_status_active' },
    unconfirmed:      { dot: 'bg-amber-400',   text: 'text-amber-500',   key: 'shares_status_unconfirmed' },
    password_missing: { dot: 'bg-amber-400',   text: 'text-amber-500',   key: 'shares_status_password_missing' },
    disabled:         { dot: 'bg-slate-300 dark:bg-slate-600', text: 'text-slate-400', key: 'shares_status_disabled' },
    expired:          { dot: 'bg-slate-300 dark:bg-slate-600', text: 'text-slate-400', key: 'shares_status_expired' },
};

function shareCardHtml(share) {
    const slug = escapeHtml(share.slug);
    const st = _SHARE_STATUS[share.status] || _SHARE_STATUS.disabled;
    const cfg = share.effective_config || share.file_config || {};
    const url = _shareUrl(share);
    const live = share.status === 'active';

    const chips = [];
    const access = cfg.access || {};
    chips.push(access.password_required
        ? `<span class="share-chip"><i class="fas fa-lock"></i>${escapeHtml(t('shares_chip_password'))}</span>`
        : `<span class="share-chip"><i class="fas fa-lock-open"></i>${escapeHtml(t('shares_chip_public'))}</span>`);
    const quota = (cfg.limits || {}).daily_messages;
    chips.push(`<span class="share-chip"><i class="fas fa-comment-dots"></i>${escapeHtml(quota
        ? t('shares_chip_quota').replace('{n}', quota) : t('shares_chip_quota_unlimited'))}</span>`);
    const tools = cfg.tools || [];
    chips.push(`<span class="share-chip"><i class="fas fa-screwdriver-wrench"></i>${escapeHtml(t('shares_chip_tools').replace('{n}', tools.length))}</span>`);
    const refs = (cfg.references || []).map(r => r.path);
    if (refs.length) {
        chips.push(`<span class="share-chip" title="${escapeHtml(refs.join('\n'))}"><i class="fas fa-book"></i>${escapeHtml(t('shares_chip_paths').replace('{n}', refs.length))}</span>`);
    }
    if (cfg.expires_at) chips.push(`<span class="share-chip"><i class="fas fa-hourglass-half"></i>${escapeHtml(t('shares_chip_expires').replace('{d}', cfg.expires_at))}</span>`);
    if ((access.allowed_origins || []).length) {
        chips.push(`<span class="share-chip" title="${escapeHtml(access.allowed_origins.join('\n'))}"><i class="fas fa-code"></i>${escapeHtml(t('shares_chip_embed').replace('{n}', access.allowed_origins.length))}</span>`);
    }

    const callouts = [];
    if (share.status === 'unconfirmed' || (share.pending || []).length) {
        const items = (share.pending || []).map(p => `<li>${escapeHtml(p)}</li>`).join('');
        const msg = (share.pending || []).length ? t('shares_pending') : t('shares_unconfirmed');
        callouts.push(`
            <div class="share-callout">
                <i class="fas fa-circle-exclamation"></i>
                <div class="flex-1 min-w-0">
                    <div>${escapeHtml(msg)}</div>
                    ${items ? `<ul>${items}</ul>` : ''}
                </div>
                <button onclick="shareAction('${slug}', 'confirm')"
                        class="self-center px-3 py-1.5 rounded-lg bg-primary-500 hover:bg-primary-600 text-white text-xs font-medium cursor-pointer transition-colors flex-shrink-0">
                    ${escapeHtml(t('shares_confirm'))}
                </button>
            </div>`);
    }
    if (share.status === 'password_missing') {
        callouts.push(`
            <div class="share-callout items-center">
                <i class="fas fa-key" style="margin-top:0"></i>
                <span class="flex-1">${escapeHtml(t('shares_password_missing'))}</span>
                <button onclick="openShareEditor('${slug}', 'password')"
                        class="px-3 py-1.5 rounded-lg bg-primary-500 hover:bg-primary-600 text-white text-xs font-medium cursor-pointer transition-colors flex-shrink-0">
                    ${escapeHtml(t('shares_set_password'))}
                </button>
            </div>`);
    }
    if ((share.notices || []).length) {
        callouts.push(`
            <div class="share-callout is-info">
                <i class="fas fa-circle-info"></i>
                <div class="flex-1 min-w-0">
                    <div>${escapeHtml(t('shares_notices'))}</div>
                    <ul>${share.notices.map(n => `<li>${escapeHtml(n)}</li>`).join('')}</ul>
                </div>
            </div>`);
    }

    const linkRow = url
        ? `<div class="share-link${live ? '' : ' is-muted'}">
                <span class="share-link-url" title="${escapeHtml(url)}">${escapeHtml(url)}</span>
                <button class="share-icon-btn" onclick="copyShareLink('${slug}')" data-tip-float data-tooltip="${escapeHtml(t('shares_copy_link'))}" data-tooltip-pos="bottom">
                    <i class="fas fa-copy text-xs"></i>
                </button>
                <a class="share-icon-btn" href="${escapeHtml(url)}" target="_blank" rel="noopener" data-tip-float data-tooltip="${escapeHtml(t('shares_open'))}" data-tooltip-pos="bottom">
                    <i class="fas fa-arrow-up-right-from-square text-xs"></i>
                </a>
            </div>`
        : `<div class="share-link is-muted"><span class="share-link-url">${escapeHtml(t('shares_no_link'))}</span></div>`;

    return `
        <div class="share-item" id="share-card-${slug}">
            <div class="flex items-center gap-3">
                <img class="share-item-logo" src="${escapeHtml(_shareLogoSrc(share))}" alt="">
                <div class="flex-1 min-w-0">
                    <div class="flex items-center gap-2 min-w-0">
                        <span class="font-medium text-slate-800 dark:text-slate-100 truncate">${escapeHtml(share.name || share.slug)}</span>
                        <span class="w-1.5 h-1.5 rounded-full flex-shrink-0 ${st.dot}"></span>
                        <span class="text-xs ${st.text} flex-shrink-0">${escapeHtml(t(st.key))}</span>
                    </div>
                    <div class="share-item-sub"><span>${escapeHtml(_shareModelLabel(cfg))}</span></div>
                </div>
                <button onclick="openShareEditor('${slug}')"
                        class="px-3 py-1.5 rounded-lg text-xs font-medium bg-slate-100 dark:bg-white/5 text-slate-600 dark:text-slate-300
                               hover:bg-slate-200 dark:hover:bg-white/10 cursor-pointer transition-colors flex-shrink-0">
                    ${escapeHtml(t('shares_edit'))}
                </button>
                <div class="share-menu-wrap flex-shrink-0">
                    <button class="share-icon-btn" onclick="toggleShareMenu(event, '${slug}')" aria-label="more">
                        <i class="fas fa-ellipsis"></i>
                    </button>
                    <div class="share-menu hidden" id="share-menu-${slug}">
                        <button class="share-menu-item" onclick="shareAction('${slug}', 'reset-link')"><i class="fas fa-rotate"></i>${escapeHtml(t('shares_reset_link'))}</button>
                        <button class="share-menu-item" onclick="shareAction('${slug}', 'revoke')"><i class="fas fa-user-slash"></i>${escapeHtml(t('shares_revoke'))}</button>
                        ${share.disabled
                            ? `<button class="share-menu-item" onclick="shareAction('${slug}', 'enable')"><i class="fas fa-play"></i>${escapeHtml(t('shares_enable'))}</button>`
                            : `<button class="share-menu-item" onclick="shareAction('${slug}', 'disable')"><i class="fas fa-pause"></i>${escapeHtml(t('shares_disable'))}</button>`}
                        <div class="share-menu-sep"></div>
                        <button class="share-menu-item is-danger" onclick="shareAction('${slug}', 'delete')"><i class="fas fa-trash-can"></i>${escapeHtml(t('shares_delete'))}</button>
                    </div>
                </div>
            </div>
            <div class="mt-4 space-y-3">
                ${linkRow}
                <div class="share-meta">${chips.join('')}</div>
                ${callouts.join('')}
            </div>
            <div class="flex flex-wrap items-center gap-1 mt-3 pt-2 -mx-2 border-t border-slate-100 dark:border-white/5">
                <button class="share-action" onclick="openShareEmbed('${slug}')"${url ? '' : ' disabled style="opacity:.4;cursor:not-allowed"'}>
                    <i class="fas fa-code"></i>${escapeHtml(t('shares_embed'))}
                </button>
                <button class="share-action" onclick="openShareLogs('${slug}')">
                    <i class="fas fa-clock-rotate-left"></i>${escapeHtml(t('shares_logs'))}
                </button>
            </div>
        </div>`;
}

function _findShare(slug) {
    return sharesList.find(s => s.slug === slug);
}

function _replaceShare(share) {
    const i = sharesList.findIndex(s => s.slug === share.slug);
    if (i >= 0) sharesList[i] = share; else sharesList.push(share);
    renderSharesView();
}

function toggleShareMenu(e, slug) {
    e.stopPropagation();
    const menu = document.getElementById(`share-menu-${slug}`);
    const wasOpen = menu && !menu.classList.contains('hidden');
    closeShareMenus();
    if (menu && !wasOpen) menu.classList.remove('hidden');
}

function closeShareMenus() {
    document.querySelectorAll('.share-menu').forEach(m => m.classList.add('hidden'));
}

document.addEventListener('click', (e) => {
    if (!e.target.closest('.share-menu-wrap')) closeShareMenus();
});

function toggleSharesFeature(enabled) {
    _shareApi('', { method: 'PUT', json: { enabled } })
        .then(data => {
            sharesFeature = data.feature || sharesFeature;
            if (enabled) return loadSharesView();
            renderSharesView();
        })
        .catch(err => {
            _shareToast(err.message);
            renderSharesView();
        });
}

function copyShareLink(slug) {
    const share = _findShare(slug);
    if (!share) return;
    copyToClipboard(_shareUrl(share))
        .then(() => _shareToast(t('shares_link_copied')))
        .catch(() => _shareToast(t('shares_copy_failed')));
}

const _SHARE_CONFIRMS = {
    'reset-link': { title: 'shares_reset_link', message: 'shares_reset_link_confirm', tone: 'danger' },
    'revoke':     { title: 'shares_revoke',     message: 'shares_revoke_confirm',     tone: 'danger' },
    'disable':    { title: 'shares_disable',    message: 'shares_disable_confirm',    tone: 'danger' },
    'delete':     { title: 'shares_delete',     message: 'shares_delete_confirm',     tone: 'danger' },
};

function shareAction(slug, action) {
    closeShareMenus();
    const run = () => {
        const req = action === 'delete'
            ? _shareApi('/' + slug, { method: 'DELETE' })
            : _shareApi(`/${slug}/${action}`, { method: 'POST', json: {} });
        req.then(data => {
            if (action === 'delete') {
                sharesList = sharesList.filter(s => s.slug !== slug);
                renderSharesView();
            } else if (data.share) {
                _replaceShare(data.share);
            }
            _shareToast(t('shares_done_' + action.replace('-', '_')));
        }).catch(err => _shareToast(err.message));
    };
    const ask = _SHARE_CONFIRMS[action];
    if (!ask) return run();
    const share = _findShare(slug);
    showConfirmDialog({
        title: t(ask.title),
        message: t(ask.message).replace('{name}', share ? (share.name || slug) : slug),
        okText: t(ask.title),
        tone: ask.tone,
        onConfirm: run,
    });
}

// =====================================================================
// Editor
// =====================================================================
function openShareEditor(slug, focus) {
    const overlay = document.getElementById('share-editor-overlay');
    document.getElementById('share-editor-error').textContent = '';
    document.getElementById('share-editor-save').disabled = false;
    _setShareMore(false);
    if (!slug) {
        shareEditing = null;
        _fillShareEditor({
            suggested_questions: [t('shares_default_q1'), t('shares_default_q2')],
        }, '', false);
        overlay.classList.remove('hidden');
        setTimeout(() => document.getElementById('share-ed-name').focus(), 30);
        return;
    }
    _shareApi('/' + slug).then(data => {
        shareEditing = data.share;
        _fillShareEditor(data.share.raw_config || {}, data.share.guest_md || '', data.share.password_set);
        overlay.classList.remove('hidden');
        const target = focus === 'password' ? 'share-ed-password' : 'share-ed-name';
        setTimeout(() => document.getElementById(target).focus(), 30);
    }).catch(err => _shareToast(err.message));
}

function _fillShareEditor(cfg, guestMd, passwordSet) {
    const isNew = !shareEditing;
    document.getElementById('share-editor-title').textContent = t(isNew ? 'shares_new_title' : 'shares_edit_title');
    document.getElementById('share-editor-subtitle').textContent = isNew ? t('shares_new_desc') : (shareEditing.name || '');
    document.getElementById('share-ed-name').value = cfg.name || '';
    document.getElementById('share-ed-welcome').value = cfg.welcome || '';
    _renderShareQuestions(cfg.suggested_questions || []);
    shareEditorRefs = (cfg.references || []).map(r => ({ path: r.path || '', note: r.note || '' }));
    _renderShareRefs();
    document.getElementById('share-ed-expires').value = (cfg.expires_at || '').slice(0, 10);
    const quota = (cfg.limits || {}).daily_messages;
    document.getElementById('share-ed-quota').value = quota === undefined ? SHARE_DEFAULT_QUOTA : quota;
    document.getElementById('share-ed-guest-md').value = guestMd || '';

    const access = cfg.access || {};
    const pwdOn = document.getElementById('share-ed-pwd-on');
    const pwd = document.getElementById('share-ed-password');
    pwdOn.checked = !!access.password_required;
    pwd.value = '';
    pwd.dataset.set = passwordSet ? '1' : '';
    _syncSharePassword();
    pwdOn.onchange = _syncSharePassword;

    shareEditorTools = Array.isArray(cfg.tools) ? cfg.tools.slice() : SHARE_DEFAULT_TOOLS.slice();
    _renderShareTools();
    shareEditorSkills = Array.isArray(cfg.skills) ? cfg.skills.slice() : [];
    _renderShareSkills();

    const brand = cfg.branding || {};
    shareColor = brand.color || '';
    _renderShareColors();
    _setShareLogo(null, false);
    document.getElementById('share-ed-footer-text').value = brand.footer_text === undefined ? SHARE_FOOTER_TEXT : brand.footer_text;
    document.getElementById('share-ed-footer-url').value = brand.footer_url === undefined ? SHARE_FOOTER_URL : brand.footer_url;

    _initShareModelPicker(cfg.model ? `${cfg.provider || ''}|${cfg.model}` : '');
}

// --- Model -----------------------------------------------------------------
function _initShareModelPicker(value) {
    const follows = (typeof appConfig !== 'undefined' && appConfig && appConfig.model) || '';
    const options = [{ value: '', label: t('shares_model_follow'), hint: follows }];
    const seen = new Set();
    sharesModels.forEach(p => (p.models || []).forEach(m => {
        const v = `${p.id}|${m}`;
        seen.add(v);
        options.push({ value: v, label: m, hint: localizedLabel(p.label) });
    }));
    if (value && !seen.has(value)) {
        const model = value.slice(value.indexOf('|') + 1);
        options.push({ value, label: model, hint: '' });
    }
    initDropdown(document.getElementById('share-ed-model'), options, value || '');
}

// --- Suggested questions --------------------------------------------------
function _shareQuestionRow(text) {
    return `<div class="share-q-row">
            <input type="text" maxlength="200" class="share-input" value="${escapeHtml(text || '')}"
                   placeholder="${escapeHtml(t('shares_question_ph'))}">
            <button type="button" class="share-icon-btn" onclick="removeShareQuestion(this)" aria-label="remove">
                <i class="fas fa-xmark text-xs"></i>
            </button>
        </div>`;
}

function _renderShareQuestions(list) {
    document.getElementById('share-ed-questions').innerHTML =
        list.slice(0, SHARE_MAX_QUESTIONS).map(_shareQuestionRow).join('');
    _syncShareQuestionAdd();
}

function _syncShareQuestionAdd() {
    const n = document.querySelectorAll('#share-ed-questions .share-q-row').length;
    document.getElementById('share-ed-q-add').disabled = n >= SHARE_MAX_QUESTIONS;
}

function addShareQuestion() {
    const box = document.getElementById('share-ed-questions');
    if (box.querySelectorAll('.share-q-row').length >= SHARE_MAX_QUESTIONS) return;
    box.insertAdjacentHTML('beforeend', _shareQuestionRow(''));
    _syncShareQuestionAdd();
    box.lastElementChild.querySelector('input').focus();
}

function removeShareQuestion(btn) {
    btn.closest('.share-q-row').remove();
    _syncShareQuestionAdd();
}

function _shareQuestions() {
    return Array.from(document.querySelectorAll('#share-ed-questions input'))
        .map(el => el.value.trim()).filter(Boolean);
}

// --- Appearance -------------------------------------------------------------
function _isLightColor(hex) {
    const [r, g, b] = [1, 3, 5].map(i => parseInt(hex.slice(i, i + 2), 16) / 255)
        .map(c => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
    return 0.2126 * r + 0.7152 * g + 0.0722 * b > 0.45;
}

function _shareSwatch(value, color) {
    const on = shareColor === value;
    const tip = value ? '' : ` data-tip-float data-tooltip="${escapeHtml(t('shares_color_default'))}" data-tooltip-pos="top"`;
    return `<button type="button" class="share-swatch${on ? ' is-on' : ''}${_isLightColor(color) ? ' is-light' : ''}"
                style="background:${color};--sw:${color}" onclick="pickShareColor('${value}')"${tip}>
                <i class="fas fa-check"></i>
            </button>`;
}

function _renderShareColors() {
    const custom = shareColor && !SHARE_COLORS.includes(shareColor) ? shareColor : '';
    const customStyle = custom ? ` style="background:${custom};--sw:${custom}"` : '';
    document.getElementById('share-ed-colors').innerHTML =
        _shareSwatch('', SHARE_DEFAULT_COLOR)
        + SHARE_COLORS.map(c => _shareSwatch(c, c)).join('')
        + `<label class="share-swatch share-swatch-custom${custom ? ' is-on' : ''}${custom && _isLightColor(custom) ? ' is-light' : ''}"${customStyle}
                  data-tip-float data-tooltip="${escapeHtml(t('shares_color_custom'))}" data-tooltip-pos="top">
                <i class="fas fa-check"></i>
                <input type="color" value="${custom || '#0ea5e9'}" onchange="pickShareColor(this.value)">
            </label>`;
}

function pickShareColor(value) {
    shareColor = String(value || '').toLowerCase();
    _renderShareColors();
}

function _setShareLogo(file, reset) {
    shareLogoFile = file;
    shareLogoReset = reset;
    if (shareLogoPreview) URL.revokeObjectURL(shareLogoPreview);
    shareLogoPreview = file ? URL.createObjectURL(file) : '';
    const hasSaved = !!(shareEditing && shareEditing.logo_version) && !reset;
    document.getElementById('share-ed-logo-img').src = shareLogoPreview || (hasSaved ? _shareLogoSrc(shareEditing) : '/assets/logo.jpg');
    document.getElementById('share-ed-logo-reset').classList.toggle('hidden', !file && !hasSaved);
    document.getElementById('share-ed-logo-file').value = '';
}

function resetShareLogo() {
    _setShareLogo(null, true);
}

function onShareLogoPicked(input) {
    const file = input.files && input.files[0];
    if (!file) return;
    if (!SHARE_LOGO_TYPES.includes(file.type)) {
        input.value = '';
        _shareEditorError(t('shares_logo_type'));
        return;
    }
    if (file.size > SHARE_LOGO_MAX) {
        input.value = '';
        _shareEditorError(t('shares_logo_size'));
        return;
    }
    _shareEditorError('');
    _setShareLogo(file, false);
}

/** Upload or drop the logo once the share it belongs to exists. */
function _saveShareLogo(data) {
    const slug = data.share.slug;
    if (shareLogoFile) {
        const form = new FormData();
        form.append('file', shareLogoFile);
        return fetch(`/api/guest-shares/${encodeURIComponent(slug)}/logo`, { method: 'POST', body: form })
            .then(async r => {
                let body = {};
                try { body = await r.json(); } catch (_) { /* empty body */ }
                if (!r.ok || body.status === 'error') {
                    throw new Error(body.reason === 'unsupported_image' ? t('shares_logo_type')
                        : body.reason === 'too_large' ? t('shares_logo_size') : (body.message || `HTTP ${r.status}`));
                }
                return body;
            });
    }
    if (shareLogoReset && data.share.logo_version) {
        return _shareApi(`/${slug}/logo`, { method: 'DELETE' });
    }
    return data;
}

// --- Access and capabilities ----------------------------------------------
function _syncSharePassword() {
    const on = document.getElementById('share-ed-pwd-on').checked;
    const pwd = document.getElementById('share-ed-password');
    pwd.disabled = !on;
    pwd.placeholder = !on ? t('shares_password_off') : (pwd.dataset.set ? t('shares_password_keep') : t('shares_password_new'));
}

function _renderShareTools() {
    const box = document.getElementById('share-ed-tools');
    box.innerHTML = SHARE_TOOLS.map(tool => {
        const on = shareEditorTools.includes(tool.id);
        return `<button type="button" class="share-tool${on ? ' is-on' : ''}" onclick="toggleShareTool('${tool.id}')">
                    <i class="fas ${tool.icon}"></i>${escapeHtml(t('shares_tool_' + tool.id))}
                </button>`;
    }).join('');
}

function toggleShareTool(id) {
    const i = shareEditorTools.indexOf(id);
    if (i >= 0) shareEditorTools.splice(i, 1);
    else shareEditorTools.push(id);
    _renderShareTools();
}

function _renderShareSkills() {
    const box = document.getElementById('share-ed-skills');
    const picker = document.getElementById('share-ed-skill-add');
    const byName = Object.fromEntries(sharesSkills.map(s => [s.name, s]));
    box.innerHTML = shareEditorSkills.map((name, i) => {
        const skill = byName[name] || { name };
        const tip = [skill.needs_shell ? t('shares_skill_needs_shell') : '', skill.description || '']
            .filter(Boolean).join(' · ');
        return `<span class="share-tool is-on${skill.needs_shell ? ' is-limited' : ''}"${tip ? ` data-tip-float data-tooltip="${escapeHtml(tip)}"` : ''}>
                    <i class="fas ${skill.needs_shell ? 'fa-terminal' : 'fa-wand-magic-sparkles'}"></i>${escapeHtml(name)}
                    <button type="button" class="share-chip-x" onclick="removeShareSkill(${i})" aria-label="remove"><i class="fas fa-xmark"></i></button>
                </span>`;
    }).join('');
    box.classList.toggle('hidden', !shareEditorSkills.length);

    const options = sharesSkills.filter(s => !s.needs_shell && !shareEditorSkills.includes(s.name))
        .map(s => ({ value: s.name, label: s.name }));
    picker.classList.toggle('hidden', !options.length);
    const empty = document.getElementById('share-ed-skills-empty');
    empty.classList.toggle('hidden', options.length > 0 || shareEditorSkills.length > 0);
    if (!options.length) return;
    initDropdown(picker, options, '', (name) => {
        if (name && !shareEditorSkills.includes(name)) shareEditorSkills.push(name);
        _renderShareSkills();
    }, { placeholder: t('shares_skill_add') });
}

function removeShareSkill(index) {
    shareEditorSkills.splice(index, 1);
    _renderShareSkills();
}

function _shareRefLabel(ref) {
    const kb = ref.agent ? `${ref.agent} · ${t('shares_ref_kb')}` : t('shares_ref_kb');
    return ref.category ? `${kb} / ${ref.category}` : kb;
}

function _renderShareRefs() {
    const box = document.getElementById('share-ed-refs');
    box.innerHTML = shareEditorRefs.map((ref, i) => `
        <div class="share-ref">
            <input type="text" class="share-input font-mono text-[13px]" value="${escapeHtml(ref.path)}"
                   placeholder="${escapeHtml(t('shares_ref_path_ph'))}" oninput="shareEditorRefs[${i}].path = this.value">
            <input type="text" class="share-input text-[13px]" maxlength="500" value="${escapeHtml(ref.note)}"
                   placeholder="${escapeHtml(t('shares_ref_note_ph'))}" oninput="shareEditorRefs[${i}].note = this.value">
            <button type="button" class="share-ref-x" onclick="removeShareRef(${i})" aria-label="remove"><i class="fas fa-xmark"></i></button>
        </div>`).join('');
    box.classList.toggle('hidden', !shareEditorRefs.length);

    const taken = new Set(shareEditorRefs.map(r => r.path));
    const options = sharesRefSuggestions.filter(r => !taken.has(r.path))
        .map(r => ({ value: r.path, label: _shareRefLabel(r) }));
    options.push({ value: '__custom__', label: t('shares_ref_custom') });
    initDropdown(document.getElementById('share-ed-ref-add'), options, '', (value) => {
        shareEditorRefs.push({ path: value === '__custom__' ? '' : value, note: '' });
        _renderShareRefs();
        const rows = box.querySelectorAll('.share-ref');
        const last = rows[rows.length - 1];
        if (last) last.querySelector(value === '__custom__' ? 'input' : 'input:nth-child(2)').focus();
    }, { placeholder: t('shares_ref_add') });
}

function removeShareRef(index) {
    shareEditorRefs.splice(index, 1);
    _renderShareRefs();
}

function _setShareMore(open) {
    document.getElementById('share-ed-more').classList.toggle('hidden', !open);
    const chevron = document.querySelector('#share-ed-more-toggle i');
    if (chevron) chevron.style.transform = open ? 'rotate(90deg)' : '';
}

function toggleShareMore() {
    _setShareMore(document.getElementById('share-ed-more').classList.contains('hidden'));
}

function closeShareEditor() {
    document.getElementById('share-editor-overlay').classList.add('hidden');
    shareEditing = null;
}

function _shareEditorError(text) {
    document.getElementById('share-editor-error').textContent = text;
}

function saveShareEditor() {
    const isNew = !shareEditing;
    if (!document.getElementById('share-ed-name').value.trim()) {
        _shareEditorError(t('shares_name_required'));
        document.getElementById('share-ed-name').focus();
        return;
    }
    const pwdOn = document.getElementById('share-ed-pwd-on').checked;
    const password = document.getElementById('share-ed-password').value;
    const passwordSet = !!document.getElementById('share-ed-password').dataset.set;
    if (pwdOn && password && password.length < 6) {
        _shareEditorError(t('shares_password_short'));
        return;
    }
    if (pwdOn && !password && !passwordSet) {
        _shareEditorError(t('shares_password_required'));
        document.getElementById('share-ed-password').focus();
        return;
    }
    const footerUrl = document.getElementById('share-ed-footer-url').value.trim();
    if (footerUrl && !/^https?:\/\/[^\s<>"']+$/i.test(footerUrl)) {
        _setShareMore(true);
        _shareEditorError(t('shares_footer_url_invalid'));
        document.getElementById('share-ed-footer-url').focus();
        return;
    }
    const quotaText = document.getElementById('share-ed-quota').value.trim();
    const quota = quotaText === '' ? SHARE_DEFAULT_QUOTA : Number(quotaText);
    if (!Number.isInteger(quota) || quota < 0) {
        _shareEditorError(t('shares_quota_invalid'));
        document.getElementById('share-ed-quota').focus();
        return;
    }

    // Start from what is on disk so settings the form does not show survive.
    const base = isNew ? {} : JSON.parse(JSON.stringify(shareEditing.raw_config || {}));
    const modelValue = getDropdownValue(document.getElementById('share-ed-model'));
    const cut = modelValue.indexOf('|');
    const config = Object.assign(base, {
        name: document.getElementById('share-ed-name').value.trim(),
        welcome: document.getElementById('share-ed-welcome').value.trim(),
        suggested_questions: _shareQuestions(),
        provider: modelValue ? modelValue.slice(0, cut) : '',
        model: modelValue ? modelValue.slice(cut + 1) : '',
        tools: shareEditorTools.slice(),
        skills: shareEditorSkills.slice(),
        references: shareEditorRefs.map(r => ({ path: r.path.trim(), note: r.note.trim() })).filter(r => r.path),
        expires_at: document.getElementById('share-ed-expires').value || '',
    });
    config.limits = Object.assign({}, base.limits || {}, { daily_messages: quota });
    config.access = Object.assign({}, base.access || {}, { password_required: pwdOn });
    config.network = Object.assign({}, base.network || {}, {
        enabled: shareEditorTools.some(id => SHARE_NETWORK_TOOLS.includes(id)),
    });
    config.branding = Object.assign({}, base.branding || {}, {
        color: shareColor,
        footer_text: document.getElementById('share-ed-footer-text').value.trim(),
        footer_url: footerUrl,
    });
    const guestMd = document.getElementById('share-ed-guest-md').value;

    const btn = document.getElementById('share-editor-save');
    btn.disabled = true;
    _shareEditorError('');
    let logoError = '';
    const save = isNew
        ? _shareApi('', { method: 'POST', json: { config, guest_md: guestMd } })
        : _shareApi('/' + shareEditing.slug, { method: 'PUT', json: { config, guest_md: guestMd } });
    save.then(data => {
            // Saving again after a later step fails must update this share, not create another.
            if (isNew && data.share) shareEditing = data.share;
            return (pwdOn && password)
                ? _shareApi(`/${data.share.slug}/password`, { method: 'POST', json: { password } })
                : data;
        })
        // The share is saved by now; a refused logo must not leave the form
        // open, where saving again would create a second share.
        .then(data => Promise.resolve(_saveShareLogo(data)).catch(err => {
            logoError = err.message;
            return data;
        }))
        .then(data => {
            closeShareEditor();
            _shareToast(logoError || t(isNew ? 'shares_created' : 'shares_saved'));
            if (data.share) _replaceShare(data.share);
            loadSharesView();
        })
        .catch(err => {
            btn.disabled = false;
            _shareEditorError(err.reason === 'console_password' ? t('shares_password_console') : err.message);
            if (isNew && shareEditing) loadSharesView();
        });
}

// =====================================================================
// Embed
// =====================================================================
function openShareEmbed(slug) {
    const share = _findShare(slug);
    const url = share && _shareUrl(share);
    if (!url) return;
    shareEmbedSlug = slug;
    const title = (share.name || share.slug).replace(/"/g, '&quot;');
    const color = ((share.file_config || share.effective_config || {}).branding || {}).color;
    shareEmbedText = [
        `<script src="${integrationBaseUrl()}/assets/guest/embed.js"`,
        `  data-share-url="${url}"`,
        `  data-title="${title}"`,
        ...(color ? [`  data-color="${color}"`] : []),
        '  defer>',
        '</script>',
    ].join('\n');
    document.getElementById('share-embed-code').textContent = shareEmbedText;
    const origins = ((share.file_config || share.effective_config || {}).access || {}).allowed_origins || [];
    document.getElementById('share-embed-origins').value = origins.join('\n');
    document.getElementById('share-embed-error').textContent = '';
    document.getElementById('share-embed-save').disabled = false;
    document.getElementById('share-embed-overlay').classList.remove('hidden');
    _openSharePreview(share, color);
}

// --- Preview ---------------------------------------------------------------
/** The live page as embed.js shows it. Loaded from this console's own
 *  origin, which the page always allows to frame it. */
function _openSharePreview(share, color) {
    const btn = document.getElementById('share-preview-btn');
    btn.style.background = color || SHARE_DEFAULT_COLOR;
    btn.setAttribute('aria-label', share.name || share.slug);
    const icon = document.getElementById('share-preview-icon');
    icon.src = _shareLogoSrc(share);
    icon.classList.toggle('is-default', !share.logo_version);
    const panel = document.getElementById('share-preview-panel');
    panel.innerHTML = '';
    if (window.matchMedia('(min-width: 1024px)').matches) {
        const frame = document.createElement('iframe');
        frame.src = `${location.origin}/share/${share.share_token}?embed=1`;
        frame.title = share.name || share.slug;
        panel.appendChild(frame);
    }
    _setSharePreviewOpen(true);
}

function _setSharePreviewOpen(open) {
    document.getElementById('share-preview-panel').classList.toggle('is-open', open);
    document.getElementById('share-preview-btn').classList.toggle('is-open', open);
}

function toggleSharePreview() {
    _setSharePreviewOpen(!document.getElementById('share-preview-panel').classList.contains('is-open'));
}

window.addEventListener('message', (e) => {
    const frame = document.querySelector('#share-preview-panel iframe');
    if (frame && e.source === frame.contentWindow && e.data && e.data.type === 'cow-guest:close') {
        _setSharePreviewOpen(false);
    }
});

function copyShareEmbed() {
    copyToClipboard(shareEmbedText)
        .then(() => _shareToast(t('shares_code_copied')))
        .catch(() => _shareToast(t('shares_copy_failed')));
}

function saveShareEmbed() {
    const errEl = document.getElementById('share-embed-error');
    const origins = _shareLines(document.getElementById('share-embed-origins').value)
        .map(o => o.replace(/\/+$/, '').toLowerCase());
    const bad = origins.find(o => !SHARE_ORIGIN_RE.test(o));
    if (bad) {
        errEl.textContent = t('shares_origin_invalid').replace('{o}', bad);
        return;
    }
    const btn = document.getElementById('share-embed-save');
    btn.disabled = true;
    errEl.textContent = '';
    const slug = shareEmbedSlug;
    _shareApi('/' + slug).then(data => {
        const config = JSON.parse(JSON.stringify(data.share.raw_config || {}));
        config.access = Object.assign({}, config.access || {}, { allowed_origins: Array.from(new Set(origins)) });
        return _shareApi('/' + slug, { method: 'PUT', json: { config } });
    }).then(data => {
        if (data.share) _replaceShare(data.share);
        closeShareEmbed();
        _shareToast(t('shares_saved'));
    }).catch(err => {
        btn.disabled = false;
        errEl.textContent = err.message;
    });
}

function closeShareEmbed() {
    document.getElementById('share-embed-overlay').classList.add('hidden');
    document.getElementById('share-preview-panel').innerHTML = '';
}

// =====================================================================
// Visitor logs
// =====================================================================
function _shareTime(ts) {
    return ts ? formatTime(new Date(ts * 1000)) : '';
}

function openShareLogs(slug) {
    const share = _findShare(slug);
    shareLogsSlug = slug;
    const overlay = document.getElementById('share-logs-overlay');
    overlay.classList.remove('is-reading');
    document.getElementById('share-logs-subtitle').textContent = share ? (share.name || slug) : slug;
    const list = document.getElementById('share-logs-list');
    const detail = document.getElementById('share-logs-detail');
    list.innerHTML = `<div class="share-logs-empty"><i class="fas fa-spinner fa-spin"></i></div>`;
    detail.innerHTML = '';
    overlay.classList.remove('hidden');
    _shareApi(`/${slug}/logs`).then(data => {
        const sessions = data.sessions || [];
        if (!sessions.length) {
            list.innerHTML = `<div class="share-logs-empty"><i class="fas fa-inbox"></i><span>${escapeHtml(t('shares_logs_empty'))}</span></div>`;
            detail.innerHTML = '';
            return;
        }
        list.innerHTML = sessions.map(s => `
            <button class="share-logs-item" data-sid="${escapeHtml(s.session_id)}" onclick="openShareLog('${escapeHtml(s.session_id)}')">
                <div class="share-logs-item-top">
                    <span class="share-logs-item-id">#${escapeHtml(s.session_id.slice(-8))}${s.deleted ? ` · ${escapeHtml(t('shares_logs_deleted'))}` : ''}</span>
                    <span class="share-logs-item-time">${escapeHtml(_shareTime(s.updated_at))}</span>
                </div>
                <div class="share-logs-item-last">${escapeHtml(s.last || '')}</div>
            </button>`).join('');
        detail.innerHTML = `<div class="share-logs-empty"><i class="fas fa-comments"></i><span>${escapeHtml(t('shares_logs_pick'))}</span></div>`;
        if (window.innerWidth > 640) openShareLog(sessions[0].session_id);
    }).catch(err => {
        list.innerHTML = `<div class="share-logs-empty text-red-400">${escapeHtml(err.message)}</div>`;
    });
}

function openShareLog(sessionId) {
    const overlay = document.getElementById('share-logs-overlay');
    const detail = document.getElementById('share-logs-detail');
    document.querySelectorAll('.share-logs-item').forEach(el => el.classList.toggle('is-active', el.dataset.sid === sessionId));
    overlay.classList.add('is-reading');
    detail.innerHTML = `<div class="share-logs-empty"><i class="fas fa-spinner fa-spin"></i></div>`;
    _shareApi(`/${shareLogsSlug}/logs/${sessionId}`).then(data => {
        const back = `<button class="share-action sm:hidden mb-3 -ml-2" onclick="document.getElementById('share-logs-overlay').classList.remove('is-reading')">
                <i class="fas fa-arrow-left"></i>${escapeHtml(t('shares_logs_back'))}</button>`;
        const turns = (data.records || []).map(shareTurnHtml).join('');
        detail.innerHTML = back + (turns || `<div class="share-logs-empty">${escapeHtml(t('shares_logs_empty'))}</div>`);
        detail.querySelectorAll('pre code').forEach(el => { try { hljs.highlightElement(el); } catch (_) { /* ignore */ } });
    }).catch(err => {
        detail.innerHTML = `<div class="share-logs-empty text-red-400">${escapeHtml(err.message)}</div>`;
    });
}

function shareTurnHtml(rec) {
    if (rec.role === 'event') {
        const key = rec.event === 'deleted' ? 'shares_logs_event_deleted' : 'shares_logs_event_clear';
        return `<div class="context-divider"><span>${escapeHtml(t(key))} · ${escapeHtml(_shareTime(rec.ts))}</span></div>`;
    }
    const isUser = rec.role === 'user';
    const files = isUser ? (rec.attachments || []) : (rec.files || []).map(f => f.path || f.file_name);
    const filesHtml = files.length
        ? `<div class="share-turn-files">${files.map(f => `<span class="share-chip"><i class="fas fa-paperclip"></i>${escapeHtml(String(f))}</span>`).join('')}</div>`
        : '';
    const tools = (rec.steps || []).filter(s => s.type === 'tool');
    const toolsHtml = tools.length
        ? `<div class="share-turn-tools">${tools.map(s => `<span class="share-chip"${s.is_error ? ' style="color:#ef4444"' : ''}><i class="fas fa-${s.is_error ? 'xmark' : 'check'}"></i>${escapeHtml(s.name || '')}</span>`).join('')}</div>`
        : '';
    const meta = [];
    if (!isUser && rec.tokens) meta.push(`${rec.tokens} tokens`);
    if (!isUser && rec.status && rec.status !== 'done' && rec.status !== 'success') meta.push(escapeHtml(rec.status));
    const body = isUser
        ? `<div class="share-turn-body">${escapeHtml(rec.content || '')}</div>`
        : `<div class="share-turn-body markdown-content">${renderMarkdown(rec.content || (rec.error ? `_${rec.error}_` : ''))}</div>`;
    return `
        <div class="share-turn ${isUser ? 'is-user' : 'is-assistant'}">
            <div class="share-turn-head">
                <span class="share-turn-role">${escapeHtml(t(isUser ? 'shares_logs_visitor' : 'shares_logs_agent'))}</span>
                <span>${escapeHtml(_shareTime(rec.ts))}</span>
                ${meta.length ? `<span>· ${meta.join(' · ')}</span>` : ''}
            </div>
            ${isUser ? '' : toolsHtml}
            ${body}
            ${filesHtml}
        </div>`;
}

function closeShareLogs() {
    document.getElementById('share-logs-overlay').classList.add('hidden');
}

document.addEventListener('keydown', (e) => {
    if (e.key !== 'Escape') return;
    const confirmOverlay = document.getElementById('confirm-dialog-overlay');
    if (confirmOverlay && !confirmOverlay.classList.contains('hidden')) return;
    ['share-editor-overlay', 'share-logs-overlay'].forEach(id => {
        const el = document.getElementById(id);
        if (el && !el.classList.contains('hidden')) el.classList.add('hidden');
    });
    if (!document.getElementById('share-embed-overlay').classList.contains('hidden')) closeShareEmbed();
});
