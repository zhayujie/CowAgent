/* Task detail: a task's run reads the way a chat does (the same bubbles, steps
   and live stream), with a composer to add to it and the task's facts and
   pending decisions alongside. Classic script sharing the console's global
   scope; loads after task-board.js and the chat scripts it renders with. */

let boardDetailTask = null;
let boardDetailLoad = 0;
let boardDetailStream = null;
let boardDetailPollTimer = null;
let boardDetailSending = false;

const BOARD_DETAIL_POLL_MS = 3000;
const BOARD_DETAIL_PAGE = 100;

const BOARD_STATUS_META = {
    queued:    { icon: 'fa-hourglass-half', tint: 'bg-slate-100 dark:bg-white/10', color: 'text-slate-500', label: 'board_lane_queued' },
    running:   { icon: 'fa-spinner fa-spin', tint: 'bg-sky-50 dark:bg-sky-500/10', color: 'text-sky-500', label: 'board_lane_running' },
    waiting:   { icon: 'fa-hand', tint: 'bg-amber-50 dark:bg-amber-500/10', color: 'text-amber-500', label: 'board_lane_waiting' },
    done:      { icon: 'fa-circle-check', tint: 'bg-primary-50 dark:bg-primary-900/20', color: 'text-primary-500', label: 'board_lane_done' },
    failed:    { icon: 'fa-circle-xmark', tint: 'bg-red-50 dark:bg-red-500/10', color: 'text-red-500', label: 'board_status_failed' },
    cancelled: { icon: 'fa-ban', tint: 'bg-slate-100 dark:bg-white/10', color: 'text-slate-400', label: 'board_status_cancelled' },
};

function boardDetailEl(id) { return document.getElementById(`board-detail-${id}`); }

function boardDetailShowing(taskId) {
    return !boardModal('board-detail-modal-overlay').classList.contains('hidden')
        && !!boardDetailTask && boardDetailTask.id === taskId;
}

function boardStatusText(task) {
    if (task.status === 'waiting') return t(task.wait_type === 'accept' ? 'board_wait_accept' : 'board_wait_approval');
    return t((BOARD_STATUS_META[task.status] || BOARD_STATUS_META.queued).label);
}

function setBoardDetailIcon(meta, icon) {
    const el = boardDetailEl('icon');
    el.className = `w-9 h-9 rounded-xl flex items-center justify-center flex-shrink-0 ${meta.tint}`;
    el.innerHTML = `<i class="fas ${icon || meta.icon} ${meta.color}"></i>`;
}

function stopBoardDetailLive() {
    if (boardDetailPollTimer) { clearTimeout(boardDetailPollTimer); boardDetailPollTimer = null; }
    if (boardDetailStream) { boardDetailStream.stop(); boardDetailStream = null; }
}

// ---- Open -------------------------------------------------------------------------

function openBoardDetail(taskId) {
    stopBoardDetailLive();
    boardDetailTask = null;
    setBoardDetailIcon(BOARD_STATUS_META.queued, 'fa-spinner fa-spin');
    boardDetailEl('title').textContent = `#${taskId}`;
    boardDetailEl('sub').textContent = '';
    boardDetailEl('chat').innerHTML = boardDetailNotice(`<i class="fas fa-spinner fa-spin mr-2"></i>${escapeHtml(t('board_loading'))}`);
    boardDetailEl('chat').dataset.taskId = '';
    boardDetailEl('side').innerHTML = '';
    boardDetailEl('side').classList.remove('hidden');
    boardDetailEl('composer').classList.add('hidden');
    boardDetailEl('actions').classList.add('hidden');
    boardModal('board-detail-modal-overlay').classList.remove('hidden');
    refreshBoardDetail(taskId);
}

