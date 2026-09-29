/* =====================================================================
 * Workspace panel: file preview + file manager + @ file references.
 * Loaded after console.js and reuses its globals (t, escapeHtml,
 * renderMarkdown, applyHighlighting, pendingAttachments, ...).
 * ===================================================================== */

const WS_WIDTH_KEY = 'cow_workspace_width';
const WS_DEFAULT_WIDTH = 420;
const WS_MIN_WIDTH = 280;

// Panel state
let wsPanelOpen = false;
let wsActiveTab = 'preview';
let wsCurrentFile = null;
// Preview editor state. `wsEditBaseline` is the text area's own value as loaded,
// so comparing against it tells whether anything actually changed;
// `wsEditBaseMtime` is the timestamp the server checks to detect that the agent
// rewrote the file mid-edit.
let wsEditing = false;
let wsEditBaseline = '';
let wsEditBaseMtime = null;
let wsSaving = false;
// Set once the user closes the panel by hand: from then on we stop
// auto-opening artifacts for the rest of the page session.
let wsAutoOpenSuppressed = false;
// Artifacts produced by the turn currently streaming.
let wsTurnArtifacts = [];

// File manager state
let wsCurrentDir = '';
let wsCurrentRoot = '';   // absolute path of the workspace/project root
let wsSearchMode = false;
let wsSearchTimer = null;

// =====================================================================
// Metadata helpers
// =====================================================================
const WS_KIND_ICONS = {
    directory: 'fa-folder',
    html: 'fa-file-code',
    markdown: 'fa-file-lines',
    image: 'fa-file-image',
    video: 'fa-file-video',
    audio: 'fa-file-audio',
    pdf: 'fa-file-pdf',
    csv: 'fa-file-csv',
    code: 'fa-file-code',
    office: 'fa-file-word',
    text: 'fa-file-lines',
    file: 'fa-file',
};

const WS_KIND_BY_EXT = {
    html: ['html', 'htm'],
    markdown: ['md', 'markdown'],
    image: ['jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp', 'svg', 'ico'],
    video: ['mp4', 'webm', 'mov', 'avi', 'mkv', 'm4v'],
    audio: ['mp3', 'wav', 'ogg', 'm4a', 'flac', 'aac'],
    pdf: ['pdf'],
    csv: ['csv', 'tsv'],
    code: ['py', 'js', 'ts', 'tsx', 'jsx', 'java', 'c', 'cpp', 'h', 'go', 'rs',
           'rb', 'php', 'sh', 'sql', 'css', 'scss', 'json', 'yaml', 'yml',
           'xml', 'toml', 'ini'],
    text: ['txt', 'log'],
    office: ['doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx'],
};

const WS_EXT_KIND = (() => {
    const map = {};
    for (const [kind, exts] of Object.entries(WS_KIND_BY_EXT)) {
        exts.forEach(e => { map[e] = kind; });
    }
    return map;
})();

const WS_PREVIEWABLE = new Set(
    ['html', 'markdown', 'image', 'video', 'audio', 'pdf', 'csv', 'code', 'text']
);

// Kinds the panel offers an editor for. Mirrors EDITABLE_KINDS in
// agent/protocol/artifact.py; the server rejects anything else on save.
const WS_EDITABLE = new Set(['html', 'markdown', 'csv', 'code', 'text']);

function wsKindOf(name) {
    const ext = (name || '').split('.').pop().toLowerCase();
    return WS_EXT_KIND[ext] || 'file';
}

function wsIconClass(kind) {
    return `fas ${WS_KIND_ICONS[kind] || WS_KIND_ICONS.file} ws-icon-${kind}`;
}

function wsFormatSize(bytes) {
    if (!bytes && bytes !== 0) return '';
    const units = ['B', 'KB', 'MB', 'GB'];
    let n = bytes;
    for (const u of units) {
        if (n < 1024) return `${u === 'B' ? Math.round(n) : n.toFixed(1)}${u}`;
        n /= 1024;
    }
    return `${n.toFixed(1)}TB`;
}

async function wsApi(path) {
    // Scope workspace reads to the current session so the file panel / @ picker /
    // preview follow the session's opened project directory. `sessionId` and
    // `activeAgentId` are globals from console.js on the same page.
    try {
        if (path.startsWith('/api/workspace/')) {
            const sid = (typeof sessionId !== 'undefined') ? sessionId : '';
            if (sid) path += (path.includes('?') ? '&' : '?') + 'session=' + encodeURIComponent(sid);
            // Without an opened project the root falls back to the Agent's own
            // workspace, so the file panel must say which Agent is active — else
            // it always shows the default Agent's directory.
            const aid = (typeof activeAgentId !== 'undefined') ? activeAgentId : '';
            if (aid) path += (path.includes('?') ? '&' : '?') + 'agent=' + encodeURIComponent(aid);
        }
    } catch (e) { /* globals not available yet */ }
    const res = await fetch(path);
    const data = await res.json();
    if (data.status !== 'success') throw new Error(data.message || 'Request failed');
    return data;
}

// =====================================================================
// Panel open / close / resize
// =====================================================================
function openWorkspacePanel(tab) {
    const panel = document.getElementById('workspace-panel');
    if (!panel) return;
    panel.classList.remove('hidden');
    wsPanelOpen = true;
    const width = parseInt(localStorage.getItem(WS_WIDTH_KEY), 10);
    if (width >= WS_MIN_WIDTH) panel.style.width = `${width}px`;
    if (tab) switchWorkspaceTab(tab);
}

/**
 * @param {boolean} byUser - true when triggered by the close button, which
 *   also disables auto-open for the rest of the session.
 */
function closeWorkspacePanel(byUser) {
    const panel = document.getElementById('workspace-panel');
    if (!panel) return;
    panel.classList.add('hidden');
    wsPanelOpen = false;
    if (byUser) wsAutoOpenSuppressed = true;
}

function toggleWorkspacePanel() {
    if (wsPanelOpen) {
        closeWorkspacePanel(true);
        return;
    }
    wsAutoOpenSuppressed = false;
    openWorkspacePanel(wsCurrentFile ? 'preview' : 'files');
}

