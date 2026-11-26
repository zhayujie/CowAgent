/* Knowledge base tree, import and relation graph.
   Split out of console.js. These are classic scripts sharing one global
   scope; see channel/web/README.md before changing the load order. */

// =====================================================================
// Knowledge View
// =====================================================================
let _knowledgeView;
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
    const view = _knowledgeView;
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
    if (data.status === 'success' && view === _knowledgeView) _refreshKnowledgeTree([doc.path]);
    return {
        status: data.status,
        code: data.payload?.conflict ? 'conflict' : data.code,
        message: data.message,
        mtime: data.payload?.mtime,
    };
}

async function _knowledgeList(view, params = {}, signal) {
    const query = new URLSearchParams({view, ...params});
    const response = await fetch(_kbUrl('/api/knowledge/list?' + query), {signal});
    const data = await response.json();
    if (data.status !== 'success') throw new Error(data.message || 'list failed');
    return data;
}

function _knowledgeTreeMessage(key) {
    const labels = {
        loading: ['加载中…', 'Loading…'],
        error: ['加载失败，点击重试', 'Loading failed. Retry'],
        empty: ['此目录没有文档', 'This folder is empty'],
        no_results: ['没有匹配的文档', 'No matching documents'],
        previous: ['上一页', 'Previous'],
        next: ['下一页', 'Next'],
    };
    return labels[key][currentLang === 'zh' ? 0 : 1];
}

function _knowledgeTreeButton(label, handler, depth = 0) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'knowledge-tree-file';
    button.style.paddingLeft = (8 + depth * 12) + 'px';
    button.textContent = label;
    button.onclick = handler;
    return button;
}

function _knowledgeTreeText(key) {
    const message = document.createElement('p');
    message.className = 'px-2 py-1 text-xs text-slate-500';
    message.textContent = _knowledgeTreeMessage(key);
    return message;
}

async function _loadKnowledgeFolder(view, folder, offset = 0, focus = '') {
    const request = {offset, focus};
    view.requests.set(folder, request);
    view.errors.delete(folder);
    renderKnowledgeTree();
    try {
        const page = await _knowledgeList('folder', {folder, offset, focus});
        if (view !== _knowledgeView || view.requests.get(folder) !== request) return;
        view.folders.set(folder, page);
        if (!folder) _applyKnowledgeRoot(page);
        return page;
    } catch (error) {
        if (view === _knowledgeView && view.requests.get(folder) === request) {
            view.errors.set(folder, request);
            if (!folder && !view.folders.has('')) {
                const empty = document.getElementById('knowledge-empty');
                const message = empty.querySelector('p');
                message.replaceChildren(_knowledgeTreeButton(_knowledgeTreeMessage('error'), () => loadKnowledgeView(view.target)));
            }
        }
    } finally {
        if (view.requests.get(folder) === request) view.requests.delete(folder);
        if (view === _knowledgeView) renderKnowledgeTree();
    }
}

function _applyKnowledgeRoot(page) {
    const empty = document.getElementById('knowledge-empty');
    _knowledgeHasPages = page.total > 0;
    if (!_knowledgeHasPages) empty.querySelector('p').textContent = t('knowledge_empty_hint');
    document.getElementById('knowledge-empty-guide').classList.toggle('hidden', _knowledgeHasPages);
    document.getElementById('knowledge-stats').textContent = currentLang === 'zh'
        ? `根目录 ${page.total} 项` : `${page.total} root items`;
    _applyKnowledgePanels();
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
    _knowledgeView?.searchRequest?.abort();
    clearTimeout(_knowledgeView?.searchTimer);
    const view = {
        folders: new Map(), expanded: new Set(), requests: new Map(), errors: new Map(),
        target: targetPath, search: null, searchRequest: null, searchTimer: null,
    };
    _knowledgeView = view;
    if (knowledgeAgentId && agentCatalog.length && !agentCatalog.some(a => a.id === knowledgeAgentId)) {
        knowledgeAgentId = '';
        localStorage.removeItem('cow_knowledge_agent');
    }
    _resetKnowledgeDocument();
    _knowledgeGraphLoaded = false;
    _knowledgeHasPages = false;
    document.getElementById('knowledge-search').value = '';
    document.getElementById('knowledge-stats').textContent = '';
    const empty = document.getElementById('knowledge-empty');
    empty.querySelector('p').textContent = t('knowledge_loading');
    document.getElementById('knowledge-empty-guide').classList.add('hidden');
    switchKnowledgeTab('docs');
    renderKnowledgeAgentSelect();
    initKnowledgeImportDropZone();

    const rootRequest = _loadKnowledgeFolder(view, '');
    if (targetPath) openKnowledgeFile(targetPath, undefined, true, rootRequest);
}

