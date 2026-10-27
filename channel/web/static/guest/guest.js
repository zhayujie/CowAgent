/* Guest share page: the console's chat view, bound to one share link.
 *
 * Builds on core/i18n.js, core/theme.js, core/utils.js and core/markdown.js,
 * and draws bubbles, steps and the composer with the same markup as
 * chat/render.js and chat/send.js so both pages look and behave alike.
 *
 * Talks only to /share/<share>/api/*. The visitor token lives in localStorage
 * under this share and travels in the X-Guest-Token header; the console's
 * cookie is never sent. Streaming uses fetch rather than EventSource so the
 * token stays out of the URL. The token names the visitor; which of their
 * conversations a request is about travels as ?sid=.
 */

// --- globals core/utils.js expects (declared by chat/state.js in the console)
const messagesDiv = document.getElementById('chat-messages');
let _autoScrollEnabled = true;
const _SCROLL_THRESHOLD = 80;
let _programmaticScroll = false;
let _programmaticScrollTop = null;
let _lastScrollTop = 0;
let _userScrollIntent = null;
let _touchScrollStartY = null;

const GUEST_TEXT = {
    zh: {
        placeholder: '输入消息，Enter 发送，Shift + Enter 换行',
        new_chat: '新对话', attach: '上传文件', stop: '停止',
        gate_subtitle: '请输入访问密码', gate_btn: '进入', password: '访问密码',
        password_wrong: '密码错误，请重试', locked: '尝试次数过多，请稍后再试',
        unavailable: '页面暂不可用', disabled: '该分享链接已停用。', expired: '该分享链接已过期。',
        not_found: '链接无效或已失效。', unreachable: '暂时无法访问，请稍后再试。',
        session_invalid: '会话已失效，请刷新页面。', rate_limited: '发送太频繁，请稍后再试。',
        max_turns: '本次对话已达长度上限，请开始新对话。', daily_quota: '今日额度已用完，请明天再来。',
        busy: '当前访问较多，请稍后重试。', too_large: '文件过大', storage_full: '本次对话的存储空间已满',
        upload_failed: '上传失败', error: '出错了，请稍后再试。', download: '下载', copy: '复制',
        visitor_quota: '今天的提问次数已用完，请明天再来。', no_sessions: '还没有对话',
        reply_running: '请等待当前回复完成', voice_failed: '没有识别出内容，请重试',
        voice_unavailable: '语音输入暂不可用',
    },
    'zh-Hant': {
        placeholder: '輸入訊息，Enter 傳送，Shift + Enter 換行',
        new_chat: '新對話', attach: '上傳檔案', stop: '停止',
        gate_subtitle: '請輸入存取密碼', gate_btn: '進入', password: '存取密碼',
        password_wrong: '密碼錯誤，請重試', locked: '嘗試次數過多，請稍後再試',
        unavailable: '頁面暫不可用', disabled: '此分享連結已停用。', expired: '此分享連結已過期。',
        not_found: '連結無效或已失效。', unreachable: '暫時無法存取，請稍後再試。',
        session_invalid: '工作階段已失效，請重新整理頁面。', rate_limited: '傳送太頻繁，請稍後再試。',
        max_turns: '本次對話已達長度上限，請開始新對話。', daily_quota: '今日額度已用完，請明天再來。',
        busy: '目前存取較多，請稍後重試。', too_large: '檔案過大', storage_full: '本次對話的儲存空間已滿',
        upload_failed: '上傳失敗', error: '出錯了，請稍後再試。', download: '下載', copy: '複製',
        visitor_quota: '今天的提問次數已用完，請明天再來。', no_sessions: '還沒有對話',
        reply_running: '請等待目前回覆完成', voice_failed: '沒有辨識出內容，請重試',
        voice_unavailable: '語音輸入暫不可用',
    },
    en: {
        placeholder: 'Message. Enter to send, Shift + Enter for a new line',
        new_chat: 'New chat', attach: 'Upload files', stop: 'Stop',
        gate_subtitle: 'Enter the access password', gate_btn: 'Continue', password: 'Password',
        password_wrong: 'Wrong password, please try again', locked: 'Too many attempts, please try again later',
        unavailable: 'Page unavailable', disabled: 'This link has been turned off.', expired: 'This link has expired.',
        not_found: 'This link is invalid or no longer works.', unreachable: 'This page cannot be reached right now. Please try again later.',
        session_invalid: 'Your session has expired. Please reload the page.', rate_limited: 'You are sending too fast. Please wait a moment.',
        max_turns: 'This conversation has reached its length limit. Start a new one.', daily_quota: 'Today\'s usage limit has been reached. Please come back tomorrow.',
        busy: 'The assistant is busy right now. Please retry shortly.', too_large: 'File is too large', storage_full: 'This conversation\'s storage is full',
        upload_failed: 'Upload failed', error: 'Something went wrong. Please try again.', download: 'Download', copy: 'Copy',
        visitor_quota: 'You have used up today\'s questions. Please come back tomorrow.', no_sessions: 'No chats yet',
        reply_running: 'Wait for the current reply to finish', voice_failed: 'Nothing was recognised. Please try again',
        voice_unavailable: 'Voice input is unavailable',
    },
};

function gt(key) {
    const table = GUEST_TEXT[currentLang] || GUEST_TEXT.en;
    return table[key] || GUEST_TEXT.en[key] || key;
}

const guestShare = location.pathname.split('/')[2] || '';
const guestBase = '/share/' + guestShare + '/api';
const guestTokenKey = 'cow_guest_' + guestShare;
const guestSidKey = guestTokenKey + '_sid';
let guestToken = localStorage.getItem(guestTokenKey) || '';
let guestSessionId = localStorage.getItem(guestSidKey) || '';
let guestSessions = [];
// Bumped whenever the visible conversation changes, so a reply still
// streaming for the previous one stops drawing into this one.
let guestViewGen = 0;
let sessionPanelOpen = false;
let guestInfo = null;
// Virtual path (/work/a.png) -> signed URL, for files a reply mentions.
const guestLinks = {};
let guestRunning = null;

const chatInput = document.getElementById('chat-input');
const sendBtn = document.getElementById('send-btn');
const newChatBtn = document.getElementById('new-chat-btn');
const attachBtn = document.getElementById('attach-btn');
const fileInput = document.getElementById('file-input');
const composerCard = document.getElementById('composer-card');
const attachmentPreview = document.getElementById('attachment-preview');
const welcomeScreen = document.getElementById('welcome-screen');

let pendingAttachments = [];
let uploadingCount = 0;

// --- network -------------------------------------------------------------

function guestSaveToken(value) {
    guestToken = value || '';
    if (guestToken) localStorage.setItem(guestTokenKey, guestToken);
    else localStorage.removeItem(guestTokenKey);
}

function guestSid(path) {
    return path + (path.indexOf('?') >= 0 ? '&' : '?') + 'sid=' + encodeURIComponent(guestSessionId);
}

function guestVisitorId() {
    return (guestToken.split('.')[2]) || '';
}

