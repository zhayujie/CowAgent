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

// True when this fence token is the still-open mermaid tail. Earlier mermaid
// fences in the same message are complete and may be drawn.
function mermaidFenceIsOpenTail(tokens, idx, openMermaid) {
    if (!openMermaid) return false;
    for (let j = idx + 1; j < tokens.length; j++) {
        const token = tokens[j];
        if (token && token.type === 'fence' && mermaidFenceLang(token.info) === 'mermaid') return false;
    }
    return true;
}
