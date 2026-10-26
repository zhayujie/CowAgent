/* Background task board: lanes by state, create / detail dialogs and the
   approval-rule editor. Lives in the Tasks view next to the scheduled-task
   list. These are classic scripts sharing one global scope; see
   channel/web/README.md before changing the load order. */

// Whether background tasks are on. Cached so a reload can draw the board tab
// before the first summary arrives; approvals.js keeps it current.
var taskFeatureEnabled = localStorage.getItem('cow_task_enabled') === '1';

const BOARD_LANES = [
    { key: 'queued',  statuses: ['queued'],              label: 'board_lane_queued',  dot: 'dot-queued' },
    { key: 'running', statuses: ['running'],             label: 'board_lane_running', dot: 'dot-running' },
    { key: 'waiting', statuses: ['waiting'],             label: 'board_lane_waiting', dot: 'dot-waiting' },
    { key: 'done',    statuses: ['done'],                label: 'board_lane_done',    dot: 'dot-done',   days: 7 },
    { key: 'failed',  statuses: ['failed', 'cancelled'], label: 'board_lane_failed',  dot: 'dot-failed', days: 30 },
];
// Finished lanes grow forever. The board keeps the recent end of them (a
// failure stays on longer than a success, it still wants a look) and the
// all-tasks list holds the rest.
const BOARD_FINISHED_LIMIT = 30;

let boardTasks = [];
let boardCounts = {};
let boardApprovals = [];
let boardSettings = null;
let boardLoading = false;
let boardRefreshTimer = null;

function setTaskFeatureEnabled(enabled) {
    enabled = !!enabled;
    const changed = enabled !== taskFeatureEnabled;
    taskFeatureEnabled = enabled;
    try { localStorage.setItem('cow_task_enabled', enabled ? '1' : '0'); } catch (_) { /* private mode */ }
    const tab = document.getElementById('tasks-tab-board');
    if (tab) tab.classList.toggle('hidden', !enabled);
    const bell = document.getElementById('approval-bell');
    if (bell) bell.classList.toggle('hidden', !enabled);
    relabelTasksView(enabled);
    if (!changed || typeof currentView === 'undefined' || currentView !== 'tasks') return;
    if (!enabled && tasksActiveTab === 'board') switchTasksTab('tasks');
    // Landed before we knew the board exists: on /scheduler/board, or on the
    // view itself with no tab named, the board is where it should have opened.
    if (enabled && tasksActiveTab !== 'board') {
        const named = typeof _routeParse === 'function' ? _routeParse(location.pathname).tab : '';
        if (!named || named === 'board') switchTasksTab('board');
    }
}

// Off, the Tasks view is the scheduler it always was; on, it holds the board
// as well, and its menu entry, title and tabs say so.
function relabelTasksView(enabled) {
    const relabel = (el, key) => {
        if (!el) return;
        el.dataset.i18n = key;
        el.textContent = t(key);
    };
    MENU_BUILTINS.tasks.icon = enabled ? 'fa-list-check' : 'fa-clock';
    MENU_BUILTINS.tasks.label = enabled ? 'menu_tasks_all' : 'menu_tasks';
    VIEW_META.tasks.page = MENU_BUILTINS.tasks.label;
    if (currentView === 'tasks') relabel(document.getElementById('breadcrumb-page'), VIEW_META.tasks.page);
    document.querySelectorAll('.sidebar-item[data-view="tasks"]').forEach(item => {
        const icon = item.querySelector('.item-icon');
        // A user-picked icon stays.
        if (icon && (icon.classList.contains('fa-clock') || icon.classList.contains('fa-list-check'))) {
            icon.classList.toggle('fa-clock', !enabled);
            icon.classList.toggle('fa-list-check', enabled);
        }
        relabel(item.querySelector('[data-i18n]'), MENU_BUILTINS.tasks.label);
    });
    relabel(document.getElementById('tasks-title'), enabled ? 'tasks_title_all' : 'tasks_title');
    relabel(document.querySelector('#tasks-tab-tasks [data-i18n]'), enabled ? 'tasks_tab_scheduled' : 'tasks_tab_tasks');
    if (typeof syncSidebarTips === 'function') syncSidebarTips();
}

