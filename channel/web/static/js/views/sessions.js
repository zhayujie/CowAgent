/* Session history panel: list, pin, rename, project grouping.
   Split out of console.js. These are classic scripts sharing one global
   scope; see channel/web/README.md before changing the load order. */

// =====================================================================
// Session Panel
// =====================================================================

const SESSION_PANEL_KEY = 'cow_session_panel_open';
let sessionPanelOpen = localStorage.getItem(SESSION_PANEL_KEY) === '1';
// Whether the history panel was open before entering the team page, so it can
// be restored on the way out (the team page force-closes it for room).
let _sessionPanelWasOpen = false;

function _persistPanelState() {
    localStorage.setItem(SESSION_PANEL_KEY, sessionPanelOpen ? '1' : '0');
}

function _isMobileView() {
    return window.innerWidth <= 768;
}

function _showSessionOverlay() {
    if (!_isMobileView()) return;
    const overlay = document.getElementById('session-panel-overlay');
    if (overlay) overlay.classList.remove('hidden');
}

function _hideSessionOverlay() {
    const overlay = document.getElementById('session-panel-overlay');
    if (overlay) overlay.classList.add('hidden');
}

function closeSessionPanel(skipPersist) {
    const panel = document.getElementById('session-panel');
    if (!panel || !sessionPanelOpen) return;
    sessionPanelOpen = false;
    panel.classList.add('hidden');
    _hideSessionOverlay();
    // When the team page tucks the panel away it shouldn't overwrite the user's
    // own preference; only real user closes persist.
    if (!skipPersist) _persistPanelState();
}

function toggleSessionPanel() {
    const panel = document.getElementById('session-panel');
    if (!panel) return;
    sessionPanelOpen = !sessionPanelOpen;
    panel.classList.toggle('hidden', !sessionPanelOpen);
    if (sessionPanelOpen) {
        _showSessionOverlay();
    } else {
        _hideSessionOverlay();
    }
    _persistPanelState();
    if (sessionPanelOpen) loadSessionList();
}

function openSessionPanel() {
    const panel = document.getElementById('session-panel');
    if (!panel || sessionPanelOpen) return;
    sessionPanelOpen = true;
    panel.classList.remove('hidden');
    _showSessionOverlay();
    _persistPanelState();
    loadSessionList();
}

function _restoreSessionPanel() {
    const panel = document.getElementById('session-panel');
    if (!panel) return;
    if (sessionPanelOpen && !_isMobileView()) {
        panel.classList.remove('hidden');
        _showSessionOverlay();
        loadSessionList();
    } else {
        panel.classList.add('hidden');
        _hideSessionOverlay();
    }
}

// Swap the native `title` for the CSS tooltip so hints appear instantly
// instead of waiting for the browser's built-in delay.
function _setBtnTooltip(el, text) {
    if (!el) return;
    el.setAttribute('data-tooltip', text);
    el.removeAttribute('title');
}

function _applyInputTooltips() {
    const set = (id, key, pos) => {
        const el = document.getElementById(id);
        if (!el) return;
        _setBtnTooltip(el, t(key));
        if (pos) el.setAttribute('data-tooltip-pos', pos);
    };
    set('new-chat-btn', 'tip_new_chat');
    // #clear-context-btn gets a rich hover popover (context-usage chart) instead
    // of the plain text tooltip, so it must not carry a data-tooltip here —
    // otherwise both would pop at once.
    set('attach-btn', 'tip_attach');
    set('steer-btn', 'steer_active');
    set('session-toggle-btn', 'session_history', 'bottom');
    set('workspace-toggle-btn', 'ws_toggle', 'bottom');
    set('timeline-toggle-btn', 'timeline_nav', 'bottom');
    set('team-toggle-btn', 'team_toggle', 'bottom');
    // Optimize / mic buttons carry state-dependent tooltips managed in their
    // own setup, but on language switch we reset them to the idle label so the
    // tooltip follows the current locale.
    set('optimize-btn', 'optimize_idle_title');
    set('mic-btn', 'mic_idle_title');
    // Send button only carries a tooltip while it acts as the cancel button.
    _setBtnTooltip(sendBtn, sendBtnMode === 'cancel' ? t('tip_cancel') : '');
    // The permission / model chips carry translated labels and tooltips, so they
    // are repainted here too (this runs on every language switch).
    _renderPermissionChip();
    _renderModelChip();
    // applyI18n resets the placeholder to the solo hint via data-i18n-placeholder,
    // so re-apply the team-aware variant for group conversations.
    _renderInputPlaceholder();
}

