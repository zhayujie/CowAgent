// Drive core/router.js against a stubbed page and check what it does to the
// history stack -- which view opens, and how many entries Back has to walk.
// The Python tests can assert that the routing code is wired up, but not what
// it does once it runs; this is that half. Run it by hand after touching the
// router:
//
//     node channel/web/tools/check-router.mjs
//
// No dependencies, no browser: the router only touches location, history and
// one event listener, all of which are stubbed below.
import { readFileSync } from 'fs';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';

const HERE = dirname(fileURLToPath(import.meta.url));
const routerSrc = readFileSync(
    join(HERE, '..', 'static', 'js', 'core', 'router.js'), 'utf8');

// Stands in for nav.js + the view scripts: records what it was asked to do and
// calls back into the router exactly where the real code does.
const fakeNav = `
function switchConfigTab(tab)    { log.tabs.push('config/' + tab);    routeNoteTab('config', tab); }
function switchMemoryTab(tab)    { log.tabs.push('memory/' + tab);    routeNoteTab('memory', tab); }
function switchTasksTab(tab)     { log.tabs.push('tasks/' + tab);     routeNoteTab('tasks', tab); }
function switchKnowledgeTab(tab) { log.tabs.push('knowledge/' + tab); routeNoteTab('knowledge', tab); }

function navigateTo(viewId, tab) {
    log.nav.push(viewId + (tab ? '/' + tab : ''));
    if (guardRefuses) return false;
    currentView = viewId;
    routeEnterView(viewId);
    if (viewId === 'config') switchConfigTab(tab || 'basic');
    else if (viewId === 'memory') switchMemoryTab(tab || 'files');
    else if (viewId === 'tasks') switchTasksTab(tab || 'tasks');
    // Knowledge takes no default from the caller because loadKnowledgeView
    // lands on docs by itself; a route-named tab then overrides it.
    else if (viewId === 'knowledge') { switchKnowledgeTab('docs'); if (tab) switchKnowledgeTab(tab); }
    return true;
}
`;

function makeApp(startPath) {
    const log = { nav: [], tabs: [], writes: [] };
    const state = { path: startPath || '/' };

    const VIEW_META = {};
    for (const v of ['chat', 'agents', 'config', 'skills', 'memory',
                     'knowledge', 'channels', 'tasks', 'logs']) VIEW_META[v] = {};

    const location = { get pathname() { return state.path; } };
    const history = {
        pushState(_s, _t, p) { log.writes.push('push ' + p); state.path = p; },
        replaceState(_s, _t, p) { log.writes.push('replace ' + p); state.path = p; },
    };
    let fire = null;
    const window = { addEventListener(ev, fn) { if (ev === 'popstate') fire = fn; } };

    const factory = new Function('env', `
        const { VIEW_META, location, history, window, log } = env;
        let currentView = 'chat';
        let guardRefuses = false;
        ${fakeNav}
        ${routerSrc}
        return {
            routeApply, navigateTo,
            get currentView() { return currentView; },
            get routeTab() { return routeTab; },
            set guardRefuses(v) { guardRefuses = v; },
        };
    `);

    const app = factory({ VIEW_META, location, history, window, log });
    // Back/Forward: the browser moves the URL, then notifies.
    app.back = (path) => { state.path = path; fire(); };
    app.log = log;
    app.path = () => state.path;
    return app;
}

let failures = 0;
function check(label, actual, expected) {
    const a = JSON.stringify(actual), e = JSON.stringify(expected);
    const ok = a === e;
    if (!ok) failures++;
    console.log(`${ok ? 'ok  ' : 'FAIL'}  ${label}`);
    if (!ok) console.log(`        got      ${a}\n        expected ${e}`);
}

// --- the console root opens chat and writes nothing -----------------------
let app = makeApp('/');
app.routeApply();
check('root: no navigation', app.log.nav, []);
check('root: address bar untouched', app.log.writes, []);

// --- a shared link opens the view and tab it names, without churn ---------
app = makeApp('/settings/models');
app.routeApply();
check('deep link: navigates once', app.log.nav, ['config/models']);
check('deep link: opens the named tab', app.log.tabs, ['config/models']);
check('deep link: no history entries added', app.log.writes, []);
check('deep link: lands on the view', app.currentView, 'config');

// the settings view is not at /config: that path is the config API
app = makeApp('/config');
app.routeApply();
check('/config is not a view route', app.currentView, 'chat');

// --- a hand-edited or stale route degrades instead of throwing ------------
app = makeApp('/knowledge/bogus');
app.routeApply();
check('unknown tab: dropped, view still opens', app.log.nav, ['knowledge']);
check('unknown tab: never switched to', app.log.tabs, ['knowledge/docs']);
check('unknown tab: address bar corrected to the tab that did open',
      app.path(), '/knowledge/docs');

app = makeApp('/nope');
app.routeApply();
check('unknown path: falls back to chat, no navigation', app.log.nav, []);
check('unknown path: address bar corrected to chat', app.path(), '/');

// a view named without one of its tabs lands on its default, and says so
app = makeApp('/settings');
app.routeApply();
check('bare view: opens the default tab', app.log.tabs, ['config/basic']);
check('bare view: address bar completed to it', app.path(), '/settings/basic');

// a trailing slash is the same route
app = makeApp('/settings/models/');
app.routeApply();
check('trailing slash: same route', app.log.nav, ['config/models']);
check('trailing slash: normalised away', app.path(), '/settings/models');

// --- clicking through the sidebar leaves one entry per view ---------------
app = makeApp('/');
app.navigateTo('config');
check('sidebar: one entry for the view, refined to its tab',
      app.log.writes, ['push /settings', 'replace /settings/basic']);
app.log.writes.length = 0;
app.navigateTo('skills');
check('sidebar: a tabless view is one plain entry',
      app.log.writes, ['push /skills']);
app.log.writes.length = 0;
app.navigateTo('chat');
check('sidebar: chat is the root path', app.log.writes, ['push /']);

// --- re-entering the current view refines rather than stacking ------------
app = makeApp('/');
app.navigateTo('config');
app.log.writes.length = 0;
app.navigateTo('config', 'models');
check('re-entry: refines the entry, never pushes a second one',
      app.log.writes, ['replace /settings', 'replace /settings/models']);

// clicking the sidebar item you are already on, repeatedly
app = makeApp('/');
app.navigateTo('skills');
app.log.writes.length = 0;
app.navigateTo('skills');
app.navigateTo('skills');
check('re-entry: a tabless view stays at one entry', app.log.writes, []);

// --- Back returns to the previous view -----------------------------------
app = makeApp('/');
app.navigateTo('config');
app.log.nav.length = 0;
app.back('/');
check('back: navigates to the previous view', app.log.nav, ['chat']);
check('back: lands there', app.currentView, 'chat');

// --- Back with unsaved edits puts the address bar back --------------------
app = makeApp('/');
app.navigateTo('config');
app.guardRefuses = true;
app.log.writes.length = 0;
app.back('/');
check('guarded back: stays on the view', app.currentView, 'config');
check('guarded back: address bar restored, without a new entry',
      app.log.writes, ['replace /settings/basic']);

// --- applying a route must not re-enter through the address bar -----------
app = makeApp('/tasks/records');
app.routeApply();
check('apply: does not loop back in', app.log.nav, ['tasks/records']);
check('apply: tracks the tab for a later restore', app.routeTab, 'records');

console.log(failures ? `\n${failures} FAILED` : '\nall scenarios pass');
process.exit(failures ? 1 : 0);
