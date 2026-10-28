/* Channel users: the people who reached the Agent over an IM channel.

   The console's own conversations are the `web` channel; everyone who wrote in
   through WeChat, Feishu, Telegram and so on lives in the same store under a
   different channel type, and nothing in the console showed them. This view
   lists those people and replays each conversation.

   Read-only on purpose: replying to a channel user means going back out through
   the instance that logged the channel in, with its own credentials and login
   state, which is what the channel itself and the scheduler's cross-channel
   delivery are for. A transcript here is for looking at, so the edit / delete /
   regenerate controls the shared bubble builders add are hidden by CSS.

   These are classic scripts sharing one global scope; see
   channel/web/README.md before changing the load order. Depends on the bubble
   builders in chat/render.js, which is why it loads with the views rather than
   with core/. */

const CU_PAGE_SIZE = 50;
let cuSessions = [];
let cuChannels = [];
let cuChannelLabels = {};
let cuChannelFilter = '';
let cuPage = 1;
let cuHasMore = false;
let cuListLoading = false;
let cuListRequest = 0;
let cuSelectedId = '';
let cuSelectedAgent = '';
let cuConvLoading = false;

// ---------------------------------------------------------------- labels

function cuChannelLabel(channelType) {
    const known = cuChannelLabels[channelType];
    return known || channelType || t('users_unknown_channel');
}

function cuLoadChannelLabels() {
    // Channel display names are localized on the backend, next to the channel
    // definitions, so this view reuses them instead of keeping a second table
    // that would drift the moment a channel is added.
    return fetch(`/api/channels?lang=${encodeURIComponent(currentLang)}`)
        .then(r => r.json())
        .then(data => {
            if (data.status !== 'success') return;
            (data.channels || []).forEach(ch => {
                if (!ch.name) return;
                const label = (typeof ch.label === 'object' && ch.label !== null)
                    ? (ch.label[currentLang] || ch.label.en)
                    : ch.label;
                cuChannelLabels[ch.name] = label || ch.name;
            });
            cuRenderChannelChips();
            cuRenderList();
        })
        .catch(() => {});
}

// ---------------------------------------------------------------- list

function loadChannelUsersView() {
    cuLoadChannelLabels();
    cuLoadSessions(1, true);
}

function cuLoadSessions(page, replace) {
    // Last request wins. Clicking a filter chip while a page is still in flight
    // would otherwise be dropped, leaving the chip lit over the old list.
    const token = ++cuListRequest;
    cuListLoading = true;
    if (replace) cuRenderList();
    const filter = cuChannelFilter ? `&channel_type=${encodeURIComponent(cuChannelFilter)}` : '';
    return fetch(`/api/channel_sessions?page=${page}&page_size=${CU_PAGE_SIZE}${filter}`)
        .then(r => r.json())
        .then(data => {
            if (token !== cuListRequest) return;
            cuListLoading = false;
            if (data.status !== 'success') {
                cuRenderListError(data.message || '');
                return;
            }
            cuChannels = data.channels || [];
            cuPage = data.page || page;
            cuHasMore = !!data.has_more;
            cuSessions = replace
                ? (data.sessions || [])
                : cuSessions.concat(data.sessions || []);
            cuRenderChannelChips();
            cuRenderList();
            if (!cuSelectedId) cuRenderEmptyConversation();
        })
        .catch(() => {
            if (token !== cuListRequest) return;
            cuListLoading = false;
            cuRenderListError('');
        });
}

function cuRenderChannelChips() {
    const box = document.getElementById('cu-channels');
    if (!box) return;
    // Index-addressed like the rows, so no channel string sits inside an
    // attribute where a quote would end it early.
    const chip = (index, value, label, count) => `
        <button class="cu-chip${cuChannelFilter === value ? ' active' : ''}"
                role="tab"
                aria-selected="${cuChannelFilter === value ? 'true' : 'false'}"
                data-index="${index}"
                onclick="cuSetChannelFilterAt(this.dataset.index)">
            ${escapeHtml(label)}${count ? `<span class="cu-chip-count">${count}</span>` : ''}
        </button>`;
    const all = cuChannels.reduce((sum, ch) => sum + (ch.session_count || 0), 0);
    box.innerHTML = chip(-1, '', t('users_filter_all'), all)
        + cuChannels.map((ch, i) => chip(
            i,
            ch.channel_type,
            cuChannelLabel(ch.channel_type),
            ch.session_count || 0
        )).join('');
}

function cuSetChannelFilterAt(index) {
    const slot = Number(index);
    if (slot === -1) {
        cuSetChannelFilter('');
        return;
    }
    const channel = cuChannels[slot];
    if (channel) cuSetChannelFilter(channel.channel_type);
}

function cuSetChannelFilter(channelType) {
    if (cuChannelFilter === (channelType || '')) return;
    cuChannelFilter = channelType || '';
    // The open conversation may not be in the new list, and leaving it on
    // screen under a filter that excludes it reads as if the filter is broken.
    cuSessions = [];
    cuSelectedId = '';
    cuSelectedAgent = '';
    cuRenderChannelChips();
    cuRenderEmptyConversation();
    cuLoadSessions(1, true);
}

