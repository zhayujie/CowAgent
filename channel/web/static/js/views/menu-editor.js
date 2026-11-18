/* Menu editor: the dialog behind the sidebar's edit button. It works on a copy
   of the menu in force and saves the whole of it to POST /api/menu; entries
   this console does not have (a desktop-only page) stay in the copy as they
   are, so saving from here never drops them.

   These are classic scripts sharing one global scope; see
   channel/web/README.md before changing the load order. Uses core/menu.js
   and core/confirm.js. */

// The pages the built-in menu always carries: hidden, never removed, so a new
// version can tell a page the user put away from one it has just added.
const ME_DEFAULT_VIEWS = new Set(MENU_DEFAULT.flatMap(g => g.views));

let meDraft = null;
// The device switcher is not part of the shared menu: whether it shows is
// this browser's choice (core/instances.js).
let meSwitcherHidden = false;
let meDragging = null;
let mePopAnchor = null;
let meArtTimer = null;
let meArtToken = 0;

function _meId(prefix) {
    return prefix + Math.random().toString(36).slice(2, 10);
}

function _meEach(fn) {
    meDraft.groups.forEach(g => g.items.forEach(i => fn(i, g)));
}

function _meFind(id) {
    for (const group of meDraft.groups) {
        const item = group.items.find(i => i.id === id);
        if (item) return { group: group, item: item };
    }
    return null;
}

/** Open the editor; `options.add` puts a new entry in the first group, ready to place. */
function menuEditorOpen(options) {
    meDraft = JSON.parse(JSON.stringify(menuDoc));
    meSwitcherHidden = instanceSwitcherHidden();
    let focusId = (options && options.focus) || '';
    if (options && options.add) {
        const item = Object.assign({ id: _meId('m_'), title: '', icon: '' }, options.add);
        meDraft.groups[0].items.push(item);
        focusId = item.id;
    }
    _meError('');
    _meClosePop();
    _meRender();
    document.getElementById('menu-editor-overlay').classList.remove('hidden');
    document.addEventListener('keydown', _meOnKey, true);
    if (focusId) {
        const row = document.querySelector(`#menu-editor-body .me-item[data-iid="${CSS.escape(focusId)}"]`);
        if (row) {
            row.classList.add('is-new');
            row.scrollIntoView({ block: 'center' });
            const input = row.querySelector('[data-field="title"]');
            if (input) { input.focus(); input.select(); }
        }
    }
}

function menuEditorClose() {
    _meClosePop();
    document.getElementById('menu-editor-overlay').classList.add('hidden');
    document.removeEventListener('keydown', _meOnKey, true);
    meDraft = null;
}

function _meOnKey(e) {
    if (e.key !== 'Escape') return;
    const confirmOverlay = document.getElementById('confirm-dialog-overlay');
    if (confirmOverlay && !confirmOverlay.classList.contains('hidden')) return;
    e.stopPropagation();
    if (mePopAnchor) _meClosePop();
    else menuEditorClose();
}

function _meError(text) {
    document.getElementById('menu-editor-error').textContent = text || '';
}

// ---------------------------------------------------------------------
// Drawing
// ---------------------------------------------------------------------

function _meRender() {
    document.getElementById('menu-editor-body').innerHTML = _meSwitcherHTML() + meDraft.groups.map(_meGroupHTML).join('');
}

function _meSwitcherHTML() {
    const tip = meSwitcherHidden ? 'menu_show' : 'menu_hide';
    return `<div class="me-pinned">
        <div class="me-item${meSwitcherHidden ? ' is-hidden' : ''}">
            <span class="me-handle"></span>
            <span class="me-icon me-icon-static"><i class="fas fa-laptop"></i></span>
            <div class="me-main">
                <span class="me-pinned-title">${escapeHtml(t('devices_switcher'))}</span>
                <span class="me-sub">${escapeHtml(t('devices_switcher_desc'))}</span>
            </div>
            <button class="me-btn me-btn-icon" data-act="switcher" title="${escapeHtml(t(tip))}">
                <i class="fas ${meSwitcherHidden ? 'fa-eye-slash' : 'fa-eye'}"></i></button>
        </div>
    </div>`;
}

