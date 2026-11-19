/* Project picker above the composer, and the file picker.
   Split out of console.js. These are classic scripts sharing one global
   scope; see channel/web/README.md before changing the load order. */

// =====================================================================
// Workspace selector (project picker above the input)
// =====================================================================
let _wsSelState = { current: null, recents: [], defaultWorkspace: '', projectsRoot: '' };

function _wsSelBtn() { return document.getElementById('workspace-selector-btn'); }
function _wsSelMenu() { return document.getElementById('workspace-selector-menu'); }

// Minimal self-dismissing toast for selector errors (no global toast exists).
function _wsToast(msg) {
    let el = document.getElementById('ws-sel-toast');
    if (!el) {
        el = document.createElement('div');
        el.id = 'ws-sel-toast';
        el.style.cssText = 'position:fixed;bottom:80px;left:50%;transform:translateX(-50%);' +
            'background:#1e293b;color:#fff;padding:8px 14px;border-radius:8px;font-size:13px;' +
            'z-index:9999;box-shadow:0 4px 16px rgba(0,0,0,0.2);opacity:0;transition:opacity .2s;';
        document.body.appendChild(el);
    }
    el.textContent = msg;
    el.style.opacity = '1';
    clearTimeout(el._t);
    el._t = setTimeout(() => { el.style.opacity = '0'; }, 2600);
}

// Refresh the selector state + label for the current session.
async function refreshWorkspaceSelector() {
    const label = document.getElementById('workspace-selector-label');
    try {
        // Scope the request to the active Agent so the default-workspace hint
        // matches the file panel's real root in multi-Agent setups.
        let url = `/api/projects?session=${encodeURIComponent(sessionId)}`;
        const aid = (typeof activeAgentId !== 'undefined') ? activeAgentId : '';
        if (aid) url += `&agent=${encodeURIComponent(aid)}`;
        const res = await fetch(url);
        const data = await res.json();
        if (data.status !== 'success') return;
        _wsSelState = {
            current: data.current || null,
            recents: data.recents || [],
            defaultWorkspace: data.default_workspace || '',
            projectsRoot: data.projects_root || '',
        };
        _wsSelUpdateLabel();
    } catch (e) { /* keep last label */ }
}

// Sync the selector button's label and hover tooltip with the current state.
// Called after every selection so the tooltip always shows the live full path.
function _wsSelUpdateLabel() {
    const label = document.getElementById('workspace-selector-label');
    if (label) {
        label.textContent = _wsSelState.current
            ? _wsSelState.current.name
            : t('ws_default_workspace');
    }
    const btn = _wsSelBtn();
    if (btn) {
        // The default workspace is the resting state, so it collapses to just
        // the folder icon (matching the desktop composer); a picked workspace
        // shows its name so the user knows they've moved off the default.
        btn.classList.toggle('composer-chip-icon-only', !_wsSelState.current);
        const full = _wsSelState.current
            ? _wsSelState.current.path
            : _wsSelState.defaultWorkspace;
        btn.setAttribute('data-tooltip', full || t('ws_sel_title'));
        btn.setAttribute('data-tooltip-pos', 'top');
        // Route through the body-level floating tooltip so the full path isn't
        // clipped/covered by the chat history above the input bar.
        btn.setAttribute('data-tip-float', '');
    }
}

function toggleWorkspaceSelector(event) {
    if (event) { event.preventDefault(); event.stopPropagation(); }
    const menu = _wsSelMenu();
    if (!menu) return;
    if (!menu.classList.contains('hidden')) {
        _wsSelHide();
        return;
    }
    _closeComposerMenus(menu);
    refreshWorkspaceSelector().then(renderWorkspaceSelectorMenu);
    menu.classList.remove('hidden');
    _wsSelBtn()?.classList.add('open');
}

function _wsSelHide() {
    const menu = _wsSelMenu();
    if (menu) menu.classList.add('hidden');
    _wsSelBtn()?.classList.remove('open');
}

