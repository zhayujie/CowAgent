/**
 * Inline editor for the console's single-document pages.
 *
 * The memory page and the skills page both show one Markdown file rendered
 * read-only, with a button that swaps the rendering for a text area. What they
 * share is the part that hurts to get subtly wrong twice: knowing whether the
 * text area still matches what was loaded, carrying the mtime that catches the
 * agent rewriting the file mid-edit, and standing between an unsaved edit and
 * the actions that would throw it away.
 *
 * The workspace preview panel keeps its own copy of this in workspace.js. That
 * one edits whatever text file the panel happens to be showing and drives the
 * panel's own header, so the two have less in common than it first appears.
 */

/**
 * Why the server refused to make a document editable. Truncation is reported
 * first: a partial read can also split a multi-byte character and so come back
 * lossy, but the size is the reason the user needs to hear.
 *
 * @param {object} data - a read response, with `truncated` and `lossy`.
 * @returns {string} an i18n key.
 */
function docUneditableReason(data) {
    if (data.truncated) return 'ws_edit_too_large';
    if (data.lossy) return 'ws_edit_encoding';
    return 'ws_edit_unsupported';
}

/**
 * How far down its scrollable content an element sits, 0 to 1.
 *
 * Switching between the rendered document and the text area swaps one element
 * for the other, so there is no scroll position to carry over - only how far
 * through the document the reader was. The two have different heights, which
 * makes this an approximation, but one that lands on the same passage.
 */
function _docScrollRatio(el) {
    const max = el.scrollHeight - el.clientHeight;
    return max > 0 ? el.scrollTop / max : 0;
}

function _docApplyScrollRatio(el, ratio) {
    const max = el.scrollHeight - el.clientHeight;
    if (max > 0) el.scrollTop = Math.round(ratio * max);
}

/**
 * Build an editor bound to one page's DOM and API.
 *
 * @param {object} cfg
 * @param {function(): HTMLElement} cfg.body - element the document is drawn
 *   into, and which the text area takes over while editing.
 * @param {function(): object} cfg.buttons - `{edit, save, cancel}` elements to
 *   show and hide; any of them may be absent.
 * @param {function(object): Promise<object>} cfg.read - fetch the document's
 *   current text. Resolves with the API payload: `content`, `mtime`,
 *   `editable`, plus `truncated` / `lossy` to explain a refusal.
 * @param {function(object, string, ?number): Promise<object>} cfg.write - save
 *   `content` against an expected mtime, resolving with the raw response so a
 *   `conflict` code can be put to the user here.
 * @param {function(object): void} cfg.render - redraw the read-only view from
 *   the document's `content`.
 * @param {function(object): boolean} [cfg.canEdit] - whether this document may
 *   be edited at all. A false answer hides the edit button rather than letting
 *   the click fail; used for skills that ship with the installation.
 * @param {function(object): string} [cfg.refusal] - i18n key explaining a read
 *   response whose `editable` is false, when the page knows a better reason
 *   than the generic ones. Defaults to {@link docUneditableReason}.
 * @param {function(object): void} [cfg.onState] - called with
 *   `{editing, dirty}` whenever either changes, for a title marker or similar.
 */
