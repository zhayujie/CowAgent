const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

const ROOT = path.join(__dirname, '..');

function setup() {
    const frames = new Map();
    let nextId = 0;
    let top = 900;
    let writes = 0;
    let onScroll;
    let onResize;
    const listeners = {};
    const historyLoads = [];
    const classes = new Set(['hidden']);
    const button = { classList: { toggle(name, hidden) { if (hidden) classes.add(name); else classes.delete(name); }, contains(name) { return classes.has(name); } } };
    const box = {
        scrollHeight: 1000, clientHeight: 100, clientWidth: 600,
        get scrollTop() { return top; },
        getBoundingClientRect() { return { right: 600 }; },
        set scrollTop(value) { writes++; top = Math.max(0, Math.min(value, this.scrollHeight - this.clientHeight)); },
        addEventListener(name, callback) { listeners[name] = callback; if (name === 'scroll') onScroll = callback; },
    };
    const context = vm.createContext({
        messagesDiv: box,
        document: { getElementById(id) { return id === 'scroll-to-bottom-btn' ? button : null; } },
        requestAnimationFrame(callback) { frames.set(++nextId, callback); return nextId; },
        cancelAnimationFrame(id) { frames.delete(id); },
        ResizeObserver: class { constructor(callback) { onResize = callback; } observe() {} },
        historyHasMore: false, historyLoading: false, historyPage: 0,
        loadHistory(page) { historyLoads.push(page); context.historyLoading = true; },
    });
    const utils = fs.readFileSync(path.join(ROOT, 'channel/web/static/js/core/utils.js'), 'utf8');
    const state = fs.readFileSync(path.join(ROOT, 'channel/web/static/js/chat/state.js'), 'utf8');
    vm.runInContext(utils.slice(utils.indexOf('let _scrollRafId'), utils.indexOf('function applyHighlighting')), context);
    vm.runInContext(state.slice(state.indexOf('let _autoScrollEnabled'), state.indexOf('// Intercept internal navigation')), context);
    const render = fs.readFileSync(path.join(ROOT, 'channel/web/static/js/chat/render.js'), 'utf8');
    vm.runInContext(render.slice(render.indexOf('let historyPinToken'), render.indexOf('// Load conversation history')), context);
    return {
        box, frames, button, classes, listeners, historyLoads, run: code => vm.runInContext(code, context),
        flush() { const batch = [...frames.values()]; frames.clear(); batch.forEach(callback => callback()); },
        scroll(value, intent = null) {
            top = value;
            if (intent === 'up') listeners.wheel({ deltaY: -1 });
            else if (intent === 'down') listeners.wheel({ deltaY: 1 });
            else if (intent === 'scrollbar') listeners.pointerdown({ target: box, clientX: 600 });
            onScroll();
        },
        touch(startY, endY, flush = false) {
            listeners.touchstart({ touches: [{ clientY: startY }] });
            listeners.touchmove({ touches: [{ clientY: endY }] });
            if (flush) this.flush();
            listeners.touchend();
        },
        resize() { onResize(); }, writes: () => writes,
    };
}

test('already at bottom does not suppress the next upward gesture', () => {
    const s = setup();
    s.run('scrollChatToBottom(true)');
    assert.equal(s.run('_programmaticScroll'), false);
    assert.equal(s.writes(), 0);
    s.scroll(880, 'up');
    assert.equal(s.run('_autoScrollEnabled'), false);
});

test('stream updates coalesce and queued scrolling respects a later user pause', () => {
    const s = setup();
    s.scroll(900); // establish the current position as the browser scroll event does
    s.run('scrollChatToBottom(); scrollChatToBottom(); scrollChatToBottom()');
    assert.equal(s.frames.size, 1);
    s.scroll(700, 'up');
    s.flush();
    assert.equal(s.box.scrollTop, 700);
    assert.equal(s.writes(), 0);
});

test('force cancels queued work and reaches the current bottom immediately', () => {
    const s = setup();
    s.box.scrollHeight = 1200;
    s.run('scrollChatToBottom(); scrollChatToBottom(true)');
    assert.equal(s.frames.size, 0);
    assert.equal(s.box.scrollTop, 1100);
    assert.equal(s.run('_lastScrollTop'), 1100);
});

