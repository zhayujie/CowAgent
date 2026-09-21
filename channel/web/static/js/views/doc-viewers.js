/* Memory file and skill definition viewers/editors.
   Split out of console.js. These are classic scripts sharing one global
   scope; see channel/web/README.md before changing the load order. */

// =====================================================================
// Document viewers (memory files, skill definitions)
// =====================================================================

/**
 * Read one file's text for an editor. Throws on an API error so the editor can
 * report it.
 *
 * No session is passed on purpose. Memory files are anchored to the agent's
 * state root, and a session with a project open would resolve the same relative
 * path against that project instead.
 */
async function docReadFile(relPath) {
    const res = await fetch(`/api/workspace/read?path=${encodeURIComponent(relPath)}`);
    const data = await res.json();
    if (data.status !== 'success') throw new Error(data.message || 'read failed');
    return data;
}

/** Save one file's text. Returns the raw response, a conflict included. */
async function docWriteFile(relPath, content, expectedMtime) {
    const res = await fetch('/api/workspace/write', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: relPath, content: content, expected_mtime: expectedMtime }),
    });
    return res.json();
}

/** Render Markdown into a viewer body. */
function docRenderBody(id, content) {
    const el = document.getElementById(id);
    if (!el) return;
    el.innerHTML = renderMarkdown(content || '');
    applyHighlighting(el);
}

/** Put a document's name in a viewer title, with a dot while it is unsaved. */
function docRenderTitle(id, name, state) {
    const el = document.getElementById(id);
    if (!el) return;
    el.textContent = name || '';
    if (state && state.dirty) {
        el.insertAdjacentHTML('beforeend', ' <span class="doc-dirty-dot">•</span>');
    }
}

/**
 * Ask about any unsaved document edit before something tears its page down.
 *
 * @param {function} next - retried once the user agrees to lose the edits.
 * @returns {boolean} true when nothing is at stake and the caller may proceed.
 */
function docGuardUnsaved(next) {
    return memoryEditor.guard(next) && skillEditor.guard(next) && knowledgeEditor.guard(next);
}

const memoryEditor = createDocEditor({
    body: () => document.getElementById('memory-viewer-content'),
    buttons: () => ({
        edit: document.getElementById('memory-btn-edit'),
        save: document.getElementById('memory-btn-save'),
        cancel: document.getElementById('memory-btn-cancel'),
    }),
    read: (doc) => docReadFile(doc.relPath),
    write: (doc, content, mtime) => docWriteFile(doc.relPath, content, mtime),
    render: (doc) => docRenderBody('memory-viewer-content', doc.content),
    onState: (state) => docRenderTitle('memory-viewer-title', memoryEditor.current()?.filename, state),
});

function openMemoryFile(filename, category) {
    category = category || 'memory';
    const agent = viewingMemoryAgentId();
    fetch(`/api/memory/content?filename=${encodeURIComponent(filename)}&category=${category}&agent_id=${encodeURIComponent(agent || '')}`).then(r => r.json()).then(data => {
        if (data.status !== 'success') return;
        document.getElementById('memory-panel-list').classList.add('hidden');
        document.getElementById('memory-panel-viewer').classList.remove('hidden');
        memoryEditor.open({
            filename: filename,
            // The memory API reports where the file sits under the workspace
            // root; the editor addresses it there rather than rebuilding the
            // path from filename plus category.
            relPath: data.rel_path || filename,
            content: data.content || '',
        });
    }).catch(() => {});
}

function closeMemoryViewer() {
    if (!memoryEditor.guard(closeMemoryViewer)) return;
    memoryEditor.forget();
    document.getElementById('memory-panel-viewer').classList.add('hidden');
    document.getElementById('memory-panel-list').classList.remove('hidden');
    // A save changed the size and timestamp the list shows.
    loadMemoryView(memoryPage);
}

// Reloading or closing the tab drops an unsaved edit. All the browser allows
// here is its own generic prompt, which still beats losing the text in silence.
window.addEventListener('beforeunload', (e) => {
    if (!memoryEditor.isDirty() && !skillEditor.isDirty() && !knowledgeEditor.isDirty()) return;
    e.preventDefault();
    e.returnValue = '';
});

