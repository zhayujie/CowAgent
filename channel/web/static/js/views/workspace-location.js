/* Settings: the workspace location card.
   Shows where the Agent workspace lives and schedules a move into another
   folder. The move runs when the service restarts (common/workspace_migration.py),
   so the card restarts it where the server can, and otherwise says how.
   Classic script sharing one global scope; see channel/web/README.md. */

let _wsLocInfo = null;

function _wsLocBytes(n) {
    if (n < 1024) return `${n} B`;
    const units = ['KB', 'MB', 'GB', 'TB'];
    let v = n / 1024;
    let i = 0;
    while (v >= 1024 && i < units.length - 1) { v /= 1024; i += 1; }
    return `${v.toFixed(v >= 100 ? 0 : 1)} ${units[i]}`;
}

function _wsLocFill(key, vars) {
    return Object.entries(vars || {}).reduce((s, [k, v]) => s.split(`{${k}}`).join(v), t(key));
}

function _wsLocError(code, detail) {
    const msg = t(`ws_loc_err_${code || 'copy_failed'}`);
    return detail ? `${msg}\n${detail}` : msg;
}

function _wsLocPost(body) {
    return fetch('/api/workspace-location', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
    }).then(r => r.json());
}

// tone: info | warn | error | ok
function _wsLocNotice(text, tone) {
    const box = document.getElementById('ws-loc-notice');
    if (!text) { box.classList.add('hidden'); return; }
    const tones = {
        info: ['text-primary-600 dark:text-primary-400 bg-primary-50 dark:bg-primary-900/20', 'fa-circle-info'],
        warn: ['text-amber-600 dark:text-amber-500 bg-amber-50 dark:bg-amber-900/20', 'fa-triangle-exclamation'],
        error: ['text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-900/20', 'fa-circle-xmark'],
    };
    const [cls, icon] = tones[tone] || tones.info;
    box.className = `flex items-start gap-2 text-xs rounded-lg px-3 py-2 ${cls}`;
    document.getElementById('ws-loc-notice-icon').className = `fas ${icon} mt-0.5`;
    document.getElementById('ws-loc-notice-text').textContent = text;
}

function _wsLocResultText(result) {
    if (result.ok) {
        const lines = [_wsLocFill('ws_loc_done', { target: result.to })];
        (result.warnings || []).forEach(w => {
            const at = w.indexOf(':');
            const key = w.slice(0, at) === 'link' ? 'ws_loc_warning_link' : 'ws_loc_warning_cleanup';
            lines.push(_wsLocFill(key, { path: w.slice(at + 1) }));
        });
        return lines.join('\n');
    }
    return _wsLocFill('ws_loc_failed', { reason: _wsLocError(result.code, result.detail) });
}

function _wsLocRender(info) {
    _wsLocInfo = info;
    const card = document.getElementById('config-workspace-card');
    if (!info || info.unsupported_reason === 'desktop') { card.classList.add('hidden'); return; }
    card.classList.remove('hidden');
    document.getElementById('ws-loc-path').textContent = info.workspace;
    document.getElementById('ws-loc-path').title = info.workspace;

    const pending = info.pending;
    const change = document.getElementById('ws-loc-change');
    change.disabled = !info.supported;
    change.classList.toggle('hidden', !info.supported);
    document.getElementById('ws-loc-actions').classList.toggle('hidden', !pending || info.restart !== 'auto');
    document.getElementById('ws-loc-restart').disabled = false;
    _wsLocWatch(info.supported && pending);

    if (!info.supported) {
        _wsLocNotice(t(`ws_loc_unsupported_${info.unsupported_reason}`), 'warn');
    } else if (pending) {
        let text = _wsLocFill('ws_loc_pending', { target: pending.to });
        if (info.restart !== 'auto') text += '\n' + t('ws_loc_restart_manual');
        _wsLocNotice(text, 'info');
    } else if (info.result && (!info.result.ok || (info.result.warnings || []).length)) {
        // A clean success is announced once by the dialog; only what still
        // needs attention stays on the card.
        _wsLocNotice(_wsLocResultText(info.result), info.result.ok ? 'warn' : 'error');
    } else {
        _wsLocNotice('');
    }
}

// The move runs on the next start, which may be a manual restart this page
// never hears about: watch for the request to be gone, then show the outcome.
let _wsLocWatchTimer = null;
// Bumped on every (re)start, so a poll still awaiting a reply can't revive an old loop.
let _wsLocWatchGen = 0;

