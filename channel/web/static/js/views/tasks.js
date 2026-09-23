/* Scheduled tasks and execution records.
   Split out of console.js. These are classic scripts sharing one global
   scope; see channel/web/README.md before changing the load order. */

// =====================================================================
// Scheduler View
// =====================================================================
let tasksLoaded = false;
// Which sub-tab of the Tasks view is showing: 'tasks' | 'records'.
let tasksActiveTab = 'tasks';
let runsLoaded = false;

// Switch between the task list and the execution-record history. The header's
// add/refresh buttons and subtitle follow the active tab so the two panes share
// one chrome (mirrors the desktop client).
function switchTasksTab(tab) {
    tasksActiveTab = tab;
    const isTasks = tab === 'tasks';
    document.getElementById('tasks-pane').classList.toggle('hidden', !isTasks);
    document.getElementById('runs-pane').classList.toggle('hidden', isTasks);
    // Add button is only meaningful on the task list.
    const addBtn = document.getElementById('task-add-btn');
    if (addBtn) addBtn.classList.toggle('hidden', !isTasks);
    const subtitle = document.getElementById('tasks-subtitle');
    if (subtitle) subtitle.textContent = t(isTasks ? 'tasks_desc' : 'records_desc');

    // Tab visual state (active color + underline).
    [['tasks-tab-tasks', isTasks], ['tasks-tab-records', !isTasks]].forEach(([id, active]) => {
        const el = document.getElementById(id);
        if (!el) return;
        el.classList.toggle('text-primary-500', active);
        el.classList.toggle('text-slate-400', !active);
        el.classList.toggle('dark:text-slate-500', !active);
        const underline = el.querySelector('.tasks-tab-underline');
        if (underline) underline.classList.toggle('hidden', !active);
    });

    if (!isTasks) loadRunsView();
    routeNoteTab('tasks', tab);
}

function refreshTasksView() {
    const btn = document.getElementById('task-refresh-btn');
    const icon = btn.querySelector('i');
    
    // Add spin animation
    icon.classList.add('fa-spin');
    btn.disabled = true;
    
    if (tasksActiveTab === 'records') {
        runsLoaded = false;
        loadRunsView();
    } else {
    tasksLoaded = false;
    const listEl = document.getElementById('tasks-list');
    listEl.innerHTML = '';
    loadTasksView();
    }
    
    // Restore button after animation ends
    setTimeout(() => {
        icon.classList.remove('fa-spin');
        btn.disabled = false;
    }, 500);
}

// ---- Execution records (history) -----------------------------------------

// Format a Unix-seconds timestamp for display; '--' when absent/invalid.
function formatRunTime(sec) {
    if (!sec) return '--';
    const d = new Date(sec * 1000);
    return isNaN(d.getTime()) ? '--' : d.toLocaleString();
}

// Compact elapsed time between start and end (blank while still running).
function formatRunDuration(start, end) {
    if (!start || !end || end < start) return '';
    const s = end - start;
    if (s < 60) return `${s}s`;
    const m = Math.floor(s / 60);
    const r = s % 60;
    return r ? `${m}m ${r}s` : `${m}m`;
}

// Status pill (done / error / running) matching the task-card status dot palette.
function runStatusBadge(status) {
    if (status === 'done') {
        return `<span class="inline-flex items-center gap-1 text-emerald-500"><i class="fas fa-circle-check text-xs"></i><span class="text-xs font-medium">${t('records_status_done')}</span></span>`;
    }
    if (status === 'error') {
        return `<span class="inline-flex items-center gap-1 text-red-500"><i class="fas fa-circle-xmark text-xs"></i><span class="text-xs font-medium">${t('records_status_error')}</span></span>`;
    }
    return `<span class="inline-flex items-center gap-1 text-slate-400"><i class="fas fa-spinner fa-spin text-xs"></i><span class="text-xs font-medium">${t('records_status_running')}</span></span>`;
}

// A web task is delivered to a chat session, not a bound IM instance, so present
// it with the friendly web type / name instead of a bare type + empty name.
function runChannelDisplay(run) {
    const isWeb = run.channel_type === 'web' || (!run.channel_type && !run.instance_id);
    if (isWeb) return { type: t('record_channel_web_type'), name: t('record_channel_web_name') };
    const inst = (taskInstances || []).find(i => i.instance_id === run.instance_id);
    return { type: run.channel_type || '', name: (inst && inst.name) || run.instance_id || '' };
}