function cuRenderListError(message) {
    const box = document.getElementById('cu-list');
    if (!box) return;
    box.innerHTML = `
        <div class="cu-empty">
            <i class="fas fa-triangle-exclamation"></i>
            <p>${escapeHtml(message || t('users_load_failed'))}</p>
        </div>`;
}

function cuRenderList() {
    const box = document.getElementById('cu-list');
    if (!box) return;
    // Selecting a user redraws the list, and dropping the scroll position would
    // throw the row the user just clicked back to the top of the pane.
    const scroll = box.scrollTop;
    if (cuListLoading && !cuSessions.length) {
        box.innerHTML = `<div class="cu-empty"><p>${t('users_loading')}</p></div>`;
        return;
    }
    if (!cuSessions.length) {
        // Under a filter, "no channel users yet" is the wrong story: the empty
        // list is this channel's, not the whole console's.
        const empty = cuChannelFilter
            ? t('users_empty_filtered').replace(
                '{name}', cuChannelLabel(cuChannelFilter)
            )
            : t('users_empty');
        box.innerHTML = `
            <div class="cu-empty">
                <i class="fas fa-user-group"></i>
                <p>${escapeHtml(empty)}</p>
                ${cuChannelFilter ? '' : `<p class="cu-empty-sub">${t('users_empty_desc')}</p>`}
            </div>`;
        return;
    }
    box.innerHTML = cuSessions.map((s, i) => cuSessionRowHtml(s, i)).join('')
        + (cuHasMore
            ? `<button class="cu-more" onclick="cuLoadMore()">${t('users_load_more')}</button>`
            : '');
    box.scrollTop = scroll;
}

// The row carries an index rather than the session id: escapeHtml escapes text
// but not quotes, so an id interpolated into an attribute would break out of it.
// The index is this file's own number, and the id is read back from the array.
function cuSessionRowHtml(s, index) {
    const active = s.session_id === cuSelectedId ? ' active' : '';
    const agent = s.agent || {};
    const groupTag = s.is_group
        ? `<span class="cu-tag">${t('users_group')}</span>`
        : '';
    const preview = (s.title || '').trim();
    return `
        <button class="cu-row${active}"
                onclick="cuOpenSessionAt(this.dataset.index)"
                data-index="${index}">
            <div class="cu-row-top">
                <span class="cu-row-name">${escapeHtml(s.name || s.session_id)}</span>
                <span class="cu-row-time">${s.last_active ? formatTime(new Date(s.last_active * 1000)) : ''}</span>
            </div>
            ${preview ? `<div class="cu-row-preview">${escapeHtml(preview)}</div>` : ''}
            <div class="cu-row-meta">
                <span class="cu-tag cu-tag-channel">${escapeHtml(cuChannelLabel(s.channel_type))}</span>
                ${groupTag}
                ${agent.name ? `<span class="cu-tag cu-tag-agent">${escapeHtml(agent.name)}</span>` : ''}
                <span class="cu-row-count">${t('users_message_count').replace('{n}', s.msg_count || 0)}</span>
            </div>
        </button>`;
}

function cuLoadMore() {
    if (!cuHasMore || cuListLoading) return;
    cuLoadSessions(cuPage + 1, false);
}

// ---------------------------------------------------------------- transcript

function cuRenderEmptyConversation() {
    const head = document.getElementById('cu-conv-head');
    const body = document.getElementById('cu-conv-body');
    if (!head || !body) return;
    head.innerHTML = '';
    body.innerHTML = `
        <div class="cu-empty cu-empty-main">
            <i class="fas fa-comments"></i>
            <p>${t('users_pick_hint')}</p>
        </div>`;
}

function cuOpenSessionAt(index) {
    const session = cuSessions[Number(index)];
    if (!session) return;
    cuSelectedAgent = session.agent_id || '';
    cuOpenSession(session.session_id);
}

function cuOpenSession(sessionId) {
    if (!sessionId) return;
    cuSelectedId = sessionId;
    cuRenderList();
    cuLoadConversation(1);
}

function cuSelectedSession() {
    return cuSessions.find(s => s.session_id === cuSelectedId) || null;
}

function cuFetchHistory(page) {
    const agent = cuSelectedAgent ? `&agent_id=${encodeURIComponent(cuSelectedAgent)}` : '';
    return fetch(`/api/history?session_id=${encodeURIComponent(cuSelectedId)}&page=${page}&page_size=20${agent}`)
        .then(r => r.json());
}

