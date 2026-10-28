import { test, beforeEach, after } from 'node:test'
import assert from 'node:assert/strict'
import { build } from 'esbuild'
import { mkdtemp, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

// Resolve the desktop root from this file, so the suite runs from any cwd.
const desktopRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')

const storage = new Map([['cow_lang', 'en']])
globalThis.localStorage = { getItem: key => storage.get(key) ?? null, setItem: (key, value) => storage.set(key, value), removeItem: key => storage.delete(key) }
globalThis.window = { electronAPI: undefined, addEventListener() {}, matchMedia: () => ({ matches: false }) }
const dir = await mkdtemp(path.join(tmpdir(), 'cow-todo-tests-'))
const outfile = path.join(dir, 'fixture.mjs')
await build({
  stdin: { contents: `export { useTodoStore, todoScope, parseTodoSnapshot } from './src/renderer/src/store/todoStore';
export { useChatStore } from './src/renderer/src/store/chatStore';
export { useAgentStore } from './src/renderer/src/store/agentStore';
export { useSessionStore } from './src/renderer/src/store/sessionStore';
export { default as api } from './src/renderer/src/api/client';
export { default as TodoPanel } from './src/renderer/src/components/TodoPanel';
export { createElement } from 'react';
export { renderToStaticMarkup } from 'react-dom/server';`, resolveDir: desktopRoot },
  outfile, bundle: true, platform: 'node', format: 'esm', jsx: 'automatic',
  banner: { js: "import { createRequire } from 'node:module'; const require = createRequire(import.meta.url);" },
  alias: { '@product': path.join(desktopRoot, 'src/renderer/src/product/default') },
})
const { useTodoStore: todos, todoScope, parseTodoSnapshot, useChatStore: chat, useAgentStore: agents, useSessionStore: sessions, api, TodoPanel, createElement, renderToStaticMarkup } = await import(pathToFileURL(outfile))
after(() => rm(dir, { recursive: true, force: true }))
const snapshot = (version = 1, agent_id = 'primary', session_id = 's', items = [{ content: 'Task', status: 'pending' }]) => ({ version, agent_id, session_id, todos: items })
const page = (todo_snapshot, page = 1) => ({ messages: [], total: 0, page, page_size: 20, has_more: false, agent_id: todo_snapshot.agent_id, session_id: todo_snapshot.session_id, todo_snapshot })
const current = () => todos.getState().snapshots[todoScope('primary', 's')]
beforeEach(() => {
  todos.setState({ snapshots: {} })
  chat.getState().clearLocal('s')
  agents.setState({ agents: [{ id: 'primary', enabled: true }, { id: 'writer', enabled: true }], defaultAgentId: 'primary', activeAgentId: 'primary' })
  sessions.setState({ activeId: 's' })
})

test('versions reject retries and older snapshots; empty updates clear the list', () => {
  const apply = todos.getState().applySnapshot
  apply(snapshot(3), 'primary', 's')
  apply(snapshot(2), 'primary', 's')
  apply(snapshot(3, 'primary', 's', []), 'primary', 's')
  assert.equal(current().version, 3)
  assert.equal(current().todos.length, 1)
  apply(snapshot(4, 'primary', 's', []), 'primary', 's')
  assert.equal(current().todos.length, 0)
})

test('agents and sessions are isolated and invalid snapshots are rejected', () => {
  const apply = todos.getState().applySnapshot
  apply(snapshot(), 'primary', 's')
  apply(snapshot(5, 'writer'), 'writer', 's')
  apply(snapshot(6, 'primary', 'other'), 'primary', 'other')
  apply(snapshot(99, 'writer'), 'primary', 's')
  assert.equal(current().version, 1)
  assert.equal(Object.keys(todos.getState().snapshots).length, 3)
  assert.notEqual(todoScope('a:b', 'c'), todoScope('a', 'b:c'))
  for (const invalid of [null, {}, snapshot(0), snapshot(1.5), snapshot(1, 'primary', 's', [{ content: '', status: 'pending' }]), snapshot(1, 'primary', 's', [{ content: 'x', status: 'unknown' }])]) {
    assert.equal(parseTodoSnapshot(invalid, 'primary', 's'), null)
  }
})

test('only first history page restores plans and older history cannot replace live state', async () => {
  api.getHistory = async () => page(snapshot(2))
  assert.equal(await chat.getState().loadHistory('s'), true)
  api.getHistory = async () => page(snapshot(8), 2)
  await chat.getState().loadHistory('s', 2)
  assert.equal(current().version, 2)
  todos.getState().applySnapshot(snapshot(4), 'primary', 's')
  api.getHistory = async () => page(snapshot(3))
  await chat.getState().loadHistory('s')
  assert.equal(current().version, 4)
})

test('late history after deletion, newer requests or owner changes cannot restore state', async () => {
  let resolve
  api.getHistory = () => new Promise(r => { resolve = r })
  const deleted = chat.getState().loadHistory('s')
  chat.getState().clearLocal('s')
  resolve(page(snapshot(8)))
  assert.equal(await deleted, false)
  assert.equal(current(), undefined)
  const older = chat.getState().loadHistory('s')
  const finishOlder = resolve
  api.getHistory = async () => page(snapshot(2))
  await chat.getState().loadHistory('s')
  finishOlder(page(snapshot(9)))
  assert.equal(await older, false)
  assert.equal(current().version, 2)
  api.getHistory = () => new Promise(r => { resolve = r })
  const wrongOwner = chat.getState().loadHistory('s')
  agents.setState({ activeAgentId: 'writer' })
  resolve(page(snapshot(10)))
  assert.equal(await wrongOwner, false)
  assert.equal(current().version, 2)
})

test('panel is collapsed by default, splits title from progress and keeps accessible statuses', () => {
  storage.delete('cow_todo_panel_expanded')
  const data = snapshot(1, 'primary', 's', [{ content: 'A very long task', status: 'in_progress' }, { content: 'Done', status: 'completed' }])
  const html = renderToStaticMarkup(createElement(TodoPanel, { snapshot: data }))
  assert.match(html, /aria-expanded="false"/)
  assert.match(html, />Tasks</)
  // Empty states are omitted, so the untouched "pending" bucket never renders.
  assert.match(html, /1 Completed \u2002·\u2002 1 In progress/)
  assert.doesNotMatch(html, /Pending/)
  assert.match(html, /line-through/)
  assert.match(html, /sr-only/)
  assert.match(html, /overflow-y-auto/)
  assert.match(html, /overflow-wrap:anywhere/)
  storage.set('cow_todo_panel_expanded', '1')
  assert.match(renderToStaticMarkup(createElement(TodoPanel, { snapshot: data })), /aria-expanded="true"/)
  assert.equal(renderToStaticMarkup(createElement(TodoPanel, { snapshot: snapshot(2, 'primary', 's', []) })), '')
})


test('live send binds todo SSE to its original owner and rejects replay, mismatches and deleted callbacks', async () => {
  const es = { close() {} }
  api.sendMessage = async () => ({ status: 'success', stream: true, request_id: 'r-live' })
  api.createSSEStream = () => es
  await chat.getState().send('s', 'hello', [])
  const emit = value => es.onmessage({ data: JSON.stringify({ type: 'todo_update', ...value }) })
  emit({ version: 2, todos: [{ content: 'Live task', status: 'in_progress' }] })
  assert.equal(current().version, 2)
  emit(snapshot(1))
  emit(snapshot(2, 'primary', 's', []))
  emit(snapshot(9, 'writer'))
  emit(snapshot(9, 'primary', 'other'))
  assert.equal(current().version, 2)
  agents.setState({ activeAgentId: 'writer' })
  emit({ version: 10, todos: [] })
  assert.equal(current().version, 2)
  assert.equal(todos.getState().snapshots[todoScope('writer', 's')], undefined)
  chat.getState().clearLocal('s')
  emit(snapshot(11))
  es.onerror()
  assert.equal(current(), undefined)
  assert.deepEqual(chat.getState().getSession('s').messages, [])
})

test('send response and rejection arriving after deletion leave the session empty', async () => {
  let resolve
  let attached = false
  api.createSSEStream = () => { attached = true; return { close() {} } }
  api.sendMessage = () => new Promise(r => { resolve = r })
  const pending = chat.getState().send('s', 'hello', [])
  chat.getState().clearLocal('s')
  resolve({ status: 'success', stream: true, request_id: 'late' })
  await pending
  assert.equal(attached, false)
  assert.deepEqual(chat.getState().getSession('s').messages, [])
  let reject
  api.sendMessage = () => new Promise((_, r) => { reject = r })
  const failed = chat.getState().send('s', 'hello', [])
  chat.getState().clearLocal('s')
  const cleared = chat.getState().getSession('s')
  reject(new Error('late failure'))
  await failed
  assert.equal(chat.getState().getSession('s'), cleared)
  assert.deepEqual(chat.getState().getSession('s').messages, [])
  assert.equal(chat.getState().getSession('s').isStreaming, false)
})