function createDocEditor(cfg) {
    // The document on screen: whatever shape the host page uses, plus the
    // `content` field this editor keeps current as it loads and saves.
    let doc = null;
    let editing = false;
    let baseline = '';
    let baseMtime = null;
    let saving = false;

    function textarea() {
        return cfg.body()?.querySelector('textarea.doc-editor') || null;
    }

    function isDirty() {
        const ta = textarea();
        return editing && !!ta && ta.value !== baseline;
    }

    function sync() {
        const { edit, save: saveBtn, cancel: cancelBtn } = cfg.buttons() || {};
        const canEdit = !!doc && (!cfg.canEdit || cfg.canEdit(doc));
        edit?.classList.toggle('hidden', !canEdit || editing);
        saveBtn?.classList.toggle('hidden', !editing);
        cancelBtn?.classList.toggle('hidden', !editing);
        cfg.onState?.({ editing: editing, dirty: isDirty() });
    }

    /** Adopt a freshly opened document and draw it read-only. */
    function open(next) {
        doc = next;
        editing = false;
        baseline = '';
        baseMtime = null;
        cfg.render(doc);
        sync();
    }

    /** Drop all state without touching what is on screen. */
    function forget() {
        doc = null;
        editing = false;
        baseline = '';
        baseMtime = null;
        sync();
    }

    /**
     * Gate an action that would throw away the text area's contents.
     *
     * @param {function} next - runs once the user agrees to lose the edits, and
     *   owns whatever replaces the editor. It runs with edit mode already off,
     *   so it must not be a function that bails out when not editing.
     * @returns {boolean} true when there is nothing to lose and the caller may
     *   go ahead; false once the confirmation is on screen.
     */
    function guard(next) {
        if (!isDirty()) return true;
        showConfirmDialog({
            title: t('ws_edit_discard_title'),
            message: t('ws_edit_discard_msg'),
            okText: t('ws_edit_discard_ok'),
            onConfirm: () => {
                editing = false;
                next();
            },
        });
        return false;
    }

    /** Load the document's current text into a text area. */
    async function start() {
        if (editing || !doc) return;
        const target = doc;
        const body = cfg.body();
        if (!body) return;
        // Read before the spinner replaces the document, which zeroes it.
        const ratio = _docScrollRatio(body);
        body.innerHTML = '<div class="py-10 text-center text-slate-400 dark:text-slate-500">'
            + '<i class="fas fa-spinner fa-spin"></i></div>';

        let data;
        try {
            data = await cfg.read(target);
        } catch (e) {
            _wsToast(`${t('ws_edit_load_failed')}: ${e.message}`);
            cfg.render(target);
            return;
        }
        // The user may have navigated away while the request was in flight.
        if (doc !== target) return;
        if (!data.editable) {
            _wsToast(t((cfg.refusal || docUneditableReason)(data)));
            cfg.render(target);
            return;
        }

        // Adopt the text just read: the agent may have rewritten the file since
        // the page rendered it, and leaving on save would otherwise redraw the
        // stale copy.
        target.content = data.content;
        editing = true;
        baseMtime = data.mtime;
        // Read the baseline back out of the text area rather than using the
        // response text: a text area normalizes CRLF to LF in its value, so a
        // CRLF file would compare as modified from the moment it loaded.
        baseline = mount(body, data.content, ratio).value;
        sync();
    }

    /**
     * @param {number} [ratio] - where the reader was in the rendered document,
     *   so the text area opens on the same passage.
     * @returns {HTMLTextAreaElement} the text area now holding the document.
     */
    function mount(body, content, ratio) {
        body.innerHTML = '';
        const ta = document.createElement('textarea');
        ta.className = 'doc-editor';
        ta.spellcheck = false;
        ta.value = content;
        body.appendChild(ta);

        ta.addEventListener('input', sync);
        ta.addEventListener('keydown', (e) => {
            if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') {
                // Save in place, the way an editor does. The Save button
                // instead returns to the rendered document.
                e.preventDefault();
                save({ keepEditing: true });
            } else if (e.key === 'Escape') {
                e.preventDefault();
                cancel();
            } else if (e.key === 'Tab') {
                // Otherwise Tab leaves the text area, which is never what
                // indenting a line is meant to do.
                e.preventDefault();
                const { selectionStart: from, selectionEnd: to } = ta;
                ta.value = `${ta.value.slice(0, from)}    ${ta.value.slice(to)}`;
                ta.selectionStart = ta.selectionEnd = from + 4;
                sync();
            }
        });
        // Assigning `value` leaves the caret at the end of the text, and
        // focusing then scrolls the whole document down to it. Put the caret on
        // the line the reader was looking at instead, so typing lands there and
        // not a screen away.
        const lines = content.split('\n');
        const line = Math.min(lines.length - 1, Math.round((ratio || 0) * lines.length));
        let offset = 0;
        for (let i = 0; i < line; i++) offset += lines[i].length + 1;
        ta.setSelectionRange(offset, offset);
        ta.focus();
        // After focus: focusing scrolls to the caret, which is only roughly
        // where the reader was.
        _docApplyScrollRatio(ta, ratio || 0);
        return ta;
    }

    /**
     * Write the text area back to disk.
     *
     * @param {object} [opts]
     * @param {boolean} [opts.keepEditing] - stay in the editor after saving.
     * @param {boolean} [opts.force] - save even though the file changed on disk.
     */
    async function save(opts) {
        const { keepEditing = false, force = false } = opts || {};
        const ta = textarea();
        if (!editing || !doc || !ta) return;
        // Ctrl+S bypasses the button's busy state, and a second save sent
        // before the first reply carries a stale mtime - which would come back
        // as a conflict against our own write.
        if (saving) return;
        // Writing an untouched file would bump its mtime for nothing.
        if (!force && !isDirty()) {
            if (!keepEditing) exit();
            return;
        }

        const target = doc;
        const content = ta.value;
        const btn = cfg.buttons()?.save;
        saving = true;
        btn?.classList.add('doc-btn-busy');
        try {
            const data = await cfg.write(target, content, force ? null : baseMtime);
            if (data.code === 'conflict') {
                showConfirmDialog({
                    title: t('ws_edit_conflict_title'),
                    message: t('ws_edit_conflict_msg'),
                    okText: t('ws_edit_overwrite'),
                    onConfirm: () => save({ keepEditing: keepEditing, force: true }),
                });
                return;
            }
            if (data.status !== 'success') throw new Error(data.message || 'save failed');

            baseline = content;
            baseMtime = data.mtime;
            target.content = content;
            _wsToast(t('ws_edit_saved'));
            if (keepEditing) sync();
            else exit();
        } catch (e) {
            _wsToast(`${t('ws_edit_save_failed')}: ${e.message}`);
        } finally {
            saving = false;
            btn?.classList.remove('doc-btn-busy');
        }
    }

    function cancel() {
        if (!editing) return;
        // Retry through exit() rather than through this function, which bails
        // out on the very flag the guard clears before retrying.
        if (!guard(exit)) return;
        exit();
    }

    /** Leave the editor and show the rendered document again. */
    function exit() {
        // Where the text area was left, so saving does not send the reader
        // back to the top of a document they were halfway down.
        const body = cfg.body();
        const ratio = _docScrollRatio(textarea() || body || document.body);
        editing = false;
        baseline = '';
        baseMtime = null;
        if (doc) cfg.render(doc);
        if (body) _docApplyScrollRatio(body, ratio);
        sync();
    }

    return {
        open: open,
        forget: forget,
        start: start,
        save: save,
        cancel: cancel,
        exit: exit,
        guard: guard,
        isDirty: isDirty,
        isEditing: () => editing,
        current: () => doc,
    };
}