const RUNS_PAGE_SIZE = 30;
let runsOffset = 0;
let runsHasMore = false;
let runsLoadingMore = false;

function loadRunsView() {
    if (runsLoaded) return;
    const rosterReady = agentCatalog.length ? Promise.resolve() : loadAgentCatalog();
    const loadingEl = document.getElementById('runs-loading');
    const emptyEl = document.getElementById('runs-empty');
    const listEl = document.getElementById('runs-list');
    loadingEl.classList.remove('hidden'); loadingEl.classList.add('flex');
    emptyEl.classList.add('hidden'); listEl.classList.add('hidden');
    runsOffset = 0; runsHasMore = false;

    rosterReady.then(() => Promise.all([
        // Empty agent_id => whole team's history (not the active chat Agent).
        fetch(`/api/scheduler/runs?agent_id=&limit=${RUNS_PAGE_SIZE}&offset=0`).then(r => r.json()).catch(() => null),
        // Instances feed the friendly channel-name resolution; cached in taskInstances.
        (taskInstances && taskInstances.length)
            ? Promise.resolve({ status: 'success', instances: taskInstances })
            : fetch('/api/scheduler/instances').then(r => r.json()).catch(() => null),
    ])).then(([runData, instData]) => {
        runsLoaded = true;
        loadingEl.classList.add('hidden'); loadingEl.classList.remove('flex');
        if (instData && instData.status === 'success') taskInstances = instData.instances || [];
        const runs = (runData && runData.status === 'success') ? (runData.runs || []) : [];
        if (runs.length === 0) {
            emptyEl.classList.remove('hidden'); emptyEl.classList.add('flex');
            listEl.classList.add('hidden');
            return;
        }
        emptyEl.classList.add('hidden'); emptyEl.classList.remove('flex');
        listEl.classList.remove('hidden');
        listEl.innerHTML = '';
        runs.forEach(run => listEl.appendChild(renderRunCard(run)));
        runsOffset = runs.length;
        runsHasMore = runs.length >= RUNS_PAGE_SIZE;
        renderRunsLoadMore();
    });
}

// Append the next page of records. A full page implies there may be more.
function loadMoreRuns() {
    if (runsLoadingMore || !runsHasMore) return;
    runsLoadingMore = true;
    const btn = document.getElementById('runs-load-more-btn');
    if (btn) { btn.disabled = true; btn.innerHTML = `<i class="fas fa-spinner fa-spin mr-1"></i>${t('records_loading')}`; }
    fetch(`/api/scheduler/runs?agent_id=&limit=${RUNS_PAGE_SIZE}&offset=${runsOffset}`)
        .then(r => r.json()).catch(() => null)
        .then(data => {
            runsLoadingMore = false;
            const runs = (data && data.status === 'success') ? (data.runs || []) : [];
            const listEl = document.getElementById('runs-list');
            runs.forEach(run => listEl.appendChild(renderRunCard(run)));
            runsOffset += runs.length;
            runsHasMore = runs.length >= RUNS_PAGE_SIZE;
            renderRunsLoadMore();
        });
}

// Render (or remove) the "load more" footer button below the list.
function renderRunsLoadMore() {
    const listEl = document.getElementById('runs-list');
    if (!listEl) return;
    let footer = document.getElementById('runs-load-more');
    if (!runsHasMore) { if (footer) footer.remove(); return; }
    if (!footer) {
        footer = document.createElement('div');
        footer.id = 'runs-load-more';
        footer.className = 'flex justify-center py-3';
        footer.innerHTML = `<button id="runs-load-more-btn" class="px-4 py-1.5 text-sm rounded-lg border border-slate-200 dark:border-white/10 text-slate-500 dark:text-slate-400 hover:border-slate-300 dark:hover:border-white/20 transition-colors">${t('records_load_more')}</button>`;
        footer.querySelector('#runs-load-more-btn').addEventListener('click', loadMoreRuns);
    } else {
        const b = footer.querySelector('#runs-load-more-btn');
        if (b) { b.disabled = false; b.innerHTML = t('records_load_more'); }
    }
    listEl.parentElement.appendChild(footer);
}