// A chat approval has no task to show, so the dialog holds just the request
// and a way back to the conversation that asked.
function openApprovalDetail(appr) {
    stopBoardDetailLive();
    boardDetailTask = null;
    setBoardDetailIcon(BOARD_STATUS_META.waiting, 'fa-shield-halved');
    boardDetailEl('title').textContent = appr.label || appr.tool_name || '';
    boardDetailEl('sub').textContent = `${t('board_wait_approval')} · ${boardApprovalOrigin(appr)}`;
    boardDetailEl('actions').classList.add('hidden');
    boardDetailEl('composer').classList.add('hidden');

    const canOpen = appr.origin_channel === 'web' && appr.origin_session_id;
    const chat = boardDetailEl('chat');
    chat.innerHTML = `
        <div class="bd-approval-only">
            <div id="bd-pending"></div>
            ${canOpen ? `<button class="board-btn board-btn-link mt-3" id="bd-open-chat"><i class="fas fa-arrow-up-right-from-square"></i>${escapeHtml(t('board_open_chat'))}</button>` : ''}
        </div>`;
    document.getElementById('bd-pending').appendChild(renderApprovalBlock(appr, { withEdit: true }));
    const openBtn = document.getElementById('bd-open-chat');
    if (openBtn) openBtn.addEventListener('click', () => {
        closeBoardModal('board-detail-modal-overlay');
        openApprovalSession(appr);
    });
    boardDetailEl('side').innerHTML = boardSideFacts([
        [t('board_meta_source'), `<span class="board-chip"><i class="fas fa-comment-dots"></i>${escapeHtml(boardApprovalOrigin(appr))}</span>`],
        [t('record_detail_agent'), boardOwner(appr.agent_id)],
        [t('board_meta_created'), escapeHtml(new Date(appr.created_at * 1000).toLocaleString())],
    ]);
    boardModal('board-detail-modal-overlay').classList.remove('hidden');
}

// ---- Load -------------------------------------------------------------------------

// The task and, when its run moved on, the transcript. A live stream owns
// the transcript while it runs, so only the facts are redrawn under it.
function refreshBoardDetail(taskId) {
    const load = ++boardDetailLoad;
    return boardFetchJSON(`/api/tasks/${taskId}`).then(data => {
        if (load !== boardDetailLoad) return;
        const prev = boardDetailTask && boardDetailTask.id === data.task.id ? boardDetailTask : null;
        const task = data.task;
        boardDetailTask = task;
        renderBoardDetailHead(task);
        renderBoardDetailSide(task, data.approvals || []);
        renderBoardDetailComposer(task);
        if (boardDetailStream) return;
        // A running task with no stream yet is about to have one, or runs
        // without the console; reading the stored transcript catches both.
        const moved = !prev || prev.status !== task.status || prev.run_count !== task.run_count
            || prev.wait_type !== task.wait_type || (prev.pending_display || '') !== (task.pending_display || '')
            || task.status === 'running';
        if (moved) return loadBoardTranscript(task, data.approvals || [], load);
        scheduleBoardDetailPoll(task);
    }).catch(err => {
        if (load !== boardDetailLoad) return;
        boardDetailEl('chat').innerHTML = `<div class="px-6 py-4"><div class="bd-box is-error">${escapeHtml(err.message || t('board_load_failed'))}</div></div>`;
    });
}

function scheduleBoardDetailPoll(task) {
    if (boardDetailPollTimer) clearTimeout(boardDetailPollTimer);
    boardDetailPollTimer = null;
    if (!['queued', 'running', 'waiting'].includes(task.status)) return;
    boardDetailPollTimer = setTimeout(() => {
        boardDetailPollTimer = null;
        if (boardDetailShowing(task.id) && !boardDetailStream) refreshBoardDetail(task.id);
    }, BOARD_DETAIL_POLL_MS);
}

