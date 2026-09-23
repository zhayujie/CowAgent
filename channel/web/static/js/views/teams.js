/* Sidebar "Teams": named, persistent Agent groups (AionUi-style).
   A team is a saved roster with a leader; opening one enters — or starts —
   a group conversation carrying that roster. Teams live in the sidebar's
   Teams section; the + button creates one. Helpers (enabledAgents,
   agentAvatarHTML, setTeamMembers, switchSession, newChat, navigateTo,
   showConfirmDialog) are resolved at call time, so load order is free. */

let _namedTeams = [];
let _teamCreatePicks = [];

function teamOfSession(sid) {
    return localStorage.getItem('cow_team_of_' + sid) || '';
}

/* ---------------------------------------------------------------- list -- */

async function loadTeams() {
    try {
        const res = await fetch('/api/team-groups');
        const data = await res.json();
        if (data.status !== 'success') return;
        _namedTeams = data.teams || [];
        renderTeamsList();
    } catch (e) { /* the sidebar list is best-effort */ }
}

function renderTeamsList() {
    const list = document.getElementById('teams-list');
    if (!list) return;
    const currentTeam = (typeof sessionId !== 'undefined')
        ? teamOfSession(sessionId) : '';
    list.innerHTML = _namedTeams.map(team => `
        <a class="team-nav-item sidebar-item flex items-center gap-3 px-3 py-2 rounded-lg cursor-pointer transition-all duration-150 hover:bg-white/5 hover:text-neutral-200 text-[14px]${currentTeam === team.id ? ' active' : ''}"
           onclick="openNamedTeam('${escapeHtml(team.id)}')" title="${escapeHtml(team.name)}">
            <i class="fas fa-user-group item-icon text-xs w-5 text-center"></i>
            <span class="truncate flex-1">${escapeHtml(team.name)}</span>
            <i class="fas fa-xmark team-nav-del" role="button" aria-label="Delete team"
               onclick="event.stopPropagation(); deleteNamedTeam('${escapeHtml(team.id)}')"></i>
        </a>`).join('');
}

/* ------------------------------------------------------------- open one -- */

async function openNamedTeam(teamId) {
    let team = _namedTeams.find(t => t.id === teamId);
    if (!team) {
        try {
            const res = await fetch('/api/team-groups/' + encodeURIComponent(teamId));
            const data = await res.json();
            if (data.status === 'success') team = data.team;
        } catch (e) { /* handled below */ }
    }
    if (!team) return;

    if (typeof navigateTo === 'function') navigateTo('chat');

    const saved = localStorage.getItem('cow_team_session_' + teamId);
    if (saved) {
        try { switchSession(saved, team.leader); } catch (e) { /* fresh below */ }
        if (typeof sessionId !== 'undefined' && sessionId === saved) {
            localStorage.setItem('cow_team_of_' + saved, teamId);
            loadTeams();
            return;
        }
    }
    startNamedTeamChat(team);
}

/* A fresh conversation owned by the leader, roster seeded from the team.
   Same shape as startTeamChat(): newChat() mints the session client-side,
   then setTeamMembers invites everyone else so the first message is group. */
function startNamedTeamChat(team) {
    const guests = (team.members || [])
        .map(m => (typeof m === 'string' ? m : m.id))
        .filter(id => id && id !== team.leader);
    activeAgentId = team.leader;
    localStorage.setItem('cow_active_agent', activeAgentId);
    newChat(true);
    if (typeof resetWorkspaceToAgentRoot === 'function') resetWorkspaceToAgentRoot();
    setTeamMembers(guests).then(() => {
        localStorage.setItem('cow_team_session_' + team.id, sessionId);
        localStorage.setItem('cow_team_of_' + sessionId, team.id);
        if (typeof renderComposerIdentity === 'function') renderComposerIdentity();
        loadTeams();
    });
}

/* -------------------------------------------------------------- create -- */

function openTeamCreateModal() {
    const modal = document.getElementById('team-create-modal');
    if (!modal) return;
    _teamCreatePicks = [];
    const nameEl = document.getElementById('team-create-name');
    if (nameEl) nameEl.value = '';
    const status = document.getElementById('team-create-status');
    if (status) status.textContent = '';
    renderTeamCreateList();
    modal.classList.remove('hidden');
}

function closeTeamCreateModal() {
    document.getElementById('team-create-modal')?.classList.add('hidden');
}

function toggleTeamCreatePick(agentId) {
    const i = _teamCreatePicks.indexOf(agentId);
    if (i === -1) _teamCreatePicks.push(agentId);
    else _teamCreatePicks.splice(i, 1);
    renderTeamCreateList();
}

function renderTeamCreateList() {
    const list = document.getElementById('team-create-list');
    if (!list) return;
    list.innerHTML = enabledAgents().map(agent => {
        const rank = _teamCreatePicks.indexOf(agent.id);
        const on = rank !== -1;
        const leader = rank === 0;
        return `<button type="button" class="team-chat-row${on ? ' on' : ''}"
                        onclick="toggleTeamCreatePick('${escapeHtml(agent.id)}')">
            ${agentAvatarHTML(agent, 28)}
            <span class="team-chat-name">${escapeHtml(agent.name)}</span>
            ${leader ? `<span class="team-chat-owner">${escapeHtml(t('team_leader_tag'))}</span>` : ''}
            <span class="team-chat-check"><i class="fas ${on ? 'fa-circle-check' : 'fa-circle'}"></i></span>
        </button>`;
    }).join('');
}

async function createNamedTeam() {
    const nameEl = document.getElementById('team-create-name');
    const status = document.getElementById('team-create-status');
    const name = (nameEl ? nameEl.value : '').trim();
    if (!name) { if (status) status.textContent = t('team_create_need_name'); return; }
    if (_teamCreatePicks.length < 1) {
        if (status) status.textContent = t('team_create_need_leader');
        return;
    }
    try {
        const res = await fetch('/api/team-groups', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                name: name,
                leader: _teamCreatePicks[0],
                members: _teamCreatePicks.slice(1),
            }),
        });
        const data = await res.json();
        if (data.status !== 'success') {
            if (status) status.textContent = data.message || t('team_create_failed');
            return;
        }
        closeTeamCreateModal();
        await loadTeams();
        openNamedTeam(data.team.id);
    } catch (e) {
        if (status) status.textContent = t('team_create_failed');
    }
}

function deleteNamedTeam(teamId) {
    showConfirmDialog({
        title: t('team_delete_title'),
        message: t('team_delete_confirm'),
        okText: t('team_delete_ok'),
        onConfirm: async () => {
            try {
                await fetch('/api/team-groups/' + encodeURIComponent(teamId),
                            { method: 'DELETE' });
            } catch (e) { /* nothing to report on failure */ }
            if (typeof sessionId !== 'undefined'
                && teamOfSession(sessionId) === teamId) {
                localStorage.removeItem('cow_team_of_' + sessionId);
            }
            localStorage.removeItem('cow_team_session_' + teamId);
            loadTeams();
        },
    });
}

document.addEventListener('DOMContentLoaded', loadTeams);