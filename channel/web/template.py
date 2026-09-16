"""Server-side assembly for the console's HTML shell.

The console page used to be one 2k-line ``chat.html``. It is now a thin shell
that pulls in fragments from ``templates/`` via ``<!--#include path-->``
markers, assembled here before the response is written. Assembly happens on
the server on purpose: the page relies on the Tailwind CDN's JIT compiler,
which is far more predictable when the whole DOM is present at parse time than
when views are injected later by script.

The bytes the browser receives are identical to the pre-split page, so the
split is invisible to the frontend.
"""

import os
import re
from typing import Dict, Tuple

# ``<!--#include templates/views/chat.html-->``. Whitespace around the path is
# tolerated so the markers can be indented to match surrounding markup.
_INCLUDE_RE = re.compile(r'<!--#include\s+([^\s>]+?)\s*-->')

# First-party scripts and stylesheets, which live under assets/js and
# assets/css. Vendored copies sit in assets/vendor and are deliberately left
# alone: they are pinned, so a version query would only waste cache entries.
_FIRST_PARTY = r'(?:js|css)/[A-Za-z0-9_\-./]+\.(?:js|css)'
_ASSET_RE = re.compile(r'assets/(%s)' % _FIRST_PARTY)
_FIRST_PARTY_RE = re.compile(r'%s$' % _FIRST_PARTY)

# An include that resolves back to an ancestor would loop forever. Fragments
# nest at most two deep today (shell -> view -> shared row), so this is a
# generous ceiling that still fails fast on a cycle.
_MAX_INCLUDE_DEPTH = 8

_WEB_DIR = os.path.dirname(os.path.abspath(__file__))
_STATIC_DIR = os.path.join(_WEB_DIR, 'static')

# path -> (mtime, text). Keyed on mtime so an edit is picked up on the next
# request without a restart, while a steady-state page load stays at one stat()
# per fragment instead of a full read.
_cache: Dict[str, Tuple[float, str]] = {}


def _read(rel_path: str) -> str:
    full_path = os.path.normpath(os.path.join(_WEB_DIR, rel_path))
    if not full_path.startswith(_WEB_DIR + os.sep):
        raise ValueError(f"include escapes the web directory: {rel_path}")

    mtime = os.path.getmtime(full_path)
    cached = _cache.get(full_path)
    if cached and cached[0] == mtime:
        return cached[1]

    with open(full_path, 'r', encoding='utf-8') as f:
        text = f.read()
    _cache[full_path] = (mtime, text)
    return text


def _expand(text: str, depth: int) -> str:
    if depth > _MAX_INCLUDE_DEPTH:
        raise ValueError("include nesting too deep; check for a cycle")

    def substitute(match):
        fragment = _expand(_read(match.group(1)), depth + 1)
        # A marker sits alone on its line and keeps its own newline, so the
        # fragment's trailing one would add a blank line. Drop exactly one, so
        # fragments can end with a newline like any other file without the
        # assembled page drifting from what it was before the split.
        if fragment.endswith('\n'):
            fragment = fragment[:-1]
        return fragment

    return _INCLUDE_RE.sub(substitute, text)


def is_versioned(asset_path: str) -> bool:
    """Whether ``render`` stamps this asset with its own mtime.

    Only first-party scripts and stylesheets are stamped, which is what makes
    their URLs content-addressed: the file cannot change without the URL
    changing with it. The asset handler consults this before promising a
    browser that a response is safe to keep, since nothing else under static/
    -- vendored bundles, fonts, logos -- carries that guarantee.
    """
    return bool(_FIRST_PARTY_RE.match(asset_path))


def asset_version(asset_path: str) -> str:
    """A stamp for one asset, derived from its last modification time.

    Milliseconds rather than seconds so two edits within the same second still
    produce different stamps, which matters while developing: an edit that did
    not move the stamp would be served from cache and look like it had no
    effect. An asset that cannot be stat'd gets no stamp instead of raising,
    so one stale reference cannot turn the whole console into a 500; the asset
    tests catch the missing file directly.
    """
    full_path = os.path.normpath(os.path.join(_STATIC_DIR, asset_path))
    if not full_path.startswith(_STATIC_DIR + os.sep):
        return ''
    try:
        return format(int(os.path.getmtime(full_path) * 1000), 'x')
    except OSError:
        return ''


def render(rel_path: str) -> str:
    """Assemble ``rel_path`` and stamp a version onto its first-party assets.

    The stamp guards against a browser running an upgraded console's markup
    against cached copies of the old scripts. Every first-party asset is
    stamped, including ones referenced from included fragments, so adding a
    script no longer means remembering to extend a hardcoded list.

    Each asset carries its own mtime rather than one stamp shared by the whole
    page. A shared wall-clock stamp changed on every request, so all 46 assets
    were re-downloaded on every reload; per-file stamps hold still until the
    file behind them actually changes, and then move only for that one file.
    """
    html = _expand(_read(rel_path), 0)

    def stamp(match):
        version = asset_version(match.group(1))
        if not version:
            return match.group(0)
        return 'assets/%s?v=%s' % (match.group(1), version)

    return _ASSET_RE.sub(stamp, html)