function renderRunCard(run) {
    const card = document.createElement('div');
    card.className = 'bg-white dark:bg-[#1A1A1A] rounded-xl border border-slate-200 dark:border-white/10 p-4 cursor-pointer hover:border-slate-300 dark:hover:border-white/20 transition-colors';
    const owner = (multiAgentMode() && run.agent_id) ? findAgent(run.agent_id) : null;
    const ownerChip = owner
        ? `<span class="inline-flex items-center gap-1 pl-1 pr-1.5 py-0.5 rounded-full bg-slate-100 dark:bg-white/10 text-[10px] leading-none text-slate-400 dark:text-slate-500">${agentAvatarHTML(owner, 15)}<span class="truncate max-w-[80px]">${escapeHtml(owner.name || owner.id)}</span></span>`
        : '';
    const trigger = run.trigger === 'manual' ? t('records_trigger_manual') : t('records_trigger_scheduled');
    const duration = formatRunDuration(run.started_at, run.ended_at);
    const bodyLine = (run.status === 'error' && run.error)
        ? `<p class="text-xs text-red-500 mb-2 line-clamp-2 break-words">${escapeHtml(run.error)}</p>`
        : `<p class="text-xs text-slate-500 dark:text-slate-400 mb-2 line-clamp-2 break-words">${run.output_preview ? escapeHtml(run.output_preview) : `<span class="italic text-slate-400">${t('records_no_output')}</span>`}</p>`;
    card.innerHTML = `
        <div class="flex items-center gap-2 mb-1.5">
            ${runStatusBadge(run.status)}
            <span class="font-medium text-sm text-slate-700 dark:text-slate-200 truncate">${escapeHtml(run.task_name || run.task_id || t('tasks_tab_records'))}</span>
            ${ownerChip}
            <div class="flex-1"></div>
            <span class="text-[10px] px-1.5 py-0.5 rounded-full bg-slate-100 dark:bg-white/10 text-slate-400 dark:text-slate-500">${escapeHtml(trigger)}</span>
            <button class="run-delete-btn text-slate-300 hover:text-red-500 dark:text-slate-600 dark:hover:text-red-400 transition-colors px-1" title="${t('records_delete')}"><i class="fas fa-trash-can text-xs"></i></button>
        </div>
        ${bodyLine}
        <div class="flex items-center gap-2 text-xs text-slate-400 dark:text-slate-500">
            <i class="fas fa-clock"></i><span>${formatRunTime(run.started_at)}</span>
            ${duration ? `<span class="opacity-50">·</span><span>${t('records_duration')} ${duration}</span>` : ''}
        </div>`;
    card.addEventListener('click', () => showRunDetailModal(run));
    const delBtn = card.querySelector('.run-delete-btn');
    if (delBtn) {
        delBtn.addEventListener('click', (e) => {
            e.stopPropagation();   // don't open the detail modal
            deleteRunRecord(run, card);
        });
    }
    return card;
}

// Confirm, then delete one execution record and drop its card from the list.
function deleteRunRecord(run, card) {
    showConfirmDialog({
        title: t('records_delete_confirm_title'),
        message: t('records_delete_confirm_msg'),
        okText: t('records_delete'),
        onConfirm: () => {
            fetch('/api/scheduler/runs/delete', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ run_id: run.run_id })
            }).then(r => r.json()).then(res => {
                if (res.status !== 'success') throw new Error(res.message || 'delete failed');
                card.remove();
                if (runsOffset > 0) runsOffset -= 1;   // keep paging offset aligned
                const listEl = document.getElementById('runs-list');
                if (listEl && listEl.children.length === 0 && !runsHasMore) {
                    const emptyEl = document.getElementById('runs-empty');
                    listEl.classList.add('hidden');
                    if (emptyEl) { emptyEl.classList.remove('hidden'); emptyEl.classList.add('flex'); }
                }
            }).catch(() => {
                alert(t('records_delete_failed'));
            });
        }
    });
}

