/* Approvals: the header bell and its inbox, the approve / reject / edit
   dialog, the inline card under a gated tool call, and the light poll that
   keeps them (and the task board) current. These are classic scripts sharing
   one global scope; see channel/web/README.md before changing the load order. */

const APPROVAL_POLL_MS = 10000;

let approvalPending = [];
let approvalPendingCount = -1;
let approvalSince = 0;
let approvalPollTimer = null;
let approvalDecideCtx = null;

// ---- Approval block: shared by board cards, the inbox, the detail dialog
// and the chat stream -------------------------------------------------------------

function renderApprovalBlock(appr, opts) {
    opts = opts || {};
    const isAccept = appr.kind === 'accept';
    const el = document.createElement('div');
    el.className = 'approval-block' + (isAccept ? ' is-accept' : '');
    el.dataset.approvalId = appr.id;
    el.dataset.pending = '1';
    const head = isAccept
        ? `<i class="fas fa-clipboard-check"></i><span>${escapeHtml(t('approval_kind_accept'))}</span>`
        : `<i class="fas fa-shield-halved"></i><span class="truncate">${escapeHtml(appr.label || appr.tool_name || t('approval_kind_action'))}</span>`;
    const summaryText = isAccept ? boardPlainText(appr.summary) : appr.summary;
    const summary = summaryText
        ? `<div class="approval-block-summary${isAccept ? ' is-text' : ''}">${escapeHtml(summaryText)}</div>` : '';
    const approveText = t(isAccept ? 'approval_accept' : 'approval_approve');
    const rejectText = t(isAccept ? 'approval_rework' : 'approval_reject');
    const more = isAccept ? '' : `
        <button class="board-btn board-btn-link" data-act="edit" title="${escapeHtml(t('approval_more_tip'))}">
            <i class="fas fa-sliders"></i>${opts.compact ? '' : escapeHtml(t('approval_more'))}
        </button>`;
    el.innerHTML = `
        <div class="approval-block-head">${head}<span class="aid">#${appr.id}</span></div>
        ${summary}
        <div class="approval-actions">
            <button class="board-btn board-btn-primary" data-act="approve"><i class="fas fa-check"></i>${escapeHtml(approveText)}</button>
            <button class="board-btn board-btn-ghost" data-act="reject">${escapeHtml(rejectText)}</button>
            <span class="grow"></span>
            ${more}
        </div>`;
    el.querySelectorAll('[data-act]').forEach(btn => btn.addEventListener('click', (e) => {
        e.stopPropagation();
        const act = btn.dataset.act;
        if (act === 'approve') quickApprove(appr, el);
        else openApprovalDecide(appr, act, el);
    }));
    return el;
}

function settleApprovalBlocks(approvalId, status) {
    document.querySelectorAll(`.approval-block[data-approval-id="${approvalId}"]`).forEach(el => {
        if (el.dataset.pending !== '1') return;
        el.dataset.pending = '0';
        const actions = el.querySelector('.approval-actions');
        if (!actions) return;
        const map = {
            approved: ['is-approved', 'fa-circle-check', 'approval_state_approved'],
            rejected: ['is-rejected', 'fa-circle-xmark', 'approval_state_rejected'],
            expired:  ['is-expired', 'fa-circle-minus', 'approval_state_expired'],
            handled:  ['is-expired', 'fa-circle-check', 'approval_state_handled'],
        };
        const [cls, icon, key] = map[status] || map.handled;
        actions.innerHTML = `<span class="approval-state ${cls}"><i class="fas ${icon}"></i>${escapeHtml(t(key))}</span>`;
    });
}

function setApprovalBlockError(el, message) {
    if (!el) { alert(message); return; }
    let err = el.querySelector('.approval-block-error');
    if (!err) {
        err = document.createElement('div');
        err.className = 'approval-block-error text-xs text-red-500 mt-1.5';
        el.appendChild(err);
    }
    err.textContent = message;
}

