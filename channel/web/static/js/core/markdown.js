/* markdown-it setup plus image, video and code-block rendering.
   Split out of console.js. These are classic scripts sharing one global
   scope; see channel/web/README.md before changing the load order. */

// =====================================================================
// Markdown Renderer
// =====================================================================
const FALLBACK_HLJS = {
    getLanguage() { return false; },
    highlight(str) { return { value: escapeHtml(str) }; },
    highlightAuto(str) { return { value: escapeHtml(str) }; },
    highlightElement() {},
};

function getHljs() {
    return window.hljs || FALLBACK_HLJS;
}

// CJK ideographs, kana, Hangul and full/halfwidth forms (BMP only).
const CJK_CHAR_RE = /[\u1100-\u11FF\u2E80-\u303F\u3040-\u33FF\u3400-\u4DBF\u4E00-\u9FFF\uA960-\uA97F\uAC00-\uD7FF\uF900-\uFAFF\uFE10-\uFE19\uFE30-\uFE6F\uFF00-\uFF60\uFFE0-\uFFE6]/;

// CommonMark's flanking rules treat every Unicode punctuation alike, so
// `是**"引号"**——` never opens emphasis: the quote after `**` is punctuation
// while 是 before it is neither punctuation nor space, and the run degrades to
// literal asterisks. Apply the CJK-friendly amendment
// (github.com/tats-u/markdown-cjk-friendly): a `*` run with a CJK neighbour and
// no adjacent whitespace both opens and closes. `_` keeps the stock rules,
// whose intraword behavior depends on the original classification.
function patchCjkEmphasis(md) {
    const State = md.inline && md.inline.State;
    if (!State || !State.prototype.scanDelims || State.prototype._cjkEmphasisPatched) return;
    const utils = md.utils;
    const scanDelims = State.prototype.scanDelims;
    State.prototype.scanDelims = function(start, canSplitWord) {
        const res = scanDelims.call(this, start, canSplitWord);
        if (!canSplitWord) return res;
        const lastCode = start > 0 ? this.src.charCodeAt(start - 1) : 0x20;
        const nextPos = start + res.length;
        const nextCode = nextPos < this.posMax ? this.src.charCodeAt(nextPos) : 0x20;
        if (utils.isWhiteSpace(lastCode) || utils.isWhiteSpace(nextCode)) return res;
        if (!CJK_CHAR_RE.test(String.fromCharCode(lastCode)) &&
            !CJK_CHAR_RE.test(String.fromCharCode(nextCode))) return res;
        res.can_open = true;
        res.can_close = true;
        return res;
    };
    State.prototype._cjkEmphasisPatched = true;
}

function buildMermaidBlockHtml(source) {
    // The source stays in the <pre> so the existing copy button can read it back,
    // and so a failed draw still has the code block on screen.
    const escaped = escapeHtml(source || '');
    return '<div class="mermaid-block code-block-wrapper" data-mermaid-pending="1">' +
        '<div class="code-block-header">' +
            '<span class="code-block-lang">mermaid</span>' +
            '<button type="button" class="code-copy-btn" title="Copy code">' +
                '<i class="fas fa-copy"></i>' +
            '</button>' +
        '</div>' +
        '<pre class="mermaid-source"><code class="language-mermaid">' + escaped + '</code></pre>' +
        '<div class="mermaid-diagram" hidden></div>' +
    '</div>';
}