function showRunDetailModal(run) {
    const overlay = document.getElementById('run-detail-modal-overlay');
    document.getElementById('run-detail-title').textContent = run.task_name || run.task_id || t('record_detail_title');

    const ch = runChannelDisplay(run);
    const owner = (multiAgentMode() && run.agent_id) ? findAgent(run.agent_id) : null;
    const trigger = run.trigger === 'manual' ? t('records_trigger_manual') : t('records_trigger_scheduled');
    const duration = formatRunDuration(run.started_at, run.ended_at);
    const cell = (label, valueHtml) => `<div><div class="text-xs text-slate-400 dark:text-slate-500 mb-0.5">${label}</div><div class="text-slate-700 dark:text-slate-200">${valueHtml}</div></div>`;
    const meta = [];
    meta.push(cell(t('record_detail_status'), runStatusBadge(run.status)));
    meta.push(cell(t('record_detail_trigger'), escapeHtml(trigger)));
    meta.push(cell(t('record_detail_started'), escapeHtml(formatRunTime(run.started_at))));
    if (duration) meta.push(cell(t('record_detail_duration'), escapeHtml(duration)));
    if (ch.type) meta.push(cell(t('record_detail_channel_type'), escapeHtml(ch.type)));
    if (ch.name) meta.push(cell(t('record_detail_channel_name'), `<span class="break-all">${escapeHtml(ch.name)}</span>`));
    if (owner) meta.push(cell(t('record_detail_agent'), `<span class="inline-flex items-center gap-1.5">${agentAvatarHTML(owner, 16)}<span class="truncate max-w-[140px]">${escapeHtml(owner.name || owner.id)}</span></span>`));
    document.getElementById('run-detail-meta').innerHTML = meta.join('');

    const errWrap = document.getElementById('run-detail-error-wrap');
    if (run.status === 'error' && run.error) {
        errWrap.classList.remove('hidden');
        document.getElementById('run-detail-error').textContent = run.error;
    } else {
        errWrap.classList.add('hidden');
    }

    const outEl = document.getElementById('run-detail-output');
    // Show the preview immediately, then swap in the full body once fetched.
    outEl.innerHTML = `<span class="text-slate-400"><i class="fas fa-spinner fa-spin mr-1"></i>${t('record_detail_loading')}</span>`;
    runDetailBody = '';
    runDetailView = 'preview';  // always default to rendered markdown on open
    updateRunDetailViewToggle();
    overlay.classList.remove('hidden');

    fetch(`/api/scheduler/runs/detail?run_id=${encodeURIComponent(run.run_id)}`)
        .then(r => r.json())
        .then(data => {
            const detail = (data && data.status === 'success') ? data.run : null;
            const body = (detail && detail.full_output) || run.output_preview || '';
            runDetailBody = body;
            renderRunDetailOutput();
        })
        .catch(() => {
            runDetailBody = run.output_preview || '';
            renderRunDetailOutput();
        });
}

// The run-detail output can be shown as rendered Markdown (default) or as raw
// text. We keep the fetched body around so toggling between the two views never
// needs a refetch.
let runDetailBody = '';
let runDetailView = 'preview';  // 'preview' (markdown) | 'text' (raw)

function renderRunDetailOutput() {
    const outEl = document.getElementById('run-detail-output');
    if (!outEl) return;
    if (!runDetailBody) {
        outEl.classList.remove('whitespace-pre-wrap');
        outEl.innerHTML = `<span class="italic text-slate-400">${t('records_no_output')}</span>`;
        return;
    }
    if (runDetailView === 'text') {
        // Raw text: preserve newlines/indentation, no markdown parsing.
        outEl.classList.add('whitespace-pre-wrap');
        outEl.textContent = runDetailBody;
    } else {
        outEl.classList.remove('whitespace-pre-wrap');
        // Use .msg-content (not just .agent-content-body): the full markdown
        // styling — paragraph spacing, headings, lists, tables, code — is scoped
        // to .msg-content. Without it Tailwind's preflight resets p/h margins to
        // 0, so a multi-paragraph body renders as one flat block with no visible
        // breaks (the "no markdown newlines" bug).
        outEl.innerHTML = `<div class="msg-content agent-content-body">${renderMarkdown(runDetailBody)}</div>`;
    }
}

function updateRunDetailViewToggle() {
    const toggle = document.getElementById('run-detail-view-toggle');
    if (!toggle) return;
    toggle.querySelectorAll('button[data-view]').forEach(btn => {
        const active = btn.dataset.view === runDetailView;
        btn.classList.toggle('bg-slate-800', active);
        btn.classList.toggle('dark:bg-white/15', active);
        btn.classList.toggle('text-white', active);
        btn.classList.toggle('dark:text-white', active);
        btn.classList.toggle('text-slate-500', !active);
        btn.classList.toggle('dark:text-slate-400', !active);
    });
}

function setRunDetailView(view) {
    if (view !== 'preview' && view !== 'text') return;
    runDetailView = view;
    updateRunDetailViewToggle();
    renderRunDetailOutput();
}