function switchWorkspaceTab(tab) {
    wsActiveTab = tab;
    document.querySelectorAll('.workspace-tab').forEach(el => {
        el.classList.toggle('active', el.dataset.wsTab === tab);
    });
    document.querySelectorAll('.workspace-body').forEach(el => {
        el.classList.toggle('active', el.id === `ws-body-${tab}`);
    });
    wsUpdateHeaderActions();
    if (tab === 'files' && !document.getElementById('ws-file-list').childElementCount) {
        loadWorkspaceDir(wsCurrentDir);
    }
}

function wsUpdateHeaderActions() {
    const onFile = wsActiveTab === 'preview' && !!wsCurrentFile;
    // While editing, the viewer actions would act on the saved file rather than
    // on what is in the text area, which reads as a bug. Hide them instead.
    ['ws-btn-external', 'ws-btn-download', 'ws-btn-copy'].forEach(id => {
        document.getElementById(id)?.classList.toggle('hidden', !onFile || wsEditing);
    });
    document.getElementById('ws-btn-edit')
        ?.classList.toggle('hidden', !onFile || wsEditing || !wsIsEditable(wsCurrentFile));
    ['ws-btn-save', 'ws-btn-edit-cancel'].forEach(id => {
        document.getElementById(id)?.classList.toggle('hidden', !onFile || !wsEditing);
    });
}

function initWorkspaceResizer() {
    const resizer = document.getElementById('ws-resizer');
    const panel = document.getElementById('workspace-panel');
    if (!resizer || !panel) return;

    let startX = 0;
    let startWidth = 0;

    function onMove(e) {
        const delta = startX - e.clientX;
        const next = Math.max(WS_MIN_WIDTH, Math.min(window.innerWidth * 0.7, startWidth + delta));
        panel.style.width = `${next}px`;
    }

    function onUp() {
        resizer.classList.remove('dragging');
        document.body.style.userSelect = '';
        // The preview iframe swallows mousemove while dragging over it.
        document.getElementById('ws-preview-content')?.style.removeProperty('pointer-events');
        document.removeEventListener('mousemove', onMove);
        document.removeEventListener('mouseup', onUp);
        localStorage.setItem(WS_WIDTH_KEY, String(parseInt(panel.style.width, 10) || WS_DEFAULT_WIDTH));
    }

    resizer.addEventListener('mousedown', (e) => {
        e.preventDefault();
        startX = e.clientX;
        startWidth = panel.offsetWidth;
        resizer.classList.add('dragging');
        document.body.style.userSelect = 'none';
        document.getElementById('ws-preview-content')?.style.setProperty('pointer-events', 'none');
        document.addEventListener('mousemove', onMove);
        document.addEventListener('mouseup', onUp);
    });
}

// =====================================================================
// Preview
// =====================================================================
function wsSetPreviewEmpty(message, icon) {
    const body = document.getElementById('ws-preview-content');
    const title = document.getElementById('ws-preview-title');
    if (!body) return;
    title?.classList.add('hidden');
    body.innerHTML = `<div class="workspace-empty">
        <i class="fas ${icon || 'fa-eye'}"></i>
        <span>${escapeHtml(message)}</span>
    </div>`;
}

/**
 * Open a file in the preview tab.
 * @param {object|string} target - file metadata, or a path to resolve first.
 */
async function openInPreview(target) {
    // Opening another file replaces the editor, so settle unsaved edits first.
    if (!wsGuardUnsaved(() => openInPreview(target))) return;

    let meta = target;
    if (typeof target === 'string') {
        try {
            meta = (await wsApi(`/api/workspace/resolve?path=${encodeURIComponent(target)}`)).file;
        } catch (e) {
            openWorkspacePanel('preview');
            wsSetPreviewEmpty(t('ws_preview_failed') + ': ' + e.message, 'fa-triangle-exclamation');
            return;
        }
    }
    if (!meta) return;
    // Directories have nothing to render; browse into them instead.
    if (meta.is_dir) {
        openWorkspacePanel('files');
        switchWorkspaceTab('files');
        loadWorkspaceDir(meta.path || '');
        return;
    }

    wsCurrentFile = meta;
    wsEditing = false;
    openWorkspacePanel('preview');
    switchWorkspaceTab('preview');
    wsRenderPreviewTitle();
    wsUpdateHeaderActions();
    await wsRenderPreview(meta);
}

/** Show the current file's path, marked with a dot while edits are unsaved. */
function wsRenderPreviewTitle() {
    const title = document.getElementById('ws-preview-title');
    if (!title) return;
    if (!wsCurrentFile) {
        title.classList.add('hidden');
        return;
    }
    const name = wsCurrentFile.path || wsCurrentFile.file_name || wsCurrentFile.name || '';
    title.textContent = wsEditorDirty() ? `${name} •` : name;
    title.classList.remove('hidden');
}