// A session that exists in the browser but not yet in the database: the user
// pressed "new chat" and has not sent the first message. Rendered from the same
// path as real sessions so it lands in the right group.
function _addOptimisticSessionItem(sid) {
    const container = document.getElementById('session-list');
    if (!container) return;
    if (_sessionItems.some(s => s.session_id === sid)) return;

    // This runs from a callback, so a chat opened as a group may already have its
    // members by now: seed the faces from them rather than waiting for a change
    // that has already happened.
    const roster = sid === sessionId && _sessCfg ? _rosterFromTeam(_sessCfg.team) : [];

    _sessionItems.unshift({
        session_id: sid,
        title: t('new_chat'),
        last_active: Math.floor(Date.now() / 1000),
        pinned: 0,
        participants: roster.length ? roster : undefined,
        // The fresh session inherits the workspace the selector currently shows.
        project: _wsSelState.current
            ? { path: _wsSelState.current.path, name: _wsSelState.current.name }
            : null,
    });
    _renderSessionList();
}

// The faces a conversation's entry shows, in the same shape and order the API
// sends: owner first, deduped. Only a real group gets faces, so a conversation
// down to its owner alone reads as the ordinary chat it is.
function _rosterFromTeam(team) {
    const roster = [];
    if (!team) return roster;
    [team.owner].concat(team.members || []).forEach(m => {
        if (m && m.id && !roster.some(a => a.id === m.id)) {
            roster.push({ id: m.id, name: m.name, avatar: m.avatar || '' });
        }
    });
    return roster.length > 1 ? roster : [];
}

/**
 * Record who is in a conversation, so its list entry shows their faces.
 *
 * An entry carries its roster once the conversation is in the database; until the
 * first message only the browser knows a chat was opened as a group, and without
 * this it reads as an ordinary empty one.
 */
function setSessionParticipants(sid, team) {
    const entry = _sessionItems.find(s => s.session_id === sid);
    if (!entry) return;
    const roster = _rosterFromTeam(team);
    if (roster.length) entry.participants = roster;
    else delete entry.participants;
    _renderSessionList();
}

function _sessionTimeGroup(ts) {
    const now = new Date();
    const d = new Date(ts * 1000);
    const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    const yesterday = new Date(today); yesterday.setDate(today.getDate() - 1);
    if (d >= today) return t('today');
    if (d >= yesterday) return t('yesterday');
    return t('earlier');
}

let _sessionPage = 1;
let _sessionHasMore = false;
let _sessionLoading = false;
const _SESSION_PAGE_SIZE = 50;

// Every session loaded so far, in backend order (pinned first, then recency).
// Kept as data rather than only as DOM because grouping by project reorders the
// whole list, which cannot be done by appending page by page.
let _sessionItems = [];
// 'time' (今天/昨天/更早, the behavior before projects existed) or 'project'.
// The backend decides, based on how many spaces are in use across all sessions.
let _sessionGroupMode = 'time';
// User-chosen order of project spaces (paths + '__default__'), from the backend.
let _projectOrder = [];
// Sentinel the backend uses for the default workspace in the ordering.
const DEFAULT_SPACE_KEY = '__default__';

// Which project groups are collapsed, persisted per-browser so the choice
// survives reloads. Keyed by space key (project path or the default sentinel).
const _COLLAPSED_KEY = 'cow_collapsed_projects';
function _loadCollapsed() {
    try { return new Set(JSON.parse(localStorage.getItem(_COLLAPSED_KEY) || '[]')); }
    catch (e) { return new Set(); }
}
function _saveCollapsed(set) {
    try { localStorage.setItem(_COLLAPSED_KEY, JSON.stringify([...set])); } catch (e) {}
}
let _collapsedProjects = _loadCollapsed();

function loadSessionList(onDone) {
    const container = document.getElementById('session-list');
    if (!container) return;

    _sessionPage = 1;
    _sessionHasMore = false;

    _fetchSessionPage(1, true, onDone);
}

