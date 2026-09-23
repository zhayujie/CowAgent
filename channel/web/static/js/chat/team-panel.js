/* Team collaboration panel: the current group conversation's mailbox, task
   board and activity feed, read from GET /api/teams/<session_id> — the same
   agent.team_runtime store the team_send / team_inbox / team_task tools write
   during the conversation. The panel is read-only: read receipts stay with
   the tools, exactly like the API it mirrors.
   These are classic scripts sharing one global scope; see channel/web/README.md
   before changing the load order. */

// =====================================================================
// Team Panel
// =====================================================================

// Team state moves on its own (wakes, hand-offs); a slow poll is enough for
// this observer panel and keeps it from fighting the SSE stream for attention.
const TEAM_PANEL_REFRESH_MS = 5000;
const TEAM_PANEL_LIMIT = 100;
const TEAM_PANEL_TABS = ['mailbox', 'tasks', 'activity'];

let teamPanelOpen = false;
let teamPanelTab = 'mailbox';   // mailbox | tasks | activity
let _teamPanelTimer = null;
let _teamPanelSeq = 0;          // newest refresh wins; stale responses are dropped
let _teamPanelData = null;      // last successful GET /api/teams payload
let _teamPanelReopen = false;   // panel was open across a session switch

// Icon + i18n key + colour class per mailbox message type / task status.
// Kept in sync with agent/team_runtime.py (MESSAGE_TYPES / TASK_STATUSES).
const TEAM_MSG_META = {
    info:     { icon: 'fa-circle-info',     key: 'team_msg_info',     cls: 'team-type-info' },
    question: { icon: 'fa-circle-question', key: 'team_msg_question', cls: 'team-type-question' },
    result:   { icon: 'fa-circle-check',    key: 'team_msg_result',   cls: 'team-type-result' },
};
const TEAM_STATUS_META = {
    pending:     { icon: 'fa-hourglass-start', key: 'team_status_pending',     cls: 'team-st-pending' },
    in_progress: { icon: 'fa-spinner',         key: 'team_status_in_progress', cls: 'team-st-inprogress' },
    completed:   { icon: 'fa-circle-check',    key: 'team_status_completed',   cls: 'team-st-completed' },
};
const TEAM_ACTIVITY_ICON = { message: 'fa-comment', task: 'fa-list-check' };

function _teamPanel() { return document.getElementById('team-panel'); }

// The panel only exists for team conversations: a session whose settings
// report at least one member beside the owner. Solo sessions never show it.
function teamPanelAvailable() {
    return !!(_sessCfg && _sessCfg.team
        && Array.isArray(_sessCfg.team.members) && _sessCfg.team.members.length > 0);
}

// Called after every refreshSessionSettings() — the one place that knows the
// current session's roster. Shows the header button for team sessions and
// hides it (plus any open panel) for solo ones.
function updateTeamPanelButton() {
    const btn = document.getElementById('team-toggle-btn');
    const available = teamPanelAvailable();
    if (btn) btn.classList.toggle('hidden', !available);
    if (!available) {
        _teamPanelReopen = false;
        closeTeamPanel();
        return;
    }
    if (_teamPanelReopen) {
        _teamPanelReopen = false;
        openTeamPanel();
    }
}

// A session switch (history panel, new chat) invalidates whatever is on
// screen — it describes the previous conversation. Drop it; when the new
// session's settings arrive, updateTeamPanelButton() reopens the panel if
// that session is still a team.
function teamOnSessionSwitch() {
    _teamPanelData = null;
    _teamPanelSeq++;
    if (teamPanelOpen) {
        closeTeamPanel();
        _teamPanelReopen = true;
    }
}

function toggleTeamPanel() {
    if (!teamPanelAvailable()) return;
    // The panel lives in the chat view; coming from another view, land there first.
    if (currentView !== 'chat' && typeof navigateTo === 'function') navigateTo('chat');
    if (teamPanelOpen) closeTeamPanel(); else openTeamPanel();
}