function _meGroupHTML(group) {
    const keeps = group.items.some(i => i.type === 'builtin' && ME_DEFAULT_VIEWS.has(i.view));
    const placeholder = MENU_GROUP_LABELS[group.id] ? t(MENU_GROUP_LABELS[group.id]) : t('menu_group_title_ph');
    return `<section class="me-group" data-gid="${escapeHtml(group.id)}">
        <div class="me-group-head">
            <span class="me-handle" data-drag title="${escapeHtml(t('menu_drag'))}"><i class="fas fa-grip-vertical"></i></span>
            <input class="me-group-input" data-field="group-title" maxlength="40"
                   value="${escapeHtml(group.title || '')}" placeholder="${escapeHtml(placeholder)}">
            <button class="me-btn" data-act="add"><i class="fas fa-plus"></i><span>${escapeHtml(t('menu_add'))}</span></button>
            <button class="me-btn me-btn-icon" data-act="group-remove" ${keeps ? 'disabled' : ''}
                    title="${escapeHtml(t(keeps ? 'menu_group_keeps_pages' : 'menu_remove'))}"><i class="fas fa-trash-can"></i></button>
        </div>
        <div class="me-items">${group.items.map(_meItemHTML).join('')}</div>
    </section>`;
}

function _meItemHTML(item) {
    const known = item.type !== 'builtin' || !!MENU_BUILTINS[item.view];
    const removable = item.type !== 'builtin' || !ME_DEFAULT_VIEWS.has(item.view);
    const required = item.type === 'builtin' && MENU_REQUIRED.includes(item.view);
    const placeholder = item.type === 'builtin' ? menuItemLabel(Object.assign({}, item, { title: '' })) : t('menu_item_title_ph');

    let sub;
    if (item.type === 'url') {
        sub = `<input class="me-input me-url" data-field="url" maxlength="2048" spellcheck="false"
                      value="${escapeHtml(item.url || '')}" placeholder="https://">`;
    } else if (item.type === 'artifact') {
        sub = `<span class="me-sub" title="${escapeHtml(item.path)}">${escapeHtml(item.path)}</span>`;
    } else {
        sub = `<span class="me-sub">${escapeHtml(t(known ? 'menu_builtin_page' : 'menu_unsupported'))}</span>`;
    }

    const controls = [];
    if (item.type === 'url') {
        const mode = item.open === 'tab' ? 'tab' : 'embed';
        controls.push(`<div class="me-seg">
            <button data-act="open" data-open="embed" class="${mode === 'embed' ? 'active' : ''}">${escapeHtml(t('menu_open_embed'))}</button>
            <button data-act="open" data-open="tab" class="${mode === 'tab' ? 'active' : ''}">${escapeHtml(t('menu_open_tab'))}</button>
        </div>`);
    }
    if (item.type === 'builtin') {
        const tip = required ? 'menu_required' : (item.hidden ? 'menu_show' : 'menu_hide');
        controls.push(`<button class="me-btn me-btn-icon" data-act="toggle-hidden" ${required ? 'disabled' : ''} title="${escapeHtml(t(tip))}">
            <i class="fas ${item.hidden ? 'fa-eye-slash' : 'fa-eye'}"></i></button>`);
    }
    if (removable) {
        controls.push(`<button class="me-btn me-btn-icon" data-act="remove" title="${escapeHtml(t('menu_remove'))}"><i class="fas fa-xmark"></i></button>`);
    }

    return `<div class="me-item${item.hidden ? ' is-hidden' : ''}${known ? '' : ' is-foreign'}" data-iid="${escapeHtml(item.id)}" data-type="${item.type}">
        <span class="me-handle" data-drag title="${escapeHtml(t('menu_drag'))}"><i class="fas fa-grip-vertical"></i></span>
        <button class="me-icon" data-act="icon" title="${escapeHtml(t('menu_icon'))}"><i class="fas ${escapeHtml(menuItemIcon(item))}"></i></button>
        <div class="me-main">
            <input class="me-input" data-field="title" maxlength="40"
                   value="${escapeHtml(item.title || '')}" placeholder="${escapeHtml(placeholder)}">
            ${sub}
        </div>
        ${controls.join('')}
    </div>`;
}

// ---------------------------------------------------------------------
// Editing
// ---------------------------------------------------------------------

function _meOnInput(e) {
    const field = e.target.dataset.field;
    if (!field) return;
    _meError('');
    if (field === 'group-title') {
        const group = meDraft.groups.find(g => g.id === e.target.closest('.me-group').dataset.gid);
        if (group) group.title = e.target.value;
        return;
    }
    const found = _meFind(e.target.closest('.me-item').dataset.iid);
    if (!found) return;
    found.item[field] = e.target.value;
    e.target.classList.remove('is-invalid');
}

