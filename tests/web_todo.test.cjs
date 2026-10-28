const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const root = path.join(__dirname, '..');
function element() {
    return { hidden: false, textContent: '', children: [], attributes: {},
        setAttribute(k, v) { this.attributes[k] = v; },
        append(...children) { this.children.push(...children); },
        appendChild(child) { this.children.push(child); },
        replaceChildren() { this.children = []; } };
}
const nodes = Object.fromEntries(['todo-panel', 'todo-title', 'todo-summary', 'todo-toggle', 'todo-chevron', 'todo-body', 'todo-list', 'todo-explanation'].map(id => [id, element()]));
const storage = new Map();
const streams = [];
const labels = { todo_title: 'T', todo_completed: 'C', todo_in_progress: 'P', todo_pending: 'N' };
const ctx = vm.createContext({ console, document: { getElementById: id => nodes[id], createElement: element },
    localStorage: { getItem: k => storage.get(k), setItem: (k, v) => storage.set(k, v) },
    activeAgentId: 'a', defaultAgentId: 'a', sessionId: 's', t: k => labels[k] || k,
    runtimeSessionKey: (sid, agent) => JSON.stringify([agent, sid]), sessionActiveRequest: {}, streamBuffers: {}, activeStreams: {},
    updateEditButtonsState() {}, EventSource: class { constructor() { streams.push(this); } close() {} },
});
function run(code) { return vm.runInContext(code, ctx); }
for (const file of ['todo.js', 'send.js']) run(fs.readFileSync(path.join(root, 'channel/web/static/js/chat', file), 'utf8'));
function snapshot(version, agent = 'a', sid = 's', todos = [{ content: '<img src=x onerror=evil()>', status: 'in_progress' }]) {
    return { agent_id: agent, session_id: sid, version, todos, explanation: '<script>evil()</script>' };
}
ctx.snap = snapshot(2);
assert.equal(run('applyWebTodoSnapshot(snap, "a", "s")'), true);
assert.equal(nodes['todo-body'].hidden, true);
assert.equal(nodes['todo-list'].children[0].children[1].textContent, ctx.snap.todos[0].content);
assert.equal(nodes['todo-explanation'].textContent, ctx.snap.explanation);
assert.equal(nodes['todo-title'].textContent, 'T');
// Zero-count states are omitted: only the one in-progress task reports.
assert.equal(nodes['todo-summary'].textContent, '1 P');
run('toggleWebTodoPanel()');
assert.equal(storage.get('cow_todo_expanded'), '1');
assert.equal(nodes['todo-body'].hidden, false);
ctx.snap = snapshot(1);
assert.equal(run('applyWebTodoSnapshot(snap, "a", "s")'), false);
ctx.snap = snapshot(2);
assert.equal(run('applyWebTodoSnapshot(snap, "a", "s")'), false);
ctx.snap = snapshot(3, 'b');
assert.equal(run('applyWebTodoSnapshot(snap, "a", "s")'), false);
ctx.snap = snapshot(3, 'a', 's', []);
run('applyWebTodoSnapshot(snap, "a", "s")');
assert.equal(nodes['todo-panel'].hidden, true);
// History loaded before live updates cannot replace them, including a null snapshot.
ctx.data = { status: 'success', agent_id: 'a', session_id: 's', todo_snapshot: null };
run('recoverWebTodoHistory(data, "a", "s", 0)');
assert.equal(run('webTodoSnapshots.get(webTodoKey("a", "s")).version'), 3);
ctx.data.todo_snapshot = snapshot(2);
run('recoverWebTodoHistory(data, "a", "s", 0)');
assert.equal(run('webTodoSnapshots.get(webTodoKey("a", "s")).version'), 3);
// Real live SSE must cache background updates without painting the current scope.
run('startSSE("r", null, new Date())');
ctx.sessionId = 'other';
streams[0].onmessage({ data: JSON.stringify({ type: 'todo_update', seq: 1, ...snapshot(4) }) });
assert.equal(run('webTodoSnapshots.get(webTodoKey("a", "s")).version'), 4);
assert.equal(nodes['todo-panel'].hidden, true);
ctx.sessionId = 's'; ctx.activeAgentId = 'b';
run('renderWebTodoPanel()');
assert.equal(nodes['todo-panel'].hidden, true);
ctx.snap = snapshot(1, 'b');
run('applyWebTodoSnapshot(snap, "b", "s")');
assert.equal(nodes['todo-panel'].hidden, false);
// Deleting one Agent's same-named session cannot erase another Agent's state.
run('deleteWebTodoSession("a", "s")');
assert.equal(nodes['todo-panel'].hidden, false);
streams[0].onmessage({ data: JSON.stringify({ type: 'todo_update', seq: 2, ...snapshot(5) }) });
ctx.activeAgentId = 'a';
ctx.data.todo_snapshot = snapshot(9);
run('recoverWebTodoHistory(data, "a", "s", webTodoRevision("a", "s")); renderWebTodoPanel()');
assert.equal(nodes['todo-panel'].hidden, true);
assert.equal(run('webTodoSnapshots.has(webTodoKey("a", "s"))'), false);
// Recover a todo-only session even when message history is empty.
ctx.sessionId = 'fresh';
ctx.data = { status: 'success', agent_id: 'a', session_id: 'fresh', messages: [], todo_snapshot: snapshot(1, 'a', 'fresh') };
run('recoverWebTodoHistory(data, "a", "fresh", 0)');
assert.equal(nodes['todo-panel'].hidden, false);
console.log('Web todo state, rendering, history races and live background SSE passed');