function guestApi(path, options) {
    options = options || {};
    const headers = {};
    if (guestToken) headers['X-Guest-Token'] = guestToken;
    let body = options.body;
    if (options.json !== undefined) {
        headers['Content-Type'] = 'application/json';
        body = JSON.stringify(options.json);
    }
    return fetch(guestBase + path, {
        method: options.method || 'GET', headers, body, credentials: 'omit',
    }).then(res => res.json().catch(() => ({})).then(data => {
        if (!res.ok || data.status === 'error') {
            const err = new Error(data.message || ('HTTP ' + res.status));
            err.status = res.status;
            err.reason = data.reason || '';
            throw err;
        }
        return data;
    }));
}

function guestErrorText(err) {
    if (err && err.reason && GUEST_TEXT.en[err.reason]) return gt(err.reason);
    return gt('error');
}

// --- links ---------------------------------------------------------------

function guestWebUrl(url) {
    if (!url) return url;
    let key = url;
    try { key = decodeURI(url); } catch (_) {}
    return guestLinks[key] || guestLinks[url] || url;
}
// markdown.js routes every image source through this.
window._toWebUrl = guestWebUrl;

const GUEST_VPATH_HREF_RE = /href="(\/(?:work|knowledge|data|skills)\/[^"]*)"/g;

function guestMarkdown(text) {
    const html = renderMarkdown(text || '');
    return html.replace(GUEST_VPATH_HREF_RE, (match, href) => {
        const url = guestWebUrl(href.replace(/&amp;/g, '&'));
        return url === href ? match : `href="${url.replace(/&/g, '&amp;').replace(/"/g, '&quot;')}"`;
    });
}

function guestAddLinks(links) {
    if (links && typeof links === 'object') Object.assign(guestLinks, links);
}

// --- file cards (workspace.js renderFileCard, download only) ------------

const GUEST_KIND_ICONS = {
    html: 'fa-file-code', markdown: 'fa-file-lines', image: 'fa-file-image', video: 'fa-file-video',
    audio: 'fa-file-audio', pdf: 'fa-file-pdf', csv: 'fa-file-csv', code: 'fa-file-code',
    office: 'fa-file-word', text: 'fa-file-lines', file: 'fa-file',
};
const GUEST_KIND_BY_EXT = {
    html: ['html', 'htm'], markdown: ['md', 'markdown'],
    image: ['jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp', 'svg', 'ico'],
    video: ['mp4', 'webm', 'mov', 'avi', 'mkv', 'm4v'], audio: ['mp3', 'wav', 'ogg', 'm4a', 'flac', 'aac'],
    pdf: ['pdf'], csv: ['csv', 'tsv'],
    code: ['py', 'js', 'ts', 'tsx', 'jsx', 'java', 'c', 'cpp', 'h', 'go', 'rs', 'rb', 'php', 'sh', 'sql',
           'css', 'scss', 'json', 'yaml', 'yml', 'xml', 'toml', 'ini'],
    text: ['txt', 'log'], office: ['doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx'],
};

function guestKindOf(name) {
    const ext = (name || '').split('.').pop().toLowerCase();
    for (const kind in GUEST_KIND_BY_EXT) {
        if (GUEST_KIND_BY_EXT[kind].includes(ext)) return kind;
    }
    return 'file';
}

function guestFormatSize(bytes) {
    if (!bytes) return '';
    const units = ['B', 'KB', 'MB', 'GB'];
    let n = bytes;
    for (const u of units) {
        if (n < 1024) return `${u === 'B' ? Math.round(n) : n.toFixed(1)}${u}`;
        n /= 1024;
    }
    return `${n.toFixed(1)}TB`;
}

function guestFileHtml(file) {
    const name = file.file_name || (file.path || '').split('/').pop() || 'file';
    const url = file.url || '';
    if (file.file_type === 'image' || guestKindOf(name) === 'image') {
        return `<div class="agent-step">${_buildImageHtml(url)}</div>`;
    }
    const kind = guestKindOf(name);
    const sub = [file.path === '/' + name ? '' : (file.path || ''), guestFormatSize(file.size)]
        .filter(Boolean).join(' · ');
    const safeUrl = escapeHtml(url);
    return `<div class="file-card-list">
        <div class="file-card" data-download="${safeUrl}" data-name="${escapeHtml(name)}">
            <i class="file-card-icon fas ${GUEST_KIND_ICONS[kind] || GUEST_KIND_ICONS.file} ws-icon-${kind}"></i>
            <div class="file-card-info">
                <div class="file-card-name">${escapeHtml(name)}</div>
                ${sub ? `<div class="file-card-sub">${escapeHtml(sub)}</div>` : ''}
            </div>
            <div class="file-card-actions">
                <a class="file-card-btn" href="${safeUrl}" download="${escapeHtml(name)}" data-tip-float
                   data-tooltip="${escapeHtml(gt('download'))}"><i class="fas fa-download"></i></a>
            </div>
        </div>
    </div>`;
}

// --- bubbles (chat/render.js) --------------------------------------------

const guestBrand = window.__GUEST_BRAND__ || {};
const GUEST_AVATAR = `<span class="bot-face"><img class="agent-avatar agent-avatar-32 guest-logo object-cover" src="${escapeHtml(guestBrand.logo || '/assets/logo.jpg')}" alt=""></span>`;

function guestStatusHtml(kind) {
    const icon = { cancelled: 'fa-circle-stop', interrupted: 'fa-circle-exclamation' }[kind];
    const label = t({ cancelled: 'reply_cancelled', interrupted: 'reply_interrupted' }[kind]);
    return `<div class="agent-step agent-status-step"><i class="fas ${icon}"></i><span>${escapeHtml(label)}</span></div>`;
}

function createUserMessageEl(content, timestamp, attachments) {
    const el = document.createElement('div');
    el.className = 'flex justify-end px-4 sm:px-6 py-3 user-message-group';
    let attachHtml = '';
    if (attachments && attachments.length) {
        const items = attachments.map(a => {
            if (a.file_type === 'image' && (a.preview_url || a.url)) {
                const src = escapeHtml(a.preview_url || a.url);
                return `<img src="${src}" alt="${escapeHtml(a.file_name || '')}" class="user-msg-image" onclick="_openImageLightbox(this.src)">`;
            }
            return `<div class="user-msg-file"><i class="fas fa-file-alt"></i> ${escapeHtml(a.file_name || '')}</div>`;
        }).join('');
        attachHtml = `<div class="user-msg-attachments">${items}</div>`;
    }
    const textHtml = content ? renderMarkdown(content) : '';
    el.innerHTML = `
        <div class="max-w-[75%] sm:max-w-[60%]">
            <div class="bg-primary-400 text-white rounded-2xl px-4 py-2.5 text-sm leading-relaxed msg-content user-bubble">
                ${attachHtml}${textHtml}
            </div>
            <div class="flex items-center justify-end gap-2 mt-1.5">
                <span class="text-xs text-slate-400 dark:text-slate-500">${formatTime(timestamp)}</span>
            </div>
        </div>`;
    return el;
}