test('viewport shrink follows the bottom; history reading survives viewport resizing', () => {
    const s = setup();
    s.box.clientHeight = 50;
    s.resize();
    s.flush();
    assert.equal(s.box.scrollTop, 950);
    s.scroll(950); // consume our programmatic scroll event
    s.scroll(600, 'up');
    s.box.clientHeight = 80;
    s.resize();
    assert.equal(s.frames.size, 0);
    assert.equal(s.box.scrollTop, 600);
    assert.equal(s.run('_autoScrollEnabled'), false);
});

test('short conversations clamp the bottom to zero', () => {
    const s = setup();
    s.box.scrollHeight = 50;
    s.box.clientHeight = 100;
    s.run('scrollChatToBottom(true)');
    assert.equal(s.box.scrollTop, 0);
});

test('touch dragging pauses follow before the stream frame runs', () => {
    const s = setup();
    s.run('scrollChatToBottom();');
    assert.equal(s.frames.size, 1);
    s.touch(300, 340, false);
    assert.equal(s.run('_autoScrollEnabled'), false);
    assert.equal(s.frames.size, 0);
    s.flush();
    assert.equal(s.box.scrollTop, 900);
});

test('tap without movement keeps follow enabled', () => {
    const s = setup();
    s.touch(300, 300);
    assert.equal(s.run('_autoScrollEnabled'), true);
});

test('programmatic scroll events preserve follow intent and button reflects detached reading', () => {
    const s = setup();
    s.box.scrollHeight = 1400;
    s.run('scrollChatToBottom(true)');
    assert.equal(s.run('_autoScrollEnabled'), true);
    s.scroll(700, 'up');
    assert.equal(s.run('_autoScrollEnabled'), false);
    assert.equal(s.classes.has('hidden'), false);
    s.box.scrollHeight += 300;
    s.run('_updateScrollToBottomBtn()');
    assert.equal(s.classes.has('hidden'), false);
    s.run('_lastScrollTop = 700');
    s.box.clientHeight = 300;
    s.scroll(1400, 'down');
    assert.equal(s.run('_autoScrollEnabled'), true);
    s.run('_updateScrollToBottomBtn()');
    assert.equal(s.classes.has('hidden'), true);
});

test('scrolling up near the top loads the next history page once', () => {
    const s = setup();
    s.run('historyHasMore = true; historyPage = 1');
    s.scroll(500, 'up');
    assert.deepEqual(s.historyLoads, []);
    s.scroll(150, 'up');
    assert.deepEqual(s.historyLoads, [2]);
    s.scroll(50, 'up');
    assert.deepEqual(s.historyLoads, [2]);
    s.run('historyLoading = false; historyPage = 2');
    s.scroll(100, 'up');
    assert.deepEqual(s.historyLoads, [2, 3]);
});

test('programmatic scrolls near the top and exhausted history never load pages', () => {
    const s = setup();
    s.run('historyHasMore = true; historyPage = 1');
    s.scroll(0);
    assert.deepEqual(s.historyLoads, []);
    s.run('historyHasMore = false');
    s.scroll(0, 'up');
    s.touch(300, 340);
    assert.deepEqual(s.historyLoads, []);
});

test('switching sessions drops the previous reader position and follows the new bottom', () => {
    const s = setup();
    s.scroll(600, 'up');
    assert.equal(s.run('_autoScrollEnabled'), false);
    s.run('const pin = historyPinToken; resetChatScrollForSession(); globalThis.pinBumped = historyPinToken !== pin');
    assert.equal(s.run('pinBumped'), true);
    assert.equal(s.run('_autoScrollEnabled'), true);
    assert.equal(s.classes.has('hidden'), true);
    s.box.scrollTop = 0;
    s.box.scrollHeight = 1500;
    s.run('scrollChatToBottom()');
    s.flush();
    assert.equal(s.box.scrollTop, 1400);
});

test('composer viewport resize follows only while enabled and keeps the return button clickable', () => {
    const s = setup();
    s.run('_autoScrollEnabled = false');
    s.box.scrollTop = 700;
    s.box.clientHeight = 50;
    s.resize();
    s.flush();
    assert.equal(s.box.scrollTop, 700);
    assert.equal(s.classes.has('hidden'), false);
    s.run('scrollChatToBottom(true)');
    assert.equal(s.box.scrollTop, 950);
    assert.equal(s.run('_autoScrollEnabled'), true);
});
