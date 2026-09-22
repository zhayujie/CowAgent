/* Built-in tools and installed skills.
   Split out of console.js. These are classic scripts sharing one global
   scope; see channel/web/README.md before changing the load order. */

// =====================================================================
// Skills View
// =====================================================================
let toolsLoaded = false;

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
    memory_get: 'fa-brain',
    memory_search: 'fa-brain',
};

function getToolIcon(name) {
    return TOOL_ICONS[name] || 'fa-wrench';
}

function loadSkillsView() {
    loadToolsSection();
    loadSkillsSection();
}

function loadToolsSection() {
    if (toolsLoaded) return;
    const emptyEl = document.getElementById('tools-empty');
    const listEl = document.getElementById('tools-list');
    const badge = document.getElementById('tools-count-badge');

    fetch('/api/tools').then(r => r.json()).then(data => {
        if (data.status !== 'success') return;
        const tools = data.tools || [];
        emptyEl.classList.add('hidden');
        if (tools.length === 0) {
            emptyEl.classList.remove('hidden');
            emptyEl.innerHTML = `<span class="text-sm text-slate-400 dark:text-slate-500">${currentLang === 'zh' ? '暂无内置工具' : 'No built-in tools'}</span>`;
            return;
        }
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
                    <div class="flex items-center gap-2">
                        <span class="font-medium text-sm text-slate-700 dark:text-slate-200 font-mono">${escapeHtml(tool.name)}</span>
                    </div>
                    <p class="text-xs text-slate-400 dark:text-slate-500 mt-1 line-clamp-2">${escapeHtml(tool.description || '--')}</p>
                </div>`;
            listEl.appendChild(card);
        });
        listEl.classList.remove('hidden');
        toolsLoaded = true;
    }).catch(() => {
        emptyEl.classList.remove('hidden');
        emptyEl.innerHTML = `<span class="text-sm text-slate-400 dark:text-slate-500">${currentLang === 'zh' ? '加载失败' : 'Failed to load'}</span>`;
    });
}

function loadSkillsSection() {
    const emptyEl = document.getElementById('skills-empty');
    const listEl = document.getElementById('skills-list');
    const badge = document.getElementById('skills-count-badge');

    fetch('/api/skills').then(r => r.json()).then(data => {
        if (data.status !== 'success') return;
        const skills = data.skills || [];
        if (skills.length === 0) {
            const p = emptyEl.querySelector('p');
            if (p) p.textContent = currentLang === 'zh' ? '暂无技能' : 'No skills found';
            return;
        }
        badge.textContent = skills.length;
        badge.classList.remove('hidden');
        emptyEl.classList.add('hidden');
        listEl.innerHTML = '';

        skills.forEach(sk => {
            const card = document.createElement('div');
            card.className = 'bg-white dark:bg-[#1A1A1A] rounded-xl border border-slate-200 dark:border-white/10 '
                + 'p-4 flex items-start gap-3 transition-opacity cursor-pointer '
                + 'hover:border-slate-300 dark:hover:border-white/20';
            card.dataset.skillName = sk.name;
            card.dataset.skillDesc = sk.description || '';
            card.dataset.skillDisplayName = sk.display_name || '';
            card.dataset.enabled = sk.enabled ? '1' : '0';
            renderSkillCard(card, sk);
            listEl.appendChild(card);
        });
    }).catch(() => {});
}

function renderSkillCard(card, sk) {
    const enabled = sk.enabled;
    const iconColor = enabled ? 'text-primary-400' : 'text-slate-300 dark:text-slate-600';
    const trackClass = enabled
        ? 'bg-primary-400'
        : 'bg-slate-200 dark:bg-slate-700';
    const thumbTranslate = enabled ? 'translate-x-3' : 'translate-x-0.5';
    card.innerHTML = `
        <div class="w-9 h-9 rounded-lg bg-amber-50 dark:bg-amber-900/20 flex items-center justify-center flex-shrink-0">
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
                <button
                    role="switch"
                    data-skill-switch
                    aria-checked="${enabled}"
                    class="relative inline-flex h-4 w-7 flex-shrink-0 cursor-pointer rounded-full transition-colors duration-200 ease-in-out focus:outline-none ${trackClass}"
                    title="${enabled ? (currentLang === 'zh' ? '点击禁用' : 'Click to disable') : (currentLang === 'zh' ? '点击启用' : 'Click to enable')}"
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

    fetch('/api/skills', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action, name })
    })
    .then(r => r.json())
    .then(data => {
        if (data.status === 'success') {
            if (card) {
                card.dataset.enabled = currentlyEnabled ? '0' : '1';
                card.style.opacity = '1';
                renderSkillCard(card, {
                    name: name,
                    description: card.dataset.skillDesc || '',
                    display_name: card.dataset.skillDisplayName || '',
                    enabled: !currentlyEnabled,
                });
            }
        } else {
            if (card) card.style.opacity = '1';
            alert(currentLang === 'zh' ? '操作失败，请稍后再试' : 'Operation failed, please try again');
        }
    })
    .catch(() => {
        if (card) card.style.opacity = '1';
        alert(currentLang === 'zh' ? '操作失败，请稍后再试' : 'Operation failed, please try again');
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

/**
 * Split a skill's SKILL.md into its YAML frontmatter fields and the markdown
 * body. The `---` header is metadata, not prose: fed to the markdown renderer
 * as-is it turns into a giant bold heading and a horizontal rule. Pull it out
 * so the viewer can present name/description as a proper header instead.
 *
 * @returns {{fields: Array<[string, string]>, body: string}}
 */
function parseSkillFrontmatter(content) {
    const text = content || '';
    const match = text.match(/^---\s*\r?\n([\s\S]*?)\r?\n---\s*\r?\n?/);
    if (!match) return { fields: [], body: text };

    const fields = [];
    for (const raw of match[1].split(/\r?\n/)) {
        const line = raw.trim();
        if (!line || line.startsWith('#')) continue;
        const idx = line.indexOf(':');
        if (idx === -1) continue;
        const key = line.slice(0, idx).trim();
        let value = line.slice(idx + 1).trim();
        // Drop surrounding quotes a YAML scalar may carry.
        value = value.replace(/^['"]|['"]$/g, '');
        if (key) fields.push([key, value]);
    }
    return { fields, body: text.slice(match[0].length) };
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
        const rows = fields.map(([key, value]) => `
            <div class="flex gap-3 text-sm">
                <span class="flex-shrink-0 w-24 font-medium text-slate-400 dark:text-slate-500">${escapeHtml(key)}</span>
                <span class="flex-1 min-w-0 text-slate-700 dark:text-slate-200 break-words">${escapeHtml(value)}</span>
            </div>`).join('');
        headerHtml = `
            <div class="mb-5 pb-5 border-b border-slate-100 dark:border-white/10 space-y-2">
                ${rows}
            </div>`;
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

    // The switch in the header goes with the panel: with no listing there is
    // nothing to show, folded away or not.
    const toggle = document.getElementById('skill-files-toggle');
    const listed = _skillFiles.length > 0;
    if (toggle) {
        toggle.classList.toggle('hidden', !listed);
        toggle.classList.toggle('doc-action-btn-on', listed && _skillFilesPanelOpen);
        toggle.setAttribute('aria-pressed', String(_skillFilesPanelOpen));
    }

    const show = listed && _skillFilesPanelOpen;
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
        row.style.paddingLeft = `${10 + file.depth * 13}px`;
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
    document.getElementById('skills-panel-viewer')?.classList.add('hidden');
    document.getElementById('skills-panel-list')?.classList.remove('hidden');
}

// ---------------------------------------------------------------------
// Creating a skill: a form, or an uploaded folder / archive
// ---------------------------------------------------------------------

// The server's own ceilings, mirrored so a 50 MB folder is refused here rather
// than after being uploaded. See SkillService.MAX_UPLOAD_*.
const SKILL_UPLOAD_MAX_FILES = 500;
const SKILL_UPLOAD_MAX_FILE_SIZE = 10 * 1024 * 1024;
const SKILL_UPLOAD_MAX_TOTAL_SIZE = 50 * 1024 * 1024;

let _skillCreateMode = 'form';
let _skillCreateFiles = [];
let _skillUploadArchive = null;
/** A picked folder, as `{file, relPath}` pairs the upload sends side by side. */
let _skillUploadFolder = [];
let _skillCreateBusy = false;
let _skillUploadDropReady = false;
let _skillAttachMenuReady = false;

function openSkillCreateDialog(mode) {
    resetSkillCreateDialog();
    switchSkillCreateMode(mode || 'form');
    document.getElementById('skill-create-overlay')?.classList.remove('hidden');
    initSkillUploadDropZone();
    initSkillAttachMenu();
    // A folder picker is Chromium/WebKit only; without it the dialog would
    // offer a button and a menu entry that do nothing.
    [['skill-upload-folder-btn', 'skill-upload-folder'],
     ['skill-create-folder-option', 'skill-create-folder']].forEach(([btnId, inputId]) => {
        const btn = document.getElementById(btnId);
        const input = document.getElementById(inputId);
        if (btn) btn.classList.toggle('hidden', !(input && 'webkitdirectory' in input));
    });
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
    clearSkillUploadSelection();
    hideSkillAttachMenu();
    setSkillCreateError('');
}

function switchSkillCreateMode(mode) {
    _skillCreateMode = mode === 'upload' ? 'upload' : 'form';
    document.querySelectorAll('[data-skill-create-tab]').forEach(tab => {
        const active = tab.dataset.skillCreateTab === _skillCreateMode;
        tab.classList.toggle('bg-white', active);
        tab.classList.toggle('dark:bg-white/10', active);
        tab.classList.toggle('shadow-sm', active);
        tab.classList.toggle('text-slate-700', active);
        tab.classList.toggle('dark:text-slate-100', active);
        tab.classList.toggle('text-slate-500', !active);
        tab.classList.toggle('dark:text-slate-400', !active);
    });
    document.getElementById('skill-create-panel-form')?.classList.toggle('hidden', _skillCreateMode !== 'form');
    document.getElementById('skill-create-panel-upload')?.classList.toggle('hidden', _skillCreateMode !== 'upload');

    const submit = document.getElementById('skill-create-submit');
    if (submit) {
        // Kept in step with data-i18n so a language switch re-translates it.
        const key = _skillCreateMode === 'upload' ? 'skill_upload_submit' : 'skill_new_submit';
        submit.dataset.i18n = key;
        submit.textContent = t(key);
    }
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

function selectSkillUploadArchive() {
    const input = document.getElementById('skill-upload-archive');
    if (!input) return;
    input.value = '';
    input.onchange = () => {
        const file = (input.files || [])[0];
        if (file) setSkillUploadArchive(file);
    };
    input.click();
}

function selectSkillUploadFolder() {
    const input = document.getElementById('skill-upload-folder');
    if (!input) return;
    input.value = '';
    input.onchange = () => {
        const files = Array.from(input.files || []);
        if (files.length) setSkillUploadFolder(files);
    };
    input.click();
}

function setSkillUploadArchive(file) {
    if (!/\.(zip|tgz|tar|gz)$/i.test(file.name || '')) {
        setSkillCreateError(t('skill_upload_bad_archive'));
        return;
    }
    _skillUploadArchive = file;
    _skillUploadFolder = [];
    renderSkillUploadSelection('fa-file-zipper', `${file.name} · ${formatSkillFileSize(file.size)}`);
}

function setSkillUploadFolder(files) {
    const wanted = skillUploadCandidates(files);
    const error = validateSkillUploadFiles(wanted);
    if (error) {
        setSkillCreateError(error);
        return;
    }
    _skillUploadArchive = null;
    _skillUploadFolder = wanted.map(file => ({ file, relPath: skillAttachmentPath(file) }));
    renderSkillUploadSelection('fa-folder-open', t('skill_upload_folder_files')
        .replace('{root}', _skillUploadFolder[0].relPath.split('/')[0] || '')
        .replace('{count}', _skillUploadFolder.length));
}

function renderSkillUploadSelection(icon, label) {
    setSkillCreateError('');
    const summary = document.getElementById('skill-upload-summary');
    const iconEl = document.getElementById('skill-upload-summary-icon');
    const nameEl = document.getElementById('skill-upload-summary-name');
    if (iconEl) iconEl.className = `fas ${icon} text-slate-400 text-xs`;
    if (nameEl) nameEl.textContent = label;
    summary?.classList.remove('hidden');
}

function clearSkillUploadSelection() {
    _skillUploadArchive = null;
    _skillUploadFolder = [];
    document.getElementById('skill-upload-summary')?.classList.add('hidden');
}

/** Check a batch of picked files against the server's caps. '' when they pass. */
function validateSkillUploadFiles(files) {
    if (!files || !files.length) return t('skill_upload_required');
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

function initSkillUploadDropZone() {
    if (_skillUploadDropReady) return;
    const zone = document.getElementById('skill-upload-dropzone');
    if (!zone) return;
    _skillUploadDropReady = true;
    const highlight = (on) => {
        zone.classList.toggle('border-primary-400', on);
        zone.classList.toggle('bg-primary-50', on);
        zone.classList.toggle('dark:bg-primary-900/10', on);
    };
    ['dragenter', 'dragover'].forEach(name => {
        zone.addEventListener(name, event => {
            if (!event.dataTransfer?.types?.includes('Files')) return;
            event.preventDefault();
            highlight(true);
        });
    });
    ['dragleave', 'drop'].forEach(name => {
        zone.addEventListener(name, event => {
            highlight(false);
            if (event.type !== 'drop') return;
            event.preventDefault();
            // A dropped directory arrives as an entry whose contents this
            // handler cannot read, so it points at the folder picker instead of
            // uploading an empty archive.
            const entry = event.dataTransfer?.items?.[0]?.webkitGetAsEntry?.();
            if (entry && entry.isDirectory) {
                setSkillCreateError(t('skill_upload_drop_dir'));
                return;
            }
            const file = (event.dataTransfer?.files || [])[0];
            if (file) setSkillUploadArchive(file);
        });
    });
}

function submitSkillCreate() {
    if (_skillCreateBusy) return;
    if (_skillCreateMode === 'upload') return submitSkillUpload();
    return submitSkillForm();
}

function submitSkillForm() {
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
    return postSkillCreate('/api/skills/create', form,
        data => ({ message: `${t('skill_new_created')}: ${data.name}` }));
}

function submitSkillUpload() {
    const form = new FormData();
    if (_skillUploadArchive) {
        form.append('archive', _skillUploadArchive, _skillUploadArchive.name);
    } else if (_skillUploadFolder.length) {
        // Paired field by field, the way the chat's directory upload sends a
        // folder: the file's own name says nothing about where it sat in it.
        _skillUploadFolder.forEach(({ file, relPath }) => {
            form.append('files', file);
            form.append('relative_paths', relPath);
        });
    } else {
        return setSkillCreateError(t('skill_upload_required'));
    }

    return postSkillCreate('/api/skills/upload', form, data => {
        const installed = (data.installed || []).concat(data.replaced || []);
        const skipped = data.skipped || [];
        if (!installed.length) {
            // Every skill in the upload was refused: show the first reason,
            // which is the only actionable part of the answer.
            return { error: skipped.length ? `${skipped[0].name}: ${skipped[0].reason}` : t('skill_upload_none') };
        }
        let message = `${t('skill_upload_installed')}: ${installed.join(', ')}`;
        if (skipped.length) {
            message += ` · ${t('skill_upload_skipped')}: ${skipped.map(s => s.name).join(', ')}`;
        }
        return { message };
    });
}

/**
 * Send a create or upload request and report the outcome.
 *
 * @param describe maps a successful response to `{message}` to toast, or to
 *   `{error}` when the server accepted the request but installed nothing.
 */
async function postSkillCreate(url, formData, describe) {
    setSkillCreateBusy(true);
    setSkillCreateError('');
    let data = null;
    try {
        const res = await fetch(url, { method: 'POST', body: formData });
        data = await res.json();
    } catch (e) {
        data = null;
    } finally {
        setSkillCreateBusy(false);
    }

    if (!data) return setSkillCreateError(t('skill_new_failed'));
    if (data.status !== 'success') return setSkillCreateError(data.message || t('skill_new_failed'));

    const outcome = describe(data);
    if (outcome.error) return setSkillCreateError(outcome.error);
    closeSkillCreateDialog();
    _wsToast(outcome.message);
    loadSkillsSection();
}