function _wsLocWatch(active) {
    clearTimeout(_wsLocWatchTimer);
    _wsLocWatchTimer = null;
    const gen = ++_wsLocWatchGen;
    if (!active) return;
    let sawMove = false;
    const poll = async () => {
        let delay = 3000;
        try {
            const resp = await fetch('/api/workspace-location', { cache: 'no-store' });
            if (gen !== _wsLocWatchGen) return;
            // The restarted service may not know this login any more.
            if (resp.status === 401) { location.reload(); return; }
            const info = await resp.json();
            if (gen !== _wsLocWatchGen) return;
            if (info.migrating) {
                // Served by the stand-in the starting service runs during the move.
                sawMove = true;
                _wsLocProgress(info.progress || {});
                delay = 1000;
            } else if (info.status === 'success' && !info.pending) {
                _wsLocRestarting = false;
                _wsLocProgress(null);
                loadWorkspaceLocation();
                _wsLocAnnounce(info.result);
                return;
            }
        } catch (e) {
            if (gen !== _wsLocWatchGen) return;
            // The service is down: the move runs as soon as it starts again.
            // After the move, the stand-in hands the port to the service proper.
            _wsLocProgress({ phase: sawMove ? 'finishing' : _wsLocRestarting ? 'restarting' : 'waiting' });
            delay = 1000;
        }
        _wsLocWatchTimer = setTimeout(poll, delay);
    };
    _wsLocWatchTimer = setTimeout(poll, _wsLocRestarting ? 1000 : 3000);
}

// Set once this page asked the service to restart, so the wait reads as such.
let _wsLocRestarting = false;

// A modal over the whole console while the move runs; null closes it.
function _wsLocProgress(p) {
    let overlay = document.getElementById('ws-loc-progress');
    if (!p) { if (overlay) overlay.remove(); return; }
    if (!overlay) {
        overlay = document.createElement('div');
        overlay.id = 'ws-loc-progress';
        overlay.className = 'fixed inset-0 bg-black/50 z-[300] flex items-center justify-center';
        overlay.innerHTML = `
            <div class="bg-panel rounded-2xl border border-slate-200 dark:border-white/10 shadow-xl w-full max-w-md mx-4 p-6 space-y-4">
                <div class="flex items-center gap-3">
                    <div class="w-10 h-10 rounded-xl bg-primary-50 dark:bg-primary-900/20 flex items-center justify-center flex-shrink-0">
                        <i class="fas fa-spinner fa-spin text-primary-500"></i>
                    </div>
                    <div class="min-w-0">
                        <h3 id="ws-loc-progress-title" class="font-semibold text-slate-800 dark:text-slate-100 text-base"></h3>
                        <p id="ws-loc-progress-phase" class="text-xs text-slate-500 dark:text-slate-400 mt-0.5"></p>
                    </div>
                </div>
                <div id="ws-loc-progress-bar-wrap" class="h-2 rounded-full bg-slate-100 dark:bg-white/10 overflow-hidden">
                    <div id="ws-loc-progress-bar" class="h-full bg-primary-500 transition-all duration-300" style="width:0%"></div>
                </div>
                <p id="ws-loc-progress-count" class="text-xs text-slate-500 dark:text-slate-400 tabular-nums"></p>
                <p class="text-xs text-amber-600 dark:text-amber-500">${escapeHtml(t('ws_loc_progress_hint'))}</p>
            </div>`;
        document.body.appendChild(overlay);
    }
    const phase = p.phase || 'starting';
    document.getElementById('ws-loc-progress-title').textContent = t('ws_loc_progress_title');
    document.getElementById('ws-loc-progress-phase').textContent = t(`ws_loc_phase_${phase}`);
    const copying = phase === 'copying' && p.total_bytes > 0;
    const pct = copying ? Math.min(100, Math.floor(p.done_bytes * 100 / p.total_bytes)) : (phase === 'verifying' || phase === 'cleaning' ? 100 : 0);
    document.getElementById('ws-loc-progress-bar-wrap').classList.toggle('hidden', ['waiting', 'restarting', 'finishing'].includes(phase));
    document.getElementById('ws-loc-progress-bar').style.width = `${pct}%`;
    document.getElementById('ws-loc-progress-count').textContent = copying
        ? `${pct}% · ${_wsLocBytes(p.done_bytes)} / ${_wsLocBytes(p.total_bytes)} · ${p.done_files} / ${p.total_files}`
        : '';
}

// Each outcome is announced once per browser, whichever view is open.
const _WS_LOC_SEEN_KEY = 'cow_ws_loc_result_seen';

function _wsLocAnnounce(result) {
    if (!result || !result.finished_at) return;
    if (localStorage.getItem(_WS_LOC_SEEN_KEY) === result.finished_at) return;
    localStorage.setItem(_WS_LOC_SEEN_KEY, result.finished_at);
    showConfirmDialog({
        title: t(result.ok ? 'ws_loc_result_ok_title' : 'ws_loc_result_failed_title'),
        message: _wsLocResultText(result),
        okText: t('ws_loc_result_close'),
        hideCancel: true,
        tone: result.ok ? 'primary' : 'danger',
    });
}

