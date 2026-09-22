import { useEffect, useState, type RefObject } from 'react'

/* Draw closed mermaid fences to SVG. The library is the same IIFE the web
   console lazy-loads from /assets/vendor/mermaid (Vite publicDir is the web
   static tree). securityLevel strict refuses HTML and javascript click
   callbacks. A click URL is still emitted as <a href>, so those hrefs are
   removed after the SVG is inserted. */

interface MermaidApi {
  initialize: (config: Record<string, unknown>) => void
  render: (id: string, text: string) => Promise<{ svg: string }>
  parse?: (text: string, options?: { suppressErrors?: boolean }) => Promise<unknown>
}

let mermaidPromise: Promise<MermaidApi> | null = null
let renderChain: Promise<void> = Promise.resolve()
let renderSeq = 0

function mermaidScriptUrl(): string {
  // Same relative URL the shell uses for fonts (index.html). Hash routing
  // keeps the document at the app root, so this resolves next to index.html
  // in dev and in the packaged build.
  return './vendor/mermaid/mermaid.min.js'
}

function readMermaid(): MermaidApi | null {
  const api = (window as unknown as { mermaid?: MermaidApi }).mermaid
  return api && typeof api.render === 'function' ? api : null
}

function ensureMermaid(): Promise<MermaidApi> {
  const ready = readMermaid()
  if (ready) return Promise.resolve(ready)
  if (mermaidPromise) return mermaidPromise
  mermaidPromise = new Promise((resolve, reject) => {
    const script = document.createElement('script')
    script.src = mermaidScriptUrl()
    script.async = true
    script.onload = () => {
      const api = readMermaid()
      if (api) resolve(api)
      else reject(new Error('mermaid did not load'))
    }
    script.onerror = () => reject(new Error('mermaid failed to load'))
    document.head.appendChild(script)
  })
  mermaidPromise.catch(() => {})
  return mermaidPromise
}

function configureMermaid(api: MermaidApi, theme: 'dark' | 'default') {
  api.initialize({
    startOnLoad: false,
    securityLevel: 'strict',
    theme,
    suppressErrorRendering: true,
    fontFamily: 'ui-sans-serif, system-ui, sans-serif',
  })
}

function fitMermaidSvg(host: Element) {
  const svg = host.querySelector('svg')
  if (!svg) return
  let width = 0
  let height = 0
  const box = svg.viewBox && svg.viewBox.baseVal
  if (box && box.width) {
    width = box.width
    height = box.height
  } else {
    const parts = (svg.getAttribute('viewBox') || '').trim().split(/[\s,]+/).map(Number)
    if (parts.length === 4 && parts[2] > 0) {
      width = parts[2]
      height = parts[3]
    }
  }
  if (!width) return
  svg.setAttribute('width', String(Math.ceil(width)))
  if (height) svg.setAttribute('height', String(Math.ceil(height)))
  svg.style.maxWidth = 'none'
  svg.style.height = 'auto'
}

// Mermaid hangs the node transform on the <a>, so the element stays.
// href / xlink:href are what would navigate this page or the Electron window.
function stripMermaidAnchorHrefs(host: Element) {
  if (!host || typeof host.querySelectorAll !== 'function') return
  const anchors = host.querySelectorAll('a')
  for (let i = 0; i < anchors.length; i++) {
    const anchor = anchors[i]
    anchor.removeAttribute('href')
    anchor.removeAttribute('xlink:href')
    if (typeof anchor.removeAttributeNS === 'function') {
      anchor.removeAttributeNS('http://www.w3.org/1999/xlink', 'href')
    }
  }
}

function markFallback(block: HTMLElement) {
  if (!block.isConnected) return
  const diagram = block.querySelector<HTMLElement>('.mermaid-diagram')
  if (diagram) {
    diagram.innerHTML = ''
    diagram.hidden = true
  }
  const pre = block.querySelector<HTMLElement>('pre')
  if (pre) pre.hidden = false
  block.dataset.mermaidDone = '1'
  block.dataset.mermaidError = '1'
}

