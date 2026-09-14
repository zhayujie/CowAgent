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
    bindSkillsConfigUi();
    loadToolsSection();
    loadMcpSection();
    loadSkillsSection();
}

let mcpServersCache = [];
let mcpEditorOriginalName = null;
let skillsConfigUiBound = false;

function bindSkillsConfigUi() {
    if (skillsConfigUiBound) return;
    skillsConfigUiBound = true;
    document.getElementById('mcp-add-btn')?.addEventListener('click', () => openMcpEditor());
    document.getElementById('mcp-field-type')?.addEventListener('change', syncMcpEditorTransport);
    document.getElementById('mcp-editor-cancel')?.addEventListener('click', closeMcpEditor);
    document.getElementById('mcp-editor-overlay')?.addEventListener('click', (e) => {
        if (e.target.id === 'mcp-editor-overlay') closeMcpEditor();
    });
    document.getElementById('mcp-editor-test')?.addEventListener('click', testMcpEditor);
    document.getElementById('mcp-editor-save')?.addEventListener('click', saveMcpEditor);
    document.getElementById('skill-install-btn')?.addEventListener('click', installSkillFromInput);
    document.getElementById('skill-install-input')?.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') { e.preventDefault(); installSkillFromInput(); }
    });
}

function kvToObject(text) {
    const out = {};
    String(text || '').split(/\r?\n/).forEach((line) => {
        const trimmed = line.trim();
        if (!trimmed) return;
        const idx = trimmed.indexOf('=');
        if (idx <= 0) return;
        out[trimmed.slice(0, idx).trim()] = trimmed.slice(idx + 1);
    });
    return out;
}

function objectToKv(obj) {
    if (!obj || typeof obj !== 'object') return '';
    return Object.entries(obj).map(([k, v]) => `${k}=${v}`).join('\n');
}

function mcpStatusLabel(status) {
    const key = {
        ready: 'mcp_status_ready',
        pending: 'mcp_status_pending',
        failed: 'mcp_status_failed',
        needs_auth: 'mcp_status_needs_auth',
        disabled: 'mcp_status_disabled',
        idle: 'mcp_status_idle',
    }[status] || 'mcp_status_idle';
    return t(key);
}

function mcpStatusClass(status) {
    if (status === 'ready') return 'bg-emerald-50 text-emerald-600 dark:bg-emerald-900/20 dark:text-emerald-400';
    if (status === 'failed') return 'bg-red-50 text-red-600 dark:bg-red-900/20 dark:text-red-400';
    if (status === 'needs_auth') return 'bg-amber-50 text-amber-600 dark:bg-amber-900/20 dark:text-amber-400';
    if (status === 'disabled') return 'bg-slate-100 text-slate-500 dark:bg-white/10 dark:text-slate-400';
    return 'bg-blue-50 text-blue-600 dark:bg-blue-900/20 dark:text-blue-400';
}

function loadMcpSection() {
    const emptyEl = document.getElementById('mcp-empty');
    const listEl = document.getElementById('mcp-list');
    const badge = document.getElementById('mcp-count-badge');
    if (!listEl) return;
    fetch('/api/mcp/servers').then(r => r.json()).then(data => {
        if (data.status !== 'success') return;
        mcpServersCache = data.servers || [];
        if (badge) {
            badge.textContent = mcpServersCache.length;
            badge.classList.toggle('hidden', mcpServersCache.length === 0);
        }
        if (!mcpServersCache.length) {
            emptyEl?.classList.remove('hidden');
            listEl.classList.add('hidden');
            listEl.innerHTML = '';
            return;
        }
        emptyEl?.classList.add('hidden');
        listEl.innerHTML = '';
        mcpServersCache.forEach(server => listEl.appendChild(renderMcpCard(server)));
        listEl.classList.remove('hidden');
    }).catch(() => {
        emptyEl?.classList.remove('hidden');
        if (emptyEl) emptyEl.innerHTML = `<span class="text-sm text-slate-400 dark:text-slate-500">${t('mcp_save_error')}</span>`;
    });
}

function renderMcpCard(server) {
    const card = document.createElement('div');
    card.className = 'bg-white dark:bg-[#1A1A1A] rounded-xl border border-slate-200 dark:border-white/10 p-4 flex items-start gap-3';
    const summary = server.type === 'stdio'
        ? [server.command, ...(server.args || [])].filter(Boolean).join(' ')
        : (server.url || server.type);
    card.innerHTML = `
        <div class="w-9 h-9 rounded-lg bg-primary-50 dark:bg-primary-900/20 flex items-center justify-center flex-shrink-0">
            <i class="fas fa-plug text-primary-500 text-sm"></i>
        </div>
        <div class="flex-1 min-w-0">
            <div class="flex items-center gap-2 mb-1">
                <span class="font-medium text-sm text-slate-700 dark:text-slate-200 truncate flex-1 font-mono">${escapeHtml(server.name)}</span>
                <span class="px-1.5 py-0.5 rounded-full text-[10px] ${mcpStatusClass(server.status)}">${escapeHtml(mcpStatusLabel(server.status))}</span>
                <button type="button" data-mcp-edit class="p-1 rounded text-slate-300 hover:text-slate-500"><i class="fas fa-pen text-[10px]"></i></button>
                <button type="button" data-mcp-delete class="p-1 rounded text-slate-300 hover:text-red-500"><i class="fas fa-trash text-[10px]"></i></button>
            </div>
            <p class="text-xs text-slate-400 dark:text-slate-500 truncate">${escapeHtml(summary || server.type)}</p>
        </div>`;
    card.querySelector('[data-mcp-edit]').onclick = () => openMcpEditor(server);
    card.querySelector('[data-mcp-delete]').onclick = () => deleteMcpServer(server.name);
    return card;
}