// ---- Deciding ----------------------------------------------------------------

function postApprovalDecision(appr, payload) {
    return fetch(`/api/approvals/${appr.id}/decide`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
    }).then(r => r.json()).then(data => {
        if (!data || data.status !== 'success') throw new Error((data && data.message) || t('board_action_failed'));
        settleApprovalBlocks(appr.id, data.approval && data.approval.status);
        followApprovalResume(data.resume);
        refreshApprovals();
        if (typeof currentView !== 'undefined' && currentView === 'tasks' && tasksActiveTab === 'board') loadTaskBoard();
        const detail = document.getElementById('board-detail-modal-overlay');
        if (detail && !detail.classList.contains('hidden') && boardDetailTask && boardDetailTask.id === appr.task_id) {
            refreshBoardDetail(appr.task_id);
        }
        return data;
    });
}

function quickApprove(appr, el) {
    const buttons = el ? el.querySelectorAll('.approval-actions button') : [];
    buttons.forEach(b => { b.disabled = true; });
    postApprovalDecision(appr, { decision: 'approve' })
        .catch(err => {
            buttons.forEach(b => { b.disabled = false; });
            setApprovalBlockError(el, err.message);
        });
}

const DECIDE_TONES = {
    danger: ['bg-red-500', 'hover:bg-red-600'],
    primary: ['bg-primary-500', 'hover:bg-primary-600'],
};

function setDecideSubmitTone(btn, tone) {
    Object.values(DECIDE_TONES).forEach(cls => btn.classList.remove(...cls));
    btn.classList.add(...DECIDE_TONES[tone]);
}

// mode: 'reject' asks for a note; 'edit' shows the call's arguments and the
// "always allow" switch, then approves.
function openApprovalDecide(appr, mode, el) {
    const isAccept = appr.kind === 'accept';
    approvalDecideCtx = { appr, mode, el };
    const icon = document.getElementById('approval-decide-icon');
    const submit = document.getElementById('approval-decide-submit');
    const argsWrap = document.getElementById('approval-decide-args-wrap');
    const noteWrap = document.getElementById('approval-decide-note-wrap');
    const alwaysWrap = document.getElementById('approval-decide-always-wrap');
    const error = document.getElementById('approval-decide-error');
    error.classList.add('hidden');
    document.getElementById('approval-decide-note').value = '';
    document.getElementById('approval-decide-always').checked = false;
    document.getElementById('approval-decide-sub').textContent =
        `#${appr.id} · ${isAccept ? (appr.label || appr.task_title || '') : (appr.label || appr.tool_name || '')}`;

    if (mode === 'reject') {
        icon.className = 'w-10 h-10 rounded-xl flex items-center justify-center flex-shrink-0 bg-red-50 dark:bg-red-900/20';
        icon.innerHTML = '<i class="fas fa-reply text-red-500"></i>';
        document.getElementById('approval-decide-title').textContent = t(isAccept ? 'approval_rework_title' : 'approval_reject_title');
        document.getElementById('approval-decide-note-label').textContent = t(isAccept ? 'approval_rework_note' : 'approval_reject_note');
        document.getElementById('approval-decide-note').placeholder = t(isAccept ? 'approval_rework_placeholder' : 'approval_reject_placeholder');
        argsWrap.classList.add('hidden');
        alwaysWrap.classList.add('hidden');
        noteWrap.classList.remove('hidden');
        setDecideSubmitTone(submit, 'danger');
        submit.textContent = t(isAccept ? 'approval_rework' : 'approval_reject');
    } else {
        icon.className = 'w-10 h-10 rounded-xl flex items-center justify-center flex-shrink-0 bg-primary-50 dark:bg-primary-900/20';
        icon.innerHTML = '<i class="fas fa-sliders text-primary-500"></i>';
        document.getElementById('approval-decide-title').textContent = t('approval_edit_title');
        let args = appr.tool_args;
        if (typeof args === 'string') { try { args = JSON.parse(args); } catch (_) { /* shown as-is */ } }
        document.getElementById('approval-decide-args').value =
            typeof args === 'string' ? args : JSON.stringify(args || {}, null, 2);
        argsWrap.classList.remove('hidden');
        noteWrap.classList.add('hidden');
        alwaysWrap.classList.toggle('hidden', !appr.rule_id);
        setDecideSubmitTone(submit, 'primary');
        submit.textContent = t('approval_approve');
    }
    document.getElementById('approval-decide-modal-overlay').classList.remove('hidden');
    setTimeout(() => {
        const focus = document.getElementById(mode === 'reject' ? 'approval-decide-note' : 'approval-decide-args');
        if (focus) focus.focus();
    }, 30);
}