function loadBoardTranscript(task, approvals, load) {
    const params = new URLSearchParams({
        session_id: task.session_id, page: '1', page_size: String(BOARD_DETAIL_PAGE), agent_id: task.agent_id || '',
    });
    return fetch(`/api/history?${params}`).then(r => r.json()).then(data => {
        if (load !== boardDetailLoad) return;
        let messages = (data && data.status === 'success') ? (data.messages || []) : [];
        // A schedule keeps one session across its firings; show this one's.
        if (!/^task_\d+$/.test(task.session_id || '')) {
            const since = (task.created_at || 0) - 2;
            messages = messages.filter(m => (m.created_at || 0) >= since);
        }
        const active = data && data.active_request;
        const chat = boardDetailEl('chat');
        const keepScroll = chat.dataset.taskId === String(task.id) && !boardDetailNearBottom();
        const scrollTop = chat.scrollTop;
        chat.dataset.taskId = String(task.id);
        chat.innerHTML = '';
        let resumeEl = null;
        messages.forEach(msg => {
            const ts = new Date((msg.created_at || 0) * 1000);
            if (msg.role === 'user') {
                const text = msg.display || msg.content;
                if (text) chat.appendChild(boardUserBubble(text, ts));
                return;
            }
            const hasSteps = msg.steps && msg.steps.length > 0;
            if (!(msg.content && msg.content.trim()) && !hasSteps && !msg.run_state) return;
            const parts = splitAssistantTurn(msg);
            parts.forEach((part, i) => {
                const isLast = i === parts.length - 1;
                const partMsg = msg.run_state && !isLast ? Object.assign({}, part.msg, { run_state: null }) : part.msg;
                const el = boardBotBubble(partMsg, ts, part.peer, task);
                if (active && msg.run_state === 'running' && isLast && !part.peer) resumeEl = el;
                chat.appendChild(el);
            });
        });
        if (task.pending_display) chat.appendChild(boardUserBubble(task.pending_display, new Date(), true));
        renderBoardTranscriptTail(task, approvals, !!active);
        if (keepScroll) chat.scrollTop = scrollTop;
        else scrollBoardDetailToEnd(true);
        if (active && active.request_id) {
            boardDetailStream = followBoardStream(task, active.request_id, active.after_seq || 0, resumeEl);
        } else {
            scheduleBoardDetailPoll(task);
        }
    }).catch(() => {
        if (load !== boardDetailLoad) return;
        boardDetailEl('chat').innerHTML = boardDetailNotice(escapeHtml(t('board_load_failed')));
    });
}

// What the run is doing now, after the last stored message.
function renderBoardTranscriptTail(task, approvals, streaming) {
    const chat = boardDetailEl('chat');
    if (task.status === 'queued' && !streaming) {
        chat.insertAdjacentHTML('beforeend', boardDetailNotice(`<i class="fas fa-hourglass-half mr-1.5"></i>${escapeHtml(t('board_detail_queued'))}`));
    } else if (task.status === 'running' && !streaming) {
        chat.insertAdjacentHTML('beforeend', boardDetailNotice(`<i class="fas fa-spinner fa-spin mr-1.5"></i>${escapeHtml(t('board_detail_running'))}`));
    } else if (task.status === 'failed' && task.error) {
        chat.insertAdjacentHTML('beforeend', `<div class="px-4 sm:px-6 py-2"><div class="bd-box is-error">${escapeHtml(task.error)}</div></div>`);
    } else if (task.status === 'cancelled') {
        chat.insertAdjacentHTML('beforeend', boardDetailNotice(`<i class="fas fa-ban mr-1.5"></i>${escapeHtml(t('board_status_cancelled'))}`));
    }
    const pending = approvals.filter(a => a.status === 'pending');
    if (pending.length && !streaming) {
        const wrap = document.createElement('div');
        wrap.className = 'px-4 sm:px-6 py-2 space-y-2 bd-chat-pending';
        pending.forEach(appr => wrap.appendChild(renderApprovalBlock(appr, { withEdit: true })));
        chat.appendChild(wrap);
    }
    if (!chat.children.length) chat.innerHTML = boardDetailNotice(escapeHtml(t('board_no_transcript')));
}

function boardDetailNotice(html) {
    return `<div class="bd-chat-notice">${html}</div>`;
}

// ---- Bubbles: the chat's own, without the actions that edit a conversation ---

function boardUserBubble(text, ts, queued) {
    const el = createUserMessageEl(text, ts);
    el.querySelectorAll('.edit-msg-btn, .delete-msg-btn').forEach(btn => btn.remove());
    if (queued) {
        el.classList.add('is-queued');
        const meta = el.querySelector('.justify-end.gap-2');
        if (meta) meta.insertAdjacentHTML('afterbegin', `<span class="bd-queued-tag"><i class="far fa-clock"></i>${escapeHtml(t('board_reply_waiting'))}</span>`);
    }
    return el;
}

function boardBotBubble(msg, ts, peer, task) {
    const el = createBotMessageEl((msg && msg.content) || '', ts, null, msg, peer);
    el.querySelectorAll('.regenerate-msg-btn').forEach(btn => btn.remove());
    if (!peer) boardBubbleFace(el, task.agent_id);
    return el;
}

