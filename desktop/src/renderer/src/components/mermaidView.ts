/**
 * Mermaid fences in the desktop app. Behavior matches the web console
 * (channel/web/static/js/core/markdown.js): code is the default view, and the
 * diagram library loads only when Preview is clicked. The web console fetches
 * mermaid@11.17.2 from a CDN. The desktop renderer CSP does not allow that
 * script host, so the same version is bundled and imported on demand.
 *
 * Message content is untrusted agent output. securityLevel 'strict' disables
 * HTML labels and click callbacks so a diagram cannot run script.
 */

import { t } from '../i18n'

const ZOOM_MIN = 0.4
const ZOOM_MAX = 3

type MermaidApi = typeof import('mermaid').default

let loadPromise: Promise<MermaidApi> | null = null
let seq = 0
let themeWatchStarted = false
let escBound = false

function themeName(): 'dark' | 'default' {
  return document.documentElement.classList.contains('dark') ? 'dark' : 'default'
}

function ensureMermaid(): Promise<MermaidApi> {
  if (!loadPromise) {
    loadPromise = import('mermaid')
      .then((mod) => mod.default)
      .catch((err) => {
        loadPromise = null
        throw err
      })
  }
  return loadPromise
}

function syncToolbar(block: HTMLElement) {
  const mode = block.dataset.mermaidMode || 'code'
  const state = block.dataset.mermaid
  block.querySelectorAll<HTMLElement>('.mermaid-mode-btn').forEach((btn) => {
    btn.classList.toggle('active', btn.dataset.mermaidView === mode)
  })
  const preview = block.querySelector<HTMLElement>('.mermaid-mode-btn[data-mermaid-view="chart"]')
  if (!preview) return
  preview.classList.toggle('loading', state === 'pending' || state === 'rendering')
  preview.classList.toggle('failed', state === 'invalid')
  preview.title = state === 'invalid' ? t('mermaid_preview_failed') : ''
}

function setZoom(block: HTMLElement, zoom: number) {
  const next = Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, zoom))
  block.dataset.mermaidZoomLevel = String(next)
  const svg = block.querySelector<SVGElement>('.mermaid-figure svg')
  if (!svg) return
  svg.style.width = `${next * 100}%`
  svg.style.maxWidth = next > 1 ? 'none' : ''
}

function syncFullscreenIcons() {
  const active =
    !!document.fullscreenElement || !!document.querySelector('.mermaid-block.mermaid-fullscreen')
  document.querySelectorAll('.mermaid-fullscreen-btn i').forEach((icon) => {
    icon.className = active ? 'fas fa-compress' : 'fas fa-expand'
  })
}

function toggleFallbackFullscreen(block: HTMLElement) {
  block.classList.toggle('mermaid-fullscreen')
  syncFullscreenIcons()
  if (!block.classList.contains('mermaid-fullscreen') || escBound) return
  escBound = true
  document.addEventListener('keydown', (e) => {
    if (e.key !== 'Escape') return
    document.querySelectorAll('.mermaid-block.mermaid-fullscreen').forEach((el) => {
      el.classList.remove('mermaid-fullscreen')
    })
    syncFullscreenIcons()
  })
}

function toggleFullscreen(block: HTMLElement) {
  const wrapper = block.querySelector<HTMLElement>('.code-block-wrapper')
  if (!wrapper) return
  if (block.classList.contains('mermaid-fullscreen')) {
    block.classList.remove('mermaid-fullscreen')
    syncFullscreenIcons()
    return
  }
  if (document.fullscreenElement) {
    document.exitFullscreen?.()
    return
  }
  if (wrapper.requestFullscreen) {
    wrapper.requestFullscreen().catch(() => toggleFallbackFullscreen(block))
  } else {
    toggleFallbackFullscreen(block)
  }
}

function markInvalid(block: HTMLElement) {
  if (!block.isConnected) return
  block.dataset.mermaid = 'invalid'
  block.dataset.mermaidMode = 'code'
  syncToolbar(block)
}

