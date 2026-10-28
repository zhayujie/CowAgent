/* Sidebar menu: drawn from the layout the user arranged (GET /api/menu), or
   from the built-in one until they save one. The desktop client reads the same
   document, so a page only one client has is skipped by the other rather than
   dropped. The artifacts and links in it open in the custom view, /m/<id>.

   These are classic scripts sharing one global scope; see
   channel/web/README.md before changing the load order. Uses nav.js
   (navigateTo, syncSidebarTips) at call time, and workspace.js
   (wsRenderPreview, WS_KIND_ICONS) once the page has loaded. */

// The pages of this console that a menu can lead to.
const MENU_BUILTINS = {
    chat:      { icon: 'fa-message',          label: 'menu_chat' },
    artifacts: { icon: 'fa-layer-group',      label: 'menu_artifacts' },
    agents:    { icon: 'fa-people-group',     label: 'menu_agents' },
    config:    { icon: 'fa-sliders',          label: 'menu_config' },
    skills:    { icon: 'fa-bolt',             label: 'menu_skills' },
    memory:    { icon: 'fa-brain',            label: 'menu_memory' },
    knowledge: { icon: 'fa-book',             label: 'menu_knowledge' },
    channels:  { icon: 'fa-tower-broadcast',  label: 'menu_channels' },
    users:     { icon: 'fa-user-group',       label: 'menu_users' },
    tasks:     { icon: 'fa-clock',            label: 'menu_tasks' },
    logs:      { icon: 'fa-terminal',         label: 'menu_logs' },
};

// The built-in menu, as sidebar.html draws it before any script runs.
const MENU_DEFAULT = [
    { id: 'chat',    views: ['chat', 'artifacts'] },
    { id: 'manage',  views: ['agents', 'config', 'skills', 'memory', 'knowledge', 'channels', 'users', 'tasks'] },
    { id: 'monitor', views: ['logs'] },
];
// Built-in pages that start hidden, so only the menu editor offers them.
const MENU_DEFAULT_HIDDEN = new Set(['artifacts']);
const MENU_GROUP_LABELS = { chat: 'nav_chat', manage: 'nav_manage', monitor: 'nav_monitor' };
// Pages a menu must always lead to; mirrors REQUIRED_VIEWS in api/menu.py.
const MENU_REQUIRED = ['chat', 'config'];
// Artifacts that can be a page of the menu; mirrors MENU_KINDS in api/menu.py.
const MENU_KINDS = ['html', 'markdown'];

// Icons a user can give an entry. The desktop client maps the same names to
// its own icon set, so only the names travel in the document.
const MENU_ICONS = {
    globe: 'fa-globe', link: 'fa-link', chart: 'fa-chart-line', gauge: 'fa-gauge',
    table: 'fa-table', file: 'fa-file-lines', book: 'fa-book', image: 'fa-image',
    video: 'fa-film', music: 'fa-music', code: 'fa-code', calendar: 'fa-calendar',
    star: 'fa-star', bookmark: 'fa-bookmark', folder: 'fa-folder', box: 'fa-box',
    rocket: 'fa-rocket', flag: 'fa-flag', heart: 'fa-heart', bolt: 'fa-bolt',
    brain: 'fa-brain', clock: 'fa-clock', terminal: 'fa-terminal', home: 'fa-house',
    cart: 'fa-cart-shopping', mail: 'fa-envelope', layers: 'fa-layer-group',
    robot: 'fa-robot', pen: 'fa-pen', search: 'fa-magnifying-glass',
};

const MENU_CACHE_KEY = 'cow_menu_cache';

let menuSaved = null;
let menuDoc = menuMerge(null);
let menuLoaded = false;
let menuCustomId = '';
let menuPageKey = '';
let _menuReadyResolve;
const menuReady = new Promise(resolve => { _menuReadyResolve = resolve; });

function menuBuiltinItem(view) {
    return { id: view, type: 'builtin', view: view, title: '', icon: '', hidden: false };
}

function _menuDefaultItem(view) {
    return Object.assign(menuBuiltinItem(view), { hidden: MENU_DEFAULT_HIDDEN.has(view) });
}

/** The menu to draw: the saved one, plus any page this version added since. */
function menuMerge(saved) {
    if (!saved || !Array.isArray(saved.groups) || !saved.groups.length) {
        return { groups: MENU_DEFAULT.map(g => ({ id: g.id, title: '', items: g.views.map(_menuDefaultItem) })) };
    }
    const doc = {
        groups: saved.groups.map(g => ({
            id: g.id, title: g.title || '',
            items: (g.items || []).map(i => Object.assign({}, i)),
        })),
    };
    const present = new Set();
    doc.groups.forEach(g => g.items.forEach(i => { if (i.type === 'builtin') present.add(i.view); }));
    MENU_DEFAULT.forEach(def => def.views.forEach(view => {
        if (present.has(view)) return;
        const home = doc.groups.find(g => g.id === def.id) || doc.groups[doc.groups.length - 1];
        home.items.push(_menuDefaultItem(view));
    }));
    return doc;
}