function cuLoadConversation(page) {
    const sessionId = cuSelectedId;
    cuConvLoading = true;
    const body = document.getElementById('cu-conv-body');
    if (body) body.innerHTML = `<div class="cu-empty cu-empty-main"><p>${t('users_loading')}</p></div>`;
    cuRenderConversationHead(cuSelectedSession());
    return cuFetchHistory(page)
        .then(data => {
            // The user may have picked someone else while this was in flight.
            if (sessionId !== cuSelectedId) return;
            cuConvLoading = false;
            if (data.status !== 'success') {
                cuRenderConversationError(data.message || '');
                return;
            }
            const messages = data.messages || [];
            cuRenderTranscript(messages, !!data.has_more, page);
            if (!messages.length) {
                const el = document.getElementById('cu-conv-body');
                if (el) {
                    el.innerHTML = `
                        <div class="cu-empty cu-empty-main">
                            <i class="fas fa-inbox"></i>
                            <p>${t('users_no_messages')}</p>
                        </div>`;
                }
            }
        })
        .catch(() => {
            if (sessionId !== cuSelectedId) return;
            cuConvLoading = false;
            cuRenderConversationError('');
        });
}

function cuRenderConversationHead(session) {
    const head = document.getElementById('cu-conv-head');
    if (!head) return;
    if (!session) {
        head.innerHTML = '';
        return;
    }
    const agent = session.agent || {};
    head.innerHTML = `
        <div class="cu-conv-title">
            <span class="cu-conv-name">${escapeHtml(session.name || session.session_id)}</span>
            <span class="cu-tag cu-tag-channel">${escapeHtml(cuChannelLabel(session.channel_type))}</span>
            ${agent.name ? `<span class="cu-tag cu-tag-agent">${escapeHtml(agent.name)}</span>` : ''}
        </div>
        <div class="cu-conv-sub">
            <span>${escapeHtml(session.session_id)}</span>
            <span class="cu-conv-readonly"><i class="fas fa-eye"></i> ${t('users_readonly_hint')}</span>
        </div>`;
}

function cuRenderConversationError(message) {
    const body = document.getElementById('cu-conv-body');
    if (!body) return;
    body.innerHTML = `
        <div class="cu-empty cu-empty-main">
            <i class="fas fa-triangle-exclamation"></i>
            <p>${escapeHtml(message || t('users_load_failed'))}</p>
        </div>`;
}

function cuRenderTranscript(messages, hasMore, page) {
    const body = document.getElementById('cu-conv-body');
    if (!body) return;
    body.innerHTML = '';
    if (hasMore) {
        const btn = document.createElement('button');
        btn.className = 'cu-more cu-more-top';
        btn.textContent = t('users_load_older');
        btn.onclick = () => cuLoadOlder(page);
        body.appendChild(btn);
    }
    messages.forEach(msg => cuAppendMessage(body, msg));
    body.scrollTop = body.scrollHeight;
}

function cuLoadOlder(page) {
    if (cuConvLoading) return;
    const next = (page || 1) + 1;
    const sessionId = cuSelectedId;
    cuConvLoading = true;
    const body = document.getElementById('cu-conv-body');
    const prevHeight = body ? body.scrollHeight : 0;
    cuFetchHistory(next)
        .then(data => {
            if (sessionId !== cuSelectedId || data.status !== 'success') {
                cuConvLoading = false;
                return;
            }
            if (!body) {
                cuConvLoading = false;
                return;
            }
            // Older turns go above what is on screen. The "load older" button
            // sits at the very top, so replacing it means dropping it and
            // putting a fresh one (or nothing, on the last page) in its place.
            const anchor = body.querySelector('.cu-more-top');
            const frag = document.createDocumentFragment();
            if (data.has_more) {
                const btn = document.createElement('button');
                btn.className = 'cu-more cu-more-top';
                btn.textContent = t('users_load_older');
                btn.onclick = () => cuLoadOlder(next);
                frag.appendChild(btn);
            }
            // Oldest first: the API returns a page in chronological order, and
            // this page is older than everything already rendered.
            (data.messages || []).forEach(msg => cuAppendMessage(frag, msg));
            body.insertBefore(frag, body.firstChild);
            if (anchor) anchor.remove();
            // Prepending grows the scroll height by exactly the height added;
            // scrolling down by that much keeps the same text under the eye.
            body.scrollTop += body.scrollHeight - prevHeight;
            cuConvLoading = false;
        })
        .catch(() => { cuConvLoading = false; });
}

function cuAppendMessage(container, msg) {
    const ts = new Date((msg.created_at || 0) * 1000);
    if (msg.role === 'user') {
        container.appendChild(createUserMessageEl(msg.content || '', ts));
        return;
    }
    if (msg.role !== 'assistant') return;
    const hasContent = msg.content && msg.content.trim();
    const hasSteps = msg.steps && msg.steps.length > 0;
    const hasToolCalls = msg.tool_calls && msg.tool_calls.length > 0;
    if (!hasContent && !hasSteps && !hasToolCalls && !msg.run_state) return;
    // One stored turn can be several bubbles; the shared builder renders each
    // part, exactly as the chat view does when it replays history.
    splitAssistantTurn(msg).forEach(part => {
        container.appendChild(
            createBotMessageEl(part.msg.content || '', ts, null, part.msg, part.peer)
        );
    });
}