async function wsRenderPreview(meta) {
    const body = document.getElementById('ws-preview-content');
    if (!body) return;
    const kind = meta.kind || wsKindOf(meta.file_name || meta.name || meta.path);
    const name = meta.file_name || meta.name || (meta.path || '').split('/').pop();
    const previewUrl = meta.preview_url;
    const rawUrl = meta.raw_url || previewUrl;

    if (kind === 'html') {
        body.innerHTML = '';
        const frame = document.createElement('iframe');
        // No allow-same-origin: the generated page runs in an opaque origin and
        // cannot reach the console's storage or auth cookie.
        frame.setAttribute('sandbox', 'allow-scripts allow-popups allow-forms allow-modals');
        frame.src = previewUrl;
        body.appendChild(frame);
        return;
    }

    if (kind === 'image') {
        body.innerHTML = `<div class="ws-pad"><img class="ws-media" src="${escapeHtml(rawUrl)}" alt="${escapeHtml(name)}"></div>`;
        return;
    }

    if (kind === 'video') {
        body.innerHTML = `<div class="ws-pad"><video class="ws-media" controls preload="metadata" src="${escapeHtml(rawUrl)}"></video></div>`;
        return;
    }

    if (kind === 'audio') {
        body.innerHTML = `<div class="ws-pad"><audio class="ws-media" controls src="${escapeHtml(rawUrl)}"></audio></div>`;
        return;
    }

    if (kind === 'pdf') {
        body.innerHTML = '';
        const frame = document.createElement('iframe');
        frame.src = previewUrl;
        body.appendChild(frame);
        return;
    }

    if (kind === 'markdown' || kind === 'code' || kind === 'text' || kind === 'csv') {
        body.innerHTML = `<div class="workspace-empty"><i class="fas fa-spinner fa-spin"></i></div>`;
        try {
            const res = await fetch(previewUrl);
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const text = await res.text();
            if (kind === 'markdown') {
                body.innerHTML = `<div class="ws-pad msg-content">${renderMarkdown(text)}</div>`;
            } else if (kind === 'csv') {
                body.innerHTML = `<pre>${escapeHtml(text)}</pre>`;
            } else {
                const lang = (name.split('.').pop() || '').toLowerCase();
                body.innerHTML = `<pre><code class="language-${escapeHtml(lang)}">${escapeHtml(text)}</code></pre>`;
            }
            applyHighlighting(body);
        } catch (e) {
            wsSetPreviewEmpty(t('ws_preview_failed') + ': ' + e.message, 'fa-triangle-exclamation');
        }
        return;
    }

    // Unsupported type: offer a download instead of a broken viewer.
    body.innerHTML = `<div class="workspace-empty">
        <i class="${wsIconClass(kind)}"></i>
        <span>${escapeHtml(name)}</span>
        <span>${escapeHtml(t('ws_no_inline_preview'))}</span>
        <a href="${escapeHtml(rawUrl)}" download="${escapeHtml(name)}"
           class="file-card-btn" style="width:auto;padding:4px 12px;border:1px solid currentColor;">
            <i class="fas fa-download"></i>&nbsp;${escapeHtml(t('ws_download'))}
        </a>
    </div>`;
}

function openPreviewExternally() {
    if (!wsCurrentFile) return;
    window.open(wsCurrentFile.preview_url || wsCurrentFile.raw_url, '_blank', 'noopener');
}

function downloadPreviewFile() {
    if (!wsCurrentFile) return;
    const a = document.createElement('a');
    a.href = wsCurrentFile.raw_url || wsCurrentFile.preview_url;
    a.download = wsCurrentFile.file_name || wsCurrentFile.name || '';
    document.body.appendChild(a);
    a.click();
    a.remove();
}

function copyPreviewPath() {
    if (!wsCurrentFile) return;
    const path = wsCurrentFile.abs_path || wsCurrentFile.path || '';
    copyToClipboard(path).then(() => {
        const btn = document.getElementById('ws-btn-copy');
        const icon = btn && btn.querySelector('i');
        if (icon) {
            icon.className = 'fas fa-check';
            setTimeout(() => { icon.className = 'fas fa-link'; }, 1500);
        }
    });
}

// =====================================================================
// Preview editor
// =====================================================================
function wsIsEditable(meta) {
    if (!meta || meta.is_dir) return false;
    return WS_EDITABLE.has(meta.kind || wsKindOf(meta.file_name || meta.name || meta.path));
}

/**
 * Path to send to the read/write API. The absolute path is unambiguous, which
 * matters for files the panel reaches outside the session's workspace root
 * (memory / knowledge assets while a project is open).
 */
function wsEditTargetPath(meta) {
    return meta.abs_path || meta.path || meta.rel_path || '';
}

function wsEditorTextarea() {
    return document.getElementById('ws-editor');
}

function wsEditorDirty() {
    const ta = wsEditorTextarea();
    return wsEditing && !!ta && ta.value !== wsEditBaseline;
}

/** Forget the editor's state, leaving what is on screen to the caller. */
function wsDiscardEditState() {
    wsEditing = false;
    wsEditBaseline = '';
    wsEditBaseMtime = null;
}

/**
 * Gate an action that would throw away the editor's contents.
 *
 * @param {function} next - run once the user agrees to discard the edits, and
 *   responsible for whatever replaces the editor. It runs with edit mode
 *   already off, so it must not be a function that bails out when not editing.
 * @returns {boolean} true when there is nothing to lose and the caller may
 *   proceed immediately; false once the confirmation has been put on screen.
 */
function wsGuardUnsaved(next) {
    if (!wsEditorDirty()) return true;
    showConfirmDialog({
        title: t('ws_edit_discard_title'),
        message: t('ws_edit_discard_msg'),
        okText: t('ws_edit_discard_ok'),
        onConfirm: () => {
            wsDiscardEditState();
            next();
        },
    });
    return false;
}

/**
 * Why the server refused to make a file editable. Truncation is reported first:
 * a partial read can also split a multi-byte character and so come back lossy,
 * but the size is the reason the user needs to hear.
 */
function wsUneditableReason(data) {
    if (data.truncated) return 'ws_edit_too_large';
    if (data.lossy) return 'ws_edit_encoding';
    return 'ws_edit_unsupported';
}

/** Load the file's current text into an editable text area. */
async function startPreviewEdit() {
    if (wsEditing || !wsIsEditable(wsCurrentFile)) return;
    const target = wsCurrentFile;
    const body = document.getElementById('ws-preview-content');
    if (!body) return;
    body.innerHTML = `<div class="workspace-empty"><i class="fas fa-spinner fa-spin"></i></div>`;

    let data;
    try {
        data = await wsApi(`/api/workspace/read?path=${encodeURIComponent(wsEditTargetPath(target))}`);
    } catch (e) {
        _wsToast(`${t('ws_edit_load_failed')}: ${e.message}`);
        await wsRenderPreview(target);
        return;
    }
    // The user may have navigated away while the request was in flight.
    if (wsCurrentFile !== target) return;
    if (!data.editable) {
        _wsToast(t(wsUneditableReason(data)));
        await wsRenderPreview(target);
        return;
    }

    wsEditing = true;
    wsEditBaseMtime = data.mtime;
    // Read the baseline back out of the text area rather than using the response
    // text: a text area normalizes CRLF to LF in its value, so a CRLF file would
    // compare as modified from the moment it loaded.
    wsEditBaseline = wsMountEditor(body, data.content).value;
    wsRenderPreviewTitle();
    wsUpdateHeaderActions();
}

