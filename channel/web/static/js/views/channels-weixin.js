/* WeChat QR login.
   Split out of console.js. These are classic scripts sharing one global
   scope; see channel/web/README.md before changing the load order. */

// =====================================================================
// WeChat QR Login
// =====================================================================
let _weixinQrPollTimer = null;
// Status polls are keyed by card (`iid`): the legacy per-type card is 'weixin',
// a multi-instance card is its instance id. Several cards may wait for a scan
// at once, so each keeps its own timer.
let _weixinStatusPollTimers = {};
// Instance card -> QR URL currently on screen. A live channel replaces its code
// every couple of minutes while it waits for a scan, so the card keeps asking
// for the current one instead of leaving an expired code up.
let _weixinShownQr = {};

function stopWeixinStatusPoll(iid) {
    if (iid === undefined) {
        Object.keys(_weixinStatusPollTimers).forEach(k => stopWeixinStatusPoll(k));
        return;
    }
    if (_weixinStatusPollTimers[iid]) {
        clearTimeout(_weixinStatusPollTimers[iid]);
        delete _weixinStatusPollTimers[iid];
    }
}

function isWeixinInstanceCard(iid) {
    return !!iid && iid !== 'weixin';
}

// Instance cards get their own QR panel. The legacy card and the "add channel"
// flow keep the single `weixin-qr-panel`, which the standalone poll
// (pollWeixinQrStatus) looks up by that fixed id — so those paths are untouched.
function weixinQrPanelId(iid) {
    return isWeixinInstanceCard(iid) ? `weixin-qr-panel-${iid}` : 'weixin-qr-panel';
}

// Locate this card's entry in an /api/channels payload: instances carry their
// own login_status; the legacy card lives in the per-type list.
function findWeixinEntry(data, iid) {
    if (isWeixinInstanceCard(iid)) {
        return (data.instances || []).find(i => i.instance_id === iid) || null;
    }
    return (data.channels || []).find(c => c.name === 'weixin') || null;
}

function startWeixinActiveStatusPoll(iid) {
    iid = iid || 'weixin';
    stopWeixinStatusPoll(iid);
    _weixinStatusPollTimers[iid] = setTimeout(() => {
        fetch('/api/channels').then(r => r.json()).then(data => {
            if (data.status !== 'success') return;
            const wx = findWeixinEntry(data, iid);
            if (!wx || (!isWeixinInstanceCard(iid) && !wx.active)) return;
            if (wx.login_status === 'logged_in') {
                delete _weixinShownQr[iid];
                channelsData = data.channels;
                channelInstancesView = data.instances || [];
                renderActiveChannels();
            } else {
                const local = isWeixinInstanceCard(iid)
                    ? channelInstancesView.find(i => i.instance_id === iid)
                    : channelsData.find(c => c.name === 'weixin');
                if (local && wx.login_status) local.login_status = wx.login_status;
                syncWeixinInstanceQr(iid, wx.login_status);
                startWeixinActiveStatusPoll(iid);
            }
        }).catch(() => { startWeixinActiveStatusPoll(iid); });
    }, 3000);
}

function syncWeixinInstanceQr(iid, loginStatus) {
    if (!isWeixinInstanceCard(iid) || !_weixinShownQr[iid]) return;
    const panel = document.getElementById(weixinQrPanelId(iid));
    if (!panel) { delete _weixinShownQr[iid]; return; }
    fetch(`/api/weixin/qrlogin?instance_id=${encodeURIComponent(iid)}`)
        .then(r => r.json())
        .then(data => {
            if (!_weixinShownQr[iid] || !document.getElementById(weixinQrPanelId(iid))) return;
            if (data.status !== 'success' || !data.qrcode_url) return;
            const status = loginStatus === 'scanned' ? 'scanned' : 'waiting';
            if (data.qrcode_url !== _weixinShownQr[iid].url || status !== _weixinShownQr[iid].status) {
                _weixinShownQr[iid] = { url: data.qrcode_url, status };
                renderWeixinQr(data.qr_image || data.qrcode_url, status, iid);
            }
        })
        .catch(() => {});
}

function showWeixinActiveQr(iid) {
    iid = iid || 'weixin';
    const container = document.getElementById(`weixin-active-qr-${iid}`);
    if (!container) return;
    container.innerHTML = `
        <div id="${weixinQrPanelId(iid)}" class="flex flex-col items-center py-2">
            <p class="text-sm text-slate-500 dark:text-slate-400 mb-4">${t('weixin_scan_loading')}</p>
        </div>`;
    stopWeixinStatusPoll(iid);
    startWeixinQrLogin(iid);
}

function stopWeixinQrPoll() {
    if (_weixinQrPollTimer) {
        clearTimeout(_weixinQrPollTimer);
        _weixinQrPollTimer = null;
    }
}

// How long to keep asking a live instance for its code before giving up: the
// channel may still be fetching it, or restarting after an expired attempt.
const WEIXIN_QR_PENDING_MAX_TRIES = 15;

