/* Committed todo snapshots are scoped to an Agent/session pair, independent of runs. */
const webTodoSnapshots = new Map();
const webTodoDeleted = new Set();
const webTodoRevisions = new Map();
let webTodoExpanded = false;
try {
    webTodoExpanded = localStorage.getItem('cow_todo_expanded') === '1';
} catch (_) { /* Keep the default when browser storage is unavailable. */ }

function webTodoOwner() { return activeAgentId || defaultAgentId || ''; }
function webTodoKey(agent, sid) { return JSON.stringify([agent, sid]); }
function webTodoRevision(agent, sid) { return webTodoRevisions.get(webTodoKey(agent, sid)) || 0; }

function applyWebTodoSnapshot(value, agent, sid) {
    const key = webTodoKey(agent, sid);
    if (!agent || !sid || webTodoDeleted.has(key) || !value || typeof value !== 'object' ||
        value.agent_id !== agent || value.session_id !== sid ||
        !Number.isSafeInteger(value.version) || value.version < 1 || !Array.isArray(value.todos) ||
        !value.todos.every(item => item && typeof item.content === 'string' && item.content.trim() &&
            ['pending', 'in_progress', 'completed'].includes(item.status))) return false;
    if ((webTodoSnapshots.get(key)?.version || 0) >= value.version) return false;
    webTodoSnapshots.set(key, {
        version: value.version,
        todos: value.todos.map(item => ({ content: item.content, status: item.status })),
        explanation: typeof value.explanation === 'string' ? value.explanation : '',
    });
    webTodoRevisions.set(key, webTodoRevision(agent, sid) + 1);
    renderWebTodoPanel();
    return true;
}

function recoverWebTodoHistory(data, agent, sid, revision) {
    // A legacy/default owner can be resolved by history, but never by a foreign Agent.
    const owner = agent || defaultAgentId || data.agent_id;
    if (data.status !== 'success' || data.session_id !== sid || data.agent_id !== owner ||
        sid !== sessionId || (webTodoOwner() && webTodoOwner() !== owner)) return;
    const key = webTodoKey(owner, sid);
    if (webTodoDeleted.has(key)) return;
    if (data.todo_snapshot) applyWebTodoSnapshot(data.todo_snapshot, owner, sid);
    else if (webTodoRevision(owner, sid) === revision) {
        // An absent snapshot can clear cached state only if no live update arrived meanwhile.
        webTodoSnapshots.delete(key);
        renderWebTodoPanel();
    }
}

function deleteWebTodoSession(agent, sid) {
    const key = webTodoKey(agent || defaultAgentId || '', sid);
    webTodoDeleted.add(key);
    webTodoSnapshots.delete(key);
    webTodoRevisions.set(key, webTodoRevision(agent || defaultAgentId || '', sid) + 1);
    renderWebTodoPanel();
}

function toggleWebTodoPanel() {
    webTodoExpanded = !webTodoExpanded;
    try {
        localStorage.setItem('cow_todo_expanded', webTodoExpanded ? '1' : '0');
    } catch (_) { /* Toggling still works without persisting the preference. */ }
    renderWebTodoPanel();
}

function renderWebTodoPanel() {
    const panel = document.getElementById('todo-panel');
    if (!panel) return;
    const snapshot = webTodoSnapshots.get(webTodoKey(webTodoOwner(), sessionId));
    panel.hidden = !snapshot?.todos.length;
    if (panel.hidden) return;
    const counts = { pending: 0, in_progress: 0, completed: 0 };
    snapshot.todos.forEach(item => counts[item.status]++);
    document.getElementById('todo-title').textContent = t('todo_title');
    // Zero-count states are left out: a status nobody is in is noise, not data.
    const summary = document.getElementById('todo-summary');
    summary.textContent = [
        counts.completed > 0 ? counts.completed + ' ' + t('todo_completed') : '',
        counts.in_progress > 0 ? counts.in_progress + ' ' + t('todo_in_progress') : '',
        counts.pending > 0 ? counts.pending + ' ' + t('todo_pending') : '',
    ].filter(Boolean).join(' \u2002·\u2002 ');
    const toggle = document.getElementById('todo-toggle');
    toggle.setAttribute('aria-expanded', String(webTodoExpanded));
    document.getElementById('todo-chevron').className = 'fas fa-chevron-' + (webTodoExpanded ? 'down' : 'up');
    const body = document.getElementById('todo-body');
    body.hidden = !webTodoExpanded;
    const list = document.getElementById('todo-list');
    list.replaceChildren();
    snapshot.todos.forEach(item => {
        const row = document.createElement('li');
        row.className = 'todo-row todo-' + item.status;
        const mark = document.createElement('i');
        mark.className = 'fas ' + ({ pending: 'fa-circle', in_progress: 'fa-circle-notch fa-spin', completed: 'fa-circle-check' }[item.status]);
        mark.setAttribute('aria-label', t('todo_' + item.status));
        const text = document.createElement('span');
        text.textContent = item.content;
        row.append(mark, text);
        list.appendChild(row);
    });
    const explanation = document.getElementById('todo-explanation');
    explanation.textContent = snapshot.explanation;
    explanation.hidden = !snapshot.explanation;
}