function renderWorkspaceSelectorMenu() {
    const menu = _wsSelMenu();
    if (!menu) return;

    const parts = [];
    const isDefault = !_wsSelState.current;
    parts.push(`<div class="ws-sel-section-title">${escapeHtml(t('ws_sel_title'))}</div>`);
    // Default workspace: hovering shows the full ~/cow absolute path.
    parts.push(`
        <button class="ws-sel-item ${isDefault ? 'active' : ''}" onclick="selectWorkspaceProject(null)"
                data-tip-float data-tooltip="${escapeHtml(_wsSelState.defaultWorkspace || '')}" data-tooltip-pos="bottom">
            <i class="fas fa-house"></i>
            <span class="ws-sel-name">${escapeHtml(t('ws_default_workspace'))}</span>
            ${isDefault ? '<i class="fas fa-check ws-sel-check"></i>' : ''}
        </button>`);

    if ((_wsSelState.recents || []).length) {
        parts.push(`<div class="ws-sel-divider"></div>`);
        parts.push(`<div class="ws-sel-section-title">${escapeHtml(t('ws_sel_recents'))}</div>`);
        _wsSelState.recents.forEach(r => {
            const active = _wsSelState.current && _wsSelState.current.path === r.path;
            parts.push(`
                <button class="ws-sel-item ${active ? 'active' : ''}" onclick="selectWorkspaceProject('${_wsAttr(r.path)}')"
                        data-tip-float data-tooltip="${escapeHtml(r.path)}" data-tooltip-pos="bottom">
                    <i class="fas fa-folder"></i>
                    <span class="ws-sel-name">${escapeHtml(r.name)}</span>
                    ${active ? '<i class="fas fa-check ws-sel-check"></i>' : ''}
                </button>`);
        });
    }

    parts.push(`<div class="ws-sel-divider"></div>`);
    parts.push(`
        <button class="ws-sel-item" onclick="wsSelOpenProjectDialog()">
            <i class="fas fa-folder-open"></i>
            <span class="ws-sel-name">${escapeHtml(t('ws_sel_open'))}</span>
        </button>`);
    parts.push(`
        <button class="ws-sel-item" onclick="wsSelNewProjectDialog()">
            <i class="fas fa-folder-plus"></i>
            <span class="ws-sel-name">${escapeHtml(t('ws_sel_new'))}</span>
        </button>`);

    menu.innerHTML = parts.join('');
}