function createMd() {
    const hljsLib = getHljs();
    const mdFactory = window.markdownit;
    if (typeof mdFactory !== 'function') {
        return {
            render(text) {
                return `<p>${escapeHtml(text || '')}</p>`;
            }
        };
    }
    const md = mdFactory({
        html: false, breaks: true, linkify: true, typographer: true,
        highlight: function(str, lang) {
            if (lang && hljsLib.getLanguage(lang)) {
                try { return hljsLib.highlight(str, { language: lang }).value; } catch (_) {}
            }
            return hljsLib.highlightAuto(str).value;
        }
    });
    patchCjkEmphasis(md);
    // Fix greedy linkify: markdown-it's linkify swallows markdown emphasis (*)
    // and CJK full-width punctuation glued to a URL (common in LLM output like
    // "**https://x**，中文"), turning the whole tail into one broken link. Cut
    // the URL at the first such char and spill the remainder back as text.
    var GREEDY_LINK_CUT = /[*\u3000-\u303F\uFF00-\uFFEF]/;
    md.core.ruler.after('linkify', 'fix_greedy_linkify', function(state) {
        for (var b = 0; b < state.tokens.length; b++) {
            var blk = state.tokens[b];
            if (blk.type !== 'inline' || !blk.children) continue;
            var ch = blk.children;
            for (var i = 0; i < ch.length; i++) {
                var open = ch[i];
                if (open.type !== 'link_open' || open.markup !== 'linkify') continue;
                var textTok = ch[i + 1], close = ch[i + 2];
                if (!textTok || textTok.type !== 'text' || !close || close.type !== 'link_close') continue;
                var idx = textTok.content.search(GREEDY_LINK_CUT);
                if (idx < 0) continue;
                var keep = textTok.content.slice(0, idx);
                var spill = textTok.content.slice(idx);
                textTok.content = keep;
                open.attrSet('href', keep);
                var spillTok = new state.Token('text', '', 0);
                spillTok.content = spill;
                ch.splice(i + 3, 0, spillTok);
            }
        }
    });
    const defaultLinkOpen = md.renderer.rules.link_open || function(tokens, idx, options, env, self) {
        return self.renderToken(tokens, idx, options);
    };
    md.renderer.rules.link_open = function(tokens, idx, options, env, self) {
        const token = tokens[idx];
        // A workspace-relative href would resolve against the console URL and
        // 404 in a new tab. Tag it instead so the click handler in
        // workspace.js opens it in the preview panel.
        const wsPath = typeof wsWorkspaceHref === 'function'
            ? wsWorkspaceHref(token.attrGet('href') || '') : null;
        if (wsPath) {
            token.attrPush(['data-ws-path', wsPath]);
            token.attrJoin('class', 'ws-link');
        } else {
            token.attrPush(['target', '_blank']);
            token.attrPush(['rel', 'noopener noreferrer']);
        }
        return defaultLinkOpen(tokens, idx, options, env, self);
    };
    // A table can't shrink below its columns' minimum content width, so a wide
    // comparison table would run past the bubble. Wrap it in a scroller: it
    // still fills the bubble when it fits and scrolls sideways when it doesn't.
    const defaultTableOpen = md.renderer.rules.table_open || function(tokens, idx, options, env, self) {
        return self.renderToken(tokens, idx, options);
    };
    const defaultTableClose = md.renderer.rules.table_close || function(tokens, idx, options, env, self) {
        return self.renderToken(tokens, idx, options);
    };
    md.renderer.rules.table_open = function(tokens, idx, options, env, self) {
        return '<div class="table-wrap">' + defaultTableOpen(tokens, idx, options, env, self);
    };
    md.renderer.rules.table_close = function(tokens, idx, options, env, self) {
        return defaultTableClose(tokens, idx, options, env, self) + '</div>';
    };
    // A closed ```mermaid fence becomes a placeholder. The SVG is drawn later,
    // after the node is in the document. An unclosed tail stays a code block so
    // streaming does not redraw a half-written diagram on every token.
    const defaultFence = md.renderer.rules.fence || function(tokens, idx, options, env, self) {
        return self.renderToken(tokens, idx, options);
    };
    md.renderer.rules.fence = function(tokens, idx, options, env, self) {
        const token = tokens[idx];
        const lang = (typeof mermaidFenceLang === 'function') ? mermaidFenceLang(token.info) : '';
        const openTail = lang === 'mermaid' && typeof mermaidFenceIsOpenTail === 'function'
            && mermaidFenceIsOpenTail(tokens, idx, !!(env && env.openMermaid));
        if (lang === 'mermaid' && !openTail) return buildMermaidBlockHtml(token.content || '');
        return defaultFence(tokens, idx, options, env, self);
    };
    return md;
}

const md = createMd();

const VIDEO_EXT_RE = /\.(?:mp4|webm|mov|avi|mkv)$/i;  // tested against URL without query string
const IMAGE_EXT_RE = /\.(?:jpg|jpeg|png|gif|webp|bmp|svg)$/i;  // tested against URL without query string

// Windows absolute path (D:\x.png / D:/x.png).
const WIN_ABS_PATH_RE = /^[A-Za-z]:[\\/]/;

