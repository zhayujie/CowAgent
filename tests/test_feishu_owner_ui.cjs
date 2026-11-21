const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const script = fs.readFileSync(path.join(__dirname, '../channel/web/static/js/views/channels-feishu.js'), 'utf8');

test('the Feishu scan targets the current instance and the server commits without a browser confirmation', async () => {
    const requests = [];
    let nextPoll;
    let refreshes = 0;
    const status = { closest: () => ({ dataset: { instanceId: 'feishu-existing' } }), querySelector: () => null };
    const ctx = vm.createContext({
        URLSearchParams,
        document: { getElementById: () => status },
        t: key => key,
        escapeHtml: value => value,
        setTimeout: callback => { nextPoll = callback; return 1; },
        clearTimeout() {},
        loadChannelsView: async () => { refreshes++; },
        fetch: async (url, options) => {
            requests.push({ url, body: options ? JSON.parse(options.body) : null });
            const payload = options
                ? { status: 'success', register_status: 'done', owner_bound: true, instance_id: 'feishu-existing' }
                : { status: 'success', registration_id: 'own-scan' };
            return { json: async () => payload };
        },
    });
    vm.runInContext(script, ctx);
    vm.runInContext('renderFeishuQr = () => {}; startFeishuRegister("status");', ctx);
    await new Promise(setImmediate);
    nextPoll();
    await new Promise(setImmediate);

    assert.deepEqual(requests, [
        { url: '/api/feishu/register?instance_id=feishu-existing&replace=0', body: null },
        { url: '/api/feishu/register', body: { action: 'poll', registration_id: 'own-scan' } },
    ]);
    assert.equal(refreshes, 1);
});

test('adopting an application owner adds one ID to the current form', async () => {
    const requests = [];
    const lookup = { classList: {} };
    const adopt = { classList: { add() {}, toggle() {} } };
    const status = {};
    const actions = {
        querySelector: () => status,
        querySelectorAll: () => [lookup, adopt],
    };
    const appId = { value: 'cli_one', addEventListener() {} };
    const owners = { value: 'ou_existing', after() {} };
    const content = {
        querySelector: () => ({ dataset: { masked: '1' }, addEventListener() {} }),
        contains: () => true,
    };
    const ctx = vm.createContext({
        appId, owners, content,
        document: { createElement: () => actions },
        t: key => key,
        escapeHtml: value => value,
        fetch: async (url, options) => {
            requests.push({ url, body: JSON.parse(options.body) });
            return { json: async () => ({ status: 'success', app_id: 'cli_one', owner_open_id: 'ou_app_owner' }) };
        },
    });
    vm.runInContext(script, ctx);
    vm.runInContext('bindFeishuOwnerLookup(content, appId, owners, "feishu-existing");', ctx);
    await lookup.onclick();
    assert.equal(owners.value, 'ou_existing');
    assert.equal(status.textContent, 'ou_app_owner');
    adopt.onclick();
    assert.equal(owners.value, 'ou_existing, ou_app_owner');
    assert.deepEqual(requests, [{
        url: '/api/channels',
        body: { action: 'lookup_owner', channel: 'feishu', instance_id: 'feishu-existing',
            config: { feishu_app_id: 'cli_one', feishu_app_secret: '' } },
    }]);
});