function toolStepHtml(step) {
    const isErr = step.is_error === true;
    const icon = isErr ? 'fas fa-times text-red-400 flex-shrink-0 tool-icon' : 'fas fa-check text-primary-400 flex-shrink-0 tool-icon';
    const time = step.execution_time ? ` <span class="tool-time">${step.execution_time}s</span>` : '';
    const output = step.result
        ? `<div class="tool-detail-section tool-output-section">
               <div class="tool-detail-label">${isErr ? 'Error' : 'Output'}</div>
               <pre class="tool-detail-content${isErr ? ' tool-error-text' : ''}">${escapeHtml(String(step.result))}</pre>
           </div>`
        : '';
    return `
<div class="agent-step agent-tool-step${isErr ? ' tool-failed' : ''}">
    <div class="tool-header">
        <i class="${icon}"></i>
        <span class="tool-name">${escapeHtml(step.name || '')}${time}</span>
        <i class="fas fa-chevron-right tool-chevron"></i>
    </div>
    <div class="tool-detail">
        <div class="tool-detail-section">
            <div class="tool-detail-label">Input</div>
            <pre class="tool-detail-content">${formatToolArgs(step.arguments || {})}</pre>
        </div>
        ${output}
    </div>
</div>`;
}

function contentStepHtml(text) {
    return `<div class="agent-step agent-content-step"><div class="agent-content-body" data-raw-md="${escapeHtml(text)}">${guestMarkdown(text)}</div></div>`;
}

function botShellHtml(timestamp, stepsHtml, answerHtml, mediaHtml, showCopy) {
    return `
        ${GUEST_AVATAR}
        <div class="min-w-0 flex-1 max-w-[85%]">
            <div class="bg-white dark:bg-[#1A1A1A] border border-slate-200 dark:border-white/10 rounded-2xl px-4 py-3 text-sm leading-relaxed msg-content text-slate-700 dark:text-slate-200">
                <div class="agent-steps">${stepsHtml || ''}</div>
                <div class="answer-content">${answerHtml || ''}</div>
                <div class="media-content">${mediaHtml || ''}</div>
            </div>
            <div class="bot-message-meta flex items-center gap-2 mt-1.5 flex-wrap">
                <span class="text-xs text-slate-400 dark:text-slate-500">${formatTime(timestamp)}</span>
                <button class="copy-msg-btn text-xs text-slate-300 dark:text-slate-600 hover:text-slate-500 dark:hover:text-slate-400 transition-colors cursor-pointer" data-tip-float data-tooltip="${escapeHtml(gt('copy'))}"${showCopy ? '' : ' style="display:none"'}>
                    <i class="fas fa-copy"></i>
                </button>
            </div>
        </div>`;
}

function createBotMessageEl(msg, timestamp) {
    const el = document.createElement('div');
    el.className = 'flex gap-3 px-4 sm:px-6 py-3 bot-message-group';
    const steps = msg.steps || [];
    const stopped = msg.status === 'cancelled';
    let answer = msg.content || '';
    // The last text becomes the answer, as in the console; a stopped reply
    // keeps every text as a step.
    let lastContentIdx = -1;
    if (!answer && !stopped) {
        for (let i = steps.length - 1; i >= 0; i--) {
            if (steps[i].type === 'content') { lastContentIdx = i; break; }
        }
        if (lastContentIdx >= 0) answer = steps[lastContentIdx].content || '';
    }
    let stepsHtml = '';
    steps.forEach((step, i) => {
        if (step.type === 'content' && i !== lastContentIdx) stepsHtml += contentStepHtml(step.content || '');
        else if (step.type === 'tool') stepsHtml += toolStepHtml(step);
    });
    if (stopped) {
        if (answer) stepsHtml += contentStepHtml(answer);
        answer = '';
        stepsHtml += guestStatusHtml('cancelled');
    } else if (msg.status === 'failed' && !answer) {
        stepsHtml += guestStatusHtml('interrupted');
    }
    const mediaHtml = (msg.files || []).map(guestFileHtml).join('');
    el.innerHTML = botShellHtml(timestamp, stepsHtml, guestMarkdown(answer), mediaHtml, !!answer);
    el.querySelector('.answer-content').dataset.rawMd = answer;
    applyHighlighting(el);
    return el;
}

function addPlainBotMessage(text) {
    const el = createBotMessageEl({ content: text }, new Date());
    messagesDiv.appendChild(el);
    scrollChatToBottom();
    return el;
}

function addLoadingIndicator() {
    const el = document.createElement('div');
    el.className = 'flex gap-3 px-4 sm:px-6 py-3 loading-indicator';
    el.innerHTML = `
        ${GUEST_AVATAR}
        <div class="bg-white dark:bg-[#1A1A1A] border border-slate-200 dark:border-white/10 rounded-2xl px-4 py-3">
            <div class="flex items-center gap-1.5">
                <span class="w-2 h-2 rounded-full bg-primary-400 animate-pulse-dot" style="animation-delay: 0s"></span>
                <span class="w-2 h-2 rounded-full bg-primary-400 animate-pulse-dot" style="animation-delay: 0.2s"></span>
                <span class="w-2 h-2 rounded-full bg-primary-400 animate-pulse-dot" style="animation-delay: 0.4s"></span>
            </div>
        </div>`;
    messagesDiv.appendChild(el);
    scrollChatToBottom();
    return el;
}

function showWelcome(show) {
    welcomeScreen.classList.toggle('hidden', !show);
}

function clearMessages() {
    Array.from(messagesDiv.children).forEach(node => { if (node !== welcomeScreen) node.remove(); });
}

// --- streaming (chat/send.js startSSE) -----------------------------------

