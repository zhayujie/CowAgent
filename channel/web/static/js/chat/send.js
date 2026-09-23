/* Sending, regenerating, SSE streaming and the polling fallback.
   Split out of console.js. These are classic scripts sharing one global
   scope; see channel/web/README.md before changing the load order. */

// Regenerate bot response: find the preceding user message and resend it
async function regenerateResponse(botMsgEl) {
    let prevEl = botMsgEl.previousElementSibling;
    while (prevEl && !prevEl.classList.contains('user-message-group')) {
        prevEl = prevEl.previousElementSibling;
    }

    if (!prevEl) {
        console.warn('No preceding user message found');
        return;
    }

    const userContent = prevEl.dataset.rawContent;
    if (!userContent) {
        console.warn('No content in preceding user message');
        return;
    }

    // Delete both the old user message AND bot reply from database
    // (because /message will create a fresh user message + new bot reply)
    // Must await to ensure delete completes before /message is sent
    const userSeq = prevEl.dataset.seq;
    if (userSeq) {
        try {
            const resp = await fetch('/api/messages/delete', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ 
                    session_id: sessionId, 
                    user_seq: parseInt(userSeq),
                    delete_user: true
                })
            });
            const data = await resp.json();
            if (data.status === 'success') console.log(`Deleted ${data.deleted} old messages`);
        } catch (err) {
            console.error('Failed to delete old messages:', err);
        }
    }

    // Remove both the old user message and bot message from DOM
    if (prevEl.parentNode) prevEl.parentNode.removeChild(prevEl);
    if (botMsgEl.parentNode) botMsgEl.parentNode.removeChild(botMsgEl);

    // Re-add the user message to DOM (so it appears before the loading indicator)
    addUserMessage(userContent, new Date());

    // Show loading indicator
    const loadingEl = addLoadingIndicator();

    // Resend the message
    const timestamp = new Date();
    const body = { session_id: sessionId, message: userContent, stream: true, timestamp: timestamp.toISOString(), lang: currentLang };
    const regenAddressed = addressedAgentId(userContent);
    if (regenAddressed) body.speaker_agent_id = regenAddressed;

    const MAX_RETRIES = 2;
    const RETRY_DELAY_MS = 1000;

    function postWithRetry(attempt) {
        fetch('/message', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body)
        })
        .then(r => r.json())
        .then(data => {
            if (data.status === 'success') {
                rememberLiveSpeaker(data);
                setLoadingSpeaker(loadingEl, data.request_id);
                if (data.inline_reply) {
                    loadingEl.remove();
                    addBotMessage(data.inline_reply, new Date());
                } else if (data.stream) {
                    setSendBtnCancelMode(data.request_id);
                    startSSE(data.request_id, loadingEl, timestamp, null);
                } else {
                    loadingContainers[data.request_id] = loadingEl;
                }
            } else {
                loadingEl.remove();
                addBotMessage(t('error_send'), new Date());
                resetSendBtnSendMode();
            }
        })
        .catch(err => {
            if (err.name === 'AbortError') {
                loadingEl.remove();
                addBotMessage(t('error_timeout'), new Date());
                resetSendBtnSendMode();
                return;
            }
            if (attempt < MAX_RETRIES) {
                console.warn(`[regenerateResponse] attempt ${attempt + 1} failed, retrying...`, err);
                setTimeout(() => postWithRetry(attempt + 1), RETRY_DELAY_MS * (attempt + 1));
                return;
            }
            loadingEl.remove();
            addBotMessage(t('error_send'), new Date());
            resetSendBtnSendMode();
        });
    }

    postWithRetry(0);
}

