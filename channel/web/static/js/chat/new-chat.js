/* New chat and multi-agent team chat.
   Split out of console.js. These are classic scripts sharing one global
   scope; see channel/web/README.md before changing the load order. */

/* The session-panel "新对话" button. With a single Agent there is nobody to
   choose between, so it just starts a chat. With several, it opens a menu: pick
   an Agent for a solo chat, or open the team picker for a group chat. */
function onNewChatButton(event) {
    if (!multiAgentMode()) { newChat(true); return; }
    if (event) event.stopPropagation();
    const menu = document.getElementById('new-chat-menu');
    if (!menu) { newChat(true); return; }
    if (!menu.classList.contains('hidden')) { menu.classList.add('hidden'); return; }
    const rows = enabledAgents().map(agent => `
        <button type="button" class="new-chat-item" onclick="startSoloChat('${escapeHtml(agent.id)}')">
            ${agentAvatarHTML(agent, 22)}
            <span>${escapeHtml(agent.name)}</span>
        </button>`).join('');
    menu.innerHTML = `
        <div class="new-chat-section">${rows}</div>
        <div class="new-chat-sep"></div>
        <button type="button" class="new-chat-item new-chat-team" onclick="openTeamChatModal()">
            <span class="new-chat-team-ico"><i class="fas fa-user-group"></i></span>
            <span>${escapeHtml(t('new_team_chat'))}</span>
        </button>`;
    menu.classList.remove('hidden');
}

function startSoloChat(agentId) {
    document.getElementById('new-chat-menu')?.classList.add('hidden');
    if (!agentId) { newChat(true); return; }
    activeAgentId = agentId;
    localStorage.setItem('cow_active_agent', activeAgentId);
    newChat(true);
    if (typeof resetWorkspaceToAgentRoot === 'function') resetWorkspaceToAgentRoot();
    renderComposerIdentity();
}

// The first checked Agent owns the conversation; the rest are invited as guests.
let _teamChatPicks = [];

function openTeamChatModal() {
    document.getElementById('new-chat-menu')?.classList.add('hidden');
    _teamChatPicks = [activeAgentId || defaultAgentId];
    const status = document.getElementById('team-chat-status');
    if (status) status.textContent = '';
    renderTeamChatList();
    document.getElementById('team-chat-modal')?.classList.remove('hidden');
}

function closeTeamChatModal() {
    document.getElementById('team-chat-modal')?.classList.add('hidden');
}

/** From the group-chat picker, jump to creating a new Agent. */
function openAgentCreateFromModal() {
    closeTeamChatModal();
    navigateTo('agents');
    if (typeof openAgentCreateForm === 'function') openAgentCreateForm();
}

function toggleTeamChatPick(agentId) {
    const i = _teamChatPicks.indexOf(agentId);
    if (i === -1) _teamChatPicks.push(agentId);
    else _teamChatPicks.splice(i, 1);
    renderTeamChatList();
}

function renderTeamChatList() {
    const list = document.getElementById('team-chat-list');
    if (!list) return;
    list.innerHTML = enabledAgents().map(agent => {
        const rank = _teamChatPicks.indexOf(agent.id);
        const on = rank !== -1;
        const owner = rank === 0;
        return `<button type="button" class="team-chat-row${on ? ' on' : ''}" onclick="toggleTeamChatPick('${escapeHtml(agent.id)}')">
            ${agentAvatarHTML(agent, 28)}
            <span class="team-chat-name">${escapeHtml(agent.name)}</span>
            ${owner ? `<span class="team-chat-owner">${escapeHtml(t('new_team_chat_owner'))}</span>` : ''}
            <span class="team-chat-check"><i class="fas ${on ? 'fa-circle-check' : 'fa-circle'}"></i></span>
        </button>`;
    }).join('');
}

function startTeamChat() {
    const picks = _teamChatPicks.filter(id => enabledAgents().some(a => a.id === id));
    if (picks.length < 2) {
        const status = document.getElementById('team-chat-status');
        if (status) status.textContent = t('new_team_chat_min');
        return;
    }
    closeTeamChatModal();
    const [owner, ...guests] = picks;
    activeAgentId = owner;
    localStorage.setItem('cow_active_agent', activeAgentId);
    newChat(true);
    if (typeof resetWorkspaceToAgentRoot === 'function') resetWorkspaceToAgentRoot();
    // The fresh session exists client-side; invite the guests onto it so the
    // very first message already goes to a group.
    setTeamMembers(guests).then(() => renderComposerIdentity());
}

