/* Knowledge base tree, import and relation graph.
   Split out of console.js. These are classic scripts sharing one global
   scope; see channel/web/README.md before changing the load order. */

// =====================================================================
// Knowledge View
// =====================================================================
// The whole tree arrives in one request (the server caches page titles), but
// rows are only built for open folders and a folder renders its files a page
// at a time, so a base of tens of thousands of pages stays as responsive as a
// small one without a request per click.
const KNOWLEDGE_EXPAND_ALL_LIMIT = 1000;
const KNOWLEDGE_FOLDER_PAGE = 200;
const KNOWLEDGE_SEARCH_LIMIT = 300;
// Replaced on every load, so async work can tell it belongs to an older view.
let _knowledgeState = null;
let _knowledgeDocumentRequest;
let _knowledgeCurrentFile = null;
let _knowledgeGraphLoaded = false;
// Which tab is selected, and whether the base has anything to show in it.
// Both panels stay hidden behind the empty state until the list says there
// are pages; starts false so the first load shows only the loading text.
let _knowledgeTab = 'docs';
let _knowledgeHasPages = false;
const KNOWLEDGE_IMPORT_MAX_FILES = 100;
const KNOWLEDGE_IMPORT_MAX_FILE_SIZE = 10 * 1024 * 1024;
const KNOWLEDGE_IMPORT_MAX_TOTAL_SIZE = 200 * 1024 * 1024;

// Which Agent's knowledge base the page is viewing. Persisted like the memory
// page's selector so a refresh keeps the last choice. An Agent on "shared" mode
// resolves to the shared base on the backend, so this simply scopes the view.
let knowledgeAgentId = localStorage.getItem('cow_knowledge_agent') || '';

function viewingKnowledgeAgentId() {
    return knowledgeAgentId || activeAgentId || defaultAgentId;
}

// Append the viewed Agent to a knowledge URL. The global fetch wrapper only
// injects activeAgentId when no agent_id is present, so an explicit one wins.
function _kbUrl(path) {
    const joiner = path.includes('?') ? '&' : '?';
    return `${path}${joiner}agent_id=${encodeURIComponent(viewingKnowledgeAgentId())}`;
}

function renderKnowledgeAgentSelect() {
    const el = document.getElementById('knowledge-agent-select');
    if (!el) return;
    const current = viewingKnowledgeAgentId();
    const list = agentCatalog.length ? agentCatalog : enabledAgents();
    const options = list.map(a => ({ value: a.id, label: a.name || a.id, agent: a }));
    // Nothing to switch between with a single Agent (or before the roster loads).
    el.style.display = options.length < 2 ? 'none' : '';
    initDropdown(el, options, current, (value) => selectKnowledgeAgent(value), { withAvatar: true });
}

function selectKnowledgeAgent(agentId) {
    // Another Agent's base replaces the open document, edit and all.
    if (!knowledgeEditor.guard(() => selectKnowledgeAgent(agentId))) return;
    knowledgeAgentId = agentId;
    localStorage.setItem('cow_knowledge_agent', agentId);
    loadKnowledgeView();
}

// The knowledge page's half of the console's inline document editor. The
// memory and skill pages build theirs in views/doc-viewers.js; all three share
// the dirty tracking, the mtime baseline and the discard guard.
const knowledgeEditor = createDocEditor({
    body: () => document.getElementById('knowledge-viewer-body'),
    buttons: () => ({
        edit: document.getElementById('knowledge-btn-edit'),
        save: document.getElementById('knowledge-btn-save'),
        cancel: document.getElementById('knowledge-btn-cancel'),
    }),
    read: (doc) => knowledgeReadDoc(doc.path),
    write: (doc, content, mtime) => knowledgeWriteDoc(doc, content, mtime),
    render: (doc) => renderKnowledgeDoc(doc),
    // index.md and log.md are maintained by the Agent, and a page too large to
    // write back is refused up front rather than at save time.
    canEdit: (doc) => doc.editable,
    onState: (state) => docRenderTitle('knowledge-viewer-title', knowledgeEditor.current()?.title, state),
});

/** Read one knowledge page's raw Markdown. Throws so the editor can report it. */
async function knowledgeReadDoc(path) {
    const res = await fetch(_kbUrl(`/api/knowledge/read?path=${encodeURIComponent(path)}`));
    const data = await res.json();
    if (data.status !== 'success') throw new Error(data.message || 'read failed');
    return data;
}

/**
 * Save a knowledge page and let the backend reindex it.
 *
 * Translated into the shape createDocEditor expects: the string `conflict`
 * code it offers to overwrite, and the new mtime as the next baseline.
 */
async function knowledgeWriteDoc(doc, content, expectedMtime) {
    const state = _knowledgeState;
    const res = await fetch('/api/knowledge/action', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
            action: 'update_document',
            payload: {path: doc.path, content: content, expected_mtime: expectedMtime},
            agent_id: viewingKnowledgeAgentId(),
        }),
    });
    const data = await res.json();
    if (data.status === 'success' && state === _knowledgeState) _refreshKnowledgeTree();
    return {
        status: data.status,
        code: data.payload?.conflict ? 'conflict' : data.code,
        message: data.message,
        mtime: data.payload?.mtime,
    };
}

function _knowledgeLabel(zh, en) {
    return currentLang === 'zh' ? zh : en;
}

// Rows at the root use the stylesheet's padding; inside a folder they indent
// one step past the folder's own button.
function _knowledgeRowPadding(depth) {
    return depth ? (24 + (depth - 1) * 12) + 'px' : '';
}

function _knowledgeTreeButton(label, handler, depth = 0) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'knowledge-tree-file text-slate-500';
    button.style.paddingLeft = _knowledgeRowPadding(depth);
    button.textContent = label;
    button.onclick = handler;
    return button;
}

function _knowledgeTreeText(label) {
    const message = document.createElement('p');
    message.className = 'px-2 py-1 text-xs text-slate-500';
    message.textContent = label;
    return message;
}

// Flatten the list response into folder nodes keyed by path (in display
// order) and every page in the order the tree shows them.
function _indexKnowledgeTree(data) {
    const files = [];
    const byPath = new Map();
    const folders = new Map();
    const build = (name, path, rawFiles, rawChildren) => {
        const node = {name, path, files: [], children: [], count: 0};
        folders.set(path, node);
        for (const f of rawFiles || []) {
            const file = {path: path ? `${path}/${f.name}` : f.name, name: f.name, title: f.title || f.name};
            file.search = `${file.title}\n${file.name}`.toLowerCase();
            node.files.push(file);
            files.push(file);
            byPath.set(file.path, file);
        }
        for (const group of rawChildren || []) {
            node.children.push(build(group.dir, path ? `${path}/${group.dir}` : group.dir, group.files, group.children));
        }
        node.count = node.files.length + node.children.reduce((sum, child) => sum + child.count, 0);
        return node;
    };
    const root = build('', '', data.root_files, data.tree);
    return {root, files, byPath, folders, stats: data.stats || {}};
}

async function _fetchKnowledgeTree() {
    const response = await fetch(_kbUrl('/api/knowledge/list'));
    const data = await response.json();
    if (data.status !== 'success') throw new Error(data.message || 'list failed');
    return _indexKnowledgeTree(data);
}