function syncMcpEditorTransport() {
    const type = document.getElementById('mcp-field-type')?.value;
    const stdio = type === 'stdio';
    document.getElementById('mcp-stdio-fields')?.classList.toggle('hidden', !stdio);
    document.getElementById('mcp-url-fields')?.classList.toggle('hidden', stdio);
}

function fillMcpEditor(server) {
    const s = server || {};
    document.getElementById('mcp-field-name').value = s.name || '';
    document.getElementById('mcp-field-name').disabled = !!s.name;
    document.getElementById('mcp-field-type').value = s.type || (s.url ? 'sse' : 'stdio');
    document.getElementById('mcp-field-command').value = s.command || '';
    document.getElementById('mcp-field-args').value = (s.args || []).join('\n');
    document.getElementById('mcp-field-env').value = objectToKv(s.env);
    document.getElementById('mcp-field-url').value = s.url || '';
    document.getElementById('mcp-field-headers').value = objectToKv(s.headers);
    document.getElementById('mcp-field-scope').value = s.scope || '';
    document.getElementById('mcp-field-prefix').value = s.tool_name_prefix || '';
    document.getElementById('mcp-field-timeout').value = s.timeout || '';
    document.getElementById('mcp-field-disabled').checked = !!s.disabled;
    const result = document.getElementById('mcp-test-result');
    result.classList.add('hidden');
    result.textContent = '';
    document.getElementById('mcp-editor-title').textContent = s.name ? t('mcp_edit') : t('mcp_add');
    syncMcpEditorTransport();
}

function readMcpEditor() {
    const type = document.getElementById('mcp-field-type').value;
    const cfg = {
        name: document.getElementById('mcp-field-name').value.trim(),
        type,
        tool_name_prefix: document.getElementById('mcp-field-prefix').value,
        disabled: document.getElementById('mcp-field-disabled').checked,
    };
    const timeout = document.getElementById('mcp-field-timeout').value.trim();
    if (timeout) cfg.timeout = Number(timeout);
    if (type === 'stdio') {
        cfg.command = document.getElementById('mcp-field-command').value.trim();
        cfg.args = document.getElementById('mcp-field-args').value.split(/\r?\n/).map(s => s.trim()).filter(Boolean);
        cfg.env = kvToObject(document.getElementById('mcp-field-env').value);
    } else {
        cfg.url = document.getElementById('mcp-field-url').value.trim();
        cfg.headers = kvToObject(document.getElementById('mcp-field-headers').value);
        cfg.scope = document.getElementById('mcp-field-scope').value.trim();
    }
    return cfg;
}

function openMcpEditor(server) {
    mcpEditorOriginalName = server ? server.name : null;
    fillMcpEditor(server);
    document.getElementById('mcp-editor-overlay').classList.remove('hidden');
}

function closeMcpEditor() {
    document.getElementById('mcp-editor-overlay').classList.add('hidden');
    mcpEditorOriginalName = null;
}

async function persistMcpServers(servers) {
    const res = await fetch('/api/mcp/servers', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ servers }),
    });
    const data = await res.json();
    if (data.status !== 'success') throw new Error(data.message || t('mcp_save_error'));
    mcpServersCache = data.servers || servers;
    loadMcpSection();
    return data;
}

async function saveMcpEditor() {
    try {
        const cfg = readMcpEditor();
        const next = mcpServersCache.filter(s => s.name !== mcpEditorOriginalName && s.name !== cfg.name);
        next.push(cfg);
        await persistMcpServers(next);
        closeMcpEditor();
    } catch (err) {
        const result = document.getElementById('mcp-test-result');
        result.classList.remove('hidden');
        result.textContent = err.message || t('mcp_save_error');
    }
}

async function testMcpEditor() {
    const result = document.getElementById('mcp-test-result');
    result.classList.remove('hidden');
    result.textContent = t('mcp_test') + '...';
    try {
        const res = await fetch('/api/mcp/servers/test', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ server: readMcpEditor() }),
        });
        const data = await res.json();
        if (data.ok) {
            const names = (data.tools || []).map(x => x.name).filter(Boolean);
            result.textContent = t('mcp_test_ok') + (names.length ? (': ' + names.join(', ')) : '');
        } else {
            result.textContent = t('mcp_test_fail') + ': ' + (data.error || data.message || '');
        }
    } catch (err) {
        result.textContent = t('mcp_test_fail') + ': ' + (err.message || '');
    }
}