function _meOnClick(e) {
    const btn = e.target.closest('[data-act]');
    if (!btn || btn.disabled) return;
    const act = btn.dataset.act;
    const section = btn.closest('.me-group');
    const group = section && meDraft.groups.find(g => g.id === section.dataset.gid);
    const row = btn.closest('.me-item');
    const found = row && _meFind(row.dataset.iid);

    if (act === 'switcher') {
        meSwitcherHidden = !meSwitcherHidden;
        _meRender();
    } else if ((act === 'add' || act === 'icon') && mePopAnchor === btn) {
        _meClosePop();
    } else if (act === 'add') {
        _meOpenAddPop(btn, group);
    } else if (act === 'group-remove') {
        meDraft.groups = meDraft.groups.filter(g => g !== group);
        _meRender();
    } else if (act === 'icon' && found) {
        _meOpenIconPop(btn, found.item);
    } else if (act === 'open' && found) {
        found.item.open = btn.dataset.open;
        row.querySelectorAll('[data-act="open"]').forEach(b => b.classList.toggle('active', b === btn));
    } else if (act === 'toggle-hidden' && found) {
        found.item.hidden = !found.item.hidden;
        row.outerHTML = _meItemHTML(found.item);
    } else if (act === 'remove' && found) {
        found.group.items = found.group.items.filter(i => i !== found.item);
        _meRender();
    }
}

function menuEditorAddGroup() {
    const group = { id: _meId('g_'), title: '', items: [] };
    meDraft.groups.push(group);
    _meRender();
    const input = document.querySelector(`#menu-editor-body .me-group[data-gid="${group.id}"] .me-group-input`);
    if (input) { input.scrollIntoView({ block: 'center' }); input.focus(); }
}

function _meAdd(group, item) {
    group.items.push(item);
    _meClosePop();
    _meRender();
    const row = document.querySelector(`#menu-editor-body .me-item[data-iid="${CSS.escape(item.id)}"]`);
    if (!row) return;
    row.classList.add('is-new');
    row.scrollIntoView({ block: 'nearest' });
    const input = row.querySelector(item.type === 'url' && item.title ? '[data-field="url"]' : '[data-field="title"]');
    if (input) { input.focus(); input.select(); }
}

// ---------------------------------------------------------------------
// Popovers: icon picker, the add menu, and the artifact picker
// ---------------------------------------------------------------------

function _meOpenPop(anchor, html) {
    const pop = document.getElementById('menu-editor-pop');
    const box = pop.parentElement.getBoundingClientRect();
    const at = anchor.getBoundingClientRect();
    pop.innerHTML = html;
    pop.classList.remove('hidden');
    const left = Math.min(at.left - box.left, box.width - pop.offsetWidth - 12);
    const below = at.bottom - box.top + 6;
    const top = below + pop.offsetHeight > box.height - 8 ? at.top - box.top - pop.offsetHeight - 6 : below;
    pop.style.left = Math.max(12, left) + 'px';
    pop.style.top = Math.max(8, top) + 'px';
    mePopAnchor = anchor;
}

function _meClosePop() {
    const pop = document.getElementById('menu-editor-pop');
    if (pop) { pop.classList.add('hidden'); pop.innerHTML = ''; pop.onclick = null; }
    mePopAnchor = null;
    meArtToken++;
}

function _meOpenIconPop(anchor, item) {
    const cells = [`<button class="me-icon-cell me-icon-default${item.icon ? '' : ' active'}" data-icon="">${escapeHtml(t('menu_icon_default'))}</button>`]
        .concat(Object.keys(MENU_ICONS).map(key =>
            `<button class="me-icon-cell${item.icon === key ? ' active' : ''}" data-icon="${key}" title="${key}"><i class="fas ${MENU_ICONS[key]}"></i></button>`));
    _meOpenPop(anchor, `<div class="me-icon-grid">${cells.join('')}</div>`);
    document.getElementById('menu-editor-pop').onclick = (e) => {
        const cell = e.target.closest('[data-icon]');
        if (!cell) return;
        item.icon = cell.dataset.icon;
        anchor.innerHTML = `<i class="fas ${escapeHtml(menuItemIcon(item))}"></i>`;
        _meClosePop();
    };
}