/** @returns {HTMLTextAreaElement} the text area now holding the file. */
function wsMountEditor(body, content) {
    body.innerHTML = '';
    const ta = document.createElement('textarea');
    ta.id = 'ws-editor';
    ta.className = 'ws-editor';
    ta.spellcheck = false;
    ta.value = content;
    body.appendChild(ta);

    ta.addEventListener('input', wsRenderPreviewTitle);
    ta.addEventListener('keydown', (e) => {
        if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') {
            // Save in place, the way an editor does. The Save button instead
            // returns to the rendered preview.
            e.preventDefault();
            savePreviewEdit({ keepEditing: true });
        } else if (e.key === 'Escape') {
            e.preventDefault();
            cancelPreviewEdit();
        } else if (e.key === 'Tab') {
            // Otherwise Tab leaves the text area, which is never what indenting
            // a line of code is meant to do.
            e.preventDefault();
            wsInsertAtCursor(ta, '    ');
        }
    });
    ta.focus();
    return ta;
}

function wsInsertAtCursor(ta, text) {
    const { selectionStart: start, selectionEnd: end } = ta;
    ta.value = ta.value.slice(0, start) + text + ta.value.slice(end);
    ta.selectionStart = ta.selectionEnd = start + text.length;
    wsRenderPreviewTitle();
}

/**
 * Write the text area back to disk.
 *
 * @param {object} [opts]
 * @param {boolean} [opts.keepEditing] - stay in the editor after saving.
 * @param {boolean} [opts.force] - save even though the file changed on disk.
 */
async function savePreviewEdit(opts) {
    const { keepEditing = false, force = false } = opts || {};
    const ta = wsEditorTextarea();
    if (!wsEditing || !wsCurrentFile || !ta) return;
    // Ctrl+S bypasses the button's disabled state, and a second save sent
    // before the first reply carries a stale mtime - which would come back as a
    // conflict against our own write.
    if (wsSaving) return;
    // Writing an untouched file would bump its mtime for nothing.
    if (!force && !wsEditorDirty()) {
        if (!keepEditing) await wsExitEdit();
        return;
    }

    const target = wsCurrentFile;
    const content = ta.value;
    const btn = document.getElementById('ws-btn-save');
    wsSaving = true;
    btn?.classList.add('ws-btn-busy');
    try {
        const res = await fetch('/api/workspace/write', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                path: wsEditTargetPath(target),
                content: content,
                session: (typeof sessionId !== 'undefined') ? sessionId : '',
                expected_mtime: force ? null : wsEditBaseMtime,
            }),
        });
        const data = await res.json();
        if (data.code === 'conflict') {
            showConfirmDialog({
                title: t('ws_edit_conflict_title'),
                message: t('ws_edit_conflict_msg'),
                okText: t('ws_edit_overwrite'),
                onConfirm: () => savePreviewEdit({ keepEditing: keepEditing, force: true }),
            });
            return;
        }
        if (data.status !== 'success') throw new Error(data.message || 'save failed');

        wsEditBaseline = content;
        wsEditBaseMtime = data.mtime;
        target.size = data.size;
        target.mtime = data.mtime;
        _wsToast(t('ws_edit_saved'));
        if (keepEditing) {
            wsRenderPreviewTitle();
        } else {
            await wsExitEdit();
        }
    } catch (e) {
        _wsToast(`${t('ws_edit_save_failed')}: ${e.message}`);
    } finally {
        wsSaving = false;
        btn?.classList.remove('ws-btn-busy');
    }
}

function cancelPreviewEdit() {
    if (!wsEditing) return;
    // Retry through wsExitEdit rather than through this function, which bails
    // out on the very flag the guard clears before retrying.
    if (!wsGuardUnsaved(wsExitEdit)) return;
    wsExitEdit();
}

/** Leave edit mode and show the rendered preview again. */
async function wsExitEdit() {
    wsDiscardEditState();
    wsRenderPreviewTitle();
    wsUpdateHeaderActions();
    if (wsCurrentFile) await wsRenderPreview(wsCurrentFile);
}

// =====================================================================
// Artifact cards in messages
// =====================================================================

/** Build the HTML for a file card. `meta` needs file_name / kind / raw_url. */
function renderFileCard(meta) {
    const name = meta.file_name || meta.name || '';
    const kind = meta.kind || wsKindOf(name);
    const relPath = meta.rel_path || meta.path || '';
    // Skip the path when it adds nothing beyond the file name already shown.
    const sub = [relPath === name ? '' : relPath, wsFormatSize(meta.size)]
        .filter(Boolean).join(' · ');
    const payload = escapeHtml(JSON.stringify({
        file_name: name,
        rel_path: meta.rel_path || meta.path || '',
        abs_path: meta.abs_path || '',
        kind: kind,
        size: meta.size || 0,
        raw_url: meta.raw_url || '',
        preview_url: meta.preview_url || '',
        previewable: meta.previewable !== false && WS_PREVIEWABLE.has(kind),
    }));
    const canPreview = meta.previewable !== false && WS_PREVIEWABLE.has(kind);
    return `<div class="file-card" data-file='${payload}'>
        <i class="file-card-icon ${wsIconClass(kind)}"></i>
        <div class="file-card-info">
            <div class="file-card-name">${escapeHtml(name)}</div>
            ${sub ? `<div class="file-card-sub">${escapeHtml(sub)}</div>` : ''}
        </div>
        <div class="file-card-actions">
            ${canPreview ? `<div class="file-card-btn" data-action="preview" title="${escapeHtml(t('ws_preview'))}"><i class="fas fa-eye"></i></div>` : ''}
            <div class="file-card-btn" data-action="download" title="${escapeHtml(t('ws_download'))}"><i class="fas fa-download"></i></div>
        </div>
    </div>`;
}

/** Append an artifact card to a live bot bubble and remember it for auto-open. */
function appendArtifactCard(container, item) {
    if (!container) return;
    const existing = container.querySelector(`[data-artifact-path="${CSS.escape(item.abs_path || '')}"]`);
    if (existing) return;
    const wrap = document.createElement('div');
    wrap.className = 'file-card-list';
    wrap.dataset.artifactPath = item.abs_path || '';
    wrap.innerHTML = renderFileCard(item);
    container.appendChild(wrap);
    wsTurnArtifacts.push(item);
}

