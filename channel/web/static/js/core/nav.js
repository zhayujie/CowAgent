/* Sidebar routing: navigateTo plus the per-view lazy loading hook.
   Split out of console.js. These are classic scripts sharing one global
   scope; see channel/web/README.md before changing the load order. */

// =====================================================================
// Sidebar & Navigation
// =====================================================================
const VIEW_META = {
    chat:     { group: 'nav_chat',    page: 'menu_chat' },
    agents:   { group: 'nav_manage',  page: 'menu_agents' },
    config:   { group: 'nav_manage',  page: 'menu_config' },
    skills:   { group: 'nav_manage',  page: 'menu_skills' },
    memory:   { group: 'nav_manage',  page: 'menu_memory' },
    knowledge:{ group: 'nav_manage',  page: 'menu_knowledge' },
    channels: { group: 'nav_manage',  page: 'menu_channels' },
    tasks:    { group: 'nav_manage',  page: 'menu_tasks' },
    logs:     { group: 'nav_monitor', page: 'menu_logs' },
};

let currentView = 'chat';

// The view switch itself. Callers want navigateTo() below, which wraps this
// with the unsaved-edit guard and the per-view lazy loading.
function _switchToView(viewId) {
    if (!VIEW_META[viewId]) return;
    document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
    const target = document.getElementById('view-' + viewId);
    if (target) target.classList.add('active');
    document.querySelectorAll('.sidebar-item').forEach(item => {
        item.classList.toggle('active', item.dataset.view === viewId);
    });
    const meta = VIEW_META[viewId];
    document.getElementById('breadcrumb-group').textContent = t(meta.group);
    document.getElementById('breadcrumb-group').dataset.i18n = meta.group;
    document.getElementById('breadcrumb-page').textContent = t(meta.page);
    document.getElementById('breadcrumb-page').dataset.i18n = meta.page;
    const leavingAgents = currentView === 'agents' && viewId !== 'agents';
    currentView = viewId;
    // The Agent detail is a fixed drawer, so it would otherwise hang over
    // whatever view you navigate to. It only belongs to the Agent Team page.
    if (viewId !== 'agents') closeAgentDetail();
    if (viewId === 'agents') {
        // The team page is a wide two-pane workbench; the history panel on top
        // of it would leave the detail cramped. Tuck it away on entry and put it
        // back the way it was when the user leaves (only if they hadn't already
        // toggled it themselves in the meantime).
        _sessionPanelWasOpen = sessionPanelOpen;
        if (sessionPanelOpen) closeSessionPanel(true);
        loadAgentCatalog();
    } else if (leavingAgents && _sessionPanelWasOpen) {
        _sessionPanelWasOpen = false;
        openSessionPanel();
    }
    
    // Clear status messages when navigating away
    document.querySelectorAll('[id$="-status"]').forEach(el => {
        el.classList.add('opacity-0');
    });
    
    if (window.innerWidth < 1024) closeSidebar();
}

function toggleSidebar() {
    const sidebar = document.getElementById('sidebar');
    const overlay = document.getElementById('sidebar-overlay');
    const isOpen = !sidebar.classList.contains('-translate-x-full');
    if (isOpen) {
        closeSidebar();
    } else {
        sidebar.classList.remove('-translate-x-full');
        overlay.classList.remove('hidden');
    }
}

function closeSidebar() {
    document.getElementById('sidebar').classList.add('-translate-x-full');
    document.getElementById('sidebar-overlay').classList.add('hidden');
}

document.querySelectorAll('.menu-group > button').forEach(btn => {
    btn.addEventListener('click', () => {
        btn.parentElement.classList.toggle('open');
    });
});

document.querySelectorAll('.sidebar-item').forEach(item => {
    item.addEventListener('click', () => navigateTo(item.dataset.view));
});

window.addEventListener('resize', () => {
    if (window.innerWidth >= 1024) {
        document.getElementById('sidebar').classList.remove('-translate-x-full');
        document.getElementById('sidebar-overlay').classList.add('hidden');
    } else {
        if (!document.getElementById('sidebar').classList.contains('-translate-x-full')) {
            closeSidebar();
        }
    }
});

// =====================================================================
// View Navigation
// =====================================================================
// Everything routes through here: the sidebar, the breadcrumb and the
// navigateTo() calls in generated onclick handlers.
// `tab` is optional and comes from the address bar; a caller that does not
// name one gets the view's usual landing tab. Returns false when the guard
// below refused to leave the current view, which is what lets the router put
// the address bar back after a Back it could not honour.
function navigateTo(viewId, tab) {
    // An open document editor is about to be replaced by another view, which
    // would drop the edit with nothing on screen to say so.
    if (!docGuardUnsaved(() => navigateTo(viewId, tab))) return false;

    // Stop log stream when leaving logs view
    if (currentView === 'logs' && viewId !== 'logs') stopLogStream();

    _switchToView(viewId);
    // The address bar follows the view, so a reload lands back here.
    routeEnterView(viewId);

    // Lazy-load view data
    if (viewId === 'config') { loadConfigView(); switchConfigTab(tab || 'basic'); }
    else if (viewId === 'skills') { resetSkillViewer(); loadSkillsView(); }
    else if (viewId === 'memory') {
        memoryEditor.forget();
        document.getElementById('memory-panel-viewer').classList.add('hidden');
        document.getElementById('memory-panel-list').classList.remove('hidden');
        // Keep the last viewed Agent across refreshes, but drop it if that
        // Agent has since been deleted so we don't point at a ghost.
        if (memoryAgentId && agentCatalog.length && !agentCatalog.some(a => a.id === memoryAgentId)) {
            memoryAgentId = '';
            localStorage.removeItem('cow_memory_agent');
        }
        if (!memoryAgentId) memoryAgentId = activeAgentId || defaultAgentId;
        renderMemoryAgentSelect();
        switchMemoryTab(tab || 'files');
    }
    // loadKnowledgeView lands on the docs tab itself, so unlike the views
    // above there is no default to pass -- only a route-named tab to override
    // it with.
    else if (viewId === 'knowledge') { loadKnowledgeView(); if (tab) switchKnowledgeTab(tab); }
    else if (viewId === 'channels') loadChannelsView();
    else if (viewId === 'tasks') { switchTasksTab(tab || 'tasks'); loadTasksView(); }
    else if (viewId === 'logs') startLogStream();
    return true;
}

