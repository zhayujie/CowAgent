/* Context-usage popover on the clear-context button.
   Split out of console.js. These are classic scripts sharing one global
   scope; see channel/web/README.md before changing the load order. */

// =====================================================================
// Context usage popover (hover on the clear-context button)
// =====================================================================
// Body-level floating card that shows a pie of what is occupying the current
// session's context window, fetched from /api/sessions/{sid}/context_usage on
// hover. Reuses the portal approach of installCfgTipPortal so the composer's
// overflow can't clip it; unlike the text tooltips it renders innerHTML (an
// inline SVG donut).
let _ctxUsageEl = null;
let _ctxUsageInstalled = false;
const _CTX_SLICE_COLORS = {
    system: '#228547',
    tools: '#4ABE6E',
    history: '#f59e0b',
    free: '#64748b',
};
const _CTX_LEGEND = [
    { key: 'system', labelKey: 'ctx_system' },
    { key: 'tools', labelKey: 'ctx_tools' },
    { key: 'history', labelKey: 'ctx_history' },
    { key: 'free', labelKey: 'ctx_free' },
];
function _ctxFmtTokens(n) {
    if (n < 1000) return String(n);
    if (n < 10000) return (n / 1000).toFixed(1) + 'k';
    return Math.round(n / 1000) + 'k';
}
function _ctxDonutSvg(slices) {
    const size = 96, stroke = 12, r = (size - stroke) / 2, c = 2 * Math.PI * r;
    const total = slices.reduce((s, x) => s + Math.max(0, x.value), 0);
    const parts = [];
    let offset = 0;
    slices.forEach((s) => {
        const frac = total > 0 ? Math.max(0, s.value) / total : 0;
        if (frac > 0) {
            parts.push(
                '<circle cx="' + size / 2 + '" cy="' + size / 2 + '" r="' + r +
                '" fill="none" stroke="' + _CTX_SLICE_COLORS[s.key] +
                '" stroke-width="' + stroke +
                '" stroke-dasharray="' + (frac * c) + ' ' + c +
                '" stroke-dashoffset="' + (-offset * c) + '"></circle>'
            );
        }
        offset += frac;
    });
    return '<svg width="' + size + '" height="' + size +
        '" viewBox="0 0 ' + size + ' ' + size + '">' +
        '<g transform="rotate(-90 ' + size / 2 + ' ' + size / 2 + ')">' +
        parts.join('') + '</g></svg>';
}
function _ctxRenderCard(usage) {
    if (!usage || usage.status === 'error') {
        return '<div class="ctx-usage-empty">' + t('ctx_error') + '</div>';
    }
    if (!usage.available || !usage.breakdown) {
        return '<div class="ctx-usage-empty">' + t('ctx_empty') + '</div>';
    }
    const b = usage.breakdown;
    const limit = usage.limit || 0;
    const used = usage.used || 0;
    const percent = limit > 0 ? Math.min(100, Math.round((used / limit) * 100)) : 0;
    const slices = _CTX_LEGEND.map((l) => ({ key: l.key, value: b[l.key] || 0 }));
    const rows = _CTX_LEGEND.map((l) =>
        '<div class="ctx-usage-row">' +
        '<span class="ctx-usage-dot" style="background:' + _CTX_SLICE_COLORS[l.key] + '"></span>' +
        '<span class="ctx-usage-label">' + t(l.labelKey) + '</span>' +
        '<span class="ctx-usage-val">' + _ctxFmtTokens(b[l.key] || 0) + '</span>' +
        '</div>'
    ).join('');
    const usedLine = t('ctx_used_of')
        .replace('{used}', _ctxFmtTokens(used))
        .replace('{limit}', _ctxFmtTokens(limit));
    return (
        '<div class="ctx-usage-head">' +
        '<span class="ctx-usage-title">' + t('ctx_usage_title') + '</span>' +
        (usage.estimated ? '<span class="ctx-usage-est">' + t('ctx_estimated') + '</span>' : '') +
        '</div>' +
        '<div class="ctx-usage-donut-wrap">' + _ctxDonutSvg(slices) +
        '<span class="ctx-usage-pct">' + percent + '%</span></div>' +
        '<div class="ctx-usage-legend">' + rows + '</div>' +
        '<div class="ctx-usage-foot">' + usedLine + '</div>' +
        _ctxActionsBar()
    );
}