function sendMessage() {
    // Do NOT branch on sendBtnMode here: Enter should always send (so
    // typing "/cancel" submits normally). Cancel is wired only to the
    // send button's pointer click — see send-btn listener above.

    const text = chatInput.value.trim();
    if (!text && pendingAttachments.length === 0) return;

    if (text) {
        inputHistory.push(text);
        historyIdx = -1;
        historySavedDraft = '';
    }

    const ws = document.getElementById('welcome-screen');
    const isFirstMessage = !!ws;
    if (ws) ws.remove();

    const titleInfo = (isFirstMessage && text) ? { sid: sessionId, userMsg: text } : null;
    syncTeamFromText(text);
    renderComposerIdentity();

    const timestamp = new Date();
    const attachments = [...pendingAttachments];
    addUserMessage(text, timestamp, attachments);

    const loadingEl = addLoadingIndicator();

    chatInput.value = '';
    resetComposerHeight();
    pendingAttachments = [];
    renderAttachmentPreview();
    sendBtn.disabled = true;
    if (typeof resetTurnArtifacts === 'function') resetTurnArtifacts();

    const body = { session_id: sessionId, message: text, stream: true, timestamp: timestamp.toISOString(), lang: currentLang };
    // Naming somebody hands them the turn. Sent explicitly because the composer
    // already knows who it wrote, and the server re-checks it either way.
    const addressed = addressedAgentId(text);
    if (addressed) body.speaker_agent_id = addressed;
    if (attachments.length > 0) {
        body.attachments = attachments.map(a => ({
            file_path: a.file_path,
            file_name: a.file_name,
            file_type: a.file_type,
            file_count: a.file_count,
        }));
    }

    const MAX_RETRIES = 2;
    const RETRY_DELAY_MS = 1000;

    function postWithRetry(attempt) {
        fetch('/message', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body)
        })
        .then(r => r.json())
        .then(data => {
            if (data.status === 'success') {
                rememberLiveSpeaker(data);
                setLoadingSpeaker(loadingEl, data.request_id);
                if (data.inline_reply) {
                    // Channel handled synchronously (e.g. /cancel fast-path);
                    // render as a bot bubble and skip SSE entirely.
                    loadingEl.remove();
                    addBotMessage(data.inline_reply, new Date());
                } else if (data.stream) {
                    setSendBtnCancelMode(data.request_id);
                    startSSE(data.request_id, loadingEl, timestamp, titleInfo);
                } else {
                    loadingContainers[data.request_id] = loadingEl;
                }
            } else {
                loadingEl.remove();
                addBotMessage(t('error_send'), new Date());
                resetSendBtnSendMode();
            }
        })
        .catch(err => {
            if (err.name === 'AbortError') {
                loadingEl.remove();
                addBotMessage(t('error_timeout'), new Date());
                resetSendBtnSendMode();
                return;
            }
            if (attempt < MAX_RETRIES) {
                console.warn(`[sendMessage] attempt ${attempt + 1} failed, retrying...`, err);
                setTimeout(() => postWithRetry(attempt + 1), RETRY_DELAY_MS * (attempt + 1));
                return;
            }
            loadingEl.remove();
            addBotMessage(t('error_send'), new Date());
            resetSendBtnSendMode();
        });
    }

    postWithRetry(0);
}

