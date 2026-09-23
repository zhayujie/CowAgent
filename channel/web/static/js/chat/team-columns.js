/* Team columns: the AionUi-style parallel member view.
   One shared conversation, one column per member — the leader first with a
   crown, each member with its own composer that hands them the turn through
   the existing @mention addressing. Two view modes per session (parallel /
   single), remembered in localStorage; identity colors pin to the member so
   adds and removals never reshuffle them.

   How it fits the single stream: every reply bubble carries
   data-speaker-agent (render.js / send.js tag it) and user bubbles are
   attributed by who they address. In columns mode the stream's children are
   MOVED into per-member column bodies inside #team-columns-root (a
   MutationObserver routes new arrivals, including late speaker tags); leaving
   the mode or the session moves everything back in the original order, so
   the plain stream view is exactly what it was. Classic script; helpers
   (sessionRoster, addressedAgentId, addTeamMember, sendMessage) resolve at
   call time. */

const TEAM_COL_PALETTE = ['#35A85B', '#4A90D9', '#D97706', '#8B5CF6',
                          '#DB2777', '#0D9488', '#EA580C', '#64748B'];
const TEAM_VIEW_KEY = 'team-view-mode-';
const TEAM_COLORS_KEY = 'team-member-colors-';

let _teamColsMode = 'parallel';    // parallel | single
let _teamColsActive = null;        // selected member id (default: leader)
let _teamColsKey = '';             // storage key stem: named team id or session id
let _teamColsRosterKey = '';       // roster shape the current columns were built for
let _teamColsRoot = null;
let _teamColsObserver = null;
let _teamColsStreamOrder = [];     // original stream order, for a lossless restore
let _teamColsColumns = new Map();  // agentId -> { col, body, composer }

function teamColsRoster() {
    // [owner/leader, ...members], profiles resolved; same source the
    // composer's @-addressing uses.
    return (typeof sessionRoster === 'function') ? sessionRoster() : [];
}

function teamColsAvailable() {
    return !!(typeof _sessCfg !== 'undefined' && _sessCfg && _sessCfg.team
        && Array.isArray(_sessCfg.team.members)
        && _sessCfg.team.members.length > 0);
}

function _teamColsStorageKey() {
    if (!_teamColsKey) {
        const named = (typeof sessionId !== 'undefined')
            ? localStorage.getItem('cow_team_of_' + sessionId) : null;
        _teamColsKey = named || (typeof sessionId !== 'undefined' ? sessionId : 'default');
    }
    return _teamColsKey;
}

/* ------------------------------------------------------------- colors -- */

function _teamColsLoadColors() {
    try {
        return JSON.parse(localStorage.getItem(TEAM_COLORS_KEY + _teamColsStorageKey()) || '{}');
    } catch (e) { return {}; }
}

function _teamColsSaveColors(map) {
    localStorage.setItem(TEAM_COLORS_KEY + _teamColsKey, JSON.stringify(map));
}

// The leader takes the brand green; members take the first free slot in the
// palette. Freed indices (a member was removed) are reused for the next one.
function _teamColorFor(agentId, leaderId) {
    if (agentId === leaderId) return TEAM_COL_PALETTE[0];
    const colors = _teamColsLoadColors();
    if (colors[agentId] !== undefined) {
        return TEAM_COL_PALETTE[colors[agentId] % TEAM_COL_PALETTE.length];
    }
    const used = new Set(Object.values(colors));
    let idx = 1;
    while (used.has(idx)) idx++;
    colors[agentId] = idx;
    _teamColsSaveColors(colors);
    return TEAM_COL_PALETTE[idx % TEAM_COL_PALETTE.length];
}

// Drop colors of members that are no longer on the roster (frees their slot).
function _pruneColors(roster) {
    const colors = _teamColsLoadColors();
    const ids = new Set(roster.map(a => a.id));
    let changed = false;
    Object.keys(colors).forEach(id => {
        if (!ids.has(id)) { delete colors[id]; changed = true; }
    });
    if (changed) _teamColsSaveColors(colors);
}