// Action row at the bottom of the usage card: clear / compact / adjust budget.
// Buttons carry data-ctx-action so one delegated handler on the card element
// wires them (the card's innerHTML is re-rendered on every refresh).
function _ctxActionsBar() {
    return (
        '<div class="ctx-usage-actions">' +
        '<button type="button" class="ctx-act-btn" data-ctx-action="compact" data-tooltip="' + t('ctx_act_compact_tip') + '">' +
        '<i class="fas fa-compress"></i><span>' + t('ctx_act_compact') + '</span></button>' +
        '<button type="button" class="ctx-act-btn" data-ctx-action="clear" data-tooltip="' + t('ctx_act_clear_tip') + '">' +
        '<i class="fas fa-trash-can"></i><span>' + t('ctx_act_clear') + '</span></button>' +
        '<button type="button" class="ctx-act-btn" data-ctx-action="adjust" data-tooltip="' + t('ctx_act_adjust_tip') + '">' +
        '<i class="fas fa-sliders"></i><span>' + t('ctx_act_adjust') + '</span></button>' +
        '</div>'
    );
}

// Small inline donut for the composer button, so the fill/percent is readable
// without opening the card. Mirrors _ctxDonutSvg's slice math at 16px with a
// thin stroke; grey ring when there's no context yet.
function _ctxMiniPieSvg(usage) {
    const size = 16, stroke = 4, r = (size - stroke) / 2, c = 2 * Math.PI * r;
    if (!usage || !usage.available || !usage.breakdown) {
        // Empty: a faint full ring.
        return '<svg width="' + size + '" height="' + size + '" viewBox="0 0 ' + size + ' ' + size + '">' +
            '<circle cx="' + size / 2 + '" cy="' + size / 2 + '" r="' + r +
            '" fill="none" stroke="currentColor" stroke-width="' + stroke + '" opacity="0.35"></circle></svg>';
    }
    const b = usage.breakdown;
    const slices = _CTX_LEGEND.map((l) => ({ key: l.key, value: b[l.key] || 0 }));
    const total = slices.reduce((s, x) => s + Math.max(0, x.value), 0);
    const parts = [
        '<circle cx="' + size / 2 + '" cy="' + size / 2 + '" r="' + r +
        '" fill="none" stroke="currentColor" stroke-width="' + stroke + '" opacity="0.18"></circle>'
    ];
    let offset = 0;
    slices.forEach((s) => {
        const frac = total > 0 ? Math.max(0, s.value) / total : 0;
        if (frac > 0 && s.key !== 'free') {
            parts.push(
                '<circle cx="' + size / 2 + '" cy="' + size / 2 + '" r="' + r +
                '" fill="none" stroke="' + _CTX_SLICE_COLORS[s.key] +
                '" stroke-width="' + stroke +
                '" stroke-dasharray="' + (frac * c) + ' ' + c +
                '" stroke-dashoffset="' + (-offset * c) + '"></circle>'
            );
        }
        offset += frac;
    });
    return '<svg width="' + size + '" height="' + size + '" viewBox="0 0 ' + size + ' ' + size + '">' +
        '<g transform="rotate(-90 ' + size / 2 + ' ' + size / 2 + ')">' + parts.join('') + '</g></svg>';
}

// Render the mini pie into the composer button. The pie is always shown — an
// empty session is just a 0% (faint) ring — so the indicator reads
// consistently instead of flipping between an icon and a chart.
function _ctxRenderMiniPie(usage) {
    const holder = document.getElementById('ctx-pie-mini');
    if (!holder) return;
    holder.innerHTML = _ctxMiniPieSvg(usage);
}
// Latest usage snapshot, shared between the mini pie and the card so actions
// can refresh both without a refetch when the server returns fresh usage.
let _ctxLastUsage = null;
let _ctxPinned = false;      // clicked-open: stays until dismissed
let _ctxCompacting = false;  // a compaction request is in flight (locks input)