function resetTurnArtifacts() {
    wsTurnArtifacts = [];
}

/**
 * Auto-open policy: only when the turn produced exactly one previewable
 * artifact, only while the user hasn't dismissed the panel by hand, and never
 * over an open editor - the file cards stay in the message either way.
 */
function maybeAutoOpenArtifact() {
    const items = wsTurnArtifacts.filter(a => a.previewable);
    wsTurnArtifacts = [];
    if (wsAutoOpenSuppressed || wsEditing || items.length !== 1) return;
    openInPreview(items[0]);
}

/**
 * Render the artifact cards of a history message. The list is built by the
 * backend from the persisted write/edit steps, since only it knows the
 * workspace root and which files still exist.
 */
function renderArtifactCards(artifacts) {
    if (!Array.isArray(artifacts) || !artifacts.length) return '';
    return artifacts.map(item =>
        `<div class="file-card-list" data-artifact-path="${escapeHtml(item.abs_path || '')}">
            ${renderFileCard(item)}
        </div>`
    ).join('');
}

async function wsResolveMeta(meta) {
    if (meta.preview_url && meta.raw_url) return meta;
    const path = meta.abs_path || meta.rel_path || meta.path;
    if (!path) return null;
    return (await wsApi(`/api/workspace/resolve?path=${encodeURIComponent(path)}`)).file;
}

function wsTriggerDownload(url, name) {
    const a = document.createElement('a');
    a.href = url;
    a.download = name || '';
    document.body.appendChild(a);
    a.click();
    a.remove();
}

// Delegate clicks on file cards, inline path chips and workspace links.
// Delegation (rather than per-element listeners) is what keeps this working
// after a streamed message re-renders its innerHTML.
document.addEventListener('click', async (e) => {
    // A closer handler already claimed this click (e.g. the knowledge viewer
    // navigating between its own documents).
    if (e.defaultPrevented) return;

    // Workspace-relative link inside rendered markdown.
    const wsLink = e.target.closest('a[data-ws-path]');
    if (wsLink) {
        e.preventDefault();
        openWorkspaceLink(wsLink.dataset.wsPath);
        return;
    }

    const chip = e.target.closest('.file-chip');
    if (chip && chip.dataset.path) {
        e.preventDefault();
        openInPreview(chip.dataset.path);
        return;
    }

    // Workspace reference chip inside a user message bubble.
    const ref = e.target.closest('[data-ws-open]');
    if (ref) {
        e.preventDefault();
        openInPreview(ref.dataset.wsOpen);
        return;
    }

    const card = e.target.closest('.file-card');
    if (!card) return;
    e.preventDefault();
    let meta;
    try { meta = JSON.parse(card.dataset.file); } catch (_) { return; }

    const action = e.target.closest('[data-action]')?.dataset.action;
    if (action === 'download') {
        if (meta.raw_url) {
            wsTriggerDownload(meta.raw_url, meta.file_name);
            return;
        }
        try {
            const full = await wsResolveMeta(meta);
            if (full) wsTriggerDownload(full.raw_url, full.name);
        } catch (_) {}
        return;
    }
    openInPreview(meta.preview_url ? meta : (meta.abs_path || meta.rel_path));
});

// =====================================================================
// Inline path chips: turn local paths mentioned in text into clickable chips
// =====================================================================
const WS_PATH_EXTS = Object.values(WS_KIND_BY_EXT).flat().join('|');
// Absolute (/Users/..., C:\...), home-relative (~/cow/...) or workspace-relative
// (websites/report.html) paths, always anchored on a known file extension and
// containing at least one separator, which keeps prose like "see report.html"
// from turning into chips. Excluding `:` and `/` before the match is what stops
// the tail of an http(s) URL from being picked up.
const WS_PATH_RE = new RegExp(
    '(^|[^\\w/\\\\.~:-])((?:~\\/|\\/|[A-Za-z]:\\\\)?(?:[\\w.\\-\\u4e00-\\u9fa5]+[\\/\\\\])+[\\w.\\-\\u4e00-\\u9fa5]+\\.(?:'
    + WS_PATH_EXTS + '))(?=$|[^\\w.\\-\\u4e00-\\u9fa5]|$)',
    'gi'
);

function _buildFileChip(path) {
    const name = path.split(/[\\/]/).pop();
    const kind = wsKindOf(name);
    return `<span class="file-chip" data-path="${escapeHtml(path)}" title="${escapeHtml(path)}">` +
        `<i class="${wsIconClass(kind)}"></i>${escapeHtml(name)}</span>`;
}

/**
 * Rewrite bare file paths in already-rendered markdown into chips.
 * Only touches text nodes outside <pre>/<code>/<a> so code samples and
 * existing links stay untouched.
 */
function injectFileChips(html) {
    if (!html || !html.includes('.')) return html;

    // Split on tags; track whether we're inside a region we must not rewrite.
    let depthSkip = 0;
    return html.split(/(<[^>]+>)/).map((chunk) => {
        if (chunk.startsWith('<')) {
            const tag = chunk.match(/^<\/?\s*([a-zA-Z0-9]+)/);
            const name = tag ? tag[1].toLowerCase() : '';
            if (['pre', 'code', 'a', 'img', 'video', 'audio'].includes(name)) {
                if (chunk.startsWith('</')) depthSkip = Math.max(0, depthSkip - 1);
                else if (!chunk.endsWith('/>')) depthSkip += 1;
            }
            return chunk;
        }
        if (depthSkip > 0 || !chunk.trim()) return chunk;
        return chunk.replace(WS_PATH_RE, (match, lead, path) =>
            path.includes('://') ? match : lead + _buildFileChip(path)
        );
    }).join('');
}

// =====================================================================
// Workspace links inside rendered markdown
// =====================================================================
/**
 * Decide whether an href points at a workspace file rather than the web.
 *
 * Agent replies cite their own files with a workspace-relative markdown link
 * (`[title](knowledge/x.md)`). The browser would resolve those against the
 * console URL and open a 404 in a new tab, so they need routing to the
 * preview panel instead.
 *
 * @returns {string|null} the cleaned workspace path, or null if not one.
 */