function boardBubbleFace(el, agentId) {
    const agent = findAgent(agentId) || findAgent(defaultAgentId);
    const face = el.querySelector('.bot-face');
    if (face && agent) {
        face.innerHTML = agentAvatarHTML(agent, 32);
        el.dataset.speakerAgent = agent.id;
    }
}

function boardDetailNearBottom() {
    const chat = boardDetailEl('chat');
    return chat.scrollHeight - chat.scrollTop - chat.clientHeight < 80;
}

function scrollBoardDetailToEnd(force) {
    const chat = boardDetailEl('chat');
    if (force || boardDetailNearBottom()) chat.scrollTop = chat.scrollHeight;
}

// ---- Live run: the chat's stream protocol, rendered into a bubble here ---------

function followBoardStream(task, requestId, afterSeq, resumeEl) {
    const view = boardStreamView(task, resumeEl);
    let lastSeq = afterSeq;
    let retries = 0;
    let es = null;
    let stopped = false;
    const live = {
        stop() {
            stopped = true;
            if (es) es.close();
        },
    };
    const finish = () => {
        if (stopped) return;
        live.stop();
        view.settle();
        if (boardDetailStream === live) boardDetailStream = null;
        // The stored copy replaces the streamed one, and picks up the next
        // round when a reply queued another.
        setTimeout(() => { if (boardDetailShowing(task.id)) { boardDetailTask = null; refreshBoardDetail(task.id); } }, 400);
    };
    const connect = () => {
        es = new EventSource(`/stream?request_id=${encodeURIComponent(requestId)}&after_seq=${lastSeq}`);
        es.onmessage = (e) => {
            let item;
            try { item = JSON.parse(e.data); } catch (_) { return; }
            const seq = Number(item.seq || 0);
            if (seq && seq <= lastSeq) return;
            if (seq) lastSeq = seq;
            retries = 0;
            view.handle(item);
            if (item.type === 'stream_end' || item.type === 'resync_required' || item.type === 'error') finish();
        };
        es.onerror = () => {
            es.close();
            if (stopped) return;
            retries += 1;
            if (retries > 5) { finish(); return; }
            setTimeout(() => { if (!stopped) connect(); }, 1000 * retries);
        };
    };
    connect();
    return live;
}