function _fetchSessionPage(page, clear, onDone) {
    if (_sessionLoading) return;
    _sessionLoading = true;

    const container = document.getElementById('session-list');
    if (!container) { _sessionLoading = false; return; }

    fetch(`/api/sessions?page=${page}&page_size=${_SESSION_PAGE_SIZE}&scope=all`)
        .then(r => r.json())
        .then(data => {
            _sessionLoading = false;
            if (data.status !== 'success') return;

            if (clear) _sessionItems = [];

            const sessions = data.sessions || [];
            _sessionPage = page;
            _sessionHasMore = !!data.has_more;
            _sessionGroupMode = data.group_mode === 'project' ? 'project' : 'time';
            if (Array.isArray(data.project_order)) _projectOrder = data.project_order;

            const sessionKey = s => `${(s.agent && s.agent.id) || ''}::${s.session_id}`;
            const seen = new Set(_sessionItems.map(sessionKey));
            sessions.forEach(s => {
                const key = sessionKey(s);
                if (seen.has(key)) return;
                seen.add(key);
                _sessionItems.push(s);
            });

            _renderSessionList();
            if (typeof onDone === 'function') onDone();
        })
        .catch(() => { _sessionLoading = false; });
}

// Split the loaded sessions into ordered, labelled groups.
//
// Time mode keeps the original today/yesterday/earlier buckets, with one
// addition: pinned conversations move into a group of their own at the top,
// because a pin that stayed inside its date bucket would not be findable.
// Project mode groups by workspace instead, and pins float to the top of their
// own project - that is where the user filed them.
function _sessionGroups() {
    const groups = [];
    const bucket = (key, label, icon, hint, isProject) => {
        let g = groups.find(x => x.key === key);
        if (!g) { g = { key, label, icon, hint, isProject, items: [] }; groups.push(g); }
        return g;
    };

    if (_sessionGroupMode === 'project') {
        // `_sessionItems` is already pinned-first / newest-first, so appending in
        // order gives each project the same ordering for free.
        _sessionItems.forEach(s => {
            const key = s.project ? s.project.path : DEFAULT_SPACE_KEY;
            const name = s.project ? s.project.name : t('ws_default_workspace');
            const icon = s.project ? 'fa-folder' : 'fa-house';
            bucket(key, name, icon, s.project ? s.project.path : '', !!s.project).items.push(s);
        });
        // Sort groups by the user's chosen order; spaces without a saved
        // position keep their natural (recency) order after the ordered ones.
        if (_projectOrder.length) {
            const rank = new Map(_projectOrder.map((k, i) => [k, i]));
            groups.sort((a, b) => {
                const ra = rank.has(a.key) ? rank.get(a.key) : Infinity;
                const rb = rank.has(b.key) ? rank.get(b.key) : Infinity;
                return ra - rb;
            });
        }
        return groups;
    }

    const pinned = _sessionItems.filter(s => s.pinned);
    if (pinned.length) {
        bucket('__pinned__', t('session_pinned_group'), 'fa-thumbtack', '', false).items.push(...pinned);
    }
    _sessionItems.filter(s => !s.pinned).forEach(s => {
        const label = _sessionTimeGroup(s.last_active);
        bucket('time:' + label, label, '', '', false).items.push(s);
    });
    return groups;
}

function _renderSessionList() {
    const container = document.getElementById('session-list');
    if (!container) return;

    if (!_sessionItems.length) {
        container.innerHTML = '<div class="session-empty">' + t('untitled_session') + '</div>';
        return;
    }

    container.innerHTML = '';
    const projectMode = _sessionGroupMode === 'project';
    // Indent sessions under their project header when several projects are
    // shown, so the list reads as a tree aligned to the folder icon above.
    const indentItems = projectMode && _sessionGroups().length > 1;
    _sessionGroups().forEach(group => {
        const collapsed = projectMode && _collapsedProjects.has(group.key);
        const header = document.createElement('div');
        header.className = 'session-group-label' + (projectMode ? ' session-group-project' : '');
        if (group.hint) header.title = group.hint;

        if (projectMode) {
            // A collapsible, draggable project header. The default space has no
            // rename/delete actions (there is no record to edit) but still drags.
            header.draggable = true;
            header.dataset.spaceKey = group.key;
            const isDefault = group.key === DEFAULT_SPACE_KEY;
            const actions = isDefault ? '' : `
                <button class="session-group-action" title="${escapeHtml(t('project_rename'))}"
                        onclick="event.stopPropagation(); renameProject('${_wsAttr(group.key)}','${_wsAttr(group.label)}')">
                    <i class="fas fa-pen"></i>
                </button>
                <button class="session-group-action" title="${escapeHtml(t('project_delete'))}"
                        onclick="event.stopPropagation(); deleteProject('${_wsAttr(group.key)}','${_wsAttr(group.label)}')">
                    <i class="fas fa-trash-can"></i>
                </button>`;
            header.innerHTML = `
                <i class="fas fa-chevron-down session-group-caret ${collapsed ? 'collapsed' : ''}"></i>
                <i class="fas ${group.icon} session-group-icon"></i>
                <span class="session-group-name">${escapeHtml(group.label)}</span>
                <span class="session-group-count">${group.items.length}</span>
                <span class="session-group-actions">${actions}</span>`;
            header.addEventListener('click', () => _toggleProjectCollapse(group.key));
            _wireGroupDrag(header, group.key);
        } else if (group.icon) {
            header.innerHTML = `<i class="fas ${group.icon}"></i><span>${escapeHtml(group.label)}</span>`;
        } else {
            header.textContent = group.label;
        }
        container.appendChild(header);

        if (!collapsed) {
            group.items.forEach(s => container.appendChild(_sessionItemEl(s, indentItems)));
        }
    });
}