function openTeamPanel() {
    const panel = _teamPanel();
    if (!panel) return;
    teamPanelOpen = true;
    panel.classList.remove('hidden');
    setTeamPanelTab(teamPanelTab);
    if (!_teamPanelData) {
        // First open (or a fresh session): placeholder until the fetch lands.
        TEAM_PANEL_TABS.forEach(name => {
            const body = document.getElementById('team-body-' + name);
            if (body) body.innerHTML = _teamPanelLoading();
        });
    }
    refreshTeamPanel();
    if (_teamPanelTimer) clearInterval(_teamPanelTimer);
    _teamPanelTimer = setInterval(() => {
        if (teamPanelOpen && !document.hidden) refreshTeamPanel();
    }, TEAM_PANEL_REFRESH_MS);
}

function closeTeamPanel() {
    if (_teamPanelTimer) { clearInterval(_teamPanelTimer); _teamPanelTimer = null; }
    teamPanelOpen = false;
    const panel = _teamPanel();
    if (panel) panel.classList.add('hidden');
}

function setTeamPanelTab(tab) {
    if (!TEAM_PANEL_TABS.includes(tab)) return;
    teamPanelTab = tab;
    TEAM_PANEL_TABS.forEach(name => {
        const tabBtn = document.getElementById('team-tab-' + name);
        if (tabBtn) tabBtn.classList.toggle('active', name === tab);
        const body = document.getElementById('team-body-' + name);
        if (body) body.classList.toggle('active', name === tab);
    });
}

async function refreshTeamPanel() {
    const panel = _teamPanel();
    if (!panel) return;
    const seq = ++_teamPanelSeq;
    try {
        // The global fetch wrapper appends agent_id, so the API resolves the
        // conversation owner exactly like the team tools do.
        const res = await fetch(`/api/teams/${encodeURIComponent(sessionId)}?limit=${TEAM_PANEL_LIMIT}`);
        const data = await res.json();
        if (seq !== _teamPanelSeq || !teamPanelOpen) return;
        if (!data || data.status !== 'success') {
            _renderTeamPanelError((data && data.message) || t('team_load_failed'));
            return;
        }
        _teamPanelData = data;
        renderTeamPanel();
    } catch (e) {
        if (seq !== _teamPanelSeq || !teamPanelOpen) return;
        _renderTeamPanelError(String((e && e.message) || e));
    }
}

function renderTeamPanel() {
    const data = _teamPanelData;
    if (!data) return;
    _renderTeamRoster(data.team || {});
    _renderTeamMailbox(data.messages || []);
    _renderTeamTasks(data.tasks || []);
    _renderTeamActivity(data.activity || []);
}

// ---- roster -------------------------------------------------------------

function _renderTeamRoster(team) {
    const box = document.getElementById('team-roster');
    if (!box) return;
    const owner = team.owner || {};
    const members = team.members || [];
    if (!members.length) {
        box.innerHTML = `<span class="team-chip">${escapeHtml(t('team_no_members'))}</span>`;
        return;
    }
    box.innerHTML = members.map(m => {
        const isOwner = owner.id && m.id === owner.id;
        return `<span class="team-chip ${isOwner ? 'team-chip-owner' : ''}" title="${escapeHtml(m.id || '')}">`
            + `<i class="fas fa-robot"></i>${escapeHtml(m.name || m.id || '?')}`
            + (isOwner ? `<em>${escapeHtml(t('new_team_chat_owner'))}</em>` : '')
            + `</span>`;
    }).join('');
}

// ---- mailbox ------------------------------------------------------------