function submitApprovalDecide() {
    const ctx = approvalDecideCtx;
    if (!ctx) return;
    const error = document.getElementById('approval-decide-error');
    const showError = (msg) => { error.textContent = msg; error.classList.remove('hidden'); };
    let payload;
    if (ctx.mode === 'reject') {
        payload = { decision: 'reject', note: document.getElementById('approval-decide-note').value.trim() };
    } else {
        const raw = document.getElementById('approval-decide-args').value.trim();
        let args;
        try { args = raw ? JSON.parse(raw) : {}; } catch (_) { showError(t('approval_args_invalid')); return; }
        if (!args || typeof args !== 'object' || Array.isArray(args)) { showError(t('approval_args_invalid')); return; }
        payload = { decision: 'approve', tool_args: args, always_auto: document.getElementById('approval-decide-always').checked };
    }
    const submit = document.getElementById('approval-decide-submit');
    submit.disabled = true;
    postApprovalDecision(ctx.appr, payload)
        .then(() => {
            document.getElementById('approval-decide-modal-overlay').classList.add('hidden');
            approvalDecideCtx = null;
        })
        .catch(err => showError(err.message))
        .finally(() => { submit.disabled = false; });
}

function sameAgentId(a, b) {
    const norm = (id) => (!id || id === 'default') ? (defaultAgentId || '') : id;
    return norm(a) === norm(b);
}

// An approval from a web conversation continues that conversation server-side.
// When it is the one on screen, follow the new turn like a typed one.
function followApprovalResume(resume) {
    if (!resume || !resume.request_id) return;
    if (currentView !== 'chat' || resume.session_id !== sessionId || !sameAgentId(resume.agent_id, activeAgentId)) return;
    if (resume.display) addUserMessage(resume.display, new Date());
    const loadingEl = addLoadingIndicator();
    setSendBtnCancelMode(resume.request_id);
    startSSE(resume.request_id, loadingEl, new Date());
}

function openApprovalSession(appr) {
    closeApprovalInbox();
    if (appr.task_id) {
        navigateTo('tasks');
        if (taskFeatureEnabled && tasksActiveTab !== 'board') switchTasksTab('board');
        openBoardDetail(appr.task_id);
        return;
    }
    if (appr.origin_channel === 'web' && appr.origin_session_id) {
        switchSession(appr.origin_session_id, appr.agent_id);
    }
}

// ---- Inline card in a chat turn -----------------------------------------------

function appendInlineApproval(toolEl, item) {
    if (!toolEl || !toolEl.parentElement || !item.approval_id) return;
    const icon = toolEl.querySelector('.tool-icon');
    if (icon) icon.className = 'fas fa-hand text-amber-500 flex-shrink-0 tool-icon';
    if (toolEl.parentElement.querySelector(`.approval-block[data-approval-id="${item.approval_id}"]`)) return;
    const wrap = document.createElement('div');
    wrap.className = 'approval-inline';
    const appr = {
        id: item.approval_id,
        kind: 'action',
        label: item.approval_label || item.tool || '',
        tool_name: item.tool || '',
        summary: item.approval_summary || '',
    };
    const block = renderApprovalBlock(appr, {});
    wrap.appendChild(block);
    toolEl.parentElement.insertBefore(wrap, toolEl.nextElementSibling);
    // The edit dialog needs the saved call and its rule; fetch them lazily.
    const known = approvalPending.find(a => a.id === appr.id);
    if (known) Object.assign(appr, known);
    else refreshApprovals().then(() => {
        const fresh = approvalPending.find(a => a.id === appr.id);
        if (fresh) Object.assign(appr, fresh);
    });
}