function _toggleProjectCollapse(key) {
    if (_collapsedProjects.has(key)) _collapsedProjects.delete(key);
    else _collapsedProjects.add(key);
    _saveCollapsed(_collapsedProjects);
    _renderSessionList();
}

// --- Project group drag-to-reorder -------------------------------------------
let _dragSpaceKey = null;

function _wireGroupDrag(header, key) {
    header.addEventListener('dragstart', (e) => {
        _dragSpaceKey = key;
        header.classList.add('dragging');
        try { e.dataTransfer.effectAllowed = 'move'; e.dataTransfer.setData('text/plain', key); } catch (err) {}
    });
    header.addEventListener('dragend', () => {
        _dragSpaceKey = null;
        header.classList.remove('dragging');
        document.querySelectorAll('.session-group-project.drop-target')
            .forEach(el => el.classList.remove('drop-target'));
    });
    header.addEventListener('dragover', (e) => {
        if (_dragSpaceKey === null || _dragSpaceKey === key) return;
        e.preventDefault();
        header.classList.add('drop-target');
    });
    header.addEventListener('dragleave', () => header.classList.remove('drop-target'));
    header.addEventListener('drop', (e) => {
        e.preventDefault();
        header.classList.remove('drop-target');
        if (_dragSpaceKey === null || _dragSpaceKey === key) return;
        _reorderSpace(_dragSpaceKey, key);
    });
}

// Move `fromKey` to sit just before `beforeKey`, then persist the new order.
function _reorderSpace(fromKey, beforeKey) {
    // Start from the currently displayed group order so dragging is stable even
    // when some spaces have no saved position yet.
    const current = _sessionGroups().map(g => g.key);
    const order = current.filter(k => k !== fromKey);
    const idx = order.indexOf(beforeKey);
    if (idx < 0) order.push(fromKey);
    else order.splice(idx, 0, fromKey);

    _projectOrder = order;
    _renderSessionList();

    fetch('/api/projects/order', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ order }),
    }).catch(() => {});
}

// Rename a project (display name only; the folder on disk is untouched).
function renameProject(path, currentName) {
    showPromptModal(t('project_rename_title'), currentName, (name) => {
        if (name === null) return;
        fetch('/api/projects/manage', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ path, name }),
        })
            .then(r => r.json())
            .then(data => {
                if (data.status !== 'success') { _wsToast(data.message || t('session_settings_failed')); return; }
                loadSessionList();
            })
            .catch(() => _wsToast(t('session_settings_failed')));
    });
}

// Delete a project record. Only the CowAgent record is removed; files stay and
// bound sessions revert to the default workspace.
function deleteProject(path, name) {
    showConfirmModal(
        t('project_delete_title'),
        t('project_delete_confirm').replace('{name}', name || path),
        () => {
            fetch('/api/projects/manage', {
                method: 'DELETE',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ path }),
            })
                .then(r => r.json())
                .then(data => {
                    if (data.status !== 'success') { _wsToast(data.message || t('session_settings_failed')); return; }
                    loadSessionList();
                })
                .catch(() => _wsToast(t('session_settings_failed')));
        }
    );
}

