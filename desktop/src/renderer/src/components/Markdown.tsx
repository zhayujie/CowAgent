import React, { useMemo, useRef, useCallback } from 'react'
import MarkdownIt from 'markdown-it'
import hljs from 'highlight.js'
import { t } from '../i18n'
import apiClient from '../api/client'
import { workspaceHrefOf } from '../lib/fileKind'
import { useWorkspaceStore } from '../store/workspaceStore'
import { useLightboxStore } from './Lightbox'

/**
 * Markdown renderer aligned 1:1 with the web console (markdown-it + highlight.js
 * + GitHub themes). Using the same engine guarantees identical line-break,
 * linkify and code-highlight behavior across web and desktop.
 */

const md: MarkdownIt = new MarkdownIt({
  html: false,
  breaks: true,
  linkify: true,
  typographer: true,
  highlight(str, lang) {
    if (lang && hljs.getLanguage(lang)) {
      try {
        return hljs.highlight(str, { language: lang }).value
      } catch {
        /* fall through */
      }
    }
    try {
      return hljs.highlightAuto(str).value
    } catch {
      return ''
    }
  },
})

// CommonMark's flanking rules treat every Unicode punctuation alike, so
// `是**"引号"**——` never opens emphasis: the quote after `**` is punctuation
// while 是 before it is neither punctuation nor space, and the run degrades to
// literal asterisks. Apply the CJK-friendly amendment
// (github.com/tats-u/markdown-cjk-friendly): a `*` run with a CJK neighbour and
// no adjacent whitespace both opens and closes. `_` keeps the stock rules,
// whose intraword behavior depends on the original classification.
const _CJK_CHAR =
  /[\u1100-\u11FF\u2E80-\u303F\u3040-\u33FF\u3400-\u4DBF\u4E00-\u9FFF\uA960-\uA97F\uAC00-\uD7FF\uF900-\uFAFF\uFE10-\uFE19\uFE30-\uFE6F\uFF00-\uFF60\uFFE0-\uFFE6]/
const _StateInline = md.inline.State as unknown as {
  prototype: {
    scanDelims(start: number, canSplitWord: boolean): { can_open: boolean; can_close: boolean; length: number }
    src: string
    posMax: number
  }
}
const _scanDelims = _StateInline.prototype.scanDelims
_StateInline.prototype.scanDelims = function (start, canSplitWord) {
  const res = _scanDelims.call(this, start, canSplitWord)
  if (!canSplitWord) return res
  const lastCode = start > 0 ? this.src.charCodeAt(start - 1) : 0x20
  const nextPos = start + res.length
  const nextCode = nextPos < this.posMax ? this.src.charCodeAt(nextPos) : 0x20
  if (md.utils.isWhiteSpace(lastCode) || md.utils.isWhiteSpace(nextCode)) return res
  if (!_CJK_CHAR.test(String.fromCharCode(lastCode)) && !_CJK_CHAR.test(String.fromCharCode(nextCode))) return res
  res.can_open = true
  res.can_close = true
  return res
}

// Fix greedy linkify: markdown-it's linkify swallows markdown emphasis (`*`)
// and CJK full-width punctuation glued to a URL (common in LLM output like
// `**https://x**，中文`), turning the whole tail into one broken link. Cut the
// URL at the first such char and spill the remainder back as plain text.
const _GREEDY_LINK_CUT = /[*\u3000-\u303F\uFF00-\uFFEF]/
md.core.ruler.after('linkify', 'fix_greedy_linkify', (state) => {
  for (const blk of state.tokens) {
    if (blk.type !== 'inline' || !blk.children) continue
    const ch = blk.children
    for (let i = 0; i < ch.length; i++) {
      const open = ch[i]
      if (open.type !== 'link_open' || open.markup !== 'linkify') continue
      const textTok = ch[i + 1]
      const close = ch[i + 2]
      if (!textTok || textTok.type !== 'text' || !close || close.type !== 'link_close') continue
      const idx = textTok.content.search(_GREEDY_LINK_CUT)
      if (idx < 0) continue
      const keep = textTok.content.slice(0, idx)
      const spill = textTok.content.slice(idx)
      textTok.content = keep
      open.attrSet('href', keep)
      const spillTok = new state.Token('text', '', 0)
      spillTok.content = spill
      ch.splice(i + 3, 0, spillTok)
    }
  }
})

// Open links in a new tab safely.
const defaultLinkOpen =
  md.renderer.rules.link_open ||
  function (tokens, idx, options, _env, self) {
    return self.renderToken(tokens, idx, options)
  }
md.renderer.rules.link_open = function (tokens, idx, options, env, self) {
  const token = tokens[idx]
  // A workspace-relative href means nothing outside the app: `target=_blank`
  // would hand it to the OS browser, which resolves it against the renderer's
  // file:// URL. Tag it so the click handler opens the preview panel instead.
  const wsPath = workspaceHrefOf(token.attrGet('href') || '')
  if (wsPath) {
    token.attrPush(['data-ws-path', wsPath])
    token.attrJoin('class', 'ws-link')
  } else {
    token.attrPush(['target', '_blank'])
    token.attrPush(['rel', 'noopener noreferrer'])
  }
  return defaultLinkOpen(tokens, idx, options, env, self)
}

// An image the agent produced is referenced by its local path (`/Users/.../x.png`
// or `~/...`). The renderer runs from file:// or the dev server, so such a src
// never resolves on its own — route it through the backend file endpoint, which
// takes an absolute path and enforces the allowed roots.
const defaultImage =
  md.renderer.rules.image ||
  function (tokens, idx, options, _env, self) {
    return self.renderToken(tokens, idx, options)
  }