function wsWorkspaceHref(href) {
    if (!href) return null;
    // A scheme (http, mailto, file, data), a protocol-relative host, an
    // in-page anchor or a site-absolute path is never a workspace file.
    if (/^[a-zA-Z][\w+.-]*:/.test(href)) return null;
    if (href.startsWith('//') || href.startsWith('#') || href.startsWith('/')) return null;

    let path = href.split('#')[0].split('?')[0].trim();
    // markdown-it percent-encodes non-ASCII hrefs; the API wants them raw.
    try { path = decodeURI(path); } catch (_) {}
    if (!path) return null;
    // Require a known extension so prose links stay untouched.
    return WS_EXT_KIND[(path.split('.').pop() || '').toLowerCase()] ? path : null;
}

/**
 * Open a workspace file referenced by a link in a rendered message.
 * Agent links are occasionally relative to the citing document rather than to
 * the workspace root, so fall back to a filename search before giving up.
 */
async function openWorkspaceLink(path) {
    // The panel lives in the chat view, so a link clicked from elsewhere (the
    // knowledge reader, a memory file) would otherwise open out of sight.
    if (typeof navigateTo === 'function' && currentView !== 'chat') navigateTo('chat');

    try {
        const data = await wsApi(`/api/workspace/resolve?path=${encodeURIComponent(path)}`);
        openInPreview(data.file);
        return;
    } catch (_) { /* fall through to the name search */ }

    const name = path.split('/').pop();
    try {
        const data = await wsApi(`/api/workspace/search?q=${encodeURIComponent(name)}&limit=10`);
        const hit = (data.results || []).find(r => !r.is_dir && r.name === name);
        if (hit) {
            openInPreview(hit);
            return;
        }
    } catch (_) {}

    openWorkspacePanel('preview');
    switchWorkspaceTab('preview');
    wsSetPreviewEmpty(`${t('ws_link_not_found')}: ${path}`, 'fa-triangle-exclamation');
}

// =====================================================================
// File manager tab
// =====================================================================
function refreshWorkspaceTree() {
    const input = document.getElementById('ws-search-input');
    if (input) input.value = '';
    wsSearchMode = false;
    loadWorkspaceDir(wsCurrentDir);
}

/** Switching the active Agent moves the file panel's root to that Agent's own
 *  workspace (when no project is open). Drop back to the root and reload, but
 *  only if the panel is already open — never pop it open on a switch. */
function resetWorkspaceToAgentRoot() {
    wsCurrentDir = '';
    if (wsPanelOpen) refreshWorkspaceTree();
}

async function loadWorkspaceDir(relPath) {
    const list = document.getElementById('ws-file-list');
    if (!list) return;
    list.innerHTML = `<div class="workspace-empty"><i class="fas fa-spinner fa-spin"></i></div>`;
    try {
        const data = await wsApi(`/api/workspace/tree?path=${encodeURIComponent(relPath || '')}`);
        wsCurrentDir = data.path || '';
        wsCurrentRoot = data.root || wsCurrentRoot;
        wsSearchMode = false;
        // Browsing leaves search mode; drop the stale query from the box.
        const searchBox = document.getElementById('ws-search-input');
        if (searchBox && searchBox.value) searchBox.value = '';
        renderWorkspaceBreadcrumb(wsCurrentDir);
        renderWorkspaceEntries(data.entries, data.truncated);
    } catch (e) {
        list.innerHTML = `<div class="workspace-empty">
            <i class="fas fa-triangle-exclamation"></i><span>${escapeHtml(e.message)}</span></div>`;
    }
}

function renderWorkspaceBreadcrumb(relPath) {
    const bar = document.getElementById('ws-breadcrumb');
    if (!bar) return;
    const parts = (relPath || '').split('/').filter(Boolean);
    // At the root, show the root's absolute path beside the house so the user
    // knows which directory the panel is anchored to. When navigated inside,
    // the deeper crumbs already convey location, so the house stays icon-only.
    const atRoot = parts.length === 0;
    const rootLabel = atRoot && wsCurrentRoot
        ? ` <span class="crumb-root">${escapeHtml(wsCurrentRoot)}</span>`
        : '';
    const crumbs = [`<span class="crumb" data-ws-dir="" data-tooltip="${escapeHtml(wsCurrentRoot || '')}"><i class="fas fa-house"></i>${rootLabel}</span>`];
    let acc = '';
    parts.forEach((p) => {
        acc = acc ? `${acc}/${p}` : p;
        crumbs.push('<span class="sep">/</span>');
        crumbs.push(`<span class="crumb" data-ws-dir="${escapeHtml(acc)}">${escapeHtml(p)}</span>`);
    });
    bar.innerHTML = crumbs.join('');
}

function renderWorkspaceEntries(entries, truncated) {
    const list = document.getElementById('ws-file-list');
    if (!list) return;
    if (!entries || entries.length === 0) {
        list.innerHTML = `<div class="workspace-empty"><i class="fas fa-folder-open"></i>
            <span>${escapeHtml(t('ws_empty_dir'))}</span></div>`;
        return;
    }
    const rows = entries.map(entry => {
        const meta = entry.is_dir ? '' : wsFormatSize(entry.size);
        return `<div class="ws-file-row" ${wsRowAttrs(entry)}>
            <i class="${wsIconClass(entry.kind)}"></i>
            <span class="ws-file-name">${escapeHtml(entry.name)}</span>
            <span class="ws-file-meta">${escapeHtml(meta)}</span>
        </div>`;
    });
    if (truncated) {
        rows.push(`<div class="workspace-empty" style="height:auto;padding:12px;">
            <span>${escapeHtml(t('ws_truncated'))}</span></div>`);
    }
    list.innerHTML = rows.join('');
}

/**
 * Row attributes for a tree/search entry. Everything is draggable into the
 * composer; `data-ws-dir` additionally makes a click navigate rather than
 * preview, since directories have nothing to render.
 */
function wsRowAttrs(entry) {
    const payload = escapeHtml(JSON.stringify(entry));
    const nav = entry.is_dir ? ` data-ws-dir="${escapeHtml(entry.path)}"` : '';
    return `data-ws-file='${payload}' draggable="true"${nav}`;
}