function deleteMcpServer(name) {
    showConfirmDialog({
        title: t('mcp_delete'),
        message: t('mcp_delete_confirm'),
        okText: t('mcp_delete'),
        onConfirm: async () => {
            try {
                await persistMcpServers(mcpServersCache.filter(s => s.name !== name));
            } catch (err) {
                alert(err.message || t('mcp_save_error'));
            }
        },
    });
}

async function installSkillFromInput() {
    const input = document.getElementById('skill-install-input');
    const spec = (input && input.value || '').trim();
    if (!spec) return;
    const btn = document.getElementById('skill-install-btn');
    if (btn) btn.disabled = true;
    try {
        const res = await fetch('/api/skills', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ action: 'install', spec }),
        });
        const data = await res.json();
        if (data.status !== 'success') throw new Error(data.message || t('skill_install_error'));
        if (input) input.value = '';
        loadSkillsSection();
    } catch (err) {
        alert(err.message || t('skill_install_error'));
    } finally {
        if (btn) btn.disabled = false;
    }
}

function deleteSkill(name) {
    showConfirmDialog({
        title: t('skill_delete'),
        message: t('skill_delete_confirm'),
        okText: t('skill_delete'),
        onConfirm: async () => {
            try {
                const res = await fetch('/api/skills', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ action: 'delete', name }),
                });
                const data = await res.json();
                if (data.status !== 'success') throw new Error(data.message || t('skill_delete_error'));
                loadSkillsSection();
            } catch (err) {
                alert(err.message || t('skill_delete_error'));
            }
        },
    });
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
            card.dataset.deletable = sk.deletable ? '1' : '0';
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
                ${sk.deletable ? `
                <button
                    data-skill-delete
                    class="flex-shrink-0 p-1 -mx-1 -mt-1.5 -mb-1 rounded text-slate-300 dark:text-slate-600 hover:text-red-500 dark:hover:text-red-400 transition-colors"
                    title="${t('skill_delete')}"
                >
                    <i class="fas fa-trash text-[10px]"></i>
                </button>` : ''}
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
    const deleteBtn = card.querySelector('[data-skill-delete]');
    if (deleteBtn) {
        deleteBtn.onclick = (e) => {
            e.stopPropagation();
            deleteSkill(sk.name);
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
                    deletable: card.dataset.deletable === '1',
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

/**
 * Skills are addressed by name, not by path: which file a name resolves to is
 * the loader's business, and a builtin skill lives outside the workspace that
 * the file APIs are confined to.
 */
async function skillReadContent(name) {
    const res = await fetch(`/api/skills/content?name=${encodeURIComponent(name)}`);
    const data = await res.json();
    if (data.status !== 'success') throw new Error(data.message || 'read failed');
    return data;
}

/** Save a skill's definition. Returns the raw response, a conflict included. */
async function skillWriteContent(name, content, expectedMtime) {
    const res = await fetch('/api/skills/content', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: name, content: content, expected_mtime: expectedMtime }),
    });
    return res.json();
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

/**
 * Render a skill's content into the viewer: the frontmatter as a titled header,
 * the remainder as markdown.
 */
function skillRenderBody(content) {
    const el = document.getElementById('skill-viewer-content');
    if (!el) return;
    const { fields, body } = parseSkillFrontmatter(content);

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
    read: (doc) => skillReadContent(doc.name),
    write: (doc, content, mtime) => skillWriteContent(doc.name, content, mtime),
    render: (doc) => skillRenderBody(doc.content),
    canEdit: (doc) => !doc.readonlyKey,
    refusal: skillReadonlyReason,
    onState: (state) => docRenderTitle('skill-viewer-title', skillEditor.current()?.name, state),
});

function openSkillFile(name, opts) {
    const startEditing = !!(opts && opts.edit);
    skillReadContent(name).then(data => {
        const badge = document.getElementById('skill-viewer-readonly');
        const readonlyKey = skillReadonlyReason(data);
        if (badge) {
            badge.classList.toggle('hidden', !readonlyKey);
            if (readonlyKey) {
                // Keep data-i18n in step so a language switch re-translates it.
                badge.dataset.i18n = readonlyKey;
                badge.textContent = t(readonlyKey);
                badge.title = t(readonlyKey);
            }
        }
        document.getElementById('skills-panel-list').classList.add('hidden');
        document.getElementById('skills-panel-viewer').classList.remove('hidden');
        skillEditor.open({
            name: data.name || name,
            content: data.content || '',
            readonlyKey: readonlyKey,
        });
        // The pencil on a card jumps straight into editing, skipping the
        // read-only view - but only where the skill is actually editable.
        if (startEditing && !readonlyKey) skillEditor.start();
    }).catch(e => _wsToast(`${t('skill_load_failed')}: ${e.message}`));
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
    document.getElementById('skills-panel-viewer')?.classList.add('hidden');
    document.getElementById('skills-panel-list')?.classList.remove('hidden');
}