// Take over a freshly fetched tree, keeping the folders the user opened. In a
// small base every folder starts open, including ones that appear later.
function _adoptKnowledgeTree(state, tree) {
    const expandAll = tree.files.length <= KNOWLEDGE_EXPAND_ALL_LIMIT;
    for (const path of [...state.expanded]) {
        if (!tree.folders.has(path)) state.expanded.delete(path);
    }
    for (const path of tree.folders.keys()) {
        if (path && expandAll && !state.known.has(path)) state.expanded.add(path);
    }
    state.known = new Set(tree.folders.keys());
    state.tree = tree;
    _knowledgeHasPages = tree.files.length > 0 || tree.root.children.length > 0;
    _knowledgeGraphLoaded = false;
    const empty = document.getElementById('knowledge-empty');
    if (!_knowledgeHasPages) empty.querySelector('p').textContent = t('knowledge_empty_hint');
    document.getElementById('knowledge-empty-guide').classList.toggle('hidden', _knowledgeHasPages);
    _renderKnowledgeStats(tree.stats);
    _applyKnowledgePanels();
}

function _renderKnowledgeStats(stats) {
    const pages = stats.pages || 0;
    const size = stats.size || 0;
    const sizeStr = size < 1024 ? `${size} B`
        : size < 1024 * 1024 ? `${(size / 1024).toFixed(1)} KB`
        : `${(size / 1024 / 1024).toFixed(1)} MB`;
    document.getElementById('knowledge-stats').textContent =
        _knowledgeLabel(`${pages} 篇 · ${sizeStr}`, `${pages} pages · ${sizeStr}`);
}

function _resetKnowledgeDocument() {
    _knowledgeDocumentRequest = null;
    _knowledgeCurrentFile = null;
    knowledgeEditor.forget();
    document.getElementById('knowledge-sidebar').classList.remove('hidden');
    document.getElementById('knowledge-content-placeholder').classList.toggle('hidden', window.innerWidth < 768);
    document.getElementById('knowledge-content-viewer').classList.add('hidden');
}

function loadKnowledgeView(targetPath) {
    if (_knowledgeState) clearTimeout(_knowledgeState.searchTimer);
    const state = {tree: null, expanded: new Set(), shown: new Map(), known: new Set(), query: '', searchTimer: null};
    _knowledgeState = state;
    if (knowledgeAgentId && agentCatalog.length && !agentCatalog.some(a => a.id === knowledgeAgentId)) {
        knowledgeAgentId = '';
        localStorage.removeItem('cow_knowledge_agent');
    }
    _resetKnowledgeDocument();
    _knowledgeGraphLoaded = false;
    _knowledgeHasPages = false;
    document.getElementById('knowledge-search').value = '';
    document.getElementById('knowledge-stats').textContent = '';
    document.getElementById('knowledge-tree').replaceChildren();
    const empty = document.getElementById('knowledge-empty');
    empty.querySelector('p').textContent = t('knowledge_loading');
    document.getElementById('knowledge-empty-guide').classList.add('hidden');
    switchKnowledgeTab('docs');
    renderKnowledgeAgentSelect();
    initKnowledgeImportDropZone();

    _fetchKnowledgeTree().then(tree => {
        if (state !== _knowledgeState) return;
        _adoptKnowledgeTree(state, tree);
        if (!_knowledgeHasPages) return;
        renderKnowledgeTree();
        _openInitialKnowledgeFile(targetPath);
    }).catch(() => {
        if (state !== _knowledgeState) return;
        empty.querySelector('p').replaceChildren(_knowledgeTreeButton(
            _knowledgeLabel('加载失败，点击重试', 'Loading failed. Retry'), () => loadKnowledgeView(targetPath)));
    });
}

// Land on the requested page, else the index, else the first page in the tree.
function _openInitialKnowledgeFile(targetPath) {
    const tree = _knowledgeState?.tree;
    if (!tree) return;
    if (targetPath) {
        openKnowledgeFile(targetPath, undefined, true);
        return;
    }
    // On a phone the tree is the landing screen; a page opens over it on tap.
    if (window.innerWidth < 768) {
        document.getElementById('knowledge-content-placeholder').classList.add('hidden');
        document.getElementById('knowledge-content-viewer').classList.add('hidden');
        return;
    }
    const first = tree.byPath.get('index.md') || tree.files[0];
    if (first) openKnowledgeFile(first.path, first.title, true);
}

// Open every folder above a page, page its folder forward far enough to
// include it, and scroll its row into view.
function _revealKnowledgeFile(path) {
    const state = _knowledgeState;
    const tree = state?.tree;
    if (!tree) return;
    let changed = false;
    if (!state.query) {
        const parts = path.split('/');
        parts.pop();
        for (let i = 1; i <= parts.length; i++) {
            const folder = parts.slice(0, i).join('/');
            if (!tree.folders.has(folder)) return;
            if (!state.expanded.has(folder)) {
                state.expanded.add(folder);
                changed = true;
            }
        }
        const parent = tree.folders.get(parts.join('/'));
        const index = parent ? parent.files.findIndex(file => file.path === path) : -1;
        const shown = Math.max(state.shown.get(parent?.path) || 0, KNOWLEDGE_FOLDER_PAGE);
        if (index >= shown) {
            state.shown.set(parent.path, Math.ceil((index + 1) / KNOWLEDGE_FOLDER_PAGE) * KNOWLEDGE_FOLDER_PAGE);
            changed = true;
        }
    }
    if (changed) renderKnowledgeTree();
    document.querySelector(`#knowledge-tree .knowledge-tree-file[data-path="${CSS.escape(path)}"]`)
        ?.scrollIntoView({block: 'nearest'});
}

function _markKnowledgeActive(path) {
    document.querySelectorAll('#knowledge-tree .knowledge-tree-file.active').forEach(el => el.classList.remove('active'));
    if (!path) return;
    document.querySelector(`#knowledge-tree .knowledge-tree-file[data-path="${CSS.escape(path)}"]`)?.classList.add('active');
}

function _knowledgeFileRow(file, depth) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'knowledge-tree-file' + (_knowledgeCurrentFile === file.path ? ' active' : '');
    button.dataset.path = file.path;
    button.style.paddingLeft = _knowledgeRowPadding(depth);
    button.innerHTML = `<i class="fas fa-file-lines text-[10px] text-slate-400"></i><span class="truncate">${escapeHtml(file.title)}</span>${_knowledgeFileActions(file.path)}`;
    button.onclick = () => openKnowledgeFile(file.path, file.title);
    return button;
}

function _knowledgeFolderGroup(node, depth, filter) {
    const open = !!filter || _knowledgeState.expanded.has(node.path);
    const group = document.createElement('div');
    group.className = 'knowledge-tree-group' + (open ? ' open' : '');
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'knowledge-tree-group-btn';
    button.style.paddingLeft = (8 + depth * 12) + 'px';
    button.setAttribute('aria-expanded', String(open));
    const count = filter ? filter.counts.get(node.path) : node.count;
    button.innerHTML = `<i class="fas fa-chevron-right chevron"></i><i class="fas fa-folder text-amber-400 text-[11px]"></i><span class="truncate">${escapeHtml(node.name)}</span><span class="ml-auto text-[10px] text-slate-400">${count}</span>${_knowledgeCategoryActions(node.path)}`;
    button.onclick = () => _toggleKnowledgeFolder(group, node, depth, filter);
    group.appendChild(button);
    if (open) group.appendChild(_knowledgeFolderItems(node, depth + 1, filter));
    return group;
}

// Only the toggled folder changes: its rows are built on open and dropped on
// close, so collapsing a huge folder also frees its DOM.
function _toggleKnowledgeFolder(group, node, depth, filter) {
    const open = !group.classList.contains('open');
    group.classList.toggle('open', open);
    group.firstElementChild.setAttribute('aria-expanded', String(open));
    if (filter) return;
    if (open) {
        _knowledgeState.expanded.add(node.path);
        group.appendChild(_knowledgeFolderItems(node, depth + 1));
    } else {
        _knowledgeState.expanded.delete(node.path);
        group.querySelector(':scope > .knowledge-tree-group-items')?.remove();
    }
}