function renderWorkspaceSearchResults(results) {
    const list = document.getElementById('ws-file-list');
    if (!list) return;
    if (!results.length) {
        list.innerHTML = `<div class="workspace-empty"><i class="fas fa-magnifying-glass"></i>
            <span>${escapeHtml(t('ws_no_results'))}</span></div>`;
        return;
    }
    list.innerHTML = results.map(entry => `
        <div class="ws-file-row" ${wsRowAttrs(entry)}>
            <i class="${wsIconClass(entry.kind)}"></i>
            <span class="ws-file-name">${escapeHtml(entry.name)}</span>
            <span class="ws-file-path">${escapeHtml(entry.path)}</span>
        </div>`).join('');
}

async function runWorkspaceSearch(query) {
    if (!query.trim()) {
        loadWorkspaceDir(wsCurrentDir);
        return;
    }
    try {
        const data = await wsApi(`/api/workspace/search?q=${encodeURIComponent(query)}&limit=60`);
        wsSearchMode = true;
        renderWorkspaceSearchResults(data.results || []);
    } catch (e) {
        const list = document.getElementById('ws-file-list');
        if (list) {
            list.innerHTML = `<div class="workspace-empty">
                <i class="fas fa-triangle-exclamation"></i><span>${escapeHtml(e.message)}</span></div>`;
        }
    }
}

function initWorkspaceFilesTab() {
    const list = document.getElementById('ws-file-list');
    const bar = document.getElementById('ws-breadcrumb');
    const input = document.getElementById('ws-search-input');

    bar?.addEventListener('click', (e) => {
        const crumb = e.target.closest('[data-ws-dir]');
        if (crumb) loadWorkspaceDir(crumb.dataset.wsDir);
    });

    list?.addEventListener('click', (e) => {
        const row = e.target.closest('.ws-file-row');
        if (!row) return;
        if (row.dataset.wsDir !== undefined) {
            loadWorkspaceDir(row.dataset.wsDir);
            return;
        }
        list.querySelectorAll('.ws-file-row.active').forEach(el => el.classList.remove('active'));
        row.classList.add('active');
        try { openInPreview(JSON.parse(row.dataset.wsFile)); } catch (_) {}
    });

    list?.addEventListener('dragstart', (e) => {
        const row = e.target.closest('.ws-file-row[data-ws-file]');
        if (!row) return;
        e.dataTransfer.effectAllowed = 'copy';
        e.dataTransfer.setData('application/x-cow-workspace-file', row.dataset.wsFile);
    });

    input?.addEventListener('input', () => {
        clearTimeout(wsSearchTimer);
        const q = input.value;
        wsSearchTimer = setTimeout(() => runWorkspaceSearch(q), 200);
    });
}

// =====================================================================
// Drag a workspace file into the conversation
// =====================================================================
function addWorkspaceRefAttachment(entry) {
    const relPath = entry.path || entry.rel_path || '';
    if (!relPath) return;
    if (pendingAttachments.some(a => a.file_type === 'workspace_ref' && a.file_path === relPath)) return;
    pendingAttachments.push({
        file_path: relPath,
        file_name: entry.name || entry.file_name || relPath.split('/').pop(),
        // Referenced in place; the backend must not treat it as an upload.
        file_type: 'workspace_ref',
        is_dir: !!entry.is_dir,
    });
    renderAttachmentPreview();
}

function initWorkspaceDropTarget() {
    const target = document.getElementById('chat-main');
    if (!target) return;

    const isWorkspaceDrag = (e) =>
        Array.from(e.dataTransfer?.types || []).includes('application/x-cow-workspace-file');

    target.addEventListener('dragover', (e) => {
        if (!isWorkspaceDrag(e)) return;
        e.preventDefault();
        e.dataTransfer.dropEffect = 'copy';
        target.classList.add('ws-drop-active');
    });

    // relatedTarget is the node being entered; moving between descendants of the
    // target still fires dragleave, so only clear when the pointer truly left.
    target.addEventListener('dragleave', (e) => {
        if (!target.contains(e.relatedTarget)) target.classList.remove('ws-drop-active');
    });

    // No stopPropagation: the outer #view-chat drop handler owns resetting the
    // upload overlay state, and it ignores drops that carry no files.
    target.addEventListener('drop', (e) => {
        if (!isWorkspaceDrag(e)) return;
        e.preventDefault();
        target.classList.remove('ws-drop-active');
        try {
            addWorkspaceRefAttachment(JSON.parse(e.dataTransfer.getData('application/x-cow-workspace-file')));
        } catch (_) {}
    });
}

// =====================================================================
// @ file references in the chat input
// =====================================================================
let mentionActive = false;
let mentionStart = -1;
let mentionItems = [];
let mentionIndex = 0;
let mentionTimer = null;

function hideMentionMenu() {
    mentionActive = false;
    mentionStart = -1;
    mentionItems = [];
    document.getElementById('mention-menu')?.classList.add('hidden');
}

function renderMentionMenu() {
    const menu = document.getElementById('mention-menu');
    if (!menu) return;
    if (!mentionItems.length) {
        menu.innerHTML = `<div class="mention-empty">${escapeHtml(t('ws_no_results'))}</div>`;
        menu.classList.remove('hidden');
        return;
    }
    menu.innerHTML = mentionItems.map((item, i) => {
        if (item.kind === 'agent') {
            const face = typeof agentAvatarHTML === 'function'
                ? agentAvatarHTML(item, 20)
                : `<i class="fas fa-user"></i>`;
            return `<div class="mention-item ${i === mentionIndex ? 'active' : ''}" data-idx="${i}">
                ${face}
                <span class="m-name">${escapeHtml(item.name)}</span>
                <span class="m-path">${escapeHtml(item.id)}</span>
            </div>`;
        }
        return `<div class="mention-item ${i === mentionIndex ? 'active' : ''}" data-idx="${i}">
            <i class="${wsIconClass(item.kind)}"></i>
            <span class="m-name">${escapeHtml(item.name)}</span>
            <span class="m-path">${escapeHtml(item.path)}</span>
        </div>`;
    }).join('');
    menu.classList.remove('hidden');
}

