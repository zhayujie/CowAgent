/**
 * Mermaid fence behavior for the web console.
 *
 *   node channel/web/tools/check-mermaid-fence.mjs
 *
 * Loads the real markdown-it bundle, mermaid-fence.js and markdown.js and
 * checks closed fences become placeholders, open fences stay code, and the
 * source is escaped. When jsdom is importable it also draws one diagram with
 * the vendored mermaid.min.js (strict mode, theme swap, parse failure).
 */
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import vm from 'node:vm'

const HERE = dirname(fileURLToPath(import.meta.url))
const WEB = resolve(HERE, '..')
const STATIC = resolve(WEB, 'static')

function assert(cond, message) {
  if (!cond) throw new Error(message)
}

function loadConsole() {
  const context = {
    console,
    Promise,
    setTimeout,
    clearTimeout,
    escapeHtml(value) {
      return String(value)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
    },
  }
  context.window = context
  context.globalThis = context
  vm.createContext(context)
  vm.runInContext(readFileSync(resolve(STATIC, 'vendor/markdown-it/markdown-it.min.js'), 'utf8'), context)
  vm.runInContext(readFileSync(resolve(STATIC, 'js/core/mermaid-fence.js'), 'utf8'), context)
  vm.runInContext(readFileSync(resolve(STATIC, 'js/core/markdown.js'), 'utf8'), context)
  assert(typeof context.renderMarkdown === 'function', 'renderMarkdown missing')
  assert(typeof context.mermaidOpenFenceAtEof === 'function', 'fence helper missing')
  return context
}

function count(html, needle) {
  return html.split(needle).length - 1
}

function fenceChecks(render) {
  const closed = render('```mermaid\ngraph TD\n  A-->B\n```\n')
  assert(closed.includes('mermaid-block'), 'closed fence should be a diagram placeholder')
  assert(closed.includes('code-copy-btn'), 'placeholder should keep a copy button')
  assert(closed.includes('graph TD'), 'placeholder should keep the source')
  assert(closed.includes('mermaid-diagram'), 'placeholder should have a diagram slot')

  const xss = render('```mermaid\ngraph TD\n  A["<img src=x onerror=alert(1)>"]\n```\n')
  assert(!xss.includes('<img'), 'diagram source must be escaped')
  assert(xss.includes('&lt;img'), 'escaped source should remain visible')

  const open = render('```mermaid\ngraph TD\n  A-->B\n')
  assert(!open.includes('mermaid-block'), 'unclosed fence must stay a code block')
  assert(open.includes('A--&gt;B') || open.includes('A-->B'), 'unclosed source should still be shown')

  const tail = render('```mermaid\ngraph TD\n  A-->B\n```\n\nhello\n')
  assert(tail.includes('mermaid-block'), 'a fence closed before more text is complete')
  assert(tail.includes('hello'), 'text after the fence is kept')

  const two = render('```mermaid\ngraph TD\n  A-->B\n```\n```mermaid\ngraph LR\n  C-->D\n')
  assert(count(two, 'mermaid-block') === 1, 'only the closed fence of a pair is a diagram, got ' + count(two, 'mermaid-block'))
  assert(two.includes('C--&gt;D') || two.includes('C-->D'), 'the open tail source is still shown')

  const python = render('```python\nprint(1)\n```\n')
  assert(!python.includes('mermaid-block'), 'other languages stay code blocks')

  const crlf = render('```mermaid\r\ngraph TD\r\n  A-->B\r\n```\r\n')
  assert(crlf.includes('mermaid-block'), 'CRLF closed fence is a diagram')

  const tilde = render('~~~mermaid\ngraph TD\n  A-->B\n~~~\n')
  assert(tilde.includes('mermaid-block'), 'tilde fence is a diagram')

  const titled = render('```Mermaid title\ngraph TD\n  A-->B\n```\n')
  assert(titled.includes('mermaid-block'), 'language match is case-insensitive and ignores a title')

  const after = render('```mermaid\ngraph TD\n  A-->B\n```\n\n```js\nconsole.log(1)\n')
  assert(count(after, 'mermaid-block') === 1, 'a later unclosed code fence does not hide the diagram')
  assert(after.includes('console.log'), 'the unclosed code fence is still rendered')

  const indented = render('    ```mermaid\n    graph TD\n    ```\n')
  assert(!indented.includes('mermaid-block'), 'an indented code block is not a mermaid fence')

  const inline = render('use ```mermaid``` in a sentence\n')
  assert(!inline.includes('mermaid-block'), 'inline backticks are not a fence')

  const both = render('```mermaid\ngraph TD\n  A-->B\n```\n\n```mermaid\nsequenceDiagram\n  Alice->>Bob: hi\n```\n')
  assert(count(both, 'mermaid-block') === 2, 'two closed fences are both diagrams')
}

function fenceSuite() {
  const ctx = loadConsole()
  fenceChecks((src) => ctx.renderMarkdown(src))
  console.log('FENCE OK')
}

