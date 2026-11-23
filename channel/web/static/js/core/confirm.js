/* The scripted confirm dialog used across every view.
   Split out of console.js. These are classic scripts sharing one global
   scope; see channel/web/README.md before changing the load order. */

// =====================================================================
// Custom Confirm Dialog
// =====================================================================
const _CONFIRM_TONES = {
    danger: {
        badge: 'bg-red-50 dark:bg-red-900/20',
        icon: 'fas fa-triangle-exclamation text-red-500',
        ok: 'bg-red-500 hover:bg-red-600',
    },
    primary: {
        badge: 'bg-primary-50 dark:bg-primary-900/20',
        icon: 'fas fa-circle-info text-primary-500',
        ok: 'bg-primary-500 hover:bg-primary-600',
    },
};

function _applyConfirmTone(tone) {
    const style = _CONFIRM_TONES[tone] || _CONFIRM_TONES.danger;
    const all = Object.values(_CONFIRM_TONES);
    const badge = document.getElementById('confirm-dialog-badge');
    const ok = document.getElementById('confirm-dialog-ok');
    all.forEach(s => {
        badge.classList.remove(...s.badge.split(' '));
        ok.classList.remove(...s.ok.split(' '));
    });
    badge.classList.add(...style.badge.split(' '));
    ok.classList.add(...style.ok.split(' '));
    document.getElementById('confirm-dialog-icon').className = style.icon;
}

function showConfirmDialog({ title, message, okText, cancelText, onConfirm, onCancel: cancelCallback, hideCancel, tone }) {
    const overlay = document.getElementById('confirm-dialog-overlay');
    _applyConfirmTone(tone);
    document.getElementById('confirm-dialog-title').textContent = title || '';
    document.getElementById('confirm-dialog-message').textContent = message || '';
    document.getElementById('confirm-dialog-ok').textContent = okText || 'OK';
    const cancelBtn = document.getElementById('confirm-dialog-cancel');
    cancelBtn.textContent = cancelText || t('channels_cancel');
    cancelBtn.classList.toggle('hidden', !!hideCancel);

    function cleanup() {
        overlay.classList.add('hidden');
        okBtn.removeEventListener('click', onOk);
        cancelBtn.removeEventListener('click', onCancel);
        overlay.removeEventListener('click', onOverlayClick);
    }
    function onOk() { cleanup(); if (onConfirm) onConfirm(); }
    function onCancel() { cleanup(); if (cancelCallback) cancelCallback(); }
    function onOverlayClick(e) { if (e.target === overlay) onCancel(); }

    const okBtn = document.getElementById('confirm-dialog-ok');
    okBtn.addEventListener('click', onOk);
    cancelBtn.addEventListener('click', onCancel);
    overlay.addEventListener('click', onOverlayClick);
    overlay.classList.remove('hidden');
}

