/* Console version badge and the update menu behind it.
   Split out of console.js. These are classic scripts sharing one global
   scope; see channel/web/README.md before changing the load order. */

/* =====================================================================
   CowAgent Console - Main Application Script
   ===================================================================== */

// =====================================================================
// Version — fetched from backend (single source: /VERSION file)
// =====================================================================
let APP_VERSION = '';

// =====================================================================
// One-click update — driven from the sidebar version menu
// =====================================================================
const GITHUB_RELEASES_URL = 'https://github.com/zhayujie/CowAgent/releases';
let UPDATE_META = { version: '', install_kind: 'unknown', update_supported: false, unsupported_reason: '' };
let UPDATE_CHECK = null;
let _updateChecking = false;
let _updateRunning = false;
let _updatePollTimer = null;
let _updateReconnectTimer = null;

function toggleUpdateMenu(event) {
    if (event) event.stopPropagation();
    const menu = document.getElementById('update-menu');
    const btn = document.getElementById('sidebar-version');
    if (!menu) return;
    const willOpen = menu.classList.contains('hidden');
    if (willOpen) {
        menu.classList.remove('hidden');
        if (btn) btn.setAttribute('aria-expanded', 'true');
        setTimeout(() => document.addEventListener('click', _closeUpdateMenuOnOutside), 0);
    } else {
        closeUpdateMenu();
    }
}

function closeUpdateMenu() {
    const menu = document.getElementById('update-menu');
    const btn = document.getElementById('sidebar-version');
    if (menu) menu.classList.add('hidden');
    if (btn) btn.setAttribute('aria-expanded', 'false');
    document.removeEventListener('click', _closeUpdateMenuOnOutside);
}

function _closeUpdateMenuOnOutside(event) {
    const menu = document.getElementById('update-menu');
    const btn = document.getElementById('sidebar-version');
    if (!menu) return;
    if (menu.contains(event.target) || (btn && btn.contains(event.target))) return;
    closeUpdateMenu();
}

// Set the sidebar version text. The red dot lives outside this button (as a
// footer child), so plain textContent is safe.
function _setSidebarVersionLabel(text) {
    const btn = document.getElementById('sidebar-version');
    if (btn) btn.textContent = text || '';
}

// "版本说明": open the GitHub releases page (keeps the old click-through behaviour).
function openReleaseNotes() {
    window.open(GITHUB_RELEASES_URL, '_blank', 'noopener,noreferrer');
    closeUpdateMenu();
}

// Single update entry, mirroring the desktop NavRail: one row whose icon +
// label + red dot are driven by the current update state. Keeping it a single
// fixed-height line means the icon and label never fall out of alignment.
//   idle        -> "检查更新"           (click = check)
//   checking    -> "正在检查…" (spinner)
//   up_to_date  -> "已是最新版本"
//   available   -> "立即更新" + red dot (click = update)
//   updating    -> current step label   (spinner, not clickable)
//   failed      -> "更新失败" + retry
let _updateUiState = 'idle';

function _renderUpdateAction(state, label, opts) {
    opts = opts || {};
    _updateUiState = state;
    const item = document.getElementById('update-action-item');
    const icon = document.getElementById('update-action-icon');
    const text = document.getElementById('update-action-label');
    const dot = document.getElementById('update-dot');
    if (!item || !icon || !text) return;

    text.textContent = label;
    item.classList.toggle('is-new', state === 'available');
    item.classList.toggle('is-ok', state === 'up_to_date');
    item.classList.toggle('is-disabled', !!opts.disabled);
    item.disabled = !!opts.disabled;
    if (dot) dot.classList.toggle('hidden', state !== 'available');

    // Swap the leading icon per state.
    const iconClass = {
        idle: 'fas fa-arrows-rotate',
        checking: 'fas fa-arrows-rotate fa-spin-update',
        up_to_date: 'fas fa-circle-check',
        available: 'fas fa-download',
        updating: 'fas fa-arrows-rotate fa-spin-update',
        failed: 'fas fa-triangle-exclamation'
    }[state] || 'fas fa-arrows-rotate';
    icon.className = iconClass;
}

// The single row's click behaviour depends on the current state.
function onUpdateActionClick() {
    if (_updateChecking || _updateRunning) return;
    if (_updateUiState === 'available') {
        startConsoleUpdate();
    } else {
        checkForConsoleUpdate();
    }
}