function startStream(requestId, loadingEl, timestamp) {
    let botEl = null;
    let stepsEl = null;
    let contentEl = null;
    let mediaEl = null;
    let accumulatedText = '';
    const toolElements = new Map();
    let cancelled = false;
    let finished = false;
    let lastSeq = 0;
    let retries = 0;
    let raf = null;
    const gen = guestViewGen;
    const sid = guestSessionId;
    const stale = () => gen !== guestViewGen;

    setSendBtnCancelMode(requestId);

    function ensureBotEl() {
        if (botEl) return;
        if (loadingEl) { loadingEl.remove(); loadingEl = null; }
        botEl = document.createElement('div');
        botEl.className = 'flex gap-3 px-4 sm:px-6 py-3 bot-message-group';
        botEl.innerHTML = botShellHtml(timestamp, '', '', '', false);
        messagesDiv.appendChild(botEl);
        stepsEl = botEl.querySelector('.agent-steps');
        contentEl = botEl.querySelector('.answer-content');
        contentEl.classList.add('sse-streaming');
        mediaEl = botEl.querySelector('.media-content');
        refreshChatScrollControls();
    }

    function flushRender() {
        if (raf === null) return;
        cancelAnimationFrame(raf);
        raf = null;
        if (contentEl) contentEl.innerHTML = guestMarkdown(accumulatedText);
    }

    function scheduleRender() {
        if (raf !== null) return;
        raf = requestAnimationFrame(() => {
            raf = null;
            if (contentEl) contentEl.innerHTML = guestMarkdown(accumulatedText);
            scrollChatToBottom();
        });
    }

    function settlePendingTools() {
        toolElements.forEach(el => {
            el.classList.remove('tool-streaming');
            const icon = el.querySelector('.tool-icon');
            if (icon) icon.className = 'fas fa-minus text-slate-400 flex-shrink-0 tool-icon';
        });
        toolElements.clear();
    }

    function finish() {
        if (finished) return;
        finished = true;
        settlePendingTools();
        if (loadingEl) { loadingEl.remove(); loadingEl = null; }
        if (contentEl) contentEl.classList.remove('sse-streaming');
        resetSendBtnSendMode();
    }

    function handle(item) {
        if (stale()) { finished = true; return; }
        if (item.seq) lastSeq = item.seq;
        if (item.type !== 'delta') flushRender();

        if (item.type === 'delta') {
            ensureBotEl();
            accumulatedText += item.content || '';
            scheduleRender();

        } else if (item.type === 'message_end') {
            if (item.has_tool_calls && accumulatedText.trim()) {
                ensureBotEl();
                stepsEl.insertAdjacentHTML('beforeend', contentStepHtml(accumulatedText.trim()));
                accumulatedText = '';
                contentEl.innerHTML = '';
                scrollChatToBottom();
            }

        } else if (item.type === 'tool_start') {
            ensureBotEl();
            accumulatedText = '';
            contentEl.innerHTML = '';
            const toolEl = document.createElement('div');
            toolEl.className = 'agent-step agent-tool-step tool-streaming';
            toolEl.innerHTML = `
                <div class="tool-header">
                    <i class="fas fa-cog fa-spin text-primary-400 flex-shrink-0 tool-icon"></i>
                    <span class="tool-name">${escapeHtml(item.tool || '')}</span>
                    <i class="fas fa-chevron-right tool-chevron"></i>
                </div>
                <div class="tool-detail">
                    <div class="tool-detail-section">
                        <div class="tool-detail-label">Input</div>
                        <pre class="tool-detail-content">${formatToolArgs(item.arguments || {})}</pre>
                    </div>
                    <div class="tool-detail-section tool-output-section">
                        <div class="tool-detail-label tool-output-label">Output</div>
                        <pre class="tool-detail-content tool-live-output"></pre>
                    </div>
                </div>`;
            stepsEl.appendChild(toolEl);
            toolElements.set(item.tool_call_id, toolEl);
            scrollChatToBottom();

        } else if (item.type === 'tool_end') {
            const toolEl = toolElements.get(item.tool_call_id);
            if (!toolEl) return;
            const isError = item.status !== 'success';
            toolEl.querySelector('.tool-icon').className = isError
                ? 'fas fa-times text-red-400 flex-shrink-0 tool-icon'
                : 'fas fa-check text-primary-400 flex-shrink-0 tool-icon';
            if (item.execution_time !== undefined) {
                toolEl.querySelector('.tool-name').insertAdjacentHTML('beforeend', ` <span class="tool-time">${item.execution_time}s</span>`);
            }
            toolEl.querySelector('.tool-output-label').textContent = isError ? 'Error' : 'Output';
            const out = toolEl.querySelector('.tool-live-output');
            out.textContent = item.result ? String(item.result) : '';
            out.classList.toggle('tool-error-text', isError);
            if (!item.result) toolEl.querySelector('.tool-output-section').remove();
            toolEl.classList.remove('tool-streaming', 'expanded');
            if (isError) toolEl.classList.add('tool-failed');
            toolElements.delete(item.tool_call_id);

        } else if (item.type === 'file') {
            ensureBotEl();
            mediaEl.insertAdjacentHTML('beforeend', guestFileHtml(item));
            scrollChatToBottom();

        } else if (item.type === 'cancelled') {
            cancelled = true;
            ensureBotEl();
            if (!stepsEl.querySelector('.agent-status-step')) {
                stepsEl.insertAdjacentHTML('beforeend', guestStatusHtml('cancelled'));
            }

        } else if (item.type === 'done') {
            guestAddLinks(item.links);
            settlePendingTools();
            const finalText = item.content || accumulatedText;
            if (!botEl && !finalText) return;
            ensureBotEl();
            // Mentions of files resolve once the reply names its links.
            stepsEl.querySelectorAll('.agent-content-body[data-raw-md]').forEach(body => {
                body.innerHTML = guestMarkdown(body.dataset.rawMd);
            });
            // Steps that finished after the stop belong above its status line.
            const status = stepsEl.querySelector('.agent-status-step');
            if (status) stepsEl.appendChild(status);
            contentEl.innerHTML = guestMarkdown(finalText);
            contentEl.dataset.rawMd = finalText;
            const copyBtn = botEl.querySelector('.copy-msg-btn');
            if (copyBtn && finalText) copyBtn.style.display = '';
            contentEl.classList.remove('sse-streaming');
            applyHighlighting(botEl);
            scrollChatToBottom();

        } else if (item.type === 'error') {
            if (!cancelled) {
                if (botEl) {
                    stepsEl.insertAdjacentHTML('beforeend', guestStatusHtml('interrupted'));
                } else {
                    if (loadingEl) { loadingEl.remove(); loadingEl = null; }
                    addPlainBotMessage(gt('error'));
                }
            }

        } else if (item.type === 'stream_end') {
            finish();
        }
    }

    function connect() {
        if (stale()) return;
        fetch(`${guestBase}/stream?request_id=${encodeURIComponent(requestId)}&after=${lastSeq}&sid=${encodeURIComponent(sid)}`, {
            headers: { 'X-Guest-Token': guestToken }, credentials: 'omit',
        }).then(res => {
            if (res.status === 404 || res.status === 401) {
                const err = new Error('stream');
                err.fatal = true;
                throw err;
            }
            if (!res.ok || !res.body) throw new Error('stream ' + res.status);
            const reader = res.body.getReader();
            const decoder = new TextDecoder();
            let buffer = '';
            const pump = () => reader.read().then(chunk => {
                if (chunk.done) return;
                if (stale()) { reader.cancel().catch(() => {}); return; }
                retries = 0;
                buffer += decoder.decode(chunk.value, { stream: true });
                const parts = buffer.split('\n\n');
                buffer = parts.pop();
                parts.forEach(part => part.split('\n').forEach(line => {
                    if (line.indexOf('data: ') !== 0) return;
                    let item;
                    try { item = JSON.parse(line.slice(6)); } catch (_) { return; }
                    if (item.seq && item.seq <= lastSeq) return;
                    handle(item);
                }));
                if (!finished) return pump();
            });
            return pump();
        }).then(() => {
            if (!finished) retry();
        }).catch(err => {
            if (err && err.fatal) {
                if (!botEl && loadingEl) addPlainBotMessage(gt('session_invalid'));
                finish();
                return;
            }
            retry();
        });
    }

    function retry() {
        if (finished || stale()) return;
        if (retries >= 10) {
            if (!botEl) addPlainBotMessage(gt('error'));
            finish();
            return;
        }
        retries++;
        setTimeout(connect, Math.min(1000 * retries, 5000));
    }

    connect();
}

// --- composer (chat/state.js) ---------------------------------------------

const COMPOSER_MIN_H = 52;
const COMPOSER_MAX_H = 220;

function autoResizeComposer() {
    chatInput.style.height = COMPOSER_MIN_H + 'px';
    const scrollH = chatInput.scrollHeight;
    chatInput.style.height = Math.max(COMPOSER_MIN_H, Math.min(scrollH, COMPOSER_MAX_H)) + 'px';
    chatInput.style.overflowY = scrollH > COMPOSER_MAX_H ? 'auto' : 'hidden';
}