function _sessionItemEl(s, indent) {
    const item = document.createElement('div');
    const ownerId = (s.agent && s.agent.id) || '';
    const isActive = s.session_id === sessionId && (!ownerId || ownerId === activeAgentId);
    item.className = 'session-item' + (isActive ? ' active' : '') + (s.pinned ? ' pinned' : '')
        + (indent ? ' session-item-indent' : '');
    item.dataset.sessionId = s.session_id;
    if (ownerId) item.dataset.agentId = ownerId;

    const title = s.title || t('untitled_session');
    const sid = _wsAttr(s.session_id);
    const owner = ownerId ? _wsAttr(ownerId) : '';
    // Faces mark a conversation that has several Agents in it, the way a group
    // chat is distinguishable from a direct one. A conversation with a single
    // Agent stays a plain row, whatever the roster looks like elsewhere. We show
    // at most three overlapping faces to keep the row tidy; when more took part,
    // a small "+N" caps the stack so the group's size is still legible.
    const roster = s.participants || [];
    const crowd = roster.length > 1 ? roster.slice(0, 3) : null;
    const overflow = roster.length - 3;
    const face = crowd
        ? `<span class="session-faces">${crowd.map(a => agentAvatarHTML(a, 20)).join('')}`
            + (overflow > 0 ? `<span class="session-face-more">+${overflow}</span>` : '')
            + `</span>`
        : `<i class="fas ${s.pinned ? 'fa-thumbtack' : 'fa-message'} session-icon"></i>`;
    item.innerHTML = `
        ${face}
        <span class="session-title" title="${escapeHtml(title)}">${escapeHtml(title)}</span>
        <button class="session-pin" onclick="event.stopPropagation(); toggleSessionPin('${sid}', '${owner}')"
                title="${escapeHtml(t(s.pinned ? 'unpin_session' : 'pin_session'))}">
            <i class="fas fa-thumbtack"></i>
        </button>
        <button class="session-rename" onclick="event.stopPropagation(); renameSession('${sid}')" title="${escapeHtml(t('rename_session'))}">
            <i class="fas fa-pen"></i>
        </button>
        <button class="session-delete" onclick="event.stopPropagation(); deleteSession('${sid}', '${owner}')" title="Delete">
            <i class="fas fa-trash-can"></i>
        </button>
    `;
    item.addEventListener('click', () => switchSession(s.session_id, ownerId || undefined));
    return item;
}

// Pin / unpin, then re-render so the conversation moves to its new place.
// Reorder loaded sessions to match the backend's ordering (pinned first, then
// most-recently-active), so an optimistic pin/unpin lands in the right place
// without waiting for a reload. Stable within each bucket.
function _sortSessionItems() {
    _sessionItems.sort((a, b) => {
        const pa = a.pinned ? 1 : 0;
        const pb = b.pinned ? 1 : 0;
        if (pa !== pb) return pb - pa;
        return (b.last_active || 0) - (a.last_active || 0);
    });
}