function startWeixinQrLogin(iid, pendingTries) {
    stopWeixinQrPoll();
    pendingTries = pendingTries || 0;
    const url = isWeixinInstanceCard(iid)
        ? `/api/weixin/qrlogin?instance_id=${encodeURIComponent(iid)}`
        : '/api/weixin/qrlogin';
    fetch(url)
        .then(r => r.json())
        .then(data => {
            const panel = document.getElementById(weixinQrPanelId(iid));
            if (!panel) return;
            if (data.status === 'pending') {
                if (pendingTries >= WEIXIN_QR_PENDING_MAX_TRIES) {
                    panel.innerHTML = `<p class="text-sm text-red-500">${t('weixin_scan_fail')}</p>`;
                    return;
                }
                setTimeout(() => startWeixinQrLogin(iid, pendingTries + 1), 2000);
                return;
            }
            if (data.status !== 'success') {
                panel.innerHTML = `<p class="text-sm text-red-500">${t('weixin_scan_fail')}: ${data.message || ''}</p>`;
                return;
            }
            renderWeixinQr(data.qr_image || data.qrcode_url, 'waiting', iid);
            if (data.source === 'channel') {
                if (isWeixinInstanceCard(iid)) {
                    _weixinShownQr[iid] = { url: data.qrcode_url, status: 'waiting' };
                }
                startWeixinActiveStatusPoll(iid);
            } else {
                pollWeixinQrStatus();
            }
        })
        .catch(() => {
            const panel = document.getElementById(weixinQrPanelId(iid));
            if (panel) panel.innerHTML = `<p class="text-sm text-red-500">${t('weixin_scan_fail')}</p>`;
        });
}

function renderWeixinQr(qrcodeUrl, status, iid) {
    const panel = document.getElementById(weixinQrPanelId(iid));
    if (!panel) return;

    let statusText = t('weixin_scan_waiting');
    let statusColor = 'text-slate-500 dark:text-slate-400';
    if (status === 'scanned') {
        statusText = t('weixin_scan_scanned');
        statusColor = 'text-primary-500';
    } else if (status === 'expired') {
        statusText = t('weixin_scan_expired');
        statusColor = 'text-amber-500';
    } else if (status === 'confirmed') {
        statusText = t('weixin_scan_success');
        statusColor = 'text-primary-500';
    }

    panel.innerHTML = `
        <div class="flex flex-col items-center">
            <p class="text-sm font-medium text-slate-700 dark:text-slate-200 mb-1">${t('weixin_scan_title')}</p>
            <p class="text-xs text-slate-400 dark:text-slate-500 mb-4">${t('weixin_scan_desc')}</p>
            <div class="bg-white p-3 rounded-xl shadow-sm border border-slate-100 dark:border-slate-700 mb-3">
                <img src="${escapeHtml(qrcodeUrl)}" alt="QR Code" class="w-52 h-52" style="image-rendering: pixelated;"/>
            </div>
            <p class="text-xs ${statusColor} mb-1">${statusText}</p>
            <p class="text-xs text-slate-400 dark:text-slate-500">${t('weixin_qr_tip')}</p>
        </div>`;
}

function pollWeixinQrStatus() {
    _weixinQrPollTimer = setTimeout(() => {
        fetch('/api/weixin/qrlogin', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ action: 'poll' })
        })
        .then(r => r.json())
        .then(data => {
            const panel = document.getElementById('weixin-qr-panel');
            if (!panel) { stopWeixinQrPoll(); return; }

            if (data.status !== 'success') {
                pollWeixinQrStatus();
                return;
            }

            const qrStatus = data.qr_status;
            if (qrStatus === 'confirmed') {
                renderWeixinQr('', 'confirmed');
                panel.innerHTML = `
                    <div class="flex flex-col items-center py-4">
                        <div class="w-12 h-12 rounded-full bg-primary-50 dark:bg-primary-900/30 flex items-center justify-center mb-3">
                            <i class="fas fa-check text-primary-500 text-lg"></i>
                        </div>
                        <p class="text-sm font-medium text-primary-600 dark:text-primary-400">${t('weixin_scan_success')}</p>
                    </div>`;
                connectWeixinAfterQr();
            } else if (qrStatus === 'expired' && (data.qr_image || data.qrcode_url)) {
                renderWeixinQr(data.qr_image || data.qrcode_url, 'waiting');
                pollWeixinQrStatus();
            } else if (qrStatus === 'scaned') {
                const img = panel.querySelector('img');
                const currentSrc = img ? img.src : '';
                renderWeixinQr(currentSrc, 'scanned');
                pollWeixinQrStatus();
            } else {
                pollWeixinQrStatus();
            }
        })
        .catch(() => {
            pollWeixinQrStatus();
        });
    }, 2000);
}

function connectWeixinAfterQr() {
    fetch('/api/channels', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: 'connect', channel: 'weixin', config: {} })
    })
    .then(r => r.json())
    .then(data => {
        if (data.status === 'success') {
            // Multi-Agent: the new Weixin instance only lives in the server's
            // channel_instances yet, and its card is rendered from that list —
            // so reload the channels view to make it appear. Re-rendering from
            // the stale local state would drop the freshly scanned card until a
            // manual refresh. Legacy single-instance patches local state.
            if (isMultiInstanceType('weixin') || data.instance_id) {
                setTimeout(() => loadChannelsView(), 1500);
                return;
            }
            const ch = channelsData.find(c => c.name === 'weixin');
            if (ch) ch.active = true;
            setTimeout(() => renderActiveChannels(), 1500);
        }
    })
    .catch(() => {});
}