// One team_send broadcast is stored as one record per recipient so per-person
// read receipts stay honest. For display, collapse records that share sender,
// type, timestamp and content back into a single row.
function _groupTeamMessages(messages) {
    const groups = new Map();
    (messages || []).forEach(m => {
        const key = `${m.from_id || ''}|${m.msg_type || ''}|${m.ts || 0}|${m.content || ''}`;
        let g = groups.get(key);
        if (!g) {
            g = { ...m, to_names: [], files_all: [], read_total: 0, read_done: 0 };
            groups.set(key, g);
        }
        g.to_names.push(m.to_name || m.to_id || '?');
        g.read_total += 1;
        if (m.read) g.read_done += 1;
        (m.files || []).forEach(f => { if (!g.files_all.includes(f)) g.files_all.push(f); });
    });
    return [...groups.values()];
}

function _renderTeamMailbox(messages) {
    const body = document.getElementById('team-body-mailbox');
    if (!body) return;
    const list = messages || [];
    _setTeamTabCount('mailbox', list.filter(m => !m.read).length);
    const groups = _groupTeamMessages(list);
    if (!groups.length) {
        body.innerHTML = _teamPanelEmpty('fa-inbox', 'team_empty_mailbox', 'team_hint_mailbox');
        return;
    }
    body.innerHTML = groups.map(m => {
        const meta = TEAM_MSG_META[m.msg_type] || TEAM_MSG_META.info;
        const unread = m.read_done < m.read_total;
        const toText = m.to_names.length > 2
            ? `${m.to_names[0]} +${m.to_names.length - 1}`
            : m.to_names.join(', ');
        const readText = m.read_total > 1 ? ` ${m.read_done}/${m.read_total}` : '';
        return `
        <div class="team-msg ${unread ? 'team-msg-unread' : ''}">
            <div class="team-msg-head">
                <span class="team-msg-from" title="${escapeHtml(m.from_id || '')}"><i class="fas fa-robot"></i>${escapeHtml(m.from_name || m.from_id || '?')}</span>
                <i class="fas fa-arrow-right-long team-msg-arrow"></i>
                <span class="team-msg-to" title="${escapeHtml(m.to_names.join(', '))}">${escapeHtml(toText)}</span>
                <span class="team-msg-time">${escapeHtml(m.created_at || '')}</span>
            </div>
            <div class="team-msg-content" onclick="this.classList.toggle('expanded')">${escapeHtml(m.summary || m.content || '')}</div>
            <div class="team-msg-foot">
                <span class="team-type ${meta.cls}"><i class="fas ${meta.icon}"></i>${escapeHtml(t(meta.key))}</span>
                ${(m.files_all && m.files_all.length) ? `<span class="team-msg-files" title="${escapeHtml(m.files_all.join('\n'))}"><i class="fas fa-paperclip"></i>${m.files_all.length}</span>` : ''}
                <span class="team-msg-read ${unread ? 'is-unread' : ''}"><i class="fas ${unread ? 'fa-envelope' : 'fa-envelope-open'}"></i>${escapeHtml(unread ? t('team_unread') : t('team_read'))}${escapeHtml(readText)}</span>
            </div>
        </div>`;
    }).join('');
}

// ---- task board ----------------------------------------------------------