function toggleSessionPin(sid, agentId) {
    const entry = _sessionItems.find(s => s.session_id === sid && (!agentId || (s.agent && s.agent.id) === agentId));
    if (!entry) return;
    const pinned = !entry.pinned;

    // Move it optimistically: the reorder is the whole point of the click, and
    // the list is re-rendered from this same data anyway. Pinning must also
    // reorder `_sessionItems` — the group renderer relies on the array already
    // being pinned-first, so flipping only the flag would leave a just-pinned
    // chat sitting in place (especially inside a project group).
    entry.pinned = pinned ? 1 : 0;
    _sortSessionItems();
    _renderSessionList();

    const owner = agentId || (entry.agent && entry.agent.id) || activeAgentId;
    fetch(`/api/sessions/${encodeURIComponent(sid)}?agent_id=${encodeURIComponent(owner || '')}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ pinned, agent_id: owner }),
    })
        .then(r => r.json())
        .then(data => {
            if (data.status === 'success') return;
            // Most often an empty brand-new chat: it has no row to pin until the
            // first message is stored.
            _wsToast(data.message || t('session_settings_failed'));
            entry.pinned = pinned ? 0 : 1;
            _sortSessionItems();
            _renderSessionList();
        })
        .catch(() => {
            entry.pinned = pinned ? 0 : 1;
            _sortSessionItems();
            _renderSessionList();
        });
}

function _onSessionListScroll() {
    if (!_sessionHasMore || _sessionLoading) return;
    const container = document.getElementById('session-list');
    if (!container) return;
    // Trigger when scrolled near the bottom (within 60px)
    if (container.scrollHeight - container.scrollTop - container.clientHeight < 60) {
        _fetchSessionPage(_sessionPage + 1, false);
    }
}

// Attach scroll listener once DOM is ready
(function _initSessionScroll() {
    const el = document.getElementById('session-list');
    if (el) {
        el.addEventListener('scroll', _onSessionListScroll);
    } else {
        document.addEventListener('DOMContentLoaded', () => {
            const el2 = document.getElementById('session-list');
            if (el2) el2.addEventListener('scroll', _onSessionListScroll);
        });
    }
})();

// Returning to a session whose reply is still streaming in the background.
// Close the background EventSource, rebuild the bubble from the buffered
// events (snapshot), then resume live streaming via a fresh connection that
// reads the remaining tail from the backend replay log. Returns true if a stream
// was re-attached. The user's own bubble is already in history (persisted
// eagerly), so it was rendered by loadHistory before this runs.
function _reattachStream(sid) {
    const key = runtimeSessionKey(sid);
    const requestId = sessionActiveRequest[key];
    if (!requestId) return false;
    const buffer = streamBuffers[requestId];
    if (!buffer) return false;

    // If the buffered stream already finished, the assistant reply is already
    // persisted and rendered by loadHistory — re-attaching would duplicate it.
    // Just clean up the buffer/cursor and rely on history.
    const finished = buffer.items.some(
        it => it.type === 'stream_end' || it.type === 'error' || it.type === 'resync_required'
    );
    if (finished) {
        const oldEs = activeStreams[requestId];
        if (oldEs) { try { oldEs.close(); } catch (_) {} delete activeStreams[requestId]; }
        delete streamBuffers[requestId];
        delete sessionActiveRequest[key];
        resetSendBtnSendMode();
        return false;
    }

    // done already exists in persistent history. Keep the background tail
    // connected for voice_attach/stream_end, but do not replay the answer into
    // the freshly loaded history view or it would create a duplicate bubble.
    if (buffer.items.some(it => it.type === 'done')) {
        resetSendBtnSendMode();
        return false;
    }

    // Stop the background connection before rebuilding. Each new connection
    // resumes independently from its last accepted sequence number.
    const oldEs = activeStreams[requestId];
    if (oldEs) { try { oldEs.close(); } catch (_) {} delete activeStreams[requestId]; }

    // Snapshot the buffered events into the replay, then start a fresh stream
    // that replays them and reconnects for the live tail.
    const replay = buffer.items.slice();
    startSSE(requestId, null, buffer.timestamp || new Date(), null, replay);
    return true;
}

function switchSession(newSessionId, agentId) {
    if (agentId && agentId !== activeAgentId) {
        activeAgentId = agentId;
        localStorage.setItem('cow_active_agent', activeAgentId);
    }
    if (newSessionId === sessionId) {
        if (currentView !== 'chat') navigateTo('chat');
        renderComposerIdentity();
        return;
    }

    // The preview panel is scoped to a session's workspace, so switching tears
    // down an open editor. Settle unsaved edits before committing to the switch.
    if (typeof wsGuardUnsaved === 'function'
        && !wsGuardUnsaved(() => switchSession(newSessionId))) return;

    // Do NOT close active streams here: sessions run in parallel, so any
    // in-flight reply for another session must keep streaming in the
    // background (it self-guards against rendering into the foreign view).
    // Switching back re-attaches and resumes live streaming.

    sessionId = newSessionId;
    updateEditButtonsState();
    localStorage.setItem(activeSessionStorageKey(), sessionId);
    refreshWorkspaceSelector();
    refreshSessionSettings();
    // Whatever the team panel shows describes the previous conversation;
    // team-panel.js drops it and re-opens once the new settings arrive.
    if (typeof teamOnSessionSwitch === 'function') teamOnSessionSwitch();
    // Same for the member columns: what is on screen belongs to the previous
    // conversation; the new session's settings re-organize them.
    if (typeof teamColumnsOnSessionSwitch === 'function') teamColumnsOnSessionSwitch();
    // Reflect the new session's context in the mini pie right away.
    if (typeof _ctxRefresh === 'function') { try { _ctxRefresh({}); } catch (_) {} }
    // Reset the file/preview panel so it reflects the new session's root.
    if (typeof wsOnSessionSwitch === 'function') wsOnSessionSwitch();

    historyPage = 0;
    historyHasMore = false;
    historyLoading = false;

    messagesDiv.innerHTML = '';
    if (typeof resetTimeline === 'function') resetTimeline();
    loadHistory(1);
    startPolling();

    // Restore the send button to match this session's stream state, and if a
    // reply is still streaming in the background, re-attach to resume showing
    // it live (the user turn itself comes from history above).
    const pendingReq = sessionActiveRequest[runtimeSessionKey(sessionId)];
    if (pendingReq) {
        setSendBtnCancelMode(pendingReq);
        _reattachStream(sessionId);
    } else {
        resetSendBtnSendMode();
    }

    document.querySelectorAll('.session-item').forEach(el => {
        el.classList.toggle('active', el.dataset.sessionId === sessionId);
    });

    if (_isMobileView()) closeSessionPanel();
    if (currentView !== 'chat') navigateTo('chat');
    renderComposerIdentity();
}

// In-place rename a session title: replace the title <span> with an <input>,
// commit on Enter/blur, cancel on Escape. Persists via PUT /api/sessions/<id>.
function renameSession(sid) {
    const item = document.querySelector(`.session-item[data-session-id="${sid}"]`);
    if (!item) return;
    const titleEl = item.querySelector('.session-title');
    if (!titleEl || item.querySelector('.session-title-input')) return;

    const oldTitle = titleEl.textContent;

    const input = document.createElement('input');
    input.type = 'text';
    input.className = 'session-title-input';
    input.value = oldTitle;
    input.maxLength = 100;

    // Avoid switching session while interacting with the input
    const stop = e => e.stopPropagation();
    input.addEventListener('click', stop);
    input.addEventListener('mousedown', stop);

    titleEl.replaceWith(input);
    input.focus();
    input.select();

    let done = false;

    const restore = (title) => {
        if (done) return;
        done = true;
        const span = document.createElement('span');
        span.className = 'session-title';
        span.title = title;
        span.textContent = title;
        input.replaceWith(span);
    };

    // Undo the optimistic rename in both the DOM and the cached entry.
    const revert = () => {
        const cachedEntry = _sessionItems.find(s => s.session_id === sid);
        if (cachedEntry) cachedEntry.title = oldTitle;
        const span = item.querySelector('.session-title');
        if (span) {
            span.title = oldTitle;
            span.textContent = oldTitle;
        }
    };

    const commit = () => {
        if (done) return;
        const newTitle = input.value.trim();
        if (!newTitle || newTitle === oldTitle) {
            restore(oldTitle);
            return;
        }
        // Optimistically show the new title, then persist. The cached entry is
        // updated too, or the next re-render (a pin, say) would revive the old one.
        restore(newTitle);
        const cached = _sessionItems.find(s => s.session_id === sid);
        if (cached) cached.title = newTitle;
        fetch(`/api/sessions/${encodeURIComponent(sid)}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ title: newTitle })
        })
            .then(r => r.json())
            .then(data => {
                if (data.status !== 'success') revert();
            })
            .catch(revert);
    };

    input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') { e.preventDefault(); commit(); }
        else if (e.key === 'Escape') { e.preventDefault(); restore(oldTitle); }
    });
    input.addEventListener('blur', commit);
}