// ---- Data -----------------------------------------------------------------

function boardFetchJSON(url, options) {
    return fetch(url, options).then(r => r.json()).then(data => {
        if (!data || data.status !== 'success') throw new Error((data && data.message) || 'request failed');
        return data;
    });
}

function loadTaskBoard() {
    if (!taskFeatureEnabled || boardLoading) return;
    boardLoading = true;
    const rosterReady = agentCatalog.length ? Promise.resolve() : loadAgentCatalog();
    rosterReady.then(() => Promise.all([
        boardFetchJSON('/api/tasks?agent_id=&limit=300'),
        boardFetchJSON('/api/approvals?status=pending&agent_id='),
        boardSettings ? Promise.resolve({ settings: boardSettings }) : boardFetchJSON('/api/tasks/settings?agent_id=').catch(() => ({ settings: null })),
    ])).then(([taskData, apprData, settingsData]) => {
        boardTasks = taskData.tasks || [];
        boardCounts = taskData.counts || {};
        boardApprovals = apprData.approvals || [];
        if (settingsData.settings) boardSettings = settingsData.settings;
        if (!taskData.enabled) { setTaskFeatureEnabled(false); return; }
        renderTaskBoard();
        if (typeof renderApprovalInbox === 'function') renderApprovalInbox(boardApprovals);
    }).catch(() => {
        const lanes = document.getElementById('board-lanes');
        if (lanes && !lanes.children.length) {
            lanes.innerHTML = `<div class="board-lane-empty">${escapeHtml(t('board_load_failed'))}</div>`;
        }
    }).finally(() => {
        boardLoading = false;
        scheduleBoardRefresh();
    });
}

// Live while the board is on screen: running cards move on their own.
function scheduleBoardRefresh() {
    clearTimeout(boardRefreshTimer);
    if (typeof currentView === 'undefined' || currentView !== 'tasks' || tasksActiveTab !== 'board') return;
    const busy = boardTasks.some(task => task.status === 'running' || task.status === 'queued');
    boardRefreshTimer = setTimeout(() => {
        if (currentView === 'tasks' && tasksActiveTab === 'board' && !document.hidden) loadTaskBoard();
        else scheduleBoardRefresh();
    }, busy ? 4000 : 15000);
}

// ---- Rendering --------------------------------------------------------------

function boardRelTime(sec) {
    if (!sec) return '';
    const diff = Math.max(0, Date.now() / 1000 - sec);
    if (diff < 60) return t('board_time_now');
    if (diff < 3600) return t('board_time_min').replace('{n}', Math.floor(diff / 60));
    if (diff < 86400) return t('board_time_hour').replace('{n}', Math.floor(diff / 3600));
    return new Date(sec * 1000).toLocaleDateString();
}

function boardDuration(start, end) {
    if (!start) return '';
    const s = Math.max(0, Math.round((end || Date.now() / 1000) - start));
    if (s < 60) return `${s}s`;
    const m = Math.floor(s / 60);
    if (m < 60) return `${m}m ${s % 60}s`;
    return `${Math.floor(m / 60)}h ${m % 60}m`;
}