// ---- Bell and inbox ------------------------------------------------------------------

function renderApprovalInbox(list) {
    approvalPending = list || [];
    const pendingIds = new Set(approvalPending.map(a => a.id));
    document.querySelectorAll('.approval-block[data-pending="1"]').forEach(el => {
        if (!pendingIds.has(+el.dataset.approvalId)) settleApprovalBlocks(el.dataset.approvalId, 'handled');
    });
    setApprovalCount(approvalPending.length);

    const listEl = document.getElementById('approval-inbox-list');
    if (!listEl) return;
    if (!approvalPending.length) {
        listEl.innerHTML = `<div class="approval-inbox-empty"><i class="fas fa-circle-check"></i>${escapeHtml(t('inbox_empty'))}</div>`;
        return;
    }
    listEl.innerHTML = '';
    approvalPending.forEach(appr => {
        const item = document.createElement('div');
        item.className = 'inbox-item';
        item.appendChild(renderApprovalBlock(appr, { compact: true }));
        let origin = '';
        if (appr.task_id) {
            origin = `${t('inbox_from_task')} #${appr.task_id}${appr.task_title ? ' · ' + appr.task_title : ''}`;
        } else if (appr.origin_channel === 'web') {
            origin = t('board_from_web_chat');
        } else if (appr.origin_channel) {
            origin = `${t('board_from_chat')} · ${appr.origin_channel}`;
        }
        if (origin) {
            const originEl = document.createElement('div');
            originEl.className = 'inbox-item-origin';
            originEl.innerHTML = `<i class="fas fa-arrow-up-right-from-square text-[9px] mr-1"></i>${escapeHtml(origin)} · ${escapeHtml(boardRelTime(appr.created_at))}`;
            if (appr.task_id || (appr.origin_channel === 'web' && appr.origin_session_id)) {
                originEl.addEventListener('click', () => openApprovalSession(appr));
            } else {
                originEl.style.cursor = 'default';
            }
            item.appendChild(originEl);
        }
        listEl.appendChild(item);
    });
}

function setApprovalCount(count) {
    const badge = document.getElementById('approval-bell-badge');
    const btn = document.getElementById('approval-bell-btn');
    if (badge) {
        badge.textContent = count > 99 ? '99+' : String(count);
        badge.classList.toggle('hidden', !count);
    }
    if (btn) {
        // Re-trigger the nudge only when something new arrives.
        if (count > Math.max(approvalPendingCount, 0)) {
            btn.classList.remove('has-pending');
            void btn.offsetWidth;
            btn.classList.add('has-pending');
        } else if (!count) {
            btn.classList.remove('has-pending');
        }
    }
    approvalPendingCount = count;
    if (typeof updateBoardTabBadge === 'function') updateBoardTabBadge(count);
}

function refreshApprovals() {
    return fetch('/api/approvals?status=pending&agent_id=')
        .then(r => r.json())
        .then(data => {
            if (data && data.status === 'success') renderApprovalInbox(data.approvals || []);
        })
        .catch(() => {});
}

function toggleApprovalInbox(event) {
    if (event) { event.preventDefault(); event.stopPropagation(); }
    const inbox = document.getElementById('approval-inbox');
    if (!inbox) return;
    if (!inbox.classList.contains('hidden')) { closeApprovalInbox(); return; }
    inbox.classList.remove('hidden');
    // The bell's tooltip would sit on top of the panel's own header.
    const btn = document.getElementById('approval-bell-btn');
    if (btn) btn.removeAttribute('data-tooltip');
    refreshApprovals();
}

