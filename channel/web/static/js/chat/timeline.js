/* Message navigator: jump back to an earlier question in a long conversation,
   where one agent turn can span many tool/thinking steps. The header button
   (#timeline-toggle-btn) drops a list of the conversation's questions; picking
   one glides the view to it.

   These are classic scripts sharing one global scope; see channel/web/README.md
   before changing the load order. Needs chat/state.js (messagesDiv, sessionId)
   and chat/render.js (loadHistory), and is driven by refreshTimeline() /
   resetTimeline() calls from the history / session-switch / send paths. */

// Gap left above the question once the view lands on it.
const TIMELINE_LAND_OFFSET = 16;
const TIMELINE_GLIDE_MS = 320;

// User-message index for the session on screen: [{seq, preview, created_at}],
// oldest first.
let _timelineItems = [];
let _timelineFetchToken = 0;
let _timelineActiveSeq = null;
let _timelineEls = null; // { panel, list, btn }
let _timelineOpen = false;
let _timelineGlide = 0; // rAF id of the running glide, 0 when idle
let _timelineJumpToken = 0;

function _timelineEnsureDom() {
    if (_timelineEls) return _timelineEls;
    const btn = document.getElementById('timeline-toggle-btn');
    if (!btn) return null;

    const panel = document.createElement('div');
    panel.id = 'chat-timeline-panel';
    panel.className = 'chat-timeline-panel hidden';
    const list = document.createElement('div');
    list.className = 'chat-timeline-list';
    panel.appendChild(list);
    document.body.appendChild(panel);
    _timelineEls = { panel, list, btn };

    // The navigator belongs to the chat view only; follow view switches.
    const chatView = document.getElementById('view-chat');
    if (chatView) {
        const sync = () => {
            const inChat = chatView.classList.contains('active');
            btn.classList.toggle('hidden', !inChat);
            if (!inChat) _timelineClosePanel();
        };
        sync();
        new MutationObserver(sync).observe(chatView, { attributes: true, attributeFilter: ['class'] });
    }

    btn.addEventListener('click', (e) => {
        e.stopPropagation();
        if (_timelineOpen) _timelineClosePanel();
        else _timelineOpenPanel();
    });
    list.addEventListener('click', (e) => {
        const row = e.target.closest('.chat-timeline-row');
        if (!row) return;
        _timelineClosePanel();
        timelineJumpTo(parseInt(row.dataset.seq, 10));
    });
    document.addEventListener('click', (e) => {
        if (!_timelineOpen || panel.contains(e.target) || btn.contains(e.target)) return;
        _timelineClosePanel();
    });
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && _timelineOpen) _timelineClosePanel();
    });
    window.addEventListener('resize', _timelineClosePanel);

    // Any gesture of the user's own takes the wheel back from a running glide.
    ['wheel', 'touchstart', 'keydown', 'mousedown'].forEach(type => {
        messagesDiv.addEventListener(type, _timelineStopGlide, { passive: true });
    });
    return _timelineEls;
}

function _timelineRender() {
    const els = _timelineEnsureDom();
    if (!els) return;
    const enough = _timelineItems.length >= 2;
    els.btn.classList.toggle('timeline-empty', !enough);
    if (!enough) {
        els.list.innerHTML = '';
        _timelineClosePanel();
        return;
    }
    els.list.innerHTML = _timelineItems.map(it =>
        `<button type="button" class="chat-timeline-row" data-seq="${it.seq}">
            <span class="chat-timeline-row-text">${escapeHtml(it.preview || '')}</span>
            <span class="chat-timeline-row-dash"></span>
        </button>`
    ).join('');
    if (_timelineOpen) _timelineMarkActive();
}

