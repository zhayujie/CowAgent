/* Per-session composer drafts, unread tracking and the status shown on each
   session row (running / finished unseen / unsent draft).
   These are classic scripts sharing one global scope; see
   channel/web/README.md before changing the load order. */

// =====================================================================
// Composer drafts (one per conversation)
// =====================================================================
// The composer is a single textarea shared by every session, so without this
// the text typed in one conversation followed the user into the next one.
// Drafts are keyed by runtimeSessionKey and persisted, so they survive a reload.
const _DRAFTS_KEY = 'cow_chat_drafts';
const _drafts = _loadJSON(_DRAFTS_KEY, {});
// Conversation the composer currently holds the draft of.
let _draftKey = runtimeSessionKey(sessionId);
let _draftPersistTimer = null;

function _loadJSON(key, fallback) {
    try {
        const raw = localStorage.getItem(key);
        const parsed = raw ? JSON.parse(raw) : null;
        return parsed && typeof parsed === 'object' ? parsed : fallback;
    } catch (_) { return fallback; }
}

function _persistDrafts() {
    if (_draftPersistTimer) { clearTimeout(_draftPersistTimer); _draftPersistTimer = null; }
    try { localStorage.setItem(_DRAFTS_KEY, JSON.stringify(_drafts)); } catch (_) {}
}

function _schedulePersistDrafts() {
    if (_draftPersistTimer) return;
    _draftPersistTimer = setTimeout(_persistDrafts, 300);
}

/** Store what the composer holds under the conversation it belongs to. */
function saveComposerDraft() {
    const text = chatInput.value;
    // In-flight uploads can't be restored later; only finished ones are kept.
    const attachments = pendingAttachments.filter(a => !a._uploading);
    const had = !!_drafts[_draftKey];
    if (!text.trim() && !attachments.length) {
        if (!had) return;
        delete _drafts[_draftKey];
    } else {
        _drafts[_draftKey] = { text, attachments };
    }
    _schedulePersistDrafts();
    if (had !== !!_drafts[_draftKey]) refreshSessionStatus();
}

/**
 * The composer moved to another conversation (sessionId / activeAgentId just
 * changed): file the current input under the previous one and load the draft
 * of the one being opened.
 */
function swapComposerDraft() {
    const nextKey = runtimeSessionKey(sessionId);
    if (nextKey === _draftKey) return;
    saveComposerDraft();
    _draftKey = nextKey;
    const draft = _drafts[nextKey];
    chatInput.value = draft ? draft.text : '';
    pendingAttachments = draft ? draft.attachments.slice() : [];
    historyIdx = -1;
    historySavedDraft = '';
    renderAttachmentPreview();
    if (chatInput.value) autoResizeComposer(); else resetComposerHeight();
    updateSendBtnState();
    refreshSessionStatus();
}

/**
 * An upload finished. If the composer moved to another conversation meanwhile,
 * the placeholder is in neither list, so file it under the one it was added in.
 */
function fileFinishedUpload(key, attachment) {
    if (pendingAttachments.includes(attachment)) return;
    if (key === _draftKey) {
        pendingAttachments.push(attachment);
        renderAttachmentPreview();
        updateSendBtnState();
        saveComposerDraft();
        return;
    }
    const draft = _drafts[key] || (_drafts[key] = { text: '', attachments: [] });
    draft.attachments.push(attachment);
    _schedulePersistDrafts();
    refreshSessionStatus();
}

function dropSessionDraft(sid, agentId) {
    const key = runtimeSessionKey(sid, agentId || activeAgentId);
    if (!_drafts[key]) return;
    delete _drafts[key];
    _persistDrafts();
}

chatInput.addEventListener('input', saveComposerDraft);
window.addEventListener('beforeunload', () => { saveComposerDraft(); _persistDrafts(); });