function deleteSession(sid, agentId) {
    showConfirmModal(t('delete_session_title'), t('delete_session_confirm'), () => {
        const owner = agentId || activeAgentId;
        const deletingCurrent = sid === sessionId && (!owner || owner === activeAgentId);
        const next = deletingCurrent ? _findNextSession(sid, owner) : null;

        fetch(`/api/sessions/${encodeURIComponent(sid)}?agent_id=${encodeURIComponent(owner || '')}`, { method: 'DELETE' })
            .then(r => r.json())
            .then(data => {
                if (data.status !== 'success') return;
                if (!deletingCurrent) {
                    loadSessionList();
                    return;
                }
                if (next) {
                    switchSession(next.sessionId, next.agentId);
                    loadSessionList();
                } else {
                    newChat(false);
                }
            })
            .catch(() => {});
    });
}

// Pick the session to show after deleting `sid` (the current session): prefer
// the next item below it in the list, otherwise the previous one. Returns null
// if no other session exists.
function _findNextSession(sid, agentId) {
    const items = Array.from(document.querySelectorAll('.session-item[data-session-id]'));
    const same = el => el.dataset.sessionId === sid && (!agentId || el.dataset.agentId === agentId);
    const idx = items.findIndex(same);
    const pick = el => el ? { sessionId: el.dataset.sessionId, agentId: el.dataset.agentId || '' } : null;
    if (idx === -1) {
        return pick(items.find(el => !same(el)));
    }
    return pick(items[idx + 1] || items[idx - 1]);
}