function installContextUsagePopover() {
    if (_ctxUsageInstalled) return;
    _ctxUsageInstalled = true;

    const btn = document.getElementById('clear-context-btn');
    if (!btn) return;

    _ctxUsageEl = document.createElement('div');
    _ctxUsageEl.className = 'ctx-usage-pop';
    document.body.appendChild(_ctxUsageEl);

    let hoverTimer = null;
    let hideTimer = null;

    const position = () => {
        const rect = btn.getBoundingClientRect();
        const elRect = _ctxUsageEl.getBoundingClientRect();
        let left = rect.left + rect.width / 2 - elRect.width / 2;
        left = Math.max(8, Math.min(left, window.innerWidth - elRect.width - 8));
        _ctxUsageEl.style.left = left + 'px';
        _ctxUsageEl.style.top = (rect.top - elRect.height - 8) + 'px';
    };

    const hideCard = () => {
        if (_ctxPinned) return;
        _ctxUsageEl.classList.remove('show');
    };
    // Expose a forced hide (used after pin dismiss / actions).
    _ctxHideCard = () => {
        _ctxPinned = false;
        _ctxUsageEl.classList.remove('show');
    };

    // Render the card from a usage payload (or the loading/empty state) and
    // show it. Keeps _ctxLastUsage in sync so the mini pie matches.
    _ctxShowCard = (usage) => {
        _ctxLastUsage = usage;
        btn.removeAttribute('data-tooltip');
        // Empty / error states are just one line, so shrink the card (compact
        // modifier) instead of showing a wide box padded around a single line.
        const isEmpty = !usage || usage.status === 'error' || !usage.available || !usage.breakdown;
        _ctxUsageEl.classList.toggle('ctx-usage-pop--compact', isEmpty && !_ctxCompacting);
        _ctxUsageEl.innerHTML = _ctxCompacting
            ? _ctxRenderCard(usage) + _ctxLoadingOverlay()
            : _ctxRenderCard(usage);
        _ctxUsageEl.classList.add('show');
        position();
    };

    // Fetch fresh usage and (re)draw the mini pie + card if open.
    _ctxRefresh = (opts) => {
        opts = opts || {};
        return fetch('/api/sessions/' + encodeURIComponent(sessionId) + '/context_usage')
            .then((r) => r.json())
            .then((data) => {
                const ok = data && data.status !== 'error';
                _ctxLastUsage = ok ? data : null;
                _ctxRenderMiniPie(_ctxLastUsage);
                // Always open/refresh the card (an empty session just shows the
                // "no context yet" state) so the pie and card read consistently.
                if (opts.openCard) {
                    _ctxShowCard(ok ? data : null);
                } else if (_ctxUsageEl.classList.contains('show') && !_ctxCompacting) {
                    _ctxShowCard(ok ? data : null);
                }
                return _ctxLastUsage;
            })
            .catch(() => {
                if (opts.openCard) _ctxShowCard(null);
                return null;
            });
    };

    // The pie is always the affordance now; no plain button tooltip.
    btn.removeAttribute('data-tooltip');

    // Hover: preview after a short delay. Does not pin.
    btn.addEventListener('mouseenter', () => {
        clearTimeout(hideTimer);
        clearTimeout(hoverTimer);
        hoverTimer = setTimeout(() => { _ctxRefresh({ openCard: true }); }, 120);
    });
    btn.addEventListener('mouseleave', () => {
        clearTimeout(hoverTimer);
        // Delay so the pointer can travel into the card without it vanishing.
        hideTimer = setTimeout(hideCard, 180);
    });
    // Click pins the card open (stays until an outside click / Esc).
    btn.addEventListener('click', (e) => {
        e.stopPropagation();
        clearTimeout(hoverTimer);
        clearTimeout(hideTimer);
        // Toggle: a second click on an already-pinned card collapses it (but
        // never while a compaction is running — that would hide the spinner).
        if (_ctxPinned && _ctxUsageEl.classList.contains('show') && !_ctxCompacting) {
            _ctxHideCard();
            return;
        }
        _ctxPinned = true;
        _ctxRefresh({ openCard: true });
    });

    // The card itself is interactive: keep it open while hovered, and wire the
    // action buttons via delegation (innerHTML is rebuilt on every refresh).
    _ctxUsageEl.addEventListener('mouseenter', () => clearTimeout(hideTimer));
    _ctxUsageEl.addEventListener('mouseleave', () => {
        hideTimer = setTimeout(hideCard, 180);
    });
    _ctxUsageEl.addEventListener('click', (e) => {
        e.stopPropagation();
        const actBtn = e.target.closest('[data-ctx-action]');
        if (!actBtn) return;
        const action = actBtn.getAttribute('data-ctx-action');
        if (action === 'clear') _ctxDoClear();
        else if (action === 'compact') _ctxDoCompact();
        else if (action === 'adjust') _ctxDoAdjust();
    });

    // Dismiss a pinned card on outside click / Esc.
    document.addEventListener('click', (e) => {
        if (!_ctxPinned) return;
        if (_ctxUsageEl.contains(e.target) || btn.contains(e.target)) return;
        _ctxHideCard();
    });
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && _ctxPinned && !_ctxCompacting) _ctxHideCard();
    });

    window.addEventListener('scroll', () => { if (!_ctxPinned) _ctxUsageEl.classList.remove('show'); }, true);
    window.addEventListener('resize', () => { if (_ctxUsageEl.classList.contains('show')) position(); });

    // Prime the mini pie once on load so the button reflects state immediately.
    // Installed from boot.js's first applyI18n(), before login has settled.
    requestAuthGatedStart(() => _ctxRefresh({}));
}

// Module-scope handles set up inside installContextUsagePopover so the action
// helpers below can drive the card.
let _ctxShowCard = null;
let _ctxHideCard = null;
let _ctxRefresh = null;