function closeApprovalInbox() {
    const inbox = document.getElementById('approval-inbox');
    if (!inbox || inbox.classList.contains('hidden')) return;
    inbox.classList.add('hidden');
    const btn = document.getElementById('approval-bell-btn');
    if (btn) btn.setAttribute('data-tooltip', t('inbox_title'));
}

function openTaskBoardFromInbox() {
    closeApprovalInbox();
    navigateTo('tasks');
    if (taskFeatureEnabled && tasksActiveTab !== 'board') switchTasksTab('board');
}

document.addEventListener('click', (e) => {
    const inbox = document.getElementById('approval-inbox');
    if (!inbox || inbox.classList.contains('hidden')) return;
    // A decision dialog opened from the inbox sits outside it.
    if (e.target.closest('#approval-bell') || e.target.closest('#approval-decide-modal-overlay')) return;
    closeApprovalInbox();
});
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') closeApprovalInbox();
});

// ---- Poll -------------------------------------------------------------------------------

function notifyTaskEvent(ev) {
    if (typeof forceScheduledNotification !== 'function') return;
    if (ev.type === 'approval') {
        // Already in front of the user as an inline card.
        if (!document.hidden && document.querySelector(`.approval-block[data-approval-id="${ev.id}"]`)) return;
        const title = t(ev.kind === 'accept' ? 'notify_accept_title' : 'notify_approval_title');
        forceScheduledNotification(title, [ev.label, ev.summary].filter(Boolean).join(' · ').slice(0, 120), null, null);
    } else if (ev.type === 'task_done') {
        // Scheduled runs announce themselves through the schedule's delivery,
        // and a web conversation's result arrives there as a pushed reply.
        if (ev.source === 'schedule' || ev.notify_level !== 'all' || ev.origin_channel === 'web') return;
        forceScheduledNotification(t('notify_task_done_title').replace('{id}', ev.id), ev.title || '', null, null);
    } else if (ev.type === 'task_failed') {
        forceScheduledNotification(t('notify_task_failed_title').replace('{id}', ev.id), ev.title || '', null, null);
    }
}

function pollTaskSummary() {
    clearTimeout(approvalPollTimer);
    fetch(`/api/tasks/summary?since=${approvalSince}&agent_id=`)
        .then(r => r.json())
        .then(data => {
            if (!data || data.status !== 'success') return;
            setTaskFeatureEnabled(data.enabled);
            if (!data.enabled) {
                approvalSince = data.now || 0;
                return;
            }
            const events = data.events || [];
            events.forEach(notifyTaskEvent);
            if (events.length || data.pending_approvals !== approvalPendingCount) {
                refreshApprovals();
                if (currentView === 'tasks' && tasksActiveTab === 'board') loadTaskBoard();
            }
            approvalSince = data.now || approvalSince;
        })
        .catch(() => {})
        .finally(() => {
            clearTimeout(approvalPollTimer);
            // Switched off there is nothing to watch; saving the config asks again.
            if (!taskFeatureEnabled) return;
            approvalPollTimer = setTimeout(pollTaskSummary, document.hidden ? APPROVAL_POLL_MS * 3 : APPROVAL_POLL_MS);
        });
}

(function wireApprovals() {
    const submit = document.getElementById('approval-decide-submit');
    if (submit) submit.addEventListener('click', submitApprovalDecide);
    const note = document.getElementById('approval-decide-note');
    if (note) note.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) submitApprovalDecide();
    });
    document.addEventListener('visibilitychange', () => {
        if (!document.hidden && approvalSince && taskFeatureEnabled) pollTaskSummary();
    });
    window.addEventListener('load', () => requestAuthGatedStart(pollTaskSummary));
})();