// Called once the console is past the login screen: report a move the last
// start carried out, and keep watching one still waiting for a restart.
function checkWorkspaceMigration() {
    fetch('/api/workspace-location', { cache: 'no-store' }).then(r => r.json()).then(info => {
        if (info.status !== 'success' || info.unsupported_reason === 'desktop') return;
        _wsLocInfo = info;
        if (info.pending) _wsLocWatch(true);
        else _wsLocAnnounce(info.result);
    }).catch(() => {});
}

function loadWorkspaceLocation() {
    fetch('/api/workspace-location').then(r => r.json()).then(info => {
        if (info.status !== 'success') return;
        _wsLocRender(info);
        const size = document.getElementById('ws-loc-size');
        size.innerHTML = '<i class="fas fa-spinner fa-spin"></i>';
        fetch('/api/workspace-location?usage=1').then(r => r.json()).then(d => {
            size.textContent = d.status === 'success' ? _wsLocBytes(d.bytes) : '';
        }).catch(() => { size.textContent = ''; });
    }).catch(() => {});
}

async function wsLocChoose() {
    if (!_wsLocInfo || !_wsLocInfo.supported) return;
    if (_wsLocInfo.native_picker) {
        const btn = document.getElementById('ws-loc-change');
        btn.disabled = true;
        const res = await _wsLocPost({ action: 'pick', title: t('ws_loc_pick_title') }).catch(() => null);
        btn.disabled = false;
        if (res && res.status === 'success') {
            if (res.path) await _wsLocCheck(res.path);
            return;
        }
        if (res && res.code === 'pick_busy') return;
        // No dialog could be shown on this machine: browse in the page instead.
    }
    openFolderPicker({
        title: t('ws_loc_pick_title'),
        openText: t('ws_loc_pick_open'),
        hint: t('ws_loc_pick_hint'),
        onPick: _wsLocCheck,
    });
}

// Returns true to close the picker.
async function _wsLocCheck(parent) {
    try {
        const res = await _wsLocPost({ action: 'check', parent });
        if (res.status !== 'success') { _wsLocNotice(_wsLocError(res.code, res.message), 'error'); return true; }
        if (!res.check.ok) {
            const msg = _wsLocError(res.check.code, res.check.detail);
            if (typeof _wsToast === 'function') _wsToast(msg);
            else _wsLocNotice(msg, 'error');
            return false;
        }
        _wsLocConfirm(parent, res.check);
        return true;
    } catch (e) {
        _wsLocNotice(_wsLocError('copy_failed', String(e.message || e)), 'error');
        return true;
    }
}

function _wsLocConfirm(parent, check) {
    const space = check.required_bytes > 0
        ? _wsLocFill('ws_loc_space', {
            required: _wsLocBytes(check.required_bytes),
            free: check.free_bytes == null ? '—' : _wsLocBytes(check.free_bytes),
        })
        : t('ws_loc_space_rename');
    const note = t(_wsLocInfo && _wsLocInfo.restart === 'auto' ? 'ws_loc_confirm_note_auto' : 'ws_loc_confirm_note');
    showConfirmDialog({
        title: t('ws_loc_confirm_title'),
        // Sentences ending in full-width punctuation need no space between them.
        message: [_wsLocFill('ws_loc_confirm_move', { target: check.target }), space, note].join(' ').replace(/([。？]) /g, '$1'),
        okText: t('ws_loc_start_move'),
        tone: 'primary',
        onConfirm: async () => {
            const res = await _wsLocPost({ action: 'schedule', parent, keep_link: true }).catch(e => ({ code: 'copy_failed', message: String(e) }));
            if (res.status !== 'success') { _wsLocNotice(_wsLocError(res.code, res.detail || res.message), 'error'); return; }
            _wsLocRender(res);
            if (res.restart === 'auto') wsLocRestart();
        },
    });
}

async function wsLocRestart() {
    const btn = document.getElementById('ws-loc-restart');
    btn.disabled = true;
    const res = await _wsLocPost({ action: 'restart' }).catch(() => null);
    if (!res || res.status !== 'success') {
        btn.disabled = false;
        _wsLocNotice(t(`ws_loc_err_${(res && res.code) || 'restart_unsupported'}`), 'error');
        return;
    }
    // _wsLocWatch picks up the outcome once the service is back.
    _wsLocNotice(t('ws_loc_restarting'), 'info');
    _wsLocRestarting = true;
    _wsLocProgress({ phase: 'restarting' });
    _wsLocWatch(true);
}