async function _revealKnowledgeFile(view, path) {
    const parts = path.split('/');
    let folder = '';
    for (const name of parts) {
        if (view !== _knowledgeView || _knowledgeCurrentFile !== path) return;
        let page = view.folders.get(folder);
        if (!page?.items.some(item => item.name === name)) {
            page = await _loadKnowledgeFolder(view, folder, page?.offset, name);
        }
        const item = page?.items.find(entry => entry.name === name);
        if (!item) return;
        if (item.kind === 'folder') {
            folder = item.path;
            view.expanded.add(folder);
        }
    }
    if (view === _knowledgeView) renderKnowledgeTree();
}

function _knowledgeFileRow(item, depth, showPath = false) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'knowledge-tree-file' + (_knowledgeCurrentFile === item.path ? ' active' : '');
    button.dataset.path = item.path;
    button.title = item.path;
    button.style.paddingLeft = (8 + 12 * depth) + 'px';
    const subtitle = showPath ? `<span class="block truncate text-[10px]">${escapeHtml(item.path)}</span>` : '';
    button.innerHTML = `<i class="fas fa-file-lines text-[10px] text-slate-400"></i><span class="truncate">${escapeHtml(item.title)}${subtitle}</span>${_knowledgeFileActions(item.path)}`;
    button.onclick = () => openKnowledgeFile(item.path, item.title);
    return button;
}

function _renderKnowledgeFolder(view, container, path, depth) {
    const page = view.folders.get(path);
    const failed = view.errors.get(path);
    if (failed) {
        container.appendChild(_knowledgeTreeButton(_knowledgeTreeMessage('error'),
            () => _loadKnowledgeFolder(view, path, failed.offset, failed.focus), depth));
    }
    if (!page) {
        if (view.requests.has(path)) container.appendChild(_knowledgeTreeText('loading'));
        return;
    }
    if (!page.items.length) container.appendChild(_knowledgeTreeText('empty'));
    for (const item of page.items) {
        if (item.kind === 'file') {
            container.appendChild(_knowledgeFileRow(item, depth));
            continue;
        }
        const isOpen = view.expanded.has(item.path);
        const group = document.createElement('div');
        group.className = 'knowledge-tree-group' + (isOpen ? ' open' : '');
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'knowledge-tree-group-btn';
        button.style.paddingLeft = (8 + 12 * depth) + 'px';
        button.setAttribute('aria-expanded', String(isOpen));
        button.innerHTML = `<i class="fas fa-chevron-right chevron"></i><i class="fas fa-folder text-amber-400 text-[11px]"></i><span class="truncate">${escapeHtml(item.name)}</span>${_knowledgeCategoryActions(item.path)}`;
        button.onclick = () => {
            if (view.expanded.delete(item.path)) {
                renderKnowledgeTree();
            } else {
                view.expanded.add(item.path);
                if (!view.folders.has(item.path) && !view.requests.has(item.path)) {
                    _loadKnowledgeFolder(view, item.path);
                } else {
                    renderKnowledgeTree();
                }
            }
            document.querySelector(`[data-knowledge-folder="${CSS.escape(item.path)}"]`)?.focus({preventScroll: true});
        };
        button.dataset.knowledgeFolder = item.path;
        group.appendChild(button);
        if (isOpen) _renderKnowledgeFolder(view, group, item.path, depth + 1);
        container.appendChild(group);
    }
    for (const direction of ['previous', 'next']) {
        if (page[direction] != null) {
            const button = _knowledgeTreeButton(_knowledgeTreeMessage(direction),
                () => _loadKnowledgeFolder(view, path, page[direction]), depth);
            button.disabled = view.requests.has(path);
            container.appendChild(button);
        }
    }
}