function resetComposerHeight() {
    chatInput.style.height = COMPOSER_MIN_H + 'px';
    chatInput.style.overflowY = 'hidden';
}

function setSendBtnCancelMode(requestId) {
    guestRunning = requestId;
    sendBtn.disabled = false;
    sendBtn.classList.add('send-btn-cancel');
    sendBtn.dataset.tooltip = gt('stop');
    sendBtn.innerHTML = '<i class="fas fa-stop text-sm"></i>';
}

function resetSendBtnSendMode() {
    guestRunning = null;
    sendBtn.classList.remove('send-btn-cancel');
    delete sendBtn.dataset.tooltip;
    sendBtn.innerHTML = '<i class="fas fa-paper-plane text-sm"></i>';
    updateSendBtnState();
}

function updateSendBtnState() {
    if (guestRunning) return;
    sendBtn.disabled = uploadingCount > 0 || (!chatInput.value.trim() && pendingAttachments.length === 0);
}

function renderAttachmentPreview() {
    if (!pendingAttachments.length) {
        attachmentPreview.classList.add('hidden');
        attachmentPreview.innerHTML = '';
        updateSendBtnState();
        return;
    }
    attachmentPreview.classList.remove('hidden');
    attachmentPreview.innerHTML = pendingAttachments.map((att, idx) => {
        if (att._uploading) {
            return `<div class="att-chip att-uploading" data-idx="${idx}">
                <i class="fas fa-spinner fa-spin"></i>
                <span class="att-name">${escapeHtml(att.file_name)}</span>
            </div>`;
        }
        if (att.file_type === 'image') {
            return `<div class="att-thumb" data-idx="${idx}">
                <img src="${escapeHtml(att.preview_url)}" alt="${escapeHtml(att.file_name)}">
                <button class="att-remove" data-remove="${idx}">&times;</button>
            </div>`;
        }
        return `<div class="att-chip" data-idx="${idx}">
            <i class="fas fa-file-alt"></i>
            <span class="att-name">${escapeHtml(att.file_name)}</span>
            <button class="att-remove" data-remove="${idx}">&times;</button>
        </div>`;
    }).join('');
    updateSendBtnState();
}

let _toastTimer = null;
function guestToast(text) {
    let el = document.getElementById('guest-toast');
    if (!el) {
        el = document.createElement('div');
        el.id = 'guest-toast';
        el.className = 'art-toast';
        document.getElementById('chat-main').appendChild(el);
    }
    el.textContent = text;
    requestAnimationFrame(() => el.classList.add('show'));
    clearTimeout(_toastTimer);
    _toastTimer = setTimeout(() => el.classList.remove('show'), 2600);
}

function uploadFile(file) {
    const maxMb = (guestInfo && guestInfo.max_upload_mb) || 20;
    if (file.size > maxMb * 1024 * 1024) {
        guestToast(`${gt('too_large')}: ${file.name}`);
        return;
    }
    const item = { file_name: file.name, _uploading: true };
    pendingAttachments.push(item);
    uploadingCount++;
    renderAttachmentPreview();
    const form = new FormData();
    form.append('file', file);
    guestApi(guestSid('/upload'), { method: 'POST', body: form }).then(data => {
        Object.assign(item, {
            _uploading: false, path: data.path, file_name: data.name,
            file_type: data.file_type, preview_url: data.url,
        });
    }).catch(err => {
        pendingAttachments = pendingAttachments.filter(a => a !== item);
        guestToast(`${err.reason && GUEST_TEXT.en[err.reason] ? gt(err.reason) : gt('upload_failed')}: ${file.name}`);
    }).finally(() => {
        uploadingCount--;
        renderAttachmentPreview();
    });
}

function sendMessage(textOverride) {
    if (guestRunning || uploadingCount > 0) return;
    const text = (textOverride !== undefined ? textOverride : chatInput.value).trim();
    const attachments = pendingAttachments.filter(a => !a._uploading && a.path);
    if (!text && !attachments.length) return;

    showWelcome(false);
    messagesDiv.appendChild(createUserMessageEl(text, new Date(), attachments));
    _autoScrollEnabled = true;
    scrollChatToBottom(true);
    if (textOverride === undefined) {
        chatInput.value = '';
        resetComposerHeight();
    }
    pendingAttachments = [];
    renderAttachmentPreview();

    const loadingEl = addLoadingIndicator();
    setSendBtnCancelMode('pending');
    const gen = guestViewGen;
    guestApi(guestSid('/message'), { method: 'POST', json: { text, attachments: attachments.map(a => a.path) } })
        .then(data => {
            if (gen !== guestViewGen) return;
            rememberSession(text || (attachments[0] && attachments[0].file_name) || '');
            startStream(data.request_id, loadingEl, new Date());
        })
        .catch(err => {
            loadingEl.remove();
            addPlainBotMessage(guestErrorText(err));
            resetSendBtnSendMode();
        });
}

function requestCancel() {
    if (!guestRunning || guestRunning === 'pending') return;
    guestApi(guestSid('/cancel'), { method: 'POST', json: {} }).catch(() => {});
    sendBtn.disabled = true;
}

// --- session -------------------------------------------------------------

function showGate(errorKey) {
    const gate = document.getElementById('guest-gate');
    gate.classList.remove('hidden');
    const errEl = document.getElementById('guest-gate-error');
    errEl.textContent = errorKey ? gt(errorKey) : '';
    errEl.classList.toggle('hidden', !errorKey);
    document.getElementById('guest-password').focus();
}

function showUnavailable(reason) {
    const textKey = { disabled: 'disabled', expired: 'expired', not_found: 'not_found' }[reason] || 'unreachable';
    document.getElementById('guest-unavailable-title').textContent = gt('unavailable');
    document.getElementById('guest-unavailable-text').textContent = gt(textKey);
    document.getElementById('guest-gate').classList.add('hidden');
    document.getElementById('guest-unavailable').classList.remove('hidden');
}

function handleSessionError(err) {
    if (err.reason === 'password_required') { guestSaveToken(''); showGate(''); return; }
    if (err.reason === 'password_wrong' || err.reason === 'locked') { showGate(err.reason); return; }
    if (err.status === 404) { showUnavailable('not_found'); return; }
    if (err.status === 403) { showUnavailable(err.reason); return; }
    showUnavailable('');
}

function openSession(body) {
    return guestApi('/session', { method: 'POST', json: body }).then(data => {
        guestSaveToken(data.token);
        return data;
    });
}

function contextDividerEl() {
    const divider = document.createElement('div');
    divider.className = 'context-divider';
    divider.innerHTML = `<span>${escapeHtml(t('context_cleared'))}</span>`;
    return divider;
}