function menuFind(id) {
    for (const group of menuDoc.groups) {
        const item = group.items.find(i => i.id === id);
        if (item) return { group: group, item: item };
    }
    return null;
}

function menuGroupLabel(group) {
    return group.title || (MENU_GROUP_LABELS[group.id] ? t(MENU_GROUP_LABELS[group.id]) : t('menu_group_untitled'));
}

function menuItemLabel(item) {
    if (item.title) return item.title;
    const builtin = item.type === 'builtin' && MENU_BUILTINS[item.view];
    return builtin ? t(builtin.label) : (item.view || '');
}

function menuItemIcon(item) {
    if (item.icon && MENU_ICONS[item.icon]) return MENU_ICONS[item.icon];
    if (item.type === 'builtin') return (MENU_BUILTINS[item.view] || {}).icon || 'fa-circle';
    if (item.type === 'url') return 'fa-globe';
    const kind = (item.file && item.file.kind) || 'file';
    return (typeof WS_KIND_ICONS !== 'undefined' && WS_KIND_ICONS[kind]) || 'fa-file';
}

/** Whether this console draws the entry: hidden pages and other clients' pages are skipped. */
function menuShows(item) {
    if (item.type !== 'builtin') return true;
    return !!MENU_BUILTINS[item.view] && !item.hidden;
}

function _menuItemHTML(item) {
    const builtin = item.type === 'builtin';
    const label = builtin && !item.title
        ? `<span data-i18n="${escapeHtml(MENU_BUILTINS[item.view].label)}">${escapeHtml(menuItemLabel(item))}</span>`
        : `<span class="sidebar-label">${escapeHtml(menuItemLabel(item))}</span>`;
    const external = item.type === 'url' && item.open === 'tab'
        ? '<i class="fas fa-arrow-up-right-from-square sidebar-ext"></i>' : '';
    return `<a class="sidebar-item flex items-center gap-3 px-3 py-2 rounded-lg cursor-pointer transition-all duration-150 hover:bg-white/5 hover:text-neutral-200 text-[14px]"
               data-view="${builtin ? escapeHtml(item.view) : 'custom'}"${builtin ? '' : ` data-menu-id="${escapeHtml(item.id)}"`}>
            <i class="fas ${escapeHtml(menuItemIcon(item))} item-icon text-xs w-5 text-center"></i>${label}${external}
        </a>`;
}

function menuRenderSidebar() {
    const nav = document.getElementById('sidebar-nav');
    if (!nav) return;
    let folded = {};
    try { folded = JSON.parse(localStorage.getItem(SIDEBAR_GROUPS_KEY) || '{}'); } catch (_) { /* keep defaults */ }
    nav.innerHTML = menuDoc.groups.map(group => {
        const items = group.items.filter(menuShows);
        if (!items.length) return '';
        const title = !group.title && MENU_GROUP_LABELS[group.id]
            ? `<span data-i18n="${MENU_GROUP_LABELS[group.id]}">${escapeHtml(menuGroupLabel(group))}</span>`
            : `<span>${escapeHtml(menuGroupLabel(group))}</span>`;
        return `<div class="menu-group${folded[group.id] === false ? '' : ' open'}" data-group="${escapeHtml(group.id)}">
            <button class="menu-group-head w-full flex items-center gap-2 pl-3 pr-8 py-2 text-xs font-semibold uppercase tracking-wider text-neutral-500 hover:text-neutral-300 cursor-pointer transition-colors duration-150">
                <i class="fas fa-chevron-right text-[10px] chevron"></i>${title}
            </button>
            <button class="menu-group-edit" onclick="menuEditorOpen()" data-tip-key="menu_edit" data-tooltip="${escapeHtml(t('menu_edit'))}"
                    data-tip-float data-tooltip-pos="right" aria-label="${escapeHtml(t('menu_edit'))}"><i class="fas fa-pen"></i></button>
            <div class="menu-group-items pl-2">${items.map(_menuItemHTML).join('')}</div>
        </div>`;
    }).join('');
    document.documentElement.classList.remove('menu-pending');
    syncSidebarTips();
    menuSyncActive();
}

/** Light the entry for what is on screen. */
function menuSyncActive() {
    const meta = VIEW_META[currentView] || {};
    const own = document.querySelector(`#sidebar .sidebar-item[data-view="${currentView}"]:not([data-menu-id])`);
    const navId = own ? currentView : (meta.nav || currentView);
    document.querySelectorAll('#sidebar .sidebar-item').forEach(el => {
        const active = el.dataset.menuId
            ? currentView === 'custom' && el.dataset.menuId === menuCustomId
            : el.dataset.view === navId;
        el.classList.toggle('active', active);
    });
    const found = currentView === 'custom' ? menuFind(menuCustomId) : null;
    document.getElementById('breadcrumb-external')?.classList.toggle('hidden', !_menuPageTarget(found && found.item));
}

