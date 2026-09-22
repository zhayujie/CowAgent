/**
 * Mermaid fence behavior for the web console.
 *
 *   node channel/web/tools/check-mermaid-fence.mjs
 *
 * Loads the real markdown-it bundle, mermaid-fence.js and markdown.js and
 * checks closed fences become placeholders, open fences stay code, and the
 * source is escaped. When jsdom is importable it also draws one diagram with
 * the vendored mermaid.min.js (strict mode, theme swap, a theme toggle
 * during the first in-flight render, parse failure, click http(s) links
 * left inert).
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

  await assertMermaidClickLinksInert(context, window)
  await assertThemeToggleDuringFirstRenderDraws(context, window)

  console.log('SVG OK')
}

// A theme toggle during the only in-flight render bumps the epoch and drops
// that draw. The placeholder has no data-mermaid-done yet, and nothing else
// queues a mount (renderMarkdown's timer is the mount we are inside). The
// diagram must still become an SVG.
async function assertThemeToggleDuringFirstRenderDraws(context, window) {
  const mermaidApi = window.mermaid
  const originalRender = mermaidApi.render.bind(mermaidApi)
  const root = window.document.documentElement
  const wasDark = root.classList.contains('dark')
  let toggled = false
  mermaidApi.render = async (id, text) => {
    if (!toggled && String(text).includes('ThemeRace')) {
      toggled = true
      root.classList.remove('dark')
      context.rerenderMermaidForTheme()
    }
    return originalRender(id, text)
  }

  const host = window.document.createElement('div')
  host.className = 'msg-content'
  try {
    root.classList.add('dark')
    host.innerHTML = context.renderMarkdown('```mermaid\ngraph TD\n  A["ThemeRace"]-->B\n```\n')
    window.document.body.appendChild(host)
    const svg = await waitFor(() => host.querySelector('.mermaid-diagram svg'))
    assert(svg, 'theme toggle during the first render should still insert an svg')
  } finally {
    mermaidApi.render = originalRender
    root.classList.toggle('dark', wasDark)
  }

  const block = host.querySelector('.mermaid-block')
  assert(toggled, 'theme toggle should run inside the in-flight render')
  assert(block.dataset.mermaidDone === '1', 'recovered diagram should be marked done')
  assert(block.dataset.mermaidError !== '1', 'theme race must not leave the source as a failed diagram')
  assert(block.querySelector('pre').hidden === true, 'source should be hidden once the remount draws')
  assert(block.dataset.mermaidTheme === 'default', 'remount should draw the theme selected by the toggle, got ' + block.dataset.mermaidTheme)
  assert(host.querySelectorAll('.mermaid-diagram svg').length === 1, 'theme race should leave a single svg')
}

// securityLevel strict still serializes click "https://..." as <a href> with
// no target. Those anchors must not be able to navigate this document.
async function assertMermaidClickLinksInert(context, window) {
  const mermaidApi = window.mermaid
  const originalRender = mermaidApi.render.bind(mermaidApi)
  let sawClick = 0
  mermaidApi.render = async (id, text) => {
    const result = await originalRender(id, text)
    if (String(text).includes('https://evil.example/phish')) {
      sawClick += 1
      const svg = String(result.svg || '')
      const injected = svg.replace(
        /<\/svg>\s*$/i,
        '<a xlink:href="https://evil.example/xlink" href="https://evil.example/also-href"><text>x</text></a></svg>'
      )
      return Object.assign({}, result, { svg: injected })
    }
    return result
  }

  const clickHost = window.document.createElement('div')
  clickHost.className = 'msg-content'
  const seqHost = window.document.createElement('div')
  const beforeUrl = String(window.location.href)
  try {
    clickHost.innerHTML = context.renderMarkdown(
      '```mermaid\n' +
      'graph TD\n' +
      '  A-->B\n' +
      '  B-->C\n' +
      '  click A "https://evil.example/phish" "open"\n' +
      '  click B "http://evil.example/other"\n' +
      '  click C "//evil.example/rel"\n' +
      '```\n'
    )
    seqHost.innerHTML = context.renderMarkdown(
      '```mermaid\n' +
      'sequenceDiagram\n' +
      '  participant Alice\n' +
      '  Alice->>Bob: hi\n' +
      '  link Alice: Dashboard @ https://evil.example/seq\n' +
      '```\n'
    )
    window.document.body.appendChild(clickHost)
    window.document.body.appendChild(seqHost)
    await context.mountMermaidDiagrams()
  } finally {
    mermaidApi.render = originalRender
  }

  assert(sawClick === 1, 'click diagram should render once, saw ' + sawClick)
  const clickBlock = clickHost.querySelector('.mermaid-block')
  assert(clickBlock && clickBlock.dataset.mermaidDone === '1', 'click diagram should mount')
  assert(clickBlock.dataset.mermaidError !== '1', 'click diagram should not fall back to a code block')
  const source = clickHost.querySelector('pre code')
  assert(source && source.textContent.includes('https://evil.example/phish'), 'copy source keeps the click URL')
  assertClickAnchorsInert(clickHost, window, beforeUrl, 3)
  assert(clickHost.querySelector('.mermaid-diagram').textContent.includes('A'), 'diagram label text should survive')

  const seqBlock = seqHost.querySelector('.mermaid-block')
  assert(seqBlock && seqBlock.dataset.mermaidError !== '1', 'sequence link diagram should render')
  assertClickAnchorsInert(seqHost, window, beforeUrl, 1)
}

function assertClickAnchorsInert(host, window, beforeUrl, minAnchors) {
  const diagram = host.querySelector('.mermaid-diagram')
  assert(diagram && diagram.querySelector('svg'), 'diagram svg missing')
  const anchors = diagram.querySelectorAll('a')
  assert(anchors.length >= minAnchors, 'expected click anchors to neutralize, got ' + anchors.length)
  const xlinkNs = 'http://www.w3.org/1999/xlink'
  anchors.forEach((anchor) => {
    const href = anchor.getAttribute('href')
    const xlink = anchor.getAttribute('xlink:href')
    const ns = typeof anchor.getAttributeNS === 'function' ? anchor.getAttributeNS(xlinkNs, 'href') : null
    assert(!href, 'click href would navigate this document: ' + href)
    assert(!xlink, 'xlink:href would navigate this document: ' + xlink)
    assert(!ns, 'namespaced xlink href would navigate this document: ' + ns)
    anchor.dispatchEvent(new window.MouseEvent('click', { bubbles: true, cancelable: true, view: window }))
  })
  assert(String(window.location.href) === beforeUrl, 'mermaid click navigated to ' + window.location.href)
  assert(!/href\s*=/i.test(diagram.innerHTML), 'diagram markup still has an href: ' + diagram.innerHTML.slice(0, 180))
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