// Cards show a line of a result, so the markdown it is written in is noise.
function boardPlainText(text) {
    return String(text || '')
        .replace(/```[\s\S]*?```/g, ' ')
        .replace(/!\[[^\]]*\]\([^)]*\)/g, ' ')
        .replace(/\[([^\]]*)\]\([^)]*\)/g, '$1')
        .replace(/(^|\s)(#{1,6}|>|[-*+]|\d+\.)\s+/g, '$1')
        .replace(/[*_`~|]+/g, '')
        .replace(/(^|\s)-{3,}(?=\s|$)/g, ' ')
        .replace(/\s+/g, ' ')
        .trim();
}

const BOARD_SOURCES = {
    manual:   ['fa-hand-pointer', 'board_source_manual'],
    chat:     ['fa-comment-dots', 'board_source_chat'],
    schedule: ['fa-clock', 'board_source_schedule'],
};

function boardSourceChip(task) {
    const [icon, key] = BOARD_SOURCES[task.source] || BOARD_SOURCES.manual;
    return `<span class="board-chip"><i class="fas ${icon}"></i>${escapeHtml(t(key))}</span>`;
}

function boardSourceInline(task) {
    const [icon, key] = BOARD_SOURCES[task.source] || BOARD_SOURCES.manual;
    return `<i class="fas ${icon}"></i><span>${escapeHtml(t(key))}</span>`;
}

// Who does the work. Shown on every card, a single-Agent install included:
// the face is what tells a task apart from a scheduled message at a glance.
function boardOwner(agentId) {
    const agent = findAgent(agentId) || findAgent(defaultAgentId);
    const name = agent ? (agent.name || agent.id) : (agentId || '');
    return `<span class="board-card-owner">${agentAvatarHTML(agent, 20)}<span>${escapeHtml(name)}</span></span>`;
}

function renderTaskBoard() {
    const lanesEl = document.getElementById('board-lanes');
    if (!lanesEl) return;
    const approvalsByTask = {};
    const loose = [];
    boardApprovals.forEach(appr => {
        if (appr.task_id) (approvalsByTask[appr.task_id] = approvalsByTask[appr.task_id] || []).push(appr);
        else loose.push(appr);
    });

    lanesEl.innerHTML = '';
    BOARD_LANES.forEach(lane => {
        let items = boardTasks.filter(task => lane.statuses.includes(task.status));
        if (lane.key === 'queued') items = items.slice().reverse();  // oldest runs first
        const finished = !!lane.days;
        if (finished) {
            const since = Date.now() / 1000 - lane.days * 86400;
            items = items.filter(task => (task.finished_at || task.updated_at) >= since);
        }
        const total = items.length + (lane.key === 'waiting' ? loose.length : 0);
        const shown = finished ? items.slice(0, BOARD_FINISHED_LIMIT) : items;
        const allTime = finished ? lane.statuses.reduce((n, st) => n + (boardCounts[st] || 0), 0) : 0;

        const laneEl = document.createElement('section');
        laneEl.className = 'board-lane';
        laneEl.innerHTML = `
            <header class="board-lane-head">
                <span class="board-lane-dot ${lane.dot}"></span>
                <span class="board-lane-title">${escapeHtml(t(lane.label))}</span>
                <span class="board-lane-count${lane.key === 'waiting' && total ? ' is-alert' : ''}">${total}</span>
            </header>
            <div class="board-lane-body"></div>`;
        const body = laneEl.querySelector('.board-lane-body');
        if (lane.key === 'waiting') loose.forEach(appr => body.appendChild(renderLooseApprovalCard(appr)));
        shown.forEach(task => body.appendChild(renderBoardCard(task, approvalsByTask[task.id] || [])));
        if (!total) {
            body.innerHTML = `<div class="board-lane-empty">${escapeHtml(t('board_lane_empty_' + lane.key))}</div>`;
        }
        if (finished && allTime > shown.length) {
            const more = document.createElement('button');
            more.className = 'board-lane-more';
            more.innerHTML = `${escapeHtml(t('board_view_all').replace('{n}', allTime))}<i class="fas fa-arrow-right"></i>`;
            more.addEventListener('click', () => openBoardHistory(lane.statuses.join(',')));
            body.appendChild(more);
        }
        lanesEl.appendChild(laneEl);
    });
    renderBoardSummary();
    updateBoardTabBadge();
}

function renderBoardSummary() {
    const el = document.getElementById('board-summary');
    if (!el || !boardSettings) return;
    const running = boardTasks.filter(task => task.status === 'running').length;
    const rules = (boardSettings.approval_rules || []).filter(rule => rule.enabled !== false).length;
    el.innerHTML = `
        <span class="board-summary-item"><span class="board-lane-dot dot-running"></span>${escapeHtml(t('board_summary_running'))} <b>${running} / ${boardSettings.max_concurrency}</b></span>
        <span class="board-summary-item"><i class="fas fa-shield-halved text-[11px]"></i>${escapeHtml(t('board_summary_rules'))} <b>${rules}</b></span>
        ${rules ? '' : `<span class="board-summary-link" onclick="openBoardSettingsModal()">${escapeHtml(t('board_summary_add_rule'))}<i class="fas fa-arrow-right text-[10px]"></i></span>`}
        <span class="board-summary-link is-quiet ml-auto" onclick="openBoardHistory()"><i class="fas fa-list-ul text-[10px]"></i>${escapeHtml(t('board_all_tasks'))}</span>`;
}

function updateBoardTabBadge(count) {
    const badge = document.getElementById('board-tab-badge');
    if (!badge) return;
    const n = typeof count === 'number' ? count : boardApprovals.length;
    badge.textContent = n > 99 ? '99+' : String(n);
    badge.classList.toggle('hidden', !n);
}

function boardStatusMarker(status) {
    if (status === 'running') return '<span class="board-card-pulse"></span>';
    const lane = BOARD_LANES.find(l => l.statuses.includes(status)) || BOARD_LANES[0];
    return `<span class="board-card-dot ${status === 'cancelled' ? 'dot-cancelled' : lane.dot}"></span>`;
}

function boardCardSub(task) {
    const sub = [`<span class="board-card-id">#${task.id}</span>`, boardSourceInline(task)];
    if (task.run_count > 1) sub.push(`<span>${escapeHtml(t('board_round').replace('{n}', task.run_count))}</span>`);
    if (task.status === 'cancelled') sub.push(`<span>${escapeHtml(t('board_status_cancelled'))}</span>`);
    return sub;
}

// A card says what the task is, where it stands and who has it. Deciding an
// approval takes the detail dialog or the inbox; a card only flags it.
function renderBoardCard(task, approvals) {
    const card = document.createElement('article');
    const status = task.status;
    const active = status === 'queued' || status === 'running' || status === 'waiting';
    card.className = 'board-card'
        + (status === 'running' ? ' is-running' : '')
        + (status === 'cancelled' ? ' is-muted' : '');
    card.dataset.taskId = task.id;

    const marker = boardStatusMarker(status);
    const sub = boardCardSub(task);

    let callout = '';
    if (status === 'waiting') {
        const accept = task.wait_type === 'accept';
        const what = accept ? '' : approvals.map(a => a.label || a.tool_name).filter(Boolean).join('、');
        const label = t(accept ? 'board_wait_accept' : 'board_wait_approval') + (what ? ` · ${what}` : '');
        callout = `<div class="board-card-callout is-wait"><i class="fas ${accept ? 'fa-clipboard-check' : 'fa-shield-halved'}"></i><span>${escapeHtml(label)}</span></div>`;
    } else if (status === 'failed' && task.error) {
        callout = `<div class="board-card-callout is-error"><i class="fas fa-circle-exclamation"></i><span>${escapeHtml(task.error)}</span></div>`;
    }

    let right;
    if (status === 'running') {
        right = `<span class="board-card-time is-live">${escapeHtml(boardDuration(task.started_at))}</span>`;
    } else if (status === 'waiting' && approvals.length > 1) {
        right = `<span class="board-card-pill">${escapeHtml(t('board_pending_n').replace('{n}', approvals.length))}</span>`;
    } else {
        const when = active ? (task.started_at || task.created_at) : (task.finished_at || task.updated_at);
        right = `<span class="board-card-time">${escapeHtml(boardRelTime(when))}</span>`;
    }

    card.innerHTML = `
        <button class="board-card-action" title="${escapeHtml(t(active ? 'board_cancel_task' : 'board_delete'))}">
            <i class="fas ${active ? 'fa-xmark' : 'fa-trash-can'}"></i>
        </button>
        <div class="board-card-head">${marker}<div class="board-card-title">${escapeHtml(task.title || '')}</div></div>
        <div class="board-card-sub">${sub.join('<span class="sep">·</span>')}</div>
        ${callout}
        <div class="board-card-foot">${boardOwner(task.agent_id)}${right}</div>`;
    card.querySelector('.board-card-action').addEventListener('click', (e) => {
        e.stopPropagation();
        boardTaskAction(active ? 'cancel' : 'delete', task);
    });
    card.addEventListener('click', () => openBoardDetail(task.id));
    return card;
}

function boardApprovalOrigin(appr) {
    return appr.origin_channel === 'web' ? t('board_from_web_chat') : (appr.origin_channel || t('board_from_chat'));
}

// An approval a chat turn is waiting on: no task behind it, so the card stands
// for the approval itself.
function renderLooseApprovalCard(appr) {
    const card = document.createElement('article');
    card.className = 'board-card';
    card.innerHTML = `
        <div class="board-card-head"><span class="board-card-dot dot-waiting"></span><div class="board-card-title">${escapeHtml(appr.label || appr.tool_name || '')}</div></div>
        <div class="board-card-sub"><i class="fas fa-comment-dots"></i><span>${escapeHtml(boardApprovalOrigin(appr))}</span></div>
        <div class="board-card-callout is-wait"><i class="fas fa-shield-halved"></i><span>${escapeHtml(appr.summary || t('board_wait_approval'))}</span></div>
        <div class="board-card-foot">${boardOwner(appr.agent_id)}<span class="board-card-time">${escapeHtml(boardRelTime(appr.created_at))}</span></div>`;
    card.addEventListener('click', () => openApprovalDetail(appr));
    return card;
}

// ---- All tasks ------------------------------------------------------------------

const BOARD_HISTORY_STATUSES = [
    { key: '', label: 'board_filter_all' },
    { key: 'done', label: 'board_lane_done' },
    { key: 'failed,cancelled', label: 'board_lane_failed' },
];
const BOARD_HISTORY_PAGE = 50;
let boardHistory = { status: '', source: '', items: [], total: 0 };
let boardHistorySeq = 0;

function openBoardHistory(status) {
    boardHistory = { status: status || '', source: '', items: [], total: 0 };
    renderBoardHistoryFilters();
    document.getElementById('board-history-list').innerHTML =
        `<div class="py-10 text-center text-slate-400 text-sm"><i class="fas fa-spinner fa-spin mr-2"></i>${escapeHtml(t('board_loading'))}</div>`;
    boardModal('board-history-modal-overlay').classList.remove('hidden');
    loadBoardHistory(true);
}

function boardHistoryIsOpen() {
    const overlay = boardModal('board-history-modal-overlay');
    return overlay && !overlay.classList.contains('hidden');
}

function renderBoardHistoryFilters() {
    const seg = (el, options, current, field) => {
        el.innerHTML = options.map(o =>
            `<button class="board-seg-btn${o.key === current ? ' is-active' : ''}" data-key="${o.key}">${escapeHtml(t(o.label))}</button>`).join('');
        el.querySelectorAll('.board-seg-btn').forEach(btn => btn.addEventListener('click', () => {
            if (boardHistory[field] === btn.dataset.key) return;
            boardHistory[field] = btn.dataset.key;
            renderBoardHistoryFilters();
            loadBoardHistory(true);
        }));
    };
    const sources = [{ key: '', label: 'board_filter_all_sources' }]
        .concat(Object.keys(BOARD_SOURCES).map(key => ({ key, label: BOARD_SOURCES[key][1] })));
    seg(document.getElementById('board-history-state'), BOARD_HISTORY_STATUSES, boardHistory.status, 'status');
    seg(document.getElementById('board-history-source'), sources, boardHistory.source, 'source');
}

function loadBoardHistory(reset) {
    const seq = ++boardHistorySeq;
    const params = new URLSearchParams({
        agent_id: '', limit: String(BOARD_HISTORY_PAGE), offset: String(reset ? 0 : boardHistory.items.length),
        status: boardHistory.status, source: boardHistory.source,
    });
    const moreBtn = document.getElementById('board-history-more');
    if (moreBtn) moreBtn.disabled = true;
    boardFetchJSON(`/api/tasks?${params}`).then(data => {
        if (seq !== boardHistorySeq) return;
        boardHistory.items = (reset ? [] : boardHistory.items).concat(data.tasks || []);
        boardHistory.total = data.total || 0;
        renderBoardHistoryList();
    }).catch(err => {
        if (seq !== boardHistorySeq) return;
        document.getElementById('board-history-list').innerHTML =
            `<div class="bd-box is-error">${escapeHtml(err.message || t('board_load_failed'))}</div>`;
    });
}

function renderBoardHistoryList() {
    const list = document.getElementById('board-history-list');
    document.getElementById('board-history-count').textContent = t('board_history_count').replace('{n}', boardHistory.total);
    if (!boardHistory.items.length) {
        list.innerHTML = `<div class="board-lane-empty mt-2">${escapeHtml(t('board_history_empty'))}</div>`;
        return;
    }
    list.innerHTML = '';
    boardHistory.items.forEach(task => {
        const active = ['queued', 'running', 'waiting'].includes(task.status);
        const when = active ? (task.started_at || task.created_at) : (task.finished_at || task.updated_at);
        const took = !active && task.started_at ? boardDuration(task.started_at, task.finished_at || task.updated_at) : '';
        const row = document.createElement('div');
        row.className = 'board-hrow';
        row.innerHTML = `
            ${boardStatusMarker(task.status)}
            <div class="board-hrow-main">
                <div class="board-hrow-title">${escapeHtml(task.title || '')}</div>
                <div class="board-card-sub">${boardCardSub(task).join('<span class="sep">·</span>')}</div>
            </div>
            <div class="board-hrow-owner">${boardOwner(task.agent_id)}</div>
            <div class="board-hrow-time"><div>${escapeHtml(boardRelTime(when))}</div>${took ? `<div>${escapeHtml(took)}</div>` : ''}</div>`;
        row.addEventListener('click', () => openBoardDetail(task.id));
        list.appendChild(row);
    });
    if (boardHistory.items.length < boardHistory.total) {
        list.insertAdjacentHTML('beforeend',
            `<div class="flex justify-center pt-3"><button id="board-history-more" class="board-btn board-btn-link">${escapeHtml(t('board_load_more'))}</button></div>`);
        document.getElementById('board-history-more').addEventListener('click', () => loadBoardHistory(false));
    }
}

// ---- Create -----------------------------------------------------------------

function boardModal(id) { return document.getElementById(id); }

function closeBoardModal(id) {
    const overlay = boardModal(id);
    if (overlay) overlay.classList.add('hidden');
    if (id === 'board-detail-modal-overlay') stopBoardDetailLive();
}

function openBoardTaskModal(prefill) {
    if (!taskFeatureEnabled) return;
    const overlay = boardModal('board-task-modal-overlay');
    document.getElementById('board-task-prompt').value = (prefill && prefill.prompt) || '';
    document.getElementById('board-task-title').value = (prefill && prefill.title) || '';
    document.getElementById('board-task-accept').checked = false;
    document.getElementById('board-task-status').textContent = '';
    const agentWrap = document.getElementById('board-task-agent-wrap');
    const select = document.getElementById('board-task-agent');
    const agents = (agentCatalog || []).filter(a => a.enabled !== false);
    if (multiAgentMode() && agents.length > 1) {
        select.innerHTML = agents.map(a => `<option value="${escapeHtml(a.id)}">${escapeHtml(a.name || a.id)}</option>`).join('');
        select.value = activeAgentId || defaultAgentId || agents[0].id;
        agentWrap.classList.remove('hidden');
    } else {
        select.innerHTML = '';
        agentWrap.classList.add('hidden');
    }
    overlay.classList.remove('hidden');
    setTimeout(() => document.getElementById('board-task-prompt').focus(), 30);
}

function submitBoardTask() {
    const prompt = document.getElementById('board-task-prompt').value.trim();
    const status = document.getElementById('board-task-status');
    if (!prompt) {
        status.textContent = t('board_prompt_required');
        document.getElementById('board-task-prompt').focus();
        return;
    }
    const btn = document.getElementById('board-task-submit');
    btn.disabled = true;
    const agentId = document.getElementById('board-task-agent').value || activeAgentId || defaultAgentId || '';
    boardFetchJSON('/api/tasks', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            prompt,
            title: document.getElementById('board-task-title').value.trim(),
            require_accept: document.getElementById('board-task-accept').checked,
            agent_id: agentId,
        }),
    }).then(() => {
        closeBoardModal('board-task-modal-overlay');
        loadTaskBoard();
    }).catch(err => {
        status.textContent = err.message || t('board_action_failed');
    }).finally(() => { btn.disabled = false; });
}

