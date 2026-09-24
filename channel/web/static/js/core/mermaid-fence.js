/* Decide which mermaid fences are safe to draw.
   Desktop keeps the same decisions in
   desktop/src/renderer/src/lib/mermaidFence.ts.
   Classic script: these names are globals. See channel/web/README.md. */

// First word of a fence info string, lowercased. ```Mermaid title -> mermaid.
function mermaidFenceLang(info) {
    const raw = String(info || '').trim();
    if (!raw) return '';
    return raw.split(/\s+/)[0].toLowerCase();
}

// A line that opens or closes a CommonMark fence at the root of the message
// (up to three spaces of indent). Indented code and quote markers are not fences.
function mermaidFenceMarker(line) {
    const marked = /^( {0,3})(`{3,}|~{3,})(.*)$/.exec(line);
    if (!marked) return null;
    return {
        ch: marked[2].charAt(0),
        len: marked[2].length,
        rest: marked[3],
    };
}

// The fence markdown-it will auto-close at EOF, or null when every fence is closed.
// Streaming appends tokens inside that tail; drawing it would re-parse a partial
// diagram on every chunk. Callers leave that tail as a code block.
function mermaidOpenFenceAtEof(src) {
    if (!src) return null;
    const lines = String(src).replace(/\r\n?/g, '\n').split('\n');
    let open = null;
    for (let i = 0; i < lines.length; i++) {
        const marked = mermaidFenceMarker(lines[i]);
        if (open) {
            if (marked && marked.ch === open.ch && marked.len >= open.len && marked.rest.trim() === '') {
                open = null;
            }
            continue;
        }
        if (!marked || marked.len < 3) continue;
        // A backtick fence whose info contains a backtick is not a fence.
        if (marked.ch === '`' && marked.rest.indexOf('`') !== -1) continue;
        open = { ch: marked.ch, len: marked.len, info: marked.rest.trim() };
    }
    if (!open) return null;
    return { lang: mermaidFenceLang(open.info), info: open.info };
}

// markdown-it includes the closing line in token.map only when the author
// closed the fence. An auto-closed tail (end of the message, a blockquote,
// or a list) omits that line, so its map is one shorter than a closed fence
// with the same body. Leave that tail as source.
function mermaidFenceTokenIsOpen(token) {
    if (!token || !token.map || token.map.length < 2) return false;
    const content = String(token.content || '');
    const bodyLines = content === '' ? 0 : content.replace(/\r?\n$/, '').split('\n').length;
    const span = token.map[1] - token.map[0];
    return span < bodyLines + 2;
}

// True when this fence token is a still-open mermaid tail. Earlier closed
// mermaid fences in the same message may be drawn.
function mermaidFenceIsOpenTail(tokens, idx, openMermaid) {
    if (mermaidFenceTokenIsOpen(tokens && tokens[idx])) return true;
    if (!openMermaid) return false;
    for (let j = idx + 1; j < tokens.length; j++) {
        const token = tokens[j];
        if (token && token.type === 'fence' && mermaidFenceLang(token.info) === 'mermaid') return false;
    }
    return true;
}
