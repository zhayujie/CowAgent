/* Composer input: drag-and-drop, paste, slash commands, key handling.
   Split out of console.js. These are classic scripts sharing one global
   scope; see channel/web/README.md before changing the load order. */

// Drag-and-drop support on entire chat view
const chatView = document.getElementById('view-chat');
const chatInputArea = document.getElementById('composer-card') || chatInput.closest('.flex-shrink-0');

// Make the empty parts of the composer card act like the text area. Keep
// controls and their popovers in charge of their own clicks.
chatInputArea.addEventListener('click', (event) => {
    const target = event.target;
    if (!(target instanceof Element) || target === chatInput) return;
    const excluded = target.closest([
        'button', 'input', 'select', 'a', '[role="button"]', 'textarea',
        '.attachment-preview', '.attach-menu', '.slash-menu', '.mention-menu',
        '.workspace-selector-menu', '.composer-menu',
    ].join(', '));
    if (excluded) return;
    chatInput.focus({ preventScroll: true });
});

// Create drag overlay for visual feedback
let dragOverlay = document.getElementById('drag-overlay');
if (!dragOverlay) {
    dragOverlay = document.createElement('div');
    dragOverlay.id = 'drag-overlay';
    dragOverlay.className = 'drag-overlay hidden';
    dragOverlay.innerHTML = `
        <div class="drag-overlay-content">
            <i class="fas fa-cloud-arrow-up"></i>
            <p>Drop files here to upload</p>
        </div>
    `;
    chatView.appendChild(dragOverlay);
}

let dragCounter = 0;

function showDragOverlay() {
    dragOverlay.classList.remove('hidden');
    dragOverlay.classList.add('active');
}

function hideDragOverlay() {
    dragOverlay.classList.remove('active');
    dragOverlay.classList.add('hidden');
}

/** Clear every drag affordance at once, whatever the drag's outcome was. */
function resetDragState() {
    dragCounter = 0;
    hideDragOverlay();
    chatInputArea.classList.remove('drag-over');
    document.getElementById('chat-main')?.classList.remove('ws-drop-active');
}

chatView.addEventListener('dragenter', (e) => {
    e.preventDefault();
    e.stopPropagation();
    dragCounter++;
    if (e.dataTransfer.types.includes('Files')) {
        showDragOverlay();
    }
});

chatView.addEventListener('dragover', (e) => {
    e.preventDefault();
    e.stopPropagation();
    // Only external file drags upload here; workspace drags have their own target.
    if (e.dataTransfer.types.includes('Files')) {
        chatInputArea.classList.add('drag-over');
    }
});

chatView.addEventListener('dragleave', (e) => {
    e.preventDefault();
    e.stopPropagation();
    dragCounter--;
    if (dragCounter <= 0) {
        resetDragState();
    }
});

chatView.addEventListener('drop', (e) => {
    e.preventDefault();
    e.stopPropagation();
    resetDragState();
    if (e.dataTransfer.files.length) {
        handleFileSelect(e.dataTransfer.files);
    }
});

// A drag can end without ever reaching a drop target (Esc, or released over
// another element). Clear the highlight unconditionally so it can't stay stuck
// until the next reload.
document.addEventListener('dragend', resetDragState);
window.addEventListener('drop', resetDragState);

document.body.addEventListener('dragover', (e) => {
    if (e.dataTransfer.types.includes('Files')) {
        e.preventDefault();
    }
});

document.body.addEventListener('drop', (e) => {
    if (e.dataTransfer.types.includes('Files')) {
        e.preventDefault();
    }
});

// Paste image support
chatInput.addEventListener('paste', (e) => {
    const items = e.clipboardData?.items;
    if (!items) return;
    const files = [];
    for (const item of items) {
        if (item.kind === 'file') {
            files.push(item.getAsFile());
        }
    }
    if (files.length) {
        e.preventDefault();
        handleFileSelect(files);
    }
});

chatInput.addEventListener('compositionstart', () => { isComposing = true; });
chatInput.addEventListener('compositionend', () => { setTimeout(() => { isComposing = false; }, 100); });