function showConfirmModal(title, message, onConfirm) {
    let overlay = document.getElementById('confirm-modal-overlay');
    if (overlay) overlay.remove();

    overlay = document.createElement('div');
    overlay.id = 'confirm-modal-overlay';
    overlay.className = 'confirm-overlay';

    const modal = document.createElement('div');
    modal.className = 'confirm-modal';
    modal.innerHTML = `
        <div class="confirm-title">${escapeHtml(title)}</div>
        <div class="confirm-message">${escapeHtml(message)}</div>
        <div class="confirm-actions">
            <button class="confirm-btn confirm-btn-cancel">${t('confirm_cancel')}</button>
            <button class="confirm-btn confirm-btn-ok">${t('confirm_yes')}</button>
        </div>
    `;
    overlay.appendChild(modal);
    document.body.appendChild(overlay);

    requestAnimationFrame(() => overlay.classList.add('visible'));

    const close = () => {
        overlay.classList.remove('visible');
        setTimeout(() => overlay.remove(), 200);
    };

    overlay.addEventListener('click', (e) => { if (e.target === overlay) close(); });
    modal.querySelector('.confirm-btn-cancel').addEventListener('click', close);
    modal.querySelector('.confirm-btn-ok').addEventListener('click', () => {
        close();
        onConfirm();
    });
}

// A confirm modal with a single text input. Calls onSubmit(value) on OK, and
// does nothing on cancel. Mirrors showConfirmModal's look and lifecycle.
function showPromptModal(title, initialValue, onSubmit) {
    let overlay = document.getElementById('confirm-modal-overlay');
    if (overlay) overlay.remove();

    overlay = document.createElement('div');
    overlay.id = 'confirm-modal-overlay';
    overlay.className = 'confirm-overlay';

    const modal = document.createElement('div');
    modal.className = 'confirm-modal';
    modal.innerHTML = `
        <div class="confirm-title">${escapeHtml(title)}</div>
        <input type="text" class="prompt-modal-input" maxlength="100" />
        <div class="confirm-actions">
            <button class="confirm-btn confirm-btn-cancel">${t('confirm_cancel')}</button>
            <button class="confirm-btn confirm-btn-ok">${t('confirm_yes')}</button>
        </div>
    `;
    overlay.appendChild(modal);
    document.body.appendChild(overlay);

    const input = modal.querySelector('.prompt-modal-input');
    input.value = initialValue || '';
    requestAnimationFrame(() => { overlay.classList.add('visible'); input.focus(); input.select(); });

    const close = () => {
        overlay.classList.remove('visible');
        setTimeout(() => overlay.remove(), 200);
    };
    const submit = () => { const v = input.value.trim(); close(); onSubmit(v); };

    overlay.addEventListener('click', (e) => { if (e.target === overlay) close(); });
    modal.querySelector('.confirm-btn-cancel').addEventListener('click', close);
    modal.querySelector('.confirm-btn-ok').addEventListener('click', submit);
    input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') { e.preventDefault(); submit(); }
        else if (e.key === 'Escape') { e.preventDefault(); close(); }
    });
}

function clearContext() {
    fetch(`/api/sessions/${encodeURIComponent(sessionId)}/clear_context`, { method: 'POST' })
        .then(r => r.json())
        .then(data => {
            if (data.status !== 'success') return;
            // Insert a visual divider in the chat
            const divider = document.createElement('div');
            divider.className = 'context-divider';
            divider.innerHTML = `<span>${t('context_cleared')}</span>`;
            messagesDiv.appendChild(divider);
            scrollChatToBottom();
        })
        .catch(() => {});
}

function generateSessionTitle(sid, userMsg, assistantReply) {
    fetch(`/api/sessions/${encodeURIComponent(sid)}/generate_title`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_message: userMsg, assistant_reply: assistantReply }),
    })
        .then(r => r.json())
        .then(data => {
            if (data.status === 'success' && sessionPanelOpen) {
                loadSessionList();
            }
        })
        .catch(() => {});
}