function boardTaskAction(action, target) {
    const task = target || boardDetailTask;
    if (!task) return;
    const run = () => boardFetchJSON(`/api/tasks/${task.id}/${action}`, { method: 'POST' })
        .then(() => {
            const detail = boardModal('board-detail-modal-overlay');
            const showing = !detail.classList.contains('hidden') && boardDetailTask && boardDetailTask.id === task.id;
            if (showing && action === 'delete') closeBoardModal('board-detail-modal-overlay');
            else if (showing) refreshBoardDetail(task.id);
            loadTaskBoard();
            if (boardHistoryIsOpen()) loadBoardHistory(true);
        })
        .catch(err => alert(err.message || t('board_action_failed')));
    if (action === 'retry') { run(); return; }
    showConfirmDialog({
        title: t(action === 'delete' ? 'board_delete_confirm_title' : 'board_cancel_confirm_title'),
        message: t(action === 'delete' ? 'board_delete_confirm_msg' : 'board_cancel_confirm_msg'),
        okText: t(action === 'delete' ? 'board_delete' : 'board_cancel_task'),
        onConfirm: run,
    });
}

// ---- Settings: approval rules ---------------------------------------------------

const BOARD_RULE_TEMPLATES = [
    { key: 'board_tpl_git_push', rule: { tool: 'bash', match: 'git\\s+push', action: 'ask' } },
    { key: 'board_tpl_rm', rule: { tool: 'bash', match: '\\brm\\s+-[a-z]*r', action: 'ask' } },
    { key: 'board_tpl_publish', rule: { tool: 'bash', match: '(npm|pnpm|yarn)\\s+publish|twine\\s+upload|docker\\s+push|kubectl\\s+(apply|delete)', action: 'ask' } },
    { key: 'board_tpl_mail', rule: { tool: '*mail*,*email*,*send_message*', match: '', action: 'ask' } },
];