function renderKnowledgeTree() {
    const view = _knowledgeView;
    const container = document.getElementById('knowledge-tree');
    container.replaceChildren();
    if (!view.search) {
        _renderKnowledgeFolder(view, container, '', 0);
        return;
    }
    const {page, loading, error, cursors} = view.search;
    if (loading) {
        container.appendChild(_knowledgeTreeText('loading'));
    } else if (error) {
        container.appendChild(_knowledgeTreeButton(_knowledgeTreeMessage('error'), () => _loadKnowledgeSearch(view)));
    } else if (page) {
        if (!page.items.length) container.appendChild(_knowledgeTreeText('no_results'));
        for (const item of page.items) container.appendChild(_knowledgeFileRow(item, 0, true));
        if (cursors.length > 1) {
            container.appendChild(_knowledgeTreeButton(_knowledgeTreeMessage('previous'),
                () => { cursors.pop(); _loadKnowledgeSearch(view); }));
        }
        if (page.next) {
            container.appendChild(_knowledgeTreeButton(_knowledgeTreeMessage('next'),
                () => { cursors.push(page.next); _loadKnowledgeSearch(view); }));
        }
    }
}

async function _loadKnowledgeSearch(view) {
    const search = view.search;
    if (view !== _knowledgeView || !search) return;
    view.searchRequest?.abort();
    const controller = new AbortController();
    view.searchRequest = controller;
    search.loading = true;
    search.error = false;
    renderKnowledgeTree();
    try {
        search.page = await _knowledgeList('search', {query: search.query, after: search.cursors.at(-1)}, controller.signal);
    } catch (error) {
        if (!controller.signal.aborted) search.error = true;
    } finally {
        if (view === _knowledgeView && view.searchRequest === controller && !controller.signal.aborted) {
            search.loading = false;
            renderKnowledgeTree();
        }
    }
}

function filterKnowledgeTree(query) {
    const view = _knowledgeView;
    clearTimeout(view.searchTimer);
    view.searchRequest?.abort();
    query = query.trim();
    view.search = query ? {query, cursors: [''], loading: true} : null;
    renderKnowledgeTree();
    if (query) view.searchTimer = setTimeout(() => _loadKnowledgeSearch(view), 300);
}