function _toWebUrl(url) {
    if ((/^\/[A-Za-z]/.test(url) || WIN_ABS_PATH_RE.test(url)) && !url.startsWith('/api/')) {
        return '/api/file?path=' + encodeURIComponent(url);
    }
    if (/^file:\/\/\//i.test(url)) {
        // file:///home/x → /home/x, but file:///D:/x stays drive-relative.
        const p = url.replace(/^file:\/\/\//i, '');
        return '/api/file?path=' + encodeURIComponent(WIN_ABS_PATH_RE.test(p) ? p : '/' + p);
    }
    return url;
}

function _buildVideoHtml(url) {
    const webUrl = _toWebUrl(url);
    const fileName = url.split('/').pop().split('?')[0];
    return `<div style="margin:10px 0;">` +
        `<video controls preload="metadata" ` +
        `style="max-width:100%;border-radius:10px;box-shadow:0 2px 8px rgba(0,0,0,0.15);display:block;">` +
        `<source src="${webUrl}"></video>` +
        `<a href="${webUrl}" target="_blank" ` +
        `style="display:inline-flex;align-items:center;gap:4px;margin-top:4px;font-size:12px;color:#8b8fa8;text-decoration:none;">` +
        `<i class="fas fa-download"></i> ${escapeHtml(fileName)}</a></div>`;
}

function _openImageLightbox(src) {
    let overlay = document.getElementById('cow-lightbox');
    if (!overlay) {
        overlay = document.createElement('div');
        overlay.id = 'cow-lightbox';
        overlay.style.cssText = 'position:fixed;inset:0;z-index:9999;background:rgba(0,0,0,0.85);display:flex;align-items:center;justify-content:center;cursor:zoom-out;opacity:0;transition:opacity .2s';
        overlay.onclick = () => { overlay.style.opacity = '0'; setTimeout(() => overlay.style.display = 'none', 200); };
        const img = document.createElement('img');
        img.id = 'cow-lightbox-img';
        img.style.cssText = 'max-width:92vw;max-height:92vh;border-radius:8px;box-shadow:0 4px 24px rgba(0,0,0,0.5);object-fit:contain;';
        img.onclick = (e) => e.stopPropagation();
        overlay.appendChild(img);
        document.body.appendChild(overlay);
    }
    overlay.querySelector('#cow-lightbox-img').src = src;
    overlay.style.display = 'flex';
    requestAnimationFrame(() => overlay.style.opacity = '1');
}

function _buildImageHtml(url) {
    const webUrl = _toWebUrl(url);
    const safeUrl = webUrl.replace(/"/g, '&quot;');
    return `<div style="margin:10px 0;">` +
        `<img src="${safeUrl}" alt="image" loading="lazy" ` +
        `onclick="_openImageLightbox(this.src)" ` +
        `style="max-width:520px;width:100%;border-radius:10px;box-shadow:0 2px 8px rgba(0,0,0,0.15);display:block;cursor:zoom-in;">` +
        `</div>`;
}

function injectVideoPlayers(html) {
    // Step 1: replace markdown-it anchor tags whose href points to a video file.
    const step1 = html.replace(
        /<a\s+href="(https?:\/\/[^"]+)"[^>]*>[^<]*<\/a>/gi,
        (match, url) => VIDEO_EXT_RE.test(url.split('?')[0]) ? _buildVideoHtml(url) : match
    );
    // Step 2: replace any remaining bare video URLs in text nodes (not inside HTML tags).
    // Split on HTML tags to avoid touching src/href attributes already in markup.
    return step1.split(/(<[^>]+>)/).map((chunk, idx) => {
        // Even indices are text nodes; odd indices are HTML tags — leave them untouched.
        if (idx % 2 !== 0) return chunk;
        return chunk.replace(/https?:\/\/\S+/gi, (url) => {
            const bare = url.replace(/[),.\s]+$/, '');  // strip trailing punctuation
            return VIDEO_EXT_RE.test(bare.split('?')[0]) ? _buildVideoHtml(bare) : url;
        });
    }).join('');
}