// Escape a path for safe embedding inside a single-quoted inline handler.
function _wsAttr(p) { return String(p || '').replace(/\\/g, '\\\\').replace(/'/g, "\\'"); }

// ------- Folder picker modal (open an existing project) -------
let _fpCurrent = '';   // absolute path currently listed
let _fpBound = false;  // one-time listener binding guard
let _fpOnPick = null;  // async (path) => true to close the picker

function wsSelOpenProjectDialog() {
    _wsSelHide();
    openFolderPicker({
        title: t('ws_sel_open'),
        openText: t('ws_sel_open_here'),
        onPick: (path) => _wsSelApply('/api/projects/select', { session: sessionId, project_dir: path }),
    });
}

// The server-side folder picker, shared with other views (e.g. the settings
// workspace location card). It lists folders on the machine running the agent.
function openFolderPicker({ title, openText, hint, start, onPick }) {
    _fpBindOnce();
    _fpOnPick = onPick;
    document.getElementById('folder-picker-title').textContent = title || t('ws_sel_open');
    document.getElementById('folder-picker-cancel').textContent = t('channels_cancel') || t('ws_sel_up');
    document.getElementById('folder-picker-open').textContent = openText || t('ws_sel_open_here');
    document.getElementById('folder-picker-hint').textContent = hint || t('ws_sel_dblclick_hint');
    document.getElementById('folder-picker-overlay').classList.remove('hidden');
    _fpBrowse(start || '');  // '' => backend starts at ~
}

function _fpBindOnce() {
    if (_fpBound) return;
    _fpBound = true;
    const overlay = document.getElementById('folder-picker-overlay');
    const close = () => overlay.classList.add('hidden');
    document.getElementById('folder-picker-cancel').addEventListener('click', close);
    overlay.addEventListener('click', (e) => { if (e.target === overlay) close(); });
    document.getElementById('folder-picker-open').addEventListener('click', async () => {
        if (!_fpCurrent || !_fpOnPick) return;
        const ok = await _fpOnPick(_fpCurrent);
        if (ok) close();
    });
}

// Virtual path (Windows) that lists logical drives; not a real openable dir.
const _FP_DRIVES = '__DRIVES__';

async function _fpBrowse(path) {
    const list = document.getElementById('folder-picker-list');
    list.innerHTML = `<div class="fp-empty"><i class="fas fa-spinner fa-spin"></i></div>`;
    try {
        const res = await fetch(`/api/projects/browse?path=${encodeURIComponent(path || '')}`);
        const data = await res.json();
        if (data.status !== 'success') { list.innerHTML = `<div class="fp-empty">${escapeHtml(data.message || 'error')}</div>`; return; }
        const isDrives = data.path === _FP_DRIVES;
        _fpCurrent = isDrives ? null : data.path;
        // Drives view is a selector, not a real directory: show a label and
        // disable "Open here" so the sentinel can't be picked as a project.
        const label = isDrives ? (t('ws_sel_drives') || 'This PC') : data.path;
        document.getElementById('folder-picker-path').textContent = label;
        document.getElementById('folder-picker-path').setAttribute('title', label);
        document.getElementById('folder-picker-open').disabled = isDrives;
        _fpRenderToolbar(data);
        _fpRenderList(data);
    } catch (e) {
        list.innerHTML = `<div class="fp-empty">${escapeHtml(String(e.message || e))}</div>`;
    }
}

function _fpRenderToolbar(data) {
    const bar = document.getElementById('folder-picker-toolbar');
    const upDisabled = !data.parent;
    bar.innerHTML = `
        <button class="fp-btn" ${upDisabled ? 'disabled' : ''} onclick="_fpBrowse('${_wsAttr(data.parent || '')}')" data-tooltip="${escapeHtml(t('ws_sel_up'))}" data-tooltip-pos="bottom">
            <i class="fas fa-arrow-up"></i>
        </button>
        <button class="fp-btn" onclick="_fpBrowse('~')" data-tooltip="~" data-tooltip-pos="bottom">
            <i class="fas fa-house"></i>
        </button>`;
}

function _fpRenderList(data) {
    const list = document.getElementById('folder-picker-list');
    const dirs = data.dirs || [];
    if (!dirs.length) {
        list.innerHTML = `<div class="fp-empty"><i class="fas fa-folder-open"></i><span>${escapeHtml(t('ws_sel_no_subdirs'))}</span></div>`;
        return;
    }
    list.innerHTML = dirs.map(d => `
        <div class="fp-row" ondblclick="_fpBrowse('${_wsAttr(d.path)}')" onclick="_fpSelectRow(this,'${_wsAttr(d.path)}')" title="${escapeHtml(d.path)}">
            <i class="fas fa-folder"></i>
            <span class="fp-name">${escapeHtml(d.name)}</span>
            <i class="fas fa-chevron-right fp-into" onclick="event.stopPropagation();_fpBrowse('${_wsAttr(d.path)}')"></i>
        </div>`).join('');
}

// Single click selects a child folder as the target (so you can open a folder
// without navigating into it); double click / chevron navigates inside.
function _fpSelectRow(el, path) {
    document.querySelectorAll('#folder-picker-list .fp-row.selected').forEach(r => r.classList.remove('selected'));
    el.classList.add('selected');
    _fpCurrent = path;
    // Picking a row (e.g. a drive in the drives view) is a valid target again.
    document.getElementById('folder-picker-open').disabled = false;
    document.getElementById('folder-picker-path').textContent = path;
}

// Create a new project by name (lands under the projects root), then open it.
function wsSelNewProjectDialog() {
    _wsSelHide();
    openKnowledgeDialog({
        title: t('ws_sel_new'),
        subtitle: (t('ws_sel_new_subtitle') || '').replace('{root}', _wsSelState.projectsRoot || ''),
        label: t('ws_sel_new_placeholder'),
        hint: t('ws_sel_new_hint'),
        icon: 'fa-folder-plus',
        value: '',
        validate: (v) => {
            v = (v || '').trim();
            if (!v) return t('ws_sel_name_required');
            if (v.includes('/') || v.includes('\\')) return t('ws_sel_name_no_slash');
            return '';
        },
        onSubmit: async (name) => {
            const ok = await _wsSelApply('/api/projects/create', { session: sessionId, name: name.trim() });
            return ok ? true : null;
        },
    });
}

// Shared apply path for select/create: POST, update label, then reveal the
// project in the right-hand file panel so the user sees they are "inside" it.
async function _wsSelApply(url, body) {
    try {
        const res = await fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        const data = await res.json();
        if (data.status !== 'success') { _wsToast(data.message || 'failed'); return false; }
        _wsSelState.current = data.current || null;
        if (Array.isArray(data.recents)) _wsSelState.recents = data.recents;
        if (data.default_workspace) _wsSelState.defaultWorkspace = data.default_workspace;
        _wsSelUpdateLabel();
        _wsSelRevealFiles();
        return true;
    } catch (e) { _wsToast(String(e.message || e)); return false; }
}

// Open (or refresh) the right-hand file panel on the Files tab so the newly
// selected project's directory is visible.
function _wsSelRevealFiles() {
    try {
        if (typeof openWorkspacePanel === 'function') {
            wsAutoOpenSuppressed = false;
            // Reset to the root of the new workspace before opening.
            if (typeof wsCurrentDir !== 'undefined') wsCurrentDir = '';
            openWorkspacePanel('files');
        }
        if (typeof refreshWorkspaceTree === 'function') refreshWorkspaceTree();
    } catch (e) { /* panel not present on this view */ }
}

// Kept for callers that select without a dialog (default / recents).
async function selectWorkspaceProject(projectDir) {
    _wsSelHide();
    await _wsSelApply('/api/projects/select', { session: sessionId, project_dir: projectDir });
}

document.addEventListener('click', (e) => {
    const menu = _wsSelMenu();
    const btn = _wsSelBtn();
    if (!menu || menu.classList.contains('hidden')) return;
    if (menu.contains(e.target) || (btn && btn.contains(e.target))) return;
    _wsSelHide();
});

