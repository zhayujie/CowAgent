/* Which mermaid fences are complete enough to draw.
   Keep the decisions in line with channel/web/static/js/core/mermaid-fence.js. */

export function mermaidFenceLang(info: string | null | undefined): string {
  const raw = String(info || '').trim()
  if (!raw) return ''
  return raw.split(/\s+/)[0].toLowerCase()
}

function mermaidFenceMarker(line: string): { ch: string; len: number; rest: string } | null {
  const marked = /^( {0,3})(`{3,}|~{3,})(.*)$/.exec(line)
  if (!marked) return null
  return {
    ch: marked[2].charAt(0),
    len: marked[2].length,
    rest: marked[3],
  }
}

export function mermaidOpenFenceAtEof(src: string | null | undefined): { lang: string; info: string } | null {
  if (!src) return null
  const lines = String(src).replace(/\r\n?/g, '\n').split('\n')
  let open: { ch: string; len: number; info: string } | null = null
  for (let i = 0; i < lines.length; i++) {
    const marked = mermaidFenceMarker(lines[i])
    if (open) {
      if (marked && marked.ch === open.ch && marked.len >= open.len && marked.rest.trim() === '') {
        open = null
      }
      continue
    }
    if (!marked || marked.len < 3) continue
    if (marked.ch === '`' && marked.rest.indexOf('`') !== -1) continue
    open = { ch: marked.ch, len: marked.len, info: marked.rest.trim() }
  }
  if (!open) return null
  return { lang: mermaidFenceLang(open.info), info: open.info }
}

export function mermaidFenceIsOpenTail(
  tokens: { type?: string; info?: string }[],
  idx: number,
  openMermaid: boolean,
): boolean {
  if (!openMermaid) return false
  for (let j = idx + 1; j < tokens.length; j++) {
    const token = tokens[j]
    if (token && token.type === 'fence' && mermaidFenceLang(token.info) === 'mermaid') return false
  }
  return true
}