async function renderBlock(mermaid: MermaidApi, block: HTMLElement) {
  const pre = block.querySelector('pre')
  const codeEl = pre?.querySelector('code')
  const source = codeEl?.textContent || ''
  const theme = themeName()
  const id = `mermaid-svg-${++seq}`
  mermaid.initialize({
    startOnLoad: false,
    securityLevel: 'strict',
    theme,
    suppressErrorRendering: true,
  })
  try {
    const { svg } = await mermaid.render(id, source)
    if (!block.isConnected || block.dataset.mermaid !== 'rendering') return
    if (themeName() !== theme) {
      block.dataset.mermaid = 'pending'
      void loadAndRender([block])
      return
    }
    block.querySelectorAll('.mermaid-figure').forEach((el) => el.remove())
    const figure = document.createElement('div')
    figure.className = 'mermaid-figure'
    figure.innerHTML = svg
    pre?.parentNode?.insertBefore(figure, pre)
    block.dataset.mermaid = 'done'
    syncToolbar(block)
    const savedZoom = parseFloat(block.dataset.mermaidZoomLevel || '1')
    if (savedZoom !== 1) setZoom(block, savedZoom)
  } catch {
    if (block.dataset.mermaid === 'rendering') markInvalid(block)
  }
}

function loadAndRender(blocks: HTMLElement[]) {
  ensureMermaid()
    .then((mermaid) => {
      blocks.forEach((block) => {
        if (!block.isConnected || block.dataset.mermaid !== 'pending') return
        block.dataset.mermaid = 'rendering'
        syncToolbar(block)
        void renderBlock(mermaid, block)
      })
    })
    .catch(() => blocks.forEach(markInvalid))
}

function preview(block: HTMLElement) {
  block.dataset.mermaidMode = 'chart'
  const state = block.dataset.mermaid
  if (state === 'idle' || state === 'invalid') block.dataset.mermaid = 'pending'
  syncToolbar(block)
  if (block.dataset.mermaid === 'pending') loadAndRender([block])
}

function watchTheme() {
  if (themeWatchStarted || typeof document === 'undefined') return
  themeWatchStarted = true
  let last = themeName()
  const observer = new MutationObserver(() => {
    const next = themeName()
    if (next === last) return
    last = next
    const pending: HTMLElement[] = []
    document.querySelectorAll<HTMLElement>('.mermaid-block[data-mermaid="done"]').forEach((block) => {
      if (block.dataset.mermaidMode !== 'chart') return
      block.dataset.mermaid = 'pending'
      pending.push(block)
    })
    if (pending.length) loadAndRender(pending)
  })
  observer.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] })
  document.addEventListener('fullscreenchange', syncFullscreenIcons)
}

watchTheme()

/** Toolbar clicks inside a rendered mermaid fence. Returns true when handled. */
export function handleMermaidClick(target: HTMLElement): boolean {
  const toolbar = target.closest('.mermaid-toolbar')
  if (!toolbar) return false
  const block = toolbar.closest('.mermaid-block') as HTMLElement | null
  if (!block) return false

  const modeBtn = target.closest('[data-mermaid-view]') as HTMLElement | null
  if (modeBtn) {
    if (modeBtn.dataset.mermaidView === 'chart') preview(block)
    else {
      block.dataset.mermaidMode = 'code'
      syncToolbar(block)
    }
    return true
  }

  const zoomBtn = target.closest('[data-mermaid-zoom]') as HTMLElement | null
  if (zoomBtn) {
    const current = parseFloat(block.dataset.mermaidZoomLevel || '1')
    const action = zoomBtn.dataset.mermaidZoom
    setZoom(block, action === 'in' ? current * 1.25 : action === 'out' ? current / 1.25 : 1)
    return true
  }

  if (target.closest('.mermaid-fullscreen-btn')) {
    toggleFullscreen(block)
    return true
  }
  return true
}