// Convert image URLs into inline <img> previews. Mirrors injectVideoPlayers but for images.
// Handles three cases produced by markdown-it:
//   1. <a href="...image.jpg">...</a>  (bare URL or autolink that linkify turned into an anchor)
//   2. <img src="...">                  (markdown image syntax) — leave as-is, but normalize style
//   3. raw URL still present in a text node                    — only as a safety net
function injectImagePreviews(html) {
    // Step 1: anchor whose href points to an image file -> replace with <img> preview.
    const step1 = html.replace(
        /<a\s+href="(https?:\/\/[^"]+)"[^>]*>[^<]*<\/a>/gi,
        (match, url) => IMAGE_EXT_RE.test(url.split('?')[0]) ? _buildImageHtml(url) : match
    );
    // Step 2: bare image URLs left in text nodes (rare — markdown-it's linkify usually catches them).
    return step1.split(/(<[^>]+>)/).map((chunk, idx) => {
        if (idx % 2 !== 0) return chunk;
        return chunk.replace(/https?:\/\/\S+/gi, (url) => {
            const bare = url.replace(/[),.\s]+$/, '');
            return IMAGE_EXT_RE.test(bare.split('?')[0]) ? _buildImageHtml(bare) : url;
        });
    }).join('');
}

function _rewriteLocalImgSrc(html) {
    return html.replace(/<img\s([^>]*?)src="([^"]+)"([^>]*?)>/gi, (match, pre, src, post) => {
        const webSrc = _toWebUrl(src);
        const safeSrc = webSrc.replace(/"/g, '&quot;');
        const hasClick = /onclick/i.test(pre + post);
        const clickAttr = hasClick ? '' : ` onclick="_openImageLightbox(this.src)" style="cursor:zoom-in;"`;
        return `<img ${pre}src="${safeSrc}"${post}${clickAttr}>`;
    });
}

function renderMarkdown(text) {
    try {
        const open = (typeof mermaidOpenFenceAtEof === 'function') ? mermaidOpenFenceAtEof(text) : null;
        let html = md.render(text, { openMermaid: !!(open && open.lang === 'mermaid') });
        html = _rewriteLocalImgSrc(html);
        // Order matters: video first (more specific), then image.
        html = injectImagePreviews(injectVideoPlayers(html));
        // Fallback for files the agent only mentions by path (workspace.js).
        if (typeof injectFileChips === 'function') html = injectFileChips(html);
        // Note: Code block headers are added via DOM manipulation after insertion
        // See addCodeBlockHeadersToElement()
        // Closed fences are placeholders until the node is in the document. The
        // streaming answer still carries .sse-streaming, so this pass only draws
        // diagrams that will not be rewritten on the next token.
        if (html.indexOf('mermaid-block') !== -1) scheduleMermaidMount(0);
        return html;
    }
    catch (e) { return text.replace(/\n/g, '<br>'); }
}

function _addCodeBlockHeaders(container) {
    // Add header with language label and copy button to each <pre> block using DOM manipulation
    const preBlocks = container.querySelectorAll('pre');
    preBlocks.forEach(pre => {
        if (pre.parentElement && pre.parentElement.classList.contains('code-block-wrapper')) return;
        
        const codeEl = pre.querySelector('code');
        if (!codeEl) return;
        
        const langClass = Array.from(codeEl.classList).find(c => c.startsWith('language-'));
        const language = langClass ? langClass.replace('language-', '') : '';
        // Hide label for unknown/empty languages (e.g. language-undefined)
        const showLang = language && language !== 'undefined' && language !== 'code';
        const langLabel = showLang ? language.charAt(0).toUpperCase() + language.slice(1) : '';
        
        const wrapper = document.createElement('div');
        wrapper.className = 'code-block-wrapper';
        
        const header = document.createElement('div');
        header.className = 'code-block-header';
        header.innerHTML = `
            <span class="code-block-lang">${langLabel}</span>
            <button class="code-copy-btn" title="Copy code">
                <i class="fas fa-copy"></i>
            </button>
        `;
        
        pre.parentNode.insertBefore(wrapper, pre);
        wrapper.appendChild(header);
        wrapper.appendChild(pre);
    });
}

// ---------------------------------------------------------------------
// Mermaid diagrams. The library is fetched the first time a closed fence
// is on the page; plain conversations never download it. securityLevel
// strict refuses HTML and javascript click callbacks. A click URL is still
// emitted as <a href>, so those hrefs are removed after the SVG is inserted.
// ---------------------------------------------------------------------