async function renderBlock(api: MermaidApi, block: HTMLElement, theme: 'dark' | 'default', cancelled: () => boolean) {
  if (!block.isConnected || block.dataset.mermaidDone === '1' || cancelled()) return
  const source = block.querySelector('pre code')?.textContent || ''
  const token = String(++renderSeq)
  block.dataset.mermaidToken = token
  if (!source.trim()) {
    markFallback(block)
    return
  }
  const id = 'cowmermaid' + token
  const stale = () => cancelled() || !block.isConnected || block.dataset.mermaidToken !== token
  try {
    configureMermaid(api, theme)
    if (typeof api.parse === 'function') {
      const parsed = await api.parse(source, { suppressErrors: true })
      if (parsed === false) throw new Error('mermaid parse failed')
    }
    if (stale()) return
    const rendered = await api.render(id, source)
    if (stale()) return
    const svg = rendered && rendered.svg
    if (!svg || svg.indexOf('<svg') === -1) throw new Error('mermaid returned no svg')
    const diagram = block.querySelector<HTMLElement>('.mermaid-diagram')
    const pre = block.querySelector<HTMLElement>('pre')
    if (!diagram) throw new Error('mermaid host missing')
    diagram.innerHTML = svg
    stripMermaidAnchorHrefs(diagram)
    fitMermaidSvg(diagram)
    diagram.hidden = false
    if (pre) pre.hidden = true
    block.dataset.mermaidDone = '1'
    block.dataset.mermaidTheme = theme
    delete block.dataset.mermaidError
  } catch {
    if (stale()) return
    markFallback(block)
  } finally {
    const leftover = document.getElementById(id)
    if (leftover && !block.contains(leftover)) leftover.remove()
  }
}

function enqueue(task: () => Promise<void>): Promise<void> {
  renderChain = renderChain.then(task, task)
  return renderChain
}

export async function mountMermaidBlocks(root: ParentNode, theme: 'dark' | 'default', cancelled: () => boolean) {
  const pending = root.querySelector('.mermaid-block:not([data-mermaid-done])')
  if (!pending || cancelled()) return
  let api: MermaidApi
  try {
    api = await ensureMermaid()
  } catch {
    root.querySelectorAll<HTMLElement>('.mermaid-block:not([data-mermaid-done])').forEach((block) => {
      if (!cancelled()) markFallback(block)
    })
    return
  }
  if (cancelled()) return
  const blocks = Array.from(root.querySelectorAll<HTMLElement>('.mermaid-block:not([data-mermaid-done])'))
  for (const block of blocks) {
    if (cancelled()) return
    await renderBlock(api, block, theme, cancelled)
  }
}

const darkListeners = new Set<(dark: boolean) => void>()
let darkObserver: MutationObserver | null = null

function subscribeHtmlDark(cb: (dark: boolean) => void): () => void {
  darkListeners.add(cb)
  if (!darkObserver) {
    const sync = () => {
      const dark = document.documentElement.classList.contains('dark')
      darkListeners.forEach((fn) => fn(dark))
    }
    darkObserver = new MutationObserver(sync)
    darkObserver.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] })
  }
  return () => {
    darkListeners.delete(cb)
    if (darkListeners.size === 0 && darkObserver) {
      darkObserver.disconnect()
      darkObserver = null
    }
  }
}

function useHtmlDark(): boolean {
  const [dark, setDark] = useState(() => document.documentElement.classList.contains('dark'))
  useEffect(() => subscribeHtmlDark((next) => setDark(next)), [])
  return dark
}

/** Draw mermaid placeholders inside root. Skips the whole pass while the
    message is still streaming so each token does not redraw the diagram. */
export function useMermaidDiagrams(
  rootRef: RefObject<HTMLElement | null>,
  html: string,
  streaming: boolean,
) {
  const dark = useHtmlDark()
  useEffect(() => {
    const root = rootRef.current
    if (!root || streaming) return
    if (!root.querySelector('.mermaid-block')) return
    const theme: 'dark' | 'default' = dark ? 'dark' : 'default'
    root.querySelectorAll<HTMLElement>('.mermaid-block').forEach((block) => {
      if (block.dataset.mermaidError === '1') return
      if (block.dataset.mermaidDone === '1' && block.dataset.mermaidTheme === theme) return
      if (block.dataset.mermaidDone === '1') {
        delete block.dataset.mermaidDone
        const diagram = block.querySelector<HTMLElement>('.mermaid-diagram')
        if (diagram) {
          diagram.innerHTML = ''
          diagram.hidden = true
        }
        const pre = block.querySelector<HTMLElement>('pre')
        if (pre) pre.hidden = false
      }
    })
    if (!root.querySelector('.mermaid-block:not([data-mermaid-done])')) return
    let cancelled = false
    enqueue(async () => {
      if (cancelled || !root.isConnected) return
      await mountMermaidBlocks(root, theme, () => cancelled)
    })
    return () => {
      cancelled = true
    }
  }, [rootRef, html, dark, streaming])
}