function _ctxLoadingOverlay() {
    return '<div class="ctx-usage-loading"><span class="ctx-spinner"></span>' +
        '<span>' + t('ctx_compacting') + '</span></div>';
}

// --- Actions -----------------------------------------------------------

// True while a reply is streaming — clearing/compacting mid-turn would race
// the agent's own message list, so we block it and nudge the user to wait.
function _ctxTurnActive() {
    return typeof sendBtnMode !== 'undefined' && sendBtnMode === 'cancel' && !!activeRequestId;
}

function _ctxDoClear() {
    if (_ctxCompacting) return;
    if (_ctxTurnActive()) { _wsToast(t('ctx_busy_turn')); return; }
    clearContext();
    _ctxHideCard && _ctxHideCard();
    // clear_context drops the agent instance; reflect the empty state.
    _ctxLastUsage = null;
    _ctxRenderMiniPie(null);
}

function _ctxDoAdjust() {
    _ctxHideCard && _ctxHideCard();
    // Jump to the Agent config: scroll the whole Agent card into view (so its
    // heading is visible, not just the field), then highlight + focus the
    // budget input.
    if (typeof navigateTo === 'function') navigateTo('config');
    setTimeout(() => {
        const card = document.getElementById('config-agent-card');
        const el = document.getElementById('cfg-max-tokens');
        if (card) card.scrollIntoView({ behavior: 'smooth', block: 'start' });
        else if (el) el.scrollIntoView({ behavior: 'smooth', block: 'center' });
        if (el) {
            el.focus({ preventScroll: true });
            el.classList.add('cfg-field-highlight');
            setTimeout(() => el.classList.remove('cfg-field-highlight'), 2000);
        }
    }, 250);
}

// Synchronous compaction: lock the composer + show a spinner on the card, then
// refresh the chart from the fresh usage the server returns.
function _ctxDoCompact() {
    if (_ctxCompacting) return;
    if (_ctxTurnActive()) { _wsToast(t('ctx_busy_turn')); return; }
    // Nothing to compact on an empty session.
    if (!_ctxLastUsage || !_ctxLastUsage.available) return;
    _ctxCompacting = true;
    _ctxPinned = true;
    _ctxSetComposerLocked(true);
    // Re-render current card with the loading overlay.
    if (_ctxShowCard) _ctxShowCard(_ctxLastUsage);

    fetch('/api/sessions/' + encodeURIComponent(sessionId) + '/compact_context', { method: 'POST' })
        .then((r) => r.json())
        .then((data) => {
            _ctxCompacting = false;
            _ctxSetComposerLocked(false);
            if (!data || data.status === 'error') {
                _wsToast(t('ctx_compact_failed'));
                if (_ctxRefresh) _ctxRefresh({ openCard: true });
                return;
            }
            if (data.ok) {
                // Drop a divider so the summarize is visible in the thread.
                const divider = document.createElement('div');
                divider.className = 'context-divider';
                divider.innerHTML = '<span>' + t('ctx_compacted_divider')
                    .replace('{before}', data.before || 0)
                    .replace('{after}', data.after || 0) + '</span>';
                messagesDiv.appendChild(divider);
                scrollChatToBottom();
            } else {
                _wsToast(t('ctx_compact_noop'));
            }
            // Redraw from returned usage (or refetch).
            if (data.usage) {
                _ctxLastUsage = data.usage;
                _ctxRenderMiniPie(_ctxLastUsage);
                if (_ctxShowCard && _ctxPinned) _ctxShowCard(_ctxLastUsage);
            } else if (_ctxRefresh) {
                _ctxRefresh({ openCard: _ctxPinned });
            }
        })
        .catch(() => {
            _ctxCompacting = false;
            _ctxSetComposerLocked(false);
            _wsToast(t('ctx_compact_failed'));
        });
}

// Lock/unlock the composer during synchronous compaction. Disables the input
// and send button; a page refresh is a safe escape hatch if it ever hangs.
function _ctxSetComposerLocked(locked) {
    try {
        if (chatInput) {
            chatInput.disabled = locked;
            chatInput.classList.toggle('ctx-input-locked', locked);
            if (locked) {
                chatInput.setAttribute('data-prev-ph', chatInput.placeholder || '');
                chatInput.placeholder = t('ctx_compacting');
            } else {
                const prev = chatInput.getAttribute('data-prev-ph');
                if (prev !== null) chatInput.placeholder = prev;
            }
        }
        if (sendBtn) {
            if (locked) sendBtn.disabled = true;
            // On unlock, let the normal enable/disable rule (empty input, etc.)
            // decide rather than force-enabling.
            else if (typeof updateSendBtnState === 'function') updateSendBtnState();
            else sendBtn.disabled = false;
        }
    } catch (_) {}
}

