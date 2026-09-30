/**
 * Check the console's script load order for hazards a bundler would catch.
 *
 *   node channel/web/tools/check-load-order.mjs
 *
 * The console is plain classic scripts sharing one global scope, loaded in the
 * order chat.html lists them. Nothing validates that order, and two mistakes
 * in it fail only in a browser, on a page that looks fine to every static
 * search:
 *
 *  1. Reaching a `let`/`const` declared in a later script. This throws, and
 *     because it throws partway through a top-level script, every declaration
 *     below it never runs - those bindings stay in their temporal dead zone
 *     for the life of the page, so the damage spreads well past the one line.
 *     The reference does not have to be visible in the statement: it counts if
 *     any function the statement calls reaches it, however deep.
 *  2. Reordering two scripts that both wrap the same thing, `window.fetch`
 *     being the live case. Both orders "work" while quietly changing which
 *     wrapper sees the untouched arguments.
 *
 * Findings are printed with the load positions involved; the exit code is 1 if
 * anything is reported. Anything genuinely intentional belongs in an assertion
 * in tests/test_web_console_assets.py, with the reason.
 */
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

const HERE = dirname(fileURLToPath(import.meta.url))
const ROOT = resolve(HERE, '../../..')

let ts
try {
  // Borrowed from the desktop app's toolchain: this check is a development
  // aid, not part of running the console, so it is not worth a dependency of
  // its own.
  ts = createRequire(import.meta.url)(
    resolve(ROOT, 'desktop/node_modules/typescript/lib/typescript.js'))
} catch {
  console.error('needs the TypeScript parser: run `npm install` in desktop/ first')
  process.exit(2)
}

const WEB = resolve(ROOT, 'channel/web')
const STATIC = resolve(WEB, 'static')