function newChat(optimistic = true, inherit = true) {
    // A fresh session resets the preview panel, discarding an open editor.
    if (typeof wsGuardUnsaved === 'function'
        && !wsGuardUnsaved(() => newChat(optimistic, inherit))) return;

    // Do NOT close active streams: other sessions keep streaming in the
    // background (each stream self-guards against the foreign view) and their
    // replies still complete and persist.

    // Generate a fresh session and persist it so the next page load also starts clean
    sessionId = generateSessionId();
    localStorage.setItem(activeSessionStorageKey(), sessionId);
    refreshWorkspaceSelector();  // a fresh session starts on the default workspace
    refreshSessionSettings();    // ... and on the global model / permission
    if (typeof wsOnSessionSwitch === 'function') wsOnSessionSwitch();
    resetSendBtnSendMode();  // fresh session has no in-flight reply
    startPolling();  // bump generation so old loop self-cancels, new loop uses fresh sessionId
    messagesDiv.innerHTML = '';
    const ws = document.createElement('div');
    ws.id = 'welcome-screen';
    ws.className = 'flex flex-col items-center justify-center h-full px-6 pb-16';
    ws.style.paddingTop = '6vh';
    ws.innerHTML = `
        <img src="/assets/logo.jpg" alt="CowAgent" class="w-16 h-16 rounded-2xl mb-6 shadow-lg shadow-primary-500/20">
        <h1 class="text-2xl font-bold text-slate-800 dark:text-slate-100 mb-3">${appConfig.title || 'CowAgent'}</h1>
        <p class="text-slate-500 dark:text-slate-400 text-center max-w-lg mb-10 leading-relaxed" data-i18n="welcome_subtitle">${t('welcome_subtitle')}</p>
        <div class="grid grid-cols-2 sm:grid-cols-3 gap-3 w-full max-w-2xl">
            <div class="example-card group bg-white dark:bg-[#1A1A1A] border border-slate-200 dark:border-white/10 rounded-xl p-4 cursor-pointer hover:border-primary-300 dark:hover:border-primary-600 hover:shadow-md transition-all duration-200">
                <div class="flex items-center gap-2 mb-2">
                    <div class="w-7 h-7 rounded-lg bg-blue-50 dark:bg-blue-900/30 flex items-center justify-center">
                        <i class="fas fa-folder-open text-blue-500 text-xs"></i>
                    </div>
                    <span class="font-medium text-sm text-slate-700 dark:text-slate-200" data-i18n="example_sys_title">${t('example_sys_title')}</span>
                </div>
                <p class="text-sm text-slate-500 dark:text-slate-400 leading-relaxed" data-i18n="example_sys_text">${t('example_sys_text')}</p>
            </div>
            <div class="example-card group bg-white dark:bg-[#1A1A1A] border border-slate-200 dark:border-white/10 rounded-xl p-4 cursor-pointer hover:border-primary-300 dark:hover:border-primary-600 hover:shadow-md transition-all duration-200">
                <div class="flex items-center gap-2 mb-2">
                    <div class="w-7 h-7 rounded-lg bg-amber-50 dark:bg-amber-900/30 flex items-center justify-center">
                        <i class="fas fa-clock text-amber-500 text-xs"></i>
                    </div>
                    <span class="font-medium text-sm text-slate-700 dark:text-slate-200" data-i18n="example_task_title">${t('example_task_title')}</span>
                </div>
                <p class="text-sm text-slate-500 dark:text-slate-400 leading-relaxed" data-i18n="example_task_text">${t('example_task_text')}</p>
            </div>
            <div class="example-card group bg-white dark:bg-[#1A1A1A] border border-slate-200 dark:border-white/10 rounded-xl p-4 cursor-pointer hover:border-primary-300 dark:hover:border-primary-600 hover:shadow-md transition-all duration-200">
                <div class="flex items-center gap-2 mb-2">
                    <div class="w-7 h-7 rounded-lg bg-emerald-50 dark:bg-emerald-900/30 flex items-center justify-center">
                        <i class="fas fa-code text-emerald-500 text-xs"></i>
                    </div>
                    <span class="font-medium text-sm text-slate-700 dark:text-slate-200" data-i18n="example_code_title">${t('example_code_title')}</span>
                </div>
                <p class="text-sm text-slate-500 dark:text-slate-400 leading-relaxed" data-i18n="example_code_text">${t('example_code_text')}</p>
            </div>
            <div class="example-card group bg-white dark:bg-[#1A1A1A] border border-slate-200 dark:border-white/10 rounded-xl p-4 cursor-pointer hover:border-primary-300 dark:hover:border-primary-600 hover:shadow-md transition-all duration-200">
                <div class="flex items-center gap-2 mb-2">
                    <div class="w-7 h-7 rounded-lg bg-violet-50 dark:bg-violet-900/30 flex items-center justify-center">
                        <i class="fas fa-book text-violet-500 text-xs"></i>
                    </div>
                    <span class="font-medium text-sm text-slate-700 dark:text-slate-200" data-i18n="example_knowledge_title">${t('example_knowledge_title')}</span>
                </div>
                <p class="text-sm text-slate-500 dark:text-slate-400 leading-relaxed" data-i18n="example_knowledge_text">${t('example_knowledge_text')}</p>
            </div>
            <div class="example-card group bg-white dark:bg-[#1A1A1A] border border-slate-200 dark:border-white/10 rounded-xl p-4 cursor-pointer hover:border-primary-300 dark:hover:border-primary-600 hover:shadow-md transition-all duration-200">
                <div class="flex items-center gap-2 mb-2">
                    <div class="w-7 h-7 rounded-lg bg-rose-50 dark:bg-rose-900/30 flex items-center justify-center">
                        <i class="fas fa-puzzle-piece text-rose-500 text-xs"></i>
                    </div>
                    <span class="font-medium text-sm text-slate-700 dark:text-slate-200" data-i18n="example_skill_title">${t('example_skill_title')}</span>
                </div>
                <p class="text-sm text-slate-500 dark:text-slate-400 leading-relaxed" data-i18n="example_skill_text">${t('example_skill_text')}</p>
            </div>
            <div class="example-card group bg-white dark:bg-[#1A1A1A] border border-slate-200 dark:border-white/10 rounded-xl p-4 cursor-pointer hover:border-primary-300 dark:hover:border-primary-600 hover:shadow-md transition-all duration-200" data-send="/help">
                <div class="flex items-center gap-2 mb-2">
                    <div class="w-7 h-7 rounded-lg bg-slate-100 dark:bg-slate-800 flex items-center justify-center">
                        <i class="fas fa-terminal text-slate-500 text-xs"></i>
                    </div>
                    <span class="font-medium text-sm text-slate-700 dark:text-slate-200" data-i18n="example_web_title">${t('example_web_title')}</span>
                </div>
                <p class="text-sm text-slate-500 dark:text-slate-400 leading-relaxed" data-i18n="example_web_text">${t('example_web_text')}</p>
            </div>
        </div>
    `;
    messagesDiv.appendChild(ws);
    renderComposerIdentity();
    ws.querySelectorAll('.example-card').forEach(card => {
        card.addEventListener('click', () => {
            const sendText = card.dataset.send;
            if (sendText) {
                chatInput.value = sendText;
                chatInput.dispatchEvent(new Event('input'));
                chatInput.focus();
                return;
            }
            const textEl = card.querySelector('[data-i18n*="text"]');
            if (textEl) {
                chatInput.value = textEl.textContent;
                chatInput.dispatchEvent(new Event('input'));
                chatInput.focus();
            }
        });
    });
    if (currentView !== 'chat') navigateTo('chat');

    // Show panel and load full session list, then prepend the new session on top
    const panel = document.getElementById('session-panel');
    if (panel && !sessionPanelOpen) {
        sessionPanelOpen = true;
        panel.classList.remove('hidden');
        _showSessionOverlay();
        _persistPanelState();
    }
    // Only prepend an optimistic "new chat" item when this is a real new-chat
    // action. When called after deleting the current session, skip it: the
    // fresh session has no backend record yet, so inserting it would leave an
    // empty, undeletable item in the list (deleting it just spawns another).
    const newSid = sessionId;
    if (optimistic) {
        loadSessionList(() => _addOptimisticSessionItem(newSid));
    } else {
        loadSessionList();
    }
}