function _renderTeamTasks(tasks) {
    const body = document.getElementById('team-body-tasks');
    if (!body) return;
    const list = tasks || [];
    _setTeamTabCount('tasks', list.filter(task => task.status !== 'completed').length);
    if (!list.length) {
        body.innerHTML = _teamPanelEmpty('fa-list-check', 'team_empty_tasks', 'team_hint_tasks');
        return;
    }
    const byId = new Map(list.map(task => [String(task.id || ''), task]));
    body.innerHTML = list.map(task => {
        const meta = TEAM_STATUS_META[task.status] || TEAM_STATUS_META.pending;
        const done = task.status === 'completed';
        const blockerIds = (task.blocked_by || []).map(String);
        const known = blockerIds.map(id => byId.get(id)).filter(Boolean);
        const missing = blockerIds.length - known.length;
        // An in-progress task gets the live spinner; the rest get their status icon.
        const statusIcon = task.status === 'in_progress' ? 'fa-spinner fa-pulse' : meta.icon;
        return `
        <div class="team-task ${task.blocked ? 'team-task-blocked' : ''} ${done ? 'team-task-done' : ''}">
            <div class="team-task-head">
                <span class="team-st ${meta.cls}"><i class="fas ${statusIcon}"></i>${escapeHtml(t(meta.key))}</span>
                <span class="team-task-subject" title="${escapeHtml(task.subject || '')}">${escapeHtml(task.subject || '')}</span>
                ${task.blocked ? `<span class="team-blocked"><i class="fas fa-lock"></i>${escapeHtml(t('team_blocked'))}</span>` : ''}
            </div>
            ${task.description ? `<div class="team-task-desc">${escapeHtml(task.description)}</div>` : ''}
            ${task.blocked ? `<div class="team-task-blockers">${known.map(b => `<span class="team-blocker-chip" title="${escapeHtml(String(b.id || ''))}"><i class="fas fa-lock"></i>${escapeHtml(b.subject || b.id || '')}</span>`).join('')}${missing > 0 ? `<span class="team-blocker-chip">+${missing}</span>` : ''}</div>` : ''}
            <div class="team-task-meta">
                <span title="${escapeHtml(task.owner || '')}"><i class="fas fa-user"></i>${escapeHtml(task.owner_name || task.owner || '—')}</span>
                <span><i class="fas fa-clock"></i>${escapeHtml(task.created_at || '')}</span>
                <span class="team-task-id" title="${escapeHtml(String(task.id || ''))}">#${escapeHtml(String(task.id || '').slice(0, 6))}</span>
            </div>
        </div>`;
    }).join('');
}

// ---- activity feed ---------------------------------------------------------

function _renderTeamActivity(items) {
    const body = document.getElementById('team-body-activity');
    if (!body) return;
    const list = items || [];
    if (!list.length) {
        body.innerHTML = _teamPanelEmpty('fa-tower-broadcast', 'team_empty_activity', 'team_hint_activity');
        return;
    }
    body.innerHTML = list.map(item => `
        <div class="team-act">
            <span class="team-act-icon"><i class="fas ${TEAM_ACTIVITY_ICON[item.kind] || TEAM_ACTIVITY_ICON.message}"></i></span>
            <div class="team-act-main">
                <div class="team-act-text"><span class="team-act-actor">${escapeHtml(item.actor_name || item.actor || '')}</span> ${escapeHtml(item.text || '')}</div>
                <div class="team-act-time">${escapeHtml(item.created_at || '')}</div>
            </div>
        </div>`).join('');
}

// ---- shared bits -----------------------------------------------------------

function _setTeamTabCount(tab, count) {
    const badge = document.getElementById(`team-tab-${tab}-badge`);
    if (!badge) return;
    const n = Number(count) || 0;
    badge.textContent = n > 99 ? '99+' : String(n);
    badge.classList.toggle('hidden', !n);
}

function _teamPanelLoading() {
    return `<div class="team-empty"><i class="fas fa-spinner fa-pulse"></i><p>${escapeHtml(t('team_loading'))}</p></div>`;
}

function _teamPanelEmpty(icon, key, hintKey) {
    return `<div class="team-empty"><i class="fas ${icon}"></i><p>${escapeHtml(t(key))}</p><p class="team-empty-hint">${escapeHtml(t(hintKey))}</p></div>`;
}

function _renderTeamPanelError(message) {
    TEAM_PANEL_TABS.forEach(name => {
        const body = document.getElementById('team-body-' + name);
        if (body) {
            body.innerHTML = `<div class="team-empty team-empty-error"><i class="fas fa-triangle-exclamation"></i>`
                + `<p>${escapeHtml(String(message || ''))}</p>`
                + `<button class="team-retry" onclick="refreshTeamPanel()">${escapeHtml(t('team_refresh'))}</button></div>`;
        }
    });
}