let _mermaidPromise = null;
let _mermaidTimer = 0;
let _mermaidChain = Promise.resolve();
let _mermaidSeq = 0;
let _mermaidEpoch = 0;

function mermaidThemeName() {
    return document.documentElement.classList.contains('dark') ? 'dark' : 'default';
}

function configureMermaid(api, theme) {
    api.initialize({
        startOnLoad: false,
        securityLevel: 'strict',
        theme: theme,
        suppressErrorRendering: true,
        fontFamily: 'ui-sans-serif, system-ui, sans-serif',
    });
}

function ensureMermaid() {
    if (window.mermaid && typeof window.mermaid.render === 'function') {
        return Promise.resolve(window.mermaid);
    }
    if (_mermaidPromise) return _mermaidPromise;
    _mermaidPromise = new Promise((resolve, reject) => {
        const script = document.createElement('script');
        script.src = '/assets/vendor/mermaid/mermaid.min.js';
        script.async = true;
        script.onload = () => {
            if (window.mermaid && typeof window.mermaid.render === 'function') resolve(window.mermaid);
            else reject(new Error('mermaid did not load'));
        };
        script.onerror = () => reject(new Error('mermaid failed to load'));
        document.head.appendChild(script);
    });
    // Keep the rejection so a missing file is not requested again on every token.
    _mermaidPromise.catch(() => {});
    return _mermaidPromise;
}

function scheduleMermaidMount(delay) {
    if (typeof document === 'undefined' || typeof document.createElement !== 'function') return;
    if (_mermaidTimer) clearTimeout(_mermaidTimer);
    _mermaidTimer = setTimeout(() => {
        _mermaidTimer = 0;
        mountMermaidDiagrams();
    }, delay);
}

function fitMermaidSvg(host) {
    const svg = host.querySelector('svg');
    if (!svg) return;
    let width = 0;
    let height = 0;
    const box = svg.viewBox && svg.viewBox.baseVal;
    if (box && box.width) {
        width = box.width;
        height = box.height;
    } else {
        const raw = svg.getAttribute('viewBox') || '';
        const parts = raw.trim().split(/[\s,]+/).map(Number);
        if (parts.length === 4 && parts[2] > 0) {
            width = parts[2];
            height = parts[3];
        }
    }
    if (!width) return;
    svg.setAttribute('width', String(Math.ceil(width)));
    if (height) svg.setAttribute('height', String(Math.ceil(height)));
    svg.style.maxWidth = 'none';
    svg.style.height = 'auto';
}

// Mermaid hangs the node transform on the <a>, so the element stays.
// href / xlink:href are what would navigate this page or the Electron window.
function stripMermaidAnchorHrefs(host) {
    if (!host || typeof host.querySelectorAll !== 'function') return;
    const anchors = host.querySelectorAll('a');
    for (let i = 0; i < anchors.length; i++) {
        const anchor = anchors[i];
        anchor.removeAttribute('href');
        anchor.removeAttribute('xlink:href');
        if (typeof anchor.removeAttributeNS === 'function') {
            anchor.removeAttributeNS('http://www.w3.org/1999/xlink', 'href');
        }
    }
}

function markMermaidFallback(block) {
    if (!block || !block.isConnected) return;
    const diagram = block.querySelector('.mermaid-diagram');
    if (diagram) {
        diagram.innerHTML = '';
        diagram.hidden = true;
    }
    const pre = block.querySelector('pre');
    if (pre) pre.hidden = false;
    block.dataset.mermaidDone = '1';
    block.dataset.mermaidError = '1';
}

function mermaidBlockStale(block, token, epoch) {
    return _mermaidEpoch !== epoch || block.dataset.mermaidToken !== token || !block.isConnected;
}