let boardRulesDraft = [];

function openBoardSettingsModal() {
    const overlay = boardModal('board-settings-modal-overlay');
    document.getElementById('board-settings-status').textContent = '';
    boardFetchJSON('/api/tasks/settings?agent_id=').then(data => {
        boardSettings = data.settings;
        boardRulesDraft = (data.settings.approval_rules || []).map(rule => Object.assign({}, rule));
        document.getElementById('board-setting-concurrency').value = data.settings.max_concurrency;
        document.getElementById('board-setting-webhook').value = data.settings.notify_webhook || '';
        renderBoardRuleTemplates();
        renderBoardRules();
        overlay.classList.remove('hidden');
    }).catch(err => alert(err.message || t('board_load_failed')));
}

function renderBoardRuleTemplates() {
    const wrap = document.getElementById('board-rule-templates');
    wrap.innerHTML = BOARD_RULE_TEMPLATES.map((tpl, i) =>
        `<button class="rule-tpl" data-tpl="${i}">+ ${escapeHtml(t(tpl.key))}</button>`).join('');
    wrap.querySelectorAll('[data-tpl]').forEach(btn => btn.addEventListener('click', () => {
        const tpl = BOARD_RULE_TEMPLATES[+btn.dataset.tpl];
        boardRulesDraft.push(Object.assign({ label: t(tpl.key), enabled: true }, tpl.rule));
        renderBoardRules();
    }));
}