function boardStreamView(task, resumeEl) {
    const chat = boardDetailEl('chat');
    let botEl = null;
    let stepsEl = null;
    let contentEl = null;
    let mediaEl = null;
    let text = '';
    let thinkEl = null;
    let thinkText = '';
    let thinkStart = 0;
    let renderRaf = null;
    const tools = new Map();
    let started = false;

    const ensure = () => {
        if (botEl) return;
        chat.querySelectorAll('.bd-chat-notice').forEach(el => el.remove());
        adopt(boardBotBubble({ content: '' }, new Date(), null, task));
        chat.appendChild(botEl);
    };
    const adopt = (el) => {
        botEl = el;
        const box = el.querySelector('.msg-content');
        contentEl = box.querySelector('.answer-content');
        mediaEl = box.querySelector('.media-content');
        stepsEl = box.querySelector('.agent-steps');
        if (!stepsEl) {
            stepsEl = document.createElement('div');
            stepsEl.className = 'agent-steps';
            box.insertBefore(stepsEl, contentEl);
        }
        box.querySelectorAll('.agent-status-step').forEach(s => s.remove());
        contentEl.classList.add('sse-streaming');
        el.querySelectorAll('.copy-msg-btn').forEach(btn => { btn.style.display = 'none'; });
    };
    if (resumeEl) adopt(resumeEl);

    const flush = () => {
        if (renderRaf === null) return;
        cancelAnimationFrame(renderRaf);
        renderRaf = null;
        contentEl.innerHTML = renderMarkdown(text);
    };
    const closeThinking = () => {
        if (!thinkEl) return;
        finalizeThinking(thinkEl, thinkStart, thinkText);
        thinkEl = null;
        thinkText = '';
    };
    const settleTools = () => {
        tools.forEach(el => {
            el.classList.remove('tool-streaming');
            const icon = el.querySelector('.tool-icon');
            if (icon && icon.classList.contains('fa-spin')) icon.className = 'fas fa-minus text-slate-400 flex-shrink-0 tool-icon';
        });
        tools.clear();
    };

    const handlers = {
        reasoning(item) {
            ensure();
            thinkText += item.content || '';
            if (!thinkEl) {
                thinkStart = Date.now();
                thinkEl = document.createElement('div');
                thinkEl.className = 'agent-step agent-thinking-step';
                thinkEl.innerHTML = `
                    <div class="thinking-header" onclick="this.parentElement.classList.toggle('expanded')">
                        <i class="fas fa-lightbulb text-amber-400 flex-shrink-0"></i>
                        <span class="thinking-summary">${t('thinking_in_progress')}</span>
                        <i class="fas fa-chevron-right thinking-chevron"></i>
                    </div>
                    <div class="thinking-full"><pre class="thinking-stream-pre"></pre></div>`;
                stepsEl.appendChild(thinkEl);
            }
            const pre = thinkEl.querySelector('.thinking-stream-pre');
            if (pre.textContent.length < REASONING_RENDER_CAP) pre.textContent = thinkText.slice(0, REASONING_RENDER_CAP);
        },
        delta(item) {
            ensure();
            closeThinking();
            text += item.content || '';
            if (renderRaf !== null) return;
            renderRaf = requestAnimationFrame(() => {
                renderRaf = null;
                const stick = boardDetailNearBottom();
                contentEl.innerHTML = renderMarkdown(text);
                if (stick) scrollBoardDetailToEnd(true);
            });
        },
        message_end(item) {
            if (!item.has_tool_calls || !text.trim()) return;
            ensure();
            const frozen = document.createElement('div');
            frozen.className = 'agent-step agent-content-step';
            frozen.innerHTML = `<div class="agent-content-body">${renderMarkdown(text.trim())}</div>`;
            stepsEl.appendChild(frozen);
            text = '';
            contentEl.innerHTML = '';
        },
        tool_start(item) {
            ensure();
            closeThinking();
            text = '';
            contentEl.innerHTML = '';
            const el = document.createElement('div');
            el.className = 'agent-step agent-tool-step tool-streaming';
            el.innerHTML = `
                <div class="tool-header" onclick="this.parentElement.classList.toggle('expanded')">
                    <i class="fas fa-cog fa-spin text-primary-400 flex-shrink-0 tool-icon"></i>
                    <span class="tool-name">${escapeHtml(item.tool || '')}</span>
                    <span class="tool-substep-count"></span>
                    <i class="fas fa-chevron-right tool-chevron"></i>
                </div>
                <div class="tool-detail">
                    <div class="tool-detail-section">
                        <div class="tool-detail-label">Input</div>
                        <pre class="tool-detail-content">${formatToolArgs(item.arguments || {})}</pre>
                    </div>
                    <div class="tool-detail-section tool-substeps-section hidden">
                        <div class="tool-detail-label">Steps</div>
                        <div class="tool-substeps"></div>
                    </div>
                    <div class="tool-detail-section tool-output-section">
                        <div class="tool-detail-label tool-output-label">Output</div>
                        <pre class="tool-detail-content tool-live-output"></pre>
                        <div class="tool-display-output"></div>
                    </div>
                </div>`;
            stepsEl.appendChild(el);
            tools.set(item.tool_call_id, el);
        },
        tool_progress(item) {
            const el = tools.get(item.tool_call_id);
            if (!el) return;
            el.classList.add('expanded');
            el.querySelector('.tool-live-output').textContent = String(item.content || '');
        },
        tool_end(item) {
            const el = tools.get(item.tool_call_id);
            if (!el) return;
            const isError = item.status !== 'success';
            el.querySelector('.tool-icon').className = isError
                ? 'fas fa-times text-red-400 flex-shrink-0 tool-icon'
                : 'fas fa-check text-primary-400 flex-shrink-0 tool-icon';
            if (item.execution_time !== undefined) {
                el.querySelector('.tool-name').insertAdjacentHTML('beforeend', ` <span class="tool-time">${item.execution_time}s</span>`);
            }
            const label = el.querySelector('.tool-output-label');
            const out = el.querySelector('.tool-live-output');
            const display = el.querySelector('.tool-display-output');
            label.textContent = isError ? 'Error' : 'Output';
            if (item.display) {
                display.innerHTML = renderMarkdown(String(item.display));
                display.classList.add('has-content');
                out.textContent = '';
            } else {
                out.textContent = item.result ? String(item.result) : '';
                out.classList.toggle('tool-error-text', isError);
            }
            el.classList.remove('tool-streaming');
            el.classList.toggle('expanded', !!item.display);
            if (!item.result && !item.display) {
                const section = el.querySelector('.tool-output-section');
                if (section) section.remove();
            }
            if (isError) el.classList.add('tool-failed');
            if (item.approval_pending) {
                appendInlineApproval(el, item);
                setTimeout(() => { if (boardDetailShowing(task.id)) refreshBoardDetail(task.id); }, 300);
            }
            tools.delete(item.tool_call_id);
        },
        subagent_step(item) {
            renderSubagentStep(tools.get(item.card_id), item);
        },
        image(item) {
            ensure();
            const img = document.createElement('img');
            img.onerror = () => _onImageLoadError(img);
            img.src = item.content;
            img.alt = item.file_name || 'image';
            img.className = 'bd-stream-image';
            img.onclick = () => _openImageLightbox(img.src);
            mediaEl.appendChild(img);
        },
        file(item) {
            ensure();
            if (item.abs_path && typeof appendArtifactCard === 'function') {
                const name = item.file_name || item.abs_path.split(/[\\/]/).pop();
                const kind = item.kind || wsKindOf(name);
                appendArtifactCard(mediaEl, Object.assign({}, item, {
                    file_name: name, kind: kind, rel_path: item.rel_path || name, raw_url: item.content,
                    previewable: item.previewable != null ? item.previewable : WS_PREVIEWABLE.has(kind),
                }));
                return;
            }
            const link = document.createElement('a');
            link.href = item.content;
            link.target = '_blank';
            link.className = 'file-attachment';
            link.innerHTML = `<i class="fas fa-file-download"></i> ${escapeHtml(item.file_name || item.content.split('/').pop())}`;
            mediaEl.appendChild(link);
        },
        artifact(item) {
            ensure();
            if (typeof appendArtifactCard === 'function') appendArtifactCard(mediaEl, item);
        },
        cancelled() {
            ensure();
            closeThinking();
            if (!stepsEl.querySelector('.agent-status-step')) stepsEl.insertAdjacentHTML('beforeend', replyStatusHtml('cancelled'));
        },
        done(item) {
            settleTools();
            closeThinking();
            const finalText = item.content || text;
            if (!botEl && !finalText) return;
            ensure();
            contentEl.classList.remove('sse-streaming');
            if (finalText) contentEl.innerHTML = renderMarkdown(finalText);
            contentEl.dataset.rawMd = finalText || '';
            const copy = botEl.querySelector('.copy-msg-btn');
            if (copy && finalText) copy.style.display = '';
            applyHighlighting(botEl);
        },
    };

    return {
        handle(item) {
            const stick = boardDetailNearBottom();
            if (!started) {
                // A reply queued just before the run took it is now this round's prompt.
                started = true;
                chat.querySelectorAll('.bd-queued-tag').forEach(el => el.remove());
                chat.querySelectorAll('.user-message-group.is-queued').forEach(el => el.classList.remove('is-queued'));
            }
            if (item.type !== 'delta') flush();
            const handler = handlers[item.type];
            if (handler) handler(item);
            if (stick) scrollBoardDetailToEnd(true);
        },
        settle() {
            flush();
            settleTools();
            closeThinking();
            if (contentEl) contentEl.classList.remove('sse-streaming');
        },
    };
}