async function renderMermaidBlock(api, block) {
    if (!block.isConnected || block.dataset.mermaidDone === '1') return;
    if (block.closest('.sse-streaming')) return;
    const codeEl = block.querySelector('pre code');
    const source = codeEl ? (codeEl.textContent || '') : '';
    const token = String(++_mermaidSeq);
    const epoch = _mermaidEpoch;
    block.dataset.mermaidToken = token;
    if (!source.trim()) {
        markMermaidFallback(block);
        return;
    }
    const id = 'cowmermaid' + token;
    try {
        const theme = mermaidThemeName();
        configureMermaid(api, theme);
        if (typeof api.parse === 'function') {
            const parsed = await api.parse(source, { suppressErrors: true });
            if (parsed === false) throw new Error('mermaid parse failed');
        }
        if (mermaidBlockStale(block, token, epoch)) return;
        const rendered = await api.render(id, source);
        if (mermaidBlockStale(block, token, epoch)) return;
        const svg = rendered && rendered.svg;
        if (!svg || svg.indexOf('<svg') === -1) throw new Error('mermaid returned no svg');
        const diagram = block.querySelector('.mermaid-diagram');
        const pre = block.querySelector('pre');
        if (!diagram) throw new Error('mermaid host missing');
        diagram.innerHTML = svg;
        stripMermaidAnchorHrefs(diagram);
        fitMermaidSvg(diagram);
        diagram.hidden = false;
        if (pre) pre.hidden = true;
        block.dataset.mermaidDone = '1';
        block.dataset.mermaidTheme = theme;
        delete block.dataset.mermaidError;
    } catch (err) {
        if (mermaidBlockStale(block, token, epoch)) return;
        markMermaidFallback(block);
    } finally {
        const leftover = document.getElementById(id);
        if (leftover && !block.contains(leftover)) leftover.remove();
    }
}

function mountMermaidDiagrams() {
    const run = _mermaidChain.then(() => mountMermaidDiagramsNow());
    _mermaidChain = run.catch(() => {});
    return run;
}

async function mountMermaidDiagramsNow() {
    if (typeof document === 'undefined' || typeof document.querySelectorAll !== 'function') return;
    const pending = document.querySelector('.mermaid-block:not([data-mermaid-done])');
    if (!pending) return;
    let ready = false;
    document.querySelectorAll('.mermaid-block:not([data-mermaid-done])').forEach(block => {
        if (!block.closest('.sse-streaming')) ready = true;
    });
    if (!ready) {
        ensureMermaid().catch(() => {});
        return;
    }
    let api;
    try {
        api = await ensureMermaid();
    } catch (err) {
        document.querySelectorAll('.mermaid-block:not([data-mermaid-done])').forEach(block => {
            if (!block.closest('.sse-streaming')) markMermaidFallback(block);
        });
        return;
    }
    const blocks = Array.prototype.slice.call(
        document.querySelectorAll('.mermaid-block:not([data-mermaid-done])')
    );
    for (let i = 0; i < blocks.length; i++) {
        await renderMermaidBlock(api, blocks[i]);
    }
}

// Theme toggles swap the hljs stylesheet in theme.js, then call this so
// diagrams already on screen pick up the light or dark palette.
function rerenderMermaidForTheme() {
    if (typeof document === 'undefined') return;
    const theme = mermaidThemeName();
    _mermaidEpoch++;
    let pending = false;
    document.querySelectorAll('.mermaid-block[data-mermaid-done]').forEach(block => {
        if (block.dataset.mermaidError === '1') return;
        if (block.dataset.mermaidTheme === theme) return;
        delete block.dataset.mermaidDone;
        const diagram = block.querySelector('.mermaid-diagram');
        if (diagram) {
            diagram.innerHTML = '';
            diagram.hidden = true;
        }
        const pre = block.querySelector('pre');
        if (pre) pre.hidden = false;
        pending = true;
    });
    if (pending) scheduleMermaidMount(0);
}

// Chat bubbles copy through the listener in chat/state.js. The same button
// in the knowledge, memory and skill viewers has no other handler.
if (typeof document !== 'undefined' && document.addEventListener) document.addEventListener('click', (e) => {
    const btn = e.target && e.target.closest && e.target.closest('.mermaid-block .code-copy-btn');
    if (!btn || btn.closest('#chat-messages')) return;
    const codeEl = btn.closest('.mermaid-block').querySelector('pre code');
    if (!codeEl || typeof copyToClipboard !== 'function') return;
    e.preventDefault();
    copyToClipboard(codeEl.textContent || '').then(() => {
        const icon = btn.querySelector('i');
        if (!icon) return;
        icon.className = 'fas fa-check';
        setTimeout(() => { icon.className = 'fas fa-copy'; }, 1500);
    });
});