function _meOpenAddPop(anchor, group) {
    // Pages of the console the menu does not carry yet (one removed earlier, or
    // one the built-in menu leaves out), listed by name rather than behind a
    // submenu of their own.
    const present = new Set();
    _meEach(i => { if (i.type === 'builtin') present.add(i.view); });
    const pages = Object.keys(MENU_BUILTINS).filter(view => !present.has(view)).map(view =>
        `<button data-view="${view}"><i class="fas ${MENU_BUILTINS[view].icon}"></i><span>${escapeHtml(t(MENU_BUILTINS[view].label))}</span></button>`);
    _meOpenPop(anchor, `<div class="me-menu">
        <button data-add="artifact"><i class="fas fa-file-lines"></i><span>${escapeHtml(t('menu_add_artifact'))}</span></button>
        <button data-add="url"><i class="fas fa-globe"></i><span>${escapeHtml(t('menu_add_url'))}</span></button>
        ${pages.length ? `<div class="me-menu-sep"></div><div class="me-menu-caption">${escapeHtml(t('menu_add_builtin'))}</div>${pages.join('')}` : ''}
    </div>`);
    document.getElementById('menu-editor-pop').onclick = (e) => {
        const choice = e.target.closest('[data-add],[data-view]');
        if (!choice) return;
        if (choice.dataset.view) _meAdd(group, menuBuiltinItem(choice.dataset.view));
        else if (choice.dataset.add === 'url') _meAdd(group, { id: _meId('m_'), type: 'url', title: '', icon: '', url: '', open: 'embed' });
        else _meOpenArtifactPop(anchor, group);
    };
}

function _meOpenArtifactPop(anchor, group) {
    _meOpenPop(anchor, `<div class="me-art-pick">
        <label class="me-art-search"><i class="fas fa-magnifying-glass"></i>
            <input type="text" spellcheck="false" autocomplete="off" placeholder="${escapeHtml(t('menu_artifact_search'))}">
        </label>
        <div class="me-art-list"><div class="me-pop-empty"><i class="fas fa-spinner fa-spin"></i></div></div>
    </div>`);
    const pop = document.getElementById('menu-editor-pop');
    const input = pop.querySelector('input');
    const list = pop.querySelector('.me-art-list');
    let items = [];
    const load = () => {
        const token = ++meArtToken;
        fetch(`/api/artifacts?scope=all&kind=page&limit=40&q=${encodeURIComponent(input.value.trim())}`)
            .then(r => r.json())
            .then(data => {
                if (token !== meArtToken) return;
                const inMenu = new Set();
                _meEach(i => { if (i.type === 'artifact') inMenu.add(i.path); });
                items = (data.items || []).filter(a => a.exists);
                list.innerHTML = items.map((a, index) => {
                    const added = inMenu.has(a.abs_path);
                    return `<button data-index="${index}" ${added ? 'disabled' : ''}>
                        <i class="${wsIconClass(a.kind)}"></i>
                        <span class="me-art-name">${escapeHtml(a.title || a.file_name)}</span>
                        <span class="me-art-path">${escapeHtml(added ? t('menu_already_added') : a.rel_path)}</span>
                    </button>`;
                }).join('') || `<div class="me-pop-empty">${escapeHtml(t('menu_artifact_empty'))}</div>`;
            })
            .catch(() => {
                if (token === meArtToken) list.innerHTML = `<div class="me-pop-empty">${escapeHtml(t('artifacts_load_failed'))}</div>`;
            });
    };
    input.addEventListener('input', () => {
        clearTimeout(meArtTimer);
        meArtTimer = setTimeout(load, 220);
    });
    pop.onclick = (e) => {
        const choice = e.target.closest('[data-index]');
        if (!choice || choice.disabled) return;
        const a = items[Number(choice.dataset.index)];
        _meAdd(group, {
            id: _meId('m_'), type: 'artifact', path: a.abs_path, icon: '',
            title: (a.title || a.file_name || '').slice(0, 40),
            file: { kind: a.kind, exists: true, file_name: a.file_name, preview_url: a.preview_url, raw_url: a.raw_url },
        });
    };
    input.focus();
    load();
}

// ---------------------------------------------------------------------
// Dragging: rows between and within groups, and the groups themselves
// ---------------------------------------------------------------------

function _meDragTarget(el) {
    return el.closest('.me-item') || el.closest('.me-group');
}

function _meInsertAt(container, selector, y) {
    const siblings = Array.from(container.querySelectorAll(`:scope > ${selector}`)).filter(n => n !== meDragging);
    const after = siblings.find(n => {
        const r = n.getBoundingClientRect();
        return y < r.top + r.height / 2;
    });
    if (after) {
        if (meDragging.nextElementSibling !== after) container.insertBefore(meDragging, after);
    } else if (container.lastElementChild !== meDragging) {
        container.appendChild(meDragging);
    }
}

function _meOnDragOver(e) {
    if (!meDragging) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
    if (meDragging.classList.contains('me-item')) {
        const section = e.target.closest('.me-group');
        if (section) _meInsertAt(section.querySelector('.me-items'), '.me-item', e.clientY);
    } else {
        _meInsertAt(document.getElementById('menu-editor-body'), '.me-group', e.clientY);
    }
}