// ---- Facts and decisions --------------------------------------------------------------

function renderBoardDetailHead(task) {
    const meta = BOARD_STATUS_META[task.status] || BOARD_STATUS_META.queued;
    setBoardDetailIcon(meta);
    boardDetailEl('title').textContent = `#${task.id} ${task.title || ''}`;
    boardDetailEl('sub').textContent = [boardStatusText(task), boardRelTime(task.updated_at)].filter(Boolean).join(' · ');
    const active = ['queued', 'running', 'waiting'].includes(task.status);
    boardDetailEl('actions').classList.remove('hidden');
    boardDetailEl('cancel').classList.toggle('hidden', !active);
    boardDetailEl('retry').classList.toggle('hidden', active);
}

function boardSideFacts(rows) {
    return `<div class="bd-facts">${rows.map(([label, value]) =>
        `<div class="bd-fact"><div class="bd-meta-label">${escapeHtml(label)}</div><div class="bd-meta-value">${value}</div></div>`).join('')}</div>`;
}

function renderBoardDetailSide(task, approvals) {
    const rows = [
        [t('board_meta_status'), `<span class="bd-status is-${task.status}">${escapeHtml(boardStatusText(task))}</span>`],
        [t('record_detail_agent'), boardOwner(task.agent_id)],
        [t('board_meta_source'), boardSourceChip(task)],
        [t('board_meta_created'), escapeHtml(new Date(task.created_at * 1000).toLocaleString())],
    ];
    if (task.started_at) {
        rows.push([t('board_meta_duration'), escapeHtml(boardDuration(task.started_at, task.status === 'running' ? 0 : (task.finished_at || task.updated_at)))]);
    }
    if (task.run_count > 1) rows.push([t('board_meta_rounds'), String(task.run_count)]);
    if (task.require_accept) rows.push([t('board_meta_accept'), `<i class="fas fa-check text-primary-500"></i>`]);
    const parts = [boardSideFacts(rows)];

    const pending = approvals.filter(a => a.status === 'pending');
    if (pending.length) {
        parts.push(`<div class="bd-section"><div class="bd-section-head">${escapeHtml(t('board_section_pending'))}</div><div id="bd-side-pending" class="space-y-2"></div></div>`);
    }
    if (task.result) {
        parts.push(`
            <div class="bd-section">
                <div class="bd-section-head">${escapeHtml(t('board_section_result'))}<span class="grow"></span>
                    <button class="board-btn board-btn-link" id="bd-copy-result"><i class="fas fa-copy"></i>${escapeHtml(t('board_copy'))}</button>
                </div>
                <div class="bd-side-result">${escapeHtml(boardPlainText(task.result))}</div>
            </div>`);
    }
    const history = approvals.filter(a => a.status !== 'pending');
    if (history.length) {
        parts.push(`<div class="bd-section"><div class="bd-section-head">${escapeHtml(t('board_section_approvals'))}</div><div class="bd-timeline">${history.map(renderApprovalTimelineItem).join('')}</div></div>`);
    }
    const side = boardDetailEl('side');
    side.innerHTML = parts.join('');
    const pendingEl = document.getElementById('bd-side-pending');
    if (pendingEl) pending.forEach(appr => pendingEl.appendChild(renderApprovalBlock(appr, { withEdit: true, compact: true })));
    const copyBtn = document.getElementById('bd-copy-result');
    if (copyBtn) copyBtn.addEventListener('click', () => {
        copyToClipboard(task.result);
        copyBtn.innerHTML = `<i class="fas fa-check"></i>${escapeHtml(t('board_copied'))}`;
        setTimeout(() => { copyBtn.innerHTML = `<i class="fas fa-copy"></i>${escapeHtml(t('board_copy'))}`; }, 1500);
    });
}

