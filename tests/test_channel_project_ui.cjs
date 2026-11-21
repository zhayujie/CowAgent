// Run with: node --test tests/test_channel_project_ui.cjs
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

function environment() {
    const elements = new Map();
    const document = { addEventListener() {}, getElementById(id) {
        if (!elements.has(id)) elements.set(id, {
            classList: { add() {}, remove() {}, toggle() {} },
            handlers: {},
            addEventListener(event, fn) { this.handlers[event] = fn; },
            removeEventListener(event, fn) { if (this.handlers[event] === fn) delete this.handlers[event]; },
        });
        return elements.get(id);
    }};
    const ctx = vm.createContext({ document, t: key => key, _wsSelHide() {} });
    for (const name of ['core/confirm.js', 'chat/workspace-selector.js']) {
        vm.runInContext(fs.readFileSync(path.join(__dirname, '../channel/web/static/js', name), 'utf8'), ctx);
    }
    return { ctx, element: document.getElementById };
}

test('confirm settles cancel, overlay dismissal, and save exactly once', () => {
    const { ctx, element } = environment();
    let confirmed = 0, cancelled = 0;
    const open = () => ctx.showConfirmDialog({onConfirm: () => confirmed++, onCancel: () => cancelled++});
    open();
    element('confirm-dialog-cancel').handlers.click();
    assert.equal(cancelled, 1);
    assert.equal(element('confirm-dialog-ok').handlers.click, undefined);
    open();
    const overlay = element('confirm-dialog-overlay');
    overlay.handlers.click({ target: overlay });
    assert.equal(cancelled, 2);
    open();
    element('confirm-dialog-ok').handlers.click();
    assert.equal(confirmed, 1);
    assert.equal(cancelled, 2);
});

test('folder picker sends selection to channel callback and clears it on dismissal', async () => {
    const { ctx, element } = environment();
    vm.runInContext('_fpBrowse = () => {};', ctx);
    let selected = '';
    ctx.openServerFolderPicker(value => { selected = value; });
    vm.runInContext("_fpCurrent = 'D:/projects/backend';", ctx);
    await element('folder-picker-open').handlers.click();
    assert.equal(selected, 'D:/projects/backend');
    assert.equal(vm.runInContext('_fpSelectCallback', ctx), null);
    ctx.openServerFolderPicker(() => assert.fail('cancelled callback must not run'));
    element('folder-picker-cancel').handlers.click();
    assert.equal(vm.runInContext('_fpSelectCallback', ctx), null);
});