function _knowledgeFolderItems(node, depth, filter) {
    const items = document.createElement('div');
    items.className = 'knowledge-tree-group-items';
    _fillKnowledgeFolder(items, node, depth, filter);
    return items;
}

// Files first, then sub-folders, as the tree has always listed them. Past a
// page of files, a "show more" row renders the next page in place.
function _fillKnowledgeFolder(container, node, depth, filter) {
    const state = _knowledgeState;
    const files = filter ? node.files.filter(file => filter.files.has(file.path)) : node.files;
    const limit = filter ? files.length : Math.max(state.shown.get(node.path) || 0, KNOWLEDGE_FOLDER_PAGE);
    for (let i = 0; i < files.length && i < limit; i++) container.appendChild(_knowledgeFileRow(files[i], depth));
    if (files.length > limit) {
        const rest = files.length - limit;
        container.appendChild(_knowledgeTreeButton(_knowledgeLabel(`显示更多（还有 ${rest} 篇）`, `Show more (${rest} left)`), () => {
            state.shown.set(node.path, limit + KNOWLEDGE_FOLDER_PAGE);
            container.replaceChildren();
            _fillKnowledgeFolder(container, node, depth, filter);
        }, depth));
    }
    for (const child of node.children) {
        if (filter && !filter.counts.has(child.path)) continue;
        container.appendChild(_knowledgeFolderGroup(child, depth, filter));
    }
}

// Matches in tree order, capped, with per-folder match counts for the labels.
function _knowledgeFilter(tree, query) {
    const needle = query.toLowerCase();
    const files = new Set();
    const counts = new Map();
    let total = 0;
    for (const file of tree.files) {
        if (!file.search.includes(needle)) continue;
        total++;
        if (files.size >= KNOWLEDGE_SEARCH_LIMIT) continue;
        files.add(file.path);
        const parts = file.path.split('/');
        for (let i = parts.length - 1; i > 0; i--) {
            const folder = parts.slice(0, i).join('/');
            counts.set(folder, (counts.get(folder) || 0) + 1);
        }
    }
    return {files, counts, total};
}

function renderKnowledgeTree() {
    const state = _knowledgeState;
    const container = document.getElementById('knowledge-tree');
    const scrollTop = container.scrollTop;
    container.replaceChildren();
    if (!state?.tree) return;
    const filter = state.query ? _knowledgeFilter(state.tree, state.query) : null;
    if (filter && !filter.files.size) {
        container.appendChild(_knowledgeTreeText(_knowledgeLabel('没有匹配的文档', 'No matching documents')));
        return;
    }
    _fillKnowledgeFolder(container, state.tree.root, 0, filter);
    if (filter && filter.total > filter.files.size) {
        container.appendChild(_knowledgeTreeText(_knowledgeLabel(
            `共 ${filter.total} 篇匹配，仅显示前 ${filter.files.size} 篇`,
            `Showing the first ${filter.files.size} of ${filter.total} matches`)));
    }
    container.scrollTop = scrollTop;
}

function filterKnowledgeTree(query) {
    const state = _knowledgeState;
    if (!state) return;
    clearTimeout(state.searchTimer);
    const apply = () => {
        state.query = query.trim();
        renderKnowledgeTree();
    };
    // Filtering is in memory; only a large base needs typing to pause first.
    if (!state.tree || state.tree.files.length <= KNOWLEDGE_EXPAND_ALL_LIMIT) apply();
    else state.searchTimer = setTimeout(apply, 150);
}

/**
 * Refetch the tree after a change, keeping open folders, the search and the
 * viewer. A save may have rewritten the page's H1, its title in the tree, but
 * the document on screen, or the text area still open over it, stays put.
 */
async function _refreshKnowledgeTree() {
    const state = _knowledgeState;
    try {
        const tree = await _fetchKnowledgeTree();
        if (state !== _knowledgeState) return;
        _adoptKnowledgeTree(state, tree);
        renderKnowledgeTree();
        const doc = knowledgeEditor.current();
        const file = doc && tree.byPath.get(doc.path);
        if (file && file.title !== doc.title) {
            doc.title = file.title;
            docRenderTitle('knowledge-viewer-title', doc.title, {dirty: knowledgeEditor.isDirty()});
        }
    } catch (error) {
        /* The tree on screen is merely stale; the change itself went through. */
    }
}

// Keep a renamed folder, and everything open beneath it, open under its new path.
function _remapKnowledgeFolders(state, oldPath, newPath) {
    const moved = path => path === oldPath || path.startsWith(oldPath + '/');
    for (const set of [state.expanded, state.known]) {
        for (const path of [...set]) {
            if (!moved(path)) continue;
            set.delete(path);
            set.add(newPath + path.slice(oldPath.length));
        }
    }
}

function _knowledgeActionButton(icon, title, handler) {
    const danger = icon === 'fa-trash' ? ' danger' : '';
    return `<span role="button" tabindex="0" title="${escapeHtml(title)}" onclick="event.stopPropagation();${handler}" class="knowledge-action${danger}"><i class="fas ${icon}"></i></span>`;
}