(function wireRunDetailModal() {
    const overlay = document.getElementById('run-detail-modal-overlay');
    if (!overlay) return;
    const close = () => overlay.classList.add('hidden');
    const closeBtn = document.getElementById('run-detail-close');
    if (closeBtn) closeBtn.addEventListener('click', close);
    overlay.addEventListener('click', (e) => { if (e.target === overlay) close(); });
    const toggle = document.getElementById('run-detail-view-toggle');
    if (toggle) {
        toggle.querySelectorAll('button[data-view]').forEach(btn => {
            btn.addEventListener('click', () => setRunDetailView(btn.dataset.view));
        });
    }
})();

function runTaskNow(task, button) {
    showConfirmDialog({
        title: t('task_run_confirm_title'),
        message: `${task.name || task.id}: ${t('task_run_confirm_msg')}`,
        okText: t('task_run_now'),
        onConfirm: () => {
            const originalHtml = button.innerHTML;
            button.disabled = true;
            button.innerHTML = `<i class="fas fa-spinner fa-spin mr-1"></i>${t('task_run_now')}`;
            fetch('/api/scheduler/run', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({task_id: task.id, agent_id: task.agent_id || ''})
            }).then(r => r.json()).then(res => {
                if (res.status !== 'success') throw new Error(res.message || t('task_run_failed'));
                // Remember this tab kicked off the run so its notification is
                // routed back here (see maybeNotifyScheduledRun), not to some
                // other tab that also happens to have this session open.
                _claimManualRunOrigin(task.id);
                button.innerHTML = `<i class="fas fa-check mr-1"></i>${t('task_run_started')}`;
                setTimeout(() => {
                    button.innerHTML = originalHtml;
                    button.disabled = false;
                }, 1500);
            }).catch(() => {
                button.innerHTML = `<i class="fas fa-triangle-exclamation mr-1"></i>${t('task_run_failed')}`;
                setTimeout(() => {
                    button.innerHTML = originalHtml;
                    button.disabled = false;
                }, 2000);
            });
        }
    });
}