function startSSE(requestId, loadingEl, timestamp, titleInfo, replayItems) {
    let botEl = null;
    let stepsEl = null;    // .agent-steps  (thinking summaries + tool indicators)
    let contentEl = null;  // .answer-content (final streaming answer)
    let mediaEl = null;    // .media-content (images & file attachments)
    let accumulatedText = '';
    const toolElements = new Map();
    let currentReasoningEl = null;  // live reasoning bubble
    let reasoningText = '';
    let reasoningStartTime = 0;
    let done = false;
    let mainDone = false;
    let completedBotSeq = null;
    let cancelled = false;
    let lastSeq = 0;

    // Who the bubble currently being written belongs to. A delegation hands the
    // floor to a teammate partway through the turn: the teammate's reply gets
    // its own bubble, and when it ends the floor returns to whoever held it
    // before. Nesting therefore reads as a flat run of turns, in the order they
    // happened, rather than turns buried inside each other.
    const speakerStack = [];
    const peerSpeaker = () => (speakerStack.length ? speakerStack[speakerStack.length - 1] : null);

    // Seal the current bubble so whatever comes next starts a new one. In-flight
    // tools are deliberately left alone: the delegating call is still running
    // while its teammate speaks, and its card should keep spinning.
    function closeBubble() {
        if (currentReasoningEl) {
            finalizeThinking(currentReasoningEl, reasoningStartTime, reasoningText);
            currentReasoningEl = null;
            reasoningText = '';
        }
        if (botEl && contentEl) {
            if (accumulatedText.trim()) contentEl.innerHTML = renderMarkdown(accumulatedText);
            contentEl.classList.remove('sse-streaming');
            applyHighlighting(botEl);
        }
        accumulatedText = '';
        botEl = null;
        stepsEl = null;
        contentEl = null;
        mediaEl = null;
    }

    // A stream can end while tools are still marked in-flight (cancel, dropped
    // connection). Settle them so nothing spins forever.
    function settlePendingTools() {
        toolElements.forEach(el => {
            el.classList.remove('tool-streaming');
            const icon = el.querySelector('.tool-icon');
            if (icon) icon.className = 'fas fa-minus text-slate-400 flex-shrink-0 tool-icon';
        });
        toolElements.clear();
    }

    // The session this stream belongs to. Sessions run in parallel: the user
    // may switch to another session while this one is still streaming. The
    // stream keeps running in the background (so the reply still completes and
    // persists); when foreign it does not touch the view but still records
    // every event into a buffer, so returning to the session can rebuild the
    // bubble by replaying the buffer and then resume live rendering.
    const ownerSession = sessionId;
    const ownerAgent = activeAgentId;
    const ownerKey = runtimeSessionKey(ownerSession, ownerAgent);
    const isActive = () => ownerSession === sessionId && ownerAgent === activeAgentId;
    sessionActiveRequest[ownerKey] = requestId;
    updateEditButtonsState();
    // Per-request event buffer used to rebuild the bubble on re-attach.
    const buffer = streamBuffers[requestId] || { items: [], timestamp };
    streamBuffers[requestId] = buffer;
    const clearOwnerRequest = () => {
        if (sessionActiveRequest[ownerKey] === requestId) {
            delete sessionActiveRequest[ownerKey];
            updateEditButtonsState();
        }
        delete streamBuffers[requestId];
    };

    const MAX_RECONNECTS = 10;
    const RECONNECT_BASE_MS = 1000;
    let reconnectCount = 0;

    function ensureBotEl() {
        if (botEl) return;
        if (loadingEl) { loadingEl.remove(); loadingEl = null; }
        botEl = document.createElement('div');
        botEl.className = 'flex gap-3 px-4 sm:px-6 py-3 bot-message-group';
        botEl.dataset.requestId = requestId;
        // Regenerate button starts hidden; it's revealed in the "done"
        // event handler once seq metadata arrives from the backend.
        // The streaming face is whoever is answering this request: the addressed
        // teammate if one was named, else the conversation's own Agent. Wrapped
        // in .bot-face so a later avatar change repaints it like any bubble.
        const peer = peerSpeaker();
        const speaker = peer || liveSpeakerAgent(requestId);
        if (speaker && speaker.id) botEl.dataset.speakerAgent = speaker.id;
        // Marks the bubble as belonging to a teammate rather than to the Agent
        // this request was addressed to, so lookups for "the reply" skip it.
        if (peer) botEl.dataset.peerBubble = '1';
        // In a group the bubble is labelled with its author while it streams,
        // exactly as the replayed history shows it — a solo chat stays unlabelled.
        // A teammate's bubble is always labelled: the label is what makes it read
        // as someone else answering instead of the Agent changing voice mid-reply.
        const speakerName = ((peer || sharedConversation()) && speaker)
            ? `<div class="bot-speaker">${escapeHtml(speaker.name || speaker.id)}</div>`
            : '';
        botEl.innerHTML = `
            <span class="bot-face">${agentAvatarHTML(speaker, 32)}</span>
            <div class="min-w-0 flex-1 max-w-[85%]">
                ${speakerName}
                <div class="bg-white dark:bg-[#1A1A1A] border border-slate-200 dark:border-white/10 rounded-2xl px-4 py-3 text-sm leading-relaxed msg-content text-slate-700 dark:text-slate-200">
                    <div class="agent-steps"></div>
                    <div class="answer-content sse-streaming"></div>
                    <div class="media-content"></div>
                    <div class="bot-audio-slot"></div>
                </div>
                <div class="flex items-center gap-2 mt-1.5">
                    <span class="text-xs text-slate-400 dark:text-slate-500">${formatTime(timestamp)}</span>
                    <button class="copy-msg-btn text-xs text-slate-300 dark:text-slate-600 hover:text-slate-500 dark:hover:text-slate-400 transition-colors cursor-pointer" title="Copy" style="display:none">
                        <i class="fas fa-copy"></i>
                    </button>
                    <button class="speak-msg-btn text-xs text-slate-300 dark:text-slate-600 hover:text-slate-500 dark:hover:text-slate-400 transition-colors cursor-pointer" title="${t('speak_msg')}" style="display:none;">
                        <i class="fas fa-volume-up"></i>
                    </button>
                    <button class="regenerate-msg-btn text-xs text-slate-300 dark:text-slate-600 hover:text-primary-400 dark:hover:text-primary-400 transition-colors cursor-pointer" title="${t('regenerate_response')}" style="display:none;">
                        <i class="fas fa-rotate-right"></i>
                    </button>
                </div>
            </div>
        `;
        messagesDiv.appendChild(botEl);
        stepsEl = botEl.querySelector('.agent-steps');
        contentEl = botEl.querySelector('.answer-content');
        mediaEl = botEl.querySelector('.media-content');
    }

    // Holds the live EventSource so terminal events (done/voice_attach/error)
    // can close it. During replay there is no live connection (null).
    let currentEs = null;

    // Render one SSE event into the bubble. Used by the live handler and by
    // re-attach replay alike, so both paths produce identical UI.
    function processSSEItem(item) {
            if (item.type === 'reasoning') {
                ensureBotEl();
                reasoningText += item.content;
                if (!currentReasoningEl) {
                    reasoningStartTime = Date.now();
                    currentReasoningEl = document.createElement('div');
                    currentReasoningEl.className = 'agent-step agent-thinking-step';
                    // During streaming, use a <pre> with a single text node and
                    // append-only updates. This avoids re-parsing markdown and
                    // re-setting innerHTML on every chunk, which is what causes
                    // the page to crash on long chains-of-thought.
                    currentReasoningEl.innerHTML = `
                        <div class="thinking-header" onclick="this.parentElement.classList.toggle('expanded')">
                            <i class="fas fa-lightbulb text-amber-400 flex-shrink-0"></i>
                            <span class="thinking-summary">${t('thinking_in_progress')}</span>
                            <i class="fas fa-chevron-right thinking-chevron"></i>
                        </div>
                        <div class="thinking-full"><pre class="thinking-stream-pre"></pre></div>`;
                    stepsEl.appendChild(currentReasoningEl);
                    const preEl = currentReasoningEl.querySelector('.thinking-stream-pre');
                    preEl.appendChild(document.createTextNode(''));
                    currentReasoningEl._streamTextNode = preEl.firstChild;
                    currentReasoningEl._streamPendingText = '';
                    currentReasoningEl._streamRafScheduled = false;
                    currentReasoningEl._streamCharsRendered = 0;
                    currentReasoningEl._streamCapped = false;
                }
                // Hard cap: once REASONING_RENDER_CAP chars are in the DOM, stop
                // appending further deltas. The full text is still kept in
                // `reasoningText` for finalize-time head+tail rendering.
                if (!currentReasoningEl._streamCapped) {
                    currentReasoningEl._streamPendingText += item.content;
                    if (!currentReasoningEl._streamRafScheduled) {
                        currentReasoningEl._streamRafScheduled = true;
                        const elRef = currentReasoningEl;
                        requestAnimationFrame(() => {
                            elRef._streamRafScheduled = false;
                            if (!elRef.isConnected || !elRef._streamTextNode) return;
                            let pending = elRef._streamPendingText;
                            elRef._streamPendingText = '';
                            if (!pending) return;
                            const remaining = REASONING_RENDER_CAP - elRef._streamCharsRendered;
                            if (remaining <= 0) {
                                elRef._streamCapped = true;
                            } else {
                                if (pending.length > remaining) {
                                    pending = pending.slice(0, remaining);
                                    elRef._streamCapped = true;
                                }
                                elRef._streamTextNode.appendData(pending);
                                elRef._streamCharsRendered += pending.length;
                                if (elRef._streamCapped) {
                                    elRef._streamTextNode.appendData(
                                        '\n\n... [reasoning truncated for display] ...'
                                    );
                                }
                            }
                            scrollChatToBottom();
                        });
                    }
                }

            } else if (item.type === 'delta') {
                ensureBotEl();
                if (currentReasoningEl) {
                    finalizeThinking(currentReasoningEl, reasoningStartTime, reasoningText);
                    currentReasoningEl = null;
                    reasoningText = '';
                }
                accumulatedText += item.content;
                contentEl.innerHTML = renderMarkdown(accumulatedText);
                scrollChatToBottom();

            } else if (item.type === 'message_end') {
                if (item.has_tool_calls && accumulatedText.trim()) {
                    ensureBotEl();
                    const frozenEl = document.createElement('div');
                    frozenEl.className = 'agent-step agent-content-step';
                    frozenEl.innerHTML = `<div class="agent-content-body">${renderMarkdown(accumulatedText.trim())}</div>`;
                    stepsEl.appendChild(frozenEl);
                    accumulatedText = '';
                    contentEl.innerHTML = '';
                    scrollChatToBottom();
                }

            } else if (item.type === 'peer_start') {
                // A teammate takes the floor. Everything until the matching
                // peer_end is its reply, and it renders through the very same
                // branches below — it just lands in a bubble wearing its face.
                closeBubble();
                speakerStack.push(
                    findAgent(item.agent_id)
                    || { id: item.agent_id || '', name: item.agent_name || item.agent_id || '' }
                );
                // The card that spawned this turn now only needs to say who was
                // handed the work; the answer itself is the bubble.
                markHandoffCard(toolElements.get(item.card_id), item);

            } else if (item.type === 'peer_end') {
                closeBubble();
                speakerStack.pop();

            } else if (item.type === 'tool_retrieval') {
                ensureBotEl();
                const fallback = item.mode === 'fallback';
                const selected = Array.isArray(item.selected_tools) ? item.selected_tools : [];
                const ranked = Array.isArray(item.ranked_tools) ? item.ranked_tools : [];
                const summary = (fallback ? t('retrieval_fallback') : t('retrieval_selected'))
                    .replace('{selected}', String(item.selected_mcp_tools || 0))
                    .replace('{total}', String(item.total_mcp_tools || 0));
                const details = [];
                if (!fallback && selected.length) {
                    details.push(`
                        <div class="tool-detail-section">
                            <div class="tool-detail-label">${t('retrieval_selected_tools')}</div>
                            <pre class="tool-detail-content">${escapeHtml(selected.join(', '))}</pre>
                        </div>`);
                }
                if (!fallback && ranked.length) {
                    const ranking = ranked.map(tool => {
                        const score = Number(tool.score);
                        return `${tool.name} (${Number.isFinite(score) ? score.toFixed(3) : '0.000'})`;
                    }).join(', ');
                    details.push(`
                        <div class="tool-detail-section">
                            <div class="tool-detail-label">${t('retrieval_ranking')}</div>
                            <pre class="tool-detail-content">${escapeHtml(ranking)}</pre>
                        </div>`);
                }
                if (item.fallback_reason) {
                    details.push(`
                        <div class="tool-detail-section">
                            <div class="tool-detail-label">${t('retrieval_fallback_reason')}</div>
                            <pre class="tool-detail-content">${escapeHtml(String(item.fallback_reason))}</pre>
                        </div>`);
                }

                const retrievalEl = document.createElement('div');
                retrievalEl.className = 'agent-step agent-tool-step agent-retrieval-step';
                retrievalEl.innerHTML = `
                    <div class="tool-header" onclick="this.parentElement.classList.toggle('expanded')">
                        <i class="fas ${fallback ? 'fa-layer-group text-amber-400' : 'fa-filter text-primary-400'} flex-shrink-0 tool-icon"></i>
                        <span class="tool-name">${escapeHtml(summary)}</span>
                        <i class="fas fa-chevron-right tool-chevron"></i>
                    </div>
                    <div class="tool-detail">${details.join('')}</div>`;
                stepsEl.appendChild(retrievalEl);
                scrollChatToBottom();

            } else if (item.type === 'tool_start') {
                ensureBotEl();
                if (currentReasoningEl) {
                    finalizeThinking(currentReasoningEl, reasoningStartTime, reasoningText);
                    currentReasoningEl = null;
                    reasoningText = '';
                }
                accumulatedText = '';
                contentEl.innerHTML = '';

                // Add tool execution indicator (collapsible)
                const toolEl = document.createElement('div');
                toolEl.className = 'agent-step agent-tool-step tool-streaming';
                toolEl.dataset.progressReceived = 'false';
                const argsStr = formatToolArgs(item.arguments || {});
                toolEl.innerHTML = `
                    <div class="tool-header" onclick="this.parentElement.classList.toggle('expanded')">
                        <i class="fas fa-cog fa-spin text-primary-400 flex-shrink-0 tool-icon"></i>
                        <span class="tool-name">${item.tool}</span>
                        <span class="tool-substep-count"></span>
                        <i class="fas fa-chevron-right tool-chevron"></i>
                    </div>
                    <div class="tool-detail">
                        <div class="tool-detail-section">
                            <div class="tool-detail-label">Input</div>
                            <pre class="tool-detail-content">${argsStr}</pre>
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
                stepsEl.appendChild(toolEl);
                toolElements.set(item.tool_call_id, toolEl);

                scrollChatToBottom();

            } else if (item.type === 'tool_progress') {
                const toolEl = toolElements.get(item.tool_call_id);
                if (toolEl) {
                    if (toolEl.dataset.progressReceived !== 'true') {
                        toolEl.classList.add('expanded');
                        toolEl.dataset.progressReceived = 'true';
                    }
                    toolEl.querySelector('.tool-live-output').textContent = String(item.content || '');
                    scrollChatToBottom();
                }

            } else if (item.type === 'tool_end') {
                const toolEl = toolElements.get(item.tool_call_id);
                if (toolEl) {
                    const isError = item.status !== 'success';
                    // A hand-off keeps the icon that says what it was, rather
                    // than the generic tick: the teammate's bubble below is the
                    // outcome, and this row is the fact that work was passed on.
                    const handoff = !isError && toolEl.classList.contains('agent-handoff-step');
                    const icon = toolEl.querySelector('.tool-icon');
                    icon.className = isError
                        ? 'fas fa-times text-red-400 flex-shrink-0 tool-icon'
                        : `fas ${handoff ? 'fa-share' : 'fa-check'} text-primary-400 flex-shrink-0 tool-icon`;

                    // Show execution time
                    const nameEl = toolEl.querySelector('.tool-name');
                    if (item.execution_time !== undefined) {
                        nameEl.innerHTML += ` <span class="tool-time">${item.execution_time}s</span>`;
                    }

                    // Fill output section. A tool that wrote its outcome for a
                    // person (item.display) gets rendered as markdown; the raw
                    // result is what the model reads and stays hidden then.
                    const outputLabel = toolEl.querySelector('.tool-output-label');
                    const outputEl = toolEl.querySelector('.tool-live-output');
                    const displayEl = toolEl.querySelector('.tool-display-output');
                    if (outputLabel) outputLabel.textContent = isError ? 'Error' : 'Output';
                    if (displayEl && item.display) {
                        displayEl.innerHTML = renderMarkdown(String(item.display));
                        displayEl.classList.add('has-content');
                        if (outputEl) outputEl.textContent = '';
                    } else if (outputEl) {
                        outputEl.textContent = item.result ? String(item.result) : '';
                        outputEl.classList.toggle('tool-error-text', isError);
                    }

                    toolEl.classList.remove('tool-streaming');
                    // Tools collapse once they are done; their output is a
                    // trace. A tool that wrote something for a person to read
                    // stays open — the reader just waited for it. A hand-off is
                    // the exception: its answer is already the bubble below, so
                    // it folds away and keeps the task it passed on for whoever
                    // opens it.
                    toolEl.classList.toggle('expanded', !!item.display && !handoff);
                    if (!item.result && !item.display) {
                        const outputSection = toolEl.querySelector('.tool-output-section');
                        if (outputSection) outputSection.remove();
                    }
                    if (isError) toolEl.classList.add('tool-failed');
                    // A permission refusal is not an ordinary failure: surface a
                    // one-click way to raise this session's permission instead of
                    // leaving the user to decode the model's error text.
                    if (item.permission_denied) {
                        _appendPermissionDeniedHint(toolEl, item.permission_mode);
                    }
                    toolElements.delete(item.tool_call_id);
                }

            } else if (item.type === 'subagent_step') {
                // A tool call made inside a sub agent, rendered under that sub
                // agent's card so its minutes of work are followable.
                renderSubagentStep(toolElements.get(item.card_id), item);
                scrollChatToBottom();

            } else if (item.type === 'image') {
                ensureBotEl();
                const imgEl = document.createElement('img');
                imgEl.src = item.content;
                imgEl.alt = 'screenshot';
                imgEl.style.cssText = 'max-width:600px;border-radius:8px;margin:8px 0;cursor:zoom-in;box-shadow:0 1px 4px rgba(0,0,0,0.1);';
                imgEl.onclick = () => _openImageLightbox(imgEl.src);
                mediaEl.appendChild(imgEl);
                scrollChatToBottom();

            } else if (item.type === 'text') {
                // Intermediate text sent before media items; display it but keep SSE open.
                ensureBotEl();
                contentEl.classList.remove('sse-streaming');
                const textContent = item.content || accumulatedText;
                if (textContent) contentEl.innerHTML = renderMarkdown(textContent);
                applyHighlighting(botEl);
                scrollChatToBottom();

            } else if (item.type === 'video') {
                ensureBotEl();
                const wrapper = document.createElement('div');
                wrapper.innerHTML = _buildVideoHtml(item.content);
                mediaEl.appendChild(wrapper.firstElementChild || wrapper);
                scrollChatToBottom();

            } else if (item.type === 'file') {
                ensureBotEl();
                const fileName = item.file_name || item.content.split('/').pop();
                const fileEl = document.createElement('a');
                fileEl.href = item.content;
                fileEl.download = fileName;
                fileEl.target = '_blank';
                fileEl.className = 'file-attachment';
                fileEl.style.cssText = 'display:inline-flex;align-items:center;gap:6px;padding:8px 14px;margin:8px 0;border-radius:8px;background:var(--bg-secondary,#f3f4f6);color:var(--text-primary,#374151);text-decoration:none;font-size:14px;border:1px solid var(--border-color,#e5e7eb);';
                fileEl.innerHTML = `<i class="fas fa-file-download" style="color:#6b7280;"></i> ${fileName}`;
                mediaEl.appendChild(fileEl);
                scrollChatToBottom();

            } else if (item.type === 'artifact') {
                // A user-facing file the agent wrote; render a card and let the
                // workspace panel decide whether to auto-open it (workspace.js).
                ensureBotEl();
                if (typeof appendArtifactCard === 'function') {
                    appendArtifactCard(mediaEl, item);
                }
                scrollChatToBottom();

            } else if (item.type === 'phase') {
                // Coarse progress (e.g. cow install-browser); must not close SSE (unlike "done")
                ensureBotEl();
                const wrap = document.createElement('div');
                wrap.className = 'text-xs sm:text-sm text-slate-600 dark:text-slate-400 border-l-2 border-primary-400 pl-2 py-1 my-0.5';
                wrap.textContent = String(item.content || '');
                stepsEl.appendChild(wrap);
                scrollChatToBottom();

            } else if (item.type === 'cancelled') {
                // Agent acknowledged the stop; mark the bubble. A trailing
                // "done" still arrives with the partial answer.
                cancelled = true;
                ensureBotEl();
                if (currentReasoningEl) {
                    finalizeThinking(currentReasoningEl, reasoningStartTime, reasoningText);
                    currentReasoningEl = null;
                    reasoningText = '';
                }
                if (!botEl.querySelector('.agent-cancelled-tag')) {
                    const tag = document.createElement('div');
                    tag.className = 'agent-cancelled-tag text-xs text-amber-600 dark:text-amber-400 mt-1';
                    tag.textContent = 'Cancelled';
                    stepsEl.appendChild(tag);
                }
                resetSendBtnSendMode();

            } else if (item.type === 'done') {
                // The answer is persisted, but async attachments may still
                // follow. Only stream_end closes the request lifecycle.
                mainDone = true;
                if (item.bot_seq !== undefined && item.bot_seq !== null) {
                    completedBotSeq = item.bot_seq;
                }
                settlePendingTools();
                resetSendBtnSendMode();

                const finalTextRaw = item.content || accumulatedText;
                const finalText = localizeCancelMarker(finalTextRaw);

                if (!botEl && finalText) {
                    if (loadingEl) { loadingEl.remove(); loadingEl = null; }
                    addBotMessage(finalText, new Date((item.timestamp || Date.now() / 1000) * 1000), requestId);
                } else if (botEl) {
                    contentEl.classList.remove('sse-streaming');
                    if (finalText) contentEl.innerHTML = renderMarkdown(finalText);
                    contentEl.dataset.rawMd = finalTextRaw || '';
                    const copyBtn = botEl.querySelector('.copy-msg-btn');
                    if (copyBtn && finalText) copyBtn.style.display = '';
                    applyHighlighting(botEl);
                }

                // Backfill seq metadata so edit/regenerate buttons can call
                // the delete API without a page refresh. Backend includes
                // user_seq / bot_seq on the done event after persistence.
                // Never a teammate's bubble: the seq being backfilled belongs to
                // the reply this request persisted, which is the Agent's own.
                const targetBotEl = botEl || (requestId
                    ? messagesDiv.querySelector(`[data-request-id="${requestId}"]:not([data-peer-bubble])`)
                    : null);
                if (targetBotEl) {
                    if (item.bot_seq !== undefined && item.bot_seq !== null) {
                        targetBotEl.dataset.seq = item.bot_seq;
                    }
                    // Reveal regenerate button now that the seq is wired up.
                    const regenBtn = targetBotEl.querySelector('.regenerate-msg-btn');
                    if (regenBtn) regenBtn.style.display = '';
                    if (item.user_seq !== undefined && item.user_seq !== null) {
                        // Locate the preceding user bubble for this turn.
                        let prev = targetBotEl.previousElementSibling;
                        while (prev && !prev.classList.contains('user-message-group')) {
                            prev = prev.previousElementSibling;
                        }
                        if (prev && !prev.dataset.seq) {
                            prev.dataset.seq = item.user_seq;
                        }
                    }
                }
                // The turn is persisted: refresh the navigation rail so the new
                // question gets its own dot (only for the foreground session).
                if (isActive() && typeof refreshTimeline === 'function') {
                    refreshTimeline();
                }
                renderBotSpeakerButton(botEl, finalText);
                scrollChatToBottom();

                if (typeof maybeAutoOpenArtifact === 'function') maybeAutoOpenArtifact();

                if (titleInfo) {
                    generateSessionTitle(titleInfo.sid, titleInfo.userMsg, '');
                    titleInfo = null;
                } else if (sessionPanelOpen) {
                    loadSessionList();
                }

            } else if (item.type === 'voice_attach') {
                // TTS finished — attach a playable audio element to the
                // persisted bot bubble. If history is still loading after a
                // session switch, keep the attachment until that bubble exists.
                if (item.url && completedBotSeq !== null) {
                    rememberPendingVoiceAttachment(
                        ownerSession, completedBotSeq, item.url
                    );
                    flushPendingVoiceAttachments(ownerSession, true);
                }

            } else if (item.type === 'stream_end') {
                done = true;
                if (currentEs) { currentEs.close(); }
                delete activeStreams[requestId];
                clearOwnerRequest();

            } else if (item.type === 'resync_required') {
                done = true;
                settlePendingTools();
                if (currentEs) { currentEs.close(); }
                delete activeStreams[requestId];
                clearOwnerRequest();
                resetSendBtnSendMode();
                if (isActive()) {
                    messagesDiv.innerHTML = '';
                    historyPage = 0;
                    historyHasMore = false;
                    historyLoading = false;
                    loadHistory(1);
                }

            } else if (item.type === 'error') {
                done = true;
                settlePendingTools();
                if (currentEs) { currentEs.close(); }
                delete activeStreams[requestId];
                clearOwnerRequest();
                if (loadingEl) { loadingEl.remove(); loadingEl = null; }
                if (contentEl) contentEl.classList.remove('sse-streaming');
                // After a stop the stream is expected to end; the bubble is
                // already tagged "已中止", so don't stack a failure on top.
                // An unknown request after "done" only means its log was
                // reclaimed: the reply is persisted and already on screen.
                const unknown = item.reason === 'unknown_request';
                if (!cancelled && !(unknown && mainDone)) {
                    addBotMessage(t(unknown ? 'error_reply_interrupted' : 'error_send'), new Date());
                }
                resetSendBtnSendMode();
            }
    }

    function connect() {
        const es = new EventSource(
            `/stream?request_id=${encodeURIComponent(requestId)}`
            + `&after_seq=${lastSeq}`
        );
        currentEs = es;
        activeStreams[requestId] = es;

        es.onmessage = function(e) {
            let item;
            try { item = JSON.parse(e.data); } catch (_) { return; }

            const seq = Number(item.seq || 0);
            if (seq && seq <= lastSeq) return;

            // Successful data received, reset reconnect counter
            reconnectCount = 0;

            // Record every event for re-attach replay (capped to avoid
            // unbounded growth on very long streams).
            if (item.type === 'tool_progress' && item.tool_call_id) {
                const previousIndex = buffer.items.findIndex(
                    buffered => buffered.type === 'tool_progress'
                        && buffered.tool_call_id === item.tool_call_id
                );
                if (previousIndex >= 0) buffer.items.splice(previousIndex, 1);
            }
            if (buffer.items.length < 5000) buffer.items.push(item);
            if (seq) lastSeq = seq;

            // done is persisted before it is published. Remember that state
            // even while this session is in the background, where rendering
            // is intentionally skipped. Notify for both foreground and
            // background sessions, before the render guard below.
            if (item.type === 'done') {
                mainDone = true;
                if (item.bot_seq !== undefined && item.bot_seq !== null) {
                    completedBotSeq = item.bot_seq;
                }
                // Scheduler deliveries are notified solely by the global runs
                // poller (maybeNotifyScheduledRun), which forces a notice across
                // all sessions and dedupes by run id. Notifying here too would
                // double-pop, so skip scheduler streams.
                if (!isSchedulerRequest(requestId)) {
                    notifyTaskFinished(ownerSession, 'done', item.content, ownerAgent);
                }
            } else if (item.type === 'error') {
                if (!cancelled && !mainDone && !isSchedulerRequest(requestId)) notifyTaskFinished(ownerSession, 'error', '', ownerAgent);
            } else if (
                item.type === 'voice_attach'
                && item.url
                && completedBotSeq !== null
            ) {
                // Background sessions skip rendering below. Preserve their
                // attachment so loadHistory can mount it when the user returns.
                rememberPendingVoiceAttachment(
                    ownerSession, completedBotSeq, item.url
                );
            }

            // Background session: keep the stream alive so the reply finishes
            // and persists, but skip rendering into the now-foreign view. The
            // buffer above still grows so returning to the session can rebuild
            // the bubble and resume live rendering.
            if (ownerSession !== sessionId) {
                if (item.type === 'stream_end' || item.type === 'error' || item.type === 'resync_required') {
                    done = true;
                    es.close();
                    delete activeStreams[requestId];
                    clearOwnerRequest();
                }
                return;
            }

            processSSEItem(item);
        };

        es.onerror = function() {
            es.close();
            delete activeStreams[requestId];

            if (done) {
                // stream_end or an unrecoverable event already closed it.
                return;
            }

            if (cancelled && !mainDone) {
                // The user stopped the run, so the stream ending here is the
                // expected outcome. Reconnecting would only land on a queue
                // the backend has already reclaimed.
                settlePendingTools();
                clearOwnerRequest();
                if (loadingEl) { loadingEl.remove(); loadingEl = null; }
                if (contentEl) contentEl.classList.remove('sse-streaming');
                resetSendBtnSendMode();
                return;
            }

            if (currentReasoningEl) {
                finalizeThinking(currentReasoningEl, reasoningStartTime, reasoningText);
                currentReasoningEl = null;
                reasoningText = '';
            }

            if (reconnectCount < MAX_RECONNECTS) {
                reconnectCount++;
                const delay = Math.min(RECONNECT_BASE_MS * reconnectCount, 5000);
                console.warn(`[SSE] connection lost for ${requestId}, reconnecting in ${delay}ms (attempt ${reconnectCount}/${MAX_RECONNECTS})`);
                setTimeout(connect, delay);
                return;
            }

            // Exhausted retries. Only surface the failure in the owning view —
            // a background session must not mutate the currently shown chat.
            clearOwnerRequest();
            settlePendingTools();
            if (!isActive()) return;
            if (loadingEl) { loadingEl.remove(); loadingEl = null; }
            if (botEl && contentEl) {
                contentEl.classList.remove('sse-streaming');
                if (accumulatedText) contentEl.innerHTML = renderMarkdown(accumulatedText);
                applyHighlighting(botEl);
            }
            // The message itself was accepted; only the live view dropped, and
            // the server may still finish and persist the reply.
            if (!mainDone) addBotMessage(t('error_connection_lost'), new Date());
            resetSendBtnSendMode();
        };
    }

    // Re-attach replay: rebuild the bubble from buffered events (snapshot,
    // not animated) before connecting for the live tail. `processSSEItem`
    // is the same renderer used by the live onmessage handler, so the
    // snapshot matches exactly what live rendering would have produced.
    if (replayItems && replayItems.length) {
        for (const item of replayItems) {
            const seq = Number(item.seq || 0);
            if (seq > lastSeq) lastSeq = seq;
            try { processSSEItem(item); } catch (_) {}
            if (item.type === 'stream_end' || item.type === 'error' || item.type === 'resync_required') {
                done = true;
            }
        }
        // If the buffered stream already finished, don't reconnect — the
        // reply is complete and persisted; show its final state and stop.
        if (done) {
            clearOwnerRequest();
            resetSendBtnSendMode();
            scrollChatToBottom(true);
            return;
        }
    }

    connect();
}

function startPolling() {
    const gen = ++pollGeneration;
    isPolling = true;
    let pollInFlight = false;

    function poll() {
        if (gen !== pollGeneration) return;
        if (pollInFlight) return;
        // Keep polling while hidden: push messages are exactly what the
        // notification below should deliver to a background tab.
        pollInFlight = true;
        fetch('/poll', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ session_id: sessionId })
        })
        .then(r => r.json())
        .then(data => {
            pollInFlight = false;
            if (gen !== pollGeneration) return;
            if (data.status === 'success' && data.has_content) {
                const rid = data.request_id;
                if (loadingContainers[rid]) {
                    loadingContainers[rid].remove();
                    delete loadingContainers[rid];
                }
                // Skip if this reply is already on screen. Happens when a reply
                // arrives via both the SSE stream and the poll queue (e.g. the
                // user switched away mid-run, leaving the queued reply to be
                // re-fetched on return) — render it only once.
                const already = rid && messagesDiv.querySelector(
                    `[data-request-id="${rid}"]`
                );
                if (!already) {
                    const welcomeScreen = document.getElementById('welcome-screen');
                    if (welcomeScreen) welcomeScreen.remove();
                    addBotMessage(data.content, new Date(data.timestamp * 1000), rid);
                    scrollChatToBottom();
                    // Scheduler executions are notified by the global runs poll
                    // (maybeNotifyScheduledRun) — it forces a notice across ALL
                    // sessions, including this one and manual "run now", and
                    // dedupes by run id. Notifying here too would double-pop, so
                    // only notify for an ordinary missed reply.
                    if (!isSchedulerRequest(rid)) {
                    showTaskNotification(
                        sessionTitleOf(sessionId) || 'CowAgent',
                        firstLineSnippet(data.content),
                            sessionId,
                            activeAgentId
                    );
                    }
                }
            }
            const delay = (data.status === 'success' && data.has_content) ? 5000 : 10000;
            setTimeout(poll, delay);
        })
        .catch(() => { pollInFlight = false; setTimeout(poll, 10000); });
    }
    poll();
}

