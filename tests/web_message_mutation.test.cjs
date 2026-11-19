const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const ROOT = path.join(__dirname, '..');

// Follow web_scroll.test.cjs: exercise the actual classic-script consumers
// with controlled browser collaborators and deferred persistence responses.
function setup({ active = false, persisted = true } = {}) {
    const events = [], requests = [], alerts = [], nodes = [];
    let click, confirm, resolveDelete, rejectDelete;
    const deletion = new Promise((resolve, reject) => { resolveDelete = resolve; rejectDelete = reject; });
    const box = {
        removeChild(item) { events.push(`remove:${item.dataset.seq || item.role}`); nodes.splice(nodes.indexOf(item), 1); },
        addEventListener(name, callback) { if (name === 'click') click = callback; },
    };
    function node(role, seq, content) {
        const item = {
            role, dataset: { rawContent: content },
            classList: { contains(name) { return name === `${role}-message-group`; } },
            get parentNode() { return nodes.includes(item) ? box : null; },
            get nextElementSibling() { return nodes[nodes.indexOf(item) + 1] || null; },
            get previousElementSibling() { return nodes[nodes.indexOf(item) - 1] || null; },
            remove() { if (item.parentNode) box.removeChild(item); },
        };
        if (seq != null) item.dataset.seq = String(seq);
        nodes.push(item);
        return item;
    }
    const first = node('user', persisted ? 1 : null, 'First question');
    const answer = node('bot', persisted ? 2 : null, 'First answer');
    node('user', 3, 'Later question'); node('bot', 4, 'Later answer');
    const input = { value: 'Unsent draft', dispatchEvent() {}, focus() {} };
    const context = vm.createContext({
        messagesDiv: box, chatInput: input, sessionId: 'owned-session', currentLang: 'en',
        isCurrentSessionConversationActive: () => active,
        t: key => key, alert: message => alerts.push(message),
        console: { log() {}, warn() {}, error() {} }, Event: class {},
        fetch(url, options) {
            requests.push({ url, body: JSON.parse(options.body) });
            if (url === '/api/messages/delete') {
                events.push('delete:request');
                return deletion.then(response => { events.push('delete:response'); return response; });
            }
            assert.equal(url, '/message'); events.push('regenerate:send');
            return Promise.resolve({ json: async () => ({ status: 'success', inline_reply: 'Fresh answer' }) });
        },
        showConfirmModal(_title, _message, callback) { confirm = callback; },
        refreshTimeline() { events.push('timeline:refresh'); }, scrollChatToBottom() {},
        addUserMessage(content) { events.push('user:add'); node('user', null, content); },
        addBotMessage() { events.push('bot:add'); }, addLoadingIndicator() { return { remove() {} }; },
        addressedAgentId: () => '', rememberLiveSpeaker() {}, setLoadingSpeaker() {},
        loadingContainers: {}, Date, setTimeout,
    });
    const source = name => fs.readFileSync(path.join(ROOT, 'channel/web/static/js/chat', name), 'utf8');
    vm.runInContext(source('message-actions.js'), context);
    vm.runInContext(source('send.js'), context);
    const state = source('state.js');
    vm.runInContext(state.slice(state.indexOf('// Intercept internal navigation links'), state.indexOf('const attachmentPreview')), context);
    function deleteClick() {
        const button = { closest(selector) { return selector === '.user-message-group' ? first : null; } };
        click({ preventDefault() {}, target: { closest(selector) { return selector === '.delete-msg-btn' ? button : null; } } });
    }
    return {
        nodes, requests, alerts, events, input,
        ids: () => nodes.filter(item => item.dataset.seq).map(item => item.dataset.seq),
        start(action) {
            if (action === 'edit') return context.editUserMessage(first);
            if (action === 'regenerate') return context.regenerateResponse(answer);
            deleteClick(); return confirm ? confirm() : Promise.resolve();
        },
        cancelDelete() { deleteClick(); },
        respond(body = { status: 'success', deleted: 2 }, ok = true) {
            resolveDelete({ ok, status: ok ? 200 : 500, json: async () => body });
        },
        invalidJson() { resolveDelete({ ok: true, json: async () => { throw new SyntaxError('Invalid JSON'); } }); },
        networkError() { rejectDelete(new Error('Connection lost')); },
    };
}
const settle = () => new Promise(resolve => setImmediate(resolve));