md.renderer.rules.image = function (tokens, idx, options, env, self) {
  const token = tokens[idx]
  const src = token.attrGet('src') || ''
  const baseDir = (env as { imageBaseDir?: string } | undefined)?.imageBaseDir
  if (/^~\//.test(src) || src.startsWith('/')) {
    token.attrSet('src', apiClient.getServeFileUrl(src))
  } else if (baseDir && !/^[a-zA-Z][\w+.-]*:/.test(src)) {
    // Doc-relative image (e.g. knowledge markdown `../images/x.png`): resolve
    // against the doc's directory (passed via render env) and serve via /api/file.
    let rel = src
    try {
      rel = decodeURIComponent(rel)
    } catch {
      /* keep the raw form */
    }
    const combined = `${baseDir}/${rel.split('?')[0]}`
    const segments: string[] = []
    for (const seg of combined.split('/')) {
      if (seg === '..') segments.pop()
      else if (seg !== '.' && seg !== '') segments.push(seg)
    }
    // Unix baseDir is absolute, so restore the leading slash split() dropped
    // (a Windows drive path like C:/x keeps its own prefix). /api/file rejects
    // non-absolute paths.
    const resolved = (combined.startsWith('/') ? '/' : '') + segments.join('/')
    token.attrSet('src', apiClient.getServeFileUrl(resolved))
  }
  return defaultImage(tokens, idx, options, env, self)
}

// Wrap fenced code blocks so we can render a header (lang + copy button).
const defaultFence =
  md.renderer.rules.fence ||
  function (tokens, idx, options, _env, self) {
    return self.renderToken(tokens, idx, options)
  }
md.renderer.rules.fence = function (tokens, idx, options, env, self) {
  const token = tokens[idx]
  const info = token.info ? token.info.trim().split(/\s+/)[0] : ''
  // Ensure the `hljs` class is present so the GitHub theme background/base
  // color applies (markdown-it only adds language-* by default).
  let rendered = defaultFence(tokens, idx, options, env, self)
  if (rendered.includes('<code class="')) {
    rendered = rendered.replace('<code class="', '<code class="hljs ')
  } else {
    rendered = rendered.replace('<code>', '<code class="hljs">')
  }
  return (
    `<div class="code-block-wrapper">` +
    `<div class="code-block-header">` +
    `<span class="code-block-lang">${info || 'text'}</span>` +
    `<button type="button" class="code-copy-btn" data-code-id="cb-${idx}" aria-label="Copy code">${t('msg_copy')}</button>` +
    `</div>` +
    rendered +
    `</div>`
  )
}

interface MarkdownProps {
  content: string
  /**
   * Intercept clicks on internal document links (relative `.md` hrefs). When
   * provided, such links open in-app instead of being handed to the OS. Used by
   * the knowledge viewer so index links open the target doc rather than firing
   * an "application cannot be opened (-120)" error in Electron.
   */
  onInternalLink?: (href: string) => void
  /**
   * Absolute directory of the document the markdown comes from, so image srcs
   * that are relative to it (`../images/x.png`) resolve to real files. Used by
   * the knowledge viewer; without it relative srcs are left untouched.
   */
  imageBaseDir?: string
}

const Markdown: React.FC<MarkdownProps> = ({ content, onInternalLink, imageBaseDir }) => {
  const rootRef = useRef<HTMLDivElement>(null)

  const html = useMemo(() => md.render(content || '', { imageBaseDir }), [content, imageBaseDir])

  // Delegate clicks: images zoom, copy buttons on code blocks, internal doc links.
  const handleClick = useCallback(
    (e: React.MouseEvent<HTMLDivElement>) => {
      const target = e.target as HTMLElement

      // Any inline image opens in the lightbox.
      const img = target.closest('img') as HTMLImageElement | null
      if (img) {
        useLightboxStore.getState().open(img.currentSrc || img.src)
        return
      }

      // Internal knowledge links (relative *.md), when a handler is provided.
      if (onInternalLink) {
        const a = target.closest('a') as HTMLAnchorElement | null
        if (a) {
          const href = a.getAttribute('href') || ''
          if (href.endsWith('.md') && !/^https?:\/\//i.test(href)) {
            e.preventDefault()
            onInternalLink(href)
            return
          }
        }
      }

      // Links to workspace files open in the preview panel.
      const wsLink = target.closest('a[data-ws-path]') as HTMLAnchorElement | null
      if (wsLink) {
        e.preventDefault()
        useWorkspaceStore.getState().openLink(wsLink.dataset.wsPath || '')
        return
      }

      const btn = target.closest('.code-copy-btn') as HTMLElement | null
      if (!btn) return
      const pre = btn.closest('.code-block-wrapper')?.querySelector('pre')
      if (!pre) return
      navigator.clipboard.writeText(pre.textContent || '')
      const original = btn.textContent
      btn.textContent = t('msg_copied')
      btn.classList.add('copied')
      setTimeout(() => {
        btn.textContent = original
        btn.classList.remove('copied')
      }, 1600)
    },
    [onInternalLink]
  )

  return (
    <div
      ref={rootRef}
      className="msg-content text-sm text-content leading-relaxed break-words"
      onClick={handleClick}
      dangerouslySetInnerHTML={{ __html: html }}
    />
  )
}

export default Markdown