// ── Slash Command Menu ───────────────────────────────────────
// desc holds an i18n key, resolved via t() at render time so the menu follows
// the current UI language.
const SLASH_COMMANDS = [
    { cmd: '/help',                desc: 'slash_help' },
    { cmd: '/status',              desc: 'slash_status' },
    { cmd: '/context',             desc: 'slash_context' },
    { cmd: '/clear',               desc: 'slash_context_clear' },
    { cmd: '/compact',             desc: 'slash_compact' },
    { cmd: '/skill list',          desc: 'slash_skill_list' },
    { cmd: '/skill list --remote', desc: 'slash_skill_list_remote' },
    { cmd: '/skill search ',       desc: 'slash_skill_search' },
    { cmd: '/skill install ',      desc: 'slash_skill_install' },
    { cmd: '/skill uninstall ',    desc: 'slash_skill_uninstall' },
    { cmd: '/skill info ',         desc: 'slash_skill_info' },
    { cmd: '/skill enable ',       desc: 'slash_skill_enable' },
    { cmd: '/skill disable ',      desc: 'slash_skill_disable' },
    { cmd: '/memory dream ',       desc: 'slash_memory_dream' },
    { cmd: '/knowledge',           desc: 'slash_knowledge' },
    { cmd: '/knowledge list',      desc: 'slash_knowledge_list' },
    { cmd: '/knowledge on',        desc: 'slash_knowledge_on' },
    { cmd: '/knowledge off',       desc: 'slash_knowledge_off' },
    { cmd: '/config',              desc: 'slash_config' },
    { cmd: '/cancel',              desc: 'slash_cancel' },
    { cmd: '/steer ',              desc: 'slash_steer' },
    { cmd: '/logs',                desc: 'slash_logs' },
    { cmd: '/version',             desc: 'slash_version' },
];

const slashMenu = document.getElementById('slash-menu');
let slashActiveIdx = 0;
let slashFiltered = [];
let slashJustSelected = false;
let slashLastFilter = '';
let slashLastMouseX = -1;
let slashLastMouseY = -1;

function showSlashMenu(filter) {
    const q = filter.toLowerCase();
    if (q === slashLastFilter && !slashMenu.classList.contains('hidden')) return;
    slashLastFilter = q;

    const newFiltered = SLASH_COMMANDS.filter(c => c.cmd.toLowerCase().startsWith(q));
    if (newFiltered.length === 0) {
        hideSlashMenu();
        return;
    }

    const changed = newFiltered.length !== slashFiltered.length ||
        newFiltered.some((c, i) => c.cmd !== slashFiltered[i]?.cmd);
    slashFiltered = newFiltered;
    if (changed) slashActiveIdx = 0;
    slashActiveIdx = Math.min(slashActiveIdx, slashFiltered.length - 1);

    slashNavByKeyboard = true;
    renderSlashItems();
    slashMenu.classList.remove('hidden');
}

function hideSlashMenu() {
    // This runs on every keystroke. Skip DOM writes when already hidden: even a
    // no-op classList.add rewrites the class attribute, which wakes the Tailwind
    // runtime's MutationObserver and makes typing lag on long conversations.
    if (!slashMenu.classList.contains('hidden')) slashMenu.classList.add('hidden');
    if (slashMenu.firstChild) slashMenu.innerHTML = '';
    slashFiltered = [];
    slashActiveIdx = -1;
    slashLastFilter = '';
    slashNavByKeyboard = false;
    slashLastMouseX = -1;
    slashLastMouseY = -1;
}

function isSlashMenuVisible() {
    return !slashMenu.classList.contains('hidden') && slashFiltered.length > 0;
}

function renderSlashItems() {
    slashMenu.innerHTML =
        '<div class="slash-menu-header">Commands</div>' +
        slashFiltered.map((c, i) =>
            `<div class="slash-menu-item${i === slashActiveIdx ? ' active' : ''}" data-idx="${i}">` +
            `<span class="cmd">${escapeHtml(c.cmd)}</span>` +
            `<span class="desc">${escapeHtml(t(c.desc))}</span></div>`
        ).join('');

    const activeEl = slashMenu.querySelector('.slash-menu-item.active');
    if (activeEl) activeEl.scrollIntoView({ block: 'nearest' });
}

// Delegated events on the persistent slashMenu container (not destroyed by innerHTML)
// Use coordinate comparison to distinguish real mouse movement from DOM-rebuild phantom events.
slashMenu.addEventListener('mousemove', (e) => {
    if (e.clientX === slashLastMouseX && e.clientY === slashLastMouseY) return;
    slashLastMouseX = e.clientX;
    slashLastMouseY = e.clientY;
    if (!slashNavByKeyboard) return;
    slashNavByKeyboard = false;
    const item = e.target.closest('.slash-menu-item');
    if (!item) return;
    const idx = parseInt(item.dataset.idx);
    if (idx === slashActiveIdx) return;
    slashActiveIdx = idx;
    slashMenu.querySelectorAll('.slash-menu-item').forEach(el => {
        el.classList.toggle('active', parseInt(el.dataset.idx) === idx);
    });
});

slashMenu.addEventListener('mouseover', (e) => {
    if (slashNavByKeyboard) return;
    const item = e.target.closest('.slash-menu-item');
    if (!item) return;
    const idx = parseInt(item.dataset.idx);
    if (idx === slashActiveIdx) return;
    slashActiveIdx = idx;
    slashMenu.querySelectorAll('.slash-menu-item').forEach(el => {
        el.classList.toggle('active', parseInt(el.dataset.idx) === idx);
    });
});