/* ------------------------------------------------------------ pill bar -- */

function _renderPillbar(roster, leaderId) {
    const bar = document.getElementById('team-pillbar');
    if (!bar) return;
    const pills = roster.map(agent => {
        const isLeader = agent.id === leaderId;
        const color = _teamColorFor(agent.id, leaderId);
        const active = _teamColsActive === agent.id ? ' active' : '';
        return `
        <button type="button" class="team-pill${active}${isLeader ? ' leader' : ''}"
                data-agent-id="${escapeHtml(agent.id)}" style="--team-accent:${color}"
                onclick="selectTeamMember('${escapeHtml(agent.id)}')">
            ${isLeader ? '<i class="fas fa-crown team-pill-crown"></i>' : ''}
            ${typeof agentAvatarHTML === 'function' ? agentAvatarHTML(agent, 20) : ''}
            <span class="team-pill-name">${escapeHtml(agent.name || agent.id)}</span>
            <span class="team-pill-dot" style="background:${color}"></span>
        </button>`;
    }).join('');
    const addBtn = `
        <button type="button" class="team-pill team-pill-add" onclick="toggleTeamAddMenu(event)">
            <i class="fas fa-plus"></i><span>${escapeHtml(t('team_pill_add'))}</span>
        </button>`;
    const toggle = `
        <span class="team-view-toggle" role="group" aria-label="${escapeHtml(t('team_view_toggle'))}">
            <button type="button" id="team-view-parallel"
                    class="team-view-btn${_teamColsMode === 'parallel' ? ' active' : ''}"
                    onclick="setTeamViewMode('parallel')" title="${escapeHtml(t('team_view_parallel'))}">
                <i class="fas fa-table-columns"></i>
            </button>
            <button type="button" id="team-view-single"
                    class="team-view-btn${_teamColsMode === 'single' ? ' active' : ''}"
                    onclick="setTeamViewMode('single')" title="${escapeHtml(t('team_view_single'))}">
                <i class="fas fa-square"></i>
            </button>
        </span>`;
    bar.innerHTML = `<div class="team-pillbar-row">${pills}${addBtn}
        <span class="team-pillbar-spacer"></span>${toggle}</div>`;
    bar.classList.remove('hidden');
}

/* ---------------------------------------------------------- add member -- */

function _closeTeamAddMenu() {
    document.getElementById('team-add-menu')?.remove();
}

function toggleTeamAddMenu(event) {
    if (event) event.stopPropagation();
    const bar = document.getElementById('team-pillbar');
    if (!bar) return;
    const existing = document.getElementById('team-add-menu');
    if (existing) { existing.remove(); return; }
    const roster = teamColsRoster();
    const agents = (typeof enabledAgents === 'function' ? enabledAgents() : [])
        .filter(a => !roster.some(m => m.id === a.id));
    const rows = agents.map(a => `
        <button type="button" class="team-add-item" onclick="addTeamMemberToTeam('${escapeHtml(a.id)}')">
            ${typeof agentAvatarHTML === 'function' ? agentAvatarHTML(a, 20) : ''}
            <span>${escapeHtml(a.name || a.id)}</span>
        </button>`).join('');
    const menu = document.createElement('div');
    menu.id = 'team-add-menu';
    menu.className = 'team-add-menu';
    menu.innerHTML = `
        <div class="team-add-list">${rows || `<div class="team-add-empty">${escapeHtml(t('team_add_empty'))}</div>`}</div>
        <button type="button" class="team-add-leader-hint" onclick="tellLeaderToAddMember()">
            ${escapeHtml(t('team_tell_leader'))} <i class="fas fa-arrow-right"></i>
        </button>`;
    bar.appendChild(menu);
}