function renderApprovalTimelineItem(appr) {
    const colors = { approved: 'dot-done', rejected: 'dot-failed', expired: 'dot-cancelled' };
    const stateKey = { approved: 'approval_state_approved', rejected: 'approval_state_rejected', expired: 'approval_state_expired' }[appr.status] || 'approval_state_expired';
    const kind = appr.kind === 'accept' ? t('approval_kind_accept') : (appr.label || appr.tool_name || '');
    const via = appr.decided_via ? ` · ${escapeHtml(appr.decided_via)}` : '';
    const when = appr.decided_at ? ` · ${escapeHtml(boardRelTime(appr.decided_at))}` : '';
    const note = appr.decision_note ? `<div class="bd-tl-sub">${escapeHtml(t('approval_note'))}: ${escapeHtml(appr.decision_note)}</div>` : '';
    return `
        <div class="bd-tl-item">
            <span class="bd-tl-dot ${colors[appr.status] || 'dot-cancelled'}"></span>
            <div class="bd-tl-title">#${appr.id} ${escapeHtml(kind)} · ${escapeHtml(t(stateKey))}</div>
            <div class="bd-tl-sub">${via.replace(/^ · /, '')}${when}</div>
            ${note}
        </div>`;
}

// ---- Composer: what a message does depends on where the run is -------------------