async function _refreshKnowledgeTree(paths, removedFolder) {
    const view = _knowledgeView;
    if (removedFolder) {
        const removed = path => path === removedFolder || path.startsWith(removedFolder + '/');
        for (const entries of [view.folders, view.expanded, view.requests, view.errors]) {
            for (const path of entries.keys()) {
                if (removed(path)) entries.delete(path);
            }
        }
    }
    const folders = new Set(['']);
    for (const path of paths.filter(Boolean)) {
        const parts = path.split('/');
        parts.pop();
        while (parts.length) {
            folders.add(parts.join('/'));
            parts.pop();
        }
    }
    if (view.search) filterKnowledgeTree(view.search.query);
    await Promise.all([...folders].filter(folder => view.folders.has(folder) || view.requests.has(folder))
        .map(folder => _loadKnowledgeFolder(view, folder, view.folders.get(folder)?.offset)));
    if (view !== _knowledgeView) return;
    const doc = knowledgeEditor.current();
    const parent = doc?.path.split('/').slice(0, -1).join('/');
    const file = view.folders.get(parent)?.items.find(item => item.path === doc?.path);
    if (file) {
        doc.title = file.title;
        docRenderTitle('knowledge-viewer-title', doc.title, {dirty: knowledgeEditor.isDirty()});
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
    const view = _knowledgeView;
    _setKnowledgeStatus(currentLang === 'zh' ? '处理中...' : 'Working...', false, true);
    try {
        const response = await fetch('/api/knowledge/action', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({action, payload, agent_id: viewingKnowledgeAgentId()}),
        });
        const result = await response.json();
        if (view !== _knowledgeView) return result.payload;
        const paths = [payload.path, payload.new_path, ...(payload.paths || [])];
        if (payload.target_category) paths.push(payload.target_category + '/');
        if (result.status !== 'success') {
            _setKnowledgeStatus(result.message || (currentLang === 'zh' ? '操作失败' : 'Operation failed'), true);
            _refreshKnowledgeTree(paths);
            return null;
        }
        _setKnowledgeStatus(_knowledgeResultMessage(action, result.payload), false);
        const current = _knowledgeCurrentFile;
        let next = openPathResolver?.(result.payload);
        let removedFolder;
        if (action === 'rename_category' || action === 'delete_category') {
            removedFolder = result.payload?.old_path || result.payload?.path;
            if (removedFolder && current?.startsWith(removedFolder + '/')) {
                if (action === 'rename_category') next = result.payload.path + current.slice(removedFolder.length);
                _resetKnowledgeDocument();
            }
        } else if (action === 'move_documents' || action === 'delete_documents') {
            const affected = result.payload?.results?.find(item => item.path === current);
            if (affected?.moved || affected?.deleted || affected?.reason === 'not_found') {
                if (affected.moved) next = affected.target;
                _resetKnowledgeDocument();
            }
        }
        const refresh = _refreshKnowledgeTree(paths, removedFolder);
        if (next) openKnowledgeFile(next, undefined, true, refresh);
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

async function _knowledgeCategoryPaths(view) {
    try {
        const data = await _knowledgeList('categories');
        return view === _knowledgeView ? data.categories : null;
    } catch (error) {
        if (view === _knowledgeView) _setKnowledgeStatus(currentLang === 'zh' ? '无法加载分类' : 'Could not load categories', true);
        return null;
    }
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

async function createKnowledgeDocument() {
    if (!knowledgeEditor.guard(createKnowledgeDocument)) return;
    const categories = await _knowledgeCategoryPaths(_knowledgeView);
    if (!categories) return;
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

async function openKnowledgeImportDialog(files) {
    if (!knowledgeEditor.guard(() => openKnowledgeImportDialog(files))) return;
    const validationError = validateKnowledgeImportFiles(files);
    if (validationError) {
        _setKnowledgeStatus(validationError, true);
        return;
    }
    const choices = await _knowledgeCategoryPaths(_knowledgeView);
    if (!choices) return;
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
    const view = _knowledgeView;
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
        if (view !== _knowledgeView) return result.payload;
        if (result.status !== 'success') {
            _setKnowledgeStatus(result.message || (currentLang === 'zh' ? '导入失败' : 'Import failed'), true);
            _refreshKnowledgeTree([targetCategory + '/']);
            return null;
        }
        _setKnowledgeStatus(_knowledgeResultMessage('import_documents', result.payload), false);
        // Auto-open the first successfully imported document.
        const firstImported = (result.payload?.results || []).find(item => item.status === 'imported');
        const refresh = _refreshKnowledgeTree([targetCategory + '/']);
        if (firstImported) openKnowledgeFile(firstImported.path, undefined, true, refresh);
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

async function moveKnowledgeDocument(path) {
    if (!knowledgeEditor.guard(() => moveKnowledgeDocument(path))) return;
    const currentCategory = path.includes('/') ? path.split('/').slice(0, -1).join('/') : '';
    const categories = await _knowledgeCategoryPaths(_knowledgeView);
    if (!categories) return;
    const choices = categories.filter(value => value !== currentCategory);
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

function openKnowledgeFile(path, title, reveal = false, rootRequest) {
    // Another document is about to take the viewer over, text area included.
    if (!knowledgeEditor.guard(() => openKnowledgeFile(path, title, reveal, rootRequest))) return;
    const view = _knowledgeView;
    const request = {};
    _knowledgeDocumentRequest = request;
    _knowledgeCurrentFile = path;
    // Update active state in tree via data-path
    document.querySelectorAll('.knowledge-tree-file').forEach(el => {
        el.classList.toggle('active', el.dataset.path === path);
    });

    knowledgeReadDoc(path).then(data => {
        if (_knowledgeDocumentRequest !== request) return;
        document.getElementById('knowledge-content-placeholder').classList.add('hidden');
        document.getElementById('knowledge-viewer-path').textContent = path;
        document.getElementById('knowledge-content-viewer').classList.remove('hidden');
        knowledgeEditor.open({
            path: path,
            title: title || data.title || path.split('/').pop(),
            content: data.content || '',
            // Absolute dir of the page, for resolving its relative image srcs.
            dir: data.dir,
            editable: !!data.editable,
        });

        if (reveal) Promise.resolve(rootRequest).then(() => _revealKnowledgeFile(view, path));

        // Mobile: hide sidebar, show content
        if (window.innerWidth < 768) {
            document.getElementById('knowledge-sidebar').classList.add('hidden');
        }
    }).catch(error => {
        if (_knowledgeDocumentRequest !== request) return;
        _knowledgeCurrentFile = knowledgeEditor.current()?.path || null;
        renderKnowledgeTree();
        // The viewer is still showing whatever was open before the click, and
        // the tree has already moved its highlight: say why it did not follow.
        _setKnowledgeStatus(currentLang === 'zh' ? '文档加载失败' : 'Failed to load document', true);
    });
}

function knowledgeMobileBack() {
    if (!knowledgeEditor.guard(knowledgeMobileBack)) return;
    _resetKnowledgeDocument();
    renderKnowledgeTree();
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
    const container = document.getElementById('knowledge-graph-container');
    container.innerHTML = '<div class="flex items-center justify-center h-full text-slate-400 text-sm"><i class="fas fa-spinner fa-spin mr-2"></i>Loading graph...</div>';

    Promise.all([
        ensureD3Loaded(),
        fetch(_kbUrl('/api/knowledge/graph')).then(r => r.json()),
    ]).then(([, data]) => {
        const nodes = data.nodes || [];
        const links = data.links || [];
        if (nodes.length === 0) {
            container.innerHTML = `<div class="flex flex-col items-center justify-center h-full text-slate-400"><i class="fas fa-diagram-project text-3xl mb-3 opacity-40"></i><p class="text-sm">${t('knowledge_empty_hint')}</p></div>`;
            return;
        }
        container.innerHTML = '';
        renderKnowledgeGraph(container, nodes, links);
    }).catch(() => {
        container.innerHTML = '<div class="flex items-center justify-center h-full text-slate-400 text-sm">Failed to load graph</div>';
    });
}

function renderKnowledgeGraph(container, nodes, links) {
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

    // Connection count for sizing
    const connCount = {};
    nodes.forEach(n => connCount[n.id] = 0);
    links.forEach(l => {
        connCount[l.source] = (connCount[l.source] || 0) + 1;
        connCount[l.target] = (connCount[l.target] || 0) + 1;
    });

    const svg = d3.select(container)
        .append('svg')
        .attr('width', width)
        .attr('height', height);

    const g = svg.append('g');

    // Zoom with adaptive label visibility
    let currentZoomScale = 1;
    // Set once the graph is fitted to the viewport. Labels hide below it, so
    // zooming out past the default view still declutters.
    let fittedScale = 1;
    const zoom = d3.zoom()
        .scaleExtent([0.2, 5])
        .on('zoom', (event) => {
            g.attr('transform', event.transform);
            currentZoomScale = event.transform.k;
            updateLabelVisibility();
        });
    svg.call(zoom);

    function updateLabelVisibility() {
        if (!label) return;
        // Fitting a graph of any size into the panel lands well below scale 1,
        // so a fixed threshold would hide every label in the default view.
        // Compare against the fitted scale instead, and keep the text a
        // constant size on screen — inside the zoomed <g>, that means dividing
        // by the scale.
        if (currentZoomScale < fittedScale * 0.9) {
            label.attr('opacity', 0);
            return;
        }
        label.attr('opacity', 1)
            .attr('font-size', 10 / currentZoomScale)
            .attr('dx', d => getNodeRadius(d) + 4 / currentZoomScale)
            .attr('dy', 3 / currentZoomScale);
    }

    const simulation = d3.forceSimulation(nodes)
        .force('link', d3.forceLink(links).id(d => d.id).distance(90))
        .force('charge', d3.forceManyBody().strength(-180))
        .force('center', d3.forceCenter(width / 2, height / 2))
        .force('x', d3.forceX(width / 2).strength(0.06))
        .force('y', d3.forceY(height / 2).strength(0.06))
        .force('collision', d3.forceCollide().radius(d => getNodeRadius(d) + 30));

    function getNodeRadius(d) {
        return Math.max(5, Math.min(16, 5 + (connCount[d.id] || 0) * 2));
    }

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
        .call(d3.drag()
            .on('start', (event, d) => { if (!event.active) simulation.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y; })
            .on('drag', (event, d) => { d.fx = event.x; d.fy = event.y; })
            .on('end', (event, d) => { if (!event.active) simulation.alphaTarget(0); d.fx = null; d.fy = null; })
        );

    const label = g.append('g')
        .selectAll('text')
        .data(nodes)
        .join('text')
        .text(d => d.label.length > 15 ? d.label.slice(0, 14) + '…' : d.label)
        .attr('font-size', 9)
        .attr('dx', d => getNodeRadius(d) + 4)
        .attr('dy', 3)
        .attr('fill', '#64748b')
        .style('pointer-events', 'none');

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
        link.attr('stroke-opacity', l => (l.source.id === d.id || l.target.id === d.id) ? 0.8 : 0.1);
        node.attr('opacity', n => n.id === d.id || links.some(l => (l.source.id === d.id && l.target.id === n.id) || (l.target.id === d.id && l.source.id === n.id)) ? 1 : 0.2);
        label.attr('opacity', n => n.id === d.id || links.some(l => (l.source.id === d.id && l.target.id === n.id) || (l.target.id === d.id && l.source.id === n.id)) ? 1 : 0.1);
    }).on('mousemove', (event) => {
        tooltip.style.left = (event.offsetX + 12) + 'px';
        tooltip.style.top = (event.offsetY - 8) + 'px';
    }).on('mouseout', () => {
        tooltip.style.opacity = '0';
        link.attr('stroke-opacity', 0.3);
        node.attr('opacity', 1);
        label.attr('opacity', 1);
    }).on('click', (event, d) => {
        // Switch to docs tab and open the file
        switchKnowledgeTab('docs');
        openKnowledgeFile(d.id, d.label);
    });

    simulation.on('tick', () => {
        link.attr('x1', d => d.source.x).attr('y1', d => d.source.y)
            .attr('x2', d => d.target.x).attr('y2', d => d.target.y);
        node.attr('cx', d => d.x).attr('cy', d => d.y);
        label.attr('x', d => d.x).attr('y', d => d.y);
    });

    // Auto fit-to-view when simulation settles
    simulation.on('end', () => {
        const pad = 16;
        let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
        nodes.forEach(n => {
            if (n.x < x0) x0 = n.x;
            if (n.y < y0) y0 = n.y;
            if (n.x > x1) x1 = n.x;
            if (n.y > y1) y1 = n.y;
        });
        const bw = x1 - x0 + pad * 2;
        const bh = y1 - y0 + pad * 2;
        if (bw > 0 && bh > 0) {
            const scale = Math.min(width / bw, height / bh, 4);
            fittedScale = scale;
            const tx = width / 2 - (x0 + x1) / 2 * scale;
            const ty = height / 2 - (y0 + y1) / 2 * scale;
            svg.transition().duration(500).call(
                zoom.transform, d3.zoomIdentity.translate(tx, ty).scale(scale)
            );
        }
    });

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