async function addTeamMemberToTeam(agentId) {
    _closeTeamAddMenu();
    if (typeof addTeamMember === 'function') await addTeamMember(agentId);
    // Keep the named team (if this session belongs to one) in step with the
    // session roster the settings endpoint now holds.
    const teamId = (typeof sessionId !== 'undefined')
        ? localStorage.getItem('cow_team_of_' + sessionId) : null;
    if (teamId && typeof currentTeamIds === 'function') {
        const ids = [activeAgentId, ...currentTeamIds()].filter(Boolean);
        try {
            await fetch('/api/team-groups/' + encodeURIComponent(teamId), {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ members: ids }),
            });
        } catch (e) { /* the roster change already applied to the session */ }
        loadTeams();
    }
}

function tellLeaderToAddMember() {
    _closeTeamAddMenu();
    const leaderId = (teamColsRoster()[0] || {}).id;
    if (leaderId) _teamColsActive = leaderId;
    if (_teamColsMode === 'single' && _teamColsRoot) updateTeamColumns();
    const entry = _teamColsColumns.get(leaderId);
    if (entry) {
        entry.composer.value = t('team_suggest_add');
        entry.composer.focus();
    }
}

/* ----------------------------------------------------- columns (build) -- */

function _buildColumns(roster, leaderId) {
    _teamColsColumns = new Map();
    if (!_teamColsRoot) {
        _teamColsRoot = document.createElement('div');
        _teamColsRoot.id = 'team-columns-root';
    }
    _teamColsRoot.className = _teamColsMode === 'single' ? 'single' : '';
    _teamColsRoot.style.gridTemplateColumns =
        `repeat(${Math.max(roster.length, 1)}, minmax(0, 1fr))`;
    _teamColsRoot.innerHTML = roster.map(agent => {
        const isLeader = agent.id === leaderId;
        const color = _teamColorFor(agent.id, leaderId);
        const active = _teamColsActive === agent.id ? ' active' : '';
        const aid = escapeHtml(agent.id);
        return `
        <div class="team-col${active}${isLeader ? ' leader' : ''}"
             data-agent-id="${escapeHtml(agent.id)}" style="--team-accent:${color}">
            <div class="team-col-head">
                ${isLeader ? '<i class="fas fa-crown team-col-crown"></i>' : ''}
                <span class="team-col-face">${typeof agentAvatarHTML === 'function' ? agentAvatarHTML(agent, 22) : ''}</span>
                <span class="team-col-name">${escapeHtml(agent.name || agent.id)}</span>
                <span class="team-col-accent"></span>
            </div>
            <div class="team-col-body"></div>
            <div class="team-col-composer">
                <input type="text" class="team-col-input" spellcheck="false"
                       placeholder="${escapeHtml(t('team_col_input_ph'))}"
                       onkeydown="if(event.key==='Enter'){event.preventDefault();teamColSend('${escapeHtml(agent.id)}', this);}">
                <button type="button" class="team-col-send"
                        onclick="teamColSend('${escapeHtml(agent.id)}', this.previousElementSibling)">
                    <i class="fas fa-paper-plane text-xs"></i>
                </button>
            </div>
        </div>`;
    }).join('');
    _teamColsRoot.querySelectorAll('.team-col').forEach(col => {
        _teamColsColumns.set(col.dataset.agentId, {
            col: col,
            body: col.querySelector('.team-col-body'),
            composer: col.querySelector('.team-col-input'),
        });
    });
}

/* Route one stream child into its member's column: replies follow their
   speaker tag, everything else (user bubbles, loading indicators) follows
   who it addresses, defaulting to the leader. */
function _agentForNode(node, leaderId) {
    if (node.dataset && node.dataset.speakerAgent) return node.dataset.speakerAgent;
    if (typeof addressedAgentId === 'function') {
        const addressed = addressedAgentId(node.textContent || '');
        if (addressed) return addressed;
    }
    return leaderId;
}

function _placeNode(node, leaderId) {
    const entry = _teamColsColumns.get(_agentForNode(node, leaderId))
        || _teamColsColumns.get(leaderId);
    if (!entry) return;
    _teamColsStreamOrder.push(node);
    entry.body.appendChild(node);
    entry.body.scrollTop = entry.body.scrollHeight;
}