// Which question the reader is at: the last user bubble above the upper third
// of the viewport (the latest one when none is).
function _timelineCurrentSeq() {
    const box = messagesDiv.getBoundingClientRect();
    const line = box.top + box.height * 0.35;
    let seq = null;
    const bubbles = messagesDiv.querySelectorAll('.user-message-group[data-seq]');
    for (const el of bubbles) {
        if (el.getBoundingClientRect().top <= line) seq = parseInt(el.dataset.seq, 10);
        else break;
    }
    if (seq === null && bubbles.length) seq = parseInt(bubbles[0].dataset.seq, 10);
    return seq;
}

function _timelineMarkActive() {
    _timelineActiveSeq = _timelineCurrentSeq();
    let activeRow = null;
    _timelineEls.list.querySelectorAll('.chat-timeline-row').forEach(row => {
        const on = parseInt(row.dataset.seq, 10) === _timelineActiveSeq;
        row.classList.toggle('is-active', on);
        if (on) activeRow = row;
    });
    const rows = _timelineEls.list.querySelectorAll('.chat-timeline-row');
    if (!activeRow && rows.length) {
        activeRow = rows[rows.length - 1];
        activeRow.classList.add('is-active');
    }
    return activeRow;
}

function _timelineOpenPanel() {
    const els = _timelineEnsureDom();
    if (!els || _timelineItems.length < 2) return;
    _timelineOpen = true;
    els.panel.classList.remove('hidden');
    els.btn.classList.add('is-active');
    // Below the header button, kept inside the viewport (full width on phones).
    const b = els.btn.getBoundingClientRect();
    const w = els.panel.offsetWidth;
    els.panel.style.left = `${Math.max(12, Math.min(b.left, window.innerWidth - w - 12))}px`;
    els.panel.style.top = `${b.bottom + 6}px`;
    // Open on the question the reader is at.
    const row = _timelineMarkActive();
    if (row) {
        els.list.scrollTop = row.offsetTop - els.list.clientHeight / 2 + row.offsetHeight / 2;
    }
}

function _timelineClosePanel() {
    _timelineOpen = false;
    if (!_timelineEls) return;
    _timelineEls.panel.classList.add('hidden');
    _timelineEls.btn.classList.remove('is-active');
}

function _timelineFindBubble(seq) {
    return messagesDiv.querySelector(`.user-message-group[data-seq="${CSS.escape(String(seq))}"]`);
}

// Move the list, flagged as programmatic so the scroll listener in state.js
// neither reads it as the user scrolling nor re-arms follow-the-stream.
function _timelineSetScroll(y) {
    if (Math.abs(messagesDiv.scrollTop - y) < 0.5) return;
    _programmaticScroll = true;
    messagesDiv.scrollTop = y;
    _lastScrollTop = messagesDiv.scrollTop;
}

function _timelineStopGlide() {
    if (_timelineGlide) cancelAnimationFrame(_timelineGlide);
    _timelineGlide = 0;
    messagesDiv.style.overflowAnchor = '';
}

// Glide to a bubble. The target is re-measured every frame, so images or code
// blocks that finish rendering mid-flight shift the landing spot instead of
// leaving the view short and snapping back. A long hop starts a little way
// off the target so the visible glide stays short.
function _timelineGlideTo(el) {
    _timelineStopGlide();
    _autoScrollEnabled = false;
    // Freshly prepended bubbles keep growing for a few frames. Scroll anchoring
    // would answer each growth with a scroll of its own, after ours, and the
    // two tug the view back and forth; the glide already tracks the target.
    messagesDiv.style.overflowAnchor = 'none';
    const maxTop = () => messagesDiv.scrollHeight - messagesDiv.clientHeight;
    const targetOf = () => {
        const y = el.getBoundingClientRect().top - messagesDiv.getBoundingClientRect().top
            + messagesDiv.scrollTop - TIMELINE_LAND_OFFSET;
        return Math.max(0, Math.min(y, maxTop()));
    };
    const lead = messagesDiv.clientHeight * 0.6;
    let from = messagesDiv.scrollTop;
    const first = targetOf();
    if (Math.abs(first - from) > lead * 2) {
        from = first + (first > from ? -lead : lead);
        _timelineSetScroll(from);
    }
    // Clocked from the first frame: a frame's timestamp is when it began, which
    // after a long task (a big history prepend) predates any performance.now()
    // taken before it, and a negative progress would fling the view backwards.
    let started = 0;
    let lastTarget = first;
    const step = (now) => {
        if (!started) started = now;
        const p = Math.min(1, (now - started) / TIMELINE_GLIDE_MS);
        const eased = 1 - Math.pow(1 - p, 3);
        // Content above resized mid-flight: carry the start along with the
        // target so the glide keeps its direction instead of backing up.
        const target = targetOf();
        from += target - lastTarget;
        lastTarget = target;
        _autoScrollEnabled = false;
        _timelineSetScroll(from + (target - from) * eased);
        if (p < 1) {
            _timelineGlide = requestAnimationFrame(step);
        } else {
            _timelineStopGlide();
            _timelineFlash(el);
        }
    };
    _timelineGlide = requestAnimationFrame(step);
}