function loadHistory() {
    const gen = guestViewGen;
    return guestApi(guestSid('/history')).then(data => {
        if (gen !== guestViewGen) return;
        guestAddLinks(data.links);
        clearMessages();
        const messages = data.messages || [];
        showWelcome(!messages.some(m => m.role !== 'event') && !data.active_request_id);
        const fragment = document.createDocumentFragment();
        messages.forEach(msg => {
            const ts = new Date((msg.ts || Date.now() / 1000) * 1000);
            if (msg.role === 'event') {
                if (fragment.lastChild) fragment.appendChild(contextDividerEl());
            } else if (msg.role === 'user') {
                fragment.appendChild(createUserMessageEl(msg.content, ts, msg.attachments));
            } else if ((msg.content || '').trim() || (msg.steps || []).length || (msg.files || []).length) {
                fragment.appendChild(createBotMessageEl(msg, ts));
            }
        });
        messagesDiv.appendChild(fragment);
        if (!messages.length) {
            messagesDiv.scrollTop = 0;
            return data.active_request_id ? startStream(data.active_request_id, addLoadingIndicator(), new Date()) : undefined;
        }
        scrollChatToBottom(true);
        [120, 350].forEach(d => setTimeout(() => { if (_autoScrollEnabled) scrollChatToBottom(); }, d));
        if (data.active_request_id) startStream(data.active_request_id, addLoadingIndicator(), new Date());
    });
}

// --- conversations (views/sessions.js) ------------------------------------

function setSession(sid) {
    guestSessionId = sid;
    localStorage.setItem(guestSidKey, sid);
}

/** Leave the conversation on screen: its reply keeps running on the server
 *  and resumes when the visitor comes back to it. */
function leaveCurrentView() {
    guestViewGen++;
    if (guestRunning) resetSendBtnSendMode();
    pendingAttachments = [];
    renderAttachmentPreview();
}

function hasMessages() {
    return !!messagesDiv.querySelector('.user-message-group, .bot-message-group');
}

function loadSessions() {
    return guestApi('/sessions').then(data => {
        guestSessions = data.sessions || [];
        renderSessionList();
        return guestSessions;
    });
}

function rememberSession(text) {
    const now = Date.now() / 1000;
    const existing = guestSessions.find(s => s.session_id === guestSessionId);
    if (existing) {
        existing.updated_at = now;
        guestSessions = [existing].concat(guestSessions.filter(s => s !== existing));
    } else {
        guestSessions.unshift({ session_id: guestSessionId, title: text.slice(0, 60), updated_at: now, created_at: now });
    }
    renderSessionList();
}

function renderSessionList() {
    const list = document.getElementById('session-list');
    if (!guestSessions.length) {
        list.innerHTML = `<div class="session-empty">${escapeHtml(gt('no_sessions'))}</div>`;
        return;
    }
    list.innerHTML = guestSessions.map(s => {
        const title = s.title || t('untitled_session');
        const active = s.session_id === guestSessionId ? ' active' : '';
        return `<div class="session-item${active}" data-session-id="${escapeHtml(s.session_id)}">
                <i class="fas fa-message session-icon"></i>
                <span class="session-title" title="${escapeHtml(title)}">${escapeHtml(title)}</span>
                <button class="session-delete" data-delete="${escapeHtml(s.session_id)}" aria-label="delete">
                    <i class="fas fa-trash-can"></i>
                </button>
            </div>`;
    }).join('');
}

function isMobileView() {
    return window.innerWidth <= 768;
}

function toggleSessionPanel(open) {
    sessionPanelOpen = open === undefined ? !sessionPanelOpen : !!open;
    document.getElementById('session-panel').classList.toggle('hidden', !sessionPanelOpen);
    document.getElementById('session-panel-overlay').classList.toggle('hidden', !sessionPanelOpen);
    if (!isMobileView()) localStorage.setItem('cow_guest_panel', sessionPanelOpen ? '1' : '0');
}

function closePanelOnMobile() {
    if (sessionPanelOpen && isMobileView()) toggleSessionPanel(false);
}

function switchSession(sid) {
    closePanelOnMobile();
    if (sid === guestSessionId) return;
    leaveCurrentView();
    setSession(sid);
    renderSessionList();
    loadHistory().catch(err => guestToast(guestErrorText(err)));
}

function newChat() {
    closePanelOnMobile();
    if (!hasMessages() && !guestRunning) {
        showWelcome(true);
        chatInput.focus();
        return Promise.resolve();
    }
    return startNewSession().then(() => chatInput.focus()).catch(err => guestToast(guestErrorText(err)));
}

function startNewSession() {
    return guestApi('/sessions', { method: 'POST', json: {} }).then(data => {
        leaveCurrentView();
        setSession(data.session_id);
        clearMessages();
        showWelcome(true);
        renderSessionList();
    });
}

function guestConfirm(title, message, onConfirm) {
    let overlay = document.getElementById('confirm-modal-overlay');
    if (overlay) overlay.remove();
    overlay = document.createElement('div');
    overlay.id = 'confirm-modal-overlay';
    overlay.className = 'confirm-overlay';
    overlay.innerHTML = `
        <div class="confirm-modal">
            <div class="confirm-title">${escapeHtml(title)}</div>
            <div class="confirm-message">${escapeHtml(message)}</div>
            <div class="confirm-actions">
                <button class="confirm-btn confirm-btn-cancel">${escapeHtml(t('confirm_cancel'))}</button>
                <button class="confirm-btn confirm-btn-ok">${escapeHtml(t('confirm_yes'))}</button>
            </div>
        </div>`;
    document.body.appendChild(overlay);
    requestAnimationFrame(() => overlay.classList.add('visible'));
    const close = () => {
        overlay.classList.remove('visible');
        setTimeout(() => overlay.remove(), 200);
    };
    overlay.addEventListener('click', e => { if (e.target === overlay) close(); });
    overlay.querySelector('.confirm-btn-cancel').addEventListener('click', close);
    overlay.querySelector('.confirm-btn-ok').addEventListener('click', () => { close(); onConfirm(); });
}

function deleteSession(sid) {
    guestConfirm(t('delete_session_title'), t('delete_session_confirm'), () => {
        guestApi('/sessions/' + encodeURIComponent(sid), { method: 'DELETE' }).then(() => {
            guestSessions = guestSessions.filter(s => s.session_id !== sid);
            if (sid !== guestSessionId) { renderSessionList(); return; }
            const next = guestSessions[0];
            if (next) {
                leaveCurrentView();
                setSession(next.session_id);
                renderSessionList();
                return loadHistory();
            }
            return startNewSession();
        }).catch(err => guestToast(guestErrorText(err)));
    });
}

function clearContext() {
    if (guestRunning) { guestToast(gt('reply_running')); return; }
    const last = messagesDiv.lastElementChild;
    if (!hasMessages() || (last && last.classList.contains('context-divider'))) return;
    guestApi(`/sessions/${encodeURIComponent(guestSessionId)}/clear`, { method: 'POST', json: {} }).then(() => {
        messagesDiv.appendChild(contextDividerEl());
        scrollChatToBottom(true);
    }).catch(err => guestToast(guestErrorText(err)));
}

/** Land on a conversation: the one this browser was in, else the latest,
 *  else a fresh one. */
function enterChat() {
    return loadSessions().then(list => {
        const visitor = guestVisitorId();
        if (visitor && guestSessionId.indexOf(visitor) === 0) return loadHistory();
        if (!list.length) return startNewSession();
        setSession(list[0].session_id);
        renderSessionList();
        return loadHistory();
    }).catch(err => {
        if (err.reason === 'session_not_found') return startNewSession();
        throw err;
    });
}