function renderBoardRules() {
    const list = document.getElementById('board-rules-list');
    if (!boardRulesDraft.length) {
        list.innerHTML = `<div class="rule-empty">${escapeHtml(t('board_rules_empty'))}</div>`;
        return;
    }
    list.innerHTML = '';
    boardRulesDraft.forEach((rule, idx) => {
        const row = document.createElement('div');
        row.className = 'rule-row' + (rule.enabled === false ? ' is-off' : '');
        row.innerHTML = `
            <div class="rule-row-top">
                <input class="rule-input flex-1" data-field="label" placeholder="${escapeHtml(t('board_rule_label'))}" value="${escapeHtml(rule.label || '')}">
                <div class="rule-seg">
                    <button data-action="ask" class="${rule.action !== 'deny' ? 'active-ask' : ''}">${escapeHtml(t('board_rule_ask'))}</button>
                    <button data-action="deny" class="${rule.action === 'deny' ? 'active-deny' : ''}">${escapeHtml(t('board_rule_deny'))}</button>
                </div>
                <label class="relative inline-flex items-center cursor-pointer flex-shrink-0" title="${escapeHtml(t('board_rule_enabled'))}">
                    <input type="checkbox" data-field="enabled" class="sr-only peer" ${rule.enabled === false ? '' : 'checked'}>
                    <div class="w-9 h-5 bg-slate-200 dark:bg-slate-700 peer-checked:bg-primary-400 rounded-full after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:after:translate-x-full"></div>
                </label>
                <button class="rule-del" title="${escapeHtml(t('board_delete'))}"><i class="fas fa-trash-can text-xs"></i></button>
            </div>
            <div class="rule-row-bottom">
                <input class="rule-input is-mono w-40" data-field="tool" placeholder="${escapeHtml(t('board_rule_tool'))}" value="${escapeHtml(rule.tool || '')}">
                <input class="rule-input is-mono flex-1" data-field="match" placeholder="${escapeHtml(t('board_rule_match'))}" value="${escapeHtml(rule.match || '')}">
            </div>`;
        row.querySelectorAll('input[data-field]').forEach(input => {
            input.addEventListener(input.type === 'checkbox' ? 'change' : 'input', () => {
                rule[input.dataset.field] = input.type === 'checkbox' ? input.checked : input.value;
                if (input.type === 'checkbox') row.classList.toggle('is-off', !input.checked);
            });
        });
        row.querySelectorAll('.rule-seg button').forEach(btn => btn.addEventListener('click', () => {
            rule.action = btn.dataset.action;
            renderBoardRules();
        }));
        row.querySelector('.rule-del').addEventListener('click', () => {
            boardRulesDraft.splice(idx, 1);
            renderBoardRules();
        });
        list.appendChild(row);
    });
}