for (const action of ['edit', 'regenerate', 'delete']) {
    for (const failure of ['api-error', 'network-error', 'invalid-json', 'http-error']) {
        test(`${action}: ${failure} preserves history and draft without a new send`, async () => {
            const s = setup(), operation = s.start(action);
            await settle();
            assert.deepEqual(s.ids(), ['1', '2', '3', '4'], 'wait for persistence before removing a turn');
            assert.equal(s.input.value, 'Unsent draft');
            assert.equal(s.requests.filter(r => r.url === '/message').length, 0);
            if (failure === 'network-error') s.networkError();
            else if (failure === 'invalid-json') s.invalidJson();
            else if (failure === 'http-error') s.respond({ status: 'success' }, false);
            else s.respond({ status: 'error', message: 'Store failed' });
            await operation; await settle();
            assert.deepEqual(s.ids(), ['1', '2', '3', '4']);
            assert.equal(s.input.value, 'Unsent draft');
            assert.deepEqual(s.alerts, ['records_delete_failed']);
            assert.equal(s.requests.filter(r => r.url === '/message').length, 0);
            assert.equal(s.events.includes('timeline:refresh'), false);
        });
    }
    test(`${action}: acknowledgment preserves the existing successful mutation`, async () => {
        const s = setup(), operation = s.start(action);
        await settle(); assert.deepEqual(s.ids(), ['1', '2', '3', '4']);
        s.respond(); await operation; await settle();
        const expected = { session_id: 'owned-session', user_seq: 1 };
        if (action !== 'delete') expected.delete_user = true;
        if (action === 'edit') expected.cascade = true;
        assert.deepEqual(s.requests[0], { url: '/api/messages/delete', body: expected });
        assert.deepEqual(s.ids(), action === 'edit' ? [] : ['3', '4']);
        const removed = s.events.findIndex(event => event.startsWith('remove:'));
        assert.ok(removed > s.events.indexOf('delete:response'));
        assert.deepEqual(s.alerts, []);
        assert.equal(s.input.value, action === 'edit' ? 'First question' : 'Unsent draft');
        const sends = s.requests.filter(r => r.url === '/message');
        assert.equal(sends.length, action === 'regenerate' ? 1 : 0);
        if (sends.length) assert.equal(sends[0].body.message, 'First question');
        if (action === 'delete') assert.ok(s.events.indexOf('timeline:refresh') > removed);
    });
}

test('canceling direct Delete does not submit or change the conversation', () => {
    const s = setup(); s.cancelDelete();
    assert.deepEqual(s.requests, []); assert.deepEqual(s.ids(), ['1', '2', '3', '4']);
    assert.equal(s.input.value, 'Unsent draft');
});
test('active reply still blocks Edit and direct Delete', async () => {
    for (const action of ['edit', 'delete']) {
        const s = setup({ active: true }); await s.start(action);
        assert.deepEqual(s.requests, []); assert.deepEqual(s.ids(), ['1', '2', '3', '4']);
    }
});
for (const action of ['edit', 'regenerate', 'delete']) {
    test(`${action}: nonpersisted turns still work without a deletion request`, async () => {
        const s = setup({ persisted: false }); await s.start(action); await settle();
        assert.equal(s.requests.filter(r => r.url === '/api/messages/delete').length, 0);
        assert.deepEqual(s.ids(), action === 'edit' ? [] : ['3', '4']); assert.deepEqual(s.alerts, []);
        if (action === 'delete') assert.equal(s.events.includes('timeline:refresh'), false);
    });
}