function _knowledgeFileActions(path) {
    if (path === 'index.md' || path === 'log.md') return '';
    const value = escapeHtml(JSON.stringify(path)).replace(/"/g, '&quot;');
    return `<span class="knowledge-actions">${_knowledgeActionButton('fa-arrow-right-arrow-left', '移动', `moveKnowledgeDocument(${value})`)}${_knowledgeActionButton('fa-trash', '删除', `deleteKnowledgeDocument(${value})`)}</span>`;
}

function _knowledgeCategoryActions(path) {
    const value = escapeHtml(JSON.stringify(path)).replace(/"/g, '&quot;');
    return `<span class="knowledge-actions">${_knowledgeActionButton('fa-pen', '重命名', `renameKnowledgeCategory(${value})`)}${_knowledgeActionButton('fa-trash', '删除', `deleteKnowledgeCategory(${value})`)}</span>`;
}

async function dispatchKnowledgeAction(action, payload, openPathResolver) {
    const state = _knowledgeState;
    _setKnowledgeStatus(currentLang === 'zh' ? '处理中...' : 'Working...', false, true);
    try {
        const response = await fetch('/api/knowledge/action', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({action, payload, agent_id: viewingKnowledgeAgentId()}),
        });
        const result = await response.json();
        if (state !== _knowledgeState) return result.payload;
        if (result.status !== 'success') {
            _setKnowledgeStatus(result.message || (currentLang === 'zh' ? '操作失败' : 'Operation failed'), true);
            _refreshKnowledgeTree();
            return null;
        }
        _setKnowledgeStatus(_knowledgeResultMessage(action, result.payload), false);
        const current = _knowledgeCurrentFile;
        let next = openPathResolver?.(result.payload);
        if (action === 'rename_category' || action === 'delete_category') {
            const oldPath = result.payload?.old_path || result.payload?.path;
            if (oldPath && action === 'rename_category') _remapKnowledgeFolders(state, oldPath, result.payload.path);
            if (oldPath && current?.startsWith(oldPath + '/')) {
                if (action === 'rename_category') next = result.payload.path + current.slice(oldPath.length);
                _resetKnowledgeDocument();
            }
        } else if (action === 'move_documents' || action === 'delete_documents') {
            const affected = result.payload?.results?.find(item => item.path === current);
            if (affected?.moved || affected?.deleted || affected?.reason === 'not_found') {
                if (affected.moved) next = affected.target;
                _resetKnowledgeDocument();
            }
        }
        await _refreshKnowledgeTree();
        if (state !== _knowledgeState) return result.payload;
        if (next) openKnowledgeFile(next, undefined, true);
        else if (!_knowledgeCurrentFile) _openInitialKnowledgeFile();
        return result.payload;
    } catch (error) {
        _setKnowledgeStatus(currentLang === 'zh' ? '请求失败，请稍后重试' : 'Request failed, please try again', true);
        return null;
    }
}

function _setKnowledgeStatus(message, isError, persistent) {
    const el = document.getElementById('knowledge-action-status');
    el.textContent = message;
    el.className = `text-xs transition-opacity duration-200 ${isError ? 'text-red-500' : 'text-primary-500'}`;
    el.classList.remove('opacity-0');
    clearTimeout(el._hideTimer);
    if (!persistent) el._hideTimer = setTimeout(() => el.classList.add('opacity-0'), 3500);
}

function _knowledgeResultMessage(action, payload) {
    if (currentLang !== 'zh') {
        return action === 'create_category' ? 'Category created' :
            action === 'create_document' ? 'Document created' :
            action === 'rename_category' ? 'Category renamed' :
            action === 'delete_category' ? 'Category deleted' :
            action === 'import_documents' ? `${payload?.imported || 0} imported · ${payload?.skipped || 0} skipped · ${payload?.failed || 0} failed` :
            action === 'move_documents' ? `${payload?.moved || 0} document moved` :
            `${payload?.deleted || 0} document deleted`;
    }
    return action === 'create_category' ? '分类已创建' :
        action === 'create_document' ? '文档已创建' :
        action === 'rename_category' ? '分类已重命名' :
        action === 'delete_category' ? '分类已删除' :
        action === 'import_documents' ? `导入 ${payload?.imported || 0} 个，跳过 ${payload?.skipped || 0} 个，失败 ${payload?.failed || 0} 个` :
        action === 'move_documents' ? `已移动 ${payload?.moved || 0} 个文档` :
        `已删除 ${payload?.deleted || 0} 个文档`;
}

function _knowledgeCategoryPaths() {
    const tree = _knowledgeState?.tree;
    return tree ? [...tree.folders.keys()].filter(Boolean) : [];
}

function openKnowledgeDialog(options) {
    const overlay = document.getElementById('knowledge-dialog-overlay');
    const card = document.getElementById('knowledge-dialog-card');
    const input = document.getElementById('knowledge-dialog-input');
    const select = document.getElementById('knowledge-dialog-select');
    const textarea = document.getElementById('knowledge-dialog-textarea');
    const documentForm = document.getElementById('knowledge-document-form');
    const documentFilename = document.getElementById('knowledge-document-filename');
    const documentContent = document.getElementById('knowledge-document-content');
    const templateBtn = document.getElementById('knowledge-document-template');
    const documentPathPreview = document.getElementById('knowledge-document-path-preview');
    const submit = document.getElementById('knowledge-dialog-submit');
    const cancel = document.getElementById('knowledge-dialog-cancel');
    document.getElementById('knowledge-dialog-title').textContent = options.title;
    document.getElementById('knowledge-dialog-subtitle').textContent = options.subtitle || '';
    document.getElementById('knowledge-dialog-label').textContent = options.label;
    document.getElementById('knowledge-dialog-hint').textContent = options.hint || '';
    document.getElementById('knowledge-dialog-error').classList.add('hidden');
    document.getElementById('knowledge-dialog-icon').className = `fas ${options.icon || 'fa-folder'} text-emerald-500`;
    card.classList.toggle('knowledge-document-dialog', options.type === 'document');
    input.classList.toggle('hidden', options.type === 'select' || options.type === 'textarea' || options.type === 'document');
    select.classList.toggle('hidden', options.type !== 'select');
    textarea.classList.toggle('hidden', options.type !== 'textarea');
    documentForm.classList.toggle('hidden', options.type !== 'document');
    input.value = options.value || '';
    textarea.value = options.value || '';
    documentFilename.value = options.filename || '';
    documentContent.value = options.content || '';
    document.getElementById('knowledge-document-category-label').textContent = currentLang === 'zh' ? '目标分类' : 'Destination category';
    documentPathPreview.textContent = options.category
        ? `knowledge/${options.category}/`
        : 'knowledge/';
    documentFilename.oninput = null;
    document.getElementById('knowledge-document-filename-label').textContent = currentLang === 'zh' ? '文件名' : 'Filename';
    document.getElementById('knowledge-document-content-label').textContent = currentLang === 'zh' ? 'Markdown 内容' : 'Markdown content';
    templateBtn.textContent = currentLang === 'zh' ? '插入模板' : 'Insert template';
    templateBtn.onclick = () => {
        if (documentContent.value.trim()) return;
        const title = (documentFilename.value || 'untitled').replace(/\.md$/i, '');
        documentContent.value = currentLang === 'zh'
            ? `# ${title}\n\n## 摘要\n\n\n## 关键点\n\n- \n\n## 参考\n\n`
            : `# ${title}\n\n## Summary\n\n\n## Key points\n\n- \n\n## References\n\n`;
        documentContent.focus();
    };
    if (options.type === 'select') {
        // Use the shared custom dropdown component instead of a native
        // <select> so the arrow / menu match the rest of the console.
        const ddOptions = (options.choices || []).map(value => ({ value, label: value }));
        initDropdown(select, ddOptions, (options.choices || [])[0] || '', null);
    }
    submit.textContent = currentLang === 'zh' ? '确定' : 'Confirm';
    cancel.textContent = currentLang === 'zh' ? '取消' : 'Cancel';
    submit.disabled = options.type === 'select' && !(options.choices || []).length;

    const close = () => overlay.classList.add('hidden');
    const submitAction = async () => {
        const rawValue = options.type === 'select' ? getDropdownValue(select) :
            (options.type === 'textarea' ? textarea.value :
            (options.type === 'document' ? {
                filename: documentFilename.value.trim(),
                content: documentContent.value,
            } : input.value));
        const value = options.type === 'textarea' || options.type === 'document' ? rawValue : rawValue.trim();
        const error = options.validate ? options.validate(value) : (!value ? (currentLang === 'zh' ? '此项不能为空' : 'This field is required') : '');
        if (error) {
            const errorEl = document.getElementById('knowledge-dialog-error');
            errorEl.textContent = error;
            errorEl.classList.remove('hidden');
            return;
        }
        submit.disabled = true;
        const ok = await options.onSubmit(value);
        submit.disabled = false;
        if (ok !== null) close();
    };
    submit.onclick = submitAction;
    cancel.onclick = close;
    overlay.onclick = event => { if (event.target === overlay) close(); };
    input.onkeydown = event => { if (event.key === 'Enter') submitAction(); };
    overlay.classList.remove('hidden');
    setTimeout(() => (options.type === 'select' ? select : (options.type === 'textarea' ? textarea : (options.type === 'document' ? documentFilename : input))).focus(), 0);
}

function closeKnowledgeNewMenu() {
    const list = document.getElementById('knowledge-new-menu-list');
    if (list) list.classList.add('hidden');
    document.removeEventListener('click', _knowledgeNewMenuOutside, true);
}

function _knowledgeNewMenuOutside(event) {
    const menu = document.getElementById('knowledge-new-menu');
    if (menu && !menu.contains(event.target)) closeKnowledgeNewMenu();
}

function toggleKnowledgeNewMenu(event) {
    if (event) event.stopPropagation();
    const list = document.getElementById('knowledge-new-menu-list');
    if (!list) return;
    const willOpen = list.classList.contains('hidden');
    list.classList.toggle('hidden');
    if (willOpen) {
        document.addEventListener('click', _knowledgeNewMenuOutside, true);
    } else {
        document.removeEventListener('click', _knowledgeNewMenuOutside, true);
    }
}

function createKnowledgeCategory() {
    if (!knowledgeEditor.guard(createKnowledgeCategory)) return;
    openKnowledgeDialog({
        title: currentLang === 'zh' ? '新建分类' : 'New category',
        subtitle: currentLang === 'zh' ? '分类会创建为 knowledge/ 下的目录' : 'Creates a directory under knowledge/',
        label: currentLang === 'zh' ? '分类路径' : 'Category path',
        hint: currentLang === 'zh' ? '支持嵌套路径，例如 research/ai' : 'Nested paths are supported, e.g. research/ai',
        icon: 'fa-folder-plus',
        onSubmit: path => dispatchKnowledgeAction('create_category', {path}),
    });
}

function createKnowledgeDocument() {
    if (!knowledgeEditor.guard(createKnowledgeDocument)) return;
    const categories = _knowledgeCategoryPaths();
    if (!categories.length) {
        _setKnowledgeStatus(currentLang === 'zh' ? '请先创建分类' : 'Create a category first', true);
        return;
    }
    openKnowledgeDialog({
        title: currentLang === 'zh' ? '新建文档' : 'New document',
        subtitle: currentLang === 'zh' ? '先选择分类，然后输入文件名' : 'Choose a category, then enter a filename',
        label: currentLang === 'zh' ? '目标分类' : 'Destination category',
        type: 'select',
        choices: categories,
        icon: 'fa-file-circle-plus',
        onSubmit: category => {
            openKnowledgeDocumentEditor(category);
            return null;
        },
    });
}

function openKnowledgeDocumentEditor(category) {
    openKnowledgeDialog({
        title: currentLang === 'zh' ? '新建文档' : 'New document',
        subtitle: currentLang === 'zh' ? `保存到 ${category}` : `Save to ${category}`,
        label: '',
        hint: currentLang === 'zh' ? '文件名可省略 .md 后缀；保存后会自动同步索引。' : 'The .md suffix is optional. Index sync runs after saving.',
        type: 'document',
        category,
        filename: '',
        content: '',
        icon: 'fa-file-circle-plus',
        validate: value => {
            if (!value.filename) return currentLang === 'zh' ? '文件名不能为空' : 'Filename is required';
            if (/\.[^.]+$/i.test(value.filename) && !/\.md$/i.test(value.filename)) {
                return currentLang === 'zh' ? '新建文档仅支持 .md 文件名' : 'New documents must be .md files';
            }
            if (!value.content.trim()) return currentLang === 'zh' ? '内容不能为空' : 'Content is required';
            if (new Blob([value.content]).size > KNOWLEDGE_IMPORT_MAX_FILE_SIZE) {
                return currentLang === 'zh' ? '内容不能超过 10MB' : 'Content cannot exceed 10MB';
            }
            return '';
        },
        onSubmit: value => {
            const safeName = value.filename.endsWith('.md') ? value.filename : `${value.filename}.md`;
            return dispatchKnowledgeAction('create_document', {
                path: `${category}/${safeName}`,
                content: value.content,
                overwrite: false,
            }, payload => payload?.path || `${category}/${safeName}`);
        },
    });
}

function selectKnowledgeImportFiles() {
    const input = document.getElementById('knowledge-import-input');
    input.value = '';
    input.onchange = () => {
        if (input.files && input.files.length) openKnowledgeImportDialog(Array.from(input.files));
    };
    input.click();
}

function openKnowledgeImportDialog(files) {
    if (!knowledgeEditor.guard(() => openKnowledgeImportDialog(files))) return;
    const validationError = validateKnowledgeImportFiles(files);
    if (validationError) {
        _setKnowledgeStatus(validationError, true);
        return;
    }
    const choices = _knowledgeCategoryPaths();
    openKnowledgeDialog({
        title: currentLang === 'zh' ? '导入文档' : 'Import documents',
        subtitle: currentLang === 'zh' ? `已选择 ${files.length} 个文件` : `${files.length} file(s) selected`,
        label: currentLang === 'zh' ? '目标分类' : 'Destination category',
        hint: choices.length ? (currentLang === 'zh' ? '支持 Markdown 和 TXT，TXT 会转成 Markdown 文档' : 'Markdown and TXT are supported. TXT is converted to Markdown.') :
            (currentLang === 'zh' ? '请先创建一个分类' : 'Create a category first'),
        type: 'select',
        choices,
        icon: 'fa-file-arrow-up',
        onSubmit: target => importKnowledgeDocuments(files, target),
    });
}

async function importKnowledgeDocuments(files, targetCategory) {
    const state = _knowledgeState;
    const validationError = validateKnowledgeImportFiles(files);
    if (validationError) {
        _setKnowledgeStatus(validationError, true);
        return null;
    }
    const supported = files.filter(file => /\.(md|txt)$/i.test(file.name || ''));
    if (!supported.length) {
        _setKnowledgeStatus(currentLang === 'zh' ? '请选择 .md 或 .txt 文件' : 'Choose .md or .txt files', true);
        return null;
    }
    const formData = new FormData();
    formData.append('target_category', targetCategory);
    formData.append('conflict_strategy', 'rename');
    supported.forEach(file => formData.append('files', file, file.name));
    _setKnowledgeStatus(currentLang === 'zh' ? '正在导入...' : 'Importing...', false, true);
    try {
        const response = await fetch(_kbUrl('/api/knowledge/import'), { method: 'POST', body: formData });
        const result = await response.json();
        if (state !== _knowledgeState) return result.payload;
        if (result.status !== 'success') {
            _setKnowledgeStatus(result.message || (currentLang === 'zh' ? '导入失败' : 'Import failed'), true);
            _refreshKnowledgeTree();
            return null;
        }
        _setKnowledgeStatus(_knowledgeResultMessage('import_documents', result.payload), false);
        // Auto-open the first successfully imported document.
        const firstImported = (result.payload?.results || []).find(item => item.status === 'imported');
        await _refreshKnowledgeTree();
        if (firstImported && state === _knowledgeState) openKnowledgeFile(firstImported.path, undefined, true);
        return result.payload;
    } catch (error) {
        _setKnowledgeStatus(currentLang === 'zh' ? '导入请求失败' : 'Import request failed', true);
        return null;
    }
}

function validateKnowledgeImportFiles(files) {
    if (!files || !files.length) return currentLang === 'zh' ? '请选择文件' : 'Choose files';
    if (files.length > KNOWLEDGE_IMPORT_MAX_FILES) {
        return currentLang === 'zh' ? `一次最多导入 ${KNOWLEDGE_IMPORT_MAX_FILES} 个文件` : `Import at most ${KNOWLEDGE_IMPORT_MAX_FILES} files at a time`;
    }
    let total = 0;
    for (const file of files) {
        total += file.size || 0;
        if ((file.size || 0) > KNOWLEDGE_IMPORT_MAX_FILE_SIZE) {
            return currentLang === 'zh' ? `${file.name} 超过 10MB` : `${file.name} exceeds 10MB`;
        }
    }
    if (total > KNOWLEDGE_IMPORT_MAX_TOTAL_SIZE) {
        return currentLang === 'zh' ? '单次导入总大小不能超过 200MB' : 'Total import size cannot exceed 200MB';
    }
    return '';
}

let _knowledgeImportDropReady = false;
function initKnowledgeImportDropZone() {
    if (_knowledgeImportDropReady) return;
    const panel = document.getElementById('knowledge-panel-docs');
    if (!panel) return;
    _knowledgeImportDropReady = true;
    ['dragenter', 'dragover'].forEach(name => {
        panel.addEventListener(name, event => {
            if (!event.dataTransfer || !event.dataTransfer.types.includes('Files')) return;
            event.preventDefault();
            panel.classList.add('knowledge-import-drag-over');
        });
    });
    ['dragleave', 'drop'].forEach(name => {
        panel.addEventListener(name, event => {
            if (event.type === 'drop') {
                event.preventDefault();
                const files = Array.from(event.dataTransfer?.files || []);
                if (files.length) openKnowledgeImportDialog(files);
            }
            panel.classList.remove('knowledge-import-drag-over');
        });
    });
}

function renameKnowledgeCategory(path) {
    if (!knowledgeEditor.guard(() => renameKnowledgeCategory(path))) return;
    openKnowledgeDialog({
        title: currentLang === 'zh' ? '重命名分类' : 'Rename category',
        subtitle: path,
        label: currentLang === 'zh' ? '新的分类路径' : 'New category path',
        value: path,
        icon: 'fa-pen',
        validate: value => value === path ? (currentLang === 'zh' ? '请输入不同的分类路径' : 'Enter a different category path') : '',
        onSubmit: newPath => dispatchKnowledgeAction('rename_category', {path, new_path: newPath}),
    });
}

function deleteKnowledgeCategory(path) {
    if (!knowledgeEditor.guard(() => deleteKnowledgeCategory(path))) return;
    showConfirmDialog({
        title: '删除分类',
        message: `确认删除“${path}”及其中全部文档？`,
        okText: t('confirm_yes'),
        cancelText: t('confirm_cancel'),
        onConfirm: () => dispatchKnowledgeAction('delete_category', {path, confirm: true}),
    });
}

function deleteKnowledgeDocument(path) {
    if (!knowledgeEditor.guard(() => deleteKnowledgeDocument(path))) return;
    showConfirmDialog({
        title: '删除文档',
        message: `确认删除“${path}”？`,
        okText: t('confirm_yes'),
        cancelText: t('confirm_cancel'),
        onConfirm: () => dispatchKnowledgeAction('delete_documents', {paths: [path]}),
    });
}

function moveKnowledgeDocument(path) {
    if (!knowledgeEditor.guard(() => moveKnowledgeDocument(path))) return;
    const currentCategory = path.includes('/') ? path.split('/').slice(0, -1).join('/') : '';
    const choices = _knowledgeCategoryPaths().filter(value => value !== currentCategory);
    openKnowledgeDialog({
        title: currentLang === 'zh' ? '移动文档' : 'Move document',
        subtitle: path,
        label: currentLang === 'zh' ? '目标分类' : 'Destination category',
        hint: choices.length ? '' : (currentLang === 'zh' ? '请先创建其他分类' : 'Create another category first'),
        type: 'select',
        choices,
        icon: 'fa-arrow-right-arrow-left',
        onSubmit: target => dispatchKnowledgeAction('move_documents', {paths: [path], target_category: target}),
    });
}

function resolveKnowledgePath(currentFilePath, relativeHref) {
    // currentFilePath: e.g. "concepts/mcp-protocol.md"
    // relativeHref: e.g. "../entities/openai.md"
    const parts = currentFilePath.split('/');
    parts.pop(); // remove filename, keep directory
    const segments = [...parts, ...relativeHref.split('/')];
    const resolved = [];
    for (const seg of segments) {
        if (seg === '..') resolved.pop();
        else if (seg !== '.' && seg !== '') resolved.push(seg);
    }
    return resolved.join('/');
}

function bindKnowledgeLinks(container, currentFilePath) {
    container.querySelectorAll('a').forEach(a => {
        const href = a.getAttribute('href');
        if (!href || /^(?:[a-z][\w+.-]*:|\/\/)/i.test(href)) return;
        let decoded;
        try { decoded = decodeURIComponent(href); } catch { decoded = href; }
        if (!/\.md$/i.test(decoded)) return;

        a.addEventListener('click', (e) => {
            e.preventDefault();
            const resolved = resolveKnowledgePath(currentFilePath, decoded);
            const linkTitle = a.textContent.trim() || resolved.replace(/\.md$/, '').split('/').pop();
            openKnowledgeFile(resolved, linkTitle, true);
        });
        a.style.cursor = 'pointer';
        a.classList.add('text-primary-500', 'hover:underline');
    });
}

// Rewrite <img> srcs that are relative to the knowledge doc's directory into
// /api/file URLs, mirroring bindKnowledgeLinks for links. Runs on rendered
// DOM, so markdown syntax quoted inside code blocks is never touched. The
// lightbox onclick that renderMarkdown attached reads this.src at click time,
// so rewriting src alone keeps zoom working.
function bindKnowledgeImages(container, baseDir) {
    if (!baseDir) return;
    container.querySelectorAll('img').forEach(img => {
        const src = img.getAttribute('src');
        // Remote / data / site-absolute srcs resolve on their own.
        if (!src || /^(?:[a-z][\w+.-]*:|\/)/i.test(src)) return;
        const combined = `${baseDir}/${src.split('?')[0]}`;
        const segments = [];
        for (const seg of combined.split('/')) {
            if (seg === '..') segments.pop();
            else if (seg !== '.' && seg !== '') segments.push(seg);
        }
        // baseDir is an absolute posix path, so restore the leading slash the
        // split() dropped — /api/file rejects non-absolute paths.
        const resolved = (combined.startsWith('/') ? '/' : '') + segments.join('/');
        img.src = '/api/file?path=' + encodeURIComponent(resolved);
    });
}

/** Draw a knowledge page read-only, with its links and images resolved. */
function renderKnowledgeDoc(doc) {
    const bodyEl = document.getElementById('knowledge-viewer-body');
    if (!bodyEl) return;
    bodyEl.innerHTML = renderMarkdown(doc.content || '');
    applyHighlighting(bodyEl);
    bindKnowledgeLinks(bodyEl, doc.path);
    bindKnowledgeImages(bodyEl, doc.dir);
}

function openKnowledgeFile(path, title, reveal = false) {
    // Another document is about to take the viewer over, text area included.
    if (!knowledgeEditor.guard(() => openKnowledgeFile(path, title, reveal))) return;
    const request = {};
    _knowledgeDocumentRequest = request;
    _knowledgeCurrentFile = path;
    _markKnowledgeActive(path);
    if (reveal) _revealKnowledgeFile(path);

    knowledgeReadDoc(path).then(data => {
        if (_knowledgeDocumentRequest !== request) return;
        document.getElementById('knowledge-content-placeholder').classList.add('hidden');
        document.getElementById('knowledge-viewer-path').textContent = path;
        document.getElementById('knowledge-content-viewer').classList.remove('hidden');
        knowledgeEditor.open({
            path: path,
            title: title || _knowledgeState?.tree?.byPath.get(path)?.title || data.title || path.split('/').pop(),
            content: data.content || '',
            // Absolute dir of the page, for resolving its relative image srcs.
            dir: data.dir,
            editable: !!data.editable,
        });

        // Mobile: hide sidebar, show content
        if (window.innerWidth < 768) {
            document.getElementById('knowledge-sidebar').classList.add('hidden');
        }
    }).catch(error => {
        if (_knowledgeDocumentRequest !== request) return;
        _knowledgeCurrentFile = knowledgeEditor.current()?.path || null;
        _markKnowledgeActive(_knowledgeCurrentFile);
        // The viewer is still showing whatever was open before the click, and
        // the tree has already moved its highlight: say why it did not follow.
        _setKnowledgeStatus(currentLang === 'zh' ? '文档加载失败' : 'Failed to load document', true);
    });
}

function knowledgeMobileBack() {
    if (!knowledgeEditor.guard(knowledgeMobileBack)) return;
    _resetKnowledgeDocument();
    _markKnowledgeActive(null);
}

function switchKnowledgeTab(tab) {
    // The graph tab hides the documents panel, text area and all.
    if (tab !== _knowledgeTab && !knowledgeEditor.guard(() => switchKnowledgeTab(tab))) return;
    document.querySelectorAll('.knowledge-tab').forEach(el => el.classList.remove('active'));
    document.getElementById('knowledge-tab-' + tab).classList.add('active');
    _knowledgeTab = tab;
    _applyKnowledgePanels();
    routeNoteTab('knowledge', tab);
}

// The one place the empty state and the two tab panels are shown or hidden.
// With no pages the empty state stands alone and both panels stay hidden
// whichever tab is selected; the tab switcher used to unhide its panel
// regardless, which put the search box and an empty tree under the "no pages
// yet" guide. The graph is fetched the first time its panel is actually shown.
function _applyKnowledgePanels() {
    const emptyEl = document.getElementById('knowledge-empty');
    const docsPanel = document.getElementById('knowledge-panel-docs');
    const graphPanel = document.getElementById('knowledge-panel-graph');
    const showDocs = _knowledgeHasPages && _knowledgeTab === 'docs';
    const showGraph = _knowledgeHasPages && _knowledgeTab === 'graph';

    emptyEl.classList.toggle('hidden', _knowledgeHasPages);
    docsPanel.classList.toggle('hidden', !showDocs);
    graphPanel.classList.toggle('hidden', !showGraph);
    if (showGraph && !_knowledgeGraphLoaded) loadKnowledgeGraph();
}

let _d3LoadPromise = null;

function ensureD3Loaded() {
    if (window.d3) return Promise.resolve(window.d3);
    if (_d3LoadPromise) return _d3LoadPromise;
    _d3LoadPromise = new Promise((resolve, reject) => {
        const script = document.createElement('script');
        script.src = '/assets/vendor/d3/d3.min.js';
        script.async = true;
        script.onload = () => resolve(window.d3);
        script.onerror = () => reject(new Error('Failed to load d3'));
        document.head.appendChild(script);
    });
    return _d3LoadPromise;
}

function loadKnowledgeGraph() {
    _knowledgeGraphLoaded = true;
    const state = _knowledgeState;
    const isCurrent = () => state === _knowledgeState && _knowledgeGraphLoaded;
    const container = document.getElementById('knowledge-graph-container');
    container.innerHTML = '<div class="flex items-center justify-center h-full text-slate-400 text-sm"><i class="fas fa-spinner fa-spin mr-2"></i>Loading graph...</div>';

    Promise.all([
        ensureD3Loaded(),
        fetch(_kbUrl('/api/knowledge/graph')).then(r => r.json()),
    ]).then(([, data]) => {
        if (!isCurrent()) return;
        const nodes = data.nodes || [];
        const links = data.links || [];
        if (nodes.length === 0) {
            container.innerHTML = `<div class="flex flex-col items-center justify-center h-full text-slate-400"><i class="fas fa-diagram-project text-3xl mb-3 opacity-40"></i><p class="text-sm">${t('knowledge_empty_hint')}</p></div>`;
            return;
        }
        return renderKnowledgeGraph(container, nodes, links, isCurrent);
    }).catch(() => {
        if (!isCurrent()) return;
        container.innerHTML = '<div class="flex items-center justify-center h-full text-slate-400 text-sm">Failed to load graph</div>';
    });
}

// Run the force layout to rest in slices of about a frame, so a large graph
// keeps the page responsive while the spinner is still up.
async function _settleKnowledgeGraph(simulation, ticks, isCurrent) {
    simulation.alphaDecay(1 - Math.pow(simulation.alphaMin(), 1 / ticks));
    for (let i = 0; i < ticks;) {
        const start = performance.now();
        while (i < ticks && performance.now() - start < 16) {
            simulation.tick();
            i++;
        }
        await new Promise(resolve => setTimeout(resolve, 0));
        if (!isCurrent()) return false;
    }
    return true;
}

async function renderKnowledgeGraph(container, nodes, links, isCurrent = () => true) {
    const width = container.clientWidth;
    const height = container.clientHeight || 600;

    // Order categories by node count so the dominant cluster gets the most
    // salient palette entry. Ties break by name to keep colors stable.
    const catCount = {};
    nodes.forEach(n => { catCount[n.category] = (catCount[n.category] || 0) + 1; });
    const categories = Object.keys(catCount).sort(
        (a, b) => catCount[b] - catCount[a] || a.localeCompare(b)
    );
    const colorScale = d3.scaleOrdinal(d3.schemeTableau10).domain(categories);

    // Degree for sizing and neighbour sets for hover highlighting, taken while
    // link ends are still ids (forceLink swaps them for node objects).
    const degree = new Map(nodes.map(n => [n.id, 0]));
    const neighbors = new Map(nodes.map(n => [n.id, new Set([n.id])]));
    links.forEach(l => {
        degree.set(l.source, (degree.get(l.source) || 0) + 1);
        degree.set(l.target, (degree.get(l.target) || 0) + 1);
        neighbors.get(l.source)?.add(l.target);
        neighbors.get(l.target)?.add(l.source);
    });

    function getNodeRadius(d) {
        return Math.min(11, 4 + Math.sqrt(degree.get(d.id) || 0) * 1.6);
    }

    // Lay the graph out before anything is drawn. Animating from a cold start
    // swelled the graph past the panel and then shrank it back once it was
    // fitted, which read as the page jumping.
    const simulation = d3.forceSimulation(nodes)
        .force('link', d3.forceLink(links).id(d => d.id).distance(45).strength(0.5))
        .force('charge', d3.forceManyBody().strength(-70).distanceMax(320))
        .force('x', d3.forceX(0).strength(0.07))
        .force('y', d3.forceY(0).strength(0.07))
        .force('collision', d3.forceCollide().radius(d => getNodeRadius(d) + 5))
        .stop();
    const ticks = Math.max(80, Math.min(300, Math.round(300000 / nodes.length)));
    if (!await _settleKnowledgeGraph(simulation, ticks, isCurrent)) return;
    container.innerHTML = '';

    const svg = d3.select(container)
        .append('svg')
        .attr('width', width)
        .attr('height', height);

    const g = svg.append('g');

    // Labels keep a constant on-screen size: the font is set once on their
    // group, divided by the zoom scale. Only labels that fit are shown:
    // better-connected pages claim their spot first, a label blocked on the
    // right of its node tries the left, and one blocked on both sides waits
    // until zooming in makes room. Sparse outer pages stay labelled while the
    // dense core thins out.
    const LABEL_FONT = 11;
    const LABEL_HEIGHT = 14;
    const LABEL_CELL = 40;
    const labelText = d => d.label.length > 15 ? d.label.slice(0, 14) + '…' : d.label;
    const labelOrder = [...nodes].sort((a, b) => degree.get(b.id) - degree.get(a.id));
    const labelWidth = new Map(nodes.map(n => [n.id,
        [...labelText(n)].reduce((w, ch) => w + (ch.charCodeAt(0) > 255 ? LABEL_FONT : LABEL_FONT * 0.6), 0)]));
    let labelGroup = null;
    let label = null;
    let labelScale = 1;
    let labelFrame = 0;
    // Node id -> 'right' | 'left' for every label currently shown.
    let shownLabels = new Map();

    function placeLabels() {
        labelFrame = 0;
        if (!label) return;
        const k = labelScale;
        const grid = new Map();
        const cells = (x, y, w, fn) => {
            for (let cx = Math.floor(x / LABEL_CELL); cx <= Math.floor((x + w) / LABEL_CELL); cx++) {
                for (let cy = Math.floor(y / LABEL_CELL); cy <= Math.floor((y + LABEL_HEIGHT) / LABEL_CELL); cy++) {
                    if (fn(cx + ',' + cy)) return true;
                }
            }
            return false;
        };
        const fits = (x, y, w) => !cells(x, y, w, key => (grid.get(key) || []).some(b =>
            x < b[0] + b[2] && b[0] < x + w && y < b[1] + LABEL_HEIGHT && b[1] < y + LABEL_HEIGHT));
        const shown = new Map();
        for (const n of labelOrder) {
            const gap = (getNodeRadius(n) + 3) * k;
            const y = n.y * k - LABEL_HEIGHT / 2;
            const w = labelWidth.get(n.id);
            let x = n.x * k + gap;
            let side = 'right';
            if (!fits(x, y, w)) {
                x = n.x * k - gap - w;
                side = 'left';
                if (!fits(x, y, w)) continue;
            }
            const box = [x, y, w];
            cells(x, y, w, key => {
                if (!grid.has(key)) grid.set(key, []);
                grid.get(key).push(box);
            });
            shown.set(n.id, side);
        }
        shownLabels = shown;
        showLabels(id => shown.has(id));
    }

    // Touch only the labels whose visibility or side changed; a zoom gesture
    // re-places labels every frame.
    function showLabels(visible) {
        label.each(function (d) {
            const side = visible(d.id) ? (shownLabels.get(d.id) || 'right') : null;
            if (this.__labelSide === side) return;
            this.__labelSide = side;
            if (!side) {
                this.setAttribute('display', 'none');
                return;
            }
            this.removeAttribute('display');
            const gap = getNodeRadius(d) + 3;
            this.setAttribute('dx', side === 'left' ? -gap : gap);
            this.setAttribute('text-anchor', side === 'left' ? 'end' : 'start');
        });
    }
    const scheduleLabels = () => {
        if (!labelFrame) labelFrame = requestAnimationFrame(placeLabels);
    };

    const zoom = d3.zoom()
        .scaleExtent([0.1, 5])
        .on('zoom', (event) => {
            g.attr('transform', event.transform);
            if (!labelGroup) return;
            labelScale = event.transform.k;
            labelGroup.attr('font-size', LABEL_FONT / labelScale);
            scheduleLabels();
        });
    svg.call(zoom);

    const link = g.append('g')
        .selectAll('line')
        .data(links)
        .join('line')
        .attr('stroke', '#94a3b8')
        .attr('stroke-opacity', 0.3)
        .attr('stroke-width', 1);

    const node = g.append('g')
        .selectAll('circle')
        .data(nodes)
        .join('circle')
        .attr('r', d => getNodeRadius(d))
        .attr('fill', d => colorScale(d.category))
        .attr('stroke', '#fff')
        .attr('stroke-width', 1.5)
        .style('cursor', 'pointer')
        // A gentle reheat, so dragging one node nudges its neighbours instead
        // of setting the whole settled graph in motion again.
        .call(d3.drag()
            .on('start', (event, d) => { if (!event.active) simulation.alphaTarget(0.08).restart(); d.fx = d.x; d.fy = d.y; })
            .on('drag', (event, d) => { d.fx = event.x; d.fy = event.y; })
            .on('end', (event, d) => { if (!event.active) simulation.alphaTarget(0); d.fx = null; d.fy = null; })
        );

    labelGroup = g.append('g')
        .attr('fill', '#64748b')
        .style('pointer-events', 'none');
    label = labelGroup
        .selectAll('text')
        .data(nodes)
        .join('text')
        .text(labelText)
        .attr('dx', d => getNodeRadius(d) + 3)
        .attr('dy', '0.35em');

    // Tooltip
    const tooltip = document.createElement('div');
    tooltip.className = 'knowledge-graph-tooltip';
    container.style.position = 'relative';
    container.appendChild(tooltip);

    node.on('mouseover', (event, d) => {
        tooltip.textContent = d.label + ' (' + d.category + ')';
        tooltip.style.opacity = '1';
        tooltip.style.left = (event.offsetX + 12) + 'px';
        tooltip.style.top = (event.offsetY - 8) + 'px';
        // Highlight connections
        const near = neighbors.get(d.id);
        link.attr('stroke-opacity', l => (l.source.id === d.id || l.target.id === d.id) ? 0.8 : 0.1);
        node.attr('opacity', n => near.has(n.id) ? 1 : 0.2);
        label.attr('opacity', n => near.has(n.id) ? 1 : 0.1);
        showLabels(id => near.has(id) || shownLabels.has(id));
    }).on('mousemove', (event) => {
        tooltip.style.left = (event.offsetX + 12) + 'px';
        tooltip.style.top = (event.offsetY - 8) + 'px';
    }).on('mouseout', () => {
        tooltip.style.opacity = '0';
        link.attr('stroke-opacity', 0.3);
        node.attr('opacity', 1);
        label.attr('opacity', 1);
        showLabels(id => shownLabels.has(id));
    }).on('click', (event, d) => {
        // Switch to docs tab and open the file
        switchKnowledgeTab('docs');
        openKnowledgeFile(d.id, d.label, true);
    });

    const draw = () => {
        link.attr('x1', d => d.source.x).attr('y1', d => d.source.y)
            .attr('x2', d => d.target.x).attr('y2', d => d.target.y);
        node.attr('cx', d => d.x).attr('cy', d => d.y);
        label.attr('x', d => d.x).attr('y', d => d.y);
    };
    draw();
    simulation.on('tick', () => { draw(); scheduleLabels(); });

    // Fit the settled layout once, without animation. The scale is clamped so
    // nodes and labels stay readable: a large graph may run past the panel
    // edges and is explored by dragging and zooming instead.
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    nodes.forEach(n => {
        if (n.x < x0) x0 = n.x;
        if (n.y < y0) y0 = n.y;
        if (n.x > x1) x1 = n.x;
        if (n.y > y1) y1 = n.y;
    });
    const pad = 40;
    const fit = Math.min(width / (x1 - x0 + pad * 2), height / (y1 - y0 + pad * 2));
    const scale = Math.max(0.75, Math.min(1.3, fit));
    svg.call(zoom.transform, d3.zoomIdentity
        .translate(width / 2 - (x0 + x1) / 2 * scale, height / 2 - (y0 + y1) / 2 * scale)
        .scale(scale));

    // Legend
    const legendDiv = document.createElement('div');
    legendDiv.className = 'knowledge-graph-legend';
    categories.forEach(cat => {
        const item = document.createElement('span');
        item.className = 'knowledge-graph-legend-item';
        item.innerHTML = `<span class="knowledge-graph-legend-dot" style="background:${colorScale(cat)}"></span>${escapeHtml(cat)}`;
        legendDiv.appendChild(item);
    });
    container.appendChild(legendDiv);
}