function renderWelcome(info) {
    const name = info.name || '';
    document.title = name;
    document.querySelectorAll('.guest-name').forEach(el => { el.textContent = name; });
    const subtitle = document.getElementById('welcome-subtitle');
    subtitle.textContent = info.welcome || '';
    subtitle.classList.toggle('hidden', !info.welcome);
    const tones = [
        ['bg-blue-50 dark:bg-blue-900/30', 'text-blue-500'],
        ['bg-amber-50 dark:bg-amber-900/30', 'text-amber-500'],
        ['bg-emerald-50 dark:bg-emerald-900/30', 'text-emerald-500'],
        ['bg-violet-50 dark:bg-violet-900/30', 'text-violet-500'],
        ['bg-rose-50 dark:bg-rose-900/30', 'text-rose-500'],
        ['bg-slate-100 dark:bg-slate-800', 'text-slate-500'],
    ];
    const examples = document.getElementById('welcome-examples');
    const questions = (info.suggested_questions || []).slice(0, 6);
    examples.classList.toggle('hidden', !questions.length);
    examples.innerHTML = questions.map((q, i) => {
        const tone = tones[i % tones.length];
        return `<button type="button" class="guest-example-card example-card group bg-white dark:bg-[#1A1A1A] border border-slate-200 dark:border-white/10 rounded-xl p-4
                        cursor-pointer hover:border-primary-300 dark:hover:border-primary-600 hover:shadow-md transition-all duration-200
                        flex items-start gap-2.5" data-question="${escapeHtml(q)}">
                    <span class="w-7 h-7 rounded-lg ${tone[0]} flex items-center justify-center flex-shrink-0">
                        <i class="fas fa-comment-dots ${tone[1]} text-xs"></i>
                    </span>
                    <span class="text-sm text-slate-600 dark:text-slate-300 leading-relaxed pt-0.5">${escapeHtml(q)}</span>
                </button>`;
    }).join('');
    welcomeScreen.classList.remove('invisible');
}

// --- wiring --------------------------------------------------------------

messagesDiv.addEventListener('wheel', event => {
    if (event.deltaY < 0) _userScrollIntent = 'up';
    else if (event.deltaY > 0) _userScrollIntent = 'down';
}, { passive: true });
messagesDiv.addEventListener('touchstart', event => {
    _touchScrollStartY = event.touches[0] ? event.touches[0].clientY : null;
}, { passive: true });
messagesDiv.addEventListener('touchmove', event => {
    const currentY = event.touches[0] && event.touches[0].clientY;
    if (_touchScrollStartY === null || currentY === undefined) return;
    const delta = currentY - _touchScrollStartY;
    if (delta > 2) {
        _userScrollIntent = 'up';
        _autoScrollEnabled = false;
        cancelQueuedChatScroll();
    } else if (delta < -2) {
        _userScrollIntent = 'down';
    }
}, { passive: true });
messagesDiv.addEventListener('touchend', () => { _touchScrollStartY = null; }, { passive: true });
messagesDiv.addEventListener('touchcancel', () => { _touchScrollStartY = null; }, { passive: true });
messagesDiv.addEventListener('pointerdown', event => {
    const rect = messagesDiv.getBoundingClientRect();
    if (event.target === messagesDiv && event.clientX >= rect.right - 16) _userScrollIntent = 'scrollbar';
}, { passive: true });
messagesDiv.addEventListener('scroll', () => {
    const scrollTop = messagesDiv.scrollTop;
    const distFromBottom = messagesDiv.scrollHeight - scrollTop - messagesDiv.clientHeight;
    if (_userScrollIntent !== null) {
        const intent = _userScrollIntent === 'scrollbar'
            ? (scrollTop < _lastScrollTop - 1 ? 'up' : scrollTop > _lastScrollTop + 1 ? 'down' : null)
            : _userScrollIntent;
        if (intent === 'up') _autoScrollEnabled = false;
        else if (intent === 'down' && distFromBottom <= _SCROLL_THRESHOLD) _autoScrollEnabled = true;
    }
    _userScrollIntent = null;
    _programmaticScroll = false;
    _programmaticScrollTop = null;
    _lastScrollTop = scrollTop;
    _updateScrollToBottomBtn();
});

function copyText(text) {
    if (navigator.clipboard && window.isSecureContext) return navigator.clipboard.writeText(text);
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.style.cssText = 'position:fixed;opacity:0';
    document.body.appendChild(ta);
    ta.select();
    try { document.execCommand('copy'); } finally { ta.remove(); }
    return Promise.resolve();
}

function flashCopied(btn) {
    const icon = btn.querySelector('i');
    if (!icon) return;
    icon.className = 'fas fa-check';
    setTimeout(() => { icon.className = 'fas fa-copy'; }, 1500);
}

messagesDiv.addEventListener('click', e => {
    const header = e.target.closest('.tool-header');
    if (header) { header.parentElement.classList.toggle('expanded'); return; }

    const codeCopyBtn = e.target.closest('.code-copy-btn');
    if (codeCopyBtn) {
        const code = codeCopyBtn.closest('.code-block-wrapper');
        const codeEl = code && code.querySelector('pre code');
        if (codeEl) copyText(codeEl.textContent).then(() => flashCopied(codeCopyBtn));
        return;
    }

    const copyBtn = e.target.closest('.copy-msg-btn');
    if (copyBtn) {
        const answer = copyBtn.closest('.bot-message-group').querySelector('.answer-content');
        const raw = answer && answer.dataset.rawMd;
        if (raw) copyText(raw).then(() => flashCopied(copyBtn));
        return;
    }

    const example = e.target.closest('[data-question]');
    if (example) { sendMessage(example.dataset.question); return; }

    const card = e.target.closest('.file-card[data-download]');
    if (card && !e.target.closest('a')) {
        const a = document.createElement('a');
        a.href = card.dataset.download;
        a.download = card.dataset.name || '';
        document.body.appendChild(a);
        a.click();
        a.remove();
    }
});

chatInput.addEventListener('input', () => { autoResizeComposer(); updateSendBtnState(); });
chatInput.addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey && !e.isComposing && e.keyCode !== 229) {
        e.preventDefault();
        sendMessage();
    }
});
sendBtn.addEventListener('click', () => { if (guestRunning) requestCancel(); else sendMessage(); });
newChatBtn.addEventListener('click', () => newChat());
document.getElementById('clear-context-btn').addEventListener('click', clearContext);
document.getElementById('session-list').addEventListener('click', e => {
    const del = e.target.closest('[data-delete]');
    if (del) { e.stopPropagation(); deleteSession(del.dataset.delete); return; }
    const item = e.target.closest('.session-item[data-session-id]');
    if (item) switchSession(item.dataset.sessionId);
});
attachBtn.addEventListener('click', () => fileInput.click());
fileInput.addEventListener('change', () => {
    Array.from(fileInput.files || []).forEach(uploadFile);
    fileInput.value = '';
});
attachmentPreview.addEventListener('click', e => {
    const btn = e.target.closest('[data-remove]');
    if (!btn) return;
    const idx = Number(btn.dataset.remove);
    if (pendingAttachments[idx] && !pendingAttachments[idx]._uploading) {
        pendingAttachments.splice(idx, 1);
        renderAttachmentPreview();
    }
});
chatInput.addEventListener('paste', e => {
    if (!guestInfo || !guestInfo.upload) return;
    const files = Array.from((e.clipboardData && e.clipboardData.files) || []);
    if (!files.length) return;
    e.preventDefault();
    files.forEach(uploadFile);
});
['dragenter', 'dragover'].forEach(type => composerCard.addEventListener(type, e => {
    if (!guestInfo || !guestInfo.upload || !e.dataTransfer || !Array.from(e.dataTransfer.types || []).includes('Files')) return;
    e.preventDefault();
    composerCard.classList.add('drag-over');
}));
['dragleave', 'drop'].forEach(type => composerCard.addEventListener(type, e => {
    composerCard.classList.remove('drag-over');
    if (type !== 'drop' || !guestInfo || !guestInfo.upload || !e.dataTransfer) return;
    e.preventDefault();
    Array.from(e.dataTransfer.files || []).forEach(uploadFile);
}));