function _organizeAll(leaderId) {
    const stream = document.getElementById('chat-messages');
    if (!stream || !_teamColsRoot || !_teamColsRoot.isConnected) return;
    [...stream.children].forEach(node => {
        if (node !== _teamColsRoot) _placeNode(node, leaderId);
    });
    _refreshWelcomeStates(leaderId);
}

function _observeStream(leaderId) {
    if (_teamColsObserver) return;
    const stream = document.getElementById('chat-messages');
    if (!stream) return;
    _teamColsObserver = new MutationObserver(mutations => {
        if (!_teamColsRoot || !_teamColsRoot.isConnected) return;
        mutations.forEach(m => {
            if (m.type === 'childList') {
                m.addedNodes.forEach(node => {
                    if (!(node instanceof Element) || node === _teamColsRoot) return;
                    if (node.parentElement !== stream) return;  // already placed
                    _placeNode(node, leaderId);
                    _refreshWelcomeStates(leaderId);
                });
            } else if (m.type === 'attributes') {
                // The speaker was identified after the bubble appeared (live
                // streams name the answerer once the turn starts).
                const el = m.target;
                const entry = el.dataset && _teamColsColumns.get(el.dataset.speakerAgent);
                if (entry && el.parentElement !== entry.body) {
                    entry.body.appendChild(el);
                    entry.body.scrollTop = entry.body.scrollHeight;
                }
                _refreshWelcomeStates(leaderId);
            }
        });
    });
    _teamColsObserver.observe(stream, {
        childList: true,
        subtree: true,
        attributes: true,
        attributeFilter: ['data-speaker-agent'],
    });
}

/* Every message node currently living in a column, original order. */
function _placedNodes() {
    return _teamColsStreamOrder.filter(n => n instanceof Element && n.isConnected);
}

function _restoreToStream() {
    if (_teamColsObserver) { _teamColsObserver.disconnect(); _teamColsObserver = null; }
    _closeTeamAddMenu();
    if (_teamColsRoot && _teamColsRoot.isConnected) {
        const stream = _teamColsRoot.parentElement;
        _placedNodes().forEach(node => stream.insertBefore(node, _teamColsRoot));
        _teamColsRoot.remove();
        stream.classList.remove('team-columns-on');
    }
    _teamColsStreamOrder = [];
    _teamColsColumns = new Map();
    _teamColsRosterKey = '';
}

/* ------------------------------------------------------------- welcome -- */

function _refreshWelcomeStates(leaderId) {
    _teamColsColumns.forEach((entry, agentId) => {
        const content = [...entry.body.children]
            .filter(n => !n.classList.contains('team-col-welcome'));
        let welcome = entry.body.querySelector('.team-col-welcome');
        if (content.length > 0) { welcome?.remove(); return; }
        if (welcome) return;
        welcome = document.createElement('div');
        welcome.className = 'team-col-welcome';
        if (agentId === leaderId) {
            const aid = escapeHtml(agentId);
            welcome.innerHTML = `
                <div class="team-col-greet">${escapeHtml(t('team_leader_greet'))}</div>
                <div class="team-col-chips">
                    <button type="button" class="team-col-chip" onclick="teamChipPrefill('${aid}', 'team_suggest_debate')">${escapeHtml(t('team_suggest_debate'))}</button>
                    <button type="button" class="team-col-chip" onclick="teamChipPrefill('${aid}', 'team_suggest_add')">${escapeHtml(t('team_suggest_add'))}</button>
                    <button type="button" class="team-col-chip" onclick="teamChipPrefill('${aid}', 'team_suggest_experts')">${escapeHtml(t('team_suggest_experts'))}</button>
                </div>`;
        } else {
            welcome.innerHTML = `<div class="team-col-greet">${escapeHtml(t('team_member_greet'))}</div>`;
        }
        entry.body.appendChild(welcome);
    });
}