function boardComposerMode(task) {
    if (task.status === 'running') return { hint: 'board_reply_hint_running', placeholder: 'board_reply_ph_running' };
    if (task.status === 'queued') return { hint: 'board_reply_hint_queued', placeholder: 'board_reply_ph_more' };
    if (task.status === 'waiting' && task.wait_type === 'accept') return { hint: 'board_reply_hint_accept', placeholder: 'board_reply_ph_accept' };
    if (task.status === 'waiting') return { hint: 'board_reply_hint_waiting', placeholder: 'board_reply_ph_more' };
    return { hint: 'board_reply_hint_finished', placeholder: 'board_reply_ph_finished' };
}

function renderBoardDetailComposer(task) {
    const mode = boardComposerMode(task);
    boardDetailEl('composer').classList.remove('hidden');
    boardDetailEl('hint').textContent = t(mode.hint);
    boardDetailEl('input').placeholder = t(mode.placeholder);
    updateBoardDetailSend();
}

function updateBoardDetailSend() {
    const input = boardDetailEl('input');
    boardDetailEl('send').disabled = boardDetailSending || !input.value.trim() || !boardDetailTask;
}

function sendBoardDetailReply() {
    const task = boardDetailTask;
    const input = boardDetailEl('input');
    const message = input.value.trim();
    if (!task || !message || boardDetailSending) return;
    boardDetailSending = true;
    updateBoardDetailSend();
    boardFetchJSON(`/api/tasks/${task.id}/reply`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message }),
    }).then(data => {
        input.value = '';
        input.style.height = '';
        if (data.mode === 'steer') {
            boardDetailEl('chat').appendChild(boardUserBubble(`↪ ${message}`, new Date()));
            scrollBoardDetailToEnd(true);
            return;
        }
        scrollBoardDetailToEnd(true);
        boardDetailTask = null;
        refreshBoardDetail(task.id);
        loadTaskBoard();
    }).catch(err => {
        boardDetailEl('hint').textContent = err.message || t('board_action_failed');
    }).finally(() => {
        boardDetailSending = false;
        updateBoardDetailSend();
    });
}

function autoGrowBoardDetailInput() {
    const input = boardDetailEl('input');
    input.style.height = 'auto';
    input.style.height = `${Math.min(input.scrollHeight, 200)}px`;
}

// ---- Wiring ------------------------------------------------------------------------

(function wireTaskDetail() {
    const cancel = boardDetailEl('cancel');
    if (!cancel) return;
    cancel.addEventListener('click', () => boardTaskAction('cancel'));
    boardDetailEl('retry').addEventListener('click', () => boardTaskAction('retry'));
    boardDetailEl('delete').addEventListener('click', () => boardTaskAction('delete'));

    const input = boardDetailEl('input');
    let composing = false;
    input.addEventListener('compositionstart', () => { composing = true; });
    input.addEventListener('compositionend', () => { composing = false; });
    input.addEventListener('input', () => { autoGrowBoardDetailInput(); updateBoardDetailSend(); });
    input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey && !composing && !e.isComposing) {
            e.preventDefault();
            sendBoardDetailReply();
        }
    });
    boardDetailEl('send').addEventListener('click', sendBoardDetailReply);

    // The chat's bubble actions are bound to its own message list.
    boardDetailEl('chat').addEventListener('click', (e) => {
        const codeBtn = e.target.closest('.code-copy-btn');
        const msgBtn = e.target.closest('.copy-msg-btn');
        let text = '';
        let btn = null;
        if (codeBtn) {
            const code = codeBtn.closest('.code-block-wrapper');
            text = code && code.querySelector('pre code') ? code.querySelector('pre code').textContent : '';
            btn = codeBtn;
        } else if (msgBtn) {
            const answer = msgBtn.closest('.bot-message-group');
            text = answer && answer.querySelector('.answer-content') ? answer.querySelector('.answer-content').dataset.rawMd : '';
            btn = msgBtn;
        }
        if (!btn || !text) return;
        e.preventDefault();
        copyToClipboard(text).then(() => {
            const icon = btn.querySelector('i');
            if (icon) { icon.className = 'fas fa-check'; setTimeout(() => { icon.className = 'fas fa-copy'; }, 1500); }
        });
    });
})();