const shell = readFileSync(resolve(WEB, 'chat.html'), 'utf8')
  .replace(/<!--#include ([^\s>]+?)\s*-->/g, (_, p) => readFileSync(resolve(WEB, p), 'utf8'))
const scripts = [...shell.matchAll(/<script defer src="\/?assets\/(js\/[^"?]+)"/g)].map((m) => m[1])
if (!scripts.length) {
  // A pattern that matches nothing would report every order as consistent.
  console.error('no <script defer src="/assets/js/..."> tags found in chat.html')
  process.exit(2)
}

const isFn = (n) => ts.isFunctionExpression(n) || ts.isArrowFunction(n) ||
  ts.isFunctionDeclaration(n) || ts.isMethodDeclaration(n)

// A callback handed to one of these has run by the time the statement
// finishes, so its body executes now. addEventListener, setTimeout and promise
// handlers do not, and following those would report the whole program.
const SYNC_CALLBACKS = new Set([
  'forEach', 'map', 'filter', 'find', 'findIndex', 'some', 'every',
  'reduce', 'flatMap', 'sort',
])

function runsImmediately(fn) {
  const p = fn.parent
  if (!p) return false
  if (ts.isCallExpression(p) && p.expression === fn) return true
  if (ts.isParenthesizedExpression(p) && p.parent &&
      ts.isCallExpression(p.parent) && p.parent.expression === p) return true
  return ts.isCallExpression(p) && p.arguments.includes(fn) &&
    ts.isPropertyAccessExpression(p.expression) &&
    SYNC_CALLBACKS.has(p.expression.name.text)
}

function freeIdentifier(n) {
  const p = n.parent
  if (!p) return true
  return !((ts.isPropertyAccessExpression(p) && p.name === n) ||
    (ts.isPropertyAssignment(p) && p.name === n) ||
    (ts.isBindingElement(p) && p.propertyName === n))
}

// Names a node calls vs. merely mentions. `window.foo = foo` only stores a
// reference; following it would drag in everything foo could ever touch.
function classify(node, onlyImmediate) {
  const called = new Set()
  const read = new Set()
  const walk = (n) => {
    if (onlyImmediate && isFn(n) && !runsImmediately(n)) return
    if (ts.isIdentifier(n)) {
      if (!freeIdentifier(n)) return
      const p = n.parent
      if (p && ts.isCallExpression(p) && p.expression === n) called.add(n.text)
      else read.add(n.text)
      return
    }
    ts.forEachChild(n, walk)
  }
  ts.forEachChild(node, walk)
  return { called, read }
}

const decls = new Map()
const files = []
scripts.forEach((script, order) => {
  const text = readFileSync(resolve(STATIC, script), 'utf8')
  const sf = ts.createSourceFile(script, text, ts.ScriptTarget.ES2022, true, ts.ScriptKind.JS)
  files.push({ script, order, sf })
  const lineOf = (n) => sf.getLineAndCharacterOfPosition(n.getStart(sf)).line + 1
  const add = (name, kind, node) => {
    if (!name) return
    if (ts.isIdentifier(name)) {
      if (!decls.has(name.text)) {
        decls.set(name.text, { script, order, line: lineOf(node), kind, node })
      }
    } else if (ts.isObjectBindingPattern(name) || ts.isArrayBindingPattern(name)) {
      for (const el of name.elements) if (el.name) add(el.name, kind, node)
    }
  }
  for (const st of sf.statements) {
    if (ts.isFunctionDeclaration(st)) add(st.name, 'function', st)
    else if (ts.isClassDeclaration(st)) add(st.name, 'class', st)
    else if (ts.isVariableStatement(st)) {
      const f = st.declarationList.flags
      const kind = f & ts.NodeFlags.Const ? 'const' : f & ts.NodeFlags.Let ? 'let' : 'var'
      for (const d of st.declarationList.declarations) add(d.name, kind, st)
    }
  }
})

const bodyCache = new Map()
function bodyRefs(name) {
  if (bodyCache.has(name)) return bodyCache.get(name)
  const empty = { called: new Set(), read: new Set() }
  bodyCache.set(name, empty)
  const d = decls.get(name)
  if (!d || d.kind !== 'function') return empty
  const refs = classify(d.node, true)
  bodyCache.set(name, refs)
  return refs
}

// A call behind a `typeof` probe does not happen when the target has not
// loaded, so neither does anything underneath it. Stop at the probe rather
// than reporting the entire subtree it guards.
function guarded(name, order) {
  const d = decls.get(name)
  return d && d.kind === 'function' && d.order > order && probed.has(name)
}

function reachable(stmt, order) {
  const { called, read } = classify(stmt, true)
  const touched = new Set([...read])
  const followed = new Set()
  const queue = []
  for (const c of called) {
    touched.add(c)
    if (!guarded(c, order)) queue.push(c)
  }
  while (queue.length) {
    const name = queue.pop()
    if (followed.has(name)) continue
    followed.add(name)
    const refs = bodyRefs(name)
    for (const r of refs.read) touched.add(r)
    for (const c of refs.called) {
      touched.add(c)
      if (!followed.has(c) && !guarded(c, order)) queue.push(c)
    }
  }
  return touched
}

// `typeof x === 'function'` is how the console probes for a script that may
// not have loaded. That is safe for a hoisted function declaration, which is
// simply absent, so those probes are not findings.
const probed = new Set()
for (const { sf } of files) {
  const walk = (n) => {
    if (ts.isTypeOfExpression(n) && ts.isIdentifier(n.expression)) probed.add(n.expression.text)
    ts.forEachChild(n, walk)
  }
  ts.forEachChild(sf, walk)
}

const findings = []
for (const { script, order, sf } of files) {
  const lineOf = (n) => sf.getLineAndCharacterOfPosition(n.getStart(sf)).line + 1
  for (const st of sf.statements) {
    if (ts.isFunctionDeclaration(st) || ts.isClassDeclaration(st)) continue
    const line = lineOf(st)
    const seen = new Set()
    for (const name of reachable(st, order)) {
      const d = decls.get(name)
      if (!d || seen.has(name)) continue
      const later = d.order > order ||
        (d.order === order && d.line > line && d.kind !== 'function' && d.kind !== 'var')
      if (!later) continue
      if (d.kind === 'function' && probed.has(name)) continue
      seen.add(name)
      findings.push({ script, line, name, kind: d.kind, at: `${d.script}:${d.line}` })
    }
  }
}

// Two scripts wrapping the same property, e.g. window.fetch.
const propWrites = []
for (const { script, order, sf } of files) {
  const lineOf = (n) => sf.getLineAndCharacterOfPosition(n.getStart(sf)).line + 1
  for (const st of sf.statements) {
    if (ts.isExpressionStatement(st) && ts.isBinaryExpression(st.expression) &&
        st.expression.operatorToken.kind === ts.SyntaxKind.EqualsToken &&
        ts.isPropertyAccessExpression(st.expression.left)) {
      propWrites.push({ script, order, line: lineOf(st), prop: st.expression.left.getText(sf) })
    }
  }
}
const chains = new Map()
for (const w of propWrites) {
  if (!chains.has(w.prop)) chains.set(w.prop, [])
  chains.get(w.prop).push(w)
}

let bad = false
if (findings.length) {
  bad = true
  console.log('Reached before it is declared:\n')
  let last = ''
  for (const f of findings) {
    if (f.script !== last) { console.log('  ' + f.script); last = f.script }
    console.log(`    L${f.line} reaches ${f.kind} ${f.name}, declared at ${f.at}`)
  }
  console.log('')
}
for (const [prop, ws] of chains) {
  if (ws.length < 2) continue
  console.log(`${prop} is wrapped by ${ws.length} scripts, in this order:`)
  for (const w of ws) console.log(`    ${w.script}:${w.line}`)
  console.log('  The last one is outermost. Reordering these changes which\n' +
    '  wrapper sees the caller\'s original arguments.\n')
}
if (!bad) console.log('Load order is consistent: nothing is used before it exists.')
process.exit(bad ? 1 : 0)