function matchingAgentMentions(query) {
    // @ addresses one Agent in particular, which only means something once a
    // conversation has more than its owner. A solo chat keeps @ as the file
    // picker it always was.
    if (typeof sharedConversation !== 'function' || !sharedConversation()) return [];
    const q = String(query || '').toLowerCase();
    // The owner is offered alongside its teammates: in a group chat it is one
    // voice among several, and @ is how the user picks it back out after a
    // teammate has been speaking. sessionRoster() already lists it first.
    const roster = typeof sessionRoster === 'function' ? sessionRoster() : [];
    return roster
        .filter(agent => !q || agent.id.toLowerCase().includes(q) || String(agent.name).toLowerCase().includes(q))
        .slice(0, 6)
        .map(agent => ({ kind: 'agent', id: agent.id, name: agent.name, avatar: agent.avatar || '' }));
}

async function updateMentionQuery(query) {
    const agents = matchingAgentMentions(query);
    try {
        const data = await wsApi(`/api/workspace/search?q=${encodeURIComponent(query)}&limit=12`);
        if (!mentionActive) return;
        mentionItems = agents.concat(data.results || []);
        mentionIndex = 0;
        renderMentionMenu();
    } catch (_) {
        if (!mentionActive) return;
        mentionItems = agents;
        mentionIndex = 0;
        if (agents.length) renderMentionMenu();
        else hideMentionMenu();
    }
}

function acceptMention(idx) {
    const item = mentionItems[idx];
    const input = document.getElementById('chat-input');
    if (!item || !input) return;
    const before = input.value.slice(0, mentionStart);
    const after = input.value.slice(input.selectionStart);
    if (item.kind === 'agent') {
        // Write the name, not the id: the mention is addressed to a colleague
        // and should read like one. The server resolves either form.
        const inserted = `@${item.name || item.id} `;
        input.value = before + inserted + after;
        input.selectionStart = input.selectionEnd = before.length + inserted.length;
        if (typeof addTeamMember === 'function') addTeamMember(item.id);
    } else {
        addWorkspaceRefAttachment(item);
        // Drop the "@query" fragment: the file travels as an attachment, not as text.
        input.value = before + after;
        input.selectionStart = input.selectionEnd = before.length;
    }
    hideMentionMenu();
    input.focus();
    input.dispatchEvent(new Event('input'));
}

function initMention() {
    const input = document.getElementById('chat-input');
    const menu = document.getElementById('mention-menu');
    if (!input || !menu) return;

    input.addEventListener('input', () => {
        const pos = input.selectionStart;
        const before = input.value.slice(0, pos);
        // Trigger on "@" at the start of the input or after whitespace.
        const match = before.match(/(?:^|\s)@([^\s@]*)$/);
        if (!match) {
            if (mentionActive) hideMentionMenu();
            return;
        }
        mentionActive = true;
        mentionStart = pos - match[1].length - 1;
        clearTimeout(mentionTimer);
        const q = match[1];
        mentionTimer = setTimeout(() => updateMentionQuery(q), 150);
    });

    // Capture phase so Enter/arrows are consumed before the send handler.
    input.addEventListener('keydown', (e) => {
        if (!mentionActive || !mentionItems.length) return;
        if (e.key === 'ArrowDown') {
            e.preventDefault();
            e.stopImmediatePropagation();
            mentionIndex = (mentionIndex + 1) % mentionItems.length;
            renderMentionMenu();
        } else if (e.key === 'ArrowUp') {
            e.preventDefault();
            e.stopImmediatePropagation();
            mentionIndex = (mentionIndex - 1 + mentionItems.length) % mentionItems.length;
            renderMentionMenu();
        } else if (e.key === 'Enter' || e.key === 'Tab') {
            e.preventDefault();
            e.stopImmediatePropagation();
            acceptMention(mentionIndex);
        } else if (e.key === 'Escape') {
            e.preventDefault();
            e.stopImmediatePropagation();
            hideMentionMenu();
        }
    }, true);

    menu.addEventListener('mousedown', (e) => {
        const item = e.target.closest('.mention-item');
        if (!item) return;
        e.preventDefault();
        acceptMention(parseInt(item.dataset.idx, 10));
    });

    document.addEventListener('click', (e) => {
        if (mentionActive && !menu.contains(e.target) && e.target !== input) hideMentionMenu();
    });
}

/** Re-render the JS-generated parts of the panel after a language switch. */
function relocalizeWorkspacePanel() {
    if (!wsCurrentFile) wsSetPreviewEmpty(t('ws_preview_empty'));
    if (wsActiveTab === 'files' && !wsSearchMode
        && document.getElementById('ws-file-list')?.childElementCount) {
        loadWorkspaceDir(wsCurrentDir);
    }
}

// Reset the panel when the active session changes. The file tree and preview
// are scoped to a session's working dir (project or default), so stale state
// from the previous session must be dropped and, if open, reloaded against the
// new session's root.
function wsOnSessionSwitch() {
    wsCurrentDir = '';
    wsCurrentRoot = '';
    wsSearchMode = false;
    wsCurrentFile = null;
    wsTurnArtifacts = [];
    wsDiscardEditState();
    wsUpdateHeaderActions();
    if (!wsPanelOpen) return;
    if (wsActiveTab === 'files') {
        loadWorkspaceDir('');
    } else {
        wsSetPreviewEmpty(t('ws_preview_empty'));
    }
}

// =====================================================================
// Init
// =====================================================================
function initWorkspacePanel() {
    initWorkspaceResizer();
    initWorkspaceFilesTab();
    initWorkspaceDropTarget();
    initMention();
    wsSetPreviewEmpty(t('ws_preview_empty'));

    // Reloading or closing the tab would drop an open editor's changes silently.
    window.addEventListener('beforeunload', (e) => {
        if (!wsEditorDirty()) return;
        e.preventDefault();
        e.returnValue = '';
    });

    // The panel belongs to the chat view only; follow view switches.
    const toggle = document.getElementById('workspace-toggle-btn');
    const chatView = document.getElementById('view-chat');
    if (toggle && chatView) {
        const sync = () => toggle.classList.toggle('hidden', !chatView.classList.contains('active'));
        sync();
        new MutationObserver(sync).observe(chatView, { attributes: true, attributeFilter: ['class'] });
    }
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initWorkspacePanel);
} else {
    initWorkspacePanel();
}