// "检查更新": the only action that contacts GitHub. Turns the row into
// "立即更新" (+ red dot) when a newer version exists.
function checkForConsoleUpdate() {
    if (_updateChecking || _updateRunning) return;
    _updateChecking = true;
    _renderUpdateAction('checking', t('update_checking'), { disabled: true });
    fetch('/api/update/check', { method: 'POST' })
        .then(r => r.json())
        .then(data => {
            if (data.status === 'error') {
                _renderUpdateAction('failed', data.message || t('update_error'));
                return;
            }
            UPDATE_CHECK = data;
            if (typeof data.update_supported === 'boolean') UPDATE_META.update_supported = data.update_supported;
            if (data.install_kind) UPDATE_META.install_kind = data.install_kind;
            if (data.up_to_date) {
                _renderUpdateAction('up_to_date', t('update_up_to_date'));
            } else if (UPDATE_META.update_supported) {
                _renderUpdateAction('available', t('update_now'));
            } else {
                // Docker / packaged / Windows: a newer version exists but this
                // install can't self-update, so keep the dot but disable the row.
                const reason = UPDATE_META.unsupported_reason || t('update_unsupported');
                _renderUpdateAction('available', reason, { disabled: true });
            }
        })
        .catch(() => _renderUpdateAction('failed', t('update_error')))
        .finally(() => { _updateChecking = false; });
}

// "立即更新": reuse the cow-update path (git pull + pip + restart) via the
// detached worker, then poll progress and auto-reconnect when it comes back.
function startConsoleUpdate() {
    if (_updateRunning) return;
    if (!UPDATE_META.update_supported || !(UPDATE_CHECK && UPDATE_CHECK.up_to_date === false)) return;
    showConfirmModal(t('update_now'), t('update_confirm'), () => {
        _updateRunning = true;
        _renderUpdateAction('updating', t('update_starting'), { disabled: true });
        fetch('/api/update/start', { method: 'POST' })
            .then(r => r.json())
            .then(data => {
                if (data.status === 'error') {
                    _renderUpdateAction('failed', `${t('update_failed')}: ${data.message || ''}`);
                    _updateRunning = false;
                    return;
                }
                _pollUpdateStatus();
            })
            .catch(() => {
                _renderUpdateAction('failed', t('update_failed'));
                _updateRunning = false;
            });
    });
}

function _pollUpdateStatus() {
    if (_updatePollTimer) clearInterval(_updatePollTimer);
    _updatePollTimer = setInterval(() => {
        fetch('/api/update/status')
            .then(r => {
                if (!r.ok) throw new Error('offline');
                return r.json();
            })
            .then(data => {
                const stepKey = data.step ? `update_step_${data.step}` : '';
                const stepLabel = (stepKey && I18N[currentLang] && I18N[currentLang][stepKey])
                    ? t(stepKey)
                    : (data.message || t('update_in_progress'));
                if (data.state === 'failed') {
                    clearInterval(_updatePollTimer);
                    _updatePollTimer = null;
                    _renderUpdateAction('failed', `${t('update_failed')}: ${data.error || data.message || ''}`);
                    _updateRunning = false;
                    return;
                }
                if (data.state === 'success') {
                    clearInterval(_updatePollTimer);
                    _updatePollTimer = null;
                    _renderUpdateAction('updating', t('update_reconnect'), { disabled: true });
                    _waitForBackend();
                    return;
                }
                if (data.state === 'restarting') {
                    _renderUpdateAction('updating', t('update_reconnect'), { disabled: true });
                    return;
                }
                _renderUpdateAction('updating', stepLabel, { disabled: true });
            })
            .catch(() => {
                // The old process was replaced mid-poll; switch to reconnecting.
                _renderUpdateAction('updating', t('update_reconnect'), { disabled: true });
                _waitForBackend();
            });
    }, 1500);
}

function _waitForBackend() {
    if (_updateReconnectTimer) return;
    _updateReconnectTimer = setInterval(() => {
        fetch('/api/version')
            .then(r => r.json())
            .then(data => {
                if (!data || !data.version) return;
                clearInterval(_updateReconnectTimer);
                _updateReconnectTimer = null;
                if (_updatePollTimer) {
                    clearInterval(_updatePollTimer);
                    _updatePollTimer = null;
                }
                UPDATE_META = {
                    version: data.version,
                    install_kind: data.install_kind || UPDATE_META.install_kind,
                    update_supported: !!data.update_supported,
                    unsupported_reason: data.unsupported_reason || ''
                };
                APP_VERSION = `v${data.version}`;
                _setSidebarVersionLabel(`CowAgent ${APP_VERSION}`);
                UPDATE_CHECK = { up_to_date: true, newer_releases: [], latest: null, current_release: null };
                _updateRunning = false;
                _renderUpdateAction('up_to_date', t('update_done'));
                // This tab still runs the previous release's scripts against the
                // new backend; reload so the page matches the code now serving it.
                setTimeout(() => window.location.reload(), 1500);
            })
            .catch(() => {});
    }, 1500);
}