async function svgSuite() {
  let JSDOM = null
  const candidates = [
    '/tmp/mermaid-smoke/node_modules/jsdom/lib/api.js',
  ]
  for (const candidate of candidates) {
    try {
      JSDOM = (await import(candidate)).JSDOM
      break
    } catch {
      /* try the next place jsdom might be installed */
    }
  }
  if (!JSDOM) {
    console.log('SKIP svg (jsdom not installed)')
    return
  }

  const dom = new JSDOM('<!doctype html><html class="dark"><head></head><body></body></html>', {
    runScripts: 'outside-only',
    url: 'http://localhost/',
    pretendToBeVisual: true,
  })
  const context = dom.getInternalVMContext()
  const window = context.window
  const bbox = () => ({ x: 0, y: 0, width: 80, height: 20 })
  for (const Ctor of [window.SVGElement, window.SVGGraphicsElement, window.Element]) {
    if (Ctor && Ctor.prototype && !Ctor.prototype.getBBox) Ctor.prototype.getBBox = bbox
  }
  if (window.SVGElement && !window.SVGElement.prototype.getComputedTextLength) {
    window.SVGElement.prototype.getComputedTextLength = () => 40
  }

  vm.runInContext(readFileSync(resolve(STATIC, 'vendor/markdown-it/markdown-it.min.js'), 'utf8'), context)
  vm.runInContext(readFileSync(resolve(STATIC, 'vendor/mermaid/mermaid.min.js'), 'utf8'), context)
  vm.runInContext(readFileSync(resolve(STATIC, 'js/core/utils.js'), 'utf8'), context)
  vm.runInContext(readFileSync(resolve(STATIC, 'js/core/mermaid-fence.js'), 'utf8'), context)
  vm.runInContext(readFileSync(resolve(STATIC, 'js/core/markdown.js'), 'utf8'), context)
  const mermaid = window.mermaid
  assert(mermaid && typeof mermaid.render === 'function', 'vendored mermaid did not set window.mermaid')

  let seen = null
  const originalInit = mermaid.initialize.bind(mermaid)
  mermaid.initialize = (config) => {
    seen = config
    return originalInit(config)
  }

  const host = window.document.createElement('div')
  host.className = 'msg-content'
  host.innerHTML = context.renderMarkdown('```mermaid\ngraph TD\n  A["Hello"]-->B\n```\n')
  window.document.body.appendChild(host)
  await context.mountMermaidDiagrams()

  const svg = host.querySelector('svg')
  assert(svg, 'closed fence should render an svg')
  assert(host.querySelector('pre').hidden === true, 'source is hidden once the diagram draws')
  assert(host.querySelector('.mermaid-diagram').hidden === false, 'diagram slot is shown')
  assert(host.querySelector('.mermaid-block').dataset.mermaidDone === '1', 'mount is idempotent')
  assert(seen && seen.securityLevel === 'strict', 'securityLevel must be strict')
  assert(seen.suppressErrorRendering === true, 'errors must not inject a diagram into the page')
  assert(seen.theme === 'dark', 'initial theme follows the dark class')
  const darkSvg = svg.outerHTML

  await context.mountMermaidDiagrams()
  assert(host.querySelectorAll('svg').length === 1, 'a second mount must not draw again')

  window.document.documentElement.classList.remove('dark')
  context.rerenderMermaidForTheme()
  const light = await waitFor(() => {
    const next = host.querySelector('svg')
    return next && next.outerHTML !== darkSvg ? next.outerHTML : ''
  })
  assert(light.includes('<svg'), 'theme change redraws the diagram')

  const badHost = window.document.createElement('div')
  badHost.innerHTML = context.renderMarkdown('```mermaid\n:::not a diagram\n```\n')
  window.document.body.appendChild(badHost)
  await context.mountMermaidDiagrams()
  const bad = badHost.querySelector('.mermaid-block')
  assert(bad.dataset.mermaidError === '1', 'a bad diagram is marked failed')
  assert(bad.querySelector('pre').hidden === false, 'failure falls back to the code block')
  assert(!bad.querySelector('.mermaid-diagram svg'), 'failure does not leave an svg')

  const streaming = window.document.createElement('div')
  streaming.className = 'sse-streaming'
  streaming.innerHTML = context.renderMarkdown('```mermaid\ngraph TD\n  A-->B\n```\n')
  window.document.body.appendChild(streaming)
  await context.mountMermaidDiagrams()
  assert(!streaming.querySelector('.mermaid-block').dataset.mermaidDone, 'streaming answer is not drawn')
  streaming.classList.remove('sse-streaming')
  await context.mountMermaidDiagrams()
  assert(streaming.querySelector('svg'), 'drawing starts once streaming settles')

  console.log('SVG OK')
}

async function waitFor(read) {
  const start = Date.now()
  while (Date.now() - start < 3000) {
    const value = read()
    if (value) return value
    await new Promise((resolve) => setTimeout(resolve, 20))
  }
  throw new Error('timed out waiting for mermaid')
}

fenceSuite()
await svgSuite()