/** Read the order back from the rows, which the drag moved in place. */
function _meSyncOrder() {
    const groups = new Map(meDraft.groups.map(g => [g.id, g]));
    const items = new Map();
    _meEach(i => items.set(i.id, i));
    meDraft.groups = Array.from(document.querySelectorAll('#menu-editor-body .me-group')).map(section => {
        const group = groups.get(section.dataset.gid);
        group.items = Array.from(section.querySelectorAll('.me-item')).map(row => items.get(row.dataset.iid));
        return group;
    });
}

// ---------------------------------------------------------------------
// Saving
// ---------------------------------------------------------------------

function _meInvalid(selector, key) {
    const input = document.querySelector(selector);
    if (input) {
        input.classList.add('is-invalid');
        input.scrollIntoView({ block: 'center' });
        input.focus();
    }
    _meError(t(key));
    return false;
}

function _meValidate() {
    for (const group of meDraft.groups) {
        group.title = (group.title || '').trim();
        if (!group.title && !MENU_GROUP_LABELS[group.id]) {
            return _meInvalid(`#menu-editor-body .me-group[data-gid="${group.id}"] .me-group-input`, 'menu_need_group_title');
        }
        for (const item of group.items) {
            item.title = (item.title || '').trim();
            const row = `#menu-editor-body .me-item[data-iid="${CSS.escape(item.id)}"]`;
            if (item.type !== 'builtin' && !item.title) return _meInvalid(`${row} [data-field="title"]`, 'menu_need_title');
            if (item.type === 'url') {
                item.url = (item.url || '').trim();
                if (!/^https?:\/\/[^\s/?#]+/i.test(item.url)) return _meInvalid(`${row} [data-field="url"]`, 'menu_need_url');
            }
        }
    }
    return true;
}

function menuEditorSave() {
    if (!meDraft || !_meValidate()) return;
    const menu = {
        groups: meDraft.groups.map(g => ({
            id: g.id, title: g.title,
            items: g.items.map(i => {
                const copy = Object.assign({}, i);
                delete copy.file;
                return copy;
            }),
        })),
    };
    _mePost(menu);
}

function menuEditorReset() {
    showConfirmDialog({
        title: t('menu_reset'),
        message: t('menu_reset_confirm'),
        okText: t('menu_reset'),
        cancelText: t('channels_cancel'),
        onConfirm: () => _mePost(null),
    });
}

function _mePost(menu) {
    const btn = document.getElementById('menu-editor-save');
    btn.disabled = true;
    fetch('/api/menu', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ menu: menu }),
    })
        .then(r => r.json())
        .then(data => {
            if (data.status !== 'success') throw new Error(data.message || t('menu_save_failed'));
            menuApply(data.menu);
            setInstanceSwitcherHidden(meSwitcherHidden);
            menuEditorClose();
            // The page on screen may be the entry just removed.
            if (currentView === 'custom' && !menuFind(menuCustomId)) navigateTo('chat');
        })
        .catch(err => _meError(err.message || t('menu_save_failed')))
        .finally(() => { btn.disabled = false; });
}

(function () {
    const overlay = document.getElementById('menu-editor-overlay');
    const body = document.getElementById('menu-editor-body');
    body.addEventListener('input', _meOnInput);
    body.addEventListener('click', _meOnClick);
    // A row only becomes draggable while its handle is held, so text in its
    // inputs can still be selected with the mouse.
    body.addEventListener('mousedown', (e) => {
        const handle = e.target.closest('[data-drag]');
        if (handle) _meDragTarget(handle).setAttribute('draggable', 'true');
    });
    body.addEventListener('dragstart', (e) => {
        const el = e.target.closest && e.target.closest('[draggable="true"]');
        if (!el) return;
        meDragging = el;
        _meClosePop();
        e.dataTransfer.effectAllowed = 'move';
        e.dataTransfer.setData('text/plain', '');
        requestAnimationFrame(() => el.classList.add('is-dragging'));
    });
    body.addEventListener('dragover', _meOnDragOver);
    body.addEventListener('drop', (e) => e.preventDefault());
    body.addEventListener('dragend', () => {
        if (!meDragging) return;
        meDragging.classList.remove('is-dragging');
        meDragging.removeAttribute('draggable');
        meDragging = null;
        _meSyncOrder();
        _meRender();
    });
    document.addEventListener('mouseup', () => {
        if (meDragging) return;
        body.querySelectorAll('[draggable="true"]').forEach(el => el.removeAttribute('draggable'));
    });
    overlay.addEventListener('mousedown', (e) => {
        if (!mePopAnchor) return;
        const pop = document.getElementById('menu-editor-pop');
        if (!pop.contains(e.target) && !mePopAnchor.contains(e.target)) _meClosePop();
    });
})();