function saveBoardSettings() {
    const status = document.getElementById('board-settings-status');
    const rules = boardRulesDraft
        .map(rule => Object.assign({}, rule, { tool: (rule.tool || '').trim(), match: (rule.match || '').trim(), label: (rule.label || '').trim() }))
        .filter(rule => rule.tool);
    const btn = document.getElementById('board-settings-save');
    btn.disabled = true;
    boardFetchJSON('/api/tasks/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            approval_rules: rules,
            max_concurrency: parseInt(document.getElementById('board-setting-concurrency').value, 10) || 2,
            notify_webhook: document.getElementById('board-setting-webhook').value.trim(),
        }),
    }).then(data => {
        boardSettings = data.settings;
        closeBoardModal('board-settings-modal-overlay');
        renderBoardSummary();
    }).catch(err => {
        status.className = 'flex-1 text-xs text-red-500';
        status.textContent = err.message || t('board_action_failed');
    }).finally(() => { btn.disabled = false; });
}

// ---- Wiring ------------------------------------------------------------------------

(function wireTaskBoard() {
    ['board-task-modal-overlay', 'board-history-modal-overlay', 'board-detail-modal-overlay', 'board-settings-modal-overlay', 'approval-decide-modal-overlay'].forEach(id => {
        const overlay = document.getElementById(id);
        if (!overlay) return;
        overlay.querySelectorAll('.board-modal-close').forEach(btn => btn.addEventListener('click', () => closeBoardModal(id)));
        overlay.addEventListener('mousedown', (e) => { if (e.target === overlay) closeBoardModal(id); });
    });
    const submit = document.getElementById('board-task-submit');
    if (submit) submit.addEventListener('click', submitBoardTask);
    const prompt = document.getElementById('board-task-prompt');
    if (prompt) prompt.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) submitBoardTask();
    });
    const addRule = document.getElementById('board-rule-add');
    if (addRule) addRule.addEventListener('click', () => {
        boardRulesDraft.push({ tool: '', match: '', action: 'ask', label: '', enabled: true });
        renderBoardRules();
        const inputs = document.querySelectorAll('#board-rules-list input[data-field="label"]');
        if (inputs.length) inputs[inputs.length - 1].focus();
    });
    const save = document.getElementById('board-settings-save');
    if (save) save.addEventListener('click', saveBoardSettings);
    setTaskFeatureEnabled(taskFeatureEnabled);
})();
