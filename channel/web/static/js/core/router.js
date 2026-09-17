/* Address-bar routing: mirrors the current view and tab into the URL path, so
   a reload lands where the user left off and Back/Forward move between views.
   These are classic scripts sharing one global scope; see
   channel/web/README.md before changing the load order. */

// =====================================================================
// Routing
// =====================================================================
// A route names a view and, for the views that have tabs, one of its tabs:
// /settings, /settings/models. Deeper state -- which session is open, which
// file the editor holds -- deliberately stays out. It is already restored from
// localStorage, and putting it in the URL would rewrite the address bar on
// every click in the session list.
//
// The view a route names is not always the view's internal id: /settings is
// the config view, because /config is the backend's config API, which this
// console and the desktop client both call. web_channel.py serves these paths
// from the same shell; the table there has to stay in step with this one.
const ROUTE_PATHS = {
    chat:      '',
    agents:    'agents',
    config:    'settings',
    skills:    'skills',
    memory:    'memory',
    knowledge: 'knowledge',
    channels:  'channels',
    tasks:     'tasks',
    logs:      'logs',
};

const ROUTE_VIEWS = {};
for (const view in ROUTE_PATHS) ROUTE_VIEWS[ROUTE_PATHS[view]] = view;

const ROUTE_TABS = {
    config:    ['basic', 'models'],
    memory:    ['files', 'dreams'],
    tasks:     ['tasks', 'records'],
    knowledge: ['docs', 'graph'],
};

// The tab showing in the current view, '' for a view that has none. Tracked so
// a navigation the unsaved-edit guard refuses can put the address bar back
// exactly where it was.
let routeTab = '';

// Set while a route is being applied to the page. The handlers that normally
// write the address bar then leave it alone: it already says what is being
// applied, and writing would stack a duplicate entry onto the history.
let _routeApplying = false;

function _routePath(view, tab) {
    const path = ROUTE_PATHS[view] || '';
    return '/' + path + (path && tab ? '/' + tab : '');
}

function _routeParse(pathname) {
    const parts = String(pathname || '/').replace(/^\/+|\/+$/g, '').split('/');
    const view = ROUTE_VIEWS[parts[0] || ''];
    // An unknown path -- a stale bookmark, a hand-edited URL -- falls back to
    // chat rather than leaving the console on whatever happens to be on screen.
    if (!view || !VIEW_META[view]) return { view: 'chat', tab: '' };
    const allowed = ROUTE_TABS[view] || [];
    // An unknown tab is dropped, not passed on: the tab switchers index into
    // the DOM by name and would throw on one that does not exist.
    return { view: view, tab: allowed.indexOf(parts[1]) === -1 ? '' : parts[1] };
}

function _routeWrite(view, tab, replace) {
    const path = _routePath(view, tab);
    if (location.pathname === path) return;
    // pushState/replaceState do not fire popstate, so writing the address bar
    // cannot loop back in as a navigation.
    history[replace ? 'replaceState' : 'pushState'](null, '', path);
}

function _routeApplyTab(view, tab) {
    if (view === 'config') switchConfigTab(tab);
    else if (view === 'memory') switchMemoryTab(tab);
    else if (view === 'tasks') switchTasksTab(tab);
    else if (view === 'knowledge') switchKnowledgeTab(tab);
}

// Called by navigateTo() once it has committed to a view: the history gains an
// entry, so Back returns to where the user came from.
function routeEnterView(view) {
    if (!VIEW_META[view]) return;
    routeTab = '';
    if (_routeApplying) return;
    // Re-entering the view already on screen -- clicking its sidebar item
    // again -- is not a new destination. Refine the entry instead of stacking
    // another, or Back would have to undo a run of no-op navigations before it
    // appeared to do anything.
    const reentry = _routeParse(location.pathname).view === view;
    _routeWrite(view, '', reentry);
}

// Called by the tab switchers. A tab is a refinement of the view already on
// screen rather than a new destination, so it replaces the entry navigateTo
// just pushed instead of stacking another one -- Back then leaves the view,
// instead of stepping back through every tab visited inside it.
function routeNoteTab(view, tab) {
    if (view !== currentView) return;
    routeTab = tab;
    if (_routeApplying) return;
    _routeWrite(view, tab, true);
}

// Apply what the address bar says: on Back/Forward, and once at startup.
function routeApply() {
    const parsed = _routeParse(location.pathname);

    if (parsed.view === currentView) {
        if (parsed.tab && parsed.tab !== routeTab) {
            _routeApplying = true;
            try { _routeApplyTab(parsed.view, parsed.tab); }
            finally { _routeApplying = false; }
        }
    } else {
        _routeApplying = true;
        try { navigateTo(parsed.view, parsed.tab); }
        finally { _routeApplying = false; }
    }

    // Settle the address bar on whatever ended up on screen. Usually it
    // already says that and this writes nothing. It earns its keep in the two
    // cases where the path and the page disagree: a path that named a tab the
    // view does not have (/settings/bogus, /settings on its own) lands on the
    // view's default tab and the path is completed to match; and a navigation
    // the unsaved-edit guard refused leaves the page where it was, so the
    // address bar -- which Back has already moved -- has to go back with it.
    _routeWrite(currentView, routeTab, true);
}

window.addEventListener('popstate', routeApply);