function teamChipPrefill(agentId, i18nKey) {
    const entry = _teamColsColumns.get(agentId);
    if (!entry) return;
    entry.composer.value = t(i18nKey);
    entry.composer.focus();
}

/* ---------------------------------------------------- modes / selection -- */

function setTeamViewMode(mode) {
    if (mode !== 'parallel' && mode !== 'single') return;
    _teamColsMode = mode;
    localStorage.setItem(TEAM_VIEW_KEY + _teamColsStorageKey(), mode);
    updateTeamColumns();
}

function selectTeamMember(agentId) {
    _teamColsActive = agentId;
    document.querySelectorAll('#team-pillbar .team-pill').forEach(pill => {
        pill.classList.toggle('active', pill.dataset.agentId === agentId);
    });
    _teamColsColumns.forEach((entry, id) => {
        entry.col.classList.toggle('active', id === agentId);
        if (id === agentId) {
            entry.body.scrollTop = entry.body.scrollHeight;
            if (_teamColsMode === 'single') entry.composer.focus();
        }
    });
}

/* ----------------------------------------------- per-column composer --- */

function teamColSend(agentId, inputEl) {
    const text = (inputEl ? inputEl.value : '').trim();
    if (!text) return;
    if (typeof pendingAttachments !== 'undefined' && pendingAttachments.length > 0) {
        if (typeof _wsToast === 'function') _wsToast(t('team_col_attach_hint'));
        return;
    }
    if (typeof chatInput === 'undefined' || typeof sendMessage !== 'function') return;
    const agent = teamColsRoster().find(a => a.id === agentId) || { name: agentId };
    // The leading mention hands this member the turn; sendMessage() owns the
    // whole outgoing path (history, addressing, streaming, composer reset).
    chatInput.value = '@' + (agent.name || agentId) + ' ' + text;
    inputEl.value = '';
    sendMessage();
}

/* ---------------------------------------------- public entry points --- */

function _teardownColumns() {
    _restoreToStream();
    document.getElementById('team-pillbar')?.classList.add('hidden');
}

// Called after every refreshSessionSettings() (session-settings.js).
function updateTeamColumns() {
    if (!teamColsAvailable()) {
        _teardownColumns();
        _teamColsKey = '';
        _teamColsActive = null;
        return;
    }
    const roster = teamColsRoster();
    if (!roster.length) { _teardownColumns(); return; }
    const leaderId = roster[0].id;
    _teamColsKey = '';  // recomputed for the (possibly new) session
    if (!_teamColsActive || !roster.some(a => a.id === _teamColsActive)) {
        _teamColsActive = leaderId;
    }
    const stored = localStorage.getItem(TEAM_VIEW_KEY + _teamColsStorageKey());
    _teamColsMode = (stored === 'single') ? 'single' : 'parallel';
    _pruneColors(roster);
    _renderPillbar(roster, leaderId);

    const stream = document.getElementById('chat-messages');
    if (!stream) return;
    const rosterKey = roster.map(a => a.id).join(',') + ':' + _teamColsMode;
    if (_teamColsRoot && _teamColsRoot.isConnected && _teamColsRosterKey === rosterKey) {
        stream.classList.add('team-columns-on');
        _organizeAll(leaderId);
        return;
    }
    // (Re)build: everything back into the stream first, then redistribute.
    _restoreToStream();
    _teamColsRosterKey = rosterKey;
    _buildColumns(roster, leaderId);
    stream.appendChild(_teamColsRoot);
    stream.classList.add('team-columns-on');
    _observeStream(leaderId);
    _organizeAll(leaderId);
}

// Called from views/sessions.js when the active session changes.
function teamColumnsOnSessionSwitch() {
    _teardownColumns();
    _teamColsKey = '';
    _teamColsActive = null;
}

// Clicking anywhere else closes the add-member dropdown.
document.addEventListener('click', () => _closeTeamAddMenu());