function _timelineFlash(el) {
    const bubble = el.querySelector('.user-bubble') || el;
    bubble.classList.remove('timeline-flash');
    void bubble.offsetWidth;
    bubble.classList.add('timeline-flash');
    setTimeout(() => bubble.classList.remove('timeline-flash'), 1600);
}

// Jump to a user message by seq. An old question may sit in a history page
// that isn't loaded yet: fetch everything back to it in one request (the
// prepend keeps the viewport still), then glide there.
async function timelineJumpTo(seq) {
    const token = ++_timelineJumpToken;
    _timelineStopGlide();
    const jumpSession = sessionId;
    let el = _timelineFindBubble(seq);
    if (!el && historyHasMore) {
        _timelineSetBusy(true);
        try {
            await _timelineWaitHistoryIdle();
            if (!_timelineFindBubble(seq) && historyHasMore) {
                await loadHistory(historyPage + 1, seq);
            }
        } finally {
            if (token === _timelineJumpToken) _timelineSetBusy(false);
        }
        if (token !== _timelineJumpToken || jumpSession !== sessionId) return;
        el = _timelineFindBubble(seq);
    }
    if (el) _timelineGlideTo(el);
}

// A scroll-to-top load may already be in flight; let it land first.
function _timelineWaitHistoryIdle() {
    return new Promise((resolve) => {
        const started = Date.now();
        const poll = () => {
            if (!historyLoading || Date.now() - started > 10000) resolve();
            else setTimeout(poll, 30);
        };
        poll();
    });
}

function _timelineSetBusy(busy) {
    const icon = _timelineEls && _timelineEls.btn.querySelector('i');
    if (!icon) return;
    icon.classList.toggle('fa-list-ul', !busy);
    icon.classList.toggle('fa-circle-notch', busy);
    icon.classList.toggle('fa-spin', busy);
}

// Fetch the user-message index for the active session and repaint. A stale
// response for a session we have since left is dropped.
function refreshTimeline() {
    if (!_timelineEnsureDom()) return;
    const token = ++_timelineFetchToken;
    const target = sessionId;
    fetch(`/api/history/user_messages?session_id=${encodeURIComponent(target)}`)
        .then(r => r.json())
        .then(data => {
            if (token !== _timelineFetchToken || target !== sessionId) return;
            if (data.status === 'success' && Array.isArray(data.messages)) {
                _timelineItems = data.messages;
                _timelineRender();
            }
        })
        .catch(() => {});
}

// Clear the navigator when leaving a session so the previous conversation's
// questions don't linger while the new history loads.
function resetTimeline() {
    _timelineItems = [];
    _timelineActiveSeq = null;
    _timelineFetchToken++;
    _timelineJumpToken++;
    _timelineStopGlide();
    _timelineSetBusy(false);
    _timelineRender();
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => _timelineEnsureDom());
} else {
    _timelineEnsureDom();
}