/** Take a menu document as the one in force: draw it and remember it for the next load. */
function menuApply(saved) {
    menuSaved = saved || null;
    menuDoc = menuMerge(menuSaved);
    try {
        if (menuSaved) localStorage.setItem(MENU_CACHE_KEY, JSON.stringify(menuSaved));
        else localStorage.removeItem(MENU_CACHE_KEY);
    } catch (_) { /* private mode */ }
    menuRenderSidebar();
    if (currentView === 'custom') _menuRenderPage();
}

function menuLoad() {
    return fetch('/api/menu')
        .then(r => r.json())
        .then(data => { if (data.status === 'success') menuApply(data.menu); })
        .catch(() => {})
        .finally(() => {
            menuLoaded = true;
            _menuReadyResolve();
            if (currentView === 'custom') _menuRenderPage();
        });
}

/** A click on an entry the user added: a link set to open in a tab leaves the console. */
function menuOpenItem(id) {
    const found = menuFind(id);
    if (found && found.item.type === 'url' && found.item.open === 'tab') {
        window.open(found.item.url, '_blank', 'noopener,noreferrer');
        return;
    }
    navigateTo('custom', id);
}

// ---------------------------------------------------------------------
// The custom view
// ---------------------------------------------------------------------

/** Called by navigateTo for /m/<id>. Every visit reloads the page, since the
    file or site behind an unchanged entry may have changed since the last one. */
function menuShowPage(id) {
    menuCustomId = id || '';
    menuSyncActive();
    _menuRenderPage(true);
}

function _menuSetBreadcrumb(found) {
    const group = document.getElementById('breadcrumb-group');
    const page = document.getElementById('breadcrumb-page');
    const groupKey = found && !found.group.title && MENU_GROUP_LABELS[found.group.id];
    group.textContent = found ? menuGroupLabel(found.group) : '';
    if (groupKey) group.dataset.i18n = groupKey;
    else delete group.dataset.i18n;
    page.textContent = found ? menuItemLabel(found.item) : '';
    delete page.dataset.i18n;
}

function _menuPageTarget(item) {
    if (!item || item.type === 'builtin') return '';
    if (item.type === 'url') return item.url;
    return (item.file && (item.file.preview_url || item.file.raw_url)) || '';
}

function _menuRenderPage(force) {
    const found = menuFind(menuCustomId);
    const item = found && found.item.type !== 'builtin' ? found.item : null;
    _menuSetBreadcrumb(item ? found : null);
    const key = item ? JSON.stringify(item) : (menuLoaded ? 'missing' : 'loading');
    if (!force && key === menuPageKey) return;
    menuPageKey = key;

    const body = document.getElementById('menu-page-body');
    menuSyncActive();
    if (!item) {
        body.innerHTML = menuLoaded
            ? `<div class="workspace-empty"><i class="fas fa-link-slash"></i><span>${escapeHtml(t('menu_page_missing'))}</span>
                 <button class="ws-empty-action" onclick="navigateTo('chat')"><span>${escapeHtml(t('menu_back_chat'))}</span></button></div>`
            : '<div class="workspace-empty"><i class="fas fa-spinner fa-spin"></i></div>';
        return;
    }

    body.innerHTML = '';
    if (item.type === 'url') {
        const frame = document.createElement('iframe');
        // The page keeps its own origin; the sandbox only withholds what an
        // embedded site has no business doing to the console around it.
        frame.setAttribute('sandbox', 'allow-scripts allow-same-origin allow-forms allow-popups allow-popups-to-escape-sandbox allow-modals allow-downloads');
        frame.setAttribute('referrerpolicy', 'no-referrer');
        frame.src = item.url;
        body.appendChild(frame);
        return;
    }
    const file = item.file || {};
    if (!file.exists) {
        body.innerHTML = `<div class="workspace-empty"><i class="fas fa-file-circle-xmark"></i><span>${escapeHtml(t('menu_file_missing'))}</span></div>`;
        return;
    }
    const stage = document.createElement('div');
    stage.className = 'menu-page-stage';
    body.appendChild(stage);
    wsRenderPreview(Object.assign({ path: item.path }, file), stage);
}

function menuOpenPageExternally() {
    const found = menuFind(menuCustomId);
    const target = found && _menuPageTarget(found.item);
    if (target) window.open(target, '_blank', 'noopener,noreferrer');
}

// Draw what the last visit saved, so a customised menu does not flash the
// built-in one first; GET /api/menu then brings it up to date.
(function () {
    try {
        const cached = JSON.parse(localStorage.getItem(MENU_CACHE_KEY) || 'null');
        if (cached) {
            menuSaved = cached;
            menuDoc = menuMerge(cached);
        }
    } catch (_) { /* unreadable cache: the built-in menu it is */ }
    menuRenderSidebar();
})();