function loadTasksView() {
    if (tasksLoaded) return;
    // The list tags each task with an owning Agent; make sure the roster is in
    // hand first so findAgent()/multiAgentMode() can resolve the avatar + name.
    const rosterReady = agentCatalog.length ? Promise.resolve() : loadAgentCatalog();
    rosterReady.then(() => {
    // Explicit empty agent_id so the global fetch wrapper doesn't inject the
    // active chat Agent: the task list is the whole team's schedule and must
    // NOT follow whichever Agent the conversation is currently on. The backend
    // treats an empty agent_id as "aggregate across all Agents".
    fetch('/api/scheduler?agent_id=').then(r => r.json()).then(data => {
        if (data.status !== 'success') return;
        const emptyEl = document.getElementById('tasks-empty');
        const listEl = document.getElementById('tasks-list');
        const allTasks = data.tasks || [];
        // Backend already sorted by enabled and next_run_at, no need to re-sort on frontend
        if (allTasks.length === 0) {
            emptyEl.querySelector('p').textContent = 'No scheduled tasks';
            emptyEl.classList.remove('hidden');
            listEl.classList.add('hidden');
            tasksLoaded = true;
            return;
        }
        emptyEl.classList.add('hidden');
        listEl.classList.remove('hidden');
        listEl.innerHTML = '';

        allTasks.forEach(task => {
            const isEnabled = task.enabled !== false;
            const card = document.createElement('div');
            card.className = 'bg-white dark:bg-[#1A1A1A] rounded-xl border border-slate-200 dark:border-white/10 p-4';
            card.dataset.taskId = task.id;
            if (!isEnabled) card.classList.add('opacity-50');
            const schedule = task.schedule || {};
            let typeLabel = '';
            if (schedule.type === 'cron') {
                typeLabel = `<span class="text-xs font-mono text-slate-400">${escapeHtml(schedule.expression || '')}</span>`;
            } else if (schedule.type === 'interval') {
                const seconds = schedule.seconds || 0;
                const hours = Math.floor(seconds / 3600);
                const mins = Math.floor((seconds % 3600) / 60);
                const secs = seconds % 60;
                let intervalText = [];
                if (hours > 0) intervalText.push(`${hours}h`);
                if (mins > 0) intervalText.push(`${mins}m`);
                if (secs > 0 || intervalText.length === 0) intervalText.push(`${secs}s`);
                typeLabel = `<span class="text-xs text-slate-400">${intervalText.join(' ')}</span>`;
            } else {
                typeLabel = `<span class="text-xs text-slate-400">${escapeHtml(schedule.type || 'once')}</span>`;
            }
            let nextRun = '--';
            if (task.next_run_at) {
                const d = new Date(task.next_run_at);
                if (!isNaN(d.getTime())) nextRun = d.toLocaleString();
            }
            const action = task.action || {};
            const taskContent = action.content || action.task_description || '';
            const toggleId = 'toggle-' + task.id;
            // Owner chip: only when several Agents exist (otherwise every task
            // carries the same face and it's just noise). Empty on a solo install.
            const owner = (multiAgentMode() && task.agent_id) ? findAgent(task.agent_id) : null;
            const ownerChip = owner
                ? `<span class="inline-flex items-center gap-1 ml-2 pl-1 pr-1.5 py-0.5 rounded-full bg-slate-100 dark:bg-white/10 text-[10px] leading-none text-slate-400 dark:text-slate-500">
                        ${agentAvatarHTML(owner, 15)}<span class="truncate max-w-[80px]">${escapeHtml(owner.name || owner.id)}</span>
                   </span>`
                : '';
            card.innerHTML = `
                <div class="flex items-center gap-2 mb-2">
                    <span class="w-2 h-2 rounded-full ${isEnabled ? 'bg-primary-400' : 'bg-slate-300 dark:bg-slate-600'}"></span>
                    <span class="font-medium text-sm text-slate-700 dark:text-slate-200">${escapeHtml(task.name || task.id || '--')}</span>
                    ${ownerChip}
                    <div class="flex-1"></div>
                    ${typeLabel}
                </div>
                <p class="text-xs text-slate-500 dark:text-slate-400 mb-2 line-clamp-2">${escapeHtml(taskContent)}</p>
                <div class="flex items-center gap-4 text-xs text-slate-400 dark:text-slate-500">
                    <span><i class="fas fa-clock mr-1"></i>Next run: ${nextRun}</span>
                    <div class="flex-1"></div>
                    <button type="button" class="task-run-now px-2 py-1 rounded-md text-primary-500 hover:bg-primary-50 dark:hover:bg-primary-500/10 transition-colors">
                        <i class="fas fa-play mr-1"></i>${t('task_run_now')}
                    </button>
                    <label class="relative inline-flex items-center cursor-pointer" for="${toggleId}">
                        <input type="checkbox" id="${toggleId}" class="sr-only peer" ${isEnabled ? 'checked' : ''}>
                        <div class="w-9 h-5 bg-slate-200 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:bg-primary-500 dark:bg-slate-600 dark:peer-checked:bg-primary-500"></div>
                    </label>
                </div>`;
            const runButton = card.querySelector('.task-run-now');
            runButton.addEventListener('click', function(e) {
                e.stopPropagation();
                runTaskNow(task, runButton);
            });
            const checkbox = card.querySelector('#' + toggleId);
            checkbox.addEventListener('change', function() {
                const newEnabled = this.checked;
                fetch('/api/scheduler/toggle', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({task_id: task.id, enabled: newEnabled, agent_id: task.agent_id || ''})
                }).then(r => r.json()).then(res => {
                    if (res.status === 'success') {
                        const dot = card.querySelector('.rounded-full.w-2');
                        if (newEnabled) {
                            card.classList.remove('opacity-50');
                            if (dot) { dot.classList.remove('bg-slate-300','dark:bg-slate-600'); dot.classList.add('bg-primary-400'); }
                        } else {
                            card.classList.add('opacity-50');
                            if (dot) { dot.classList.remove('bg-primary-400'); dot.classList.add('bg-slate-300','dark:bg-slate-600'); }
                        }
                    } else {
                        this.checked = !newEnabled;
                    }
                }).catch(() => { this.checked = !newEnabled; });
            });
            // Card click event (excluding toggle switch clicks)
            card.addEventListener('click', function(e) {
                if (!e.target.closest('label') && !e.target.closest('input[type="checkbox"]')) {
                    openTaskEditModal(task);
                }
            });
            card.style.cursor = 'pointer';
            listEl.appendChild(card);
        });
        tasksLoaded = true;
    }).catch(() => {});
    });
}

