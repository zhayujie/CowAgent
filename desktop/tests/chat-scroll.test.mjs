import { test } from 'node:test'
import assert from 'node:assert/strict'
import { build } from 'esbuild'
import { mkdtemp, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const dir = await mkdtemp(path.join(tmpdir(), 'cow-chat-scroll-'))
const outfile = path.join(dir, 'scroll.mjs')
await build({
  stdin: { contents: `export { followingAfterUserScroll, shouldApplyBottomScroll, shouldFollowContentChange, shouldShowScrollToBottom, distanceFromBottom } from './src/renderer/src/lib/chatScroll.ts';`, resolveDir: path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..') },
  outfile, bundle: true, platform: 'node', format: 'esm',
})
const { followingAfterUserScroll, shouldApplyBottomScroll, shouldFollowContentChange, shouldShowScrollToBottom, distanceFromBottom } = await import(pathToFileURL(outfile))
test.after(() => rm(dir, { recursive: true, force: true }))

const metrics = (scrollTop, scrollHeight = 1000, clientHeight = 200) => ({ scrollTop, scrollHeight, clientHeight })

test('programmatic/layout scroll does not change the explicit follow intent', () => {
  assert.equal(followingAfterUserScroll(true, null, metrics(500)), true)
  assert.equal(followingAfterUserScroll(false, null, metrics(950)), false)
})

test('user upward intent pauses following even while still near the bottom', () => {
  assert.equal(distanceFromBottom(metrics(760)), 40)
  assert.equal(followingAfterUserScroll(true, 'up', metrics(760)), false)
  assert.equal(shouldShowScrollToBottom(false, metrics(760)), false)
  assert.equal(shouldShowScrollToBottom(false, metrics(700)), true)
})

test('user downward intent resumes only after returning within the bottom threshold', () => {
  assert.equal(followingAfterUserScroll(false, 'down', metrics(700)), false)
  assert.equal(followingAfterUserScroll(false, 'down', metrics(760)), true)
})

test('todo, input and message growth follow only while the reader has not detached', () => {
  assert.equal(shouldFollowContentChange(true, false), true)
  assert.equal(shouldFollowContentChange(false, false), false)
  assert.equal(shouldFollowContentChange(true, true), false)
})

test('queued bottom work is rejected after user pause, timeline jump or session switch', () => {
  const base = { following: true, jumping: false, currentSession: 'a', scheduledSession: 'a' }
  assert.equal(shouldApplyBottomScroll(base), true)
  assert.equal(shouldApplyBottomScroll({ ...base, following: false }), false)
  assert.equal(shouldApplyBottomScroll({ ...base, jumping: true }), false)
  assert.equal(shouldApplyBottomScroll({ ...base, currentSession: 'b' }), false)
})