slashMenu.addEventListener('mousedown', (e) => {
    const item = e.target.closest('.slash-menu-item');
    if (!item) return;
    e.preventDefault();
    selectSlashCommand(parseInt(item.dataset.idx));
});

function selectSlashCommand(idx) {
    if (idx < 0 || idx >= slashFiltered.length) return;
    const chosen = slashFiltered[idx].cmd;
    slashJustSelected = true;
    chatInput.value = chosen;
    chatInput.dispatchEvent(new Event('input'));
    hideSlashMenu();
    chatInput.focus();
    chatInput.selectionStart = chatInput.selectionEnd = chosen.length;
}

chatInput.addEventListener('input', function() {
    autoResizeComposer();
    updateSendBtnState();
    // Reveal/hide the steer button as the user types during a running turn.
    updateSteerBtnState();

    const val = this.value;
    if (slashJustSelected) {
        slashJustSelected = false;
    } else if (val.startsWith('/')) {
        showSlashMenu(val);
    } else {
        hideSlashMenu();
    }
});

chatInput.addEventListener('keydown', function(e) {
    if (e.keyCode === 229 || e.isComposing || isComposing) return;

    if (e.key === 'Escape' && isAttachMenuVisible()) {
        hideAttachMenu();
        return;
    }

    if (isSlashMenuVisible()) {
        if (e.key === 'ArrowDown') {
            e.preventDefault();
            slashNavByKeyboard = true;
            slashActiveIdx = Math.min(slashActiveIdx + 1, slashFiltered.length - 1);
            renderSlashItems();
            return;
        }
        if (e.key === 'ArrowUp') {
            e.preventDefault();
            slashNavByKeyboard = true;
            slashActiveIdx = Math.max(slashActiveIdx - 1, 0);
            renderSlashItems();
            return;
        }
        if (e.key === 'Enter' && !e.shiftKey && !e.ctrlKey) {
            e.preventDefault();
            selectSlashCommand(slashActiveIdx);
            return;
        }
        if (e.key === 'Escape') {
            e.preventDefault();
            hideSlashMenu();
            return;
        }
        if (e.key === 'Tab') {
            e.preventDefault();
            selectSlashCommand(slashActiveIdx);
            return;
        }
    }

    // Arrow-key history recall (only when input is empty or already browsing history)
    if (e.key === 'ArrowUp' && inputHistory.length > 0 && !isSlashMenuVisible()) {
        const curVal = this.value.trim();
        const isSingleLine = !this.value.includes('\n');
        if (isSingleLine && (curVal === '' || historyIdx >= 0)) {
            e.preventDefault();
            if (historyIdx < 0) {
                historySavedDraft = this.value;
                historyIdx = inputHistory.length - 1;
            } else if (historyIdx > 0) {
                historyIdx--;
            }
            this.value = inputHistory[historyIdx];
            slashJustSelected = true;
            this.dispatchEvent(new Event('input'));
            hideSlashMenu();
            this.selectionStart = this.selectionEnd = this.value.length;
            return;
        }
    }
    if (e.key === 'ArrowDown' && historyIdx >= 0 && !isSlashMenuVisible()) {
        const isSingleLine = !this.value.includes('\n');
        if (isSingleLine) {
            e.preventDefault();
            if (historyIdx < inputHistory.length - 1) {
                historyIdx++;
                this.value = inputHistory[historyIdx];
            } else {
                historyIdx = -1;
                this.value = historySavedDraft;
                historySavedDraft = '';
            }
            slashJustSelected = true;
            this.dispatchEvent(new Event('input'));
            hideSlashMenu();
            this.selectionStart = this.selectionEnd = this.value.length;
            return;
        }
    }

    if ((e.ctrlKey || e.shiftKey) && e.key === 'Enter') {
        const start = this.selectionStart;
        const end = this.selectionEnd;
        this.value = this.value.substring(0, start) + '\n' + this.value.substring(end);
        this.selectionStart = this.selectionEnd = start + 1;
        this.dispatchEvent(new Event('input'));
        e.preventDefault();
    } else if (e.key === 'Enter' && !e.shiftKey && !e.ctrlKey) {
        sendMessage();
        e.preventDefault();
    }
});

chatInput.addEventListener('blur', () => {
    setTimeout(hideSlashMenu, 150);
});

document.querySelectorAll('.example-card').forEach(card => {
    card.addEventListener('click', () => {
        // data-send overrides the visible text (e.g. show "查看全部命令" but send "/help")
        const sendText = card.dataset.send;
        if (sendText) {
            chatInput.value = sendText;
            chatInput.dispatchEvent(new Event('input'));
            chatInput.focus();
            return;
        }
        const textEl = card.querySelector('[data-i18n*="text"]');
        if (textEl) {
            chatInput.value = textEl.textContent;
            chatInput.dispatchEvent(new Event('input'));
            chatInput.focus();
        }
    });
});