(function _restoreInitialDraft() {
    const draft = _drafts[_draftKey];
    if (!draft) return;
    chatInput.value = draft.text;
    pendingAttachments = draft.attachments.slice();
    renderAttachmentPreview();
    if (chatInput.value) autoResizeComposer();
    updateSendBtnState();
})();

// =====================================================================
// Unread conversations
// =====================================================================
// A conversation whose run finished (or that received a message) while the
// user wasn't looking at it. Persisted so an unseen result survives a reload.
const _UNREAD_KEY = 'cow_unread_sessions';
const _unread = new Set(_loadJSON(_UNREAD_KEY, []));

function _persistUnread() {
    try { localStorage.setItem(_UNREAD_KEY, JSON.stringify([..._unread])); } catch (_) {}
}

/** The user is looking at this conversation right now. */
function _isViewingSession(sid, agentId) {
    return sid === sessionId
        && (!agentId || agentId === activeAgentId)
        && currentView === 'chat'
        && !document.hidden
        && document.hasFocus();
}

function markSessionUnread(sid, agentId) {
    if (!sid || _isViewingSession(sid, agentId)) return;
    const key = runtimeSessionKey(sid, agentId || activeAgentId);
    if (_unread.has(key)) return;
    _unread.add(key);
    _persistUnread();
    refreshSessionStatus();
}

function clearSessionUnread(sid, agentId) {
    const key = runtimeSessionKey(sid, agentId || activeAgentId);
    if (!_unread.delete(key)) return;
    _persistUnread();
    refreshSessionStatus();
}

/** Opening a conversation, or coming back to it, counts as reading it. */
function clearViewingUnread() {
    if (_isViewingSession(sessionId)) clearSessionUnread(sessionId);
}

window.addEventListener('focus', clearViewingUnread);
document.addEventListener('visibilitychange', clearViewingUnread);

// =====================================================================
// Session row status
// =====================================================================
function _rowAgent(agentId) {
    return agentId || activeAgentId;
}

/** 'running' | 'unread' | 'draft' | '' for one conversation, highest first. */
function sessionStatusOf(sid, agentId) {
    const key = runtimeSessionKey(sid, _rowAgent(agentId));
    if (sessionActiveRequest[key]) return 'running';
    if (_unread.has(key)) return 'unread';
    // The open conversation's draft is right there in the composer.
    if (_drafts[key] && key !== runtimeSessionKey(sessionId)) return 'draft';
    return '';
}

const _STATUS_ICON = {
    running: '<i class="fas fa-spinner fa-spin"></i>',
    unread: '<span class="session-status-dot"></span>',
    draft: '<i class="fas fa-pencil"></i>',
};
const _STATUS_LABEL = {
    running: 'session_running',
    unread: 'session_unread',
    draft: 'session_draft',
};

function applySessionStatus(item) {
    const el = item.querySelector('.session-status');
    if (!el) return;
    const status = sessionStatusOf(item.dataset.sessionId, item.dataset.agentId);
    if (el.dataset.status === status) return;
    el.dataset.status = status;
    el.innerHTML = status ? _STATUS_ICON[status] : '';
    if (status) el.setAttribute('aria-label', t(_STATUS_LABEL[status]));
    else el.removeAttribute('aria-label');
}

/** Repaint every row's status, plus the hint on collapsed project headers. */
function refreshSessionStatus() {
    document.querySelectorAll('.session-item[data-session-id]').forEach(applySessionStatus);
    if (typeof _sessionGroups !== 'function' || _sessionGroupMode !== 'project') return;
    const groups = new Map(_sessionGroups().map(g => [g.key, g]));
    document.querySelectorAll('.session-group-project[data-space-key]').forEach(header => {
        const group = groups.get(header.dataset.spaceKey);
        const busy = !!group && _collapsedProjects.has(group.key) && group.items.some(s => {
            const status = sessionStatusOf(s.session_id, s.agent && s.agent.id);
            return status === 'running' || status === 'unread';
        });
        header.classList.toggle('has-activity', busy);
    });
}