document.getElementById('guest-toggle-pwd').addEventListener('click', () => {
    const input = document.getElementById('guest-password');
    const show = input.type === 'password';
    input.type = show ? 'text' : 'password';
    document.querySelector('#guest-toggle-pwd i').className = show ? 'fas fa-eye-slash text-sm' : 'fas fa-eye text-sm';
});
document.getElementById('guest-gate-form').addEventListener('submit', e => {
    e.preventDefault();
    const input = document.getElementById('guest-password');
    const btn = document.getElementById('guest-gate-btn');
    if (!input.value) return;
    btn.disabled = true;
    openSession({ password: input.value }).then(() => {
        input.value = '';
        document.getElementById('guest-gate').classList.add('hidden');
        return enterChat();
    }).catch(handleSessionError).finally(() => { btn.disabled = false; });
});

// --- voice input (chat/state.js setupMicButton) ---------------------------

function setupMicButton() {
    const micBtn = document.getElementById('mic-btn');
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia ||
        typeof window.MediaRecorder === 'undefined') return;
    micBtn.classList.remove('hidden');

    let mediaRecorder = null;
    let stream = null;
    let chunks = [];
    let recording = false;
    let busy = false;
    let startedAt = 0;

    const setState = (state) => {
        recording = state === 'recording';
        busy = state === 'busy';
        micBtn.classList.toggle('text-red-500', recording);
        micBtn.classList.toggle('animate-pulse', recording);
        micBtn.classList.toggle('text-primary-500', busy);
        micBtn.classList.toggle('text-slate-400', state === 'idle');
        micBtn.querySelector('i').className = recording ? 'fas fa-stop text-sm'
            : busy ? 'fas fa-spinner fa-spin text-sm' : 'fas fa-microphone text-sm';
        micBtn.dataset.tooltip = t(recording ? 'mic_recording_title' : busy ? 'mic_busy_title' : 'mic_idle_title');
    };
    const stopStream = () => {
        if (stream) { stream.getTracks().forEach(track => track.stop()); stream = null; }
    };
    const pickMimeType = () => ['audio/webm;codecs=opus', 'audio/webm', 'audio/ogg;codecs=opus', 'audio/mp4']
        .find(m => MediaRecorder.isTypeSupported && MediaRecorder.isTypeSupported(m)) || '';

    const upload = (blob, ext) => {
        setState('busy');
        const form = new FormData();
        form.append('file', blob, `recording.${ext}`);
        guestApi('/voice', { method: 'POST', body: form })
            .then(data => sendMessage(data.text))
            .catch(err => guestToast(err.reason === 'voice_failed' ? gt('voice_failed') : guestErrorText(err)))
            .finally(() => setState('idle'));
    };

    const start = async () => {
        try {
            stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        } catch (e) {
            guestToast(t('mic_permission_denied'));
            return;
        }
        chunks = [];
        const mimeType = pickMimeType();
        try {
            mediaRecorder = mimeType ? new MediaRecorder(stream, { mimeType }) : new MediaRecorder(stream);
        } catch (e) {
            stopStream();
            guestToast(t('mic_error'));
            return;
        }
        mediaRecorder.ondataavailable = ev => { if (ev.data && ev.data.size > 0) chunks.push(ev.data); };
        mediaRecorder.onstop = () => {
            stopStream();
            const type = (mediaRecorder.mimeType || 'audio/webm').split(';')[0];
            const blob = new Blob(chunks, { type });
            if (blob.size < 256) { setState('idle'); guestToast(t('mic_too_short')); return; }
            upload(blob, { 'audio/ogg': 'ogg', 'audio/mp4': 'm4a', 'audio/mpeg': 'mp3' }[type] || 'webm');
        };
        mediaRecorder.start(250);
        startedAt = Date.now();
        setState('recording');
    };
    const stop = () => {
        const wait = 350 - (Date.now() - startedAt);
        const done = () => { if (mediaRecorder && mediaRecorder.state !== 'inactive') mediaRecorder.stop(); };
        if (wait > 0) setTimeout(done, wait); else done();
    };

    micBtn.addEventListener('click', () => {
        if (busy) return;
        if (recording) { stop(); return; }
        if (guestRunning) { guestToast(gt('reply_running')); return; }
        start();
    });
    setState('idle');
}

// --- boot ----------------------------------------------------------------

chatInput.placeholder = gt('placeholder');
document.getElementById('guest-password').placeholder = gt('password');
document.getElementById('guest-gate-subtitle').textContent = gt('gate_subtitle');
document.getElementById('guest-gate-btn').textContent = gt('gate_btn');
newChatBtn.dataset.tooltip = t('tip_new_chat');
attachBtn.dataset.tooltip = gt('attach');
document.getElementById('clear-context-btn').dataset.tooltip = t('tip_clear_context');
document.getElementById('session-toggle-btn').dataset.tooltip = t('session_history');
document.getElementById('session-panel-title').textContent = t('session_history');
document.getElementById('session-panel-new-label').textContent = t('new_chat');
document.getElementById('scroll-to-bottom-btn').setAttribute('aria-label', t('chat_scroll_to_bottom'));
document.querySelectorAll('.guest-powered').forEach(el => {
    el.textContent = guestBrand.footer_text || '';
    if (/^https?:\/\//i.test(guestBrand.footer_url || '')) el.href = guestBrand.footer_url;
    el.classList.toggle('hidden', !guestBrand.footer_text);
});
applyTheme();
installCfgTipPortal();
resetComposerHeight();

// Framed by embed.js: the launcher may be hidden behind a full-screen panel
// on phones, so the page offers its own way to close the window.
const guestEmbedded = window.parent !== window && new URLSearchParams(location.search).get('embed') === '1';
if (!guestEmbedded && !isMobileView() && localStorage.getItem('cow_guest_panel') !== '0') toggleSessionPanel(true);

if (guestEmbedded) {
    const closeBtn = document.getElementById('guest-close-btn');
    closeBtn.classList.remove('hidden');
    closeBtn.addEventListener('click', () => window.parent.postMessage({ type: 'cow-guest:close' }, '*'));
}

guestApi('/info').then(info => {
    guestInfo = info;
    renderWelcome(info);
    attachBtn.classList.toggle('hidden', !info.upload);
    if (info.voice) setupMicButton();
    if (!info.available) { showUnavailable(info.reason); return; }
    return openSession({ token: guestToken }).then(enterChat, handleSessionError);
}).catch(err => handleSessionError(err));
